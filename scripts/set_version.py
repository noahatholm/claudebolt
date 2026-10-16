"""Stamp one version into every manifest and lockfile. CI runs this before building.

usage: python scripts/set_version.py 1.2.3   (a leading "v" is accepted)
"""

import re
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
version = sys.argv[1].removeprefix("v")
# MSI needs plain numeric MAJOR.MINOR.PATCH
if not re.fullmatch(r"\d+\.\d+\.\d+", version):
    sys.exit(f"not a MAJOR.MINOR.PATCH version: {version}")


def sub(rel: str, pattern: str, repl: str) -> None:
    path = root / rel
    text = path.read_text("utf-8")
    new, n = re.subn(pattern, repl, text, count=1, flags=re.MULTILINE)
    if n != 1:
        sys.exit(f"version field not found in {rel}")
    path.write_text(new, "utf-8", newline="")


sub("engine/pyproject.toml", r'^version = "[^"]*"', f'version = "{version}"')
sub("engine/src/claudebolt/__init__.py", r'^__version__ = "[^"]*"', f'__version__ = "{version}"')
sub("engine/uv.lock", r'^(name = "claudebolt"\r?\nversion = )"[^"]*"', rf'\g<1>"{version}"')
sub("app/src-tauri/Cargo.toml", r'^version = "[^"]*"', f'version = "{version}"')
sub("app/src-tauri/Cargo.lock", r'^(name = "claudebolt"\r?\nversion = )"[^"]*"', rf'\g<1>"{version}"')
# the first two-space-indented "version" key is the top-level one; regex keeps the formatting
sub("app/package.json", r'^  "version": "[^"]*"', f'  "version": "{version}"')
sub("app/src-tauri/tauri.conf.json", r'^  "version": "[^"]*"', f'  "version": "{version}"')
print(version)
