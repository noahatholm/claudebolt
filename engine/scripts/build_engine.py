"""Freeze the engine into a one-folder app (dist/claudebolt-engine/) with ffmpeg bundled."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
dist = root.parent / "app" / "engine-dist"
shutil.rmtree(dist, ignore_errors=True)
entry = root / "scripts" / "engine_entry.py"
cmd = [
    "uv", "run", "--project", str(root), "--extra", "whisper", "--extra", "vad",
    "--with", "pyinstaller", "pyinstaller", "--noconfirm", "--onedir", "--console",
    "--name", "claudebolt-engine", "--distpath", str(dist), "--workpath", str(root / "build"),
    "--specpath", str(root / "build"),
    "--paths", str(root / "src"),
    "--collect-submodules", "claudebolt", "--collect-all", "mcp", "--collect-all", "faster_whisper",
    "--collect-all", "ctranslate2", "--collect-all", "onnxruntime", "--collect-all", "tokenizers",
    "--copy-metadata", "mcp", "--copy-metadata", "fastapi", "--copy-metadata", "uvicorn",
    "--hidden-import", "uvicorn.logging", "--hidden-import", "uvicorn.loops.auto",
    "--hidden-import", "uvicorn.protocols.http.auto", "--hidden-import", "uvicorn.protocols.websockets.auto",
    "--hidden-import", "uvicorn.lifespan.on",
    str(entry),
]
subprocess.run(cmd, check=True)
out = dist / "claudebolt-engine"
# CLAUDEBOLT_BUNDLE_FFMPEG_DIR points at a smaller "essentials" build to keep the installer lean
bundle_dir = os.environ.get("CLAUDEBOLT_BUNDLE_FFMPEG_DIR")
for name in ("ffmpeg", "ffprobe"):
    found = shutil.which(name, path=bundle_dir) if bundle_dir else shutil.which(name)
    if not found:
        sys.exit(f"{name} not found on PATH; install a GPL ffmpeg build to bundle")
    shutil.copy(found, out / Path(found).name)
(out / "THIRD_PARTY_NOTICE.txt").write_text(
    "This folder bundles FFmpeg (https://ffmpeg.org), licensed under the GPL/LGPL depending on the\n"
    "build. Source and license: https://ffmpeg.org/legal.html\n", "utf-8")
print("built", out)
