#!/usr/bin/env python3
"""SOLMARA — a travel poster for a place that isn't there.

A program that paints one travel poster (768x1024 PNG) to /output/entry.png
using only the Python 3.13 standard library: no network, no third-party
packages, a hand-rolled PNG encoder (zlib + struct) and a tiny bitmap font
drawn by this program itself.

The place: SOLMARA, a white cliff town above a teal sea where the sun
sets twice — two suns hang low over the water, a lighthouse keeps watch,
and the little houses glow warm at the water's edge.
"""

import math
import os
import random
import struct
import sys
import zlib

# ---------------------------------------------------------------- canvas

W, H = 768, 1024


def lerp(a, b, t):
    return a + (b - a) * t


def lerp_color(c1, c2, t):
    return (int(lerp(c1[0], c2[0], t)),
            int(lerp(c1[1], c2[1], t)),
            int(lerp(c1[2], c2[2], t)))


def gradient(stops, t):
    """stops: list of (position 0..1, (r,g,b)); t in 0..1."""
    if t <= stops[0][0]:
        return stops[0][1]
    for i in range(1, len(stops)):
        p0, c0 = stops[i - 1]
        p1, c1 = stops[i]
        if t <= p1:
            return lerp_color(c0, c1, (t - p0) / (p1 - p0))
    return stops[-1][1]


class Canvas:
    def __init__(self, w, h):
        self.w = w
        self.h = h
        self.px = bytearray(w * h * 3)

    def set(self, x, y, color):
        if 0 <= x < self.w and 0 <= y < self.h:
            i = (y * self.w + x) * 3
            self.px[i] = color[0]
            self.px[i + 1] = color[1]
            self.px[i + 2] = color[2]

    def blend(self, x, y, color, alpha):
        """alpha 0..1: paint color over the pixel."""
        if alpha <= 0:
            return
        if alpha >= 1:
            self.set(x, y, color)
            return
        if 0 <= x < self.w and 0 <= y < self.h:
            i = (y * self.w + x) * 3
            self.px[i] = int(self.px[i] * (1 - alpha) + color[0] * alpha)
            self.px[i + 1] = int(self.px[i + 1] * (1 - alpha) + color[1] * alpha)
            self.px[i + 2] = int(self.px[i + 2] * (1 - alpha) + color[2] * alpha)

    def fill_rect(self, x0, y0, x1, y1, color):
        for y in range(max(0, y0), min(self.h, y1)):
            for x in range(max(0, x0), min(self.w, x1)):
                self.set(x, y, color)

    def vgrad_rect(self, x0, y0, x1, y1, stops):
        for y in range(max(0, y0), min(self.h, y1)):
            t = (y - y0) / max(1, (y1 - y0 - 1))
            c = gradient(stops, t)
            for x in range(max(0, x0), min(self.w, x1)):
                self.set(x, y, c)

    def disc(self, cx, cy, r, color, alpha=1.0):
        r2 = r * r
        for y in range(int(cy - r), int(cy + r) + 1):
            for x in range(int(cx - r), int(cx + r) + 1):
                if (x - cx) ** 2 + (y - cy) ** 2 <= r2:
                    self.blend(x, y, color, alpha)

    def glow(self, cx, cy, r, color, peak=0.55):
        """Soft radial glow: alpha falls off with distance."""
        for y in range(int(cy - r), int(cy + r) + 1):
            for x in range(int(cx - r), int(cx + r) + 1):
                d = math.hypot(x - cx, y - cy) / r
                if d < 1:
                    self.blend(x, y, color, peak * (1 - d) * (1 - d))

    def hline(self, x0, x1, y, color, alpha=1.0):
        for x in range(max(0, x0), min(self.w, x1 + 1)):
            self.blend(x, y, color, alpha)

    def vline(self, x, y0, y1, color, alpha=1.0):
        for y in range(max(0, y0), min(self.h, y1 + 1)):
            self.blend(x, y, color, alpha)

    def line(self, x0, y0, x1, y1, color, alpha=1.0, width=1):
        dx = x1 - x0
        dy = y1 - y0
        steps = max(abs(dx), abs(dy), 1)
        for s in range(steps + 1):
            t = s / steps
            x = int(x0 + dx * t)
            y = int(y0 + dy * t)
            for ox in range(width):
                for oy in range(width):
                    self.blend(x + ox, y + oy, color, alpha)

    def polygon(self, points, color, alpha=1.0):
        """Scanline fill (even-odd). points: list of (x, y)."""
        if not points:
            return
        ys = [p[1] for p in points]
        for y in range(max(0, min(ys)), min(self.h, max(ys) + 1)):
            xs = []
            n = len(points)
            for i in range(n):
                x0, y0 = points[i]
                x1, y1 = points[(i + 1) % n]
                if y0 == y1:
                    continue
                if (y0 <= y < y1) or (y1 <= y < y0):
                    xs.append(x0 + (y - y0) * (x1 - x0) / (y1 - y0))
            xs.sort()
            for i in range(0, len(xs) - 1, 2):
                for x in range(int(math.ceil(xs[i])), int(xs[i + 1]) + 1):
                    self.blend(x, y, color, alpha)


# ---------------------------------------------------------------- font
# A 5x7 pixel font, drawn by hand. "1" = filled pixel.

FONT = {
    'A': ("01110", "10001", "10001", "11111", "10001", "10001", "10001"),
    'B': ("11110", "10001", "10001", "11110", "10001", "10001", "11110"),
    'C': ("01110", "10001", "10000", "10000", "10000", "10001", "01110"),
    'D': ("11110", "10001", "10001", "10001", "10001", "10001", "11110"),
    'E': ("11111", "10000", "10000", "11110", "10000", "10000", "11111"),
    'F': ("11111", "10000", "10000", "11110", "10000", "10000", "10000"),
    'G': ("01110", "10001", "10000", "10111", "10001", "10001", "01111"),
    'H': ("10001", "10001", "10001", "11111", "10001", "10001", "10001"),
    'I': ("01110", "00100", "00100", "00100", "00100", "00100", "01110"),
    'J': ("00111", "00010", "00010", "00010", "00010", "10010", "01100"),
    'K': ("10001", "10010", "10100", "11000", "10100", "10010", "10001"),
    'L': ("10000", "10000", "10000", "10000", "10000", "10000", "11111"),
    'M': ("10001", "11011", "10101", "10101", "10001", "10001", "10001"),
    'N': ("10001", "11001", "10101", "10011", "10001", "10001", "10001"),
    'O': ("01110", "10001", "10001", "10001", "10001", "10001", "01110"),
    'P': ("11110", "10001", "10001", "11110", "10000", "10000", "10000"),
    'Q': ("01110", "10001", "10001", "10001", "10101", "10010", "01101"),
    'R': ("11110", "10001", "10001", "11110", "10100", "10010", "10001"),
    'S': ("01111", "10000", "10000", "01110", "00001", "00001", "11110"),
    'T': ("11111", "00100", "00100", "00100", "00100", "00100", "00100"),
    'U': ("10001", "10001", "10001", "10001", "10001", "10001", "01110"),
    'V': ("10001", "10001", "10001", "10001", "10001", "01010", "00100"),
    'W': ("10001", "10001", "10001", "10101", "10101", "10101", "01010"),
    'X': ("10001", "10001", "01010", "00100", "01010", "10001", "10001"),
    'Y': ("10001", "10001", "01010", "00100", "00100", "00100", "00100"),
    'Z': ("11111", "00001", "00010", "00100", "01000", "10000", "11111"),
}


def text_width(text, scale):
    # 5 px glyph + 1 px gap, last glyph has no trailing gap
    return (len(text) * 6 - 1) * scale


def draw_text(c, text, cx, y, scale, color, outline=None):
    """Draw text centered on cx, top at y. outline: optional dark color."""
    w = text_width(text, scale)
    x = cx - w // 2
    if outline is not None:
        for dx, dy in ((-3, 0), (3, 0), (0, -3), (0, 3),
                       (-3, -3), (3, -3), (-3, 3), (3, 3)):
            _draw_text_raw(c, text, x + dx, y + dy, scale, outline)
    _draw_text_raw(c, text, x, y, scale, color)


def _draw_text_raw(c, text, x0, y0, scale, color):
    x = x0
    for ch in text:
        glyph = FONT.get(ch)
        if glyph:
            for row in range(7):
                for col in range(5):
                    if glyph[row][col] == '1':
                        c.fill_rect(x + col * scale, y0 + row * scale,
                                    x + (col + 1) * scale,
                                    y0 + (row + 1) * scale, color)
        x += 6 * scale


# ---------------------------------------------------------------- PNG

def _chunk(kind, data):
    out = struct.pack(">I", len(data)) + kind + data
    out += struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    return out


def _paeth(a, b, c):
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    if pb <= pc:
        return b
    return c


def write_png(c, path):
    w, h = c.w, c.h
    raw = bytearray()
    prev = bytearray(w * 3)
    for y in range(h):
        row = c.px[y * w * 3:(y + 1) * w * 3]
        best = None
        for ftype in range(5):
            if ftype == 0:
                filtered = bytearray(row)
            elif ftype == 1:
                filtered = bytearray(w * 3)
                for i in range(w * 3):
                    left = row[i - 3] if i >= 3 else 0
                    filtered[i] = (row[i] - left) & 0xFF
            elif ftype == 2:
                filtered = bytearray((row[i] - prev[i]) & 0xFF
                                     for i in range(w * 3))
            elif ftype == 3:
                filtered = bytearray(w * 3)
                for i in range(w * 3):
                    left = row[i - 3] if i >= 3 else 0
                    filtered[i] = (row[i] - ((left + prev[i]) // 2)) & 0xFF
            else:
                filtered = bytearray(w * 3)
                for i in range(w * 3):
                    a = row[i - 3] if i >= 3 else 0
                    b = prev[i]
                    cc = prev[i - 3] if i >= 3 else 0
                    filtered[i] = (row[i] - _paeth(a, b, cc)) & 0xFF
            score = sum(abs(b - 256) if b >= 128 else b for b in filtered)
            if best is None or score < best[0]:
                best = (score, ftype, filtered)
        raw.append(best[1])
        raw.extend(best[2])
        prev = row
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    png = b"\x89PNG\r\n\x1a\n"
    png += _chunk(b"IHDR", ihdr)
    png += _chunk(b"IDAT", zlib.compress(bytes(raw), 9))
    png += _chunk(b"IEND", b"")
    with open(path, "wb") as f:
        f.write(png)
    return len(png)


# ---------------------------------------------------------------- scene

HORIZON = 640
SKY_STOPS = [(0.00, (28, 22, 70)),
             (0.35, (94, 50, 108)),
             (0.65, (196, 94, 96)),
             (1.00, (252, 176, 92))]
SEA_STOPS = [(0.00, (18, 92, 104)),
             (0.50, (12, 64, 84)),
             (1.00, (8, 38, 58))]

CREAM = (250, 240, 215)
INK = (28, 18, 40)
GOLD = (255, 214, 140)


def paint():
    c = Canvas(W, H)
    rng = random.Random(42)

    # --- sky
    c.vgrad_rect(0, 0, W, HORIZON, SKY_STOPS)
    # faint stars high up
    for _ in range(46):
        x = rng.randint(20, W - 20)
        y = rng.randint(16, 260)
        c.blend(x, y, (255, 240, 210), rng.uniform(0.25, 0.7))

    # --- the two suns of Solmara
    c.glow(470, 566, 190, (255, 178, 100), peak=0.5)
    c.glow(268, 474, 120, (255, 196, 130), peak=0.45)
    c.disc(470, 566, 66, (255, 226, 158))
    c.disc(470, 566, 52, (255, 238, 190))
    c.disc(268, 474, 34, (255, 232, 178))
    c.disc(268, 474, 26, (255, 244, 210))

    # --- birds
    for (bx, by, s) in [(560, 210, 16), (600, 250, 12), (180, 300, 14),
                        (640, 330, 11), (120, 180, 10)]:
        c.line(bx - s, by, bx, by - s // 2, INK, alpha=0.75, width=2)
        c.line(bx, by - s // 2, bx + s, by, INK, alpha=0.75, width=2)

    # --- sea
    c.vgrad_rect(0, HORIZON, W, H, SEA_STOPS)
    # sun glitter: two sparkling paths under the suns
    for (sx, half_w) in ((470, 95), (268, 55)):
        for _ in range(210):
            gx = sx + rng.randint(-half_w, half_w)
            gy = HORIZON + 14 + int(abs(rng.gauss(0, 0.55)) * 260)
            if gy > H - 30:
                continue
            length = rng.randint(8, 42)
            depth = 1 - (gy - HORIZON) / 330.0
            alpha = max(0.08, depth * rng.uniform(0.25, 0.75))
            c.hline(gx - length // 2, gx + length // 2, gy,
                    (255, 216, 150), alpha=alpha)
    # gentle wave strokes
    for _ in range(60):
        wx = rng.randint(0, W - 120)
        wy = rng.randint(HORIZON + 30, H - 40)
        wl = rng.randint(24, 110)
        c.hline(wx, wx + wl, wy, (120, 190, 200),
                alpha=rng.uniform(0.08, 0.22))

    # --- cliff (left) with the lighthouse
    cliff = [(0, H), (0, 716), (46, 668), (96, 610), (150, 556),
             (210, 566), (258, 620), (292, 690), (306, H)]
    c.polygon(cliff, (58, 34, 50))
    # warm rim light on the cliff crest
    c.line(96, 610, 150, 556, (214, 130, 96), alpha=0.55, width=3)
    c.line(150, 556, 210, 566, (214, 130, 96), alpha=0.45, width=3)
    # lighthouse tower (tapered, on the cliff top)
    tower = [(138, 556), (146, 402), (176, 402), (184, 556)]
    c.polygon(tower, (240, 235, 224))
    c.polygon([(140, 512), (144, 470), (178, 470), (182, 512)], (52, 40, 62))
    c.polygon([(142, 452), (146, 430), (176, 430), (180, 452)], (52, 40, 62))
    # gallery + lamp room
    c.fill_rect(140, 392, 182, 404, (52, 40, 62))
    c.fill_rect(148, 366, 174, 392, (255, 206, 120))
    c.fill_rect(144, 360, 178, 368, (52, 40, 62))
    c.glow(161, 379, 60, (255, 200, 110), peak=0.5)
    # light beam sweeping right across the dusk sky
    c.polygon([(174, 376), (700, 332), (700, 408), (174, 386)],
              (255, 214, 130), alpha=0.06)

    # --- little white houses at the water's edge (right shore)
    for (hx, hw, hh, roof) in [(430, 44, 34, 20), (482, 52, 40, 24),
                                (544, 40, 30, 18), (592, 56, 44, 26),
                                (656, 42, 32, 20)]:
        base = HORIZON + 4
        c.fill_rect(hx, base - hh, hx + hw, base, (236, 228, 208))
        c.polygon([(hx - 3, base - hh), (hx + hw // 2, base - hh - roof),
                   (hx + hw + 3, base - hh)], (58, 36, 52))
        for wx in (hx + 8, hx + hw - 14):
            c.fill_rect(wx, base - hh + 10, wx + 6, base - hh + 18,
                        (255, 190, 100))

    # --- foreground rocks, bottom right (depth)
    c.polygon([(768, H), (768, 900), (700, 930), (640, 990), (600, H)],
              (24, 16, 34))

    # --- frame
    for inset in (14, 20):
        c.fill_rect(inset, inset, W - inset, inset + 3, CREAM)
        c.fill_rect(inset, H - inset - 3, W - inset, H - inset, CREAM)
        c.fill_rect(inset, inset, inset + 3, H - inset, CREAM)
        c.fill_rect(W - inset - 3, inset, W - inset, H - inset, CREAM)

    # --- the name, set big at the top of the sky
    draw_text(c, "SOLMARA", W // 2, 64, 15, CREAM, outline=INK)

    return c


def main(argv):
    out = argv[1] if len(argv) > 1 else "/output/entry.png"
    directory = os.path.dirname(out)
    if directory:
        os.makedirs(directory, exist_ok=True)
    canvas = paint()
    size = write_png(canvas, out)
    print(f"wrote {out}: {W}x{H}, {size} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
