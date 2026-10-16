import subprocess

import pytest

from claudebolt.detect import threshold
from claudebolt.media.decode import decode
from claudebolt.media.ffmpeg import ffprobe_path
from claudebolt.media.probe import probe
from claudebolt.service import Service


def dur(path) -> float:
    out = subprocess.run([ffprobe_path(), "-v", "error", "-show_entries", "format=duration",
                          "-of", "csv=p=0", str(path)], capture_output=True, text=True)
    return float(out.stdout)


def test_probe_audio_and_video(media):
    a = probe(media / "pattern.wav")
    assert a.kind == "audio" and a.video is None and a.duration == pytest.approx(5.7, abs=0.05)
    v = probe(media / "pattern.mp4")
    assert v.kind == "video" and v.video.width == 640 and v.video.fps == pytest.approx(30)
    v60 = probe(media / "pattern60.mp4")
    assert v60.video.fps == pytest.approx(59.94, abs=0.01)


def test_decode_levels(media):
    src = probe(media / "pattern.wav")
    an = decode(src)
    assert len(an.levels) == pytest.approx(5.7 / 0.04, abs=2)
    assert an.levels[10] > -30 and an.levels[50] < -80  # tone vs digital silence
    again = decode(src)  # served from cache
    assert (again.levels == an.levels).all()


def test_golden_cut_list(media):
    svc = Service()
    pid = svc.open_media([str(media / "pattern.wav")])["id"]
    svc.detect_silence(pid)
    keeps = [(s.start, s.end) for s in svc.project(pid).segments if s.op == "keep"]
    assert len(keeps) == 2
    assert keeps[0][0] == pytest.approx(0.0, abs=0.04) and keeps[0][1] == pytest.approx(1.15, abs=0.04)
    assert keeps[1][0] == pytest.approx(2.99, abs=0.04) and keeps[1][1] == pytest.approx(4.85, abs=0.04)


def test_auto_threshold_with_noise(media):
    svc = Service()
    pid = svc.open_media([str(media / "noisy.wav")])["id"]
    a = svc.analyze_audio(pid)
    assert -60 <= a["suggested_threshold"] <= -20
    svc.detect_silence(pid, {"threshold": "auto"})
    keeps = [s for s in svc.project(pid).segments if s.op == "keep"]
    assert len(keeps) == 2


def test_threshold_helpers():
    import numpy as np

    lv = np.concatenate([np.full(100, -60.0), np.full(100, -20.0)])
    assert threshold.auto_threshold(lv) == pytest.approx(-54.0)
    assert threshold.analyze(np.full(50, -30.0))["warnings"]


@pytest.mark.parametrize("name", ["pattern.mp4", "pattern60.mp4", "pattern.wav", "pattern.mp3"])
def test_render_duration_matches_timeline(media, name):
    svc = Service()
    pid = svc.open_media([str(media / name)])["id"]
    svc.detect_silence(pid)
    p = svc.project(pid)
    ext = name.rsplit(".", 1)[1]
    out = media / f"out_{name}"
    job = svc.render(pid, str(out))
    j = svc.wait_job(job["job_id"], 60)
    assert j["status"] == "done", j
    tol = (1 / p.fps + 0.005) if p.fps else 0.05 if ext == "mp3" else 0.002
    assert dur(out) == pytest.approx(p.output_duration, abs=tol)
    if p.fps:  # A/V drift under one frame
        out_v = subprocess.run([ffprobe_path(), "-v", "error", "-show_entries", "stream=codec_type,duration",
                                "-of", "csv=p=0", str(out)], capture_output=True, text=True).stdout
        ds = [float(x.split(",")[1]) for x in out_v.split() if "," in x and x.split(",")[1] != "N/A"]
        assert max(ds) - min(ds) < 1 / p.fps


def test_speed_instead_of_cut(media):
    svc = Service()
    pid = svc.open_media([str(media / "pattern.wav")])["id"]
    svc.detect_silence(pid, {"silence_action": "speed", "speed_rate": 4.0})
    p = svc.project(pid)
    assert any(s.op == "speed" for s in p.segments)
    out = media / "sped.wav"
    j = svc.wait_job(svc.render(pid, str(out))["job_id"], 60)
    assert j["status"] == "done", j
    assert dur(out) == pytest.approx(p.output_duration, abs=0.01)


def test_multitrack_or_combine(media):
    svc = Service()
    pid = svc.open_media([str(media / "multitrack" / "a.wav"), str(media / "multitrack" / "b.wav")])["id"]
    solo = Service()
    sid = solo.open_media([str(media / "multitrack" / "a.wav")])["id"]
    svc.detect_silence(pid, {"snap_window": 0})
    solo.detect_silence(sid, {"snap_window": 0})
    assert svc.project(pid).output_duration > solo.project(sid).output_duration
    out = media / "mt.wav"
    j = svc.wait_job(svc.render(pid, str(out))["job_id"], 60)
    assert j["status"] == "done", j
    assert dur(out) == pytest.approx(svc.project(pid).output_duration, abs=0.01)


def test_split_concat_matches_single_pass(media):
    svc = Service()
    pid = svc.open_media([str(media / "pattern.wav")])["id"]
    svc.detect_silence(pid)
    import claudebolt.render.render as r

    old = r.CHUNK_PIECES
    r.CHUNK_PIECES = 1
    try:
        out = media / "split.wav"
        j = svc.wait_job(svc.render(pid, str(out), {"split_concat": True})["job_id"], 60)
    finally:
        r.CHUNK_PIECES = old
    assert j["status"] == "done", j
    assert dur(out) == pytest.approx(svc.project(pid).output_duration, abs=0.01)


def test_cancelled_render_leaves_no_file(media):
    svc = Service()
    pid = svc.open_media([str(media / "pattern.mp4")])["id"]
    out = media / "cancel.mp4"
    job = svc.render(pid, str(out))
    svc.cancel_job(job["job_id"])
    j = svc.wait_job(job["job_id"], 60)
    assert j["status"] in ("cancelled", "done")
    if j["status"] == "cancelled":
        assert not out.exists()


def test_preview_clip(media):
    svc = Service()
    pid = svc.open_media([str(media / "pattern.wav")])["id"]
    svc.detect_silence(pid)
    r = svc.preview_clip(pid, 0.0, 1.0)
    assert r["status"] == "done" and dur(r["result"]["path"]) > 0.5
