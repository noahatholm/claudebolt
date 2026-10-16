"""Filler-word detector (pure)."""

from __future__ import annotations

from dataclasses import dataclass

from ..config import CleanupSettings
from ..timeline.model import Word
from .normalize import norm

ALWAYS = {"um", "uh", "er", "ah", "hmm", "mm"}
CONTEXT = {"like", "so", "right", "actually", "basically", "literally"}
PAUSE = 0.15


@dataclass
class Detection:
    word_start: int
    word_end: int  # inclusive
    kind: str
    confidence: float
    note: str = ""


def detect_fillers(words: list[Word], cfg: CleanupSettings) -> list[Detection]:
    toks = [norm(w.text) for w in words]
    phrases = sorted((tuple(norm(x) for x in f.split()) for f in cfg.fillers), key=len, reverse=True)
    out: list[Detection] = []
    i = 0
    while i < len(words):
        hit = None
        for ph in phrases:
            n = len(ph)
            if n and tuple(toks[i:i + n]) == ph:
                hit = ph
                break
        if hit is None:
            i += 1
            continue
        j = i + len(hit) - 1
        conf = _confidence(words, i, j, hit)
        out.append(Detection(i, j, "filler", round(min(conf, 0.99), 2), " ".join(hit)))
        i = j + 1
    return out


def _confidence(words: list[Word], a: int, b: int, ph: tuple[str, ...]) -> float:
    if len(ph) == 1 and ph[0] in ALWAYS:
        return 0.95
    base = 0.4 if len(ph) == 1 and ph[0] in CONTEXT else 0.5
    before = words[a].start - words[a - 1].end if a > 0 else 1.0
    after = words[b + 1].start - words[b].end if b + 1 < len(words) else 1.0
    if before > PAUSE and after > PAUSE:
        base += 0.3
    if ph == ("so",):
        prev = words[a - 1].text.strip() if a > 0 else "."
        if a == 0 or prev[-1:] in ".?!":
            base += 0.2
    if ph == ("like",) and (words[b].text.rstrip().endswith(",") or after > PAUSE):
        base += 0.3
    return base
