"""Sentence segmentation over word lists, plus transcript import."""

from __future__ import annotations

import json
import re
from pathlib import Path

from ..timeline.model import Transcript, Word

GAP = 0.7


def make_sentences(words: list[Word]) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    start = 0
    for i, w in enumerate(words):
        last = i == len(words) - 1
        end_punct = w.text.rstrip()[-1:] in ".?!"
        gap = (words[i + 1].start - w.end) > GAP if not last else False
        if last or end_punct or gap:
            out.append((start, i))
            start = i + 1
    return out


def build(words: list[Word], model: str, language: str) -> Transcript:
    return Transcript(model=model, language=language, words=words, sentences=make_sentences(words))


def import_json(path: str | Path) -> Transcript:
    """Accept [{word|text, start, end}] or {words: [...]}."""
    data = json.loads(Path(path).read_text("utf-8"))
    items = data["words"] if isinstance(data, dict) else data
    words = [Word(text=i.get("word", i.get("text", "")), start=float(i["start"]),
                  end=float(i["end"])) for i in items]
    return build(words, "imported", "en")


_TS = re.compile(r"(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)")


def import_srt(path: str | Path) -> Transcript:
    """Cue-level SRT; words are spread evenly over each cue."""
    words: list[Word] = []
    for block in re.split(r"\n\s*\n", Path(path).read_text("utf-8-sig").strip()):
        lines = block.strip().splitlines()
        for k, ln in enumerate(lines):
            m = _TS.search(ln)
            if m:
                g = list(map(int, m.groups()))
                a = g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000
                b = g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1000
                toks = " ".join(lines[k + 1:]).split()
                for n, t in enumerate(toks):
                    d = (b - a) / max(1, len(toks))
                    words.append(Word(text=t, start=a + n * d, end=a + (n + 1) * d))
                break
    return build(words, "imported", "en")
