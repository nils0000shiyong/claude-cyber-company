# 飞书 WebSocket Bot

飞书机器人服务，通过官方 SDK 长连接接收消息，分发给 Claude 或 Codex 执行。同一份代码启动两次（分别配不同的 App ID），即可同时运行 Claude Bot 和 Codex Bot。

## 安装(首次)

```bash
cd feishu-bot
/opt/homebrew/bin/python3.10 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

> 必须用 Python 3.10+,bot.py 用了 `dict | None` 等新语法。系统自带的 3.9 起不来。

## 日常使用:菜单栏控制台

双击 `feishu-bot/launch-console.command`,菜单栏出现飞书 Bot 图标:

| 图标 | 含义 |
|------|------|
| 🟢 | 运行中,最近 60s 无错误日志 |
| 🟡 | 运行中,但最近 60s 有 WARNING/ERROR |
| 🔴 | 已停止 / 崩溃 |

点击图标弹出菜单:

- **启动 / 停止 / 重启** — 直接控制 bot 进程
- **查看实时日志…** — 弹窗显示最近 120 行
- **最近一次错误…** — bot 崩溃时,自动把日志尾部匹配成中文「原因 + 解法」
- **打开日志目录** — 完整历史日志在 `feishu-bot/logs/`
- **崩溃自动重启** — 勾选后崩溃会按 2s / 8s / 30s 退避自动拉起,最多 3 次

控制台退出时会先 `terminate` 再 `kill` 子进程,不留孤儿进程。

## 切换 Claude / Codex 引擎

通过 `.env` 或环境变量配置 `FEISHU_AGENT_ENGINE`(`claude` 或 `codex`),控制台读取同一份 bot.py。需要同时跑两个 bot 时,各起一份控制台进程并指向不同的 `.env` 即可。

## 常见错误自助排查

控制台「最近一次错误」会自动识别以下场景并给出中文建议,无需翻日志:

- Python 版本太老(< 3.10)
- 依赖缺失(`ModuleNotFoundError`)
- `.env` 不存在或 `FEISHU_APP_ID` / `FEISHU_APP_SECRET` 未设
- 飞书 App Token 无效(凭据写错或 App 被停用)
- 连不上 open.feishu.cn(网络/代理问题)
- 端口被占用
- bot.py 本身有语法错误

没命中模式则显示日志尾部 + 提示发给 Elon。

## 飞书后台配置

1. 进入飞书开放平台 → 应用 → 事件与回调 → 事件配置。
2. 订阅方式选择：`使用长连接接收事件`。
3. 保持本地 `python bot.py` 运行，点击验证。
4. 添加事件：`im.message.receive_v1`。
5. 权限管理 → 添加：`im:message`、`im:message:send_as_bot`。
6. 保存并发布应用版本。

长连接模式不需要公网域名，也不需要配置加密策略。

## 权限模式

默认不跳过 Claude/Codex 自身权限限制。如果这是只给你自己使用的私有 bot，并且明确接受风险，可以加：

```bash
AGENT_ALLOW_UNSAFE_PERMISSIONS=true
```

注意：打开后，飞书消息可能触发本机文件修改或命令执行。不要把这种 bot 放进多人群。

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `FEISHU_APP_ID` | 必填 | 飞书应用 App ID |
| `FEISHU_APP_SECRET` | 必填 | 飞书应用 App Secret |
| `FEISHU_AGENT_ENGINE` | `claude` | `claude` 或 `codex` |
| `AGENT_WORK_DIR` | 项目根目录 | agent 工作目录 |
| `AGENT_TIMEOUT` | `300` | agent 执行超时秒数 |
| `AGENT_ALLOW_UNSAFE_PERMISSIONS` | `false` | 是否跳过权限限制 |
| `CLAUDE_COMMAND` | `claude` | Claude CLI 命令 |
| `CODEX_COMMAND` | `codex` | Codex CLI 命令 |
| `CODEX_SANDBOX` | `workspace-write` | Codex 沙箱模式 |
| `CODEX_APPROVAL_POLICY` | `never` | Codex 审批策略 |
| `HOTNEWS_CHAT_ID` | 空(不启用) | 每日 AI 热点推送目标 chat_id,留空则跳过 |
| `HOTNEWS_HOUR` | `8` | 推送小时(0-23) |
| `HOTNEWS_MINUTE` | `30` | 推送分钟(0-59) |
| `HOTNEWS_API_URL` | aihot 默认地址 | 数据源 URL |
| `HOTNEWS_MAX_ITEMS` | `10` | 单次卡片最多显示几条 |
| `HOTNEWS_HTTP_TIMEOUT` | `20` | 拉取 API 的超时秒数 |

也可以把变量写入 `.env` 文件（参考 `.env.claude.example` / `.env.codex.example`）。不要把真实密钥提交到 git。

## 每日 AI 热点推送 (`daily_hotnews.py`)

设置 `HOTNEWS_CHAT_ID` 后,bot 启动时会拉起一个后台 daemon 线程,每天 `HOTNEWS_HOUR:HOTNEWS_MINUTE` 自动:

1. GET `https://aihot.virxact.com/api/public/daily`(带浏览器 UA,避免被 nginx 黑名单)
2. 用 v1 interactive card 渲染前 N 条热点
3. 通过现有的 `lark_client` 发到 `HOTNEWS_CHAT_ID`

未配置 `HOTNEWS_CHAT_ID` 则模块不启用,bot 行为不变。

### 联调

```bash
# 干跑:只打印卡片 JSON,不发飞书
.venv/bin/python daily_hotnews.py

# 完整链路:立即推送一次到 HOTNEWS_CHAT_ID
.venv/bin/python daily_hotnews.py --send
```

### 找 chat_id 的两种方式

1. **从已有 session 文件读**:`memory/sessions/oc_xxx.json` 文件名里的 `oc_xxx` 就是 chat_id。
2. **从日志里看**:bot 收到任意一条消息时会打印 `chat=oc_xxx ... received: ...`,复制下来即可。

### 故障排查

- 没到点也想测一次 → `python daily_hotnews.py --send`
- 推送内容乱码 / 字段缺失 → bot 日志里有 `hotnews payload keys=...`,把 payload 实际结构告诉 maintainer 改 `build_card()` 里的字段名映射
- 拉取 403 → aihot 屏蔽了你的出口 IP,或 `HOTNEWS_UA` 被改成 curl 默认 UA

## 隔离原则

- Claude Bot 只调用 Claude，读取 `CLAUDE.md` 和 `.claude/agents/`。
- Codex Bot 只调用 Codex，读取 `AGENTS.md` 和 `.codex/agents/`。
- 两者只通过 `memory/` 和 `tasks/` 共享长期信息。
- 两个飞书应用各自独立，互不干扰。
