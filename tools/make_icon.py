"""Generate ui/icon.ico (calendar symbol) with the standard library only.

Run:  python tools/make_icon.py
"""
import struct
import sys
import zlib
from pathlib import Path

SIZES = (16, 24, 32, 48, 64, 128, 256)
SS = 4  # supersampling per axis

BORDER, BODY = (170, 184, 222), (255, 255, 255)
HEADER, RING = (59, 108, 246), (30, 46, 110)
CELL, TODAY = (186, 197, 227), (217, 69, 61)


def rrect(x, y, x0, y0, x1, y1, r):
    """Point inside a rounded rectangle."""
    if not (x0 <= x <= x1 and y0 <= y <= y1):
        return False
    cx = min(max(x, x0 + r), x1 - r)
    cy = min(max(y, y0 + r), y1 - r)
    return (x - cx) ** 2 + (y - cy) ** 2 <= r * r


def shade(u, v):
    """Colour at unit coordinates, or None when transparent (painter's algorithm)."""
    if not rrect(u, v, 0.05, 0.12, 0.95, 0.95, 0.14):
        # binder rings stick out above the body
        for cx in (0.30, 0.70):
            if rrect(u, v, cx - 0.045, 0.04, cx + 0.045, 0.24, 0.045):
                return RING
        return None
    for cx in (0.30, 0.70):
        if rrect(u, v, cx - 0.045, 0.04, cx + 0.045, 0.24, 0.045):
            return RING
    if not rrect(u, v, 0.075, 0.145, 0.925, 0.925, 0.115):
        return BORDER
    if v < 0.36:
        return HEADER
    # day grid: 3 columns x 2 rows, one highlighted day
    for row in range(2):
        for col in range(3):
            x0 = 0.19 + col * 0.215
            y0 = 0.47 + row * 0.23
            if rrect(u, v, x0, y0, x0 + 0.17, y0 + 0.17, 0.035):
                return TODAY if (row, col) == (1, 1) else CELL
    return BODY


def render(size):
    rows = []
    for py in range(size):
        row = bytearray()
        for px in range(size):
            r = g = b = a = 0
            for sy in range(SS):
                for sx in range(SS):
                    c = shade((px + (sx + 0.5) / SS) / size, (py + (sy + 0.5) / SS) / size)
                    if c:
                        r += c[0]; g += c[1]; b += c[2]; a += 255
            n = SS * SS
            cover = a // 255
            if cover:
                row += bytes((r // cover, g // cover, b // cover, a // n))
            else:
                row += b'\x00\x00\x00\x00'
        rows.append(bytes(row))
    return rows


def png(size, rows):
    def chunk(tag, data):
        body = tag + data
        return struct.pack('>I', len(data)) + body + struct.pack('>I', zlib.crc32(body) & 0xFFFFFFFF)
    raw = b''.join(b'\x00' + r for r in rows)
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', size, size, 8, 6, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(raw, 9)) + chunk(b'IEND', b''))


def main():
    out = Path(__file__).resolve().parent.parent / 'ui' / 'icon.ico'
    images = [(s, png(s, render(s))) for s in SIZES]
    header = struct.pack('<HHH', 0, 1, len(images))
    offset = 6 + 16 * len(images)
    entries, blobs = b'', b''
    for s, data in images:
        entries += struct.pack('<BBBBHHII', s % 256, s % 256, 0, 0, 1, 32, len(data), offset)
        blobs += data
        offset += len(data)
    out.write_bytes(header + entries + blobs)
    if len(sys.argv) > 1:                       # optional: also save the largest size as PNG preview
        Path(sys.argv[1]).write_bytes(images[-1][1])
    print('Zapisano', out, out.stat().st_size, 'B')


if __name__ == '__main__':
    main()
