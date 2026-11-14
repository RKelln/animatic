#!/usr/bin/env python3
"""Make web copies of videos (see webvideo.py for the recipe and the cache).

    python3 tools/web-video.py clip.mp4 out.mp4            # one file, muted
    python3 tools/web-video.py clip.mp4 out.mp4 --sound    # keep the audio
    python3 tools/web-video.py --talk talk.md              # every video a reading copy would play: sizes, no output

A talk opts in with frontmatter `web-video: true`; then tools/web-export.py swaps each
video figure's still for a click-to-play, looping web copy (the still is its poster).
A card with `web-video: false` keeps its still (rights, or size). The handout PDF
always prints stills.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import webvideo  # noqa: E402


def talk_videos(talk: Path, encode: bool = True) -> list[dict]:
    """The talk's playable videos (from a scratch build's manifest), each with its
    source size and, when `encode`, its cached web copy."""
    work = Path(tempfile.mkdtemp(prefix="animatic-webvideo-"))
    try:
        r = subprocess.run([sys.executable, str(ROOT / "build.py"), str(talk), "--out", str(work)],
                           stdout=subprocess.DEVNULL)
        if r.returncode:
            sys.exit(r.returncode)
        manifest = json.loads((work / "media-manifest.json").read_text())
        out = []
        for e in manifest["referenced"]:
            m = e["media"]
            f = m.get("file") or ""
            if m.get("live") or Path(f).suffix.lower() not in webvideo.VIDEO_EXTS:
                continue
            src = Path(f) if Path(f).is_absolute() else work / f
            v = {"slug": e["slug"], "sound": bool(m.get("sound")), "web": m.get("web_video", True),
                 "size": src.stat().st_size if src.is_file() else 0, "copy": None}
            if encode and v["web"] and src.is_file():
                v["copy"] = webvideo.web_copy(src, v["sound"])
            out.append(v)
        return out
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("src", nargs="?", type=Path)
    ap.add_argument("dst", nargs="?", type=Path)
    ap.add_argument("--sound", action="store_true", help="keep the audio track")
    ap.add_argument("--talk", type=Path, help="report a talk's web videos (encodes into the cache)")
    a = ap.parse_args()
    if a.talk:
        total_in = total_out = 0
        for v in talk_videos(a.talk):
            if not v["web"]:
                print(f"skip      {v['slug']:28} (card web-video: false)")
                continue
            n_out = v["copy"].stat().st_size if v["copy"] else 0
            total_in += v["size"]
            total_out += n_out
            print(f"{'ok' if v['copy'] else 'FAILED':9} {v['slug']:28} {v['size'] / 1e6:6.1f} MB -> "
                  f"{n_out / 1e6:5.1f} MB{'  sound' if v['sound'] else ''}")
        print(f"\ntotal {total_in / 1e6:.0f} MB -> {total_out / 1e6:.0f} MB")
        return 0
    if not (a.src and a.dst):
        ap.error("give SRC and DST, or --talk")
    got = webvideo.web_copy(a.src, a.sound)
    if not got:
        print("encode failed", file=sys.stderr)
        return 1
    shutil.copy2(got, a.dst)
    print(f"{a.dst} ({a.dst.stat().st_size / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
