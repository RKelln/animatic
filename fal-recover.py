#!/usr/bin/env python3
"""fal-recover.py — backfill fal's generation record for a whole deck.

For every clip in a deck's media tree, read the fal request id out of its C2PA
manifest and cache the generation record beside it (`.fal.json` +
`.expanded.txt`). Use it to document a batch that was generated before the
pipeline knew about it; `ingest.py` does the same thing per file as it files
them. Mechanics, fields and limits: see `falrec.py`.

Usage:
    python3 fal-recover.py <talk.md> [--limit N] [--dry-run] [--refresh]
                                      [--include-incoming]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import falrec
from mediaresolve import VIDEO_EXTS


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("talk", type=Path)
    ap.add_argument("--limit", type=int, default=0, help="only the first N clips")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--refresh", action="store_true", help="re-fetch cached records")
    ap.add_argument("--include-incoming", action="store_true",
                    help="also recover clips still in media/_incoming/ — recover "
                         "BEFORE filing, because the prompt identifies the slug")
    args = ap.parse_args(argv)

    talk = args.talk.resolve()
    if not talk.is_file():
        print(f"error: no such talkfile: {talk}", file=sys.stderr)
        return 2
    media = talk.parent / "media"
    clips = sorted(p for p in media.rglob("*")
                   if p.is_file() and p.suffix.lower() in VIDEO_EXTS
                   and (args.include_incoming or "_incoming" not in p.parts))
    if args.limit:
        clips = clips[: args.limit]

    key = None
    if not args.dry_run:
        try:
            key = falrec.load_key()
        except falrec.NoRecord as e:
            sys.exit(f"error: {e}")

    got, noid, failed, secs, units = 0, [], [], 0.0, 0.0
    for p in clips:
        if args.dry_run:
            rid = falrec.extract_request_id(p)
            print(f"  {p.relative_to(media)}  ->  {rid or '(no fal id)'}")
            continue
        if p.with_suffix(falrec.SIDECAR).is_file() and not args.refresh:
            rec = json.loads(p.with_suffix(falrec.SIDECAR).read_text())
        else:
            try:
                rec = falrec.recover(p, key, refresh=args.refresh)
            except falrec.NoRecord:
                rec = None
            except Exception as e:                                   # noqa: BLE001
                failed.append((p.name, f"{type(e).__name__}: {e}"))
                continue
            if rec is None:
                noid.append(p.name)
                continue
        got += 1
        secs += float(rec.get("duration") or 0)
        units += float(rec.get("billable_units") or 0)

    if args.dry_run:
        return 0
    print(f"clips scanned      : {len(clips)}")
    print(f"records recovered  : {got}")
    if noid:
        print(f"no fal id          : {len(noid)}  {noid}")
    if failed:
        print(f"fetch failed       : {len(failed)}  {failed}")
    print(f"fal processing time: {secs:.1f} s")
    if units:
        print(f"billed units       : {units:.1f}")
    print(f"\ncached a {falrec.SIDECAR} + {falrec.EXPANDED} beside each clip")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
