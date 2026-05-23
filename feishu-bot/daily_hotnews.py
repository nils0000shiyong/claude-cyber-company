"""
每日 AI 热点推送模块。

- 数据源:https://aihot.virxact.com/api/public/daily(匿名公开 OpenAPI 3.1,只读,
  需要带浏览器 User-Agent,否则 nginx 黑名单 → 403)
- 输出:飞书 interactive card,通过 bot 现有的 lark_client 发到 HOTNEWS_CHAT_ID
- 调度:独立 daemon 线程,每天到点(默认 08:30)触发一次

跟 bot 主进程共生:同一份 Feishu 凭证,同一个 lark_client,不需要额外认证。
HOTNEWS_CHAT_ID 不配置时模块自动跳过,bot 行为不受影响。

CLI 测试:
    # 仅打印生成的卡片 JSON, 不发送
    python daily_hotnews.py

    # 立即对 HOTNEWS_CHAT_ID 发送一次(用于联调)
    python daily_hotnews.py --send
"""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
from datetime import datetime, timedelta
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

log = logging.getLogger(__name__)

DEFAULT_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
DEFAULT_API = "https://aihot.virxact.com/api/public/daily"


# ── Config ────────────────────────────────────────────────────────────────────

def _config() -> dict:
    """读取 env(每次调度循环都重读一次,方便热改 .env)"""
    return {
        "chat_id": os.getenv("HOTNEWS_CHAT_ID", "").strip(),
        "hour": int(os.getenv("HOTNEWS_HOUR", "8")),
        "minute": int(os.getenv("HOTNEWS_MINUTE", "30")),
        "api_url": os.getenv("HOTNEWS_API_URL", DEFAULT_API),
        "ua": os.getenv("HOTNEWS_UA", DEFAULT_UA),
        "max_items": int(os.getenv("HOTNEWS_MAX_ITEMS", "10")),
        "timeout": int(os.getenv("HOTNEWS_HTTP_TIMEOUT", "20")),
    }


# ── Fetch ─────────────────────────────────────────────────────────────────────

def fetch_daily(api_url: str, ua: str, timeout: int) -> dict:
    """GET aihot daily endpoint, 必须带 UA, 默认 curl UA 会 403"""
    req = Request(api_url, method="GET")
    req.add_header("User-Agent", ua)
    req.add_header("Accept", "application/json")
    with urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8")
    return json.loads(body)


# ── Card builder ──────────────────────────────────────────────────────────────

def _pick(d: dict, *keys: str, default: str = "") -> str:
    """从字典里挑第一个非空的字段, 兼容 API 字段名变动"""
    for k in keys:
        v = d.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return default


def build_card(payload: dict, max_items: int) -> dict:
    """
    构造飞书 v1 interactive card.
    防御性解析:payload 可能直接是 {date, items}, 也可能包在 {data: {...}} 里,
    items 字段名也可能是 highlights / articles / topics。
    """
    root = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    date_str = _pick(root, "date", "created_at", "day", default=datetime.now().strftime("%Y-%m-%d"))

    items = (
        root.get("items")
        or root.get("highlights")
        or root.get("articles")
        or root.get("topics")
        or []
    )
    if not isinstance(items, list):
        items = []

    rendered: list[str] = []
    for i, it in enumerate(items[:max_items], 1):
        if not isinstance(it, dict):
            continue
        title = _pick(it, "title", "name", "headline", default="(无标题)")
        url = _pick(it, "url", "link", "source_url")
        summary = _pick(it, "summary", "description", "excerpt", "abstract")
        source = _pick(it, "source", "publisher", "site")

        head = f"**{i}. [{title}]({url})**" if url else f"**{i}. {title}**"
        line = head
        if source:
            line += f"  *— {source}*"
        if summary:
            # 飞书卡片对长度敏感, 单条摘要做个上限
            line += "\n" + (summary[:200] + ("…" if len(summary) > 200 else ""))
        rendered.append(line)

    if rendered:
        body_md = "\n\n".join(rendered)
    else:
        log.warning("hotnews: payload 没有可渲染的条目, payload keys=%s", list(payload.keys()))
        body_md = (
            "今天 aihot 返回为空或字段不识别,bot 日志里有原始 payload。\n"
            "也可以打开:[aihot.virxact.com](https://aihot.virxact.com) 直接查看"
        )

    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": f"🔥 AI 每日热点 · {date_str}"},
            "template": "blue",
        },
        "elements": [
            {"tag": "div", "text": {"tag": "lark_md", "content": body_md}},
            {"tag": "hr"},
            {
                "tag": "note",
                "elements": [
                    {"tag": "lark_md", "content": "数据源:[aihot.virxact.com](https://aihot.virxact.com)"}
                ],
            },
        ],
    }


# ── Scheduling ────────────────────────────────────────────────────────────────

def _next_fire_time(hour: int, minute: int, now: datetime | None = None) -> datetime:
    now = now or datetime.now()
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return target


def _push_once(
    send_card: Callable[[str, dict], None],
    send_text: Callable[[str, str], None],
    cfg: dict,
) -> None:
    """拉取 + 渲染 + 发送, 异常吞下并尽量降级为文本告警"""
    try:
        payload = fetch_daily(cfg["api_url"], cfg["ua"], cfg["timeout"])
    except (URLError, HTTPError, TimeoutError, json.JSONDecodeError) as e:
        log.error("hotnews fetch failed: %s", e)
        try:
            send_text(cfg["chat_id"], f"⚠ AI 每日热点拉取失败:{e}")
        except Exception as e2:
            log.error("hotnews fallback send also failed: %s", e2)
        return
    except Exception as e:  # noqa: BLE001
        log.exception("hotnews fetch unexpected error: %s", e)
        return

    log.info("hotnews payload keys=%s", list(payload.keys()) if isinstance(payload, dict) else type(payload).__name__)
    try:
        card = build_card(payload, cfg["max_items"])
        send_card(cfg["chat_id"], card)
        log.info("hotnews pushed to chat=%s", cfg["chat_id"])
    except Exception as e:  # noqa: BLE001
        log.exception("hotnews send failed: %s", e)
        try:
            send_text(cfg["chat_id"], f"⚠ AI 每日热点渲染/发送失败:{e}")
        except Exception:
            pass


def _scheduler_loop(
    send_card: Callable[[str, dict], None],
    send_text: Callable[[str, str], None],
) -> None:
    while True:
        try:
            cfg = _config()
        except ValueError as e:
            log.error("hotnews 配置错误(可能是 HOTNEWS_HOUR/MINUTE 非整数): %s, 1h 后重试", e)
            time.sleep(3600)
            continue

        if not cfg["chat_id"]:
            log.warning("HOTNEWS_CHAT_ID 已被清空, 调度暂停 1h")
            time.sleep(3600)
            continue

        target = _next_fire_time(cfg["hour"], cfg["minute"])
        log.info(
            "hotnews: 下次推送 %s (剩余 %.0f 秒)",
            target.isoformat(timespec="seconds"),
            (target - datetime.now()).total_seconds(),
        )

        # 分段 sleep, 容忍系统休眠/时钟跳变
        while True:
            remaining = (target - datetime.now()).total_seconds()
            if remaining <= 0:
                break
            time.sleep(min(remaining, 60))

        _push_once(send_card, send_text, cfg)


def start(
    send_card: Callable[[str, dict], None],
    send_text: Callable[[str, str], None],
) -> threading.Thread | None:
    """启动后台调度线程。HOTNEWS_CHAT_ID 未配置则跳过。"""
    cfg = _config()
    if not cfg["chat_id"]:
        log.info("HOTNEWS_CHAT_ID 未配置,日热点推送模块未启用")
        return None
    t = threading.Thread(
        target=_scheduler_loop,
        args=(send_card, send_text),
        name="hotnews-scheduler",
        daemon=True,
    )
    t.start()
    log.info(
        "hotnews scheduler 已启动:每天 %02d:%02d 推送到 chat=%s",
        cfg["hour"], cfg["minute"], cfg["chat_id"],
    )
    return t


# ── CLI ───────────────────────────────────────────────────────────────────────

def _cli() -> int:
    """
    命令行测试:
        python daily_hotnews.py         打印生成的卡片 JSON, 不发送
        python daily_hotnews.py --send  立即推送一次到 HOTNEWS_CHAT_ID(联调用)
    """
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    # .env 加载(bot.py 也走 dotenv, 这里独立使用要自己加载)
    try:
        from dotenv import load_dotenv  # type: ignore
        load_dotenv()
    except ImportError:
        pass

    cfg = _config()
    want_send = "--send" in sys.argv

    if want_send and not cfg["chat_id"]:
        print("HOTNEWS_CHAT_ID 未设置, --send 无法工作", file=sys.stderr)
        return 2

    # 1. 干跑模式:只打印渲染结果
    if not want_send:
        log.info("dry run: 拉取 %s", cfg["api_url"])
        payload = fetch_daily(cfg["api_url"], cfg["ua"], cfg["timeout"])
        card = build_card(payload, cfg["max_items"])
        print(json.dumps(card, ensure_ascii=False, indent=2))
        return 0

    # 2. 真发送:从 bot 模块借用 lark_client
    log.info("--send: 走完整 fetch → build → 发送链路")
    from bot import lark_client, send_message  # noqa: E402
    from lark_oapi.api.im.v1 import CreateMessageRequest, CreateMessageRequestBody  # noqa: E402

    def _send_card(chat_id: str, card: dict) -> None:
        req = (
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
        resp = lark_client.im.v1.message.create(req)
        if not resp.success():
            raise RuntimeError(f"send_card failed: code={resp.code} msg={resp.msg}")

    _push_once(_send_card, send_message, cfg)
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
