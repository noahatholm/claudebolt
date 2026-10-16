"""Write latest.json, the manifest the in-app updater reads from the newest GitHub release.

usage: python scripts/make_latest_json.py <dist-dir> <version> <owner/repo>

Every updatable package in <dist-dir> must have a <package>.sig next to it (tauri writes them when
built with createUpdaterArtifacts and TAURI_SIGNING_PRIVATE_KEY). The .sig files are folded into
the manifest and deleted, so they are not uploaded as release assets. Fails if any platform is
missing: the updater rejects the whole manifest when one entry is incomplete.
"""

import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

# updater platform key ({os}-{arch}-{installer}) -> how that package is named
PLATFORMS = {
    "windows-x86_64-nsis": r"_x64-setup\.exe",
    "windows-x86_64-msi": r"_x64_[A-Za-z-]+\.msi",
    "linux-x86_64-deb": r"_amd64\.deb",
    "linux-aarch64-deb": r"_arm64\.deb",
    "linux-x86_64-rpm": r"\.x86_64\.rpm",
    "linux-aarch64-rpm": r"\.aarch64\.rpm",
    "darwin-aarch64-app": r"_aarch64\.app\.tar\.gz",
}


def build(dist: Path, version: str, repo: str) -> dict:
    sigs = sorted(dist.glob("*.sig"))
    platforms: dict[str, dict] = {}
    for key, pattern in PLATFORMS.items():
        hits = [s for s in sigs if re.search(pattern + r"\.sig$", s.name)]
        if len(hits) != 1:
            sys.exit(f"{key}: expected one signed package matching {pattern}, got {[h.name for h in hits]}")
        pkg = hits[0].with_suffix("")
        if not pkg.is_file():
            sys.exit(f"{key}: {hits[0].name} has no package {pkg.name} next to it")
        platforms[key] = {
            "signature": hits[0].read_text("utf-8").strip(),
            "url": f"https://github.com/{repo}/releases/download/v{version}/{pkg.name}",
        }
    return {
        "version": version,
        "notes": f"https://github.com/{repo}/releases/tag/v{version}",
        "pub_date": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "platforms": platforms,
    }


def main() -> None:
    dist, version, repo = Path(sys.argv[1]), sys.argv[2].removeprefix("v"), sys.argv[3]
    manifest = build(dist, version, repo)
    (dist / "latest.json").write_text(json.dumps(manifest, indent=2) + "\n", "utf-8")
    for sig in dist.glob("*.sig"):
        sig.unlink()
    print(f"latest.json: v{version}, {len(manifest['platforms'])} platforms")


if __name__ == "__main__":
    main()
