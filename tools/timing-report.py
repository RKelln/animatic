#!/usr/bin/env python3
"""timing-report — how long a talk runs, and where the time goes.

    python3 tools/timing-report.py <talkfile> [--dur 2h] [--wpm N] [--top N]
                                   [--screens] [--json]

Uses the clock everything else uses: render.cue_estimate, then timing.yaml
overrides (measured > authored > estimated). Shelf screens are left out, as in
check 19. Every screen's seconds split into buckets that add up to its total:

    spoken    script words at the deck's wpm
    timer     countdown time beyond the words (a plain timer runs while the
              words are spoken; a revealed timer follows them).  A countdown
              continued by `[timer]` screens is shared: the screens in its span
              count their own words, and the timer bucket is what is left
    video     a video's real length beyond the words and timer
    minimum   the floor for a black beat, a beat screen or a credits read
    override  a timing.yaml value, which replaces the whole screen

Anything with no words, timer or override (Q&A, an unscripted demo) counts only
as a minimum, so a low total can mean time nobody has written down.
"""

from __future__ import annotations

import argparse
import json
import sys
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import render  # noqa: E402
import talkparse  # noqa: E402
import timing  # noqa: E402
from mediaresolve import MediaResolver, expand_pools  # noqa: E402

BUCKETS = ("spoken", "timer", "video", "minimum", "override")
SLOW_WPM = 130.0
FAST_WPM = 150.0


def clock(seconds: float) -> str:
    s = int(round(seconds))
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 \
        else f"{s // 60}:{s % 60:02d}"


def split(total: float, words_s: float, timer_s: float, armed: bool,
          video_s: float) -> dict:
    """One estimated screen's seconds as buckets that sum to `total`."""
    spoken = min(words_s, total)
    timer = timer_s if armed else max(timer_s - spoken, 0.0)
    timer = min(timer, total - spoken)
    rest = total - spoken - timer
    video = rest if video_s else 0.0
    return {"spoken": spoken, "timer": timer, "video": video,
            "minimum": rest - video, "override": 0.0}


def build_report(path, *, wpm=None, dur=None) -> dict:
    """The report as plain data.  `dur` and `wpm` replace the deck's own."""
    path = Path(path)
    talk = talkparse.build_talk(path)
    # The resolver warns about missing media; the check suite owns those messages.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        resolver = MediaResolver(talk_dir=path.parent, meta=talk.meta)
        expand_pools(talk, resolver)
    tt = timing.load(path.parent)
    rate = float(wpm) if wpm else tt.wpm
    slug = render.deck_slug(talk)
    titles = {m.index: m.title for m in talk.movements}

    def total_at(at_wpm: float) -> float:
        return sum(tt.effective(f"{slug}-{s.idx:03d}",
                                render.cue_estimate(s, resolver, at_wpm))[0]
                   for s in talk.screens if not s.shelf)

    screens, elapsed = [], 0.0
    for s in talk.screens:
        if s.shelf:
            continue
        cid = f"{slug}-{s.idx:03d}"
        est = render.cue_estimate(s, resolver, rate)
        seconds, tier = tt.effective(cid, est)
        words = timing.word_count(render.screen_script(s))
        words_s = words / rate * 60 if rate else 0.0
        tm = s.timer
        cont = s.timer_parent is not None
        timer_s = float(tm[0]) if tm and not cont else 0.0
        span_s = render.timer_span_seconds(s, resolver, rate) if not cont else 0.0
        armed = render.timer_armed(s)
        video_s = render.cue_video_seconds(s, resolver) or 0.0
        buckets = (dict.fromkeys(BUCKETS, 0.0) | {"override": seconds}
                   if tier != "estimated"
                   else split(seconds, words_s, max(timer_s - span_s, 0.0), armed,
                              video_s))
        screens.append({
            "id": cid, "ordinal": s.idx, "movement": s.movement,
            "title": render.screen_title(s)
                     or (s.media_shot.slug if s.media_shot and s.media_shot.slug
                         else f"({render.screen_kind(s)})"),
            "kind": render.screen_kind(s), "words": words,
            "seconds": seconds, "tier": tier, "starts_at": elapsed,
            "timer": timer_s or None, "timer_reveal": armed,
            # a continued countdown: how many screens after this one share it,
            # and their estimated seconds; a continuation names its parent
            "span_screens": len(s.timer_span), "span_seconds": span_s,
            "continues": (f"{slug}-{s.timer_parent.idx:03d}" if cont else None),
            "words_seconds": words_s,
            "buckets": buckets,
        })
        elapsed += seconds

    movements = []
    for index in dict.fromkeys(x["movement"] for x in screens):
        rows = [x for x in screens if x["movement"] == index]
        movements.append({
            "index": index,
            "title": titles.get(index) or ("Opening" if index == 0 else f"Movement {index}"),
            "screens": len(rows), "words": sum(x["words"] for x in rows),
            "seconds": sum(x["seconds"] for x in rows),
            "starts_at": rows[0]["starts_at"],
            "buckets": {b: sum(x["buckets"][b] for x in rows) for b in BUCKETS},
        })

    declared = dur if dur is not None else talk.meta.get("dur")
    dur_s = timing.parse_dur(declared)
    shelf = [s for s in talk.screens if s.shelf]
    return {
        "deck": slug, "source": str(path), "wpm": rate,
        "total_seconds": elapsed,
        "declared_dur": declared, "dur_seconds": dur_s,
        "divergence": (elapsed - dur_s) / dur_s if dur_s else None,
        "at_slow_wpm": total_at(SLOW_WPM), "at_fast_wpm": total_at(FAST_WPM),
        "words": sum(x["words"] for x in screens),
        "buckets": {b: sum(x["buckets"][b] for x in screens) for b in BUCKETS},
        "movements": movements, "screens": screens,
        "shelf_screens": len(shelf),
        "problems": list(tt.problems),
    }


def bucket_cells(buckets: dict) -> str:
    return " ".join(f"{clock(buckets[b]) if buckets[b] >= 0.5 else '-':>7}"
                    for b in BUCKETS)


def render_text(r: dict, *, top: int, all_screens: bool) -> str:
    out = [f"{r['deck']}  ({r['source']})", ""]
    line = f"Estimated total  {clock(r['total_seconds'])}"
    if r["dur_seconds"]:
        line += (f"   against {clock(r['dur_seconds'])} ({r['declared_dur']}): "
                 f"{r['divergence']:+.0%}")
    else:
        line += "   no dur to compare (pass --dur)"
    out.append(line)
    out.append(f"Speech rate      {r['wpm']:.0f} wpm, {r['words']} spoken words   "
               f"(at {SLOW_WPM:.0f} wpm {clock(r['at_slow_wpm'])}, "
               f"at {FAST_WPM:.0f} wpm {clock(r['at_fast_wpm'])})")
    total = r["total_seconds"] or 1.0
    parts = [f"{b} {clock(r['buckets'][b])} ({r['buckets'][b] / total:.0%})"
             for b in BUCKETS if r["buckets"][b] >= 0.5]
    out.append("Made of          " + ", ".join(parts))
    if r["shelf_screens"]:
        out.append(f"Left out         {r['shelf_screens']} shelf screens")
    for problem in r["problems"]:
        out.append(f"timing.yaml      {problem}")

    head = (f"{'starts':>7} {'length':>7} {'share':>5} {'scr':>3} {'words':>5} "
            + " ".join(f"{b:>7}" for b in BUCKETS))
    out += ["", "BY MOVEMENT", head + "  movement"]
    for m in r["movements"]:
        out.append(f"{clock(m['starts_at']):>7} {clock(m['seconds']):>7} "
                   f"{m['seconds'] / total:>5.0%} {m['screens']:>3} {m['words']:>5} "
                   f"{bucket_cells(m['buckets'])}  {m['title']}")

    timed = [x for x in r["screens"] if x["timer"]]
    if timed:
        out += ["", "TIMERS", f"{'starts':>7} {'timer':>7} {'kind':<8} "
                f"{'words':>5} {'span':>4} {'counted':>7}  screen"]
        for x in timed:
            span = x["span_screens"]
            # time spoken while the countdown runs: the span's screens, plus
            # this screen's own words when the timer starts on arrival
            during = x["span_seconds"] + (0.0 if x["timer_reveal"] else x["words_seconds"])
            late = x["tier"] == "estimated" and (during > x["timer"] if span else (
                not x["timer_reveal"] and x["buckets"]["spoken"] > x["timer"]))
            # a continued countdown counts the parent plus its span
            counted = x["seconds"] + x["span_seconds"]
            out.append(f"{clock(x['starts_at']):>7} {clock(x['timer']):>7} "
                       f"{'revealed' if x['timer_reveal'] else 'plain':<8} "
                       f"{x['words']:>5} {(f'+{span}' if span else ''):>4} "
                       f"{clock(counted):>7}  {x['title']}"
                       + (("  !! the talk inside it outlasts the timer" if span
                           else "  !! words outlast the timer") if late else ""))

    overrides = [x for x in r["screens"] if x["tier"] != "estimated"]
    if overrides:
        out += ["", "OVERRIDES (timing.yaml)"]
        out += [f"{clock(x['seconds']):>7}  {x['tier']:<9} {x['id']}  {x['title']}"
                for x in overrides]

    longest = sorted(r["screens"], key=lambda x: (-x["seconds"], x["ordinal"]))[:top]
    out += ["", f"LONGEST {len(longest)} SCREENS",
            f"{'starts':>7} {'length':>7} {'words':>5}  screen"]
    out += [f"{clock(x['starts_at']):>7} {clock(x['seconds']):>7} {x['words']:>5}  "
            f"{x['title']}" for x in longest]

    if all_screens:
        out += ["", "EVERY SCREEN", f"{'starts':>7} {'length':>7} {'words':>5} "
                f"{'tier':<9} cue"]
        out += [f"{clock(x['starts_at']):>7} {clock(x['seconds']):>7} {x['words']:>5} "
                f"{x['tier']:<9} {x['id']}  {x['title']}" for x in r["screens"]]
    return "\n".join(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="How long a talk runs, and where the time goes.")
    ap.add_argument("talkfile")
    ap.add_argument("--dur", help="compare against this slot instead of the deck's dur (2h, 90, 1h30)")
    ap.add_argument("--wpm", type=float, help="speech rate instead of the deck's")
    ap.add_argument("--top", type=int, default=10, help="how many longest screens to list (default 10)")
    ap.add_argument("--screens", action="store_true", help="also list every screen")
    ap.add_argument("--json", action="store_true", help="print the report as JSON")
    args = ap.parse_args(argv)
    path = Path(args.talkfile).expanduser()
    if not path.is_file():
        print(f"timing-report: talkfile not found: {path}", file=sys.stderr)
        return 2
    if args.wpm is not None and args.wpm <= 0:
        ap.error("--wpm must be above zero")
    if args.dur is not None and timing.parse_dur(args.dur) is None:
        ap.error(f"--dur {args.dur!r} is not a duration (try 2h, 90 or 1h30)")
    try:
        report = build_report(path, wpm=args.wpm, dur=args.dur)
    except ValueError as exc:
        print(f"timing-report: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2) if args.json
          else render_text(report, top=args.top, all_screens=args.screens))
    return 0


if __name__ == "__main__":
    sys.exit(main())
