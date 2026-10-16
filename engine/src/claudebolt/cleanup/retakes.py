"""Retake detector: an earlier sentence restated later (pure)."""

from __future__ import annotations

from rapidfuzz.distance import Levenshtein

from ..config import CleanupSettings
from ..timeline.model import Word
from .fillers import Detection
from .normalize import norm


def _match(a: list[str], b: list[str], thr: float) -> int:
    """Greedy one-to-one fuzzy word matching; returns the number of common words."""
    taken = [False] * len(b)
    common = 0
    for x in a:
        best, bi = 0.0, -1
        for k, y in enumerate(b):
            if taken[k]:
                continue
            s = Levenshtein.normalized_similarity(x, y)
            if s > best:
                best, bi = s, k
        if bi >= 0 and best >= thr:
            taken[bi] = True
            common += 1
    return common


def _is_prefix(a: list[str], b: list[str], thr: float) -> bool:
    return len(a) <= len(b) and all(
        Levenshtein.normalized_similarity(x, y) >= thr for x, y in zip(a, b)
    )


def detect_retakes(words: list[Word], sentences: list[tuple[int, int]],
                   cfg: CleanupSettings) -> list[Detection]:
    toks = [norm(w.text) for w in words]
    out: list[Detection] = []
    for i, (a0, a1) in enumerate(sentences):
        a = [t for t in toks[a0:a1 + 1] if t]
        if len(a) < 2:
            continue
        for j in range(i + 1, min(len(sentences), i + 1 + cfg.look_ahead)):
            b0, b1 = sentences[j]
            b = [t for t in toks[b0:b1 + 1] if t]
            common = _match(a, b, cfg.similarity)
            union = len(a) + len(b) - common
            jac = common / union if union else 0.0
            if len(a) >= 3 and jac >= cfg.similarity:
                out.append(Detection(a0, a1, "retake", round(jac, 2), f"restated in sentence {j}"))
                break
            if len(b) > len(a) and _is_prefix(a, b, cfg.similarity):
                out.append(Detection(a0, a1, "retake", 0.75, f"restarted in sentence {j}"))
                break
    return out
