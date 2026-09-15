# Animatic design tokens and themes

Status: E3 baseline (2026-09-05, committed) — A (lecture) and C (workshop)
feel-tested on the roles-demo specimen and L01 and locked for now; swept
2026-09-08 (engine layer row removed, spare slot deleted, placeholder default
decided — see decision log). Open questions below remain live. Docs move when
the deck does: this file is the human spec, the CSS in themes/ is the machine
source. Propose, never lock.

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
  dim=N flag supplies opacity)
- document (paper): `--doc-bg`, `--doc-ink`, `--doc-muted`, `--doc-accent`,
  `--doc-line`, `--doc-callout-bg`
- shared type: `--font-display` (headings, stat), `--font-body` (reading),
  `--font-ui` (lower thirds, credits, placeholders)

No look value lives outside a token or a theme layer.

## Role vocabulary to styles

| Role / block | Present view | Document view |
|---|---|---|
| media shot (full bleed) | `.media-zone` + `.slide-media`, object-fit cover; `fit` = contain on a media-only slide, HERO text (max-size) when the slide carries text; `piece` = the media floats as a framed object (natural size, border + shadow on the image itself, never a container box) | `figure.shot` |
| `kb=in/out` | slow single drift (22 s), reduced-motion off | static |
| `dim=N` | solid `--stage-dim` at opacity N | none |
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
to full-bleed atmosphere here too (Ryan 2026-09-05: atmosphere is the
default in every theme); the framed "piece" look is opt-in per shot.

- stage: `#f2ecdf` / ink `#262019` / accent `#7d5f2e`; dim tint warm dark
  `#241f18`
- character: centered text (the room's difference is the daylight palette
  and sans-leaning UI, not pinned type — Ryan 2026-09-05), no glow on paper,
  full-bleed atmosphere default, lower thirds as paper chips, quotes over
  media sit on a warm paper plate (`--quote-panel-bg` 0.55 alpha; the blur
  carries the legibility)

## Palette decision log

- 2026-09-05 (Ryan + agent): three directions proposed from standing
  principles (warm, civic, curious; CVD-safe; no saturated red/blue pairs):
  A reference room, B green room, C workshop daylight. Ryan: "probably A
  and C, let's feel it out." Starter set = lecture (A), workshop (C),
  spare slot held for B.
- Image consultation 2026-09-05: Ryan's placeholder media (_media/ryan/)
  reads in two families: bright aerial fieldwork (needs scrim discipline
  and text zones) and dark ink-in-water studies (warm vortices on deep
  ink = palette A's own colour story). A sits on the ink images; C frames
  the aerials.
- Corrections from the first live feel-test (2026-09-05): (1) type scale
  was browser-16px-based and read small from a distance — the stage now
  sets an explicit cinematic base (3vh) so em sizes track projection
  height; (2) framed media is NOT a theme default — full-bleed atmosphere
  is the default in both themes, and the floating framed look is the
  opt-in `piece` flag, meant for images shown as objects (e.g. other
  people's work); (3) non-owned images carry credit tags via the existing
  lower / credits roles.
- Motion resolved (2026-09-05, after three failed attempts): Ken Burns
  drift = CSS animation translating the IMAGE itself inside a static
  overflow-hidden lens. The image layer is oversized 130% and centred, so
  its texture always exceeds the clip: edges can never surface and the
  drift is a pure compositor blit. Failed first: scale-based CSS on the
  image (per-frame texture resampling = stutter); failed second: rAF JS
  transform writes (main-thread frame drops); failed third: animating the
  LENS with will-change (the compositor baked the 100% clip into the
  layer texture, exposing edges). Pan amplitude ~±7%/2.5% at 22 s legs
  clears pixel-snapping; CSS compositor animations beat JS rAF for this.
- Pager: reveal.js could not stand in at all in the desktop preview pane
  (remote content is blocked there, and even in browsers the CDN deck is
  one network failure from dead). E3 owns the present view: a small
  inline pager (keyboard, hash, `n` notes panel, `s` presenter window,
  `i` diagnostics dump, swipe, progress), one self-contained HTML file per
  deck plus the presenter page. Media publishes to out/_media with
  relative paths, so a deck is a portable folder.
- Diagnostics panel (`i`, 2026-09-15): same translucent-glass register as the
  notes and hookup panels, monospace, `user-select: text`, and — unlike the
  presentation layers — deliberately interactive, because its whole purpose is
  to be scrolled and copied. It sits outside `.screen-body`, so the
  click-through rule that governs the slide body does not apply to it.
- Feel-test round 2 (2026-09-05, roles-demo + L01 live in Firefox):
  (1) text over full-bleed media is THE common slide — every text role
  (title card, fit hero, stat, quote, list) can take a background via a
  media shot, and role shots stat/lower/credits overlay-merge onto an
  unvoiced media screen (stat joined in E3); (2) legibility kit: dim=N
  scrims, per-slide `text=light|dark` mode (ink text dies on dark ground;
  light glyphs + dark glow are the default ask), and a structural halo
  contract — lecture = `--stage-text-glow` on over-media text, workshop =
  pale paper halo; the shadow should be nearly invisible unless toggled
  (Ryan); (3) quotes over media sit on a frosted plate (`--quote-panel-bg`
  + backdrop blur + 2px edge blur + radius 1.1em) wrapping quote AND
  credit; 32em max width; workshop plate at 0.55 alpha, "the blur carries
  the legibility"; (4) `fit` on a text-carrying media slide = hero type as
  big as the slide allows; media-only `fit` keeps letterbox-contain;
  (5) workshop text stays CENTERED like lecture — the room's character is
  palette + sans UI, not pinned type.
- Media stand-ins (`--media-remap`): unproduced slugs (brief/to-find/
  prompting) can be pointed at real files for style tests and drafts.
  Last in resolution order — real art always wins, so stand-ins
  evaporate when art lands; manifest records `source: standin`.
  remaps/l01-standins.yaml = temporary L01 set (3 stand-ins + 1 real
  video; 10 placeholders remain by design: charts/composites have no
  honest stand-in).
- 2026-09-08 (T04 hygiene sweep): (1) the `engine` layer row is gone from
  the table above — E3 removed reveal.js and the builder inlines exactly
  reset/base/components/theme (`@layer reset, base, components, theme;` in
  render.py); (2) the `spare` third-theme slot is deleted (D9) — direction B
  returns only when a deck actually wants it, never as an empty slot (an
  empty slot in a spec invites an agent to invent a theme); (3) placeholder
  visibility default decided (D10): present ON, document OFF,
  `--show-placeholders` opts a document build in. The look, when shown,
  stays a feel-test question below.

## Add a theme

1. Copy `themes/theme-lecture.css` to `themes/theme-<slug>.css`; retitle.
2. Define all required tokens (both surfaces).
3. Add `<slug>` to `KNOWN_THEMES` in render.py.
4. Add the theme's character rules in the same file (layer theme, so they
   may restyle any component with plain selectors).
5. Palette consultation with Ryan before locking any palette.

## Open questions (feel-test list)

- Stat slides: accent rule under the number works on paper and black; does
  the brass want to be stronger?
- Few-credits vs many-credits column behaviour; real end rolls may want
  section grouping, not a flat list.
- Lower third position and size on 1920x1080 (currently bottom left chip).
- Whether the reveal fade is the right inter-screen motion (vs hard cuts).
- Placeholder look when shown: placeholders now default OUT of document
  builds (D10, 2026-09-08 — present ON, document OFF, `--show-placeholders`
  overrides); the look itself, when a document build opts in, is still a
  feel-test question.
- Duo object side: book covers may read better with the object on the LEFT
  (left-to-right reading); specimen tests object-right only (asked Ryan,
  unanswered).
- Hero-quote plate: a pull quote at `fit` scale on the frosted plate (the
  second "hero" Ryan named; heading heroes are done).
- Backdrop blur over VIDEO is the expensive case (re-blurs per frame);
  a reduced-blur mode behind a flag if quote plates stack on video.
