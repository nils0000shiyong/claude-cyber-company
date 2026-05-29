import json
import logging
import os
import queue
import re
import shutil
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path

import lark_oapi as lark
from lark_oapi.api.im.v1 import (
    CreateMessageRequest,
    CreateMessageRequestBody,
    ReplyMessageRequest,
    ReplyMessageRequestBody,
)
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(threadName)s] %(message)s",
)
log = logging.getLogger(__name__)

APP_ID = os.environ["FEISHU_APP_ID"]
APP_SECRET = os.environ["FEISHU_APP_SECRET"]
WORK_DIR = os.getenv(
    "AGENT_WORK_DIR",
    str(Path(__file__).resolve().parents[1]),
)
AGENT_ENGINE = os.getenv("FEISHU_AGENT_ENGINE", "claude").strip().lower()
AGENT_TIMEOUT = int(os.getenv("AGENT_TIMEOUT", "300"))
AGENT_ALLOW_UNSAFE_PERMISSIONS = (
    os.getenv("AGENT_ALLOW_UNSAFE_PERMISSIONS", "false").strip().lower()
    in {"1", "true", "yes", "on"}
)
CLAUDE_COMMAND = os.getenv("CLAUDE_COMMAND") or shutil.which("claude") or str(
    Path.home() / ".local" / "bin" / "claude"
)
CODEX_COMMAND = os.getenv("CODEX_COMMAND", "codex")
CODEX_SANDBOX = os.getenv("CODEX_SANDBOX", "workspace-write")
CODEX_APPROVAL_POLICY = os.getenv("CODEX_APPROVAL_POLICY", "never")

if AGENT_ENGINE not in {"claude", "codex"}:
    raise RuntimeError("FEISHU_AGENT_ENGINE must be 'claude' or 'codex'")

# Session config
SESSION_RECENT_PAIRS = int(os.getenv("SESSION_RECENT_PAIRS", "5"))
SESSION_COMPRESS_TRIGGER = int(os.getenv("SESSION_COMPRESS_TRIGGER", "8"))
SESSION_IDLE_TIMEOUT_HOURS = int(os.getenv("SESSION_IDLE_TIMEOUT_HOURS", "24"))
SESSION_DIR = Path(WORK_DIR) / "memory" / "sessions"

# Group chat & access control
MESSAGE_STALENESS_SECONDS = int(os.getenv("MESSAGE_STALENESS_SECONDS", "120"))

FEISHU_OWNER_OPEN_IDS = {s.strip() for s in os.getenv("FEISHU_OWNER_OPEN_IDS", "").split(",") if s.strip()}
FEISHU_ALLOWED_OPEN_IDS = {s.strip() for s in os.getenv("FEISHU_ALLOWED_OPEN_IDS", "").split(",") if s.strip()}
FEISHU_REJECT_MODE = os.getenv("FEISHU_REJECT_MODE", "silent").strip().lower()

lark_client = lark.Client.builder().app_id(APP_ID).app_secret(APP_SECRET).build()

_dedup_lock = threading.Lock()
_dedup_seen: dict[str, datetime] = {}
_DEDUP_TTL = timedelta(minutes=10)

_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="agent")

# ── Per-chat serial queue ─────────────────────────────────────────────────────

_chat_queues: dict[str, queue.Queue] = {}
_chat_queues_lock = threading.Lock()
_chat_workers: set[str] = set()


def _get_chat_queue(chat_id: str) -> queue.Queue:
    with _chat_queues_lock:
        if chat_id not in _chat_queues:
            _chat_queues[chat_id] = queue.Queue()
        return _chat_queues[chat_id]


def _chat_worker(chat_id: str) -> None:
    """Drain the queue for a single chat_id, processing messages one by one."""
    q = _get_chat_queue(chat_id)
    try:
        while True:
            try:
                task = q.get_nowait()
            except queue.Empty:
                break
            try:
                _process_message(**task)
            except Exception as e:
                log.error("chat worker error for %s: %s", chat_id, e)
            finally:
                q.task_done()
    finally:
        with _chat_queues_lock:
            _chat_workers.discard(chat_id)
            if not q.empty():
                _chat_workers.add(chat_id)
                _executor.submit(_chat_worker, chat_id)


def _enqueue_message(**kwargs) -> None:
    """Enqueue a message for serial processing within its chat."""
    chat_id = kwargs["chat_id"]
    q = _get_chat_queue(chat_id)
    q.put(kwargs)
    with _chat_queues_lock:
        if chat_id not in _chat_workers:
            _chat_workers.add(chat_id)
            _executor.submit(_chat_worker, chat_id)


def _is_message_stale(message) -> bool:
    """Check if a message is too old to process (e.g., after WS reconnect)."""
    if MESSAGE_STALENESS_SECONDS <= 0:
        return False
    create_time = getattr(message, 'create_time', None)
    if not create_time:
        return False
    try:
        create_ts = int(create_time) / 1000.0
        age = datetime.now().timestamp() - create_ts
        return age > MESSAGE_STALENESS_SECONDS
    except (ValueError, TypeError):
        return False


# ── Access control helpers ────────────────────────────────────────────────────

def _strip_mentions(text: str, mentions) -> str:
    """Remove all @mention placeholder keys from message text."""
    if not mentions:
        return text
    for mention in mentions:
        key = getattr(mention, 'key', None)
        if key:
            text = text.replace(key, "")
    return re.sub(r'\s+', ' ', text).strip()


def _check_sender_authorized(sender_open_id: str) -> str | None:
    """
    Check if sender is in the whitelist.
    Returns role: "owner" / "member" / None (unauthorized).
    If both whitelist sets are empty, returns "owner" (backward compatible).
    """
    if not FEISHU_OWNER_OPEN_IDS and not FEISHU_ALLOWED_OPEN_IDS:
        return "owner"  # backward compatible: no whitelist = allow all as owner
    if sender_open_id in FEISHU_OWNER_OPEN_IDS:
        return "owner"
    if sender_open_id in FEISHU_ALLOWED_OPEN_IDS:
        return "member"
    return None


def _make_sender_label(role: str, sender_open_id: str) -> str:
    """Generate a human-readable sender label for session history and prompts."""
    if role == "owner":
        return "董事长"
    suffix = sender_open_id[-6:] if len(sender_open_id) >= 6 else sender_open_id
    return f"成员-{suffix}"


# ── Dedup ─────────────────────────────────────────────────────────────────────

def is_duplicate(message_id: str) -> bool:
    now = datetime.now()
    with _dedup_lock:
        expired = [k for k, v in _dedup_seen.items() if now - v > _DEDUP_TTL]
        for k in expired:
            del _dedup_seen[k]
        if message_id in _dedup_seen:
            return True
        _dedup_seen[message_id] = now
        return False


# ── Session manager ────────────────────────────────────────────────────────────

class SessionManager:
    """
    Per-chat conversation history with auto-compression.

    Session file: memory/sessions/{safe_chat_id}.json
    Format:
        {
            "summary": "...",          # compressed older history (≤300 chars)
            "recent": [                # verbatim recent rounds
                {
                    "role": "user"|"bot",
                    "content": "...",
                    "timestamp": "...",
                    "sender_id": "...",      # open_id of sender (P0-4)
                    "sender_label": "..."    # human-readable label (P0-4)
                }
            ]
        }

    When recent rounds exceed SESSION_COMPRESS_TRIGGER, the oldest rounds
    are compressed into the rolling summary via a short claude call.
    """

    def __init__(self, sessions_dir: Path, recent_pairs: int, compress_trigger: int, idle_timeout_hours: int = 24):
        self.sessions_dir = sessions_dir
        self.recent_pairs = recent_pairs
        self.compress_trigger = compress_trigger
        self.idle_timeout_hours = idle_timeout_hours
        sessions_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, chat_id: str) -> Path:
        safe = chat_id.replace("/", "_").replace("\\", "_").replace(":", "_")
        return self.sessions_dir / f"{safe}.json"

    def _load_raw(self, chat_id: str) -> dict:
        path = self._path(chat_id)
        if not path.exists():
            return {"summary": "", "recent": []}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {"summary": "", "recent": []}

    def _save_raw(self, chat_id: str, data: dict) -> None:
        path = self._path(chat_id)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def _is_idle(self, data: dict) -> bool:
        if self.idle_timeout_hours <= 0:
            return False
        recent = data.get("recent", [])
        if not recent:
            return False
        last_ts = recent[-1].get("timestamp", "")
        if not last_ts:
            return False
        try:
            last_time = datetime.fromisoformat(last_ts)
            return datetime.now() - last_time > timedelta(hours=self.idle_timeout_hours)
        except ValueError:
            return False

    def _archive(self, chat_id: str) -> None:
        path = self._path(chat_id)
        if not path.exists():
            return
        date_str = datetime.now().strftime("%Y%m%d")
        safe = chat_id.replace("/", "_").replace("\\", "_").replace(":", "_")
        archive_path = self.sessions_dir / f"{safe}_{date_str}.json"
        # avoid overwriting an existing archive from the same day
        suffix = 0
        while archive_path.exists():
            suffix += 1
            archive_path = self.sessions_dir / f"{safe}_{date_str}_{suffix}.json"
        path.rename(archive_path)
        log.info("session %s archived to %s (idle timeout)", chat_id, archive_path.name)

    def format_for_prompt(self, chat_id: str) -> str:
        data = self._load_raw(chat_id)
        if self._is_idle(data):
            self._archive(chat_id)
            return ""
        parts: list[str] = []
        if data.get("summary"):
            parts.append(f"[历史摘要]\n{data['summary']}")
        recent = data.get("recent", [])
        if recent:
            lines = ["[近期对话]"]
            for msg in recent:
                # P0-4: use sender_label if available, fallback to legacy behavior
                label = msg.get("sender_label", "董事长" if msg["role"] == "user" else "Elon")
                lines.append(f"{label}: {msg['content']}")
            parts.append("\n".join(lines))
        return "\n\n".join(parts) if parts else ""

    def save_exchange(self, chat_id: str, user_text: str, bot_reply: str,
                      sender_id: str = "", sender_label: str = "董事长") -> None:
        data = self._load_raw(chat_id)
        if self._is_idle(data):
            self._archive(chat_id)
            data = {"summary": "", "recent": []}
        now = datetime.now().isoformat()
        data["recent"].append({
            "role": "user", "content": user_text, "timestamp": now,
            "sender_id": sender_id, "sender_label": sender_label,
        })
        data["recent"].append({
            "role": "bot", "content": bot_reply, "timestamp": now,
            "sender_id": "", "sender_label": "Elon",
        })

        if len(data["recent"]) > self.compress_trigger * 2:
            keep = self.recent_pairs * 2
            to_compress = data["recent"][:-keep]
            data["recent"] = data["recent"][-keep:]
            self._save_raw(chat_id, data)
            self._compress(chat_id, to_compress, data.get("summary", ""))
        else:
            self._save_raw(chat_id, data)

    def _compress(self, chat_id: str, old_msgs: list, existing_summary: str) -> None:
        history_lines = []
        for msg in old_msgs:
            # P0-4: use sender_label if available, fallback to legacy behavior
            label = msg.get("sender_label", "董事长" if msg["role"] == "user" else "Elon")
            history_lines.append(f"{label}: {msg['content']}")
        history_text = "\n".join(history_lines)

        existing_part = f"已有摘要：\n{existing_summary}\n\n" if existing_summary else ""
        prompt = (
            f"请将以下对话内容压缩为简洁摘要（不超过300字），"
            f"保留关键决策、任务状态和重要上下文。\n\n"
            f"{existing_part}"
            f"需要压缩的对话：\n{history_text}\n\n"
            f"直接输出摘要文本，不要加任何前缀或解释。"
        )
        try:
            result = subprocess.run(
                [CLAUDE_COMMAND, "-p", prompt],
                cwd=WORK_DIR,
                capture_output=True,
                text=True,
                timeout=60,
            )
            if result.returncode == 0 and result.stdout.strip():
                data = self._load_raw(chat_id)
                data["summary"] = result.stdout.strip()
                self._save_raw(chat_id, data)
                log.info("session %s compressed", chat_id)
            else:
                log.warning("compression failed for %s (rc=%s)", chat_id, result.returncode)
        except Exception as e:
            log.warning("compression error for %s: %s", chat_id, e)


session_mgr = SessionManager(SESSION_DIR, SESSION_RECENT_PAIRS, SESSION_COMPRESS_TRIGGER, SESSION_IDLE_TIMEOUT_HOURS)


# ── Agent ──────────────────────────────────────────────────────────────────────

def build_agent_prompt(user_text: str, history_text: str = "", sender_label: str = "董事长") -> str:
    history_section = f"{history_text}\n\n" if history_text else ""
    return (
        "你正在通过飞书机器人接收董事长的任务。\n\n"
        "请严格遵守当前项目的Claude/Codex隔离与共享记忆协议:\n"
        "- 如果你是Claude,只把CLAUDE.md和.claude/agents/作为平台私有agent定义。\n"
        "- 如果你是Codex,只把AGENTS.md和.codex/agents/作为平台私有agent定义。\n"
        "- 双方只通过memory/和tasks/共享长期信息。\n"
        "- 不要读取对方平台私有agent目录作为运行时上下文,除非董事长明确要求检查配置。\n\n"
        f"{history_section}"
        f"[本次消息]\n{sender_label}: {user_text}"
    )


class AgentError(Exception):
    """Structured agent error with user-facing message and technical detail."""
    def __init__(self, user_msg: str, detail: str = ""):
        self.user_msg = user_msg
        self.detail = detail
        super().__init__(user_msg)


_ERROR_PATTERNS: list[tuple[str, str]] = [
    ("api_key", "后端 API Key 未配置或已失效，请检查 .env 文件中的 ANTHROPIC_API_KEY"),
    ("API key", "后端 API Key 未配置或已失效，请检查 .env 文件中的 ANTHROPIC_API_KEY"),
    ("ANTHROPIC_API_KEY", "后端 API Key 未配置或已失效，请检查 .env 文件中的 ANTHROPIC_API_KEY"),
    ("rate limit", "API 请求超出速率限制，请等待几分钟后重试"),
    ("429", "API 请求超出速率限制，请等待几分钟后重试"),
    ("overloaded", "API 服务端过载，请稍后重试"),
    ("529", "API 服务端过载，请稍后重试"),
    ("No such file or directory", "工作目录或命令路径不存在，请检查 AGENT_WORK_DIR 和 CLAUDE_COMMAND 配置"),
    ("Permission denied", "文件权限不足，请检查 bot 进程对工作目录的读写权限"),
    ("ENOSPC", "服务器磁盘空间不足，请清理磁盘"),
    ("disk quota", "服务器磁盘空间不足，请清理磁盘"),
    ("network", "网络连接异常，请检查服务器的网络和代理配置"),
    ("connection", "网络连接异常，请检查服务器的网络和代理配置"),
    ("Could not connect", "网络连接异常，请检查服务器的网络和代理配置"),
]


def _classify_agent_error(engine: str, returncode: int, stderr: str) -> AgentError:
    stderr_lower = stderr.lower()
    for pattern, user_msg in _ERROR_PATTERNS:
        if pattern.lower() in stderr_lower:
            return AgentError(user_msg, detail=stderr[:500])
    return AgentError(
        f"{engine} 后端异常 (exit code {returncode})，详情请查看服务器日志",
        detail=stderr[:500],
    )


def run_claude(prompt: str) -> str:
    command = [CLAUDE_COMMAND, "-p", prompt]
    if AGENT_ALLOW_UNSAFE_PERMISSIONS:
        command.append("--dangerously-skip-permissions")

    result = subprocess.run(
        command,
        cwd=WORK_DIR,
        capture_output=True,
        text=True,
        timeout=AGENT_TIMEOUT,
    )
    if result.returncode != 0:
        log.error("claude stderr: %s", result.stderr[:500])
        raise _classify_agent_error("claude", result.returncode, result.stderr)
    return result.stdout.strip()


def run_codex(prompt: str) -> str:
    command = [CODEX_COMMAND, "exec", "-C", WORK_DIR]
    if AGENT_ALLOW_UNSAFE_PERMISSIONS:
        command.append("--dangerously-bypass-approvals-and-sandbox")
    else:
        command.extend([
            "--sandbox", CODEX_SANDBOX,
            "--ask-for-approval", CODEX_APPROVAL_POLICY,
        ])
    command.append(prompt)

    result = subprocess.run(
        command,
        cwd=WORK_DIR,
        capture_output=True,
        text=True,
        timeout=AGENT_TIMEOUT,
    )
    if result.returncode != 0:
        log.error("codex stderr: %s", result.stderr[:500])
        raise _classify_agent_error("codex", result.returncode, result.stderr)
    return result.stdout.strip()


def run_agent(user_text: str, history_text: str = "", sender_label: str = "董事长") -> str:
    prompt = build_agent_prompt(user_text, history_text, sender_label)
    if AGENT_ENGINE == "claude":
        return run_claude(prompt)
    return run_codex(prompt)


# ── Feishu messaging ───────────────────────────────────────────────────────────

def reply_message(message_id: str, text: str) -> None:
    request = (
        ReplyMessageRequest.builder()
        .message_id(message_id)
        .request_body(
            ReplyMessageRequestBody.builder()
            .content(json.dumps({"text": text}))
            .msg_type("text")
            .build()
        )
        .build()
    )
    resp = lark_client.im.v1.message.reply(request)
    if not resp.success():
        log.error("reply failed: code=%s msg=%s", resp.code, resp.msg)


def send_message(chat_id: str, text: str) -> None:
    """Send a new message to a chat (not a reply to a specific message)."""
    request = (
        CreateMessageRequest.builder()
        .receive_id_type("chat_id")
        .request_body(
            CreateMessageRequestBody.builder()
            .receive_id(chat_id)
            .content(json.dumps({"text": text}))
            .msg_type("text")
            .build()
        )
        .build()
    )
    resp = lark_client.im.v1.message.create(request)
    if not resp.success():
        log.error("send_message failed: code=%s msg=%s", resp.code, resp.msg)


def send_card(chat_id: str, card: dict) -> None:
    """Send an interactive (v1) card to a chat."""
    request = (
        CreateMessageRequest.builder()
        .receive_id_type("chat_id")
        .request_body(
            CreateMessageRequestBody.builder()
            .receive_id(chat_id)
            .content(json.dumps(card, ensure_ascii=False))
            .msg_type("interactive")
            .build()
        )
        .build()
    )
    resp = lark_client.im.v1.message.create(request)
    if not resp.success():
        log.error("send_card failed: code=%s msg=%s", resp.code, resp.msg)


# ── Message processing ─────────────────────────────────────────────────────────

def _process_message(message_id: str, user_text: str, chat_id: str,
                     sender_id: str = "", sender_label: str = "董事长") -> None:
    try:
        reply_message(message_id, "收到")
    except Exception:
        pass

    history_text = session_mgr.format_for_prompt(chat_id)
    prompt = build_agent_prompt(user_text, history_text, sender_label)

    reply = ""
    try:
        if AGENT_ENGINE == "claude":
            reply = run_claude(prompt)
        else:
            reply = run_codex(prompt)
    except subprocess.TimeoutExpired:
        reply = (
            f"⏱ 任务处理超时（已等待 {AGENT_TIMEOUT} 秒）\n"
            f"建议：将复杂问题拆分成更小的步骤分别提问"
        )
        log.error("%s timeout for %s", AGENT_ENGINE, message_id)
    except AgentError as e:
        reply = f"⚠ {e.user_msg}"
        log.error("%s AgentError for %s: %s | detail: %s", AGENT_ENGINE, message_id, e.user_msg, e.detail)
    except Exception as e:
        reply = f"⚠ 未知错误，请联系管理员查看服务器日志\n错误摘要：{str(e)[:100]}"
        log.error("%s unexpected error for %s: %s", AGENT_ENGINE, message_id, e)

    try:
        send_message(chat_id, reply)
        log.info("result delivered to chat %s for msg %s", chat_id, message_id)
    except Exception as e:
        log.error("send_message error for %s: %s", chat_id, e)
        return

    try:
        session_mgr.save_exchange(chat_id, user_text, reply,
                                  sender_id=sender_id, sender_label=sender_label)
    except Exception as e:
        log.error("session save error for %s: %s", chat_id, e)


def on_message(data: lark.im.v1.P2ImMessageReceiveV1) -> None:
    message = data.event.message if data.event else None
    if not message:
        log.warning("event without message, skipped")
        return

    message_id = message.message_id
    message_type = message.message_type
    chat_id = message.chat_id

    if not message_id:
        log.warning("event without message_id, skipped")
        return

    if not chat_id:
        log.warning("event without chat_id, skipped")
        return

    if is_duplicate(message_id):
        log.info("duplicate %s, skipped", message_id)
        return

    mentions = getattr(message, 'mentions', None)

    # ── P0-3: Sender whitelist check ───────────────────────────────────────
    sender = data.event.sender if data.event else None
    sender_open_id = ""
    if sender and getattr(sender, 'sender_id', None):
        sender_open_id = getattr(sender.sender_id, 'open_id', "") or ""

    if not sender_open_id:
        log.warning("event without sender open_id for %s, skipped", message_id)
        return

    role = _check_sender_authorized(sender_open_id)
    if role is None:
        if FEISHU_REJECT_MODE == "reply":
            _executor.submit(reply_message, message_id, "抱歉，您没有使用权限。")
        else:
            log.info("unauthorized sender %s, skipped", sender_open_id)
        return

    # ── Message type check ─────────────────────────────────────────────────
    if message_type != "text":
        log.info("unsupported message_type: %s (%s)", message_type, message_id)
        _executor.submit(reply_message, message_id, "暂时只支持文本消息。")
        return

    try:
        user_text = json.loads(message.content or "{}").get("text", "").strip()
    except json.JSONDecodeError:
        log.warning("invalid content JSON for %s", message_id)
        return

    # ── P0-2: Strip @mention placeholders from text ────────────────────────
    user_text = _strip_mentions(user_text, mentions)

    if not user_text:
        return

    # ── Stale message filter ──────────────────────────────────────────────
    if _is_message_stale(message):
        age_s = "?"
        try:
            age_s = f"{datetime.now().timestamp() - int(message.create_time) / 1000.0:.0f}"
        except Exception:
            pass
        log.warning("stale message %s (age=%ss), skipped", message_id, age_s)
        _executor.submit(
            reply_message, message_id,
            f"⚠ 该消息已过期（延迟 {age_s} 秒到达），上下文可能不准确，请重新发送指令。"
        )
        return

    # ── P0-4: Generate sender label ────────────────────────────────────────
    sender_label = _make_sender_label(role, sender_open_id)

    log.info("[%s] chat=%s sender=%s(%s) received: %s",
             AGENT_ENGINE, chat_id, sender_label, sender_open_id, user_text[:100])
    _enqueue_message(
        message_id=message_id,
        user_text=user_text,
        chat_id=chat_id,
        sender_id=sender_open_id,
        sender_label=sender_label,
    )


# ── Entry point ────────────────────────────────────────────────────────────────

def main() -> None:
    log.info(
        "starting Feishu WebSocket bot, engine=%s, work_dir=%s, "
        "session_recent=%d, session_compress_trigger=%d, session_idle_timeout_hours=%d",
        AGENT_ENGINE, WORK_DIR, SESSION_RECENT_PAIRS, SESSION_COMPRESS_TRIGGER, SESSION_IDLE_TIMEOUT_HOURS,
    )

    # Access control status
    if not FEISHU_OWNER_OPEN_IDS and not FEISHU_ALLOWED_OPEN_IDS:
        log.warning("白名单未配置 (FEISHU_OWNER_OPEN_IDS / FEISHU_ALLOWED_OPEN_IDS 均为空)，所有用户均可访问")
    else:
        log.info("白名单已配置: owners=%d, allowed=%d, reject_mode=%s",
                 len(FEISHU_OWNER_OPEN_IDS), len(FEISHU_ALLOWED_OPEN_IDS), FEISHU_REJECT_MODE)

    # ── Daily AI hotnews scheduler (optional; controlled by HOTNEWS_CHAT_ID) ──
    try:
        import daily_hotnews
        daily_hotnews.start(send_card=send_card, send_text=send_message)
    except Exception as e:  # noqa: BLE001
        log.warning("daily_hotnews 启动失败,bot 继续运行: %s", e)

    event_handler = (
        lark.EventDispatcherHandler.builder("", "")
        .register_p2_im_message_receive_v1(on_message)
        .build()
    )
    ws_client = lark.ws.Client(
        APP_ID,
        APP_SECRET,
        event_handler=event_handler,
        log_level=lark.LogLevel.INFO,
    )
    ws_client.start()


if __name__ == "__main__":
    main()
