"""build.py — animatic builder spike (E2).

One talkfile in, three outputs out:
    out/present/index.html      reveal.js v6 stand-in deck (VO in speaker notes)
    out/document/index.html     static HTML handout (VO as prose; print CSS for PDF)
    out/cues.json               ordered slide id -> script text (future controller)
    out/media-manifest.json     slug resolution audit

Usage:
    python3 build.py TALKFILE [--out OUTDIR]

Example (specimen):
    python3 build.py ~/talks/decks/L01-opening-talk/talk.md

The specimen talkfile and its media dir are READ-ONLY inputs: this builder
never writes outside OUTDIR.  Deterministic output; out/ is gitignored.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

import talkparse
from mediaresolve import MediaResolver
from render import render_cues, render_document, render_manifest, render_present


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("talkfile", help="path to the talkfile (markdown)")
    ap.add_argument("--out", default="out", help="output directory (default: out/)")
    ap.add_argument("--keep", action="store_true",
                    help="do not wipe the output directory first")
    args = ap.parse_args(argv)

    talk_path = Path(args.talkfile).expanduser().resolve()
    if not talk_path.is_file():
        print(f"error: talkfile not found: {talk_path}", file=sys.stderr)
        return 2

    talk = talkparse.build_talk(talk_path)
    resolver = MediaResolver(talk_dir=talk_path.parent, meta=talk.meta)

    out = Path(args.out).expanduser().resolve()
    if out.exists():
        if not args.keep:
            shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)

    present = render_present(talk, resolver, out / "present")
    document = render_document(talk, resolver, out / "document")
    cues = render_cues(talk, resolver, out)
    manifest = render_manifest(talk, resolver, out)

    print(f"talk      : {talk.source}")
    print(f"title     : {talk.meta.get('title', '')}")
    print(f"movements : {len(talk.movements)} "
          f"({', '.join(str(m.index) for m in talk.movements)})")
    print(f"screens   : {len(talk.screens)} (cues); "
          f"opening={sum(1 for s in talk.screens if s.movement == 0)}")
    roles = {r: 0 for r in ("stat", "lower", "credits")}
    for s in talk.screens:
        for b in s.blocks:
            if b.kind in roles:
                roles[b.kind] += 1
    empty_script = 0
    for s in talk.screens:
        has_script = any((b.kind == "vo" and b.text.strip()) or b.kind == "stat"
                         for b in s.blocks)
        if not has_script:
            empty_script += 1
    print(f"roles     : stat={roles['stat']} lower={roles['lower']} "
          f"credits={roles['credits']} (payloads)")
    print(f"beats     : {empty_script} screen(s) carry no script (card/media "
          f"beat with no VO — see cues.json)")
    media_refs = referenced_media(talk, resolver)
    found = [r for r in media_refs if r.found]
    missing = [r for r in media_refs if not r.found]
    print(f"media     : {len(media_refs)} referenced slugs; "
          f"found={len(found)} placeholder={len(missing)}")
    if talk.warnings:
        print("warnings  :")
        for w in talk.warnings:
            print(f"  - {w}")
    print(f"written   : {present}")
    print(f"           : {document}")
    print(f"           : {cues}")
    print(f"           : {manifest}")
    return 0


def referenced_media(talk: talkparse.Talk, resolver: MediaResolver):
    seen = []
    slugs = set()
    for s in talk.screens:
        for shot in s.shots:
            if shot.is_media and shot.slug not in slugs:
                slugs.add(shot.slug)
                seen.append(resolver.resolve(shot.slug))
    return seen


if __name__ == "__main__":
    sys.exit(main())
