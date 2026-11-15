#!/usr/bin/env python3
"""Draw the pictures the tour deck uses (no photos, no rights).

    python3 examples/tour/make-media.py

Writes lamp.jpg, river.jpg, ink-vortices.webp and pages.jpg into media/.
Plain procedural art. Swap in your own pictures with the same file names.
"""
import math, random
from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter

W, H = 1600, 900
OUT = Path(__file__).resolve().parent / "media"


def lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def gradient(top, bottom):
    im = Image.new("RGB", (W, H))
    d = ImageDraw.Draw(im)
    for y in range(H):
        d.line([(0, y), (W, y)], fill=lerp(top, bottom, y / (H - 1)))
    return im


def lamp():
    """A warm pool of light on near-black: the lecture theme's own colours."""
    im = Image.new("RGB", (W, H), (18, 16, 12))
    d = ImageDraw.Draw(im, "RGBA")
    cx, cy = int(W * 0.68), int(H * 0.42)
    for r in range(900, 0, -12):
        t = 1 - r / 900
        d.ellipse([cx - r, cy - int(r * 0.7), cx + r, cy + int(r * 0.7)],
                  fill=lerp((24, 20, 14), (216, 169, 92), t ** 2.2) + (255,))
    return im.filter(ImageFilter.GaussianBlur(18))


def pages():
    """Stacked sheets of ruled lines: a script, seen from above."""
    rnd = random.Random(3)
    im = Image.new("RGB", (W, H), (30, 27, 22))
    d = ImageDraw.Draw(im, "RGBA")
    for k in range(7):
        x0, y0 = 160 + k * 150, 90 + (k % 3) * 40
        w, h = 520, 700
        d.rectangle([x0 + 14, y0 + 14, x0 + w + 14, y0 + h + 14], fill=(0, 0, 0, 90))
        d.rectangle([x0, y0, x0 + w, y0 + h], fill=(242, 236, 223))
        y = y0 + 60
        while y < y0 + h - 40:
            n = rnd.randint(18, 34)
            d.line([(x0 + 40, y), (x0 + 40 + n * 12, y)], fill=(120, 110, 95), width=5)
            if rnd.random() < 0.18:
                d.rectangle([x0 + 40, y - 26, x0 + 300, y + 30], fill=(216, 169, 92, 200))
            y += 38
    return im.filter(ImageFilter.GaussianBlur(1.2))


def river():
    im = gradient((190, 225, 245), (20, 70, 120))
    d = ImageDraw.Draw(im)
    for band in range(26):
        y0 = 120 + band * 30
        pts = [(x, y0 + 22 * math.sin(x / 140 + band * 0.7)) for x in range(0, W + 20, 20)]
        shade = lerp((230, 245, 255), (10, 50, 100), band / 25)
        d.line(pts, fill=shade, width=14)
    return im.filter(ImageFilter.GaussianBlur(1.5))


def ink():
    rnd = random.Random(7)
    im = Image.new("RGB", (W, H), (245, 240, 232))
    d = ImageDraw.Draw(im, "RGBA")
    for arm in range(5):
        base = arm * 2 * math.pi / 5
        for i in range(360):
            t = i / 360
            a = base + t * 5.5
            r = 40 + t * 520
            x, y = W / 2 + r * math.cos(a), H / 2 + r * math.sin(a) * 0.62
            s = 6 + 30 * (1 - t) + rnd.random() * 4
            col = lerp((20, 20, 60), (230, 70, 110), t) + (90,)
            d.ellipse([x - s, y - s, x + s, y + s], fill=col)
    return im.filter(ImageFilter.GaussianBlur(5))


OUT.mkdir(exist_ok=True)
lamp().save(OUT / "lamp.jpg", quality=88)
river().save(OUT / "river.jpg", quality=88)
ink().save(OUT / "ink-vortices.webp", quality=85)
pages().save(OUT / "pages.jpg", quality=88)
print("wrote", *sorted(p.name for p in OUT.iterdir() if p.suffix != ".yaml"))
