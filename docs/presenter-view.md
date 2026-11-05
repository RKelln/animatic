# Presenter view — the second window

**Added 2026-09-15.** Pressing **`s`** in the present view opens a SECOND
window holding the speaker UI: the current cue id, movement, ordinal of N, the
full VO script and stage notes, the next cue's title and notes, a wall clock,
elapsed time, and a preview of the current and next screen. Pressing `s` again
(or closing the window) closes it, and the in-page notes panel moved to **`n`**
for the one-screen room.

Animatic replaced reveal.js with its own pager (`docs/engine-decision.md` §1,
superseded by §6), so reveal's notes plugin behaviour was never rebuilt. This is
that missing piece, in reveal's shape: two windows, the speaker UI in the
second.

| Surface | Keys |
| --- | --- |
| deck | arrows / space / PageUp / PageDown / Home / End to move, `w` re-sends the latest waypoint (a publishing build only), `s` presenter window, `n` in-page notes, `d` demo hookup panel, `Escape` closes a panel (then, after a quick-select jump, returns) |
| presenter window | arrows / space to move the deck, `w` re-sends the latest waypoint (a deck built with `ANIMATIC_WAYPOINT_TOKEN` only: see below), `/` quick select (see below), `Escape` returns from a quick-select jump, `f` (or the ⇅ button) puts the notes above the slide image instead of below, remembered per browser, `[` / `]` (or the A− / A+ buttons) shrink / grow the current screen's notes text, also remembered, `s` closes the window, `t` (or the restart button) restarts elapsed time and every `[Timer]` |
| timer screens (either window) | `p` pause / resume, `0` reset and run, `+` / `=` add a minute, `-` take a minute off (spec: Timer screens) |

## Quick select

A deck built with a shelf (`quick_sections`, `docs/quick-select.md`) adds a search to
this window. `/` opens it and **swallows every key while open**: its keydown handler is
registered in the capture phase and stops the event before the handlers that own `s`,
`t`, `p`, `f`, `0`, `r`, `[`, `]` and the arrows, so typing a word cannot close the
window, restart the clock or touch a timer. Up / Down / Enter choose, `Esc` closes it.

It stays inside the `file://` rule above. Everything it needs from the deck is a message
with a window handle, never a shared channel:

| direction | message | meaning |
| --- | --- | --- |
| presenter to deck | `animatic-jump` `{index}` | go to any slide, fully revealed; the first jump saves `{index, step}` |
| presenter to deck | `animatic-return` | go back to the saved slide and step, then forget it |
| presenter to deck | `animatic-preview-request` `{index, rid}` | send me a clone of that slide; nothing navigates |
| deck to presenter | `animatic-preview` `{index, rid, preview}` | the same clone `animatic-state` carries for next-up (a video is a still, a live screen has none) |

The deck keeps the search index out of the runtime message: it is in the build-time cue
index (`title`, `st` the screen text, `sc` the script, and `sec` / `sec_title` /
`sec_kw` for a section's screens; never the stage notes). `animatic-state` gains `count`
(the talk's own screen count, not the shelf), `hi` (the last index paging reaches from
here), `jumped`, `returnTo` and `move` (`"jump"`, `"return"` or `"nav"`, so a later
consumer can tell a jump from advancing). On a shelf screen the header shows the section
title in place of "n / m", and a status line, `Quick: <title> · Esc returns to <n>`,
shows while the deck is away from the talk. The projector shows neither.

## Waypoints

A deck built with `ANIMATIC_WAYPOINT_TOKEN` (docs/waypoints.md) publishes a word as the
talk reaches marked slides, and this window shows the result on its own line under the
header, `Waypoint: expanding ✓ 7:04pm`, or `Waypoint: expanding ✗ not sent, w to retry`
(and `… sending` while a request is out, `none yet` before the first word). The deck owns
the publishing, and the token never leaves `present/index.html`: this page learns the
state through the existing `animatic-state` message (a `waypoint` object, `null` when the
build is inert) and asks for a re-send with `animatic-waypoint-resend`, posted by `w`.
`w` does nothing in an inert build, and the status line is not even in the page. While
the quick search is open it swallows `w` with every other key, like the rest.

## Why two windows and not a bigger panel

Notes in the same window are notes on the projector. The in-page panel is still
there (`n`) because one-screen rooms exist: a laptop on a table, no second
display, nothing to hide the notes from. Anyone with a second display gets the
speaker UI on it instead.

## The constraint that shapes the design: `file://`

Opening `present/index.html` from disk is the recommended way to present
(`docs/live-capture.md`), and it is what rules out the obvious plumbing:

- A `file://` document has an **opaque origin**, and every file gets its own. Two
  windows over the same folder are therefore NOT same-origin, so
  `BroadcastChannel` and `localStorage` never connect, and the presenter cannot
  reach into the deck's DOM.
- `postMessage` is origin-agnostic by design, so it works anyway. `event.origin`
  is the string `"null"` for an opaque origin and is useless as a check; the
  **window handle** is what identifies the peer (`window.open` returns it, and
  `event.source` carries it back).
- Because the deck cannot read the presenter either, the split is one-way: the
  deck is the single source of truth and pushes state on every
  `window.animatic.onChange`. The presenter only posts requests back: a `ready`
  handshake on load (so a manual reload re-syncs with nothing to click), navigation
  from its own buttons and arrow keys, and the requests for timers, live capture,
  quick select and waypoints described in their own sections.

The handshake is required right after `window.open()` too: the presenter's
script may not have run yet when the deck opens it, so the deck pushes again
when `ready` arrives. Nothing is polled.

## Where the facts live

The presenter page is emitted by the builder (`present/presenter.html`), and it
carries a **build-time cue index**: id, ordinal, movement, movement label, kind,
title and a `live` flag per cue, from the same parse as `cues.json`. The runtime
message carries only what only the deck has: the position, the VO script and
stage notes for the current and next cue (read from the `<aside class="notes">`
markup the deck already renders), and the two previews.

The notes markup is the deck's, so the presenter window shows whatever the
notes hold: his voice-over, the payloads he reads off (a `stat`, a
`paraphrase`), and the screen's text that follows his words — a list, a quote
with its credit, a code block — copied in as the **reading copy** of the slide,
so he can read the slide without looking at it (spec: Text — The reading
copy). The deck's own notes panel (`n`) shows the same notes. A list or a code
block travels with its wrapper: the presenter window renders the bullets and
the code as blocks, not as bare rows of `<li>`s.

That split is not decoration. It is what makes the interesting rule checkable
without a browser: **a `type: live` screen is marked preview-less before
anything runs**, so no second sink can ever attach to a capture stream for a
thumbnail. `tests/properties/html_props.py` asserts the index mirrors
`cues.json` cue for cue, live flag included, and that the presenter renders its
no-preview label from that flag.

## Previews

A preview is a **clone of the slide the deck already renders**, pushed as HTML.
`presenter.html` sits beside `index.html`, so every relative `../_media/...`
source resolves identically and one theme styles both. What the clone is not:

| Screen | Preview |
| --- | --- |
| image | the image, drift included (Ken Burns is CSS, and it restarts on insert) |
| video | a **still**: the first frame, paused. A preview is a look, not a second decoder on the talk machine |
| `type: live` | a plain label, `live window capture, no preview`. A live window has nothing to preview, and a second sink attached to the stream would pull frames for a thumbnail |
| unresolved slug | its placeholder box, exactly as the deck shows it (slug, type, status, reason) |
| end of deck | `end of deck` |

Cloned buttons and videos are taken out of the tab order and made
click-through, so a preview can never be operated by accident.

## The layout contract, and the probe that checks it

The window exists to be READ FROM, so the layout has a priority order rather
than a set of fixed boxes:

1. **The current pane is two thirds, next-up one third.** That split is what
   makes the current screen obvious at a glance.
2. **The current screen's notes are the largest type in the window** (1.12rem
   against next-up's 0.88rem, on a 0.72rem label scale). A presenter should not
   be squinting at the thing they are speaking from.
3. **The preview gives up its space first.** It starts at a third of the
   viewport, shrinks as the notes need room, stops at a 12vh thumbnail, and next
   -up's preview is capped to whatever the current one actually ended up at, so
   the secondary screen can never read bigger than the primary one.
4. **Scrolling is the last resort.** The fit ladder in `fitNotes()` runs on
   every arrival: natural flow, then the current notes in two columns, then
   `solo` — the current pane takes the whole window and next-up steps aside. Only
   a screen whose notes defeat all three scrolls, and the probe reports the
   pixels when one does.

`tools/presenter-probe.html` automates the checks, because this class of bug is
invisible to `tests/run.py` (state, never pixels) and hand-driving CDP for every
layout change is a five-step incantation nobody repeats:

```bash
python3 tools/presenter-probe.py --deck out-w01      # serves, prints the URL
python3 tools/presenter-probe.py --deck out-w01 --sizes 1280x800,1920x1080 --open
```

It drives the real presenter page in an iframe and hands it a constructed state
through `window.presenter.apply()` — the same function a live deck push calls,
so the fit ladder runs exactly as it would in a talk. Content comes from the
deck: its longest-notes screen, the median, the shortest, and the live screen.
It reports pass/warn/fail per case per viewport, prints the JSON to the console,
and exposes `window.presenterProbe.results`.

Measured on W01 (2026-09-15, after the 2fr/1fr split and the ladder landed): 6
pass, 2 warn, 0 fail. The warns are the deck's own worst screen — cue 011, 3300
characters of notes — which needs the `solo` rung at 800px tall and still
overflows by 180px there, while the same screen fits in two columns at 1080p.
That is a fact about how long that screen's notes are rather than a layout
defect: no readable font size makes 3300 characters fit a small window. The
probe reports it with the pixels so the decision is visible.

**TODO: `warm (file://)` in `tests/browser_quick_select.py` failed once in about 12 runs on
2026-11-05, right after several browser tests in a row, and passed the rest. Likely timing;
the failing check wasn't captured. Print it next time it fails.**

**TODO: update the probe's live-control expectations.** Its `live control: stalled`
and `live control: idle` cases fail on every deck with a live screen. They still expect
what was true in September: a stalled capture offers Stop first, and an idle one offers
no button. Share and Stop moved to the presenter window on 2026-10-27 (`35d37ae`), so
the page now offers `Share again` and `Share a window`, on purpose. The expectations
are stale; the page is right. Fix them in `tools/presenter-probe.html`, around
`wantsButton`.

It must be **served, not opened from disk**: a `file://` page cannot script an
iframe of another `file://` page (opaque origins), and scripting the frame is
the entire method.

What it does not do: press `s`, so the popup path and the two-window handshake
are still hand-verified; and it cannot judge taste — it reports measurements,
and a warn is a question for a person, not a verdict.

## When the browser blocks the popup

`window.open()` needs a user gesture. A keypress is one, so the ordinary case
just works, but a browser that blocks pop-ups outright (or a deck inside a
sandbox that forbids them) returns `null`. The deck then says so on its own
screen, bottom centre: **"The presenter window was blocked. Allow pop-ups for
this page, then press s again."** `.deck-status` is the element, silent unless a
module has something to say.

## Verification

`html_props` covers the static half: the presenter page is emitted for every
deck, carries no remote asset and no machine-local path, its cue index mirrors
`cues.json` (ids in order, ordinal, movement, movement label, kind, title, live),
the no-preview label is present and wired to the live flag, and the deck carries
its status line plus the moved `n` binding.

The layout half needs a real engine, because a state-level harness asserts state
and never pixels:

```bash
python3 /path/to/animatic/tools/serve-deck.py --port 8788 --directory .   # from the built folder (Range-capable)
```

Then, with the deck open: press `s` **for real** (CDP `Input.dispatchKeyEvent`,
or by hand), confirm the second window exists, advance the deck, and read the
presenter's own DOM. A synthetic `.click()` or `dispatchEvent` proves nothing
here (see "What the harness cannot see" in `docs/live-capture.md`).

Two real-engine bugs have already been caught this way, and both are now pinned
by `html_props`:

- **A note paragraph carrying `class="stage"`** matched the present view's fixed,
  full-viewport `.stage` container, so it left the notes panel and covered the
  whole slide. In the presenter it sat on top of the header and swallowed the
  next button: a hit test at the button's centre returned the paragraph. Stage
  notes are `stage-note` now, and the property suite refuses `<p class="stage">`.
- **A preview box as a shrinkable flex item** lost its 16:9 aspect ratio when a
  pane's notes ran long, so the two previews came out different heights and the
  slide inside was squashed. `.preview { flex: 0 0 auto }` is the fix; measure
  the two boxes and they must match.

## The timer readout

A screen with a `[Timer: ...]` token (spec: Timer screens) shows its countdown in the
presenter header, beside the deck name: large digits, `paused` or `over time`, and the
keys. The deck owns the timer and pushes `timer: {mode, endAt, left, duration}` in the
usual state message on every change (arrival, pause, reset, +/- a minute); the presenter
repaints four times a second from the same wall clock, so the readout stays live between
pushes. `p`, `0`, `+`, `-` in the presenter window post `animatic-timer` requests to the
deck, which applies them to the current screen. The preview thumbnails show the plate at
its full duration: a preview never runs a timer.

`t` (or the restart button beside `elapsed`) restarts the talk clock: elapsed goes back to
0:00 and every `[Timer: ...]` in the deck is reset to unstarted, with the current screen's
timer starting over. The deck owns `startedAt`, so a presenter reload keeps the new zero.

## Limits, stated plainly

- One publisher, one subscriber: the deck owns the state. The presenter shows
  what the deck last sent, which is exactly what is on the projection.
- The popup window's own name is fixed (`animatic-presenter`), so a second
  instance reuses that window rather than opening a third.
- The presenter does not touch the projection, the capture, or the audio: it
  reads. Nothing about the built deck's determinism changes, and no CSS token was
  added (the layout reuses the stage/document tokens every theme already sets).

## NEXT marks

Write `[next]` (or `[n]`, any case) in a spoken paragraph where you press next, or alone on
its own line (a lone mark also ends the paragraph, so the text after it starts a new one). The parser takes the token out of the text and keeps only its position
(`Block.nexts`), so timing, captions, `cues.json`, the document view and the handout never
see it. The notes panel and the presenter window show an amber `▶ NEXT` pill at that spot
(`.next-mark`). It follows the same bracket convention as `[Timer: ...]`. `-->` was
rejected: arrows turn up in spoken text ("input --> output"), and `-->` also closes an HTML
comment. The marks track the stepping: pressed ones fade and strike through, the next one is solid and glowing, later ones stay hollow (the deck pushes `pressesDone` in its state message). Limits: bold or italic that spans a mark loses its styling in the notes.

Check 40 (warning) compares a screen's mark count with the next-presses that stay on it:
stepped-image frames and `reveal=list` items, less the one showing on arrival. A screen
with marks and nothing that steps warns too.

## Share and Stop follow the presenter window

While the presenter window is open, a live screen's **Share a window** and
**Stop** buttons are hidden on the slide (`body.presenter-open`, set by the deck
from the window handle) and sit in the presenter panel instead, so a dropped
capture is fixed from the laptop, not the projected slide. Close the window and
the slide's buttons come back. The stream itself is always on the slide.

`getDisplayMedia` needs a click in the document that calls it, so the
**presenter window does the capture** and sends it to the deck over a local
`RTCPeerConnection` with no ICE servers: offer out
(`animatic-live-offer`), answer back (`animatic-live-answer`), both over
`postMessage`. The deck adopts the stream as the session for that screen's
group, same as a capture it made itself. Consequences: closing the presenter
window ends a share it started (the deck falls back to the idle state with its
buttons back); if the link cannot form within 10 s the panel says so and the
slide button is the fallback. Verified in headless Chromium with a canvas
stand-in for the picker; the real picker (and Wayland's portal) is still a
one-time check on the presenting machine.
