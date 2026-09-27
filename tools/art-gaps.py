#!/usr/bin/env python3
"""art-gaps — the two-way gap report for one deck.

A deck links slugs it cannot show, and it owns art that no screen shows. This
prints both, so a human can decide per item: make the missing art, or cut or
place the art that has no home.

    python3 tools/art-gaps.py <talkfile> [--json] [--top N] [--width N]

A. SHOTS WITH NO MEDIA
   Slugs a shot links that resolve to nothing, in document order, with the
   first cue that wants each one and the resolver's own reason. The `on disk`
   column is the one to look at: art already sitting on disk that the card does
   not point at is made, so those rows are wire-or-cut rather than to-do. A
   slug whose status claims the art is in hand AND that has nothing on disk is
   drift.

B. PREPPED ART WITH NO SHOT
   Displayable files on disk whose slug no shot references, biggest first.
   `carded` = a card points at one of its files; `orphan` = nothing in the deck
   points at it, so the resolver cannot see it at all. One row per slug with a
   file count, because extra takes of an unwired slug are the same decision.
   Non-displayable files (PDFs, receipts, logs) are counted, not listed:
   nothing can be cut from them.

Exit code is 0 either way: this is a report, not a gate. Use --json downstream.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import talkparse  # noqa: E402
from mediaresolve import MediaResolver  # noqa: E402
from render import deck_slug  # noqa: E402

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".avif", ".tif", ".tiff", ".bmp"}
VIDEO_EXT = {".mp4", ".mov", ".webm", ".mkv", ".m4v", ".avi"}

# Card statuses that say the art is in hand. If one of these resolves to
# nothing AND nothing is on disk, the file went missing rather than never
# existing.
IN_HAND = {"have", "approved", "delivered", "final"}


def kind_of(p: Path) -> str:
    return "video" if p.suffix.lower() in VIDEO_EXT else "image"


def displayable(p: Path) -> bool:
    return p.suffix.lower() in IMAGE_EXT or p.suffix.lower() in VIDEO_EXT


def human_bytes(n: float) -> str:
    if n < 1024:
        return f"{n:.0f} B"
    if n < 1024 ** 2:
        return f"{n / 1024:.0f} KB"
    if n < 1024 ** 3:
        return f"{n / 1024 ** 2:.1f} MB"
    return f"{n / 1024 ** 3:.2f} GB"


def slug_for_file(media_dir: Path, p: Path) -> str:
    """The slug a file under media/ belongs to, by the resolver's own shapes."""
    parts = p.relative_to(media_dir).parts
    if len(parts) == 1:
        return p.stem
    if parts[0] == "found" and len(parts) >= 3:
        return parts[1]
    if len(parts) >= 3 and parts[1] == "attempts":
        return parts[0]
    return parts[0]


def collect(talk_path: Path) -> dict:
    talk = talkparse.build_talk(talk_path)
    resolver = MediaResolver(talk_dir=talk_path.parent, meta=talk.meta)
    slug = deck_slug(talk)
    media_dir = Path(resolver.media_dir)

    # linked slugs in document order, with the first cue that wants each
    first_cue: dict[str, str] = {}
    order: list[str] = []
    for screen in talk.screens:
        cue = f"{slug}-{screen.idx:03d}"
        for shot in screen.shots:
            if shot.is_media and shot.slug and shot.slug not in first_cue:
                first_cue[shot.slug] = cue
                order.append(shot.slug)
    refs = {s: resolver.resolve(s) for s in order}

    # one pass over the media tree: what art actually exists, per slug
    disk: dict[str, dict] = {}
    counted: set[str] = set()
    other_files: Counter = Counter()
    other_bytes = 0
    if media_dir.is_dir():
        for p in media_dir.rglob("*"):
            if not p.is_file():
                continue
            rel = p.relative_to(media_dir)
            if rel.parts[0].startswith("_") or any(x.startswith(".") for x in rel.parts):
                continue
            if not displayable(p):
                other_files[p.suffix.lower() or "(none)"] += 1
                other_bytes += p.stat().st_size
                continue
            s = slug_for_file(media_dir, p)
            e = disk.setdefault(s, {"files": 0, "bytes": 0, "type": kind_of(p), "path": ""})
            e["files"] += 1
            e["bytes"] += p.stat().st_size
            counted.add(str(p))
            if not e["path"]:
                cand = media_dir / s
                if not cand.is_dir():
                    cand = media_dir / "found" / s
                e["path"] = str(cand if cand.is_dir() else p.parent)

    # ---- A: linked but not shown
    missing = []
    for s in order:
        r = refs[s]
        if r.found:
            continue
        d = disk.get(s)
        missing.append({
            "slug": s, "cue": first_cue[s], "type": r.type, "status": r.status,
            "reason": (r.reason or r.note or "").splitlines()[0].strip(),
            "on_disk_files": d["files"] if d else 0,
            "on_disk_bytes": d["bytes"] if d else 0,
            "on_disk_path": d["path"] if d else "",
            "unwired": bool(d),
            "drift": r.status in IN_HAND and not d,
        })

    # ---- B: art with no shot. One row per slug: the on-disk walk and the card
    # list are merged, because a carded slug can also hold extra takes.
    unused_cards = resolver.unreferenced_cards(set(order))
    agg: dict[str, dict] = {}
    for s, d in disk.items():
        if s not in refs:
            agg[s] = dict(d, slug=s, status="", how="orphan", card_file="")
    for s in unused_cards:
        r = resolver.resolve(s)
        e = agg.setdefault(s, {"slug": s, "files": 0, "bytes": 0, "type": r.type or "image",
                               "path": str(media_dir / s), "status": "", "how": "orphan",
                               "card_file": ""})
        e["status"] = r.status or ""
        if r.type and r.type != "unknown":
            e["type"] = r.type
        if r.found and r.file:
            p = Path(r.file)
            e["how"] = "carded"
            e["card_file"] = str(p)
            if str(p) not in counted:
                counted.add(str(p))
                e["files"] += 1
                e["bytes"] += p.stat().st_size if p.exists() else 0
                if not e["path"]:
                    e["path"] = str(p.parent)

    unused = sorted(agg.values(), key=lambda e: -e["bytes"])
    return {
        "talk": str(talk_path),
        "deck": slug,
        "screens": len(talk.screens),
        "linked": len(order),
        "found": sum(1 for r in refs.values() if r.found),
        "a_missing": missing,
        "b_unused": unused,
        "b_other": dict(other_files),
        "b_other_bytes": other_bytes,
        "unreferenced_cards": len(unused_cards),
    }


def report(d: dict, top: int, width: int) -> None:
    print(f"art gaps — {d['talk']}")
    print(f"  deck {d['deck']}: {d['screens']} screens, {d['linked']} linked slugs, "
          f"{d['found']} resolve, {len(d['a_missing'])} do not\n")

    miss = d["a_missing"]
    print(f"A. SHOTS WITH NO MEDIA — {len(miss)}")
    if miss:
        by_status = Counter(m["status"] or "(no card)" for m in miss)
        print("   by card status: " + ", ".join(f"{k}={v}" for k, v in by_status.most_common()))
        unwired = [m for m in miss if m["unwired"]]
        drift = [m for m in miss if m["drift"]]
        if unwired:
            print(f"   {len(unwired)} already have art on disk and are only unwired, "
                  f"{human_bytes(sum(m['on_disk_bytes'] for m in unwired))} in total: "
                  + ", ".join(m["slug"] for m in unwired))
        if drift:
            print(f"   !! drift, status says in hand and nothing on disk: "
                  + ", ".join(m["slug"] for m in drift))
        print(f"\n   {'cue':<22}{'slug':<32}{'status':<10}{'type':<8}{'on disk':<22}why")
        for m in miss:
            on = (f"{m['on_disk_files']} files {human_bytes(m['on_disk_bytes'])}"
                  if m["unwired"] else "-")
            print(f"   {m['cue']:<22}{m['slug'][:31]:<32}{m['status'] or '-':<10}{m['type']:<8}"
                  f"{on[:21]:<22}{m['reason'][:width]}")
    print()

    un = d["b_unused"]
    print(f"B. PREPPED ART WITH NO SHOT — {len(un)} slugs, "
          f"{human_bytes(sum(e['bytes'] for e in un))}")
    print(f"   ({d['unreferenced_cards']} cards are unreferenced; the ones without art on disk "
          f"are briefs, so nothing can be cut from them)")
    if un:
        print(f"\n   {'how':<8}{'slug':<32}{'status':<11}{'type':<7}{'files':>6}{'size':>11}  path")
        for e in un[:top]:
            print(f"   {e['how']:<8}{e['slug'][:31]:<32}{e['status'] or '-':<11}{e['type']:<7}"
                  f"{e['files']:>6}{human_bytes(e['bytes']):>11}  {e['path']}")
        if len(un) > top:
            rest = un[top:]
            print(f"   ... {len(rest)} more, {human_bytes(sum(e['bytes'] for e in rest))} "
                  f"(raise --top to list them)")
    if d["b_other"]:
        tally = ", ".join(f"{n}x {ext}" for ext, n in
                          sorted(d["b_other"].items(), key=lambda kv: -kv[1]))
        print(f"\n   reference material, not art "
              f"({sum(d['b_other'].values())} files, {human_bytes(d['b_other_bytes'])}): {tally}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("talkfile", help="path to the talkfile")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--top", type=int, default=40, help="rows to list in section B (default 40)")
    ap.add_argument("--width", type=int, default=58, help="reason column width (default 58)")
    args = ap.parse_args(argv)

    talk_path = Path(args.talkfile).expanduser().resolve()
    if not talk_path.is_file():
        print(f"error: talkfile not found: {talk_path}", file=sys.stderr)
        return 2
    d = collect(talk_path)
    if args.json:
        print(json.dumps(d, indent=2, ensure_ascii=False))
    else:
        report(d, args.top, args.width)
    return 0


if __name__ == "__main__":
    sys.exit(main())
