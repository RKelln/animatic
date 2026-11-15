#!/usr/bin/env python3
"""Audit one talkfile for its reading copy (web page and handout PDF).

    python3 tools/reading-audit.py <talkfile> [--work DIR]

Builds the deck, then prints one compact report: the checker's findings, how the
Sources list will print, screens that print as a bare heading, spoken text that
refers to the room or the screen, and anything in the page that should not be
public.  It reads only; it never edits the talk.  Built so an agent can fix a
talk from this report plus the few screens it names, without reading all of it.
"""
import argparse
import html as html_mod
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import talkparse  # noqa: E402

# spoken text that points at the room, the screen or the machines: fine aloud, odd on a page
ROOM = re.compile(
    r"raise your hand|show of hands|hands up|put your hand|turn to (a |your )?neighbo|find a partner|"
    r"stand up|on the screen|on the wall|this slide|next slide|up here|over here|scan (the|this) (code|qr)|"
    r"qr code|in front of you|on your (screen|machine|macbook|laptop)|take a moment|look at (the|this)|"
    r"press (the )?(command|enter|return|next)|go ahead and|let's (try|open|look)", re.I)
LEAK = re.compile(r"/home/\w+|~/(?:Documents|\.)|\bread 20\d\d-\d\d-\d\d|verify (this|before)|"
                  r"\bTODO\b|\bTBD\b|\[\^|<!--|\bnot re-?read\b|pasted by|\(Stage|Stage:", re.I)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("talkfile")
    ap.add_argument("--work")
    a = ap.parse_args()
    talk = Path(a.talkfile).resolve()
    work = Path(a.work) if a.work else Path(tempfile.mkdtemp(prefix="animatic-audit-"))
    subprocess.run([sys.executable, str(ROOT / "build.py"), str(talk), "--out", str(work)],
                   stdout=subprocess.DEVNULL, check=True)
    cues = json.loads((work / "cues.json").read_text())
    meta = talkparse.build_talk(talk).meta
    page = (work / "document" / "index.html").read_text(encoding="utf-8")
    vis = [c for c in cues["cues"] if not c.get("live_only")]
    print(f"# {meta.get('title', talk.parent.name)}: {len(cues['cues'])} screens, "
          f"{len(cues['cues']) - len(vis)} live-only or exercise, {len(vis)} in the reading copy\n")

    chk = subprocess.run([sys.executable, str(ROOT / "check.py"), str(talk)], capture_output=True, text=True).stdout
    finds = [l for l in chk.splitlines() if l.startswith(("fatal", "warning"))]
    print("## Checker\n" + ("\n".join(finds) if finds else "clean") + "\n")

    cited = cues.get("deck", {}).get("sources") or []
    cites = meta.get("cites") if isinstance(meta.get("cites"), dict) else None
    print("## Sources")
    if not cited:
        print("none cited")
    elif cites is None:
        print(f"{len(cited)} cited, but the talk has no `cites:` map, so NO Sources list prints. "
              f"Needs `cites:` (public form of each `sources:` entry).")
    else:
        bare = [c["id"] for c in cited if not str(cites.get(c["id"], "")).strip()]
        print(f"{len(cited)} cited, {len(cited) - len(bare)} print" + (f"; missing from cites: {', '.join(bare)}" if bare else ""))
    print()

    print("## Screens that print as a bare heading or nothing (ordinal, title, shot line)")
    n = 0
    pics = 0
    for c in vis:
        words = len((c.get("script") or "").split())
        text = [t for t in (c.get("screen_text") or []) if t.get("kind") != "heading" and ((t.get("text") or "").strip() or t.get("items"))]
        if words < 8 and not text and c["kind"] != "black":
            if not c.get("title"):
                pics += 1       # a picture with no words is a figure, fine in a reading copy
                continue
            print(f"- {c['ordinal']:>3} {c['title']!r:40} {words}w")
            n += 1
    print(("none" if not n else "") + (f" ({pics} picture-only screens not listed)" if pics else ""))

    print("## Spoken text aimed at the room or screen (ordinal: excerpt)")
    n = 0
    for c in vis:
        for m in ROOM.finditer(c.get("script") or ""):
            s = (c["script"] or "")
            print(f"- {c['ordinal']:>3}: ...{s[max(0, m.start() - 50):m.end() + 50].strip()!r}")
            n += 1
    print("none" if not n else "")

    print("## Timers and hands-on screens in the reading copy")
    for c in vis:
        blob = json.dumps(c.get("screen_text") or [])
        if re.search(r"timer", blob, re.I):
            print(f"- {c['ordinal']:>3} {c.get('title') or ''!r}: has a timer: a room beat? consider `live` or `do` (timers never print)")
    print()

    print("## Page leaks")
    body = re.sub(r"<(style|script)\b.*?</\1>", " ", page, flags=re.S)
    text = html_mod.unescape(re.sub(r"<[^>]+>", " ", body))
    allowed = [str(x) for x in (meta.get("web-allow") or [])]
    hits = sorted({m.group(0) for m in LEAK.finditer(text)
                   if not any(x in text[m.start():m.end() + 80] for x in allowed)})
    print(", ".join(repr(h) for h in hits) if hits else "none")
    return 0


if __name__ == "__main__":
    sys.exit(main())
