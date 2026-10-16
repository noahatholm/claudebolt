# claudebolt
SAAS is dead. I used to pay $20 a month for a tool like this (think TimeBolt), so I built a free, fully local alternative with Claude.

claudebolt automatically cuts silences, filler words, false starts and retakes from video and audio files. It runs entirely on your machine, with local Whisper transcription, and includes a local MCP server so an AI agent can edit for you.

## Status
- **Engine** (`engine/`, Python): silence detection (volume, speech/VAD or both), cut/speed-up, multitrack, local Whisper transcripts, filler / false-start / retake suggestions, render (video and audio-only), exports (FCPXML, xmeml, EDL, SRT/VTT, Audacity labels, cut list JSON), REST + WebSocket API and an MCP server. Tested.
- **Desktop app** (`app/`, Tauri 2 + React): the UI and native shell are written; the Rust shell has **not been compiled yet** (needs the Rust toolchain).

## Try it (CLI)
Needs [uv](https://docs.astral.sh/uv/) and ffmpeg on PATH.
```
cd engine
uv sync
uv run claudebolt cut talk.mp4 -o talk.cut.mp4          # also works for .mp3 / .wav / .m4a
uv run claudebolt cut talk.mp3 -o talk.cut.mp3 --threshold auto --grace 0.6
uv run claudebolt detect talk.mp4 --json                 # just print the cut list
```
Transcript-based cleanup (local Whisper, `uv sync --extra whisper`):
```
uv run claudebolt transcribe talk.mp4 --model small.en
uv run claudebolt cleanup talk.mp4.claudebolt.json --apply "filler>=0.8"
uv run claudebolt export talk.mp4.claudebolt.json --format fcpxml -o talk.fcpxml
```

## Let an AI agent edit for you (MCP)
```
uv run claudebolt mcp install     # registers claudebolt in every AI agent it detects
uv run claudebolt mcp install codex opencode   # or pick: claude-code, claude-desktop, codex,
                                  #   opencode, antigravity, gemini, cursor, windsurf, vscode
uv run claudebolt mcp install --list            # what is supported / detected here
```
Then ask: "remove all the ums and long pauses from demo.mp4 and render it".

## Desktop app
```
cd app && pnpm install && pnpm tauri dev      # needs Rust; starts the engine for you
```
See `engine/scripts/build_engine.py` to freeze the engine into a bundled `claudebolt-engine.exe`.

## Tests
```
cd engine && uv run pytest              # fast suite
uv run pytest -m slow                   # Whisper / VAD / 2-hour streaming
cd ../app && pnpm test
```

## Releases
Every push to `main` runs `.github/workflows/release.yml`. It picks the next version from the commit
messages since the last `v*` tag (`feat:` bumps minor, `!`/`BREAKING CHANGE` bumps major, anything else
bumps patch). Then it runs the tests and builds the desktop installers and a standalone engine archive
for Windows x64, Linux x64/arm64 and macOS arm64. Once all of that passes, it tags `vX.Y.Z` and publishes
a GitHub release. The version is stamped into the manifests at build time (`scripts/set_version.py`),
so nothing is committed back. PRs run the tests only (`test.yml`).

### Updates
Installed releases check the newest GitHub release's `latest.json` at start-up and every 6 hours. When
there is a newer version they show a banner, and on **Install & restart** they download it, verify its
signature and install it in the same format (NSIS, MSI, `.app`, `.deb`, `.rpm`). The portable zip and the
standalone engine don't update themselves. Builds from a checkout never look for updates: only the
release workflow compiles in `CLAUDEBOLT_OFFICIAL_BUILD`, and only when it holds the signing key.

The release workflow signs update packages with the `TAURI_SIGNING_PRIVATE_KEY` and
`TAURI_SIGNING_PRIVATE_KEY_PASSWORD` repository secrets; the public key is in
`app/src-tauri/tauri.conf.json`. Keep the private key safe: installed apps only accept updates signed
with it.
