import json
import tomllib

import pytest

from claudebolt.mcp import install as ins


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(ins, "_home", lambda: tmp_path)
    for var in ("APPDATA", "XDG_CONFIG_HOME", "CODEX_HOME"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(ins.shutil, "which", lambda name: None)  # no agent CLIs on PATH
    monkeypatch.setattr(ins, "server_command", lambda: ("/opt/cb/python", ["-m", "claudebolt", "mcp"]))
    return tmp_path


STDIO = {"command": "/opt/cb/python", "args": ["-m", "claudebolt", "mcp"]}


@pytest.mark.parametrize("client,path,section,entry", [
    ("antigravity", ".gemini/config/mcp_config.json", "mcpServers", STDIO),
    ("gemini", ".gemini/settings.json", "mcpServers", STDIO),
    ("cursor", ".cursor/mcp.json", "mcpServers", STDIO),
    ("windsurf", ".codeium/windsurf/mcp_config.json", "mcpServers", STDIO),
    ("opencode", ".config/opencode/opencode.json", "mcp",
     {"type": "local", "command": ["/opt/cb/python", "-m", "claudebolt", "mcp"], "enabled": True}),
])
def test_json_clients_merge_and_keep_other_servers(home, client, path, section, entry):
    p = home / path
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps({"theme": "dark", section: {"other": {"command": "x"}}}))
    [line] = ins.install([client])
    assert "wrote" in line
    cfg = json.loads(p.read_text())
    assert cfg["theme"] == "dark"
    assert cfg[section] == {"other": {"command": "x"}, "claudebolt": entry}
    ins.install([client])  # idempotent
    assert json.loads(p.read_text()) == cfg


def test_opencode_new_file_gets_schema(home):
    ins.install(["opencode"])
    cfg = json.loads((home / ".config/opencode/opencode.json").read_text())
    assert cfg["$schema"] == "https://opencode.ai/config.json"


def test_jsonc_is_left_untouched(home):
    p = home / ".config/opencode/opencode.jsonc"
    p.parent.mkdir(parents=True)
    original = '{\n  // my comment\n  "mcp": {}\n}\n'
    p.write_text(original)
    [line] = ins.install(["opencode"])
    assert "isn't plain JSON" in line and '"claudebolt"' in line
    assert p.read_text() == original


def test_codex_toml_replaces_only_our_table(home):
    p = home / ".codex/config.toml"
    p.parent.mkdir(parents=True)
    p.write_text('model = "o3"\n\n[mcp_servers.claudebolt]\ncommand = "old"\n\n'
                 '[mcp_servers.claudebolt.env]\nA = "1"\n\n[mcp_servers.other]\ncommand = "y"\n')
    ins.install(["codex"])
    cfg = tomllib.loads(p.read_text())
    assert cfg["model"] == "o3"
    assert cfg["mcp_servers"]["other"] == {"command": "y"}
    assert cfg["mcp_servers"]["claudebolt"] == STDIO


def test_codex_home_env_and_windows_paths(home, monkeypatch):
    monkeypatch.setenv("CODEX_HOME", str(home / "ch"))
    monkeypatch.setattr(ins, "server_command", lambda: (r"C:\Program Files\cb\engine.exe", ["mcp"]))
    ins.install(["codex"])
    cfg = tomllib.loads((home / "ch/config.toml").read_text())
    assert cfg["mcp_servers"]["claudebolt"]["command"] == r"C:\Program Files\cb\engine.exe"


def test_detection_and_unknown(home):
    [line] = ins.install()
    assert "No supported AI agents" in line
    (home / ".cursor").mkdir()
    assert [c["id"] for c in ins.list_clients() if c["detected"]] == ["cursor"]
    [line] = ins.install()
    assert line.startswith("Cursor:")
    with pytest.raises(ValueError, match="unknown agent"):
        ins.install(["nope"])


def test_claude_code_without_cli_gives_command(home):
    [line] = ins.install(["claude-code"])
    assert "claude mcp add --scope user claudebolt -- /opt/cb/python -m claudebolt mcp" in line


async def test_rest_endpoints(home):
    import httpx

    from claudebolt.server.app import create_app
    from claudebolt.service import Service

    (home / ".cursor").mkdir()
    app = create_app(Service(sandbox=True), "tk", with_mcp=False)
    h = {"Authorization": "Bearer tk"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://127.0.0.1:1") as c:
        clients = (await c.get("/api/mcp/clients", headers=h)).json()
        assert {"id": "cursor", "label": "Cursor", "detected": True} in clients
        r = await c.post("/api/mcp/install", json={}, headers=h)  # default: detected agents
        assert [line.split(":")[0] for line in r.json()["lines"]] == ["Cursor"]
        r = await c.post("/api/mcp/install", json={"targets": ["gemini"]}, headers=h)
        assert r.json()["lines"][0].startswith("Gemini CLI: wrote")
        assert (await c.post("/api/mcp/install", json={"targets": ["x"]}, headers=h)).status_code == 400
