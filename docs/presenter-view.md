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
| deck | arrows / space / PageUp / PageDown / Home / End to move, `s` presenter window, `n` in-page notes, `d` demo hookup panel, `Escape` closes a panel |
| presenter window | arrows / space to move the deck, `s` closes the window |

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
  `window.animatic.onChange`. The presenter posts exactly two things back: a
  `ready` handshake on load (so a manual reload re-syncs with nothing to click)
  and navigation requests from its own buttons and arrow keys.

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
python3 -m http.server 8788 --bind 127.0.0.1     # from the built folder
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

## Limits, stated plainly

- One publisher, one subscriber: the deck owns the state. The presenter shows
  what the deck last sent, which is exactly what is on the projection.
- The popup window's own name is fixed (`animatic-presenter`), so a second
  instance reuses that window rather than opening a third.
- The presenter does not touch the projection, the capture, or the audio: it
  reads. Nothing about the built deck's determinism changes, and no CSS token was
  added (the layout reuses the stage/document tokens every theme already sets).
