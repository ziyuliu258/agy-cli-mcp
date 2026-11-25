"""An MCP stdio bridge for the authenticated Antigravity CLI."""
import argparse
import base64
import json
import os
import re
import shutil
import sqlite3
from contextlib import closing
from pathlib import Path
from subprocess import DEVNULL
from tempfile import TemporaryDirectory
from typing import Literal, get_args

import anyio
from anyio.streams.buffered import BufferedByteReceiveStream
from mcp import McpError, types
from mcp.server.fastmcp import Context, FastMCP

mcp = FastMCP("agy", instructions=(
    "When the user asks to consult an agy model, use ask. "
    "For user-referenced text or an editor selection, include the exact relevant excerpt in prompt. "
    "For user-referenced images, use ask_image with local image paths or Base64 image data. "
    "Pass a crop for a screenshot selection when available. Say when the host has not provided "
    "the referenced content. "
    "Show its reply directly in the chat, preserving its language and Markdown, "
    "unless the user requests a summary or further processing. Use ask parameters for one turn. "
    "In Claude Code, list_models then show numbered choices in chat and use AskUserQuestion if available. "
    "In other hosts, use select_model for interactive selection. On needs_selection, "
    "ask using the returned IDs and wait. A closed form alone does not establish user intent; "
    "if the user did not explicitly cancel, show the returned choices in chat for a numbered reply. "
    "Apply the selected ID via set_defaults with "
    "effort='inherit'. For a read-only catalog use list_models. "
    "Use set_defaults only when the user requests a lasting change. Choose permissions only "
    "as requested by the user."
))
AGY = os.environ.get("AGY_BIN") or shutil.which("agy") or str(Path.home() / ".local/bin/agy")
ASK_SECONDS = 600

Effort = Literal["inherit", "low", "medium", "high", "xhigh", "max"]
EFFORT_LEVELS = set(get_args(Effort)) - {"inherit"}
GEMINI_SHORTCUTS = {"neon", "carbon", "argon", "hydrogen", "flash"}
Permission = Literal["inherit", "strict", "request-review", "proceed-in-sandbox", "always-proceed"]
DB = Path(__file__).resolve().with_name("defaults.sqlite3")
INHERITED = dict.fromkeys(("model", "effort", "permission"), "inherit")


def preference_store():
    conn = sqlite3.connect(DB)
    conn.execute("CREATE TABLE IF NOT EXISTS defaults (name TEXT PRIMARY KEY, value TEXT NOT NULL)")
    return conn


def saved_options(conn):
    return {**INHERITED, **dict(conn.execute("SELECT name, value FROM defaults"))}


async def resolve_model(name):
    if name == "inherit" or name.startswith("gemini-"):
        return name, False
    key = name.casefold()
    # Some agy IDs encode a dotted version as separate hyphenated numbers.
    cli_spelling = re.sub(r"(?<=[0-9])\.(?=[0-9])", "-", name)
    choices = set()
    for line in (await list_models()).splitlines():
        model_id, tab, label = line.partition("\t")
        if not tab:
            continue
        gemini = model_id.startswith("gemini-")
        family, _, tier = model_id.rpartition("-")
        if key in GEMINI_SHORTCUTS:
            if gemini and tier in EFFORT_LEVELS and key in family.split("-"):
                choices.add((family, True))
        elif model_id in (name, cli_spelling) or (gemini and key == label.strip().casefold()):
            choices.add((model_id, False))
        elif tier in EFFORT_LEVELS and "-" in family:
            full_name = label.strip().casefold().removesuffix(f" ({tier})")
            if family in (name, cli_spelling) or (gemini and key == full_name):
                choices.add((family, True))
    if len(choices) == 1:
        return choices.pop()
    if choices:
        raise ValueError(f"{name} 匹配多个模型，请使用完整 ID：" + "、".join(sorted(model_id for model_id, _ in choices)))
    raise ValueError(f"无法选择 {name}。请用 /agy-cli list-models 查看完整模型 ID。")


async def combine(previous, model, effort, permission):
    options = previous.copy()
    if model is not None:
        model = model.strip()
        if not model:
            raise ValueError("请输入模型 ID，或用 inherit 跟随 CLI。")
        model, is_family = await resolve_model(model)
        if is_family:
            previous_tier = previous["model"].rpartition("-")[2]
            if effort is None and previous["effort"] == "inherit" and previous_tier in EFFORT_LEVELS:
                # Older settings can encode an explicit tier solely in the model ID.
                model = f"{model}-{previous_tier}"
        options["model"] = model
        if model.rpartition("-")[2] in EFFORT_LEVELS:
            options["effort"] = "inherit"
    if effort is not None:
        options["effort"] = effort
    if permission is not None:
        options["permission"] = permission
    return options


def model_flags(options):
    model, effort = options["model"], options["effort"]
    flags = []
    if model != "inherit":
        family, _, tier = model.rpartition("-")
        if family and tier in EFFORT_LEVELS and effort not in ("inherit", tier):
            model = family
        flags.append(f"--model={model}")
    if effort != "inherit":
        flags.append(f"--effort={effort}")
    return flags


async def inspect_model(options, command):
    args = [*model_flags(options), "--output-format=json", "--print", command]
    out, err, code = await run_agy(args, 60)
    if not out.strip():
        raise RuntimeError(err or f"agy 查询失败（退出码 {code}）。")
    result = json.loads(out)
    if code or result.get("status") != "SUCCESS":
        raise ValueError(result.get("error") or err or "agy 拒绝了该模型或 effort。")
    return result["command"]["data"]


@mcp.tool()
async def get_settings() -> dict:
    """Show shared MCP defaults, effective agy model, and its supported effort levels.
    'inherit' means agy chooses that setting. Permissions apply to agy tool use.
    """
    with closing(preference_store()) as conn:
        options = saved_options(conn)
    return {
        "defaults": options,
        "active_model": await inspect_model(options, "/model"),
        "effort": await inspect_model(options, "/effort"),
        "permission_choices": list(get_args(Permission)),
    }


@mcp.tool()
async def set_defaults(model: str | None = None, effort: Effort | None = None,
                       permission: Permission | None = None) -> dict:
    """Save defaults shared by all clients using this installation, only on explicit request.
    Use external model IDs such as claude-opus-5.5, optionally with a separate effort.
    Gemini accepts shortcuts such as neon. A shortcut alone keeps
    the saved effort. Pass effort separately to switch both. Set 'inherit' to remove an
    override. Choosing an exact tiered model also selects its tier unless effort is given. To reset all, use
    'inherit' for all three. always-proceed allows unattended tools per agy rules.
    """
    with closing(preference_store()) as conn:
        previous = saved_options(conn)
        updated = await combine(previous, model, effort, permission)
        if updated == previous:
            return updated
        if (model is not None or effort is not None) and (
            updated["model"] != "inherit" or updated["effort"] != "inherit"
        ):
            await inspect_model(updated, "/model")
        with conn:
            conn.execute("BEGIN IMMEDIATE")
            if saved_options(conn) != previous:
                raise RuntimeError("另一客户端刚更新了默认设置，请重新读取后再试。")
            conn.executemany("INSERT OR REPLACE INTO defaults VALUES (?, ?)", updated.items())
        return updated


async def run_agy(args: list[str], seconds: int, data: bytes = b"") -> tuple[str, str, int]:
    with TemporaryDirectory(prefix="agy-mcp-") as directory:
        try:
            with anyio.fail_after(seconds):
                proc = await anyio.run_process(
                    [AGY, *args], input=data, cwd=directory, check=False,
                )
        except TimeoutError as exc:
            raise RuntimeError(f"agy 请求在 {seconds} 秒后超时。") from exc
    return proc.stdout.decode(), proc.stderr.decode(errors="replace").strip(), proc.returncode


@mcp.tool(structured_output=False)
async def list_models() -> str:
    """List the model IDs and display names currently available through agy."""
    stdout, stderr, code = await run_agy(["models"], 60)
    if code or not stdout.strip():
        raise RuntimeError(stderr or f"agy models 未返回模型列表（退出码 {code}）。")
    return stdout.strip()


@mcp.tool()
async def select_model(ctx: Context) -> dict:
    """Ask the user to pick an agy default from the live catalog. If the host
    needs to ask in chat, return the choices and wait for an explicit selection.
    """
    choices = {}
    for line in (await list_models()).splitlines():
        model_id, tab, label = line.partition("\t")
        if tab and model_id:
            choices[model_id] = label.strip()
    if not choices:
        raise RuntimeError("agy 没有提供可选择的模型。")
    fallback = {"status": "needs_selection", "models": choices}
    client = ctx.session.client_params
    # Claude surfaces can advertise forms but return cancel without showing them.
    if client and "claude" in client.clientInfo.name.casefold():
        return fallback
    support = client.capabilities.elicitation if client else None
    # An empty elicitation capability advertises legacy form support.
    if support is None or (support.form is None and support.url is not None):
        return fallback
    schema = {
        "type": "object",
        "properties": {"model": {"title": "模型 ID（含档位）", "type": "string", "enum": list(choices)}},
        "required": ["model"],
    }
    try:
        answer = await ctx.session.elicit_form(
            "为后续 agy 请求选择默认模型", schema, related_request_id=ctx.request_context.request_id
        )
    except McpError as exc:
        if exc.error.code in (types.METHOD_NOT_FOUND, types.INVALID_PARAMS):
            return fallback
        raise
    if answer.action != "accept":
        return {"status": "cancelled", "models": choices}
    selected = (answer.content or {}).get("model")
    if not isinstance(selected, str) or selected not in choices:
        raise ValueError("请选择本次列表中的一个模型。")
    defaults = await set_defaults(model=selected, effort="inherit")
    return {"status": "selected", "model": selected, "defaults": defaults}


@mcp.tool(structured_output=False)
async def ask(prompt: str, model: str | None = None, effort: Effort | None = None,
              permission: Permission | None = None) -> str:
    """Ask agy and show the verbatim reply. Model, effort, and permission override
    saved defaults for this call. Use a Gemini shortcut or an external model ID such as claude-opus-5.5. 'inherit'
    uses the CLI setting. Include relevant history in prompt. Permission controls agy tools; headless approvals are denied.
    Select always-proceed only when requested.
    """
    if not prompt.strip():
        raise ValueError("请输入要发送给 agy 的问题。")
    args = [
        "--disable-slash-commands", "--input-format", "stream-json",
        "--output-format", "stream-json", "--print-timeout", f"{ASK_SECONDS}s", "--print=",
    ]
    with closing(preference_store()) as conn:
        previous = saved_options(conn)
    options = await combine(previous, model, effort, permission)
    args.extend(model_flags(options))
    policy = options["permission"]
    if policy != "inherit":
        # Pin default execution mode so CLI auto-mode cannot supersede toolPermission.
        settings = {"agentMode": "", "toolPermission": policy}
        if policy == "proceed-in-sandbox":
            settings["enableTerminalSandbox"] = True
        args.extend(["--settings", json.dumps(settings)])
    message = {"event": "user", "message": {"content": prompt}}
    data = (json.dumps(message, ensure_ascii=False) + "\n").encode()
    stdout, stderr, code = await run_agy(args, ASK_SECONDS + 10, data)
    # The result event carries the complete answer. Delta events may also contain reasoning.
    for line in reversed(stdout.split("\n")):
        if not line.strip():
            continue
        event = json.loads(line)
        if event.get("event") == "result":
            result = event["result"]
            if code or result.get("status") != "SUCCESS":
                raise RuntimeError(result.get("error") or stderr or f"agy 请求失败（退出码 {code}）。")
            reply = result.get("response")
            if not isinstance(reply, str) or not reply.strip():
                raise RuntimeError("agy 返回了空回复。")
            return reply
    raise RuntimeError(stderr or f"agy 没有返回最终结果（退出码 {code}）。")


MAX_IMAGE_BYTES = 8 * 1024 * 1024
IMAGE_TYPES = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp"}


def image_block(source):
    if source.startswith("data:"):
        header, _, encoded = source.removeprefix("data:").partition(",")
        mime, _, encoding = header.partition(";")
        if mime not in IMAGE_TYPES.values() or encoding != "base64":
            raise ValueError("请传入 PNG、JPEG 或 WebP 的 Base64 data URL。")
        if len(encoded) > 4 * ((MAX_IMAGE_BYTES + 2) // 3):
            raise ValueError("单张图片最大 8 MiB。")
        data = base64.b64decode(encoded, validate=True)
    else:
        path = Path(source).expanduser()
        mime = IMAGE_TYPES.get(path.suffix.lower().lstrip("."))
        if not path.is_absolute() or not mime or not path.is_file():
            raise ValueError(f"请传入可读的 PNG、JPEG 或 WebP 图片绝对路径：{source}")
        with path.open("rb") as file:
            data = file.read(MAX_IMAGE_BYTES + 1)
    if not data or len(data) > MAX_IMAGE_BYTES:
        raise ValueError("图片不能为空，单张图片最大 8 MiB。")
    return {"type": "image", "mimeType": mime, "data": base64.b64encode(data).decode("ascii")}


async def run_image_prompt(blocks, options):
    with TemporaryDirectory(prefix="agy-mcp-image-") as directory:
        async with await anyio.open_process([AGY, "acp"], cwd=directory, stderr=DEVNULL) as proc:
            incoming = BufferedByteReceiveStream(proc.stdout)
            response_chunks = []
            request_id = 0

            async def send(message):
                await proc.stdin.send((json.dumps({"jsonrpc": "2.0", **message}) + "\n").encode())

            async def call(method, params):
                nonlocal request_id
                request_id += 1
                await send({"id": request_id, "method": method, "params": params})
                while True:
                    event = json.loads(await incoming.receive_until(b"\n", 8 * 1024 * 1024))
                    if "method" in event and "id" in event:
                        if event["method"] == "session/request_permission":
                            await send({"id": event["id"], "result": {"outcome": {"outcome": "cancelled"}}})
                        else:
                            await send({"id": event["id"], "error": {"code": -32601, "message": "Unsupported client method"}})
                    elif event.get("method") == "session/update":
                        update = event["params"]["update"]
                        content = update.get("content", {})
                        if update.get("sessionUpdate") == "agent_message_chunk" and content.get("type") == "text":
                            response_chunks.append(content["text"])
                    elif event.get("id") == request_id:
                        if "error" in event:
                            raise RuntimeError(event["error"]["message"])
                        return event["result"]

            try:
                with anyio.fail_after(ASK_SECONDS):
                    init = await call("initialize", {"protocolVersion": 1, "clientCapabilities": {}})
                    if not init["agentCapabilities"].get("promptCapabilities", {}).get("image"):
                        raise RuntimeError("当前 agy ACP 版本未提供图片输入能力。")
                    session = await call("session/new", {"cwd": directory, "mcpServers": []})
                    session_id = {"sessionId": session["sessionId"]}
                    config = {option["id"]: option for option in session.get("configOptions", [])}
                    model, effort = options["model"], options["effort"]
                    if model != "inherit":
                        available = {item["value"] for item in config["model"]["options"]}
                        family, _, tier = model.rpartition("-")
                        if family in available and tier in EFFORT_LEVELS and effort == "inherit":
                            effort = tier
                        if model not in available and tier in EFFORT_LEVELS:
                            model = family
                        await call("session/set_config_option", {**session_id, "configId": "model", "value": model})
                    if effort != "inherit":
                        await call("session/set_config_option", {
                            **session_id, "configId": "thought_level", "value": effort,
                        })
                    response_chunks.clear()
                    result = await call("session/prompt", {**session_id, "prompt": blocks})
                    reply = "".join(response_chunks)
                    if not reply.strip() or result.get("stopReason") == "cancelled":
                        raise RuntimeError(f"agy 未返回完整的图片回复（{result.get('stopReason')}）。")
                    return reply
            except (anyio.EndOfStream, anyio.IncompleteRead) as exc:
                raise RuntimeError("agy ACP 提前退出。请检查 agy 版本和登录状态。") from exc
            except TimeoutError as exc:
                raise RuntimeError(f"agy 图片请求在 {ASK_SECONDS} 秒后超时。") from exc
            finally:
                if proc.returncode is None:
                    proc.terminate()
                    with anyio.move_on_after(2, shield=True):
                        await proc.wait()
                    if proc.returncode is None:
                        proc.kill()


@mcp.tool(structured_output=False)
async def ask_image(prompt: str, images: list[str], model: str | None = None,
                    effort: Effort | None = None) -> str:
    """Ask agy about user-provided images and return its reply verbatim.
    Pass one to four absolute local PNG/JPEG/WebP paths or image data URLs.
    For a selected screenshot region, pass a cropped image when available.
    Model and effort follow ask defaults. Image sessions decline approval requests.
    """
    if not prompt.strip() or not 1 <= len(images) <= 4:
        raise ValueError("请提供问题和 1 至 4 张图片。")
    blocks = [{"type": "text", "text": prompt}, *(image_block(source) for source in images)]
    with closing(preference_store()) as conn:
        previous = saved_options(conn)
    options = await combine(previous, model, effort, None)
    return await run_image_prompt(blocks, options)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agy-bin", default=AGY, help="Path to the authenticated agy executable")
    AGY = parser.parse_args().agy_bin
    mcp.run(transport="stdio")
