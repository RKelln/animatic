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
| `document/` | the poster as a figure, or an honest note that a live capture happened there |
| `media-manifest.json` | `type: live`, `found: true`, `source: live`, `file: null`, `poster` (published as `_media/<slug>-poster.<ext>`, or null) |

HTML is never byte-diffed, so the live behaviour is pinned by properties
instead: `tests/properties/html_props.py` asserts the host is present in the
present view, that the poster resolves, and that the live surface carries
`muted` and `playsinline` with no native controls (a live stream has nothing to
autoplay until it starts and no end to loop, so the cinematic attribute set
does not apply to it); `manifest_props.py` asserts the file-less shape and the
published poster. The fixture is `tests/fixtures/decks/live-capture/`.

## Limits, stated plainly

- One capture per host, no audio, and no recording of the stream by the builder.
  A screen recording of the session does capture it, because it is on screen.
- The capture is a runtime artifact: it does not exist in any output file, so a
  deck's built folder is still portable and offline.
- Nothing about the deck's determinism changes: the built HTML is identical
  whatever the presenter later captures.
