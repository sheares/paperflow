#!/usr/bin/env python3
"""Generate a 32x32 mouse-cursor PNG (white fill, dark outline) using
only the standard library. Anti-aliased via 3x3 supersampling.

Shape follows the classic OS pointer: sharp tip at the top-left with a
near-vertical left spine, diagonal right shoulder, and a short tail
hook off the bottom-right. Sized to look natural on 1920x1080 video."""

import struct
import zlib
from pathlib import Path

W = H = 42
OUT = Path(__file__).resolve().parent.parent / 'docs' / '_cursor.png'

# Classic pointer polygon in a 42x42 canvas. Kept realistically small
# so the cursor reads as a proper OS pointer, not an oversized graphic;
# 42 px is enough to be legible on a full 1920x1080 frame without
# overwhelming the paperflow UI beneath it.
POLY = [
    (3, 3),       # tip
    (23, 23),     # right shoulder (end of long diagonal)
    (17, 24),     # inner-top of the tail notch
    (22, 35),     # tail tip (bottom-right)
    (17, 38),     # tail bottom-left
    (12, 27),     # inner-bottom of the tail notch
    (3, 29),      # bottom of the left spine
]


def point_in_polygon(x, y, poly):
    inside = False
    n = len(poly)
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


def dist_to_edge(x, y, poly):
    best = 1e9
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        dx, dy = x2 - x1, y2 - y1
        length2 = dx * dx + dy * dy
        if length2 == 0:
            d = ((x - x1) ** 2 + (y - y1) ** 2) ** 0.5
        else:
            t = max(0.0, min(1.0, ((x - x1) * dx + (y - y1) * dy) / length2))
            px, py = x1 + t * dx, y1 + t * dy
            d = ((x - px) ** 2 + (y - py) ** 2) ** 0.5
        if d < best:
            best = d
    return best


def sample(fx, fy):
    OUTLINE_W = 1.2
    inside = point_in_polygon(fx, fy, POLY)
    ed = dist_to_edge(fx, fy, POLY)
    if inside:
        if ed < OUTLINE_W:
            return (18, 18, 24, 255)   # dark outline (inside edge)
        return (250, 250, 255, 255)    # white body
    if ed < 1.0:
        return (18, 18, 24, 255)       # dark outline (outside edge)
    return (0, 0, 0, 0)


def render_pixel(x, y):
    """Anti-aliased render via 3x3 supersampling."""
    N = 3
    r_sum = g_sum = b_sum = a_sum = 0
    for sy in range(N):
        for sx in range(N):
            fx = x + (sx + 0.5) / N
            fy = y + (sy + 0.5) / N
            r, g, b, a = sample(fx, fy)
            r_sum += r * a
            g_sum += g * a
            b_sum += b * a
            a_sum += a
    total = N * N
    a = a_sum // total
    if a == 0:
        return (0, 0, 0, 0)
    r = min(255, r_sum // a_sum) if a_sum else 0
    g = min(255, g_sum // a_sum) if a_sum else 0
    b = min(255, b_sum // a_sum) if a_sum else 0
    return (r, g, b, a)


def make_png(path):
    raw = bytearray()
    for y in range(H):
        raw.append(0)
        for x in range(W):
            r, g, b, a = render_pixel(x, y)
            raw.extend((r, g, b, a))

    def chunk(kind, data):
        return (struct.pack('>I', len(data))
                + kind + data
                + struct.pack('>I', zlib.crc32(kind + data)))

    ihdr = struct.pack('>IIBBBBB', W, H, 8, 6, 0, 0, 0)
    idat = zlib.compress(bytes(raw), 9)
    with open(path, 'wb') as f:
        f.write(b'\x89PNG\r\n\x1a\n')
        f.write(chunk(b'IHDR', ihdr))
        f.write(chunk(b'IDAT', idat))
        f.write(chunk(b'IEND', b''))


if __name__ == '__main__':
    make_png(OUT)
    print(f'wrote {OUT} ({OUT.stat().st_size} bytes)')
