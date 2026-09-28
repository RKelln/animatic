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

C. SCREENS THAT ASK FOR A PICTURE BUT LINK NO SLUG
   A bare `<!-- shot -->` whose stage directions describe a visual ("Visual:",
   "new card needed", "screenshot", "light up" a wall row). Section A cannot
   see these because there is no slug to resolve. Callout-card directions are
   tallied on their own line: they are a deck-wide graphic, not per-screen art.

D. SHOWN, BUT NOT SETTLED
   Linked slugs that resolve to a take nobody has approved yet (candidate,
   prompting, brief), with the take count. `!!` marks a screen whose stage
   direction names a take ("take a3") that is not the file the resolver picked:
   the resolver takes the highest attempt, so the named take is not on screen.

E. POSSIBLE WINS
   First, unused art whose slug a stage direction names outright (a sure win:
   the script already asks for it). Then unresolved slugs paired with unused
   art whose names or briefs share words with the screen, one shared word at
   least being a slug word. A hint to look at: nothing is wired from it.

F. THE PLAN
   Section A regrouped by what closing each gap takes: wire (art on disk), live
   (a `type: live` card), find, build (chart or diagram), generate, record
   (Ryan's own screen or archive), or decide (not enough in the card or the
   script to say). Each row carries the card brief or the screen's own visual
   direction as the description of what is needed.

Exit code is 0 either way: this is a report, not a gate. Use --json downstream.
"""
from __future__ import annotations

import argparse
import json
import re
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
    # Files a linked slug already resolves to are in use, whatever folder they
    # sit in (the Engels charts are two used + three unused in one folder), so
    # they are excluded here rather than reported as unused art.
    used_paths = {str(Path(r.file)) for r in refs.values() if r.found and r.file}
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
            if str(p) in used_paths:
                continue
            s = slug_for_file(media_dir, p)
            e = disk.setdefault(s, {"files": 0, "bytes": 0, "type": kind_of(p), "path": "",
                                    "items": []})
            e["files"] += 1
            e["bytes"] += p.stat().st_size
            counted.add(str(p))
            if len(e["items"]) < 5:
                e["items"].append(p.stem)
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
                               "card_file": "", "items": []})
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
                if len(e["items"]) < 5:
                    e["items"].append(p.stem)
                if not e["path"]:
                    e["path"] = str(p.parent)

    # An unreferenced card with no art on disk is a brief: there is nothing to
    # cut, so it does not belong in a cut-or-place list.
    carded_with_art = {s for s, e in agg.items() if e["files"] > 0 and e["how"] == "carded"}
    unused = sorted((e for e in agg.values() if e["files"] > 0), key=lambda e: -e["bytes"])
    extra = collect_plan(talk, resolver, slug, refs, first_cue, missing, unused, media_dir)
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
        "b_brief_cards": len(unused_cards) - len(carded_with_art),
        **extra,
    }


# ---- C-F: the planning sections -------------------------------------------

# Stage directions that ask for a picture. "Clip" and "Callout" are handled on
# their own: a clip is a video need, a callout card is a deck-wide graphic.
VISUAL_ASK = re.compile(r"\b(visual|new card needed|screenshot|screen capture|"
                        r"screen recording|light up|clip)\b", re.I)
CALLOUT = re.compile(r"^\s*callout cards?:", re.I)
TAKE_NAMED = re.compile(r"\btake (a\d+)\b", re.I)
SETTLED = IN_HAND | {"live"}
TEXT_KINDS = {"heading", "quote", "quote-source", "stat", "lower", "credits", "list",
              "table", "paraphrase"}
STOP = set("""need find build generate record decide wire line same still rows right back
image test screen take takes
the a an and or of to in on at for with from by as is are be it its this that
these those into over under than then when what who how why not no yes one two three
visual new card needed take silent voice under clip ryan tbd about each just like our own
your you they them their there here very more most some any all out off only also
""".split())

# Card-type and wording cues for what closing a gap takes, most specific first.
NEED_ORDER = ["wire", "live", "find", "build", "generate", "record", "decide"]
RECORD_WORDS = re.compile(r"\b(screen recording|screen capture|screenshot|your own|"
                          r"ryan: a screenshot|ryan: screen|clip tbd|recorded)\b", re.I)
FIND_WORDS = re.compile(r"\b(public[- ]domain|licensed|photo|archive|found|prelinger|"
                        r"commons)\b", re.I)
BUILD_WORDS = re.compile(r"\b(chart|diagram|map|graph)\b", re.I)


def _stage(screen) -> list[str]:
    return [s.strip() for b in screen.blocks for s in b.stage if s.strip()]


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z][a-z0-9]+", text.lower())
            if len(w) > 3 and w not in STOP}


def _takes(media_dir: Path, slug: str) -> int:
    adir = media_dir / slug / "attempts"
    return sum(1 for p in adir.iterdir() if p.is_file() and displayable(p)) if adir.is_dir() else 0


def existing_paths(text: str, talk_dir: Path) -> list[str]:
    """Backticked paths in a stage direction that exist on disk, tried against
    the deck dir and its ancestors (a talk points at `events/...` by repo root)."""
    found = []
    for raw in re.findall(r"`([^`\s]+/[^`\s]*)`", text):
        for base in [talk_dir, *list(talk_dir.parents)[:4]]:
            if (base / raw).exists():
                found.append(str(base / raw))
                break
    return found


def classify_need(slug: str, card: dict | None, asks: str, unwired: bool,
                  paths: list[str] | None = None) -> str:
    """What closing one unresolved slug takes. A heuristic for a planning list:
    the card's own type and status speak first, then the script's words. A
    stage direction that points at an existing file or folder counts as art on
    disk: the render exists, it just lives outside media/."""
    said = re.search(r"\bNEED:\s*([a-z]+)", str((card or {}).get("brief") or ""))
    if said and said.group(1) in NEED_ORDER:
        return said.group(1)            # the card says so itself: trust it
    ctype = str((card or {}).get("type") or "").lower()
    status = str((card or {}).get("status") or "").lower()
    credit = str((card or {}).get("credit") or "").lower()
    if ctype == "live" or slug.startswith("live-"):
        return "live"
    if unwired or paths:
        return "wire"
    if status == "to-find":
        return "find"
    if ctype == "chart":
        return "build"
    if "generated" in credit:
        return "generate"
    if RECORD_WORDS.search(asks):
        return "record"
    if FIND_WORDS.search(asks):
        return "find"
    if BUILD_WORDS.search(asks):
        return "build"
    if "new card needed" in asks.lower():
        return "generate"
    return "decide"


def collect_plan(talk, resolver, deck, refs, first_cue, missing, unused, media_dir) -> dict:
    by_cue = {f"{deck}-{s.idx:03d}": s for s in talk.screens}

    # C: bare screens that describe a visual, and the callout-card tally
    unslugged, callouts = [], []
    for s in talk.screens:
        cue = f"{deck}-{s.idx:03d}"
        stage = _stage(s)
        callouts += [(cue, x) for x in stage if CALLOUT.match(x)]
        if any(sh.is_media for sh in s.shots):
            continue
        asks = [x for x in stage if VISUAL_ASK.search(x) and not CALLOUT.match(x)]
        if asks:
            unslugged.append({"cue": cue, "line": s.shots[0].line if s.shots else s.line,
                              "ask": asks[0]})
        elif not any(b.kind in TEXT_KINDS for b in s.blocks) and not any(
                sh.role for sh in s.shots):
            unslugged.append({"cue": cue, "line": s.shots[0].line if s.shots else s.line,
                              "ask": "(no picture, no screen text: voice only)"})

    # D: resolved but unsettled, and named takes the resolver does not show
    unsettled = []
    for slug_, r in refs.items():
        if not r.found or r.live:
            continue
        cue = first_cue[slug_]
        named = []
        for s in talk.screens:
            if any(sh.slug == slug_ for sh in s.shots):
                named += TAKE_NAMED.findall(" ".join(_stage(s)))
        shown = Path(r.file).stem if r.file else ""
        wrong = sorted({t for t in named if not shown.endswith("-" + t.lower())})
        if (r.status or "") in SETTLED and not wrong:
            continue
        unsettled.append({"slug": slug_, "cue": cue, "status": r.status or "",
                          "takes": _takes(media_dir, slug_), "shown": shown,
                          "named_take_not_shown": wrong})

    # E: word overlap between each unresolved slug's screen and unused art
    def art_words(e):
        card = resolver.card_for(e["slug"]) or {}
        return _words(" ".join([e["slug"].replace("-", " "), str(card.get("brief") or ""),
                                str(card.get("alt") or "")]))
    pool = [(e["slug"], art_words(e)) for e in unused]
    wins = []
    for m in missing:
        if m["unwired"]:
            continue
        scr = by_cue.get(m["cue"])
        card = resolver.card_for(m["slug"]) or {}
        want = _words(" ".join([m["slug"].replace("-", " "), str(card.get("brief") or ""),
                                " ".join(_stage(scr)) if scr else ""]))
        # at least one shared word must be a slug word on either side, so two
        # long briefs cannot match on prose alone
        names = _words(m["slug"].replace("-", " "))
        best = sorted(((len(want & w), s, sorted(want & w)) for s, w in pool
                       if want & w & (names | _words(s.replace("-", " ")))),
                      reverse=True)
        if best and best[0][0] >= 3:
            n, s, shared = best[0]
            wins.append({"slug": m["slug"], "cue": m["cue"], "art": s, "shared": shared[:6]})

    # E, the sure kind: unused art whose slug a stage direction names outright
    # ("stocking-frame-overlook → frame-breaking → ..."), with no shot for it
    unused_slugs = {e["slug"] for e in unused}
    for s in talk.screens:
        text = " ".join(_stage(s))
        for u in sorted(unused_slugs):
            if re.search(rf"(?<![a-z0-9-]){re.escape(u)}(?![a-z0-9-])", text):
                wins.insert(0, {"slug": "(named in script)", "cue": f"{deck}-{s.idx:03d}",
                                "art": u, "shared": ["slug named in a stage direction"]})

    # F: the plan, section A regrouped by what it takes
    plan = []
    for m in missing:
        scr = by_cue.get(m["cue"])
        card = resolver.card_for(m["slug"])
        stage = _stage(scr) if scr else []
        asks = " ".join(stage)
        brief = " ".join(str((card or {}).get("brief") or "").split())
        vis = next((x for x in stage if VISUAL_ASK.search(x)), "")
        what = brief or vis or next((b.text for b in (scr.blocks if scr else [])
                                     if b.kind in ("heading", "vo") and b.text), "")
        uses = sum(1 for s in talk.screens if any(sh.slug == m["slug"] for sh in s.shots))
        paths = existing_paths(asks, Path(resolver.talk_dir))
        plan.append({"slug": m["slug"], "cue": m["cue"], "uses": uses,
                     "need": classify_need(m["slug"], card, asks + " " + brief, m["unwired"],
                                           paths),
                     "what": " ".join(what.split()), "paths": paths})
    plan.sort(key=lambda p: (NEED_ORDER.index(p["need"]), p["cue"]))
    return {"c_unslugged": unslugged, "c_callouts": [{"cue": c, "text": t} for c, t in callouts],
            "d_unsettled": unsettled, "e_wins": wins, "f_plan": plan}


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
    print(f"   plus {d['b_brief_cards']} unreferenced cards with no art on disk: briefs, "
          f"so nothing can be cut from those")
    if un:
        print(f"\n   {'how':<8}{'slug':<32}{'status':<11}{'type':<7}{'files':>6}{'size':>11}  path")
        for e in un[:top]:
            print(f"   {e['how']:<8}{e['slug'][:31]:<32}{e['status'] or '-':<11}{e['type']:<7}"
                  f"{e['files']:>6}{human_bytes(e['bytes']):>11}  {e['path']}")
            if 1 < e["files"] <= 4 and e.get("items"):
                print(f"   {'':<8}  {', '.join(e['items'])}")
        if len(un) > top:
            rest = un[top:]
            print(f"   ... {len(rest)} more, {human_bytes(sum(e['bytes'] for e in rest))} "
                  f"(raise --top to list them)")
    if d["b_other"]:
        tally = ", ".join(f"{n}x {ext}" for ext, n in
                          sorted(d["b_other"].items(), key=lambda kv: -kv[1]))
        print(f"\n   reference material, not art "
              f"({sum(d['b_other'].values())} files, {human_bytes(d['b_other_bytes'])}): {tally}")
    report_plan(d, width)


def report_plan(d: dict, width: int) -> None:
    un = d["c_unslugged"]
    print(f"\nC. SCREENS THAT ASK FOR A PICTURE BUT LINK NO SLUG — {len(un)}")
    for u in un:
        print(f"   {u['cue']:<22}line {u['line']:<6}{u['ask'][:width + 40]}")
    if d["c_callouts"]:
        print(f"   plus {len(d['c_callouts'])} callout-card directions (one deck-wide graphic, "
              f"no role yet): " + ", ".join(c["cue"].rsplit("-", 1)[-1] for c in d["c_callouts"]))

    us = d["d_unsettled"]
    print(f"\nD. SHOWN, BUT NOT SETTLED — {len(us)}")
    if us:
        print(f"   {'cue':<22}{'slug':<32}{'status':<11}{'takes':>5}  shown")
        for u in us:
            flag = (f"  !! script names take {', '.join(u['named_take_not_shown'])}"
                    if u["named_take_not_shown"] else "")
            print(f"   {u['cue']:<22}{u['slug'][:31]:<32}{u['status'] or '-':<11}"
                  f"{u['takes']:>5}  {u['shown']}{flag}")

    ws = d["e_wins"]
    print(f"\nE. POSSIBLE WINS — {len(ws)} (shared words, a hint only)")
    for w in ws:
        print(f"   {w['cue']:<22}{w['slug'][:31]:<32}<- {w['art']:<30}{', '.join(w['shared'])}")

    plan = d["f_plan"]
    print(f"\nF. THE PLAN — {len(plan)} gaps by what closing them takes")
    for need in NEED_ORDER:
        rows = [p for p in plan if p["need"] == need]
        if not rows:
            continue
        print(f"\n   {need.upper()} ({len(rows)})")
        for p in rows:
            uses = f" x{p['uses']}" if p["uses"] > 1 else ""
            print(f"   {p['cue']:<22}{(p['slug'] + uses)[:31]:<32}{p['what'][:width + 40]}")
            for path in p.get("paths", []):
                print(f"   {'':<22}{'':<32}on disk: {path}")


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
