"""python scripts/test_make_latest_json.py (stdlib only)"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).with_name("make_latest_json.py")
PACKAGES = [
    "claudebolt_1.2.3_x64-setup.exe", "claudebolt_1.2.3_x64_en-US.msi",
    "claudebolt_1.2.3_amd64.deb", "claudebolt_1.2.3_arm64.deb",
    "claudebolt-1.2.3-1.x86_64.rpm", "claudebolt-1.2.3-1.aarch64.rpm",
    "claudebolt_1.2.3_aarch64.app.tar.gz",
]


def run(dist: Path):
    return subprocess.run([sys.executable, str(SCRIPT), str(dist), "v1.2.3", "o/r"],
                          capture_output=True, text=True)


class MakeLatestJson(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dist = Path(self.tmp.name)
        for name in PACKAGES:
            (self.dist / name).write_bytes(b"pkg")
            (self.dist / f"{name}.sig").write_text(f"SIG-{name}\n", "utf-8")
        (self.dist / "claudebolt_1.2.3_aarch64.dmg").write_bytes(b"not updatable")
        (self.dist / "claudebolt-1.2.3-windows-x64-portable.zip").write_bytes(b"not updatable")

    def tearDown(self):
        self.tmp.cleanup()

    def test_manifest(self):
        r = run(self.dist)
        self.assertEqual(r.returncode, 0, r.stderr)
        m = json.loads((self.dist / "latest.json").read_text("utf-8"))
        self.assertEqual(m["version"], "1.2.3")
        self.assertEqual(len(m["platforms"]), 7)
        nsis = m["platforms"]["windows-x86_64-nsis"]
        self.assertEqual(nsis["signature"], "SIG-claudebolt_1.2.3_x64-setup.exe")
        self.assertEqual(nsis["url"],
                         "https://github.com/o/r/releases/download/v1.2.3/claudebolt_1.2.3_x64-setup.exe")
        self.assertTrue(m["platforms"]["darwin-aarch64-app"]["url"].endswith("_aarch64.app.tar.gz"))
        self.assertEqual(list(self.dist.glob("*.sig")), [])  # folded in, not uploaded

    def test_missing_platform_fails(self):
        (self.dist / "claudebolt-1.2.3-1.aarch64.rpm.sig").unlink()
        r = run(self.dist)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("linux-aarch64-rpm", r.stderr)
        self.assertFalse((self.dist / "latest.json").exists())


if __name__ == "__main__":
    unittest.main()
