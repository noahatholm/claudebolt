"""Detections -> Proposal objects with time spans."""

from __future__ import annotations

from ..config import CleanupSettings
from ..timeline.model import Proposal, Transcript, Word
from .false_starts import detect_false_starts
from .fillers import Detection, detect_fillers
from .retakes import detect_retakes

MAX_REACH = 0.25


def span(words: list[Word], a: int, b: int, duration: float) -> tuple[float, float]:
    """Cover words a..b plus half of the adjacent gaps; never reach into neighbouring words."""
    prev_end = words[a - 1].end if a > 0 else 0.0
    next_start = words[b + 1].start if b + 1 < len(words) else duration
    pre = min(max(0.0, (words[a].start - prev_end) / 2), MAX_REACH)
    post = min(max(0.0, (next_start - words[b].end) / 2), MAX_REACH)
    return words[a].start - pre, words[b].end + post


def run_cleanup(t: Transcript, cfg: CleanupSettings, duration: float,
                kinds: list[str] | None = None) -> list[Proposal]:
    kinds = kinds or cfg.kinds
    dets: list[Detection] = []
    if "filler" in kinds:
        dets += detect_fillers(t.words, cfg)
    if "false_start" in kinds:
        dets += detect_false_starts(t.words, cfg)
    if "retake" in kinds:
        dets += detect_retakes(t.words, t.sentences, cfg)
    dets = [d for d in dets if d.confidence >= cfg.min_confidence]
    # drop detections fully inside an earlier/larger one
    dets.sort(key=lambda d: (d.word_start, -(d.word_end - d.word_start)))
    kept: list[Detection] = []
    for d in dets:
        if any(k.word_start <= d.word_start and d.word_end <= k.word_end for k in kept):
            continue
        kept.append(d)
    out = []
    for d in kept:
        s, e = span(t.words, d.word_start, d.word_end, duration)
        text = " ".join(w.text.strip() for w in t.words[d.word_start:d.word_end + 1])
        out.append(Proposal(kind=d.kind, start=s, end=e, word_range=(d.word_start, d.word_end),
                            text=text, confidence=d.confidence, note=d.note))
    return out
