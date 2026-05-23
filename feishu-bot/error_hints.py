"""把 bot 退出时的最后几行日志翻译成中文错误解释 + 建议解法。"""

from __future__ import annotations

import re
from typing import NamedTuple


class Hint(NamedTuple):
    title: str
    explanation: str
    fix: str


_RULES: list[tuple[re.Pattern[str], Hint]] = [
    (
        re.compile(r"unsupported operand type\(s\) for \|.*'type'.*'NoneType'", re.S),
        Hint(
            title="Python 版本太老",
            explanation="bot.py 用了 `dict | None` 这种类型注解,需要 Python 3.10+。当前解释器是 3.9 或更老。",
            fix="确认控制台是用 feishu-bot/.venv/bin/python 启动的;或在 bot.py 里把类型注解改成 Optional[dict]。",
        ),
    ),
    (
        re.compile(r"ModuleNotFoundError: No module named ['\"]([^'\"]+)['\"]"),
        Hint(
            title="依赖缺失",
            explanation="bot 需要的 Python 包没装到当前解释器里。",
            fix="在 feishu-bot 目录执行: .venv/bin/pip install -r requirements.txt",
        ),
    ),
    (
        re.compile(r"KeyError: ['\"]FEISHU_(APP_ID|APP_SECRET)['\"]"),
        Hint(
            title=".env 没读到飞书凭据",
            explanation="环境变量 FEISHU_APP_ID 或 FEISHU_APP_SECRET 未设置,bot 启动时直接报 KeyError。",
            fix="检查 feishu-bot/.env 是否存在并包含 FEISHU_APP_ID=... 和 FEISHU_APP_SECRET=... 两行。",
        ),
    ),
    (
        re.compile(r"99991663|invalid.*app.*access.*token|invalid.*tenant.*access.*token", re.I),
        Hint(
            title="飞书 App Token 无效",
            explanation="飞书开放平台拒绝了 bot 的身份认证,通常是 APP_ID / APP_SECRET 写错或 App 被停用。",
            fix="登录飞书开放平台核对凭据,确认 App 状态正常,把正确的值写回 .env 后重启控制台。",
        ),
    ),
    (
        re.compile(r"(ConnectionError|Max retries exceeded|Failed to establish a new connection|Name or service not known|getaddrinfo failed)", re.I),
        Hint(
            title="连不上飞书开放平台",
            explanation="网络层失败,bot 没法和 open.feishu.cn 建立连接。",
            fix="检查网络/代理/VPN;在终端跑 `ping open.feishu.cn` 验证;企业网可能需要走代理,确认 HTTPS_PROXY 设置。",
        ),
    ),
    (
        re.compile(r"(Address already in use|EADDRINUSE|port.*in use)", re.I),
        Hint(
            title="端口被占用",
            explanation="bot 想监听的端口已经被另一个进程占着。",
            fix="先用 `lsof -i :<端口号>` 查到占用进程并结束,或者关掉已经在跑的另一个 bot 实例。",
        ),
    ),
    (
        re.compile(r"FileNotFoundError.*\.env", re.I),
        Hint(
            title=".env 文件不存在",
            explanation="bot.py 期望在 feishu-bot 目录读到 .env,但文件不在。",
            fix="新建 feishu-bot/.env,至少包含 FEISHU_APP_ID 和 FEISHU_APP_SECRET 两项。",
        ),
    ),
    (
        re.compile(r"SyntaxError", re.I),
        Hint(
            title="bot.py 语法错误",
            explanation="bot.py 本身的代码无法被 Python 解释器解析。多半是最近一次改动留了破折。",
            fix="看日志里 SyntaxError 提示的行号,回到 bot.py 那一行检查;必要时用 git diff 对照上一个能跑的版本。",
        ),
    ),
]


_UNKNOWN = Hint(
    title="未知错误",
    explanation="没匹配到已知模式。请把下面日志尾部发给 Elon 排查。",
    fix="复制下面的日志最后几行,贴给 Elon。若是临时网络抖动可先试一次「重启」。",
)


def match_hint(log_tail: str) -> Hint:
    """扫描日志尾部,返回首个命中的中文提示;都没命中返回兜底。"""
    for pattern, hint in _RULES:
        if pattern.search(log_tail):
            return hint
    return _UNKNOWN
