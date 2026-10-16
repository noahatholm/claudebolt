"""Token normalization for transcript matching."""

from __future__ import annotations

import re

_APOS = str.maketrans({"’": "'", "‘": "'", "`": "'"})
_STRIP = re.compile(r"[^\w']+", re.UNICODE)


def norm(text: str) -> str:
    t = _STRIP.sub("", text.lower().translate(_APOS)).strip("'")
    if re.fullmatch(r"u+m+", t):
        return "um"
    if re.fullmatch(r"u+h+", t):
        return "uh"
    if re.fullmatch(r"h+m+", t):
        return "hmm"
    if re.fullmatch(r"m{2,}", t):
        return "mm"
    if re.fullmatch(r"e+r+m*", t) and len(t) <= 4:
        return "er"
    if t == "you're":
        return "your"
    return t
