"""Build the media folder the UI end-to-end tests open (run inside the engine's environment).

Every test gets its own copy of a fixture because the engine keeps projects open between tests.
The "talk" files come with a saved project holding a known transcript, so no Whisper model is needed.
"""

import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "engine" / "tests" / "fixtures"))

import make_fixtures  # noqa: E402

from claudebolt.service import Service  # noqa: E402
from claudebolt.timeline.model import Word  # noqa: E402
from claudebolt.transcribe.sentences import build  # noqa: E402

# Laid over the fixture's tone bursts (0-1.0 s, 3.0-3.3 s, 3.7-4.7 s), with one planted "um".
WORDS = [Word(text="Hello", start=0.1, end=0.4), Word(text="um", start=0.5, end=0.8),
         Word(text="world.", start=0.9, end=1.0), Word(text="Again", start=3.0, end=3.3),
         Word(text="there.", start=3.8, end=4.5)]

out = Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=True)
fx = make_fixtures.make()
for name in ("video", "export"):
    shutil.copy(fx / "pattern.mp4", out / f"{name}.mp4")
for name in ("detect", "speech", "zoom", "render"):
    shutil.copy(fx / "pattern.wav", out / f"{name}.wav")
svc = Service()
for name in ("talk", "fillers"):
    p = out / f"{name}.wav"
    shutil.copy(fx / "pattern.wav", p)
    pid = svc.open_media([str(p)])["id"]
    svc.set_transcript(pid, build(list(WORDS), "test", "en"))
    svc.save_project(pid)
print(out)
