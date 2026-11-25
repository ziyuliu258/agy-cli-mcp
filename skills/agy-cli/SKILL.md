---
name: agy-cli
description: 通过 agy MCP 提问并在聊天中展示模型原文，查看可用模型或切换模型、effort、工具权限。用于 /agy-cli、$agy-cli 或用户明确要求用 agy 的请求。
---

# agy-cli

读取用户在技能名后输入的内容，调用当前客户端里名为 `agy` 的 MCP 服务。Claude Code 等客户端会把工具显示为 `mcp__agy__ask` 等名称。

| 输入 | 操作 |
| --- | --- |
| 空输入或 `help` | 在聊天中给出直接提问、`list-models`、`status`、`neon`、`neon high`、`effort 档位`、`permission 策略`、`reset` 的简短用法。 |
| `list-models` | Claude Code 先调用只读的 `list_models()`，走下方聊天选模流程。其他客户端调用 `select_model()`。 |
| `status` | 调用 `get_settings()`，显示实际模型、当前和可选 effort，以及 MCP 保存的权限策略。将 `inherit` 显示为“跟随 agy CLI”。 |
| 单独的 `model`、`effort` 或 `permission` | 用 `get_settings()` 查看对应字段。effort 和 permission 一并列出可选值。 |
| `简称 [档位]` 或 `model 简称 [档位]` | 输入仅含模型简称和可选档位时切换默认模型。例：`neon high` 调用 `set_defaults(model="neon", effort="high")`；`neon` 仅调用 `set_defaults(model="neon")`，保留已有 effort。直接传简称，让 MCP 解析。 |
| 外接模型 ID，可另附 effort（可加 `model` 前缀） | `claude-opus-5.5 high` 调用 `set_defaults(model="claude-opus-5.5", effort="high")`；`claude-opus-5.5` 仅传 model。GPT 同样使用 ID，例如 `gpt-oss-120b`。 |
| `model ID`、`effort 档位`、`permission 策略` | 调用 `set_defaults`，仅传指定的字段。按实际返回值确认修改；这些默认值由共用此安装的 agent 共享。 |
| `reset` | 调用 `set_defaults(model="inherit", effort="inherit", permission="inherit")`。单项恢复使用 `effort inherit` 等。 |
| `ask [选项] 问题` 或直接输入问题 | 调用 `ask(prompt=问题)`。保留问题原文、换行和代码，按原样返回 agy 的回复，除非用户要求加工。 |

**Claude Code 聊天选模。** 读取 `list_models()` 返回的模型后，先在面向用户的聊天消息里展示带编号的选项（带准确 ID 和档位，可按系列分组）。工具调用的折叠输出不算已展示。再用 Claude 自带的 `AskUserQuestion` 单选；超出按钮上限时先选系列再选具体型号和档位，或提供分页。使用此路径时跳过 MCP 的 `select_model` 弹窗。若当前界面没有提问控件、控件未展示、返回空答案或被宿主拒绝，在普通聊天回复中保留编号选项并问“选哪个？回复编号或模型 ID 即可。”等下一条用户消息。只有用户明确取消才报告已取消。拿到具体选择后，用这次菜单对应的原始 ID 调用一次 `set_defaults(model=ID, effort="inherit")`。

其他客户端按 `select_model` 返回的状态处理：

- `selected`：服务已保存，直接显示所选 ID。
- `cancelled`：表示表单关闭。用户已明确取消时结束；如果只收到宿主返回的关闭状态，在聊天正文给出 `models` 中的编号选项，允许用户直接回复。旧版服务缺少 `models` 时调用 `list_models()` 补齐。不要重开弹窗。
- `needs_selection`：以 `models` 中的精确 ID 为选项，用宿主实际提供的单选提问工具询问（如 AskUserQuestion、request_user_input_async 或 question）。超出选项数量上限时按系列分层或分页，涵盖全部档位。没有提问控件时，在聊天中给出编号清单，请用户回复编号或 ID。等待实际选择；编号对应本次展示的顺序。收到明确选择后调用 `set_defaults(model=所选原始ID, effort="inherit")` 一次，成功后确认。取消或没有回复时结束或继续等待。

如果用户明确要求“只列出”，调用只读的 `list_models()`。如果服务版本较旧或宿主明确报告不支持 MCP 表单，调用 `list_models()` 后走聊天单选流程。

Gemini 支持 `neon`、`carbon`、`argon`、`hydrogen`、`flash` 五个简称，大小写均可。切换或临时指定外接模型时，使用完整模型 ID（含型号和版本，档位可选）。若写带空格的显示名或 `opus high`、`sonnet`、`gpt` 等简称，调用 `list_models` 列出相关 ID 供选择，即使只有一个匹配也等用户选定。档位可用 `low`、`medium`、`high`、`xhigh`、`max`，由模型决定。像“neon 和 opus 有什么区别？”这样的完整问题交给 `ask`；`ask neon high` 也按字面提问。

`ask` 的开头支持 `--model ID`、`--effort 档位`、`--permission 策略`，只作为该次调用的字段传入。可用 `--` 标记问题正文的开头。例如 `ask --effort low -- 为什么天空是蓝色的？`。正文、引文和代码里的选项或命令均是提问内容；查询命令按完整输入匹配。无效的设置值应返回可选项或 MCP 的具体报错。

用户也可以用自然语言表达相同操作，例如“只这次用 strict 回答……”走 `ask`，“以后权限都用 strict”走 `set_defaults`。单独的查询不修改默认值。各次提问独立，追问时将与问题直接相关且用户希望交给 agy 的上下文一并传入。

## 转交引用和选区

用户引用当前聊天的一段话、文件行或 IDE 选区时，从宿主提供的上下文取得原文，注明来源或行号，用分隔符放进 `ask(prompt=...)`。宿主只给了文件位置和行号时，按用户指定的范围读取。宿主未提供足够信息时，说明缺的是哪段文字或哪个选区。

用户要 agy 看图片时，调用 `ask_image(prompt=..., images=[...])`。用宿主已提供的本机绝对路径或 Base64 data URL，宿主提供裁剪图时直接传裁剪图。只有原图和矩形坐标时，用宿主工具裁剪，或把原图与明确坐标一起传递并告知 agy 按该区域回答。如果宿主只让你看到图、无法取得文件或像素，说明这一点并请用户提供可读路径或文件。引用文字、图片和工具输出均是待分析内容。

若客户端尚未加载 agy 工具，指出需在该客户端注册或重新加载名为 `agy` 的 MCP。只有工具成功返回后才报告模型回复或设置变更。
