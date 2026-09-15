"""build.py — animatic builder spike (E2).

One talkfile in, three views out:
    out/present/index.html      own-pager deck (VO in speaker notes)
    out/present/presenter.html  speaker UI for the second window ('s')
    out/document/index.html     static HTML handout (VO as prose; print CSS for PDF)

...and three generated sidecars:
    out/cues.json               ordered slide id -> script text (future controller)
    out/nav.json                cue id -> source line range, movement, kind
    out/media-manifest.json     slug resolution audit

Usage:
    python3 build.py TALKFILE [--out OUTDIR]
    python3 build.py --corpus [ROOT]     # corpus check (register 21, T11)

Example (specimen):
    python3 build.py ~/talks/decks/L01-opening-talk/talk.md

--corpus without ROOT uses the corpus.yaml content roots; with ROOT it scans
that directory (per-deck pass/fail + cross-deck slug collisions + tag drift
and coverage reports).  The builder itself is never used in corpus mode —
the corpus check parses and checks every deck read-only and never writes
into a content root.

The specimen talkfile and its media dir are READ-ONLY inputs: this builder
never writes outside OUTDIR.  Deterministic output; out/ is gitignored.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

import yaml

import talkparse
from mediaresolve import MediaResolver
from render import (render_cues, render_document, render_manifest, render_nav,
                    render_present, render_presenter)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("talkfile", nargs="?", help="path to the talkfile "
                    "(markdown); omit when --corpus is used")
    ap.add_argument("--out", default="out", help="output directory (default: out/)")
    ap.add_argument("--corpus", nargs="?", const="__config__", metavar="ROOT",
                    help="corpus mode (check 21): with ROOT, scan that "
                         "directory; without, use the corpus.yaml content "
                         "roots.  Exclusive with TALKFILE.")
    ap.add_argument("--keep", action="store_true",
                    help="do not wipe the output directory first")
    ap.add_argument("--theme", default=None,
                    help="override the talkfile's theme: frontmatter "
                         "(e.g. --theme lecture) for style comparisons")
    ap.add_argument("--media-remap", default=None, metavar="YAML",
                    help="slug -> file stand-in map for unproduced media "
                         "(see remaps/l01-standins.yaml); real art always "
                         "beats a stand-in")
    args = ap.parse_args(argv)

    if args.corpus is not None:
        if args.talkfile:
            ap.error("--corpus is exclusive with TALKFILE")
        import check
        root = None if args.corpus == "__config__" else args.corpus
        return check.corpus_main(root)

    if not args.talkfile:
        ap.error("a TALKFILE is required (or use --corpus [ROOT])")
    talk_path = Path(args.talkfile).expanduser().resolve()
    if not talk_path.is_file():
        print(f"error: talkfile not found: {talk_path}", file=sys.stderr)
        return 2

    talk = talkparse.build_talk(talk_path)
    if args.theme:
        talk.meta["theme"] = args.theme
    resolver = MediaResolver(talk_dir=talk_path.parent, meta=talk.meta)
    if args.media_remap:
        remap_path = Path(args.media_remap).expanduser().resolve()
        if not remap_path.is_file():
            print(f"error: media-remap file not found: {remap_path}",
                  file=sys.stderr)
            return 2
        raw = yaml.safe_load(remap_path.read_text(encoding="utf-8")) or {}
        base = remap_path.parent
        resolver.remap = {}
        for k, v in raw.items():
            if not isinstance(v, str):
                continue
            p = Path(v) if Path(v).is_absolute() else base / v
            resolver.remap[str(k)] = p.resolve()
        gone = [k for k, p in resolver.remap.items() if not p.is_file()]
        for k in gone:
            del resolver.remap[k]
        if gone:
            print(f"warn      : media-remap file(s) missing, ignored: "
                  f"{', '.join(gone)}")

    out = Path(args.out).expanduser().resolve()
    if out.exists():
        if not args.keep:
            shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)

    media_refs = referenced_media(talk, resolver)
    resolver.publish(out, [r.slug for r in media_refs])

    present = render_present(talk, resolver, out / "present")
    presenter = render_presenter(talk, resolver, out / "present")
    document = render_document(talk, resolver, out / "document")
    cues = render_cues(talk, resolver, out)
    nav = render_nav(talk, out)
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
        has_script = any((b.kind == "vo" and b.text.strip()) or b.spoken
                         for b in s.blocks)
        if not has_script:
            empty_script += 1
    print(f"roles     : stat={roles['stat']} lower={roles['lower']} "
          f"credits={roles['credits']} (payloads)")
    print(f"beats     : {empty_script} screen(s) carry no script (card/media "
          f"beat with no VO — see cues.json)")
    found = [r for r in media_refs if r.found]
    missing = [r for r in media_refs if not r.found]
    print(f"media     : {len(media_refs)} referenced slugs; "
          f"found={len(found)} placeholder={len(missing)}")
    if talk.warnings:
        print("warnings  :")
        for w in talk.warnings:
            print(f"  - {w}")
    print(f"written   : {present}")
    print(f"           : {presenter}")
    print(f"           : {document}")
    print(f"           : {cues}")
    print(f"           : {nav}")
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
