#!/usr/bin/env python3
"""Build a talkfile's handout PDF: build.py, then headless Chromium prints the
document view.  The handout carries small JPEG stills, never videos or
originals, so the PDF stays in the single-digit MB.

    python3 tools/handout-pdf.py <talkfile> <out.pdf> [--work DIR] [--figures full|n%] [--no-pools] [--no-placeholders]

The work dir (the full build) defaults to ~/animatic-handout-build/<slug>.
It must be under $HOME and not hidden: a snap-packaged Chromium cannot read /tmp.
"""
import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("talkfile")
    ap.add_argument("pdf")
    ap.add_argument("--work")
    ap.add_argument("--no-pools", action="store_true",
                    help="leave pool-card art out of the handout")
    ap.add_argument("--no-placeholders", action="store_true",
                    help="leave the grey box for a card with no picture yet out")
    ap.add_argument("--figures", metavar="WIDTH",
                    help="figure width: capped (default), full, or n%% of the text column")
    a = ap.parse_args()
    talk = Path(a.talkfile).resolve()
    work = Path(a.work) if a.work else Path.home() / "animatic-handout-build" / talk.parent.name
    pdf = Path(a.pdf).resolve()
    chrome = shutil.which("chromium") or shutil.which("chromium-browser") or shutil.which("google-chrome")
    if not chrome:
        print("error: no chromium / google-chrome on PATH", file=sys.stderr)
        return 2
    r = subprocess.run([sys.executable, str(ROOT / "build.py"), str(talk), "--out", str(work)]
                       + (["--handout-figures", a.figures] if a.figures else [])
                       + (["--no-handout-pools"] if a.no_pools else [])
                       + (["--no-handout-placeholders"] if a.no_placeholders else []),
                       env={k: v for k, v in os.environ.items() if k != "ANIMATIC_WAYPOINT_TOKEN"})
    if r.returncode:
        return r.returncode
    pdf.parent.mkdir(parents=True, exist_ok=True)
    tmp = work / "handout.pdf"      # under $HOME for snap Chromium, then moved
    subprocess.run([chrome, "--headless=new", "--no-sandbox", "--disable-gpu",
                    "--no-pdf-header-footer", "--virtual-time-budget=20000",
                    f"--print-to-pdf={tmp}", (work / "document" / "index.html").as_uri()],
                   check=True, stderr=subprocess.DEVNULL)
    shutil.move(str(tmp), pdf)
    print(f"handout   : {pdf} ({pdf.stat().st_size / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
