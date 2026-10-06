"""Property checks for timer tokens (spec: Timer screens).

`[Timer: 8:00]` in screen text is a countdown in the present view and one quiet
line in the document view.  For every fixture that has tokens these hold,
independent of the goldens:

- a cue's `timer` is an integer number of seconds, equal to the first valid
  token's duration; `timer_in` indexes the `screen_text` entry holding it;
  `timer_corner` is set exactly when that token says `corner`; a cue with no
  valid token has none of the three keys;
- no cue's voice-over (`script`) holds a token; a token in a spoken paragraph
  starts nothing;
- the present view draws exactly one `.timer-plate` per timer cue, with
  `data-timer` equal to the seconds and the shape the token asked for (corner,
  block when alone on its line, inline otherwise); no plate on any other cue;
- the document view never carries a plate or a clock: each timer cue prints
  `<duration as written> timer`;
- est_seconds: with no voice-over a timer cue lasts the timer; with voice-over
  the estimate is the words' own and the timer adds nothing;
- a token inside a fence or a parenthetical, an invalid one and a second one
  stay literal and start nothing.
"""

from __future__ import annotations

import re

import talkparse
import timing

from .common import err

LOOSE_RE = re.compile(r"\[\s*timer\s*:[^\]]*\]", re.IGNORECASE)


def _section(text: str, cue_id: str) -> str:
    m = re.search(r'<section id="%s".*?</section>' % re.escape(cue_id), text, re.DOTALL)
    return m.group(0) if m else ""


def _first_valid(entries: list):
    """(index, seconds, phrase, corner) for the first valid token in the
    cue's screen_text entries, in order, or None."""
    for i, t in enumerate(entries):
        if t.get("kind") == "code":
            continue
        texts = list(t.get("items") or []) + ([t["text"]] if "text" in t else [])
        for text in texts:
            for m in LOOSE_RE.finditer(text):
                inner = talkparse.TIMER_TOKEN_RE.match(m.group(0)).group(1)
                got = talkparse.parse_timer_token(inner)
                if got is not None:
                    return i, got[0], got[1], got[2]
    return None


def check(fx, errors: list) -> None:
    if not LOOSE_RE.search(fx.source_text):
        return
    cues = fx.cues()["cues"]
    present = (fx.out / "present" / "index.html").read_text(encoding="utf-8")
    doc = (fx.out / "document" / "index.html").read_text(encoding="utf-8")

    for c in cues:
        cid = c["id"]
        entries = c.get("screen_text") or []
        sec = _section(present, cid)
        plates = re.findall(r'class="timer-plate timer-(\w+)"[^>]*data-timer="(\d+)"', sec)
        want = _first_valid(entries)
        if "timer" in c:
            if not isinstance(c["timer"], int) or isinstance(c["timer"], bool):
                err(errors, f"{cid}: timer {c['timer']!r} is not an integer")
            if want is None or c["timer"] != want[1]:
                err(errors, f"{cid}: timer {c['timer']!r} != first valid token {want!r}")
            else:
                if c.get("timer_in") != want[0]:
                    err(errors, f"{cid}: timer_in {c.get('timer_in')!r} != {want[0]}")
                if bool(c.get("timer_corner")) != want[3]:
                    err(errors, f"{cid}: timer_corner {c.get('timer_corner')!r} != {want[3]}")
        else:
            if want is not None:
                err(errors, f"{cid}: has a valid timer token but no `timer` in cues")
            if "timer_in" in c or "timer_corner" in c:
                err(errors, f"{cid}: timer_in/timer_corner without timer")
        if LOOSE_RE.search(c.get("script") or ""):
            err(errors, f"{cid}: a timer token reached the voice-over")

        # present view
        if "timer" in c:
            if len(plates) != 1:
                err(errors, f"{cid}: {len(plates)} timer plates in the present view, want 1")
            else:
                shape, secs = plates[0]
                if int(secs) != c["timer"]:
                    err(errors, f"{cid}: data-timer {secs} != {c['timer']}")
                if c.get("timer_corner"):
                    wshape = "corner"
                elif entries[c["timer_in"]]["kind"] == "timer":
                    wshape = "block"
                else:
                    wshape = "inline"
                if shape != wshape:
                    err(errors, f"{cid}: plate shape {shape}, want {wshape}")
        elif plates or 'class="timer-plate' in sec:
            err(errors, f"{cid}: a timer plate on a screen with no timer")
        # a token that is not the live one stays visible as text
        for t in entries:
            if t.get("kind") == "timer" and ("timer" not in c or t["text"] != entries[c["timer_in"]]["text"]):
                if t["text"].replace("&", "&amp;") not in sec:
                    err(errors, f"{cid}: literal token {t['text']!r} is not shown on screen")

        # document view: never a clock, always the quiet words
        if "timer" in c:
            phrase = want[2] if want else None
            if phrase and f"{phrase} timer" not in doc:
                err(errors, f"{cid}: document view lacks {phrase!r} timer")

        # the clock
        words = timing.word_count(c.get("script") or "")
        if "timer" in c and words == 0 and c.get("media") is None:
            if abs(c["est_seconds"] - c["timer"]) > 5e-4:
                err(errors, f"{cid}: est_seconds {c['est_seconds']} != timer {c['timer']} (no voice-over)")
        if "timer" in c and words > 0 and c.get("media") is None and not c.get("stage"):
            w = round(timing.estimate_seconds(words, c["kind"]), 3)
            if abs(c["est_seconds"] - w) > 5e-4:
                err(errors, f"{cid}: est_seconds {c['est_seconds']} counts the timer (words alone give {w})")

    if 'class="timer-plate' in doc or 'role="timer"' in doc:
        err(errors, "document view carries a live timer plate")
    if "data-timer=" in doc:
        err(errors, "document view carries a data-timer clock")
    # a fenced or parenthetical token is literal text, never a plate
    n_plates = len(re.findall(r'<div class="timer-plate|<span class="timer-plate', present))
    n_cues = sum(1 for c in cues if "timer" in c)
    if n_plates != n_cues:
        err(errors, f"present view has {n_plates} timer plates for {n_cues} timer cues")
