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

## Add a theme

1. Copy `themes/theme-lecture.css` to `themes/theme-<slug>.css`; retitle.
2. Define all required tokens (both surfaces).
3. Add `<slug>` to `KNOWN_THEMES` in render.py.
4. Add the theme's character rules in the same file (layer theme, so they
   may restyle any component with plain selectors).
5. Try it on `examples/roles-demo`, which exercises every role.
