## Install

| Platform | Download |
|---|---|
| Windows 10/11 x64 | `claudebolt_*_x64-setup.exe` (per-user, recommended), `*.msi` (per-machine), or `*-portable.zip` (no install: unzip, run `claudebolt.exe`) |
| macOS 14+ (Apple silicon) | `claudebolt_*_aarch64.dmg`: drag claudebolt to Applications |
| Debian / Ubuntu 22.04+ | `sudo apt install ./claudebolt_*_amd64.deb` (or `_arm64.deb`) |
| Fedora / RHEL | `sudo dnf install ./claudebolt-*.x86_64.rpm` (or `.aarch64.rpm`) |
| CLI / MCP only | `claudebolt-engine-*-<platform>` archive: unpack, run `claudebolt-engine --help` |

ffmpeg is bundled. Speech models download on first use (Settings → Speech models).

Already installed? The app offers updates itself (banner at the top, or Settings → Check for updates);
the portable zip has to be replaced by hand.

These builds aren't code-signed yet:
- **Windows:** SmartScreen may say "Windows protected your PC". Click **More info → Run anyway**.
- **macOS:** the first launch is blocked. Open **System Settings → Privacy & Security → Open Anyway**,
  or run `xattr -dr com.apple.quarantine /Applications/claudebolt.app`.

Check downloads against `SHA256SUMS.txt`.
