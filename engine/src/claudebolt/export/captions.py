"""SRT / VTT from the transcript, remapped to edited-output time."""

from __future__ import annotations

from ..timeline.model import Project, source_to_output

MAX_CHARS = 42
MAX_LINES = 2
MAX_SECONDS = 7.0
GAP = 0.7


def kept_words(p: Project) -> list[tuple[str, float, float]]:
    """(text, out_start, out_end) for words whose midpoint lies in a non-removed segment."""
    if p.transcript is None:
        raise ValueError("no transcript: transcribe first")
    out = []
    segs = p.segments
    j = 0
    for w in p.transcript.words:
        mid = (w.start + w.end) / 2
        while j < len(segs) - 1 and segs[j].end < mid:
            j += 1
        if segs[j].op == "remove":
            continue
        a = source_to_output(segs, w.start)
        b = source_to_output(segs, w.end)
        out.append((w.text.strip(), a, max(b, a + 0.01)))
    return out


def cues(p: Project) -> list[tuple[float, float, str]]:
    words = kept_words(p)
    res: list[tuple[float, float, str]] = []
    cur: list[tuple[str, float, float]] = []

    def flush() -> None:
        if not cur:
            return
        text = " ".join(t for t, _, _ in cur)
        if len(text) > MAX_CHARS:
            mid = len(text) // 2
            cut = min((i for i, c in enumerate(text) if c == " "), key=lambda i: abs(i - mid))
            text = text[:cut] + "\n" + text[cut + 1:]
        res.append((cur[0][1], cur[-1][2], text))
        cur.clear()

    for w in words:
        if cur:
            chars = len(" ".join(t for t, _, _ in cur)) + 1 + len(w[0])
            if (w[1] - cur[-1][2] > GAP or chars > MAX_CHARS * MAX_LINES
                    or w[2] - cur[0][1] > MAX_SECONDS):
                flush()
        cur.append(w)
        if w[0][-1:] in ".?!":
            flush()
    flush()
    return res


def _ts(t: float, sep: str) -> str:
    ms = round(t * 1000)
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d}{sep}{ms % 1000:03d}"


def srt(p: Project) -> str:
    return "".join(f"{i}\n{_ts(a, ',')} --> {_ts(b, ',')}\n{text}\n\n"
                   for i, (a, b, text) in enumerate(cues(p), 1))


def vtt(p: Project) -> str:
    return "WEBVTT\n\n" + "".join(f"{_ts(a, '.')} --> {_ts(b, '.')}\n{text}\n\n"
                                   for a, b, text in cues(p))
