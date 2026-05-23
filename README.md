# OPC — 一人公司 AI Agent 系统

> **One-Person Company** — A local multi-agent collaboration system built on Claude Code & Codex. One human, five AI roles, real work done.

[中文文档] | [English below](#english-overview)

---

## 这是什么？

OPC 是一套基于 Claude Code 的本地多 Agent 协作框架。你是唯一的人类（"董事长"），通过自然语言下达指令，由主 Agent **Elon（CEO）** 理解、拆解、分派给专职 worker agent，最终汇总交付。

**不需要额外框架，不需要 API 密钥管理，不需要服务器。** 全程跑在你本地的 Claude Code CLI 上。

```
        你（人类）
           │ 自然语言指令
        Elon（CEO Agent）
           │ 任务拆解 + 分派
    ┌──────┼──────┬──────┐
   Jobs  Linus  Turing Bezos
   产品   编程   验证   客服
```

| Agent | 职能 | 工具权限 |
|-------|------|---------|
| **Elon** | CEO，主对话入口，理解 → 拆解 → 分派 → 汇总 | Claude Code 全部工具 |
| **Jobs** | 产品设计，需求分析，PRD 撰写，UX 决策 | Read, Write, Edit, WebSearch, WebFetch, Glob, Grep |
| **Linus** | 编程执行，写代码，调试，重构，跑测试 | Read, Write, Edit, Bash, Glob, Grep |
| **Turing** | 验证质检，代码审查，交叉验证，逻辑漏洞排查 | Read, Bash, Glob, Grep, WebSearch, WebFetch, Agent |
| **Bezos** | 对外沟通，客户邮件，客服话术，社交媒体回复 | Read, Write, Edit, WebSearch |

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
├── memory/                    # Claude / Codex 唯一共享记忆层
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
    ├── console.py             # macOS 菜单栏控制台
    ├── daily_hotnews.py       # 每日 AI 热点推送
    ├── error_hints.py         # 中文错误提示
    ├── requirements.txt
    ├── .env.claude.example    # Claude Bot 配置模板
    ├── .env.codex.example     # Codex Bot 配置模板
    └── launch-console.command # 双击启动控制台
```

---

## 快速开始（5 分钟）

### 前置条件

- [Claude Code](https://docs.anthropic.com/claude-code) CLI 已安装并登录
- Git

Codex 支持为可选项，没有也能用。

### 第一步：克隆项目

```bash
git clone https://github.com/YOUR_USERNAME/opc.git
cd opc
```

### 第二步：启动

```bash
claude
```

就这样。你现在在和 **Elon** 对话了。

### 第三步：给第一个指令

建议先用一个简单任务热身，让 Elon 展示分派流程：

```
任务：帮我写一个 Python 脚本，把指定文件夹内的文件按修改时间从新到旧排序并打印
验收标准：脚本能接受路径参数，输出格式清晰，有注释
```

Elon 会：
1. 输出任务卡确认理解
2. 分派给 **Linus** 写代码
3. 分派给 **Turing** 验证
4. 汇总交付给你

---

## 如何下达指令

推荐格式（可省略任何部分，Elon 会补问）：

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

**不需要告诉 Elon 该找哪个 agent。** 他自己判断。

---

## 双平台支持（Claude + Codex）

本项目同时支持 Claude Code 和 OpenAI Codex CLI，共用相同的记忆层：

| 平台 | 主入口 | Agent 定义 | 启动命令 |
|------|--------|-----------|---------|
| Claude Code | `CLAUDE.md` | `.claude/agents/*.md` | `claude` |
| Codex | `AGENTS.md` | `.codex/agents/*.toml` | `codex` |

**隔离原则**：两个平台的 agent 定义互不污染。Claude 只读 `.claude/`，Codex 只读 `.codex/`。两者唯一的共享层是 `memory/` 和 `tasks/`。

---

## 记忆系统

`memory/` 目录是 Claude 和 Codex 之间的文件级共享记忆：

| 目录 | 用途 | 写入规则 |
|------|------|---------|
| `memory/stable/` | 已验证的长期事实（公司背景、决策记录） | 标注日期、来源、置信度 |
| `memory/working/` | 当前任务的阶段性上下文、草稿 | 任务结束后清理 |
| `memory/inbox/` | 平台间交接摘要 | 只写必要摘要，不写完整历史 |

**建议在 `memory/stable/` 放你的公司/项目背景**，这样 Elon 就不需要每次重新问你是谁在做什么。

---

## 自定义你的 Agent 团队

### 修改 Elon 的行为

编辑 `CLAUDE.md`（Elon 的 system prompt）：
- 修改"跟董事长沟通的风格"部分，适配你自己的偏好
- 修改"分派决策原则"，增减 agent 分工边界

### 添加新 Agent

在 `.claude/agents/` 下新建一个 `.md` 文件：

```markdown
---
name: agentname
description: 一句话说明什么时候调用这个 agent（Elon 靠这个判断分派）
tools: Read, Write, Edit, Bash
model: sonnet
---

你是 [角色名]，负责 [职责]。

[角色 system prompt...]
```

### 修改现有 Agent

直接编辑 `.claude/agents/` 下对应的 `.md` 文件。修改后立即生效，不需要重启。

### 个人本地配置

复制并编辑：

```bash
cp .claude/settings.local.example.json .claude/settings.local.json
```

`settings.local.json` 已被 gitignore，用于存放你自己机器上特有的路径或权限配置。

---

## 飞书 Bot（可选）

如果你希望通过飞书消息直接跟 Elon 对话，而不是开终端，可以启用飞书 Bot。

```
你的飞书消息 → 飞书 Bot → Claude/Codex CLI → 回复
```

详细配置见 [feishu-bot/README.md](feishu-bot/README.md)。

核心步骤：
1. 在飞书开放平台创建应用，获取 App ID 和 App Secret
2. 复制 `feishu-bot/.env.claude.example` → `feishu-bot/.env`，填入凭证
3. 安装依赖：`cd feishu-bot && python3.10 -m venv .venv && .venv/bin/pip install -r requirements.txt`
4. 双击 `feishu-bot/launch-console.command` 启动

---

## 常见问题

**Q: Elon 怎么知道该找 Jobs 还是 Linus？**  
A: 靠每个 subagent 定义文件里的 `description` 字段。Claude Code 会把所有 agent 的描述都给 Elon 看，Elon 根据任务性质自行判断。

**Q: Turing 的交叉验证是怎么做的？**  
A: Turing 有 `Agent` 工具权限，可以启动一个独立的 Claude 实例（用 opus 模型）从零审查 Linus 的代码。两份独立判断，比自我审查可靠得多。

**Q: 可以只用 Claude，不用 Codex 吗？**  
A: 完全可以。`.codex/` 目录存在但不影响 Claude 侧的运行。

**Q: 记忆会不会越积越多？**  
A: `memory/sessions/` 已 gitignore。`memory/stable/` 需要你主动维护，建议定期清理过时的条目。

**Q: 能不能并行跑多个 Agent？**  
A: Claude Code 支持并行 subagent，但实际效果取决于任务是否真的可以独立拆分。Elon 默认串行分派；如果你明确说"这三件事互相独立，并行做"，Elon 会并行调用。

---

## 迭代建议

1. **先跑最小闭环**：只用 Elon + Linus，跑通一个真实任务，再加其他 agent
2. **把偏好写进 memory/stable/**：比如你的技术栈偏好、代码风格要求，不用每次重复说
3. **agent prompt 持续微调**：用 git 追踪每次改动，方便回滚
4. **飞书 Bot 是放大器**：核心是 agent 系统，Bot 只是让你随时随地能发指令

---

## License

Apache 2.0 — 见 [LICENSE](LICENSE)

---

## English Overview

**OPC (One-Person Company)** is a local multi-agent system built on Claude Code. You give natural language instructions to **Elon (CEO Agent)**, who decomposes tasks and delegates to specialized subagents:

- **Jobs** — product design, requirements, UX decisions
- **Linus** — coding, debugging, testing, scripts
- **Turing** — code review, cross-validation, fact-checking
- **Bezos** — customer emails, copywriting, external comms

**No extra frameworks. No servers. Just Claude Code.**

### Quick Start

```bash
git clone https://github.com/YOUR_USERNAME/opc.git
cd opc
claude
```

Then talk to Elon in natural language.

The system also supports [OpenAI Codex CLI](https://github.com/openai/codex) as an alternative runtime via `AGENTS.md` and `.codex/agents/`. Both runtimes share a file-based memory layer at `memory/` and `tasks/`.

Optional: a [Feishu (Lark) WebSocket Bot](feishu-bot/README.md) bridges your Feishu messages to the agent system.

### Customize

- Edit `CLAUDE.md` to change Elon's behavior and communication style
- Edit `.claude/agents/*.md` to modify any subagent's role
- Add new `.md` files to `.claude/agents/` to create new specialists
- Put project context in `memory/stable/` so agents know your background
