"""Register claudebolt as an MCP server in local AI agents (Claude, Codex, OpenCode, Antigravity, ...).

Each client keeps its MCP servers in its own config file and format. We only ever touch the
`claudebolt` entry, write atomically, and refuse to rewrite a file we can't parse exactly
(e.g. JSON with comments) - the user gets the snippet to paste instead.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

NAME = "claudebolt"


def server_command() -> tuple[str, list[str]]:
    if getattr(sys, "frozen", False):
        return sys.executable, ["mcp"]
    return sys.executable, ["-m", "claudebolt", "mcp"]


def _home() -> Path:
    return Path.home()


def _env_dir(var: str, default: Path) -> Path:
    v = os.environ.get(var)
    return Path(v).expanduser() if v else default


def _xdg_config() -> Path:
    return _env_dir("XDG_CONFIG_HOME", _home() / ".config")


def _app_support(name: str) -> Path:
    """Per-OS app settings dir as used by Electron apps (Claude Desktop, VS Code)."""
    if os.name == "nt":
        return _env_dir("APPDATA", _home() / "AppData" / "Roaming") / name
    if sys.platform == "darwin":
        return _home() / "Library" / "Application Support" / name
    return _xdg_config() / name


def _write_atomic(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(text, "utf-8")
    os.replace(tmp, p)


class ManualStep(Exception):
    """Can't safely edit the config; the message tells the user what to add by hand."""


# ---- JSON clients ----------------------------------------------------------------------------


def _merge_json(p: Path, section: str, entry: dict, new_file: dict | None = None) -> None:
    if p.exists() and p.read_text("utf-8").strip():
        try:
            cfg = json.loads(p.read_text("utf-8"))
        except json.JSONDecodeError as e:
            snippet = json.dumps({section: {NAME: entry}}, indent=2)
            raise ManualStep(f"{p} isn't plain JSON ({e.msg}); add this to it:\n{snippet}") from e
        if not isinstance(cfg, dict) or not isinstance(cfg.get(section, {}), dict):
            raise ManualStep(f"{p} has an unexpected layout; add a '{NAME}' entry under '{section}'")
    else:
        cfg = dict(new_file or {})
    cfg.setdefault(section, {})[NAME] = entry
    _write_atomic(p, json.dumps(cfg, indent=2) + "\n")


def _stdio_entry() -> dict:
    cmd, args = server_command()
    return {"command": cmd, "args": args}


def claude_desktop_path() -> Path:
    return _app_support("Claude") / "claude_desktop_config.json"


def opencode_path() -> Path:
    d = _xdg_config() / "opencode"
    # opencode reads either name; prefer the one the user already has
    for n in ("opencode.json", "opencode.jsonc"):
        if (d / n).exists():
            return d / n
    return d / "opencode.json"


def antigravity_path() -> Path:
    return _home() / ".gemini" / "config" / "mcp_config.json"


def gemini_path() -> Path:
    return _home() / ".gemini" / "settings.json"


def cursor_path() -> Path:
    return _home() / ".cursor" / "mcp.json"


def windsurf_path() -> Path:
    return _home() / ".codeium" / "windsurf" / "mcp_config.json"


def vscode_path() -> Path:
    return _app_support("Code") / "User" / "mcp.json"


def _install_json(path: Callable[[], Path], section: str, entry: Callable[[], dict],
                  new_file: dict | None = None) -> Callable[[], str]:
    def run() -> str:
        p = path()
        _merge_json(p, section, entry(), new_file)
        return f"wrote {p}"

    return run


def _opencode_entry() -> dict:
    cmd, args = server_command()
    return {"type": "local", "command": [cmd, *args], "enabled": True}


def _vscode_entry() -> dict:
    return {"type": "stdio", **_stdio_entry()}


# ---- Codex (TOML) ----------------------------------------------------------------------------


def codex_path() -> Path:
    return _env_dir("CODEX_HOME", _home() / ".codex") / "config.toml"


def _toml_str(s: str) -> str:
    return json.dumps(s)  # JSON string escapes are valid TOML basic-string escapes


def install_codex() -> str:
    p = codex_path()
    cmd, args = server_command()
    block = (f"[mcp_servers.{NAME}]\ncommand = {_toml_str(cmd)}\n"
             f"args = [{', '.join(_toml_str(a) for a in args)}]\n")
    text = p.read_text("utf-8") if p.exists() else ""
    try:
        tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise ManualStep(f"{p} doesn't parse as TOML ({e}); add this to it:\n{block}") from e
    # drop our existing [mcp_servers.claudebolt] table (and any sub-tables), keep everything else
    header = re.compile(rf"^\s*\[\s*mcp_servers\.{NAME}\s*(\]|\.)")
    kept, skipping = [], False
    for line in text.splitlines(keepends=True):
        if line.lstrip().startswith("["):
            skipping = bool(header.match(line))
        if not skipping:
            kept.append(line)
    base = "".join(kept).rstrip()
    new = (base + "\n\n" if base else "") + block
    cfg = tomllib.loads(new)  # e.g. an inline `mcp_servers = {...}` would collide here
    if cfg.get("mcp_servers", {}).get(NAME) != {"command": cmd, "args": args}:
        raise ManualStep(f"couldn't place the entry in {p} safely; add this to it:\n{block}")
    _write_atomic(p, new)
    return f"wrote {p}"


# ---- Claude Code (CLI) -----------------------------------------------------------------------


def install_claude_code() -> str:
    cmd, args = server_command()
    full = ["claude", "mcp", "add", "--scope", "user", NAME, "--", cmd, *args]
    manual = " ".join(f'"{a}"' if " " in a else a for a in full)
    exe = shutil.which("claude")
    if not exe:
        raise ManualStep(f"`claude` CLI not found on PATH. Run:\n  {manual}")
    # `add` refuses to overwrite, so drop any previous registration first
    subprocess.run([exe, "mcp", "remove", "--scope", "user", NAME], capture_output=True)
    r = subprocess.run([exe, *full[1:]], capture_output=True, text=True)
    if r.returncode != 0:
        raise ManualStep(f"`claude mcp add` failed ({r.stderr.strip()}). Run:\n  {manual}")
    return "registered (user scope)"


# ---- registry --------------------------------------------------------------------------------


@dataclass(frozen=True)
class Client:
    id: str
    label: str
    detect: Callable[[], bool]
    install: Callable[[], str]


def _on_path(*names: str) -> Callable[[], bool]:
    return lambda: any(shutil.which(n) for n in names)


def _exists(path: Callable[[], Path]) -> Callable[[], bool]:
    return lambda: path().exists()


def _any(*checks: Callable[[], bool]) -> Callable[[], bool]:
    return lambda: any(c() for c in checks)


CLIENTS: list[Client] = [
    Client("claude-code", "Claude Code",
           _any(_on_path("claude"), _exists(lambda: _home() / ".claude")), install_claude_code),
    Client("claude-desktop", "Claude Desktop", _exists(lambda: claude_desktop_path().parent),
           _install_json(claude_desktop_path, "mcpServers", _stdio_entry)),
    Client("codex", "Codex",
           _any(_on_path("codex"), _exists(lambda: codex_path().parent)), install_codex),
    Client("opencode", "OpenCode",
           _any(_on_path("opencode"), _exists(lambda: opencode_path().parent)),
           _install_json(opencode_path, "mcp", _opencode_entry,
                         {"$schema": "https://opencode.ai/config.json"})),
    Client("antigravity", "Antigravity",
           _any(_on_path("antigravity", "agy"), _exists(lambda: _home() / ".gemini" / "antigravity"),
                _exists(lambda: antigravity_path().parent)),
           _install_json(antigravity_path, "mcpServers", _stdio_entry)),
    Client("gemini", "Gemini CLI", _any(_on_path("gemini"), _exists(gemini_path)),
           _install_json(gemini_path, "mcpServers", _stdio_entry)),
    Client("cursor", "Cursor", _any(_on_path("cursor"), _exists(lambda: cursor_path().parent)),
           _install_json(cursor_path, "mcpServers", _stdio_entry)),
    Client("windsurf", "Windsurf",
           _any(_on_path("windsurf"), _exists(lambda: windsurf_path().parent)),
           _install_json(windsurf_path, "mcpServers", _stdio_entry)),
    Client("vscode", "VS Code", _exists(lambda: vscode_path().parent),
           _install_json(vscode_path, "servers", _vscode_entry)),
]
BY_ID = {c.id: c for c in CLIENTS}


def list_clients() -> list[dict]:
    return [{"id": c.id, "label": c.label, "detected": c.detect()} for c in CLIENTS]


def install(targets: list[str] | None = None) -> list[str]:
    """Install into `targets` (client ids), or into every detected client when None."""
    if targets is None:
        chosen = [c for c in CLIENTS if c.detect()]
        if not chosen:
            return ["No supported AI agents detected. Pass one explicitly, e.g. "
                    f"`claudebolt mcp install codex` ({', '.join(BY_ID)})."]
    else:
        unknown = [t for t in targets if t not in BY_ID]
        if unknown:
            raise ValueError(f"unknown agent(s): {', '.join(unknown)} (choose from {', '.join(BY_ID)})")
        chosen = [BY_ID[t] for t in dict.fromkeys(targets)]
    out = []
    for c in chosen:
        try:
            out.append(f"{c.label}: {c.install()} (restart {c.label} to pick it up)")
        except (ManualStep, OSError) as e:
            out.append(f"{c.label}: {e}")
    return out
