"""Generate test media with ffmpeg lavfi into tests/.fixtures/ (not committed)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from claudebolt.media.ffmpeg import ffmpeg_path

OUT = Path(__file__).resolve().parents[1] / ".fixtures"

# sine 1s | silence 2s | sine 0.3s | silence 0.4s | sine 1s | silence 1s  (= 5.7 s)
PATTERN = [("s", 1.0), ("z", 2.0), ("s", 0.3), ("z", 0.4), ("s", 1.0), ("z", 1.0)]


def _ff(*args: str) -> None:
    subprocess.run([ffmpeg_path(), "-y", "-v", "error", "-nostdin", *args], check=True)


def _pattern_filter(freq: int = 440, vol: float = 0.5) -> tuple[list[str], str]:
    inputs: list[str] = []
    labels = ""
    for i, (kind, d) in enumerate(PATTERN):
        src = (f"sine=frequency={freq}:sample_rate=48000:duration={d}" if kind == "s"
               else f"anullsrc=r=48000:cl=mono:d={d}")
        inputs += ["-f", "lavfi", "-t", str(d), "-i", src]
        labels += f"[{i}:a]"
    return inputs, f"{labels}concat=n={len(PATTERN)}:v=0:a=1,volume={vol}[a]"


def make(force: bool = False) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    wav = OUT / "pattern.wav"
    if force or not wav.exists():
        inp, fc = _pattern_filter()
        _ff(*inp, "-filter_complex", fc, "-map", "[a]", "-ac", "1", str(wav))
    mp3 = OUT / "pattern.mp3"
    if force or not mp3.exists():
        _ff("-i", str(wav), "-c:a", "libmp3lame", "-q:a", "2", str(mp3))
    for name, rate in (("pattern.mp4", "30"), ("pattern60.mp4", "60000/1001")):
        mp4 = OUT / name
        if force or not mp4.exists():
            _ff("-f", "lavfi", "-i", f"testsrc2=size=640x360:rate={rate}:duration=5.7",
                "-i", str(wav), "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-shortest", str(mp4))
    noisy = OUT / "noisy.wav"
    if force or not noisy.exists():
        _ff("-i", str(wav), "-f", "lavfi", "-i", "anoisesrc=color=pink:amplitude=0.02:duration=5.7:r=48000",
            "-filter_complex", "[0:a][1:a]amix=inputs=2:duration=first:normalize=0[a]",
            "-map", "[a]", "-ac", "1", str(noisy))
    # track B: shifted by 0.237 s and talking in A's gaps
    mt = OUT / "multitrack"
    mt.mkdir(exist_ok=True)
    if force or not (mt / "b.wav").exists():
        _ff("-i", str(wav), "-c", "copy", str(mt / "a.wav"))
        _ff("-f", "lavfi", "-i", "sine=frequency=330:sample_rate=48000:duration=0.8",
            "-af", "adelay=1500,apad=whole_dur=5.7", "-ac", "1", str(mt / "b.wav"))
    return OUT


SPEECH_TEXT = ("Welcome to the show. Um, today we talk about editing. "
               "Uh, we talk about editing audio files. The end.")


def make_speech() -> Path | None:
    """Offline TTS clip with planted fillers (Windows SAPI). Returns None if unavailable."""
    wav = OUT / "speech.wav"
    if wav.exists():
        return wav
    if sys.platform != "win32":
        return None
    OUT.mkdir(parents=True, exist_ok=True)
    ps = ("Add-Type -AssemblyName System.Speech; $s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
          f"$s.SetOutputToWaveFile('{wav}'); $s.Speak('{SPEECH_TEXT}'); $s.Dispose()")
    r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True)
    return wav if r.returncode == 0 and wav.exists() else None


# Five quiet, drawn-out hesitations between sentences: the kind Whisper's VAD gate used to drop.
SOFT_SSML = """<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="en-US">
So the first thing I do is open the project. <break time="900ms"/>
<prosody volume="x-soft" rate="x-slow">uhhh</prosody> <break time="900ms"/>
Then I look at the waveform. <break time="1s"/>
<prosody volume="soft" rate="x-slow">ummm</prosody> <break time="700ms"/>
and I find the long pauses. <break time="800ms"/>
<prosody volume="x-soft" rate="slow">uh</prosody> <break time="600ms"/>
It is really, <prosody volume="soft" rate="x-slow">uhm</prosody> fast once you get used to it.
<break time="900ms"/> <prosody volume="x-soft" rate="x-slow">hmmm</prosody> <break time="900ms"/>
That is all for today.
</speak>"""
SOFT_HESITATIONS = 5


def make_soft_speech() -> Path | None:
    """Offline TTS clip with soft hesitations (Windows SAPI). Returns None if unavailable."""
    wav = OUT / "soft_speech.wav"
    if wav.exists():
        return wav
    if sys.platform != "win32":
        return None
    OUT.mkdir(parents=True, exist_ok=True)
    ssml = OUT / "soft_speech.ssml"
    ssml.write_text(SOFT_SSML, "utf-8")
    ps = ("Add-Type -AssemblyName System.Speech; $s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
          f"$s.SetOutputToWaveFile('{wav}'); $s.SpeakSsml([IO.File]::ReadAllText('{ssml}')); $s.Dispose()")
    r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True)
    return wav if r.returncode == 0 and wav.exists() else None


if __name__ == "__main__":
    print(make(force="--force" in sys.argv), make_speech(), make_soft_speech())
