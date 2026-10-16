import subprocess
import tracemalloc

import pytest

from claudebolt.media.decode import decode
from claudebolt.media.ffmpeg import ffmpeg_path, ffprobe_path
from claudebolt.media.probe import probe
from claudebolt.render import encoders
from claudebolt.service import Service


def dur(p):
    return float(subprocess.run([ffprobe_path(), "-v", "error", "-show_entries", "format=duration",
                                 "-of", "csv=p=0", str(p)], capture_output=True, text=True).stdout)


def test_zoom_and_speed_graph(media):
    svc = Service()
    pid = svc.open_media([str(media / "pattern.mp4")])["id"]
    svc.detect_silence(pid, {"grace": 0.1, "min_keep": 0.2})
    svc.apply_edits(pid, [{"action": "zoom", "start": 0, "end": 1.0, "zoom": 1.5}])
    out = media / "zoom.mp4"
    j = svc.wait_job(svc.render(pid, str(out), {"zoom_mode": "alternate"})["job_id"], 60)
    assert j["status"] == "done", j
    assert dur(out) == pytest.approx(svc.project(pid).output_duration, abs=0.07)


def test_audio_out_of_video_source(media):
    svc = Service()
    pid = svc.open_media([str(media / "pattern.mp4")])["id"]
    svc.detect_silence(pid)
    out = media / "only_audio.mp3"
    j = svc.wait_job(svc.render(pid, str(out))["job_id"], 60)
    assert j["status"] == "done", j
    info = probe(out)
    assert info.kind == "audio"


def test_encoder_selection_is_verified():
    assert encoders.pick_video_encoder("libx264") == "libx264"
    assert encoders.pick_video_encoder("h264_does_not_exist") == "libx264"
    assert encoders.pick_video_encoder("auto") in encoders.available() | {"libx264"}


def test_auto_encoder_render_works(media):
    svc = Service()
    pid = svc.open_media([str(media / "pattern.mp4")])["id"]
    svc.detect_silence(pid)
    out = media / "auto.mp4"
    j = svc.wait_job(svc.render(pid, str(out), {"encoder_pref": "auto"})["job_id"], 120)
    assert j["status"] == "done", j


@pytest.mark.slow
def test_two_hour_decode_streams_in_constant_memory(tmp_path):
    wav = tmp_path / "long.wav"
    subprocess.run([ffmpeg_path(), "-y", "-v", "error", "-f", "lavfi", "-i",
                    "sine=frequency=300:sample_rate=16000:duration=7200", "-ac", "1", str(wav)],
                   check=True)
    src = probe(wav)
    tracemalloc.start()
    an = decode(src)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert len(an.levels) == pytest.approx(7200 / 0.04, abs=5)
    assert peak < 300 * 1024 * 1024


def test_auto_sync_recovers_offset(media):
    import numpy as np

    from claudebolt.detect.multitrack import estimate_offset

    rng = np.random.default_rng(1)
    base = np.zeros(16000 * 20, np.float32)
    for s in rng.integers(0, 16000 * 18, 12):  # random bursts of "speech"
        base[s:s + 4000] = rng.normal(0, 0.3, 4000)
    lag = int(0.237 * 16000)
    other = np.concatenate((np.zeros(lag, np.float32), base))[: len(base)]  # other is late by .237
    est = estimate_offset(base, other)
    assert est == pytest.approx(-0.237, abs=0.002) or est == pytest.approx(0.237, abs=0.002)
    # sign: adding `est` to the other track's times must line it up with the reference
    assert est == pytest.approx(-0.237, abs=0.002)


def test_service_sync_and_vfr_warning(media):
    svc = Service()
    pid = svc.open_media([str(media / "pattern.wav"), str(media / "pattern.wav")])["id"]
    assert svc.auto_sync(pid)["offsets"][1] == pytest.approx(0.0, abs=0.002)
    svc.set_track(pid, 1, muted=True)
    assert svc.project(pid).tracks[1].muted
    assert svc.describe(pid)["warnings"] == []
