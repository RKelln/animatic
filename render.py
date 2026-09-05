"""render.py — one parse model, three outputs.

- PRESENT view : reveal.js v6.0.1 deck (stand-in engine; see
  docs/engine-decision.md).  One <section> per screen; VO + stage directions
  go to the speaker-notes <aside>; on-screen objects (media, title, stat,
  lower, credits, quotes, lists) render as the slide body.  reveal assets are
  pinned to https://unpkg.com/reveal.js@6.0.1 (verified reachable).
- DOCUMENT view: a self-contained static HTML handout.  The VO prose IS the
  document (the format's answer to "the handout is your notes"); shots become
  figures, stat cards become callouts, card headings become subheadings.
  Same parse, no duplicated authoring.  Print-to-PDF via @media print CSS.
- CUES: ordered slide-id -> script JSON for the future controller.
- MEDIA MANIFEST: slug resolution audit (what resolved where, what is a
  placeholder and why).

Deterministic: no timestamps, no set iteration, stable ordering everywhere.
"""

from __future__ import annotations

import html
import json
from pathlib import Path

from talkparse import (
    Block,
    Screen,
    Talk,
    inline_md,
    plain_md,
    slugify,
)
from mediaresolve import MediaResolver, MediaRef

REVEAL_CDN = "https://unpkg.com/reveal.js@6.0.1"


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def deck_slug(talk: Talk) -> str:
    raw = str(talk.meta.get("slug", "") or Path(talk.source).stem)
    return slugify(raw)


def screen_kind(screen: Screen) -> str:
    """Primary kind of a screen: media | stat | lower | credits | card."""
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
            parts.append(
                f'<video class="{css_class} media-video" src="{html.escape(ref.file)}" '
                f'controls preload="metadata" muted loop playsinline'
                + (f' data-autoplay' if css_class == "slide-media" else "")
                + f' aria-label="{html.escape(ref.alt or ref.slug)}"></video>'
            )
        else:
            parts.append(
                f'<img class="{css_class} media-image" src="{html.escape(ref.file)}" '
                f'alt="{html.escape(ref.alt or ref.slug)}" loading="lazy">'
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


# ---------------------------------------------------------------------------
# PRESENT view (reveal.js)
# ---------------------------------------------------------------------------

PRESENT_CSS = """
:root { --ink:#f2ede4; --paper:#0d0f12; --accent:#d8b26e; --muted:#9aa0a6; }
html, body { height: 100%; }
.reveal { font-family: Georgia, 'Times New Roman', serif; }
.reveal .slides section { height: 100%; }
.animatic-slide { position: relative; }
.media-zone { position:absolute; inset:0; }
.slide-media { position:absolute; inset:0; width:100%; height:100%; object-fit:cover; }
.dim { position:absolute; inset:0; background:#000; z-index:1; }
.screen-body { position:relative; z-index:2; height:100%; display:flex;
  flex-direction:column; align-items:center; justify-content:center;
  text-align:center; padding:4vh 6vw; box-sizing:border-box; }
.reveal h1, .reveal h2, .reveal h3 { font-weight:normal; text-shadow:0 2px 24px rgba(0,0,0,.55); }
.slide-title { color:var(--ink); }
.stat { font-size:1.9em; font-weight:bold; letter-spacing:.01em; line-height:1.15;
  color:var(--ink); text-shadow:0 2px 24px rgba(0,0,0,.6); }
blockquote { border-left:3px solid var(--accent); text-align:left; font-size:.85em; }
.lower-third { position:absolute; left:5vw; bottom:12vh; text-align:left; z-index:3;
  font-size:.6em; letter-spacing:.08em; text-transform:uppercase; color:var(--ink);
  background:rgba(0,0,0,.45); padding:.5em 1em; border-left:2px solid var(--accent); }
.credits-line { position:absolute; right:5vw; bottom:6vh; text-align:right; z-index:3;
  font-size:.45em; color:var(--muted); }
.notes { display:none; }
"""


def render_present(talk: Talk, resolver: MediaResolver, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    sections = []
    for screen in talk.screens:
        sections.append(_present_section(talk, screen, resolver))
    meta = talk.meta
    title = html.escape(str(meta.get("title", deck_slug(talk))))
    doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} — present view</title>
<link rel="stylesheet" href="{REVEAL_CDN}/dist/reveal.css">
<link rel="stylesheet" href="{REVEAL_CDN}/dist/theme/black.css">
<style>{PRESENT_CSS}</style>
</head>
<body>
<div class="reveal">
<div class="slides">
{chr(10).join(sections)}
</div>
</div>
<script src="{REVEAL_CDN}/dist/reveal.js"></script>
<script src="{REVEAL_CDN}/dist/plugin/notes.js"></script>
<script>
  Reveal.initialize({{
    width: 1920, height: 1080, margin: 0, minScale: 0.1, maxScale: 2,
    hash: true, controls: true, progress: true, slideNumber: true,
    center: false, transition: 'none', plugins: [RevealNotes]
  }});
</script>
</body>
</html>
"""
    path = out_dir / "index.html"
    path.write_text(doc, encoding="utf-8")
    return path


def _present_section(talk: Talk, screen: Screen, resolver: MediaResolver) -> str:
    mshot = screen.media_shot
    ref = resolver.resolve(mshot.slug) if (mshot and mshot.slug) else None
    flags = mshot.flags if mshot else {}
    cue_id = f"{deck_slug(talk)}-{screen.idx:02d}"
    mv = screen.movement

    inner = []
    if ref is not None:
        media = media_html(ref, flags, css_class="slide-media")
        inner.append(f'<div class="media-zone">{media}</div>')

    body = []
    for b in screen.blocks:
        # VO never renders on the slide body (cinematic slides; VO is spoken,
        # shown in speaker notes only).
        if b.kind == "vo":
            continue
        if b.kind == "heading":
            lvl = min(b.level or 2, 3)
            body.append(f"<h{lvl} class='slide-title'>{inline_md(b.text)}</h{lvl}>")
        elif b.kind == "quote":
            body.append(f"<blockquote><p>{inline_md(b.text)}</p></blockquote>")
        elif b.kind == "list":
            items = "".join(f"<li>{inline_md(i)}</li>" for i in b.items)
            body.append(f"<ul>{items}</ul>")
        elif b.kind == "stat":
            body.append(f'<div class="stat">{inline_md(b.text)}</div>')
        # lower / credits are absolutely positioned overlays (below)

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

    return (
        f'<section id="{cue_id}" class="animatic-slide" data-movement="{mv}">'
        f'{"".join(inner)}'
        f'<aside class="notes">{notes_html}</aside>'
        f"</section>"
    )


# ---------------------------------------------------------------------------
# DOCUMENT view (static HTML handout; print-to-PDF via @media print)
# ---------------------------------------------------------------------------

DOC_CSS = """
:root { color-scheme: light; --ink:#1c1e21; --muted:#5b6066; --line:#d9d4cc;
  --accent:#8a6a2f; --callout-bg:#f7f3ea; }
* { box-sizing: border-box; }
body { font-family: Georgia, 'Times New Roman', serif; color: var(--ink);
  max-width: 46rem; margin: 0 auto; padding: 2.5rem 1.5rem 4rem; line-height: 1.6; }
header.doc-head { border-bottom: 1px solid var(--line); padding-bottom: 1rem; margin-bottom: 1.5rem; }
header.doc-head h1 { font-size: 2.1rem; line-height: 1.15; margin: 0 0 .5rem; }
.meta { color: var(--muted); font-size: .9rem; margin: 0; }
.vo { margin: 1.1em 0; }
.lead { margin: 1.1em 0; }
h2.movement { font-size: 1.35rem; margin-top: 2.6rem; padding-top: 1.2rem;
  border-top: 2px solid var(--line); }
h3.screen-heading, h2.screen-heading { font-size: 1.15rem; margin: 1.8em 0 .4em; }
figure.shot { margin: 1.6em 0; text-align: center; }
figure.shot img, figure.shot video { max-width: 100%; border-radius: 4px; }
figure.shot .media-placeholder { border: 1.5px dashed var(--line); border-radius: 4px;
  padding: 2rem 1rem; color: var(--muted); display: flex; flex-direction: column; gap: .25rem; }
.media-placeholder .ph-slug { font-family: ui-monospace, Menlo, monospace; color: var(--ink); }
.media-placeholder .ph-note { font-size: .8rem; }
figcaption, .screen-caption { color: var(--muted); font-size: .85rem; margin-top: .5rem; }
blockquote { margin: 1.4em 0; padding: .2em 0 .2em 1.1em; border-left: 3px solid var(--accent);
  font-style: italic; color: #3a3d41; }
ul { padding-left: 1.4em; }
.stat-callout { margin: 1.6em 0; padding: 1.1em 1.3em; background: var(--callout-bg);
  border-left: 4px solid var(--accent); font-size: 1.3rem; font-weight: bold; }
.stat-callout p { margin: 0; }
.stage-note { display: none; }
@media print {
  @page { size: letter; margin: 16mm 15mm; }
  body { max-width: none; padding: 0; }
  h2.movement { page-break-before: always; }
  figure.shot, .stat-callout, blockquote { page-break-inside: avoid; }
}
"""


def render_document(talk: Talk, resolver: MediaResolver, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    meta = talk.meta
    deck_title = str(meta.get("title", deck_slug(talk)))
    meta_bits = [str(v) for v in
                 (meta.get("venue"), meta.get("date"), meta.get("format"), meta.get("dur"))
                 if v]

    opening = []
    movement_sections = []
    current = {"idx": 0, "items": opening}
    for screen in talk.screens:
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

    doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(deck_title)} — document view</title>
<style>{DOC_CSS}</style>
</head>
<body>
<article>
<header class="doc-head">
<h1>{html.escape(deck_title)}</h1>
<p class="meta">{html.escape(" · ".join(b for b in meta_bits if b))}</p>
</header>
{open_html}
{mov_html}
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
        elif b.kind == "list":
            items = "".join(f"<li>{inline_md(i)}</li>" for i in b.items)
            out.append(f"<ul>{items}</ul>")
        elif b.kind == "stat":
            if b.text.strip():
                out.append(f'<div class="stat-callout"><p>{inline_md(b.text)}</p></div>')
        elif b.kind in ("lower", "credits"):
            if b.text.strip():
                out.append(f'<p class="screen-caption">{html.escape(b.text)}</p>')
        # stage notes never reach the handout
    return "".join(out)


# ---------------------------------------------------------------------------
# CUES (ordered slide id -> script) + media manifest
# ---------------------------------------------------------------------------


def render_cues(talk: Talk, resolver: MediaResolver, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    cues = []
    by_movement: dict[int, list[str]] = {}

    for screen in talk.screens:
        cue_id = f"{deck_slug(talk)}-{screen.idx:02d}"
        by_movement.setdefault(screen.movement, []).append(cue_id)

        screen_obj = {"kind": "screen"}
        text = []
        for b in screen.blocks:
            if b.kind == "heading":
                text.append({"kind": "heading", "level": b.level, "text": b.text})
            elif b.kind == "quote":
                text.append({"kind": "quote", "text": b.text})
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
            "source": talk.source,
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
        cue_id = f"{deck_slug(talk)}-{screen.idx:02d}"
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
