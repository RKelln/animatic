#!/usr/bin/env python3
"""tools/check-fit.py: does the present view's text fit-to-height work?

Builds a small deck (one slide that fits, one that overflows a short window by a
little, one that overflows by a lot), loads it in headless Chromium at a short
window, and reads the data-fit attribute the pager sets:
  - the short slide carries none (untouched),
  - the slightly-too-tall slide is shrunk (data-fit between 0.75 and 1),
  - the far-too-tall slide stops at the floor (data-fit="floor").
Needs chromium on PATH. Not part of tests/run.py (it needs a browser).
Usage: python3 tools/check-fit.py
"""
import re, shutil, subprocess, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
chromium = shutil.which("chromium") or shutil.which("chromium-browser")
if not chromium:
    sys.exit("chromium not found")
names = ["Jane Doe, Manager, Innovation", "Sam Roe, Services Specialist"]
def items(n): return "\n".join(f"- {names[i % 2]} {i}" for i in range(n))
talk = f"""---
type: Talk
format-version: 1.0
content-version: 1
slug: fit
title: "fit"
theme: workshop
---
<!-- shot -->
### Short
- one
- two

<!-- shot -->
### Slightly tall
{items(13)}

<!-- shot -->
### Far too tall
{items(30)}
"""
work = Path(tempfile.mkdtemp(prefix="animatic-fit-", dir=Path.home()))   # snap chromium reads $HOME only
try:
    (work / "talk.md").write_text(talk)
    subprocess.run([sys.executable, str(ROOT / "build.py"), str(work / "talk.md"), "--out", str(work / "out")],
                   check=True, capture_output=True)
    dom = subprocess.run([chromium, "--headless=new", "--no-sandbox", "--window-size=1280,640",
                          "--virtual-time-budget=3000", "--dump-dom",
                          (work / "out/present/index.html").as_uri()],
                         check=True, capture_output=True, text=True).stdout
    fits = {m.group(1): m.group(2) for m in re.finditer(r'<section id="(fit-\d+)"[^>]*?data-fit="([^"]*)"', dom)}
    print("data-fit:", fits)
    errs = []
    if "fit-001" in fits: errs.append("short slide was touched")
    v = fits.get("fit-002")
    if v is None or v == "floor" or not 0.75 <= float(v) < 1: errs.append(f"slightly tall slide: {v!r}")
    if fits.get("fit-003") != "floor": errs.append(f"far too tall slide: {fits.get('fit-003')!r}")
    print("FAIL: " + "; ".join(errs) if errs else "ok")
    sys.exit(1 if errs else 0)
finally:
    shutil.rmtree(work, ignore_errors=True)
