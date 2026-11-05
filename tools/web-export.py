#!/usr/bin/env python3
"""Export a talkfile's document view as a self-contained web page: one folder
holding index.html and the web-sized images it uses, ready to drop on a static
site (Hugo `static/`, GitHub Pages, any file server).

    python3 tools/web-export.py <talkfile> <out-dir> [--work DIR]

The folder is `index.html` plus `media/*.jpg`; every link in the page is
relative, so it works under any URL prefix.  Nothing else from the build ships:
no present or presenter view, no cues.json, no originals.  Refuses to ship a
page that points outside its own folder or names a local path.
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from html import escape
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import talkparse  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
MEDIA_PREFIX = "../_media/doc/"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("talkfile")
    ap.add_argument("out")
    ap.add_argument("--work", help="build directory (default: a temporary one)")
    ap.add_argument("--allow", action="append", default=[], metavar="TEXT",
                    help="a local-path string the author has cleared to appear in the page "
                         "(also frontmatter `web-allow:`, a list)")
    a = ap.parse_args()
    talk = Path(a.talkfile).resolve()
    out = Path(a.out).resolve()
    work = Path(a.work) if a.work else Path(tempfile.mkdtemp(prefix="animatic-web-"))
    r = subprocess.run([sys.executable, str(ROOT / "build.py"), str(talk), "--out", str(work),
                        "--no-handout-placeholders"], stdout=subprocess.DEVNULL,
                       env={k: v for k, v in os.environ.items() if k != "ANIMATIC_WAYPOINT_TOKEN"})
    if r.returncode:
        return r.returncode
    html = (work / "document" / "index.html").read_text(encoding="utf-8")

    used = sorted(set(re.findall(re.escape(MEDIA_PREFIX) + r"([^\"')\s]+)", html)))
    html = html.replace(MEDIA_PREFIX, "media/")

    meta = talkparse.build_talk(talk).meta
    title = escape(str(meta.get("title", "")), quote=True)
    desc = escape(str(meta.get("logline", "")), quote=True)
    head = ""
    if desc:
        head += f'<meta name="description" content="{desc}">\n'
    head += f'<meta property="og:title" content="{title}">\n'
    if desc:
        head += f'<meta property="og:description" content="{desc}">\n'
    html = re.sub(r"(</title>\n?)", r"\1" + head.replace("\\", "\\\\"), html, count=1)

    allowed = list(a.allow) + [str(x) for x in (meta.get("web-allow") or [])]
    problems = []
    for ref in re.findall(r'(?:src|href)="([^"#][^"]*)"', html):
        if ref.startswith(("http://", "https://", "mailto:", "data:", "media/")):
            continue
        problems.append(f"link leaves the folder: {ref}")
    for leak in re.findall(r"/home/\w+[^\"<\s]*|~/(?:Documents|\.)[^\"<\s]*", html):
        if not any(x in leak for x in allowed):
            problems.append(f"local path in page: {leak}  (author-cleared? add `web-allow:` to the frontmatter)")
    if problems:
        print("refusing to export:\n  " + "\n  ".join(problems[:10]), file=sys.stderr)
        return 1

    if out.exists():
        shutil.rmtree(out)
    (out / "media").mkdir(parents=True)
    (out / "index.html").write_text(html, encoding="utf-8")
    for name in used:
        shutil.copy2(work / "_media" / "doc" / name, out / "media" / name)
    size = sum(f.stat().st_size for f in out.rglob("*") if f.is_file())
    print(f"web       : {out} ({len(used)} images, {size / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
