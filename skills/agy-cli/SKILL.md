---
name: agy-cli
description: 通过 agy MCP 提问并在聊天中展示模型原文，查看可用模型或切换模型、effort、工具权限。用于 /agy-cli、$agy-cli 或用户明确要求用 agy 的请求。
---

# agy-cli

读取用户在技能名后输入的内容，调用当前客户端里名为 `agy` 的 MCP 服务。Claude Code 等客户端会把工具显示为 `mcp__agy__ask` 等名称。

| 输入 | 操作 |
| --- | --- |
| 空输入或 `help` | 在聊天中给出直接提问、`models`、`status`、`neon`、`neon high`、`effort 档位`、`permission 策略`、`reset` 的简短用法。 |
| `models` | 调用 `list_models()`，以可复制的模型 ID 为主。Claude 的版本可写作点号，例如 `claude-opus-5.5`，将 effort 单列。 |
| `status` | 调用 `get_settings()`，显示实际模型、当前和可选 effort，以及 MCP 保存的权限策略。将 `inherit` 显示为“跟随 agy CLI”。 |
| 单独的 `model`、`effort` 或 `permission` | 用 `get_settings()` 查看对应字段。effort 和 permission 一并列出可选值。 |
| `简称 [档位]` 或 `model 简称 [档位]` | 输入仅含模型简称和可选档位时切换默认模型。例：`neon high` 调用 `set_defaults(model="neon", effort="high")`；`neon` 仅调用 `set_defaults(model="neon")`，保留已有 effort。直接传简称，让 MCP 解析。 |
| 外接模型 ID，可另附 effort（可加 `model` 前缀） | `claude-opus-5.5 high` 调用 `set_defaults(model="claude-opus-5.5", effort="high")`；`claude-opus-5.5` 仅传 model。GPT 同样使用 ID，例如 `gpt-oss-120b`。 |
| `model ID`、`effort 档位`、`permission 策略` | 调用 `set_defaults`，仅传指定的字段。按实际返回值确认修改；这些默认值由共用此安装的 agent 共享。 |
| `reset` | 调用 `set_defaults(model="inherit", effort="inherit", permission="inherit")`。单项恢复使用 `effort inherit` 等。 |
| `ask [选项] 问题` 或直接输入问题 | 调用 `ask(prompt=问题)`。保留问题原文、换行和代码，按原样返回 agy 的回复，除非用户要求加工。 |

Gemini 支持 `neon`、`carbon`、`argon`、`hydrogen`、`flash` 五个简称，大小写均可。切换或临时指定外接模型时，使用完整模型 ID（含型号和版本，档位可选）。若写带空格的显示名或 `opus high`、`sonnet`、`gpt` 等简称，调用 `list_models` 列出相关 ID 供选择，即使只有一个匹配也等用户选定。档位可用 `low`、`medium`、`high`、`xhigh`、`max`，由模型决定。像“neon 和 opus 有什么区别？”这样的完整问题交给 `ask`；`ask neon high` 也按字面提问。

`ask` 的开头支持 `--model ID`、`--effort 档位`、`--permission 策略`，只作为该次调用的字段传入。可用 `--` 标记问题正文的开头。例如 `ask --effort low -- 为什么天空是蓝色的？`。正文、引文和代码里的选项或命令均是提问内容；查询命令按完整输入匹配。无效的设置值应返回可选项或 MCP 的具体报错。

用户也可以用自然语言表达相同操作，例如“只这次用 strict 回答……”走 `ask`，“以后权限都用 strict”走 `set_defaults`。单独的查询不修改默认值。各次提问独立，追问时将与问题直接相关且用户希望交给 agy 的上下文一并传入。

若客户端尚未加载 agy 工具，指出需在该客户端注册或重新加载名为 `agy` 的 MCP。只有工具成功返回后才报告模型回复或设置变更。
