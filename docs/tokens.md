# Styling: design tokens and themes

This file is the human reference for how animatic looks; the CSS in `themes/`
is the machine source. Two themes ship: `lecture` (default) and `workshop`.

## The layer contract

Every view inlines the same four stylesheet layers, in order:

| Layer | File | Job |
|---|---|---|
| reset | themes/reset.css | Box model, UA margins, media defaults. No look. |
| base | themes/base.css | Element defaults, font stacks, view scopes (`body.view-present` / `body.view-document`). Everything reads tokens. |
| components | themes/components.css | The animatic kit: role styles and both view surfaces. Also token-only, theme-agnostic. |
| theme | themes/theme-<slug>.css | Tokens + character. Last layer: restyles any component with plain rules, no specificity war, no `!important`. |

Why layers: order-of-source no longer beats intent, and a theme is a
swap, not a patch. Switch the theme file and the whole deck re-skins.

The builder selects the theme from frontmatter (`theme: lecture`). Unknown
or `TBD` themes fall back to `lecture` with one build warning. See
render.py `resolve_theme()`.

## Required tokens

Themes must define every token in base.css `:root` (the fallback block is a
reminder, not a theme). Two token groups, one per surface:

- stage (present view, 1920x1080 projection canvas): `--stage-bg`,
  `--stage-ink`, `--stage-muted`, `--stage-accent`,
  `--stage-accent-contrast`, `--stage-overlay-bg` (chip/lower backing),
  `--quote-panel-bg`, `--quote-panel-shadow` (frosted plate behind quotes
  over media), `--stage-text-glow`, `--stage-dim` (solid scrim tint; the
  dim=N flag supplies opacity), `--stage-alert` (a countdown at zero and in
  overtime: lecture ember `#f0884a`, workshop deep ember `#b23c14`)
- document (paper): `--doc-bg`, `--doc-ink`, `--doc-muted`, `--doc-accent`,
  `--doc-line`, `--doc-callout-bg`
- shared type: `--font-display` (headings, stat), `--font-body` (reading),
  `--font-ui` (lower thirds, credits, placeholders), `--font-mono` (fenced
  code, diagnostics)

No look value lives outside a token or a theme layer.

## Role vocabulary to styles

| Role / block | Present view | Document view |
|---|---|---|
| media shot (full bleed) | `.media-zone` + `.slide-media`, object-fit cover; `fit` = contain on a media-only slide, HERO text (max-size) when the slide carries text; `piece` = the media floats as a framed object (natural size, border + shadow on the image itself, never a container box) | `figure.shot` |
| `kb=in/out` | slow single drift (22 s), reduced-motion off | static |
| `dim=N` | solid `--stage-dim` at opacity N | none |
| fenced code | `.code-block` `<pre>`: `--font-mono`, left-aligned, a plate from `--quote-panel-bg` + `--quote-panel-shadow` with a hairline edge and an accent rule; shrinks to 75%, `fit=hero` grows it | `pre.code-block`: tinted `--doc-callout-bg` panel, accent rule, wraps |
| timer token (`[Timer: 8:00]`) | `.timer-plate`: `--font-display` digits in fixed cells (block: large in the flow; inline: at its text's size; `corner`: a plate from `--stage-bg` at 90%, hairline edge, `--quote-panel-shadow`, lower right); `--stage-alert` at zero and overtime | one quiet line, `8 minute timer` (`.timer-note`, `--doc-muted`) |
| heading card | `.slide-title`, display serif | `.screen-heading` |
| quote card | centered pull quote with accent rule | bordered blockquote |
| `stat` | one huge line, accent rule under; overlay-merges onto an unvoiced media shot like lower/credits | `.stat-callout` box |
| `lower` | chip, bottom of frame, transient | figcaption |
| `credits` overlay (media screen) | `.credits-line`, corner, persistent | figcaption |
| credits screen (own screen) | `.credits-screen`: title + entries; 3 balanced columns when many (>= 3), centered when few | `.doc-credits` block |
| `black` beat | full-stage black, deliberate | nothing (no prose) |
| placeholders | slug + status + reason (builder transparency) | same, subdued |

## Themes

### lecture — the reference room (default)

Lamp light in the dark. Warm near-black stage, warm ink, brass accent, serif
display. The dark ink-in-water studies and deep aerial shots live here.

- stage: `#12100c` / ink `#f2ecdf` / muted `#a79e8e` / accent `#d8a95c`
- paper (doc): `#f7f2e8` / ink `#26211a` / accent `#8a6a2f`
- character: text glows over media, stat carries a brass rule, lower thirds
  get an accent edge

### workshop — daylight room

The lights are on and the words matter. Warm paper stage, ink text,
olive-clay accent, sans-leaning UI for text-forward cards. Media defaults
to full-bleed atmosphere here too (atmosphere is the default in every theme); the framed "piece" look is opt-in per shot.

- stage: `#f2ecdf` / ink `#262019` / accent `#7d5f2e`; dim tint warm dark
  `#241f18`
- character: centered text (the room's difference is the daylight palette
  and sans-leaning UI, not pinned type), no glow on paper,
  full-bleed atmosphere default, lower thirds as paper chips, quotes over
  media sit on a warm paper plate (`--quote-panel-bg` 0.55 alpha; the blur
  carries the legibility)

## Design rationale

Decisions behind the look, kept because they explain behaviour that would
otherwise look arbitrary.

- **Palettes.** Warm, civic, curious; colour-vision-safe; no saturated red/blue
  pairs. `lecture` sits on dark ink-in-water and night imagery; `workshop`
  frames bright aerial photography.
- **Type scale.** The stage sets an explicit cinematic base (4.8vh) so `em`
  sizes track projection height; a browser-16px base reads small from the back
  of a room. `fit=hero` slides keep 3.6vh (`--hero-base`) and plain titles keep
  a fixed size (`--title-k`), so only body text scales with the base.
- **Media default.** Full-bleed atmosphere is the default in both themes. The
  floating framed look is the opt-in `piece` flag, for images shown as objects
  (other people's work, book covers). Media that is not yours carries credit
  tags via the `lower` / `credits` roles.
- **Text over media is the common slide.** Every text role (title card, fit
  hero, stat, quote, list) can sit on a media shot, and `stat`, `lower` and
  `credits` overlay-merge onto an unvoiced media screen. The legibility kit is
  `dim=N` scrims, per-slide `text=light|dark` (ink text dies on a dark ground;
  light glyphs with a dark glow are the default), and a structural halo:
  `lecture` uses `--stage-text-glow`, `workshop` a pale paper halo. The shadow
  should be nearly invisible unless toggled.
- **Quote plates.** Quotes over media sit on a frosted plate
  (`--quote-panel-bg`, backdrop blur, 2px edge blur, 1.1em radius, 32em max
  width) wrapping quote and credit. The workshop plate is 0.55 alpha; the blur
  carries the legibility.
- **`fit` on text.** On a text-carrying media slide `fit` means hero type as
  big as the slide allows; media-only `fit` keeps letterbox-contain. Text stays
  centred in both themes: the difference between rooms is palette and UI
  type, not pinned layout.
- **Ken Burns drift.** A CSS animation translates the image itself inside a
  static overflow-hidden lens. The image layer is oversized 130% and centred,
  so its texture always exceeds the clip and edges never surface; the drift is
  a pure compositor blit. Scaling the image (per-frame resampling), driving it
  with requestAnimationFrame (main-thread drops) and animating the lens with
  `will-change` (the compositor bakes the clip into the texture and exposes
  edges) all failed. Amplitude is about ±7% / 2.5% on 22 s legs.
- **Pager.** The present view is one self-contained HTML file per deck (plus
  the presenter page) with a small inline pager: keyboard, hash, `n` notes
  panel, `s` presenter window, `i` diagnostics dump, swipe, progress. No CDN,
  so a deck is not one network failure from dead. Media publishes to
  `out/_media` with relative paths, so a deck is a portable folder.
- **Diagnostics panel (`i`).** Same translucent-glass register as the notes
  panel, monospace, `user-select: text`, and deliberately interactive: its job
  is to be scrolled and copied. It sits outside `.screen-body`, so the
  click-through rule for the slide body does not apply.
- **Presenter layout (`s`).** A priority order, not fixed boxes: current pane
  2fr against next-up 1fr, current notes the largest type in the window, the
  preview first to give up space, scrolling last (the `fitNotes()` ladder:
  natural, two columns, solo). Contract and probe: `docs/presenter-view.md`.
- **Media stand-ins.** `--media-remap` points unproduced slugs at real files
  for style tests and drafts. It is last in resolution order, so real art
  always wins and stand-ins evaporate when art lands; the manifest records
  `source: standin`. Charts and composites have no honest stand-in and stay
  placeholders.
- **Placeholders.** Shown in the present view, hidden in document builds;
  `--show-placeholders` opts a document build in.

## Add a theme

1. Copy `themes/theme-lecture.css` to `themes/theme-<slug>.css`; retitle.
2. Define all required tokens (both surfaces).
3. Add `<slug>` to `KNOWN_THEMES` in render.py.
4. Add the theme's character rules in the same file (layer theme, so they
   may restyle any component with plain selectors).
5. Try it on `examples/roles-demo`, which exercises every role.

## Open questions

- Stat slides: does the brass accent rule want to be stronger?
- Credits: real end rolls may want section grouping, not a flat list.
- Lower third position and size at 1920x1080 (currently a bottom-left chip).
- Whether the reveal fade is the right inter-screen motion (vs hard cuts).
- Duo layout: book covers may read better with the object on the left.
- Hero-quote plate: a pull quote at `fit` scale on the frosted plate.
- Backdrop blur over video re-blurs per frame; a reduced-blur mode may be
  needed if quote plates stack on video.
