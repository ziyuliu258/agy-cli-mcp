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
    parser.add_argument("--skill", action="append", choices=("codex", "claude"), default=[],
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
        if client == "codex":
            skill_root = Path.home() / ".agents" / "skills"
        else:
            skill_root = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude") / "skills"
        skill_dir = skill_root / "agy-cli"
        skill_dir.mkdir(parents=True, exist_ok=True)
        publish(skill_dir / "SKILL.md", (source / "skills/agy-cli/SKILL.md").read_bytes())
        print(f"{client} skill 已安装到 {skill_dir}")
    print("按所用客户端选择一条注册命令：")
    for prefix in (["claude", "mcp", "add", "--scope", "user", "--transport", "stdio", "agy", "--"],
                   ["codex", "mcp", "add", "agy", "--"]):
        words = [*prefix, str(python), *args]
        if windows:
            print("& " + " ".join("'" + word.replace("'", "''") + "'" for word in words))
        else:
            print(shlex.join(words))


if __name__ == "__main__":
    main()
