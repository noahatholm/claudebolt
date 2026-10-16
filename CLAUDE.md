# CLAUDE.md

## What this project is
**claudebolt** is a local-first automatic video/audio editor, similar in purpose to commercial apps like TimeBolt. It removes:
- silences: cut them or speed them up
- filler words, false starts and retakes ("speech cleanup")

It works on **video and audio** files. Everything runs **on the user's machine**: transcription uses local Whisper, and there's no cloud, license server or upload.

It also exposes a **local MCP server**, so an AI editing agent can analyze, edit, render and export projects.

## Originality rule (important)
- All code is written from scratch against public documentation (FFmpeg, Whisper, MCP spec). Never copy code, assets, strings or feature names from any third-party application.
- `.plan/` and `.rea/` are local notes and are gitignored. Never commit them, un-ignore them, or reference their contents in tracked files.

## Status
Engine (M0-M4, most of M6) and UI source (M5) are implemented. The Tauri Rust shell passes `cargo check`; packaging (M7) runs in CI (`.github/workflows/release.yml`) for Windows x64, Linux x64/arm64 and macOS arm64, but no release has been verified end to end yet. MCP SDK is pinned `<2`.

## Where to look
- `.plan/00-overview.md`: goals, principles, index of the plan.
- `.plan/01-architecture.md`: layout, process model, data model, storage.
- `.plan/02`–`06`: detection, local speech cleanup, render/export, MCP tools, UI.
- `.plan/07-milestones.md`: build order (M0 → M7) with acceptance criteria. Work milestone by milestone.

## Stack
- `engine/`: Python 3.12 package `claudebolt`, managed with **uv**.
  - Core libraries: numpy, pydantic v2, typer (CLI), FastAPI + uvicorn (daemon), the official `mcp` SDK, faster-whisper, onnxruntime (Silero VAD), rapidfuzz.
  - Calls **ffmpeg/ffprobe** as subprocesses.
- `app/`: Tauri 2 + React + TypeScript (pnpm, Vite), wavesurfer.js v7. It starts the engine as a sidecar and talks to it over REST + WebSocket.

## Commands (once scaffolded)
```
cd engine
uv sync
uv run pytest                      # fast tests
uv run pytest -m slow              # whisper / long-file tests
uv run python tests/fixtures/make_fixtures.py
uv run claudebolt cut in.mp4 -o out.mp4
uv run claudebolt serve            # engine (REST, /events WS, /mcp), prints {port, token}
uv run claudebolt mcp              # MCP over stdio
cd ../app && pnpm install && pnpm tauri dev
```
ffmpeg must be on PATH during development, or set `CLAUDEBOLT_FFMPEG`.

## Core concepts
- **Project** = sources (video/audio) + tracks + **Timeline** + transcript + proposals + settings. Saved as `*.claudebolt.json`.
- **Timeline** = sorted `Segment`s that always tile `[0, duration]`. Each segment has `op`: `keep | remove | speed`, plus a `reason`: `silence | filler | false_start | retake | manual | agent`.
- **Ops** (`timeline/ops.py`) are the only way to mutate a timeline. Each stores its inverse (undo/redo) and is broadcast as an event.
- **Proposals:** detectors (silence re-detect aside) produce proposals that must be accepted. Re-detection never overwrites locked, manual or agent edits.
- **service.py** is the single service layer behind the CLI, REST and MCP. Add features there first, then expose them.

## Conventions
- Detection, refine, detectors and time mapping are **pure functions** with table tests. Render and exports are tested against real ffmpeg output durations.
- Never mutate source media. Write files atomically.
- Engine binds only to `127.0.0.1` and requires the daemon token. MCP file access is limited to opened media and output dirs.
- Keep audio-only inputs first-class: every feature must work without a video stream.
