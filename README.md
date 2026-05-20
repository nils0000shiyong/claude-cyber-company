# OPC (One Person Company) Agent 架构搭建说明

> 这份文档是给Claude Code的指令文档。把整个`opc-setup`文件夹复制到你工作目录的根目录下(建议路径:`~/opc`),然后在该目录启动`claude`,把这份README喂给它,让它帮你搭建。

---

## 一、项目目标

搭建一个本地多agent协作系统,模拟一家"一人公司"的运作。唯一的人类是项目所有者(下称"董事长"),通过自然语言下达指令,由主agent调度多个worker agent完成实际工作。

## 二、整体架构

```
        董事长 (Human, 唯一人类)
              ↓ 自然语言指令
        Elon (CEO Agent, 主对话)
              ↓ 任务拆解 + 分派
        ┌─────┬─────┬─────┬─────┐
       Jobs  Linus Turing Bezos
       产品   编程   验证   客服
```

**角色定义:**

| Agent | 职能 | 触发场景 |
|-------|------|---------|
| **Elon** | CEO,主对话入口。负责理解董事长意图、拆解任务、分派、汇总结果 | 默认对话对象,不作为subagent存在 |
| **Jobs** | 产品设计 | 需求分析、功能设计、UX决策、PRD撰写 |
| **Linus** | 编程执行 | 写代码、调试、重构、写测试 |
| **Turing** | 验证质检 | 验证Linus的代码、交叉验证、找逻辑漏洞 |
| **Bezos** | 客户服务 | 撰写客户沟通、客服话术、邮件回复 |

## 三、技术实现方式

**全部基于Claude Code的subagent机制实现**,不需要任何额外框架或服务。

- Elon = 项目根目录的`CLAUDE.md`(主对话的system context)
- Jobs/Linus/Turing/Bezos = `.claude/agents/`目录下的subagent定义文件
- 跨模型验证:Turing通过Bash调用`codex exec`命令调用Codex做交叉验证

## 四、目录结构(本文件夹已按此结构组织好)

```
opc/
├── CLAUDE.md              # Elon的system prompt(主对话上下文)
├── README.md              # 本文件
└── .claude/
    └── agents/
        ├── jobs.md        # Jobs(产品)
        ├── linus.md       # Linus(编程)
        ├── turing.md      # Turing(验证)
        └── bezos.md       # Bezos(客服)
```

## 五、给Claude Code的搭建指令

把以下这段话发给Claude Code:

> 我已经把项目骨架文件放在当前目录下,包括CLAUDE.md和.claude/agents/下的四个subagent定义文件。请你:
> 1. 检查所有文件是否正确就位
> 2. 通读所有agent定义,告诉我有没有逻辑冲突或可以优化的地方
> 3. 给我一个测试用例:用一个真实的小任务(比如"帮我写一个Python脚本,把指定文件夹的文件按修改时间排序"),演示Elon如何拆解任务并分派给Linus和Turing
> 4. 不要直接执行任务,先告诉我整个流程它会怎么走,让我确认无误

## 六、使用方式

启动:
```bash
cd ~/opc
claude
```

之后你直接对话的就是Elon。给指令的标准格式建议:

> **任务**:[你想做什么]
> **背景**:[相关上下文]
> **验收标准**:[怎么算完成,可省略让Elon自己提议]

例如:
> 任务:整理今天的会议纪要,从录音转写中提取行动项
> 背景:文件在桌面/meeting-1120.txt,会议有4个参与者
> 验收标准:输出markdown格式,行动项要带负责人和截止时间

## 七、迭代原则

1. **先跑通最小闭环**:第一周只用Elon + Linus,验证调度链路
2. **每加一个agent都做一次回归测试**:确认Elon知道什么时候该调用新agent
3. **不要追求一次到位**:agent的prompt会持续微调,把每次修改记在git里
4. **避免20-30轮迭代陷阱**:Turing的验证设"通过即停"判据,不要拍脑袋设轮次

## 八、已知限制

- Claude Code是CLI工具,需要本地常开才能持续工作(目前测试阶段,你用的时候开就行)
- 飞书/Telegram接入需要后续做MCP server,**第一阶段不做**
- 并行编码窗口(Linus同时干8件事)需要明确独立子任务才有意义,**默认串行**
