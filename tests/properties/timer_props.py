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
  stay literal and start nothing;
- `reveal=timer` (spec: Timer screens, Revealed timers): the cue carries
  `timer_reveal: true` exactly when its plate carries `data-timer-reveal` and
  starts `pending` (hidden); `timer_reveal_first: true` (the timer is written
  above the revealed list, so it takes the first press) exactly when the marker
  says `first`, otherwise `last`; only a cue with a timer can have either; the
  document view never carries the attribute.  What a press does is proved in a
  real browser by tests/browser_reveal_timer.py.
- continued countdowns (`[timer]`, spec: Timer screens, Continued timers): a cue
  with `timer_continues` names an earlier timer cue with no `timer_continues` of
  its own, carries that cue's seconds, its `timer_in` holds the `[timer]` token
  and `timer_corner` follows that token; its plate carries `data-timer-from`
  (the parent's slide index) and is never revealed; the parent's plate carries
  `data-timer-span` (its last continuation's slide index).  The clock: a
  continuation adds nothing for the timer, and the span (parent through its last
  continuation) lasts at least the countdown, plus the parent's own words when
  it is revealed.
"""

from __future__ import annotations

import re

import render
import talkparse
import timing

from .common import err

LOOSE_RE = re.compile(r"\[\s*timer\s*:[^\]]*\]", re.IGNORECASE)
CONT_RE = re.compile(r"\[\s*timer(\s+corner)?\s*\]", re.IGNORECASE)


def _first_cont(entries: list):
    """(index, corner) for the first `[timer]` continuation token, or None."""
    for i, t in enumerate(entries):
        if t.get("kind") == "code":
            continue
        for text in list(t.get("items") or []) + ([t["text"]] if "text" in t else []):
            m = CONT_RE.search(text)
            if m:
                return i, m.group(1) is not None
    return None


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
    by_id = {c["id"]: c for c in cues}
    present = (fx.out / "present" / "index.html").read_text(encoding="utf-8")
    doc = (fx.out / "document" / "index.html").read_text(encoding="utf-8")

    for c in cues:
        cid = c["id"]
        entries = c.get("screen_text") or []
        sec = _section(present, cid)
        plates = re.findall(r'class="timer-plate(?: pending| timer-private)? timer-(\w+)"[^>]*data-timer="(\d+)"', sec)
        m_armed = re.search(r'data-timer-reveal="(first|last)" class="timer-plate pending ', sec)
        armed_attr = m_armed is not None
        want = _first_valid(entries)
        parent = by_id.get(c.get("timer_continues")) if "timer_continues" in c else None
        if "timer_continues" in c:
            got = _first_cont(entries)
            if parent is None or "timer_continues" in parent or parent["ordinal"] >= c["ordinal"]:
                err(errors, f"{cid}: timer_continues {c['timer_continues']!r} is not an earlier timer cue")
            elif c.get("timer") != parent.get("timer"):
                err(errors, f"{cid}: continuation timer {c.get('timer')!r} != parent's {parent.get('timer')!r}")
            if got is None or c.get("timer_in") != got[0] or bool(c.get("timer_corner")) != got[1]:
                err(errors, f"{cid}: continuation timer_in/timer_corner do not follow its [timer] token {got!r}")
            if c.get("timer_reveal"):
                err(errors, f"{cid}: a continuation is never revealed")
            if parent is not None and f'data-timer-from="{parent["ordinal"] - 1}"' not in sec:
                err(errors, f"{cid}: plate lacks data-timer-from for its parent")
            want = (got[0], c.get("timer"), "", got[1]) if got else None
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
        if "timer_reveal" in c:
            if c["timer_reveal"] is not True or "timer" not in c:
                err(errors, f"{cid}: timer_reveal {c['timer_reveal']!r} without a timer or not true")
        if c.get("timer_reveal_first") and not c.get("timer_reveal"):
            err(errors, f"{cid}: timer_reveal_first without timer_reveal")
        if armed_attr and (m_armed.group(1) == "first") != bool(c.get("timer_reveal_first")):
            err(errors, f"{cid}: plate says {m_armed.group(1)!r} but timer_reveal_first is {c.get('timer_reveal_first')!r}")
        if bool(c.get("timer_reveal")) != armed_attr:
            err(errors, f"{cid}: timer_reveal {c.get('timer_reveal')!r} but the plate's hidden-until-press "
                        f"marker is {'present' if armed_attr else 'absent'}")
        # presenter reminder: an armed screen with no [n]/[next] cue gets one line at the
        # END of its notes; one with a cue, or any unarmed screen, gets none
        notes_m = re.search(r'<aside class="notes">(.*?)</aside>', sec, re.DOTALL)
        notes = notes_m.group(1) if notes_m else ""
        want_rem = armed_attr and "next-mark" not in notes
        n_rem = notes.count('class="timer-reminder"')
        if n_rem != (1 if want_rem else 0):
            err(errors, f"{cid}: {n_rem} timer reminders in the notes, want {1 if want_rem else 0}")
        if want_rem and not notes.rstrip().endswith("</p>"):
            err(errors, f"{cid}: timer reminder is not last in the notes")
        if want_rem and f"({render.timer_clock(c['timer'])})" not in notes:
            err(errors, f"{cid}: timer reminder does not show the duration")
        if "timer-reminder" in doc:
            err(errors, "document view carries a timer reminder")
        # a token that is not the live one stays visible as text
        for t in entries:
            if t.get("kind") == "timer" and ("timer" not in c or t["text"] != entries[c["timer_in"]]["text"]):
                if t["text"].replace("&", "&amp;") not in sec:
                    err(errors, f"{cid}: literal token {t['text']!r} is not shown on screen")

        # document view: a timer is the room's clock, never printed
        if "timer" in c and re.search(r"\d timer\b", re.sub(r"<[^>]+>", " ", _section(doc, cid))):
            err(errors, f"{cid}: document view prints a timer line")

        # the clock
        words = timing.word_count(c.get("script") or "")
        span = [x for x in cues if x.get("timer_continues") == cid]
        if span:
            last = max(x["ordinal"] for x in span)
            if f'data-timer-span="{last - 1}"' not in sec:
                err(errors, f"{cid}: parent plate lacks data-timer-span={last - 1}")
            if c.get("media") is None:
                total = sum(x["est_seconds"] for x in cues if c["ordinal"] <= x["ordinal"] <= last)
                need_s = c["timer"] + (words / timing.DEFAULT_WPM * 60 if c.get("timer_reveal") else 0.0)
                if total < need_s - 5e-3:
                    err(errors, f"{cid}: span est {total} under-counts the timer (want at least {need_s})")
            continue
        if "timer_continues" in c:
            if c.get("media") is None and abs(
                    c["est_seconds"] - timing.estimate_seconds(words, c["kind"])) > 5e-4:
                err(errors, f"{cid}: a continuation's est_seconds {c['est_seconds']} counts the timer")
            continue
        if "timer" in c and words == 0 and c.get("media") is None:
            if abs(c["est_seconds"] - c["timer"]) > 5e-4:
                err(errors, f"{cid}: est_seconds {c['est_seconds']} != timer {c['timer']} (no voice-over)")
        if "timer" in c and words > 0 and c.get("media") is None:
            spoken = timing.estimate_seconds(words, c["kind"])
            want = (round(words / timing.DEFAULT_WPM * 60 + c["timer"], 3)
                    if c.get("timer_reveal") else max(spoken, float(c["timer"])))
            if c["est_seconds"] < want - 5e-4:
                err(errors, f"{cid}: est_seconds {c['est_seconds']} under-counts the timer (want at least {want})")

    if 'class="timer-plate' in doc or 'role="timer"' in doc:
        err(errors, "document view carries a live timer plate")
    if "data-timer-reveal" in doc:
        err(errors, "document view carries a data-timer-reveal marker")
    if "data-timer=" in doc:
        err(errors, "document view carries a data-timer clock")
    # a fenced or parenthetical token is literal text, never a plate
    n_plates = len(re.findall(r'<(?:div|span)[^>]*class="timer-plate', present))
    n_cues = sum(1 for c in cues if "timer" in c)
    if n_plates != n_cues:
        err(errors, f"present view has {n_plates} timer plates for {n_cues} timer cues")
