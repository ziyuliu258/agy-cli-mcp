"""Install the stdio server and print MCP client settings for this machine."""
import argparse
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import venv


def publish(path, data):
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as temp:
        temp.write(data)
    os.replace(temp.name, path)


CLIENTS = ("codex", "claude", "pi", "dsh", "opencode", "openchamber")


def install_skill(client, source, target, command, args):
    home = Path.home()
    config_dir = Path(os.getenv("XDG_CONFIG_HOME") or home / ".config")
    pi_dir = Path(os.getenv("PI_CODING_AGENT_DIR") or home / ".pi/agent")
    dsh_dir = Path(os.getenv("DSH_HOME") or home / ".dsh")
    opencode_dir = Path(os.getenv("OPENCODE_CONFIG_DIR") or config_dir / "opencode")
    roots = {
        "codex": home / ".agents", "claude": Path(os.getenv("CLAUDE_CONFIG_DIR") or home / ".claude"),
        "pi": pi_dir, "dsh": dsh_dir, "opencode": opencode_dir, "openchamber": opencode_dir,
    }
    skill_dir = roots[client] / "skills" / "agy-cli"
    skill_dir.mkdir(parents=True, exist_ok=True)
    publish(skill_dir / "SKILL.md", (source / "skills/agy-cli/SKILL.md").read_bytes())
    print(f"{client} skill 已安装到 {skill_dir}")
    if client in ("pi", "opencode", "openchamber"):
        templates = roots[client] / ("prompts" if client == "pi" else "commands")
        templates.mkdir(parents=True, exist_ok=True)
        publish(templates / "agy-cli.md", "调用 agy-cli 技能处理以下输入：\n\n$ARGUMENTS\n".encode())
    if client == "dsh":
        # A YAML patch layer is a list; JSON flow notation also quotes paths portably.
        plugin = {"id": "mcp-agy", "name": "@deepseek-ai/dsh-mcp-client",
                  "config": {"serverName": "agy", "transport": "stdio", "command": command,
                             "args": args, "toolCallTimeoutMs": 630000}}
        patch = target / "dsh-agy.patch.yml"
        publish(patch, ("- insert:\n    - " + json.dumps(plugin, ensure_ascii=False) + "\n").encode())
        print(f"DSH：将 {patch} 的列表项合并到当前 profile 的 cordis.patch.yml。")


def main():
    if sys.version_info < (3, 10):
        sys.exit("需要 Python 3.10 或更高版本。")
    windows = os.name == "nt"
    default_root = Path.home() / ".local/share"
    if windows:
        default_root = Path(os.environ["LOCALAPPDATA"])
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install-dir", type=Path, default=default_root / "agy-cli-mcp")
    parser.add_argument("--agy-bin", default=os.getenv("AGY_BIN", "agy"))
    parser.add_argument("--skill", action="append", choices=CLIENTS, default=[],
                        help="Install the agy-cli chat skill for this client (repeatable)")
    options = parser.parse_args()
    binary = shutil.which(os.path.expanduser(options.agy_bin))
    if not binary:
        sys.exit("找不到 agy。请先安装 CLI，或指定 --agy-bin /完整路径/agy。")

    source = Path(__file__).resolve().parent
    target = options.install_dir.expanduser().resolve()
    target.mkdir(parents=True, exist_ok=True)
    environment = target / "venv"
    python = environment / ("Scripts/python.exe" if windows else "bin/python")
    uv = shutil.which("uv")
    if not python.exists():
        if uv:
            subprocess.run([uv, "venv", "--python", sys.executable, environment], check=True)
        else:
            venv.EnvBuilder(with_pip=True).create(environment)
    installer = [uv, "pip", "install", "--python", python] if uv else [python, "-m", "pip", "install"]
    subprocess.run([*installer, "-r", source / "requirements.txt"], check=True)
    server = target / "server.py"
    publish(server, (source / "server.py").read_bytes())
    args = [str(server), "--agy-bin", os.path.abspath(binary)]
    config = {"mcpServers": {"agy": {"command": str(python), "args": args}}}
    config_path = target / "mcp-config.json"
    publish(config_path, (json.dumps(config, indent=2, ensure_ascii=False) + "\n").encode())
    print(f"\n已安装到 {target}\n通用 MCP 配置文件：{config_path}\n")
    for client in dict.fromkeys(options.skill):
        install_skill(client, source, target, str(python), args)
    print("按所用客户端选择一条注册命令：")
    for prefix in (["claude", "mcp", "add", "--scope", "user", "--transport", "stdio", "agy", "--"],
                   ["codex", "mcp", "add", "agy", "--"],
                   ["pi", "mcp", "add", "agy", "--"],
                   ["opencode", "mcp", "add", "--global", "agy", "--"]):
        words = [*prefix, str(python), *args]
        if windows:
            print("& " + " ".join("'" + word.replace("'", "''") + "'" for word in words))
        else:
            print(shlex.join(words))


if __name__ == "__main__":
    main()
