# agy CLI MCP

通过支持本地 stdio MCP 的 agent 调用 Antigravity CLI。使用 `list_models()` 列出模型，`ask` 提问，`get_settings()` 查看配置，`set_defaults` 切换默认设置。回复保留模型的原文和 Markdown。每次提问独立执行，追问时请把所需上下文一起传入。

## 让 agy 看引用和图片

宿主读取用户指定的聊天原文、代码或 IDE 选区，再将文本放进 `ask`。传图片使用 `ask_image(prompt, images, model?, effort?)`，`images` 接受 1 至 4 个本机绝对路径或 Base64 data URL，支持 PNG、JPEG、WebP（单张最多 8 MiB）。框选截图优先传宿主提供的裁剪图。若宿主只提供原图和坐标，也可在问题中注明选区范围。

图片会经 `agy acp` 作为原始像素送入模型。该调用使用 agy 的 ACP 会话并拒绝其中的审批请求。宿主需要把引用内容或文件交给 skill，客户端对选区和附件的访问方式取决于各自的集成。[Antigravity ACP](https://antigravity.google/docs/cli/acp/)

## 在目标机器安装

1. 准备 Python 3.10 或更高版本，安装 Antigravity CLI 并在运行 agent 的系统账号下完成登录。在终端执行 `agy models`，确认能看到模型列表。[Google 官方安装说明](https://antigravity.google/docs/getting-started?tab=cli)
2. 解压安装包，进入含有 `install.py` 的 `agy-cli-mcp` 目录，在终端运行下面的命令。首次安装需要联网下载 Python 依赖。

   **Linux / macOS**

   ```sh
   python3 install.py
   ```

   **Windows PowerShell**

   ```powershell
   py -3 install.py
   ```

3. 安装器会打印两条已填好本机绝对路径的命令。使用 **Claude Code** 时执行以 `claude` 开头的那条，使用 **Codex** 时执行以 `codex` 开头的那条。Windows 上两条命令使用 PowerShell 调用语法。
4. 其他桌面 agent 可在 MCP 设置中选择本地 **stdio** 类型。打开安装器打印的 `mcp-config.json`，把 `mcpServers.agy` 条目合并到客户端已有的 MCP 配置。如果界面分别要求名称、命令和参数，就填 `agy`、`command` 的完整路径，以及 `args` 中按顺序排列的各项。参数数组中的每项各占一个参数，路径里的空格一并保留。
5. 在客户端重新加载 MCP 或开启新会话，先发送「列出 agy 可用的模型」，再试「用 agy 回答：为什么天空是蓝色的？把它的原文显示在这里。」

## 使用 agy-cli 技能

在解压目录里运行 `python3 install.py --skill codex` 或 `python3 install.py --skill claude`。需要两个客户端时运行 `python3 install.py --skill codex --skill claude`。Windows 将 `python3` 换成 `py -3`。首次接入的客户端还需执行安装器打印的对应 MCP 注册命令。已注册并使用相同安装路径的客户端可直接复用。

Claude Code 使用 `/agy-cli`，Codex 可使用 `$agy-cli` 选择技能。下面以 Claude Code 写法为例，Codex 选中技能后输入相同的参数。[Claude Code 技能](https://code.claude.com/docs/en/skills) · [Codex 技能](https://developers.openai.com/codex/skills/)

```text
/agy-cli 帮我解释什么是梯度累积
/agy-cli list-models
/agy-cli status
/agy-cli neon high
/agy-cli neon
/agy-cli claude-opus-5.5 high
/agy-cli gpt-oss-120b-medium
/agy-cli effort high
/agy-cli permission strict
/agy-cli ask --effort low -- 用一句话解释过拟合
/agy-cli reset
```

直接写 `neon high` 会同时切换默认模型和 effort，单写 `neon` 只切模型，保留已有的 effort 配置。支持的简称还有 `carbon`、`argon`、`hydrogen` 和 `flash`。若目标模型不支持保留的档位，设置会报错，原配置继续生效。

Claude、GPT 等外接模型在切换和单次提问时均使用模型 ID。例如 `/agy-cli claude-opus-5.5 high` 同时指定模型和档位，`/agy-cli claude-opus-5.5` 只切换模型。CLI 使用连字符表示版本时，MCP 会将点号版本对应到实际 ID。也可从 `/agy-cli list-models` 直接复制 CLI 的原始 ID。

模型、effort 和权限子命令带值时会保存默认值，省略值时查询当前设置。`ask` 的选项仅用于当前问题。其他兼容 Agent Skills 的客户端也可以把包内的 `skills/agy-cli` 目录复制到自己的技能目录，再连接 `agy` MCP。

## 交互选模及其他 harness

`/agy-cli list-models` 会从当前账号读取模型，显示“为后续 agy 请求选择默认模型”的单选问题。每个选项对应一个精确 ID，包含该模型提供的档位。提交后自动保存，取消会保留之前的配置。仅想查看清单时可说“只列出 agy 模型”。

Claude Code 先在聊天正文展示带编号的模型选项，再通过原生选择按钮或回复编号选定。其他支持表单的客户端通过标准 MCP 表单请求选择。客户端未声明表单能力时，由 skill 使用该客户端的提问控件；只有文本聊天时，会给出编号列表，回复编号或完整 ID 即可。多个客户端共用同一安装时，保存的默认值也共享。

在解压目录中执行以下命令可安装另外四个客户端的入口，`--skill` 可按需选用。Windows 将 `python3` 换成 `py -3`。

```sh
python3 install.py --skill pi --skill dsh --skill opencode --skill openchamber
```

| 客户端 | 入口与首次注册 |
| --- | --- |
| Pi | 安装器写入个人 skill 和 `prompts/agy-cli.md`，使用 `/agy-cli list-models`。执行安装器打印的 `pi mcp add` 命令。只有桌面版时，可把生成的 `mcp-config.json` 中的 agy 条目合并到 Pi 用户目录的 `mcp.json`。 |
| DeepSeek Harness（DSH） | skill 位于 `$DSH_HOME/skills`，默认 `~/.dsh/skills`。将安装目录中生成的 `dsh-agy.patch.yml` 列表项合并到目标 profile 的 `cordis.patch.yml`，加载该 profile。带技能入口的界面可用 `/agy-cli list-models`。 |
| OpenCode | 安装器写入用户目录的 `skills/agy-cli` 和 `commands/agy-cli.md`。执行打印的 `opencode mcp add --global` 命令，再输入 `/agy-cli list-models`。 |
| OpenChamber | 使用其连接的 OpenCode 后端上的同一份 MCP 配置和命令。如果后端在容器或远程机器，在该后端安装并注册。 |
| 其他 harness | 支持 stdio MCP 的客户端可导入生成的 command 和 args；支持 Agent Skills 的客户端可复制包内的 `skills/agy-cli`。仅支持 MCP 工具时直接调用 `select_model`；若返回 `needs_selection`，展示 models 并在用户选定后用精确 ID 调用 `set_defaults(model=ID, effort="inherit")`。 |

[Pi MCP 配置](https://docs.pi.dev/latest/mcp) · [DSH MCP 客户端](https://github.com/deepseek-ai/deepseek-harness/tree/master/packages/mcp/mcp-client) · [OpenCode 命令](https://opencode.ai/docs/commands) · [OpenChamber 后端](https://github.com/openchamber/openchamber)

## 在聊天里切换模型、effort 和权限

| 想做的事 | 可以直接对 agent 说 |
| --- | --- |
| 查看当前设置 | “查看 agy 的默认设置、实际模型，以及这个模型支持的 effort。” |
| 切换默认模型 | “以后 agy 用 Gemini 4 Neon，默认 effort 用 high。” |
| 临时切换档位 | “只在这一次用 low effort，让 agy 解释这段代码。” |
| 临时收紧权限 | “这次用 agy 的 strict 权限回答，保留回复原文。” |
| 切换默认权限 | “把 agy MCP 的默认权限改成 request-review。” |
| 恢复默认 | “把 agy MCP 的模型、effort 和权限都恢复为跟随 CLI。” |

**工具参数。** `ask(prompt, model?, effort?, permission?)` 只覆盖这一次。`set_defaults(model?, effort?, permission?)` 保存到当前安装目录的 `defaults.sqlite3`，共用此安装的 agent 在下次调用时读取。省略字段会沿用现有值；显式传 `inherit` 会让该字段跟随 CLI。选择带档位的模型 ID 时会采用 ID 自带的档位，若同时传入 effort，则以显式 effort 为准。保存模型和 effort 之前会用 agy 校验组合。查看实际生效的模型和可选档位用 `get_settings()`。

**权限选项。** 这些设置控制 agy 在回答过程中调用工具的方式。显式选策略时，MCP 会对该次 agy 进程设置默认执行模式，让所选权限策略生效。无交互调用中，需要人工确认的动作会被拒绝，模型仍可继续回答。[agy 非交互模式](https://antigravity.google/docs/cli/headless/)

| permission | 行为 |
| --- | --- |
| `inherit` | 跟随 agy 自身的执行模式和权限配置。初次安装采用此值。 |
| `strict` | 每次工具动作都要求审批，包括文件读取。 |
| `request-review` | 按 CLI 规则处理，写入、命令、网络等需要审批的动作须有相应授权。 |
| `proceed-in-sandbox` | 启用 agy 终端沙箱，允许符合规则的沙箱内命令。宿主不支持沙箱时，CLI 回退到请求审批。 |
| `always-proceed` | 允许工具自动执行，已有的 ask 和 deny 规则仍生效。 |

可选 effort 有 `low`、`medium`、`high`、`xhigh`、`max`，具体档位由当前模型决定。升级已有安装时，在新包里重新运行安装脚本，再让客户端重新加载 MCP。安装路径相同即可沿用原来的注册和已保存的偏好。[agy effort 说明](https://antigravity.google/docs/cli/commands/effort/) · [agy 权限说明](https://antigravity.google/docs/cli/settings)

## 安装位置和运行条件

Linux / macOS 默认安装到 `~/.local/share/agy-cli-mcp`，Windows 默认安装到 `%LOCALAPPDATA%\agy-cli-mcp`。安装后可以移走下载的压缩包和解压目录。安装器会记录本机的 CLI 路径，每换一台机器都请重新运行安装器。每个 agent 单独注册，同一机器的多个 agent 可以共用一份安装。

如需指定 CLI 或安装路径，可运行 `python3 install.py --agy-bin "/完整路径/agy" --install-dir "/目标目录/agy-cli-mcp"`。安装器优先使用现有的 uv，否则使用 Python 自带的 venv 和 pip。

服务复用目标机器的 agy 登录状态。如果终端能用而桌面 agent 无法连接，请确认二者使用同一账号，并在需要代理时让 agent 的 MCP 进程继承相应代理变量。较长的问题可能需要提高客户端的工具调用超时，建议设为 630 秒，服务自身最多等待 agy 生成 600 秒。
