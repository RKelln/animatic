#!/usr/bin/env python3
"""Draw the four placeholder pictures this specimen uses (no photos, no rights).

    python3 examples/roles-demo/make-media.py

Writes roundabout.jpg, river.jpg, seaside.jpg and ink-vortices.webp into media/.
They are plain procedural art: bright rings, blue bands, a horizon, a swirl.
Swap in your own pictures with the same file names, or point a card at them.
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


def roundabout():
    im = gradient((250, 214, 90), (240, 90, 60))
    d = ImageDraw.Draw(im)
    cx, cy = W // 2, H // 2
    colours = [(20, 20, 30), (255, 255, 255), (30, 120, 200), (255, 255, 255)]
    for i, r in enumerate(range(520, 40, -48)):
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=colours[i % 4])
    for k in range(12):  # spokes
        a = k * math.pi / 6
        d.line([(cx, cy), (cx + 560 * math.cos(a), cy + 560 * math.sin(a))], fill=(255, 255, 255), width=6)
    return im


def river():
    im = gradient((190, 225, 245), (20, 70, 120))
    d = ImageDraw.Draw(im)
    for band in range(26):
        y0 = 120 + band * 30
        pts = [(x, y0 + 22 * math.sin(x / 140 + band * 0.7)) for x in range(0, W + 20, 20)]
        shade = lerp((230, 245, 255), (10, 50, 100), band / 25)
        d.line(pts, fill=shade, width=14)
    return im.filter(ImageFilter.GaussianBlur(1.5))


def seaside():
    im = gradient((255, 190, 140), (120, 170, 210))
    d = ImageDraw.Draw(im)
    d.rectangle([0, 470, W, H], fill=(40, 110, 160))
    for i in range(14):
        y = 490 + i * 28
        d.line([(0, y), (W, y)], fill=lerp((90, 170, 210), (20, 70, 120), i / 13), width=3)
    d.ellipse([1100, 330, 1260, 490], fill=(255, 240, 200))
    d.polygon([(0, 900), (0, 700), (400, 760), (900, 900)], fill=(214, 190, 140))
    return im.filter(ImageFilter.GaussianBlur(1))


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
roundabout().save(OUT / "roundabout.jpg", quality=88)
river().save(OUT / "river.jpg", quality=88)
seaside().save(OUT / "seaside.jpg", quality=88)
ink().save(OUT / "ink-vortices.webp", quality=85)
print("wrote", *sorted(p.name for p in OUT.iterdir()))
