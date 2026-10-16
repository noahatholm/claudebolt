"""Repeated-phrase and cut-off-word detector (pure)."""

from __future__ import annotations

from ..config import CleanupSettings
from ..timeline.model import Word
from .fillers import Detection
from .normalize import norm


def detect_false_starts(words: list[Word], cfg: CleanupSettings | None = None) -> list[Detection]:
    toks = [norm(w.text) for w in words]
    out: list[Detection] = []
    used: set[int] = set()
    for n in (3, 2, 1):  # prefer longer repeats
        for i in range(len(words) - 2 * n + 1):
            a, b = toks[i:i + n], toks[i + n:i + 2 * n]
            if a == b and all(a) and not any(k in used for k in range(i, i + n)):
                out.append(Detection(i, i + n - 1, "false_start", 0.85, "repeat: " + " ".join(a)))
                used.update(range(i, i + n))
    for i in range(len(words) - 1):
        if i in used:
            continue
        raw = words[i].text.strip()
        t, nxt = toks[i], toks[i + 1]
        if raw.endswith(("-", "–", "—")) and nxt:
            out.append(Detection(i, i, "false_start", 0.7, f"cut-off: {raw}"))
        elif len(t) >= 3 and len(nxt) >= len(t) + 2 and nxt.startswith(t):
            out.append(Detection(i, i, "false_start", 0.6, f"cut-off word: {t} -> {nxt}"))
    return sorted(out, key=lambda d: d.word_start)
