"""Generate placeholder app icons (stdlib only). Replace with real artwork later."""

import os
import struct
import zlib


def png(n: int) -> bytes:
    rows = []
    for y in range(n):
        row = b"\x00"
        for x in range(n):
            on = abs((x / n) - (1 - y / n)) < 0.12 and 0.15 < y / n < 0.85
            row += bytes((250, 204, 21, 255) if on else (15, 18, 24, 255))
        rows.append(row)

    def chunk(t: bytes, d: bytes) -> bytes:
        c = struct.pack(">I", len(d)) + t + d
        return c + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", n, n, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"".join(rows))) + chunk(b"IEND", b""))


out = os.path.join(os.path.dirname(__file__), "..", "src-tauri", "icons")
os.makedirs(out, exist_ok=True)
for n, name in ((32, "32x32.png"), (128, "128x128.png"), (256, "icon.png")):
    open(os.path.join(out, name), "wb").write(png(n))
p = png(256)
ico = struct.pack("<HHH", 0, 1, 1) + struct.pack("<BBBBHHII", 0, 0, 0, 0, 1, 32, len(p), 22) + p
open(os.path.join(out, "icon.ico"), "wb").write(ico)
