# Live window capture — `type: live`

**Added 2026-09-15.** A screen whose card declares `type: live` hosts a live
capture of a window on the presenter's machine, started from inside the deck.
The room sees the real thing, in the deck's own frame, and a slide change is
all it takes to show or hide it.

## Why this shape and not an embed

An iframe around the site was the first idea and it is not available: the arena
serves `x-frame-options: SAMEORIGIN` plus a `frame-ancestors` policy, so the
browser refuses the frame. Beyond that, an embed would drag the network into a
deck that has no remote assets by design, and it steals the arrow keys from the
pager.

A live **window** capture solves all three, and it has one property worth the
whole design: capture continues while the captured window is not visible. The
demo window can sit behind the deck or on the second display and still be shown
inside the slide. There is no alt-tab dance and no window juggling: visibility
is a slide change.

## Authoring

One card, one shot.

```yaml
# media/cards.yaml
- slug: arena-live
  status: live
  type: live
  alt: What two assistants say about the same question, live
  poster: media/arena-live-poster.png   # optional; the still the handout prints
  brief: window capture of the arena, started from this slide
```

```
<!-- shot: arena-live layout=piece -->
### The heading can stay

(...)
```

- `poster:` is optional and deck-relative (same rule as every declared path).
  With one, the handout prints the still; without one, the handout says a live
  capture happened there instead of printing a placeholder. Either way the
  document view never pretends to be live.
- `layout=piece` frames the capture as an object (hairline border, soft shadow).
  Without it the capture fills the stage. Both are supported; the piece framing
  reads better when the deck also carries a heading, since the letterbox area
  gives the type somewhere to live.
- `kb=` and `dim=` are ignored on a live screen. Drift and a scrim both fight a
  moving picture.

## The one requirement: a secure context

`getDisplayMedia()` is available only in secure contexts, and the spec forbids
remembering the permission, so the presenter must click every session.

| Where the deck is opened | Capture works |
| --- | --- |
| `file://` (built folder opened from disk) | yes |
| `http://localhost` or `127.0.0.1` | yes |
| `https://` | yes |
| `http://` on a LAN or Tailscale address | **no** |

The built deck is self-contained (one inline script, no fetch, no remote
assets), so opening `present/index.html` straight from the filesystem is a
supported way to present, and the best one for a room with unreliable wifi.
The remaining option is Firefox's `dom.securecontext.allowlist` pref (a
comma-separated host list) — it works, but it relaxes a security preference, so
it is the last resort.

## On the day

- **Arming.** The permission cannot be persisted. Either arm at the top of the
  session (the picker fires once, the capture runs hidden behind whatever slide
  is up, and the browser's sharing indicator sits in the toolbar for the rest of
  the session), or arm at the beat (the picker appears mid-moment, in front of
  the room). Whatever you choose, do it once and say so.
- **Pick a window, never the screen.** Capturing the display that is showing the
  deck gives you a hall of mirrors. The builder excludes the deck's own tab from
  the picker (`selfBrowserSurface: "exclude"`) but it cannot protect you from
  choosing a screen that contains it.
- **A chrome-less target makes a better slide.** A browser app window for the
  site is captured without tabs and without a URL bar; that is what belongs on a
  projector.
- **Wayland** routes the picker through the desktop portal, so the dialog looks
  different from Firefox's own. Test on the machine that will present.
- **Cost.** Window capture costs CPU for as long as it runs. Long sessions with
  the capture live the whole time should be tried once before the day.

## What the builder emits

| View | A `type: live` screen renders as |
| --- | --- |
| `present/` | a capture host: idle state (poster if declared, a start control, a status line that names the remedy when capture is unavailable), then the stream alone once sharing, with a small stop chip |
| `present/presenter.html` | nothing previewed: the speaker window shows the label `live window capture, no preview` for that cue, because a second sink on the stream would pull frames for a thumbnail (`docs/presenter-view.md`) |
| `document/` | the poster as a figure, or an honest note that a live capture happened there |
| `media-manifest.json` | `type: live`, `found: true`, `source: live`, `file: null`, `poster` (published as `_media/<slug>-poster.<ext>`, or null) |

HTML is never byte-diffed, so the live behaviour is pinned by properties
instead: `tests/properties/html_props.py` asserts the host is present in the
present view, that the poster resolves, and that the live surface carries
`muted` and `playsinline` with no native controls (a live stream has nothing to
autoplay until it starts and no end to loop, so the cinematic attribute set
does not apply to it); `manifest_props.py` asserts the file-less shape and the
published poster. The fixture is `tests/fixtures/decks/live-capture/`.

## The hookup panel: one session, or several slides

The permission cannot be remembered, so hooking up is a pre-talk ritual, not a
mid-talk improvisation. Press **`d`** in the present view for the hookup panel:
one row per capture session, showing which slides it feeds, whether it is
hooked, the label of the window the browser actually gave you, and three
controls (`hook up`, `stop`, `go`). `go` jumps to the slide; `d` or `Escape`
closes the panel.

Two other keys sit next to it: **`s`** opens the second-window presenter view and
**`n`** toggles the in-page notes panel (notes used to be `s`; the presenter
window is what reveal.js puts on that key, and it is where the speaker UI belongs
now — `docs/presenter-view.md`). Both are safe on a live deck: the presenter
window labels a live screen rather than previewing it, so arming a capture is
never disturbed by opening the speaker view.

A live host is also self-sufficient: while its slide is up and nothing is hooked
it offers its own "Share a window" control, so a one-demo deck needs no ritual
at all.

### Several demo slides

`live_group` in a card makes hosts share one session:

```yaml
- slug: demo-arena
  type: live
  live_group: demos
- slug: demo-arena-again      # a second slide showing the same window
  type: live
  live_group: demos
```

One picker, one stream, both slides. Two ways to work with several demos:

| Approach | Pickers | What changes between slides |
| --- | --- | --- |
| One group, one window; switch tabs or scroll inside it | 1 | your own window's content |
| One group per window | one each | the whole captured window |

The first is cheaper and simpler, and it is the reason groups exist. Its one
cost: a normal browser window carries its tab strip and URL bar into the
capture, whereas a chrome-less app window (`chromium --app=<url>`) captures
clean but has no tabs. Pick per deck: chrome-less windows and one session per
demo, or one tabbed window and one session for all of them.

## Frame cost is gated on visibility

There is no polling anywhere. One capture session is one live stream, and the
lever is whether a `<video>` is *attached* to it: frames are pulled only while
something is consuming them. So every host detaches its sink when its slide is
not active and re-attaches on arrival, while the session (and the permission)
stays alive. Re-attaching is instant and never re-prompts.

That is also why a deck with several demo slides costs no more than a deck with
one: at any moment exactly one host is attached, and the rest are `armed`
(hooked, no sink). `data-live-state` carries the full state:

| State | Means | What is on the slide |
| --- | --- | --- |
| `idle` | no session | the poster if any, the hint, the "Share a window" control |
| `armed` | session, slide not up | nothing; the panel reports it |
| `live` | session, attached | the capture, plus a small stop chip |
| `stalled` | session, track not delivering | the hint, the control (usable again), the stop chip, and a status line |
| `unavailable` | no capture API here | the poster if any, and a status line naming the remedy |

### When a capture dies

A capture stops two ways and they need different handling, which cost a round
trip to learn:

- **`ended`** is final: the presenter hit stop, or the platform ends the track
  when the captured window closes. The session is torn down and the host returns
  to `idle` with the control back.
- **`mute`** is Firefox's response to a captured window going away, and the
  track can recover. Tearing the session down would throw away a live
  permission, so a muted track surfaces `stalled` instead: the control comes
  back, the session is kept, and `unmute` re-attaches with nothing to click.

The bug that made this explicit: only `ended` was wired, so closing the shared
window left the host in `live` with a dead track, which hides the idle block.
The window correctly stopped showing, and the "Share a window" control was
simply gone. Hooking again now also tears down whatever was there first, so a
stalled session cannot linger or double.

## Verification

`tools/check-live-js.js` runs the present view's capture module against a stub
DOM in node and asserts the behaviour that cannot be clicked in CI: one session
per key, hosts sharing a group sharing one stream, the sink following the
active slide, no second prompt on a slide change, teardown stopping every host
in a group, both ways a capture dies (`ended` and `mute`), and the panel's rows
and hook markers.

```
python3 -c "import render; open('/tmp/live.js','w').write(render.LIVE_JS)"
node tools/check-live-js.js /tmp/live.js
```

### What the harness cannot see, and how to check it instead

The harness asserts state, never pixels or layout. Two classes of bug live
outside it, and both have bitten:

- **A state with no CSS rule showing the right block.** Adding a state means
  adding its stylesheet rule; nothing automated will notice if you forget.
- **An interactive control that is covered.** The text layer (`.screen-body`)
  sits above the media zone and is click-through on purpose, because a live
  capture's controls live underneath it. Verify this by hit-testing, not by
  calling `.click()`: a synthetic click dispatches straight to the element and
  will happily "pass" while every real click lands on the layer above.

With the deck served locally (`python3 -m http.server`), point a browser at
`present/index.html#11` and check what is actually on top:

```js
window.animatic.go(10);                       // the live slide
const host = document.querySelector('[data-live-slug="w01-arena-live"]');
const b = host.querySelector('.live-start').getBoundingClientRect();
document.elementFromPoint(b.left + b.width / 2, b.top + b.height / 2);
// want: BUTTON.live-start, inside the host.
// not: DIV.screen-body, which means the text layer is eating the input.
```

Then click it for real (mouse events through the input pipeline, or by hand) and
watch `data-live-state` go `idle` → `live`. `html_props` pins the click-through
rule for any deck that has a live screen, so a theme edit cannot quietly undo it.

## Limits, stated plainly

- One capture per host, no audio, and no recording of the stream by the builder.
  A screen recording of the session does capture it, because it is on screen.
- The capture is a runtime artifact: it does not exist in any output file, so a
  deck's built folder is still portable and offline.
- Nothing about the deck's determinism changes: the built HTML is identical
  whatever the presenter later captures.
