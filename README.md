# OPC — 一人公司 AI Agent 系统

> **One-Person Company** — A local multi-agent scaffold on Claude Code & Codex: one human, a role-based delegation convention, and a shared file-memory layer. Optionally wired to Feishu for a zero-friction chat entry.

[中文文档] | [English below](#english-overview)

---

## 这是什么？

一句话：你当老板，AI 当员工，而且这帮员工不要工资、不摸鱼、不请年假。

OPC 是一套基于 Claude Code 的本地多 Agent 协作框架。你是公司里唯一的人类（光荣的"董事长"），用大白话下指令，主 Agent **Elon（CEO）** 负责听懂、拆活、派活，最后把成果端到你面前。你只管动嘴。

**不需要额外框架，不需要折腾 API 密钥，不需要租服务器。** 全程跑在你本地的 Claude Code CLI 上——你的电脑就是公司总部。

```
        你（人类，也是唯一的人）
           │ 自然语言指令
        Elon（CEO Agent）
           │ 任务拆解 + 分派
    ┌──────┼──────┬──────┐
   Jobs  Linus  Turing Bezos
   产品   编程   验证   客服
```

公司花名册：

| Agent | 职能 | 工具权限 |
|-------|------|---------|
| **Elon** | CEO，唯一对你说话的人，负责听懂 → 拆解 → 分派 → 汇总 | Claude Code 全部工具 |
| **Jobs** | 产品设计，需求分析，PRD 撰写，UX 决策（负责纠结"该做什么"） | Read, Write, Edit, WebSearch, WebFetch, Glob, Grep |
| **Linus** | 编程执行，写代码、调试、重构、跑测试（负责真干活） | Read, Write, Edit, Bash, Glob, Grep |
| **Turing** | 验证质检，代码审查，交叉验证，专挑同事的毛病 | Read, Bash, Glob, Grep, WebSearch, WebFetch, Agent |
| **Bezos** | 对外沟通，客户邮件，客服话术，负责对外说人话 | Read, Write, Edit, WebSearch |

### 它不是什么（先把丑话说前头）

免得你抱着"买了个机器人管家"的期待进来，结果失望：

- **不是一个部署型服务**——它就跑在你本地一台机器上，电脑一关，全公司集体下班。
- **不是一个飞书集成方案**——论"操作飞书"，飞书官方 CLI 比我们全得多（见下文「与飞书官方 CLI 的关系」）。本项目的 Bot 只干一件官方 CLI 不干的脏活：**入站实时触发**。
- **不是一个保证全自动协作的魔法系统**——链路跑不跑得通，看任务多复杂、你指令给得多清楚。终端里面对面聊，比隔着飞书喊话靠谱。

---

## 目录结构

```
opc/
├── CLAUDE.md                  # Elon 的 system prompt（Claude 侧主入口）
├── AGENTS.md                  # Elon 的 system prompt（Codex 侧主入口）
├── README.md                  # 本文件
│
├── .claude/
│   ├── agents/                # Claude Code subagent 定义
│   │   ├── jobs.md
│   │   ├── linus.md
│   │   ├── turing.md
│   │   └── bezos.md
│   ├── settings.json          # 项目级权限配置（可提交）
│   └── settings.local.json    # 个人本地配置（已 gitignore）
│
├── .codex/
│   └── agents/                # Codex subagent 定义（.toml 格式）
│       ├── jobs.toml
│       ├── linus.toml
│       ├── turing.toml
│       └── bezos.toml
│
├── memory/                    # Claude / Codex 唯一共享记忆层（公司的"集体记忆"）
│   ├── README.md              # 读写协议说明
│   ├── stable/                # 已验证的长期事实
│   ├── working/               # 阶段性上下文、未验证假设
│   └── inbox/                 # 平台间交接记录
│
├── tasks/                     # 任务过程记录
│   └── README.md
│
└── feishu-bot/                # 可选：飞书 WebSocket Bot
    ├── bot.py                 # 主程序
    ├── console.py             # macOS 菜单栏控制台（仅限 Mac）
    ├── daily_hotnews.py       # 每日 AI 热点推送
    ├── error_hints.py         # 中文错误提示
    ├── requirements.txt
    ├── .env.claude.example    # Claude Bot 配置模板
    ├── .env.codex.example     # Codex Bot 配置模板
    └── launch-console.command # 双击启动控制台
```

---

## 快速开始（5 分钟，比泡面还快）

### 前置条件

- [Claude Code](https://docs.anthropic.com/claude-code) CLI 已安装并登录
- Git

Codex 支持是可选项，没有也照样开张。

### 第一步：克隆项目（把公司搬回家）

```bash
git clone https://github.com/YOUR_USERNAME/opc.git
cd opc
```

### 第二步：启动

```bash
claude
```

就这样。恭喜上任，你现在正在和你的 CEO **Elon** 谈话。

### 第三步：给第一个指令（开个简单的让员工热身）

别一上来就丢个登月计划，先来个小活儿看看分派流程：

```
任务：帮我写一个 Python 脚本，把指定文件夹内的文件按修改时间从新到旧排序并打印
验收标准：脚本能接受路径参数，输出格式清晰，有注释
```

Elon 会：
1. 输出任务卡，确认自己没听岔
2. 把活儿甩给 **Linus** 写代码
3. 再喊 **Turing** 来挑毛病
4. 汇总好，端给你

---

## 如何下达指令

推荐格式（哪部分懒得写都行，Elon 会追着你问）：

```
任务：[你想做什么]
背景：[相关上下文]
验收标准：[怎么算完成，可省略]
```

例子：

```
任务：整理今天的会议纪要，从文本里提取行动项
背景：文件在 ~/desktop/meeting.txt，参与者有 4 人
验收标准：输出 markdown，行动项带负责人和截止日期
```

**别操心该派给谁。** 这是 CEO 该头疼的事，不是你的。

---

## 双平台支持（Claude + Codex）

本项目同时支持 Claude Code 和 OpenAI Codex CLI——相当于公司有两套办公系统，但共用同一份档案库：

| 平台 | 主入口 | Agent 定义 | 启动命令 |
|------|--------|-----------|---------|
| Claude Code | `CLAUDE.md` | `.claude/agents/*.md` | `claude` |
| Codex | `AGENTS.md` | `.codex/agents/*.toml` | `codex` |

**隔离原则**：两套系统的 agent 定义互不串味。Claude 只看 `.claude/`，Codex 只看 `.codex/`，谁也别偷看对方的笔记。唯一允许共享的，是 `memory/` 和 `tasks/` 这两个公共储物间。

---

## 记忆系统

`memory/` 是 Claude 和 Codex 之间的文件级共享记忆——也就是这家公司唯一靠谱的"脑子"：

| 目录 | 用途 | 写入规则 |
|------|------|---------|
| `memory/stable/` | 已验证的长期事实（公司背景、决策记录） | 标注日期、来源、置信度 |
| `memory/working/` | 当前任务的阶段性上下文、草稿 | 任务结束后记得收拾 |
| `memory/inbox/` | 平台间交接摘要 | 只写要点，别搬运完整聊天记录 |

**强烈建议在 `memory/stable/` 里写清你的公司/项目背景**，这样 Elon 就不用每次见面都"请问您是哪位、咱公司是做啥的"。

---

## 自定义你的 Agent 团队

### 调教 Elon（改 CEO 的脾气）

编辑 `CLAUDE.md`（Elon 的 system prompt）：
- 改"跟董事长沟通的风格"，调成你受得了的语气
- 改"分派决策原则"，重新划分手下的地盘

### 招新员工（添加新 Agent）

在 `.claude/agents/` 下新建一个 `.md` 文件，等于发了张入职 offer：

```markdown
---
name: agentname
description: 一句话说明什么时候该叫这个 agent（Elon 全靠这句话决定派不派活）
tools: Read, Write, Edit, Bash
model: sonnet
---

你是 [角色名]，负责 [职责]。

[角色 system prompt...]
```

### 给老员工改 KPI（修改现有 Agent）

直接编辑 `.claude/agents/` 下对应的 `.md`。改完立刻生效，不用重启——比真员工好管多了。

### 个人本地配置

复制一份再改：

```bash
cp .claude/settings.local.example.json .claude/settings.local.json
```

`settings.local.json` 已被 gitignore，专门放你这台机器上独有的路径或权限，不会带累别人。

---

## 飞书 Bot（可选）

懒得每次开终端？想躺在沙发上用飞书指挥公司？那就启用飞书 Bot。

```
你的飞书消息 → 飞书 Bot → Claude/Codex CLI → 回复
```

详细配置见 [feishu-bot/README.md](feishu-bot/README.md)。

**与飞书官方 CLI 的关系**：飞书在 2026 年发了官方 [CLI](https://github.com/larksuite/cli)（200+ 命令 + Agent Skills，消息 / 文档 / 多维表格 / 表格 / 日历 / 邮箱通吃）。如果你想让 agent **主动去操作**飞书——发消息、读写文档、传文件——别重复造轮子，直接用官方 CLI。OPC 的 feishu-bot 只补另外半块拼图：**入站实时触发**，也就是有人发消息时把你的 agent 叫醒。两者天生一对：feishu-bot 负责"听到敲门"，飞书 CLI 负责"开门干活"。

**访问控制与安全**（这段不开玩笑，请认真看）：两层门禁——飞书应用「可用范围」（平台层，决定谁能 @ 到 bot，不在范围里的人连门都敲不响）+ 代码白名单（区分 owner / member）。⚠️ 当 `AGENT_ALLOW_UNSAFE_PERMISSIONS=true` 时，可用范围内的成员就等于拿到了你这台机器的命令执行权限。自己一个人用没问题；要拉别人进来之前，先想清楚要不要收紧权限或加沙箱，**千万别手一抖把飞书应用的可用范围开给全公司**。

核心步骤：
1. 在飞书开放平台创建应用，拿到 App ID 和 App Secret
2. 复制 `feishu-bot/.env.claude.example` → `feishu-bot/.env`，填入凭证
3. 安装依赖：`cd feishu-bot && python3.10 -m venv .venv && .venv/bin/pip install -r requirements.txt`
4. 双击 `feishu-bot/launch-console.command` 启动

### 菜单栏控制台是个啥（仅限 macOS）

`console.py` 是一个 macOS 顶部菜单栏小程序（用 `rumps` 做的），相当于给你的 bot 配了个**仪表盘**——你不用蹲在终端里盯着满屏日志，抬头看一眼菜单栏的小图标就知道公司还活着没：

- 🟢 **运行中**：一切安好，员工都在岗
- 🟡 **最近有告警**：刚才 60 秒内冒了点烟，点开看看
- 🔴 **已停止**：下班了 / 崩了

点开菜单栏图标，里面有这些按钮：

| 菜单项 | 作用 |
|--------|------|
| 状态: 🟢/🟡/🔴 | 显示当前死活，不可点，纯看 |
| 启动 / 停止 / 重启 | 一键开关 bot，不用记命令 |
| 查看实时日志… | 弹出滚动日志，看 bot 正在嘀咕什么 |
| 最近一次错误… | 直接给你看上次摔哪了，还附**中文人话版**排错提示 |
| 崩溃自动重启 | 打开后，bot 摔了会自己爬起来（按 2s → 8s → 30s 的节奏退避重试） |
| 打开日志目录 | 在访达里打开 `logs/`，方便你翻旧账 |
| 退出控制台 | 关掉仪表盘（注意：这会一并把 bot 停掉） |

**怎么用**：双击 `launch-console.command` → 菜单栏右上角出现图标 → 点"启动" → 图标变 🟢 就代表 bot 上岗了，现在可以去飞书发消息了。出问题时先点"最近一次错误…"，八成能看懂是咋回事。

> 非 macOS 的同学：这个图形控制台用不了（`rumps` 是 Mac 专属，启动脚本也写死了 `./.venv/bin/python` 路径）。但不影响主业——直接 `cd feishu-bot && ./.venv/bin/python bot.py` 把 bot 跑起来就行，只是少了菜单栏那点仪式感。

---

## 常见问题

**Q: Elon 怎么知道该找 Jobs 还是 Linus？**  
A: 靠每个 subagent 文件里的 `description` 字段。Claude Code 会把全员的"岗位说明"摆在 Elon 面前，他看任务性质对号入座。

**Q: Turing 的交叉验证是怎么做的？**  
A: Turing 有 `Agent` 工具权限，能另起一个独立的 Claude 实例（用 opus 模型）从零审查 Linus 的代码。两个脑子互相挑刺，总比自己改自己的作业靠谱。

**Q: 可以只用 Claude，不用 Codex 吗？**  
A: 当然。`.codex/` 目录搁那儿不碍事，Claude 侧照常运行。

**Q: 记忆会不会越积越多，最后撑爆？**  
A: `memory/sessions/` 已 gitignore。`memory/stable/` 得你自己当管家，定期清掉过期的破烂。

**Q: 能不能让一堆 Agent 同时开工？**  
A: Claude Code 支持并行 subagent，但能不能真并行，看任务拆不拆得开。Elon 默认排队干；你要是明说"这三件事互不相干，一起上"，他才会并行调用。

---

## 迭代建议

1. **先跑通最小闭环**：就用 Elon + Linus，把一个真任务跑完整，再考虑扩编
2. **把口味写进 memory/stable/**：技术栈、代码风格这些，写一次，省得天天复读
3. **agent prompt 慢慢调**：每次改动都用 git 记下来，调崩了能一键反悔
4. **飞书 Bot 是放大器，不是主角**：核心永远是 agent 系统，Bot 只是让你随时随地能喊话

---

## 局限与已知问题

开源就得把话挑明，省得你兴冲冲跳进来再骂街：

- **单机运行**：跑在你一台机器上，没有高可用，全靠机器常开；电脑一睡，每日推送这类定时任务也跟着睡。
- **每条消息冷启动**：飞书 Bot 用 `claude -p` 单次调用，没用 `--resume`，没有持久会话，上下文靠把历史硬塞进 prompt——所以慢，而且白白浪费 prompt cache。
- **记忆有损**：跨消息记忆靠摘要压缩（≤300 字），长对话会丢细节；记忆按会话存，不分具体是谁在说话。
- **多 Agent 链路不保证跑通**：在飞书单次调用 + 超时限制下，Elon → 子 Agent → 验证这条完整流水线可能跑一半断气，终端交互式使用更稳。
- **目前只认字**：飞书 Bot 暂时不处理图片 / 文件 / 语音，发表情包它是看不懂的。
- **每日推送靠第三方**：数据源是非官方公开 API，随时可能罢工，属于锦上添花、断了不影响主业。
- **安全边界**：开了 `--dangerously-skip-permissions` 之后，飞书可用范围内的成员约等于握着你机器的命令行——只给信得过的人用。

---

## License

Apache 2.0 — 见 [LICENSE](LICENSE)

---

## English Overview

**OPC (One-Person Company)** is a local multi-agent system built on Claude Code. You're the sole human (proud title: "Chairman"). You bark natural-language orders at **Elon (CEO Agent)**, who decomposes the work and delegates it to a staff of specialists who never ask for a raise:

- **Jobs** — product design, requirements, UX decisions
- **Linus** — coding, debugging, testing, scripts
- **Turing** — code review, cross-validation, professional nitpicking
- **Bezos** — customer emails, copywriting, talking to outsiders like a human

**No extra frameworks. No servers. Just Claude Code.** Your laptop is the headquarters; close the lid and the whole company clocks out.

### Quick Start

```bash
git clone https://github.com/YOUR_USERNAME/opc.git
cd opc
claude
```

Then just talk to Elon in plain language.

The system also supports [OpenAI Codex CLI](https://github.com/openai/codex) as an alternative runtime via `AGENTS.md` and `.codex/agents/`. Both runtimes share a file-based memory layer at `memory/` and `tasks/`.

Optional: a [Feishu (Lark) WebSocket Bot](feishu-bot/README.md) bridges your Feishu messages to the agent system — but note it only handles the *inbound trigger*; for actually operating Feishu, Lark's official [CLI](https://github.com/larksuite/cli) does it better. The menu-bar console is macOS-only.

### Customize

- Edit `CLAUDE.md` to change Elon's behavior and communication style
- Edit `.claude/agents/*.md` to modify any subagent's role
- Add new `.md` files to `.claude/agents/` to hire new specialists
- Put project context in `memory/stable/` so agents know your background
