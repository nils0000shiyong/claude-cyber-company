"""飞书 Bot 菜单栏控制台。

启动方式: ./.venv/bin/python console.py
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path

import rumps

from error_hints import Hint, match_hint


HERE = Path(__file__).resolve().parent
BOT_PY = HERE / "bot.py"
LOG_DIR = HERE / "logs"
LOG_DIR.mkdir(exist_ok=True)

ICON_RUNNING = "🟢"
ICON_WARN = "🟡"
ICON_STOPPED = "🔴"

WARN_WINDOW_SEC = 60
RING_CAPACITY = 500
RESTART_BACKOFF = [2, 8, 30]


class BotProcess:
    """对 bot 子进程的薄封装:启动、停止、读日志、给出最近状态。"""

    def __init__(self) -> None:
        self.proc: subprocess.Popen[str] | None = None
        self.ring: deque[str] = deque(maxlen=RING_CAPACITY)
        self.last_warn_ts: float = 0.0
        self.log_path: Path | None = None
        self.started_at: float | None = None
        self._reader: threading.Thread | None = None
        self._lock = threading.Lock()

    def is_alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def start(self) -> tuple[bool, str]:
        if self.is_alive():
            return False, "bot 已经在运行中"
        if not BOT_PY.exists():
            return False, f"找不到 {BOT_PY.name}"

        self.log_path = LOG_DIR / f"bot-{datetime.now():%Y%m%d-%H%M%S}.log"
        try:
            self.proc = subprocess.Popen(
                [sys.executable, str(BOT_PY)],
                cwd=str(HERE),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
        except OSError as exc:
            return False, f"启动失败: {exc}"

        self.ring.clear()
        self.last_warn_ts = 0.0
        self.started_at = time.time()
        self._reader = threading.Thread(target=self._pump_stdout, daemon=True)
        self._reader.start()
        return True, "已启动"

    def stop(self, timeout: float = 5.0) -> tuple[bool, str]:
        if not self.is_alive():
            return False, "bot 没在运行"
        assert self.proc is not None
        self.proc.terminate()
        try:
            self.proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait(timeout=2)
        self.started_at = None
        return True, "已停止"

    def uptime_str(self) -> str:
        if not self.started_at:
            return "—"
        secs = int(time.time() - self.started_at)
        h, rem = divmod(secs, 3600)
        m, s = divmod(rem, 60)
        return f"{h:02d}:{m:02d}:{s:02d}"

    def tail(self, n: int = 80) -> str:
        with self._lock:
            lines = list(self.ring)[-n:]
        return "".join(lines)

    def _pump_stdout(self) -> None:
        assert self.proc is not None and self.proc.stdout is not None
        log_file = open(self.log_path, "a", encoding="utf-8") if self.log_path else None
        try:
            for line in self.proc.stdout:
                with self._lock:
                    self.ring.append(line)
                if log_file:
                    log_file.write(line)
                    log_file.flush()
                low = line.lower()
                if "error" in low or "exception" in low or "traceback" in low or "warning" in low:
                    self.last_warn_ts = time.time()
        finally:
            if log_file:
                log_file.close()


class ConsoleApp(rumps.App):
    def __init__(self) -> None:
        super().__init__("飞书 Bot", title=ICON_STOPPED, quit_button=None)
        self.bot = BotProcess()
        self.last_hint: Hint | None = None
        self.last_exit_code: int | None = None
        self.auto_restart = False
        self.restart_attempts = 0
        self.next_restart_at: float | None = None
        self.was_alive = False

        self.m_status = rumps.MenuItem("状态: 🔴 已停止")
        self.m_status.set_callback(None)
        self.m_start = rumps.MenuItem("启动", callback=self.on_start)
        self.m_stop = rumps.MenuItem("停止", callback=self.on_stop)
        self.m_restart = rumps.MenuItem("重启", callback=self.on_restart)
        self.m_logs = rumps.MenuItem("查看实时日志…", callback=self.on_view_logs)
        self.m_last_err = rumps.MenuItem("最近一次错误…", callback=self.on_view_error)
        self.m_auto = rumps.MenuItem("崩溃自动重启", callback=self.on_toggle_auto)
        self.m_logs_dir = rumps.MenuItem("打开日志目录", callback=self.on_open_logs_dir)
        self.m_quit = rumps.MenuItem("退出控制台", callback=self.on_quit)

        self.menu = [
            self.m_status,
            None,
            self.m_start,
            self.m_stop,
            self.m_restart,
            None,
            self.m_logs,
            self.m_last_err,
            self.m_logs_dir,
            None,
            self.m_auto,
            None,
            self.m_quit,
        ]
        self._refresh_menu_enable()

    def _refresh_menu_enable(self) -> None:
        alive = self.bot.is_alive()
        self.m_start.set_callback(None if alive else self.on_start)
        self.m_stop.set_callback(self.on_stop if alive else None)
        self.m_restart.set_callback(self.on_restart if alive else None)
        self.m_last_err.set_callback(self.on_view_error if self.last_hint else None)
        self.m_auto.state = 1 if self.auto_restart else 0

    @rumps.timer(2)
    def tick(self, _sender) -> None:
        alive = self.bot.is_alive()

        if self.was_alive and not alive:
            self._handle_crash()
        self.was_alive = alive

        if alive:
            recent_warn = (time.time() - self.bot.last_warn_ts) < WARN_WINDOW_SEC
            self.title = ICON_WARN if recent_warn else ICON_RUNNING
            self.m_status.title = (
                f"状态: {ICON_WARN if recent_warn else ICON_RUNNING}"
                f" {'有近期警告' if recent_warn else '运行中'} · uptime {self.bot.uptime_str()}"
            )
        else:
            self.title = ICON_STOPPED
            if self.next_restart_at and time.time() < self.next_restart_at:
                wait = int(self.next_restart_at - time.time())
                self.m_status.title = f"状态: 🔴 已停止 · {wait}s 后自动重启"
            else:
                self.m_status.title = "状态: 🔴 已停止"

        if (
            not alive
            and self.auto_restart
            and self.next_restart_at
            and time.time() >= self.next_restart_at
        ):
            self.next_restart_at = None
            self._try_auto_restart()

        self._refresh_menu_enable()

    def _handle_crash(self) -> None:
        code = self.bot.proc.poll() if self.bot.proc else None
        self.last_exit_code = code
        tail = self.bot.tail(120)
        self.last_hint = match_hint(tail)
        rumps.notification(
            title="飞书 Bot 已停止",
            subtitle=f"退出码 {code} · {self.last_hint.title}",
            message="点击菜单栏图标查看「最近一次错误」。",
        )
        if self.auto_restart and self.restart_attempts < len(RESTART_BACKOFF):
            delay = RESTART_BACKOFF[self.restart_attempts]
            self.next_restart_at = time.time() + delay
        else:
            self.next_restart_at = None
            if self.auto_restart and self.restart_attempts >= len(RESTART_BACKOFF):
                rumps.notification(
                    title="自动重启已放弃",
                    subtitle=f"连续失败 {self.restart_attempts} 次",
                    message="请打开「最近一次错误」查看原因。",
                )

    def _try_auto_restart(self) -> None:
        self.restart_attempts += 1
        ok, _ = self.bot.start()
        if ok:
            return
        if self.restart_attempts < len(RESTART_BACKOFF):
            self.next_restart_at = time.time() + RESTART_BACKOFF[self.restart_attempts]

    # ---- 菜单回调 ----

    def on_start(self, _sender) -> None:
        self.restart_attempts = 0
        self.next_restart_at = None
        self.last_hint = None
        ok, msg = self.bot.start()
        if not ok:
            rumps.alert("启动失败", msg)

    def on_stop(self, _sender) -> None:
        self.auto_restart_suppress_once = True
        self.next_restart_at = None
        # 手动停止不应触发崩溃诊断
        self.bot.stop()
        self.was_alive = False  # 抑制 tick 里把这次停止当成 crash
        self.last_hint = None

    def on_restart(self, _sender) -> None:
        self.bot.stop()
        self.was_alive = False
        time.sleep(0.5)
        self.restart_attempts = 0
        ok, msg = self.bot.start()
        if not ok:
            rumps.alert("重启失败", msg)

    def on_view_logs(self, _sender) -> None:
        tail = self.bot.tail(120) or "(还没有日志)"
        rumps.Window(
            title="飞书 Bot 实时日志(最近 120 行)",
            message="完整日志在「打开日志目录」里。",
            default_text=tail,
            dimensions=(720, 420),
            ok="关闭",
            cancel=None,
        ).run()

    def on_view_error(self, _sender) -> None:
        if not self.last_hint:
            rumps.alert("没有错误记录", "bot 还没崩过,或控制台刚启动。")
            return
        h = self.last_hint
        code = self.last_exit_code if self.last_exit_code is not None else "?"
        body = (
            f"【{h.title}】(退出码 {code})\n\n"
            f"原因:\n{h.explanation}\n\n"
            f"建议解法:\n{h.fix}\n\n"
            f"——— 日志尾部 ———\n{self.bot.tail(40)}"
        )
        rumps.Window(
            title="最近一次错误",
            message="",
            default_text=body,
            dimensions=(720, 480),
            ok="知道了",
            cancel=None,
        ).run()

    def on_open_logs_dir(self, _sender) -> None:
        subprocess.Popen(["open", str(LOG_DIR)])

    def on_toggle_auto(self, sender) -> None:
        self.auto_restart = not self.auto_restart
        sender.state = 1 if self.auto_restart else 0
        if not self.auto_restart:
            self.next_restart_at = None

    def on_quit(self, _sender) -> None:
        if self.bot.is_alive():
            self.bot.stop()
        rumps.quit_application()


def _install_signal_handlers(app: ConsoleApp) -> None:
    def _graceful(_signo, _frame):
        if app.bot.is_alive():
            app.bot.stop()
        os._exit(0)

    signal.signal(signal.SIGINT, _graceful)
    signal.signal(signal.SIGTERM, _graceful)


if __name__ == "__main__":
    app = ConsoleApp()
    _install_signal_handlers(app)
    app.run()
