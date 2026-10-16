"""End to end: the real `claudebolt serve` process driven the way the app drives it (REST plus the
/events WebSocket), and the real CLI, from opening media to rendered files and exports on disk."""

import json
import os
import subprocess
import sys
import threading
import time

import httpx
import pytest
from websockets.sync.client import connect as ws_connect

from claudebolt.media.probe import probe
from claudebolt.service import Service
from claudebolt.timeline.model import Word
from claudebolt.transcribe.sentences import build

# Words laid over the fixture's tone bursts (0-1.0 s, 3.0-3.3 s, 3.7-4.7 s), with one planted "um".
WORDS = [Word(text="Hello", start=0.1, end=0.4), Word(text="um", start=0.5, end=0.8),
         Word(text="world.", start=0.9, end=1.0), Word(text="Again", start=3.0, end=3.3),
         Word(text="there.", start=3.8, end=4.5)]


class Daemon:
    """A `claudebolt serve` subprocess plus a client that records every /events message."""

    def __init__(self, env: dict):
        self.proc = subprocess.Popen([sys.executable, "-m", "claudebolt", "serve", "--port", "0"],
                                     stdout=subprocess.PIPE, text=True, env=env)
        info = json.loads(self.proc.stdout.readline())
        self.base = f"http://127.0.0.1:{info['port']}/api"
        self.http = httpx.Client(headers={"Authorization": f"Bearer {info['token']}"}, timeout=60)
        self.events: list[dict] = []
        self._url = f"ws://127.0.0.1:{info['port']}/events?token={info['token']}"
        self._ws = None
        connected = threading.Event()
        self._reader = threading.Thread(target=self._read, args=(connected,), daemon=True)
        self._reader.start()
        assert connected.wait(10), "could not connect to /events"

    def _read(self, connected: threading.Event):
        try:
            with ws_connect(self._url, origin="http://tauri.localhost", open_timeout=10) as ws:
                self._ws = ws
                connected.set()
                for msg in ws:
                    self.events.append(json.loads(msg))
        except Exception:
            pass  # socket closed at shutdown

    def get(self, path: str, **kw):
        r = self.http.get(self.base + path, **kw)
        assert r.status_code == 200, r.text
        return r.json()

    def post(self, path: str, body: dict | None = None):
        r = self.http.post(self.base + path, json=body or {})
        assert r.status_code == 200, r.text
        return r.json()

    def wait_job(self, job_id: str, timeout: float = 60) -> dict:
        t0 = time.time()
        while time.time() - t0 < timeout:
            st = self.get(f"/jobs/{job_id}")
            if st["status"] in ("done", "failed", "cancelled"):
                return st
            time.sleep(0.1)
        raise TimeoutError(job_id)

    def wait_event(self, pred, timeout: float = 10) -> dict:
        t0 = time.time()
        while time.time() - t0 < timeout:
            hit = next((e for e in self.events if pred(e)), None)
            if hit:
                return hit
            time.sleep(0.05)
        raise AssertionError(f"no matching event in {[e.get('type') for e in self.events]}")

    def close(self):
        if self._ws is not None:
            self._ws.close()
        self._reader.join(5)
        self.http.close()
        self.proc.terminate()
        self.proc.wait(10)


@pytest.fixture
def daemon_env(media):
    return os.environ | {"CLAUDEBOLT_CACHE": str(media.parent / "ecache")}


def seed_transcript(media_path):
    """Save a project with a known transcript next to the media; opening the media loads it."""
    svc = Service()
    pid = svc.open_media([str(media_path)])["id"]
    svc.set_transcript(pid, build(list(WORDS), "test", "en"))
    svc.save_project(pid)


def test_daemon_video_journey(media, daemon_env):
    """Open -> detect -> filler cleanup -> render -> export -> undo -> save -> reopen in a new daemon."""
    video = media / "pattern.mp4"
    seed_transcript(video)
    d = Daemon(daemon_env)
    try:
        opened = d.post("/projects", {"paths": [str(video)]})
        pid = opened["id"]
        assert opened["has_transcript"] and opened["loaded_existing"]
        assert opened["sources"][0]["kind"] == "video"
        assert len(d.get(f"/projects/{pid}/peaks", params={"px": 500})["peaks"]) == 500
        assert "suggested_threshold" in d.get(f"/projects/{pid}/analyze")

        det = d.post(f"/projects/{pid}/detect", {"settings": {"threshold": -35}})
        assert det["percent_removed"] > 30
        d.wait_event(lambda e: e["type"] == "timeline.changed" and e.get("project") == pid)
        after_silence = det["output_duration"]

        words = d.get(f"/projects/{pid}/transcript")["words"]
        assert [w["text"] for w in words] == [w.text for w in WORDS]
        d.post(f"/projects/{pid}/cleanup", {"kinds": ["filler"]})
        props = d.get(f"/projects/{pid}/proposals")["proposals"]
        assert [(p["kind"], p["text"]) for p in props] == [("filler", "um")]
        d.post(f"/projects/{pid}/proposals/accept", {"min_confidence": 0.8})
        summary = d.get(f"/projects/{pid}/timeline", params={"detail": "summary"})
        assert summary["output_duration"] < after_silence

        out = media / "journey.mp4"
        job = d.post(f"/projects/{pid}/render", {"output_path": str(out)})
        st = d.wait_job(job["job_id"])
        assert st["status"] == "done", st
        d.wait_event(lambda e: e["type"] == "job.done" and e.get("job") == job["job_id"])
        rendered = probe(out)
        assert rendered.kind == "video"
        assert rendered.duration == pytest.approx(summary["output_duration"], abs=0.1)

        for fmt in ("fcpxml", "edl", "srt"):
            path = d.post(f"/projects/{pid}/export", {"format": fmt})["path"]
            assert os.path.getsize(path) > 0
        srt = open(d.post(f"/projects/{pid}/export", {"format": "srt"})["path"], encoding="utf-8").read()
        assert "Hello" in srt and "um" not in srt.split()

        assert d.post(f"/projects/{pid}/undo")["applied"]
        undone = d.get(f"/projects/{pid}/timeline", params={"detail": "summary"})["output_duration"]
        assert undone == pytest.approx(after_silence, abs=0.01)
        saved_version = d.get(f"/projects/{pid}")["version"]
        d.post(f"/projects/{pid}/save")
    finally:
        d.close()

    d2 = Daemon(daemon_env)
    try:
        again = d2.post("/projects", {"paths": [str(video)]})
        assert again["loaded_existing"] and again["has_transcript"]
        assert again["version"] == saved_version
        assert again["output_duration"] == pytest.approx(undone, abs=0.01)
    finally:
        d2.close()


def test_daemon_audio_speed_up_journey(media, daemon_env):
    """Audio-only input with silences sped up instead of cut renders an audio file of the right length."""
    d = Daemon(daemon_env)
    try:
        pid = d.post("/projects", {"paths": [str(media / "pattern.wav")]})["id"]
        det = d.post(f"/projects/{pid}/detect", {"settings": {"silence_action": "speed", "speed_rate": 4}})
        segs = d.get(f"/projects/{pid}/timeline", params={"detail": "segments"})["segments"]
        assert any(s["op"] == "speed" for s in segs) and not any(s["op"] == "remove" for s in segs)
        out = media / "sped.wav"
        st = d.wait_job(d.post(f"/projects/{pid}/render", {"output_path": str(out)})["job_id"])
        assert st["status"] == "done", st
        rendered = probe(out)
        assert rendered.kind == "audio"
        assert rendered.duration == pytest.approx(det["output_duration"], abs=0.1)
    finally:
        d.close()


def test_daemon_rejects_bad_requests(media, daemon_env):
    d = Daemon(daemon_env)
    try:
        missing = d.http.post(d.base + "/projects", json={"paths": [str(media / "nope.mp4")]})
        assert missing.status_code == 400 and "hint" in missing.json()
        unknown = d.http.get(d.base + "/projects/doesnotexist")
        assert unknown.status_code == 400 and "doesnotexist" in unknown.text
        pid = d.post("/projects", {"paths": [str(media / "pattern.wav")]})["id"]
        stale = d.http.post(d.base + f"/projects/{pid}/edits",
                            json={"ops": [{"action": "remove", "start": 1, "end": 2}], "expected_version": 99})
        assert stale.status_code == 409
    finally:
        d.close()


@pytest.mark.parametrize("name", ["pattern.mp3", "pattern.mp4"])
def test_cli_cut(media, name, daemon_env):
    """`claudebolt cut` end to end: the output is shorter by exactly what detection removed."""
    src = media / name
    out = media / f"cut.{name}"
    r = subprocess.run([sys.executable, "-m", "claudebolt", "cut", str(src), "-o", str(out)],
                       capture_output=True, text=True, env=daemon_env, timeout=120)
    assert r.returncode == 0, r.stderr
    svc = Service()
    pid = svc.open_media([str(src)])["id"]
    expected = svc.detect_silence(pid)["output_duration"]
    got = probe(out)
    assert got.duration == pytest.approx(expected, abs=0.1)
    assert got.duration < probe(src).duration * 0.7
    assert got.kind == probe(src).kind


@pytest.mark.slow
def test_soft_hesitations_reach_the_transcript(tmp_path):
    """Regression: quiet, drawn-out "uhhh"s must survive transcription so cleanup can offer to cut them."""
    import make_fixtures

    speech = make_fixtures.make_soft_speech()
    if speech is None:
        pytest.skip("needs Windows text-to-speech to make the clip")
    pytest.importorskip("faster_whisper")
    import shutil

    wav = tmp_path / "soft_speech.wav"
    shutil.copy(speech, wav)
    svc = Service()
    pid = svc.open_media([str(wav)])["id"]
    j = svc.wait_job(svc.download_model("tiny.en")["job_id"], 600)
    assert j["status"] == "done", j
    j = svc.wait_job(svc.transcribe(pid, "tiny.en")["job_id"], 600)
    assert j["status"] == "done", j
    svc.run_cleanup(pid, ["filler"])
    fillers = [p for p in svc.project(pid).proposals if p.kind == "filler" and p.confidence >= 0.9]
    # The old VAD-gated decode kept 3 of these 5 with tiny.en; require at least 4.
    assert len(fillers) >= make_fixtures.SOFT_HESITATIONS - 1, [p.text for p in fillers]
