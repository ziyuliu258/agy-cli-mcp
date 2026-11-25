"""An MCP stdio bridge for the authenticated Antigravity CLI."""
import argparse
import json
import os
import shutil
import sqlite3
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal, get_args

import anyio
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("agy", instructions=(
    "When the user asks to consult an agy model, use ask. "
    "Show its reply directly in the chat, preserving its language and Markdown, "
    "unless the user requests a summary or further processing. Use ask parameters for one turn. "
    "Use set_defaults only when the user requests a lasting change. Choose permissions only "
    "as requested by the user."
))
AGY = os.environ.get("AGY_BIN") or shutil.which("agy") or str(Path.home() / ".local/bin/agy")
ASK_SECONDS = 600

Effort = Literal["inherit", "low", "medium", "high", "xhigh", "max"]
EFFORT_LEVELS = set(get_args(Effort)) - {"inherit"}
Permission = Literal["inherit", "strict", "request-review", "proceed-in-sandbox", "always-proceed"]
DB = Path(__file__).resolve().with_name("defaults.sqlite3")
INHERITED = dict.fromkeys(("model", "effort", "permission"), "inherit")


def preference_store():
    conn = sqlite3.connect(DB)
    conn.execute("CREATE TABLE IF NOT EXISTS defaults (name TEXT PRIMARY KEY, value TEXT NOT NULL)")
    return conn


def saved_options(conn):
    return {**INHERITED, **dict(conn.execute("SELECT name, value FROM defaults"))}


def combine(previous, model, effort, permission):
    options = previous.copy()
    if model is not None:
        model = model.strip()
        if not model:
            raise ValueError("请输入模型 ID，或用 inherit 跟随 CLI。")
        options["model"] = model
        # A specifically selected variant takes precedence over a previously saved tier.
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
    Omit fields to keep them. Set 'inherit' to remove an override. Choosing an exact
    tiered model also selects its tier unless effort is given. To reset all, use
    'inherit' for all three. always-proceed allows unattended tools per agy rules.
    """
    with closing(preference_store()) as conn:
        previous = saved_options(conn)
        updated = combine(previous, model, effort, permission)
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


@mcp.tool(structured_output=False)
async def ask(prompt: str, model: str | None = None, effort: Effort | None = None,
              permission: Permission | None = None) -> str:
    """Ask agy and show the verbatim reply. Model, effort, and permission override
    saved defaults for this call. 'inherit' uses the CLI setting. Include relevant
    history in prompt. Permission controls agy tools; headless approvals are denied.
    Select always-proceed only when requested.
    """
    if not prompt.strip():
        raise ValueError("请输入要发送给 agy 的问题。")
    args = [
        "--disable-slash-commands", "--input-format", "stream-json",
        "--output-format", "stream-json", "--print-timeout", f"{ASK_SECONDS}s", "--print=",
    ]
    with closing(preference_store()) as conn:
        options = combine(saved_options(conn), model, effort, permission)
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


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agy-bin", default=AGY, help="Path to the authenticated agy executable")
    AGY = parser.parse_args().agy_bin
    mcp.run(transport="stdio")
