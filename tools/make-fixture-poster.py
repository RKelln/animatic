"""Make the live-capture fixture's poster PNG. Deterministic, stdlib only.

Run from the repo root: python3 tools/make-fixture-poster.py
"""
import struct
import zlib
from pathlib import Path

W = H = 8
rows = b"".join(b"\x00" + bytes([180, 170, 150] * W) for _ in range(H))


def chunk(tag: bytes, data: bytes) -> bytes:
    crc = zlib.crc32(tag + data) % 2 ** 32
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)


png = (
    b"\x89PNG\r\n\x1a\n"
    + chunk(b"IHDR", struct.pack(">IIBBBBB", W, H, 8, 2, 0, 0, 0))
    + chunk(b"IDAT", zlib.compress(rows, 9))
    + chunk(b"IEND", b"")
)

out = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "decks" / "live-capture" / "media" / "live-window-poster.png"
out.parent.mkdir(parents=True, exist_ok=True)
out.write_bytes(png)
print("wrote", out, len(png), "bytes")
