import pytest

from claudebolt.service import Service

pytestmark = pytest.mark.slow


def test_tiny_en_finds_planted_fillers(fx, tmp_path):
    import make_fixtures

    speech = make_fixtures.make_speech()
    if speech is None:
        pytest.skip("no offline TTS available")
    pytest.importorskip("faster_whisper")
    import shutil

    wav = tmp_path / "speech.wav"
    shutil.copy(speech, wav)
    svc = Service()
    pid = svc.open_media([str(wav)])["id"]
    j = svc.wait_job(svc.download_model("tiny.en")["job_id"], 600)
    assert j["status"] == "done", j
    j = svc.wait_job(svc.transcribe(pid, "tiny.en")["job_id"], 600)
    assert j["status"] == "done", j
    words = [w.text.lower().strip(" ,.") for w in svc.project(pid).transcript.words]
    assert "editing" in words
    r = svc.run_cleanup(pid, ["filler"])
    props = svc.list_proposals(pid)["proposals"]
    found = {p["text"].lower().strip(" ,.") for p in props}
    # the TTS says both planted fillers; tiny.en may drop one, but must catch at least one
    assert found & {"um", "uh"}, (words, r)
    # transcript is cached: second run is instant and identical
    j2 = svc.wait_job(svc.transcribe(pid, "tiny.en")["job_id"], 60)
    assert j2["result"]["words"] == j["result"]["words"]


def test_vad_beats_rms_on_noise_bed(fx, tmp_path):
    """Speech over a steady noise bed: RMS keeps the bed, VAD cuts the pauses."""
    import subprocess

    import make_fixtures

    from claudebolt.detect import vad
    from claudebolt.media.ffmpeg import ffmpeg_path

    speech = make_fixtures.make_speech()
    if speech is None:
        pytest.skip("no offline TTS available")
    pytest.importorskip("onnxruntime")
    try:
        vad.ensure_model()
    except Exception:
        pytest.skip("VAD model unavailable (offline)")
    bed = tmp_path / "bed.wav"
    subprocess.run([ffmpeg_path(), "-y", "-v", "error", "-i", str(speech), "-f", "lavfi", "-i",
                    "anoisesrc=color=pink:amplitude=0.05:r=22050", "-filter_complex",
                    "[0:a]aresample=22050[a0];[a0][1:a]amix=inputs=2:duration=first:normalize=0",
                    "-ac", "1", str(bed)], check=True)
    svc = Service()
    pid = svc.open_media([str(bed)])["id"]
    svc.detect_silence(pid, {"mode": "rms", "threshold": -45.0})
    rms_out = svc.project(pid).output_duration
    svc.detect_silence(pid, {"mode": "vad"})
    vad_out = svc.project(pid).output_duration
    assert vad_out < rms_out - 0.5, (rms_out, vad_out)
