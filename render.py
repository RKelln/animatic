"""render.py — one parse model, three outputs.

- PRESENT view : one self-contained HTML file per deck (no external engine;
  the pager is a small inline script).  One <section> per screen on a
  .stage; VO + stage directions go to the speaker-notes asides ('s' shows
  them); on-screen objects (media, title, stat, lower, credits, quotes,
  lists) render as the slide body.  All look lives in themes/
  (layer reset > base > components > theme) and every value comes from the
  selected theme's tokens.
- DOCUMENT view: a self-contained static HTML handout.  The VO prose IS the
  document (the format's answer to "the handout is your notes"); shots become
  figures, stat cards become callouts, card headings become subheadings.
  Same parse, no duplicated authoring.  Print-to-PDF via @media print CSS.
- CUES: ordered slide-id -> script JSON for the future controller.
- MEDIA MANIFEST: slug resolution audit (what resolved where, what is a
  placeholder and why).

Themes: the `theme:` frontmatter field selects themes/<slug>.css
(theme-<slug>.css on disk).  Unknown / TBD themes fall back to `lecture`
with a warning.  See docs/tokens.md for the token set and layer contract.

Deterministic: no timestamps, no set iteration, stable ordering everywhere.
"""

from __future__ import annotations

import html
import json
from pathlib import Path

from talkparse import (
    BLACK_ROLE,
    Block,
    Screen,
    Talk,
    inline_md,
    plain_md,
    slugify,
)
from mediaresolve import MediaResolver, MediaRef

THEMES_DIR = Path(__file__).resolve().parent / "themes"
KNOWN_THEMES = ("lecture", "workshop")
DEFAULT_THEME = "lecture"

LAYER_ORDER = "@layer reset, base, components, theme;"


# ---------------------------------------------------------------------------
# Theme loading (cascade layers, see docs/tokens.md)
# ---------------------------------------------------------------------------


def resolve_theme(talk: Talk) -> str:
    """Resolve the deck's theme: frontmatter theme: -> known slug.

    Idempotent per Talk: the resolved slug is cached on talk.meta
    ('_theme').  Unknown or placeholder themes fall back to the default and
    warn once.
    """
    cached = talk.meta.get("_theme")
    if cached:
        return str(cached)
    raw = str(talk.meta.get("theme", "") or "").strip()
    slug = slugify(raw)
    if slug in KNOWN_THEMES:
        resolved = slug
    else:
        resolved = DEFAULT_THEME
        if raw and raw not in ("tbd", "none", ""):
            talk.warnings.append(
                f"theme: unknown or pending theme {raw!r}; using {resolved!r} "
                f"(known: {', '.join(KNOWN_THEMES)})"
            )
    talk.meta["_theme"] = resolved
    return resolved


def theme_css_files(theme: str) -> list[str]:
    """Ordered stylesheet names for one theme (shared by both views)."""
    return ["reset.css", "base.css", "components.css", f"theme-{theme}.css"]


def load_theme_css(theme: str) -> str:
    """Concatenated layer CSS for one theme (engine import emitted separately)."""
    parts = []
    for name in theme_css_files(theme):
        path = THEMES_DIR / name
        parts.append(path.read_text(encoding="utf-8"))
    return "\n".join(parts)


def theme_style_blocks(theme: str) -> str:
    """Full <style> content for a view: layer order, then the four theme
    files (reset / base / components / theme) in layer order."""
    return f"<style>\n{LAYER_ORDER}\n{load_theme_css(theme)}\n</style>"


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def deck_slug(talk: Talk) -> str:
    raw = str(talk.meta.get("slug", "") or Path(talk.source).stem)
    return slugify(raw)


def screen_kind(screen: Screen) -> str:
    """Primary kind of a screen: black | media | stat | lower | credits | card."""
    if any(s.role == BLACK_ROLE for s in screen.shots):
        return "black"
    if screen.media_shot is not None:
        return "media"
    kinds = [b.kind for b in screen.blocks]
    for k in ("stat", "lower", "credits"):
        if k in kinds:
            return k
    return "card"


def screen_title(screen: Screen) -> str:
    h = screen.first_heading
    return h.text if h else ""


def vo_paragraphs(screen: Screen) -> list[Block]:
    return [b for b in screen.blocks if b.kind == "vo" and b.text.strip()]


def stage_of(screen: Screen) -> list:
    out = []
    for b in screen.blocks:
        out.extend(b.stage)
    return out


def role_blocks(screen: Screen) -> list[Block]:
    return [b for b in screen.blocks if b.kind in ("stat", "lower", "credits")]


def overlay_blocks(screen: Screen) -> list[Block]:
    return [b for b in screen.blocks if b.kind in ("lower", "credits")]


def credits_entries(screen: Screen) -> list[Block]:
    return [b for b in screen.blocks if b.kind == "credits" and b.text.strip()]


def is_black_screen(screen: Screen) -> bool:
    return any(s.role == BLACK_ROLE for s in screen.shots)


def is_credits_screen(screen: Screen) -> bool:
    """A credits SCREEN (end roll): no media shot, credits entries present.

    Contrast: a credits OVERLAY sits on a media screen (media shot present)
    and renders as a corner attribution line.
    """
    return screen.media_shot is None and bool(credits_entries(screen))


def onscreen_blocks(screen: Screen) -> list[Block]:
    """Blocks that are screen objects (not VO)."""
    return [b for b in screen.blocks if b.kind != "vo"]


def screen_script(screen: Screen) -> str:
    """Spoken text of a screen: VO paragraphs plus STAT payloads, plain text,
    parentheticals and markdown markers stripped (feeds TTS / script-follower).

    A stat payload ("57.5% of web traffic is bots, not people.") is a sentence
    the speaker reads while the screen shows the number, so it is scripted.
    Lower/credits payloads are attribution labels: screen text, never VO.
    """
    parts = []
    for b in screen.blocks:
        if b.kind == "vo" and b.text.strip():
            parts.append(plain_md(b.text))
        elif b.kind == "stat" and b.text.strip():
            parts.append(plain_md(b.text))
    return "\n\n".join(parts)


def cited_sources(talk: Talk) -> list[dict]:
    """The handout citation list data: every referenced registry entry, in
    first-appearance order (spec §5, Receipts).

    `Talk.footnote_ids` carries the stripped `[^id]` references in document
    order; each id keys into the frontmatter `sources:` registry (§2).  The
    result is the shared payload behind both `deck.sources` in cues.json and
    the document view's Sources list, so the frozen IR and the handout can
    never disagree about what a deck cites.

    A reference whose id has no registry entry is a parse-side defect (check
    28, spec §10) — it is stripped and collected but never emitted here:
    there is no registry value to cite, and the deck already warns.
    """
    registry = talk.meta.get("sources")
    if not isinstance(registry, dict):
        return []
    cited = []
    for rid in talk.footnote_ids:
        value = registry.get(rid)
        if value is None or not str(value).strip():
            continue
        cited.append({"id": rid, "source": str(value)})
    return cited


# ---------------------------------------------------------------------------
# Media element HTML
# ---------------------------------------------------------------------------

DIM_OVERLAY = (
    '<div class="dim" style="opacity:{op}"></div>'
)


def media_html(ref: MediaRef, shot_flags: dict | None = None, css_class: str = "figure-media") -> str:
    """One resolved media element (image / video / placeholder)."""
    flags = shot_flags or {}
    parts = []
    if ref.found and ref.file:
        ext = Path(ref.file).suffix.lower()
        if ext in (".mp4", ".webm", ".mov", ".m4v"):
            src = html.escape(ref.file if Path(ref.file).is_absolute() else "../" + ref.file)
            if "slide-media" in css_class.split():
                # cinematic: autoplay muted loop when the slide is active,
                # no native controls bar (the big play button never belongs
                # on a shot; the pager plays/pauses via data-autoplay)
                attrs = 'autoplay muted loop playsinline preload="auto" data-autoplay'
            else:
                # document figure: a reader clicks to play
                attrs = 'controls preload="metadata" muted loop playsinline'
            parts.append(
                f'<video class="{css_class} media-video" src="{src}" {attrs} '
                f'aria-label="{html.escape(ref.alt or ref.slug)}"></video>'
            )
        else:
            src = html.escape(ref.file if Path(ref.file).is_absolute() else "../" + ref.file)
            # slide media loads eagerly: hidden slides never enter the
            # viewport, so lazy images there would never fetch. Document
            # figures (all visible) may stay lazy.
            lazy = "" if "slide-media" in css_class.split() else ' loading="lazy"'
            parts.append(
                f'<img class="{css_class} media-image" src="{src}" '
                f'alt="{html.escape(ref.alt or ref.slug)}"{lazy}>'
            )
    else:
        parts.append(
            f'<div class="{css_class} media-placeholder" role="img" '
            f'aria-label="media pending: {html.escape(ref.slug)}">'
            f'<span class="ph-slug">{html.escape(ref.slug)}</span>'
            f'<span class="ph-type">{html.escape(ref.type)} · {html.escape(ref.status)}</span>'
            f'<span class="ph-note">{html.escape(ref.reason)}</span>'
            f'</div>'
        )
    if flags.get("dim"):
        try:
            op = max(0.0, min(1.0, float(flags["dim"])))
        except ValueError:
            op = 0.0
        parts.append(DIM_OVERLAY.format(op=f"{op:.2f}"))
    return "".join(parts)


def media_zone_html(ref: MediaRef, flags: dict) -> str:
    """Full-bleed media zone: media element + kb class + fit/dim + role/layout handling."""
    fit = " fit" if "fit" in flags else ""
    # Layout flags come from `layout=` (replaces flat piece/duo); read from flags.
    layout_name = flags.get("layout")
    piece = " piece" if layout_name == "piece" else ""
    duo = flags.get("duo")
    # For backward compat, if `layout=duo` or `layout=piece` set directly:
    if layout_name == "duo":
        duo = True  # treat as presence
    duo_cls = ""
    if layout_name == "duo" or (layout_name == "piece" and not piece):
        # duo implies piece (same layering rule as before)
        if not piece:
            piece = " piece"
    if layout_name == "duo" or (isinstance(duo, str) and duo == "left"):
        duo_cls = " duo-left"
    elif layout_name == "duo" or (duo is not None and not isinstance(duo, bool)):
        duo_cls = " duo"
    # Role-driven rendering: stat payloads render as screen objects; lower/credits
    # as overlays. The yaml-backed vocabulary keeps this deterministic.
    media_flags = {k: v for k, v in flags.items() if k != "dim" and k not in ("layout",)} if piece else flags
    kbcls = f" kb-{flags['kb']}" if flags.get("kb") in ("in", "out") else ""
    media = media_html(ref, media_flags, css_class=f"slide-media{kbcls}")
    if kbcls and not piece:
        # camera drift: the lens moves over an oversized, already-rasterized
        # picture — the IMAGE is the animated layer (its texture is the
        # full overscan), the lens only clips. No per-frame sampling, and
        # an edge can never surface because the texture exceeds the clip.
        media = f'<div class="kb-lens">{media}</div>'
    return f'<div class="media-zone{fit}{piece}{duo_cls}">{media}</div>'


# ---------------------------------------------------------------------------
# PRESENT view (owned pager: no external engine, one self-contained file)
# ---------------------------------------------------------------------------

PAGER_JS = """
(function () {
  "use strict";
  var slides = Array.prototype.slice.call(
    document.querySelectorAll(".animatic-slide"));
  var panel = document.getElementById("notes-panel");
  var fill = document.getElementById("progress-fill");
  var curEl = document.getElementById("slide-cur");
  var totalEl = document.getElementById("slide-total");
  var cur = 0;
  var lastCur = -1;
  totalEl.textContent = String(slides.length);

  function notesFor(i) {
    var aside = slides[i].querySelector(".notes");
    // notes HTML is builder-escaped (inline_md) static local output, safe
    return aside ? aside.innerHTML : "";
  }

  function restartMotion(slide) {
    // Ken Burns drift is a CSS animation on the kb image (compositor
    // thread, translate only). Restart it fresh on every arrival so each
    // visit begins in phase.
    var els = slide.querySelectorAll(".kb-lens .kb-in, .kb-lens .kb-out");
    for (var i = 0; i < els.length; i++) {
      var el = els[i];
      el.style.animation = "none";
      void el.offsetWidth;   // force reflow so the restart takes
      el.style.animation = "";
    }
  }

  function render() {
    for (var i = 0; i < slides.length; i++) {
      if (i === cur) { slides[i].classList.add("active"); }
      else { slides[i].classList.remove("active"); }
    }
    if (cur !== lastCur) { lastCur = cur; restartMotion(slides[cur]); }
    if (fill) fill.style.width = ((cur + 1) / slides.length * 100) + "%";
    if (curEl) curEl.textContent = String(cur + 1);
    if (panel && panel.classList.contains("open")) panel.innerHTML = notesFor(cur);
    // autoplay the active slide's video; pause everything else
    for (var i = 0; i < slides.length; i++) {
      var v = slides[i].querySelector("video[data-autoplay]");
      if (v) {
        if (i === cur) { var p = v.play(); if (p && p.catch) p.catch(function () {}); }
        else { v.pause(); }
      }
    }
  }

  function go(i, updateHash) {
    cur = Math.max(0, Math.min(slides.length - 1, i));
    render();
    if (updateHash !== false) history.replaceState(null, "", "#" + (cur + 1));
  }
  function next() { go(cur + 1); }
  function prev() { go(cur - 1); }

  function toggleNotes() {
    if (!panel) return;
    panel.classList.toggle("open");
    if (panel.classList.contains("open")) panel.innerHTML = notesFor(cur);
  }

  function fromHash() {
    var m = /^#(\\d+)$/.exec(location.hash);
    if (m) {
      var n = parseInt(m[1], 10) - 1;
      if (n >= 0 && n < slides.length) go(n, false);
    }
  }

  var nextBtn = document.getElementById("next-slide");
  var prevBtn = document.getElementById("prev-slide");
  if (nextBtn) nextBtn.addEventListener("click", next);
  if (prevBtn) prevBtn.addEventListener("click", prev);

  document.addEventListener("keydown", function (e) {
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    switch (e.key) {
      case "ArrowRight": case "ArrowDown": case "PageDown":
      case " ": e.preventDefault(); next(); break;
      case "ArrowLeft": case "ArrowUp": case "PageUp":
        e.preventDefault(); prev(); break;
      case "Home": e.preventDefault(); go(0); break;
      case "End": e.preventDefault(); go(slides.length - 1); break;
      case "s": case "S": toggleNotes(); break;
      case "Escape": if (panel) panel.classList.remove("open"); break;
    }
  });
  window.addEventListener("hashchange", fromHash);

  // basic swipe (tablets / touch surfaces)
  var x0 = null;
  document.addEventListener("pointerdown", function (e) { x0 = e.clientX; });
  document.addEventListener("pointerup", function (e) {
    if (x0 === null) return;
    var dx = e.clientX - x0;
    x0 = null;
    if (Math.abs(dx) > 60) { if (dx < 0) next(); else prev(); }
  });

  fromHash();
  render();
})();
"""


def render_present(talk: Talk, resolver: MediaResolver, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    theme = resolve_theme(talk)
    sections = []
    for i, screen in enumerate(talk.screens):
        # slide 1 is statically active: a deck is never a blank page even
        # before the pager script runs (progressive enhancement)
        first = " active" if i == 0 else ""
        sections.append(_present_section(talk, screen, resolver, first=first))
    meta = talk.meta
    title = html.escape(str(meta.get("title", deck_slug(talk))))
    doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} — present view</title>
{theme_style_blocks(theme)}
</head>
<body class="view-present">
<main class="stage" id="stage">
{chr(10).join(sections)}
</main>
<div class="progress-track"><div class="progress-fill" id="progress-fill"></div></div>
<nav class="pager-ui" aria-label="slides">
<button type="button" id="prev-slide" aria-label="previous">&#8249;</button>
<span class="counter"><span id="slide-cur">1</span> / <span id="slide-total">1</span></span>
<button type="button" id="next-slide" aria-label="next">&#8250;</button>
</nav>
<aside class="notes-panel" id="notes-panel" aria-live="polite"></aside>
<script>
{PAGER_JS}
</script>
</body>
</html>
"""
    path = out_dir / "index.html"
    path.write_text(doc, encoding="utf-8")
    return path


def _present_section(talk: Talk, screen: Screen, resolver: MediaResolver,
                     first: str = "") -> str:
    mshot = screen.media_shot
    ref = resolver.resolve(mshot.slug) if (mshot and mshot.slug) else None
    flags = mshot.flags if mshot else {}
    cue_id = f"{deck_slug(talk)}-{screen.idx:03d}"
    mv = screen.movement
    black = is_black_screen(screen)
    credits_screen = is_credits_screen(screen)
    # slide-level flags come from the screen's first shot (`fit` hero cards)
    sflags = screen.shots[0].flags if screen.shots else {}
    has_body = any(b.kind in ("heading", "stat", "quote", "list")
                   for b in screen.blocks)

    inner = []
    if ref is not None:
        mflags = dict(flags)
        if "fit" in mflags and has_body:
            mflags.pop("fit", None)  # on a text slide fit means hero TEXT
        inner.append(media_zone_html(ref, mflags))

    if credits_screen:
        # full end-roll: optional title + entries in balanced columns
        entries = credits_entries(screen)
        h = screen.first_heading
        title = (
            f'<h2 class="credits-title">{inline_md(h.text)}</h2>'
            if h is not None and h.text.strip()
            else ""
        )
        many = " many" if len(entries) >= 3 else " few"
        items = "".join(
            f'<p class="credits-entry">{inline_md(b.text)}</p>'
            for b in entries
        )
        inner.append(
            f'<div class="credits-screen{many}">{title}'
            f'<div class="credits-columns">{items}</div></div>'
        )
    else:
        body = []
        i = 0
        blocks = screen.blocks
        while i < len(blocks):
            b = blocks[i]
            # VO never renders on the slide body (cinematic slides; VO is
            # spoken, shown in speaker notes only).
            if b.kind == "vo":
                i += 1
                continue
            if b.kind == "heading":
                lvl = min(b.level or 2, 3)
                body.append(f"<h{lvl} class='slide-title'>{inline_md(b.text)}</h{lvl}>")
            elif b.kind == "quote":
                # quote + its attribution share one centered block, with the
                # credit line hugging the block's right edge
                nxt = blocks[i + 1] if i + 1 < len(blocks) else None
                if nxt is not None and nxt.kind == "quote-source" and nxt.text.strip():
                    src = f'<p class="quote-source">{inline_md(nxt.text)}</p>'
                    i += 1
                else:
                    src = ""
                body.append(
                    f'<div class="quote-block">'
                    f'<div class="quote-plate" aria-hidden="true"></div>'
                    f"<blockquote><p>{inline_md(b.text)}</p></blockquote>"
                    f"{src}</div>"
                )
            elif b.kind == "list":
                items = "".join(f"<li>{inline_md(i)}</li>" for i in b.items)
                body.append(f"<ul>{items}</ul>")
            elif b.kind == "stat":
                body.append(f'<div class="stat">{inline_md(b.text)}</div>')
            # lower / credits overlays are positioned (below); credits entries
            # on a credits screen were rendered above.
            i += 1

        if body:
            inner.append(f'<div class="screen-body">{"".join(body)}</div>')

        for b in overlay_blocks(screen):
            if b.kind == "lower" and b.text.strip():
                inner.append(f'<div class="lower-third">{html.escape(b.text)}</div>')
            elif b.kind == "credits" and b.text.strip():
                inner.append(f'<div class="credits-line">{html.escape(b.text)}</div>')

    # speaker notes: VO + stage directions (never on the slide body)
    notes = []
    for b in vo_paragraphs(screen):
        notes.append(f"<p>{inline_md(b.text)}</p>")
    for b in screen.blocks:
        for st in b.stage:
            notes.append(f'<p class="stage">({html.escape(st)})</p>')
    notes_html = "".join(notes)

    cls = "animatic-slide" + first
    if "fit" in sflags and not credits_screen and (
            screen.media_shot is None or has_body):
        # `fit` = hero text as big as the slide allows — including OVER
        # full-bleed media when the screen carries text (a media-only `fit`
        # keeps its other meaning: letterbox-contain the image)
        cls += " text-fit"
    layout_name = sflags.get("layout")
    if layout_name == "duo" and screen.media_shot is not None:
        cls += " duo"
    # per-slide text mode (shot flag `text=light|dark`): the author picks the
    # text colour for the ground — light glyphs for dark imagery, ink for
    # bright. Defaults to the room's identity colour (theme handles it).
    if sflags.get("text") in ("light", "dark"):
        cls += f" text-{sflags['text']}"
    layout_name = flags.get("layout")
    piece_active = (layout_name == "piece") or ("piece" in flags)
    if ref is not None and flags.get("layout") is None and "piece" not in flags:
        # full-bleed background media under screen text (image or video):
        # the common case; themes style the text zone for this ground
        cls += " over-media"
    if black:
        cls += " black-beat"
    return (
        f'<section id="{cue_id}" class="{cls}" data-movement="{mv}">'
        f'{"".join(inner)}'
        f'<aside class="notes">{notes_html}</aside>'
        f"</section>"
    )


# ---------------------------------------------------------------------------
# DOCUMENT view (static HTML handout; print-to-PDF via @media print)
# ---------------------------------------------------------------------------


def render_document(talk: Talk, resolver: MediaResolver, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    theme = resolve_theme(talk)
    meta = talk.meta
    deck_title = str(meta.get("title", deck_slug(talk)))
    meta_bits = [str(v) for v in
                 (meta.get("venue"), meta.get("date"), meta.get("format"), meta.get("dur"))
                 if v]

    opening = []
    movement_sections = []
    current = {"idx": 0, "items": opening}
    for screen in talk.screens:
        if is_black_screen(screen):
            continue  # black beats have no prose: nothing to print
        if screen.movement != current["idx"]:
            m = next((m for m in talk.movements if m.index == screen.movement), None)
            current = {"idx": screen.movement, "items": []}
            if m is not None:
                movement_sections.append(
                    (m.label, current["items"])
                )
        current["items"].append(_doc_screen_blocks(talk, screen, resolver, skip_deck_h1=deck_title))

    def render_flow(blocks) -> str:
        return "".join(blocks)

    open_html = f'<section class="opening">{render_flow(opening)}</section>' if opening else ""
    mov_html = "".join(
        f'<section class="movement" data-movement="{i}"><h2 class="movement">{html.escape(label)}</h2>{render_flow(items)}</section>'
        for i, (label, items) in enumerate(movement_sections, start=1)
    )

    # Receipts surface once, as the handout citation list (spec §5): every
    # referenced `sources:` registry entry, first-appearance order.  The
    # registry value is the citation — ids are authoring keys and stay in
    # cues.json, never on the page.  No receipts, no section.
    sources_html = ""
    cited = cited_sources(talk)
    if cited:
        items = "".join(
            f'<li>{html.escape(src["source"])}</li>' for src in cited
        )
        sources_html = (
            '<section class="sources">'
            '<h2 class="sources">Sources</h2>'
            f'<ol class="doc-sources">{items}</ol>'
            "</section>"
        )

    # Blank-source decks must not gain a stray blank line: emit each section
    # only when it has content, so receipt-free output stays byte-clean.
    body_sections = "\n".join(s for s in (open_html, mov_html, sources_html) if s)

    doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(deck_title)} — document view</title>
{theme_style_blocks(theme)}
</head>
<body class="view-document">
<article>
<header class="doc-head">
<h1>{html.escape(deck_title)}</h1>
<p class="meta">{html.escape(" · ".join(b for b in meta_bits if b))}</p>
</header>
{body_sections}
</article>
</body>
</html>
"""
    path = out_dir / "index.html"
    path.write_text(doc, encoding="utf-8")
    return path


def _doc_screen_blocks(talk: Talk, screen: Screen, resolver: MediaResolver,
                       skip_deck_h1: str) -> str:
    out = []
    media_shot = screen.media_shot
    ref = resolver.resolve(media_shot.slug) if (media_shot and media_shot.slug) else None
    credits_entries_ = credits_entries(screen)
    is_credits = is_credits_screen(screen)
    # figure first (media shot leads the screen), then flow blocks
    consumed = set()
    if ref is not None:
        inner = media_html(ref, css_class="figure-media")
        cap = "".join(
            f'<figcaption>{html.escape(b.text)}</figcaption>'
            for b in screen.blocks if b.kind in ("lower", "credits") and b.text.strip()
        )
        out.append(f'<figure class="shot" data-slug="{html.escape(ref.slug)}">{inner}{cap}</figure>')
        # lower/credits already rendered as the figure caption: don't repeat them
        consumed = {id(b) for b in screen.blocks if b.kind in ("lower", "credits")}
    for b in screen.blocks:
        if id(b) in consumed:
            continue
        if b.kind == "vo":
            if b.text.strip():
                out.append(f'<p class="vo">{inline_md(b.text)}</p>')
        elif b.kind == "heading":
            if b.text.strip() == skip_deck_h1 and screen.movement == 0:
                continue  # deck title already in the header
            lvl = 2 if (b.level or 2) <= 1 else min(b.level or 3, 4)
            out.append(f"<h{lvl} class='screen-heading'>{inline_md(b.text)}</h{lvl}>")
        elif b.kind == "quote":
            out.append(f"<blockquote><p>{inline_md(b.text)}</p></blockquote>")
        elif b.kind == "quote-source":
            out.append(f'<p class="doc-quote-source">{inline_md(b.text)}</p>')
        elif b.kind == "list":
            items = "".join(f"<li>{inline_md(i)}</li>" for i in b.items)
            out.append(f"<ul>{items}</ul>")
        elif b.kind == "stat":
            if b.text.strip():
                out.append(f'<div class="stat-callout"><p>{inline_md(b.text)}</p></div>')
        elif b.kind in ("lower", "credits") and not is_credits:
            if b.text.strip():
                out.append(f'<p class="screen-caption">{html.escape(b.text)}</p>')
        # stage notes never reach the handout
    if is_credits and credits_entries_:
        items = "".join(
            f'<p class="credits-entry">{inline_md(b.text)}</p>'
            for b in credits_entries_
        )
        out.append(f'<div class="doc-credits">{items}</div>')
    return "".join(out)


# ---------------------------------------------------------------------------
# CUES (ordered slide id -> script) + media manifest
# ---------------------------------------------------------------------------


def render_cues(talk: Talk, resolver: MediaResolver, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    cues = []
    by_movement: dict[int, list[str]] = {}

    for screen in talk.screens:
        cue_id = f"{deck_slug(talk)}-{screen.idx:03d}"
        by_movement.setdefault(screen.movement, []).append(cue_id)

        screen_obj = {"kind": "screen"}
        text = []
        for b in screen.blocks:
            if b.kind == "heading":
                text.append({"kind": "heading", "level": b.level, "text": b.text})
            elif b.kind == "quote":
                text.append({"kind": "quote", "text": b.text})
            elif b.kind == "quote-source":
                text.append({"kind": "source", "text": b.text})
            elif b.kind == "list":
                text.append({"kind": "list", "items": list(b.items)})
            elif b.kind in ("stat", "lower", "credits"):
                if b.text.strip():
                    text.append({"kind": b.kind, "text": b.text})
        screen_text = text if text else None

        media = None
        shots = []
        for s in screen.shots:
            shots.append({
                "slug": s.slug,
                "role": s.role,
                "flags": dict(sorted(s.flags.items())),
            })
            if s.is_media and s.slug:
                media = media_ref_dict(resolver.resolve(s.slug))

        cues.append({
            "id": cue_id,
            "ordinal": screen.idx,
            "movement": screen.movement,
            "kind": screen_kind(screen),
            "title": screen_title(screen) or None,
            "shots": shots,
            "media": media,
            "screen_text": screen_text,
            "script": screen_script(screen),
            "stage": stage_of(screen) or None,
        })

    movements_out = []
    for m in talk.movements:
        movements_out.append({
            "index": m.index,
            "label": m.label,
            "title": m.title,
            "cue_ids": by_movement.get(m.index, []),
        })

    payload = {
        "schema": "animatic.cues.v1",
        "deck": {
            "slug": str(meta_get(talk, "slug", deck_slug(talk))),
            "title": str(meta_get(talk, "title", "")),
            "date": str(meta_get(talk, "date", "")),
            "venue": str(meta_get(talk, "venue", "")),
            "format": str(meta_get(talk, "format", "")),
            "dur": str(meta_get(talk, "dur", "")),
            "theme": str(meta_get(talk, "theme", "")),
            "media_dir": str(meta_get(talk, "media", "media")),
            "bank": str(meta_get(talk, "bank", "")),
            # `sources`: the handout citation list data — every referenced
            # `[^id]` receipt id (first-appearance order) plus its frontmatter
            # `sources:` registry value (spec §5).  Empty when the deck has
            # no receipts.  The document view renders this same list.
            "sources": cited_sources(talk),
            # no `source` key: talk.source is an absolute machine path and
            # cues.json is a portable artifact (register check 17). If source
            # provenance is ever needed it belongs in nav.json, not here.
        },
        "movements": movements_out,
        "cues": cues,
        "warnings": list(talk.warnings),
    }
    path = out_dir / "cues.json"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def meta_get(talk: Talk, key: str, default):
    v = talk.meta.get(key)
    return default if v is None else v


def media_ref_dict(ref: MediaRef) -> dict:
    return {
        "slug": ref.slug,
        "type": ref.type,
        "status": ref.status,
        "found": ref.found,
        "file": ref.file,
        "source": ref.source,
        "alt": ref.alt,
        "credit": ref.credit,
        "licence": ref.licence,
        "note": ref.note,
        "reason": ref.reason,
    }


def render_manifest(talk: Talk, resolver: MediaResolver, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    referenced = []
    seen = set()
    for screen in talk.screens:
        cue_id = f"{deck_slug(talk)}-{screen.idx:03d}"
        for s in screen.shots:
            if s.is_media and s.slug not in seen:
                seen.add(s.slug)
                referenced.append({
                    "slug": s.slug,
                    "first_cue": cue_id,
                    "media": media_ref_dict(resolver.resolve(s.slug)),
                })
    payload = {
        "schema": "animatic.media.v1",
        "deck_slug": str(meta_get(talk, "slug", deck_slug(talk))),
        "referenced": referenced,
        "unreferenced_cards": resolver.unreferenced_cards(seen),
    }
    path = out_dir / "media-manifest.json"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path
