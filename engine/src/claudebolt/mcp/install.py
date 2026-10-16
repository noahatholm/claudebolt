"""Register claudebolt as an MCP server in Claude Code / Claude Desktop."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


def server_command() -> tuple[str, list[str]]:
    if getattr(sys, "frozen", False):
        return sys.executable, ["mcp"]
    return sys.executable, ["-m", "claudebolt", "mcp"]


def desktop_config_path() -> Path:
    if os.name == "nt":
        return Path(os.environ.get("APPDATA", "~")).expanduser() / "Claude" / "claude_desktop_config.json"
    if sys.platform == "darwin":
        return Path("~/Library/Application Support/Claude/claude_desktop_config.json").expanduser()
    return Path("~/.config/Claude/claude_desktop_config.json").expanduser()


def install_desktop(path: Path | None = None) -> str:
    cmd, args = server_command()
    p = path or desktop_config_path()
    cfg = {}
    if p.exists():
        cfg = json.loads(p.read_text("utf-8") or "{}")
    cfg.setdefault("mcpServers", {})["claudebolt"] = {"command": cmd, "args": args}
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(cfg, indent=2), "utf-8")
    os.replace(tmp, p)
    return f"Claude Desktop: wrote {p} (restart Claude Desktop)"


def install_code() -> str:
    cmd, args = server_command()
    full = ["claude", "mcp", "add", "claudebolt", "--", cmd, *args]
    if shutil.which("claude"):
        r = subprocess.run(full, capture_output=True, text=True)
        if r.returncode == 0:
            return "Claude Code: registered claudebolt"
        return f"Claude Code: command failed ({r.stderr.strip()}). Run manually:\n  {' '.join(full)}"
    return f"Claude Code CLI not found on PATH. Run manually:\n  {' '.join(full)}"


def install(code: bool = True, desktop: bool = True) -> list[str]:
    out = []
    if code:
        out.append(install_code())
    if desktop:
        out.append(install_desktop())
    return out
