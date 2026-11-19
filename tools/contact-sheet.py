#!/usr/bin/env python3
"""tools/contact-sheet.py: every slide of a deck as one thumbnail sheet (PNG).

For styling review: build the deck, screenshot each slide of the present view
in headless Chromium at a real projector size, and tile the shots into one
image, each labelled with its number, title and shot flags. A slide the fitter
gave up on (data-fit="floor": its text is clipped) gets a red frame.

    python3 tools/contact-sheet.py examples/specimens/hero/talk.md sheet.png
    python3 tools/contact-sheet.py TALK sheet.png --theme workshop
    python3 tools/contact-sheet.py TALK sheet.png --size 1280x800 --only 5-9,12
    python3 tools/contact-sheet.py TALK sheet.png --frames DIR   # keep full-size PNGs too

The specimen decks under examples/specimens/ exist for this: one screen per
combination of features. Needs chromium on PATH. Read-only on the deck: the
build goes to a temporary directory, removed afterwards.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent


def chromium_path() -> str | None:
    return shutil.which("chromium") or shutil.which("chromium-browser") or shutil.which("google-chrome")


def parse_only(spec: str | None, count: int) -> list[int]:
    """'5-9,12' -> [5, 6, 7, 8, 9, 12] (1-based, clipped to the deck)."""
    if not spec:
        return list(range(1, count + 1))
    out: list[int] = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        a, _, b = part.partition("-")
        lo, hi = int(a), int(b or a)
        out.extend(n for n in range(lo, hi + 1) if 1 <= n <= count and n not in out)
    return out


def label_for(cue: dict) -> tuple[str, str]:
    """(title line, flags line) for a thumbnail."""
    title = (cue.get("title") or "").strip()
    if not title:
        for b in cue.get("screen_text") or []:
            t = (b.get("text") or " ".join(b.get("items") or [])).strip()
            if t:
                title = f"({b.get('kind')}) {t}"
                break
    if not title:
        title = f"({cue.get('kind')})"
    title = re.sub(r"\s+", " ", title)
    shot = (cue.get("shots") or [{}])[0]
    bits = [shot["slug"]] if shot.get("slug") else []
    bits += [k if v is True else f"{k}={v}" for k, v in (shot.get("flags") or {}).items()]
    if shot.get("role") and f"role={shot['role']}" not in bits:
        bits.append(f"role={shot['role']}")
    return title, " ".join(bits)


def shoot(chromium: str, page: Path, n: int, w: int, h: int, dest: Path) -> bool:
    # one browser per slide: the hash opens the deck on that slide, and the
    # virtual-time budget lets the fade, the fonts and the fitter settle
    url = page.as_uri() + f"#{n}"
    proc = subprocess.run(
        [chromium, "--headless=new", "--no-sandbox", "--disable-gpu", "--hide-scrollbars",
         "--mute-audio", f"--window-size={w},{h}", "--virtual-time-budget=4000",
         f"--screenshot={dest}", url],
        capture_output=True, text=True, timeout=120)
    return proc.returncode == 0 and dest.exists()


def fit_states(chromium: str, page: Path, w: int, h: int) -> dict[str, str]:
    """{slide id: data-fit} as the pager left it at this window size."""
    dom = subprocess.run(
        [chromium, "--headless=new", "--no-sandbox", "--disable-gpu", f"--window-size={w},{h}",
         "--virtual-time-budget=4000", "--dump-dom", page.as_uri()],
        capture_output=True, text=True, timeout=120).stdout
    out = {}
    for m in re.finditer(r"<section\b[^>]*>", dom):
        tag = m.group(0)
        sid = re.search(r'\bid="([^"]+)"', tag)
        fit = re.search(r'\bdata-fit="([^"]*)"', tag)
        if sid and fit:
            out[sid.group(1)] = fit.group(1)
    return out


def font(size: int):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:   # Pillow < 10.1
        return ImageFont.load_default()


def fit_text(draw: ImageDraw.ImageDraw, text: str, f, width: int) -> str:
    if draw.textlength(text, font=f) <= width:
        return text
    while text and draw.textlength(text + "…", font=f) > width:
        text = text[:-1]
    return text + "…"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("talkfile")
    ap.add_argument("out", help="the sheet, a .png")
    ap.add_argument("--theme", help="build with this theme instead of the deck's")
    ap.add_argument("--size", default="1920x1080", help="browser window, WxH (default 1920x1080)")
    ap.add_argument("--thumb", type=int, default=480, help="thumbnail width in px (default 480)")
    ap.add_argument("--cols", type=int, default=5)
    ap.add_argument("--only", help="slides to include, 1-based: 5-9,12")
    ap.add_argument("--frames", help="also keep each full-size screenshot in this directory")
    ap.add_argument("--jobs", type=int, default=6, help="browsers at once (default 6)")
    a = ap.parse_args()

    chromium = chromium_path()
    if not chromium:
        print("contact-sheet: chromium not found on PATH", file=sys.stderr)
        return 77
    w, h = (int(v) for v in a.size.lower().split("x"))
    talk = Path(a.talkfile).resolve()
    if talk.is_dir():
        talk = talk / "talk.md"

    # snap chromium can only read under $HOME, so the build goes there
    work = Path(tempfile.mkdtemp(prefix="animatic-sheet-", dir=Path.home()))
    try:
        cmd = [sys.executable, str(ROOT / "build.py"), str(talk), "--out", str(work / "out"), "-q"]
        if a.theme:
            cmd += ["--theme", a.theme]
        b = subprocess.run(cmd, capture_output=True, text=True)
        if b.returncode != 0:
            print(b.stdout + b.stderr, file=sys.stderr)
            return 1
        page = work / "out" / "present" / "index.html"
        cues = json.loads((work / "out" / "cues.json").read_text())["cues"]
        picks = parse_only(a.only, len(cues))
        # the browser writes under $HOME too (snap); --frames gets a copy
        frames = work / "frames"
        frames.mkdir()

        with cf.ThreadPoolExecutor(max_workers=max(1, a.jobs)) as pool:
            futs = {n: pool.submit(shoot, chromium, page, n, w, h, frames / f"{n:03d}.png") for n in picks}
            fits = fit_states(chromium, page, w, h)
            shot_ok = {n: f.result() for n, f in futs.items()}

        tw = a.thumb
        th = round(tw * h / w)
        pad, cap = 14, 40
        cols = max(1, min(a.cols, len(picks)))
        rows = -(-len(picks) // cols)
        head = 44
        sheet = Image.new("RGB", (pad + cols * (tw + pad), head + rows * (th + cap + pad) + pad), (238, 236, 232))
        d = ImageDraw.Draw(sheet)
        f_title, f_small = font(14), font(11)
        d.text((pad, 12), fit_text(d, f"{talk.parent.name}/{talk.name}  ·  theme {a.theme or 'deck'}  ·  {w}x{h}"
                                   f"  ·  {len(picks)} slides  ·  red frame = text clipped at the fit floor",
                                   font(16), sheet.width - 2 * pad), fill=(30, 30, 30), font=font(16))
        floors = 0
        for k, n in enumerate(picks):
            cue = cues[n - 1]
            x = pad + (k % cols) * (tw + pad)
            y = head + (k // cols) * (th + cap + pad)
            if shot_ok[n]:
                im = Image.open(frames / f"{n:03d}.png").convert("RGB").resize((tw, th), Image.LANCZOS)
                sheet.paste(im, (x, y))
            else:
                d.rectangle([x, y, x + tw, y + th], fill=(90, 0, 0))
                d.text((x + 8, y + 8), "screenshot failed", fill=(255, 255, 255), font=f_title)
            fit = fits.get(cue["id"])
            if fit == "floor":
                floors += 1
                d.rectangle([x - 3, y - 3, x + tw + 2, y + th + 2], outline=(210, 20, 20), width=4)
            title, flags = label_for(cue)
            tag = f"{n}" + (f"  fit {fit}" if fit else "")
            d.text((x, y + th + 4), fit_text(d, f"{tag} · {title}", f_title, tw), fill=(20, 20, 20), font=f_title)
            d.text((x, y + th + 22), fit_text(d, flags, f_small, tw), fill=(110, 110, 110), font=f_small)
        if a.frames:
            keep = Path(a.frames)
            keep.mkdir(parents=True, exist_ok=True)
            for p in frames.glob("*.png"):
                shutil.copy2(p, keep / p.name)
        out = Path(a.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        sheet.save(out, optimize=True)
        print(f"contact-sheet: {len(picks)} slides -> {out}" + (f"  ({floors} clipped at the floor)" if floors else ""))
        return 0
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
