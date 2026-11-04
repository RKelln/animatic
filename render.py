"""render.py — one parse model, three outputs.

- PRESENT view : one self-contained HTML file per deck (no external engine;
  the pager is a small inline script).  One <section> per screen on a
  .stage; VO + stage directions go to the speaker-notes asides ('n' shows
  them in this window; 's' opens the second-window presenter view —
  docs/presenter-view.md); on-screen objects (media, title, stat, lower,
  credits, quotes, lists, paraphrase) render as the slide body.  All look lives in themes/
  (layer reset > base > components > theme) and every value comes from the
  selected theme's tokens.
- PRESENTER page: present/presenter.html, the speaker UI for the second
  window 's' opens (cue id, movement, ordinal, VO, stage notes, next cue,
  wall clock, elapsed, and a preview of the current and next screen).  It
  carries the build-time cue index and is fed by postMessage from the deck,
  so it works over file://; a live screen is labelled, never previewed.
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

import dataclasses
import html
import json
import re
from pathlib import Path
from typing import Optional

import talkparse
import timing

from talkparse import (
    BLUR_MAX,
    BLACK_ROLE,
    Block,
    Screen,
    Talk,
    TIMER_TOKEN_RE,
    inline_md,
    parse_timer_token,
    plain_md,
    slugify,
    spoken_list_items,
    strip_timer_tokens,
)
from mediaresolve import VIDEO_EXTS, MediaResolver, MediaRef

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
    if h is None:   # a handout-only heading still names the screen in nav
        h = next((b for b in screen.blocks if b.kind == "handout-heading"), None)
    return h.text if h else ""


def vo_paragraphs(screen: Screen) -> list[Block]:
    return [b for b in screen.blocks if b.kind == "vo" and b.text.strip()]


NEXT_MARK_HTML = ('<span class="next-mark" role="img" aria-label="press next">'
                  '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 4l12 8-12 8z"/></svg>'
                  'NEXT</span>')


def notes_vo_html(b: Block) -> str:
    """A VO paragraph for the speaker notes, with a NEXT mark wherever the author
    wrote `[n]` / `[next]` (the presenter presses next there)."""
    out, pos = [], 0
    for off in b.nexts:
        out.append(inline_md(b.text[pos:off]))
        out.append(NEXT_MARK_HTML)
        pos = off
    out.append(inline_md(b.text[pos:]))
    return "".join(out)


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
    return [b for b in screen.blocks if b.kind not in ("vo", "print")]


def screen_script(screen: Screen) -> str:
    """Spoken text of a screen: VO paragraphs plus STAT payloads, plain text,
    parentheticals and markdown markers stripped (feeds TTS / script-follower).

    A stat payload ("57.5% of web traffic is bots, not people.") is a sentence
    the speaker reads while the screen shows the number, so it is scripted.
    Lower/credits payloads are attribution labels: screen text, never VO.

    A list under spoken voice-over is spoken as well as shown: its items join
    the script where the list stands, one item per paragraph (spec: Text —
    Spoken lists).
    """
    parts = []
    for b in screen.blocks:
        if b.kind == "vo" and b.text.strip():
            parts.append(plain_md(b.text))
        elif b.kind == "list" and b.spoken:
            for item in spoken_list_items(b.spoken_items or b.items):
                parts.append(item)
        elif b.spoken and b.text.strip():
            # a timer token in a spoken payload (a stat) is shown, never read
            t = strip_timer_tokens(b.text) if b.timer is not None else b.text
            if t.strip():
                parts.append(plain_md(t))
    return "\n\n".join(parts)


def notes_quote_html(b: Block, source: Optional[Block] = None) -> str:
    """A quote for the speaker notes: the quote and its attribution, in the
    notes' own treatment (no slide plate)."""
    inner = f"<blockquote{quote_kind_attr(b.text)}>{quote_paras_html(b.text)}</blockquote>"
    if source is not None and source.text.strip():
        inner += f'<p class="quote-source">{inline_md(source.text)}</p>'
    return f'<div class="quote-block">{inner}</div>'


def speaker_notes(screen: Screen) -> list:
    """The speaker notes of a screen, as (block, html) pairs.

    The notes are a reading copy of the slide: the presenter's words, the
    payloads he reads off (a stat, a paraphrase), and the screen's text that
    follows his words — or all of the screen's text, on a screen with no
    words of its own (spec: Text — Spoken lists, The reading copy).

    A `[notes]` block and the stage notes keep their own places: each is
    emitted where the author wrote it, a stage note right after the words of
    the paragraph it sits in.
    """
    out = []
    silent = not screen_script(screen).strip()   # nothing said on this screen
    spoken_before = False                         # his words have been said
    blocks = screen.blocks
    for i, b in enumerate(blocks):
        if b.kind == "vo" and (b.text.strip() or b.nexts):
            out.append((b, f"<p>{notes_vo_html(b)}</p>"))
            if b.text.strip():
                spoken_before = True
        elif b.kind in ("stat", "paraphrase") and b.spoken and b.text.strip():
            # a payload he reads off: the number, our line under a quote
            out.append((b, f"<p>{inline_md(b.text)}</p>"))
            spoken_before = True
        elif b.kind == "list" and b.items:
            if spoken_before or silent:
                out.append((b, list_html(b)))
        elif b.kind == "quote":
            if spoken_before or silent:
                nxt = blocks[i + 1] if i + 1 < len(blocks) else None
                src = nxt if (nxt is not None and nxt.kind == "quote-source") else None
                out.append((b, notes_quote_html(b, src)))
        elif b.kind == "quote-source":
            pass            # it travels with its quote, never on its own
        elif b.kind == "code" and b.text.strip():
            if spoken_before or silent:
                out.append((b, code_html(b)))
        elif b.kind == "print":      # `[notes]` text: in the notes, off the slide
            inner = []
            for ib in b.inner:
                if ib.kind == "list":
                    inner.append(list_html(ib))
                elif ib.kind == "table":
                    inner.append(table_html(ib))
                elif ib.text.strip():
                    inner.append(f'<p class="print-note">{inline_md(ib.text)}</p>')
            if inner:
                out.append((b, "".join(inner)))
        for st in b.stage:
            out.append((b, f'<p class="stage-note">({html.escape(st)})</p>'))
    return out


_BEAT_NOTE_RE = re.compile(r"beat\.?", re.IGNORECASE)


def has_beat_note(screen: Screen) -> bool:
    """True when a stage note marks this screen an explicit beat (`(Beat.)`,
    spec: Text — parenthetical prefixes; a `(Beat.)` is a timing/pause)."""
    return any(_BEAT_NOTE_RE.fullmatch(s.strip())
               for b in screen.blocks for s in b.stage)


def cue_estimate(screen: Screen, resolver: MediaResolver,
                 wpm: float = timing.DEFAULT_WPM) -> float:
    """The screen's `estimated` tier, in seconds (spec: Timing).

    Script word count ÷ `wpm`, floored per screen kind.  A media shot whose
    file is a video contributes the file's real duration from ffprobe, the
    hard floor: a video cannot be played faster than it is.  Screens with no
    voice-over stand on the floor alone.

    The one implementation both `cues.json` (est_seconds) and check 19 use, so
    the artifact and the check can never disagree about the clock.
    """
    words = timing.word_count(screen_script(screen))
    video_seconds = None
    shot = screen.media_shot
    if shot is not None and shot.slug:
        ref = resolver.resolve(shot.slug)
        if ref.found and ref.file:
            suffix = Path(ref.file).suffix.lower()
            if ref.type == "video" or suffix in VIDEO_EXTS:
                video_seconds = timing.probe_video_seconds(ref.origin or ref.file)
    tm = screen.timer
    return timing.estimate_seconds(
        words, screen_kind(screen),
        video_seconds=video_seconds, wpm=wpm,
        credits_read=is_credits_screen(screen),
        beat=has_beat_note(screen),
        timer_seconds=tm[0] if tm else None)


def cited_sources(talk: Talk) -> list[dict]:
    """The handout citation list data: every referenced registry entry, in
    first-appearance order (spec: Text, Receipts).

    `Talk.footnote_ids` carries the stripped `[^id]` references in document
    order; each id keys into the frontmatter `sources:` registry (Frontmatter).  The
    result is the shared payload behind both `deck.sources` in cues.json and
    the document view's Sources list, so the frozen IR and the handout can
    never disagree about what a deck cites.

    A reference whose id has no registry entry is a parse-side defect (check
    28, spec: Error and warning taxonomy) — it is stripped and collected but never emitted here:
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


def live_host_html(ref: MediaRef, css_class: str = "slide-media") -> str:
    """The present-view host for a `type: live` card: a window capture.

    `getDisplayMedia` is secure-context only and always needs a user gesture
    (spec: docs/live-capture.md), so the markup ships an idle state with a
    start control, a surface the stream attaches to, and a status line that
    names the remedy when capture is unavailable.  The stream is attached to
    the surface and never torn down by slide changes, so visibility is a slide
    change and nothing else.

    The surface carries no `controls` and is not `loop`ed: a live stream has no
    end to loop and the presenter stops it from the deck's own control.
    """
    poster = ""
    if ref.poster:
        # same relative-path rule as file media: a published poster is
        # out-root-relative, and both views sit one level below the out root
        poster_src = ref.poster if Path(ref.poster).is_absolute() else "../" + ref.poster
        poster = (
            f'<img class="live-poster media-image" src="{html.escape(poster_src)}" '
            f'alt="{html.escape(ref.alt or ref.slug)}">'
        )
    group_attr = (
        f' data-live-group="{html.escape(ref.group)}"' if ref.group else ""
    )
    return (
        f'<div class="{css_class} live-host" data-live-surface '
        f'data-live-state="idle" data-live-slug="{html.escape(ref.slug)}"{group_attr}>'
        f"{poster}"
        f'<video class="live-surface" muted playsinline aria-label="'
        f'{html.escape(ref.alt or ref.slug)}"></video>'
        f'<div class="live-idle">'
        f'<p class="live-hint">Live window</p>'
        f'<button class="live-start" type="button">Share a window</button>'
        f'</div>'
        f'<div class="live-controls">'
        f'<span class="live-chip">sharing a window</span>'
        f'<button class="live-stop" type="button">Stop</button>'
        f'</div>'
        f'<p class="live-status" role="status"></p>'
        f'</div>'
    )


def shot_playback(ref: MediaRef, flags: dict) -> str:
    """The screen's playback: the shot's `playback=` over the card's
    `playback:`. On a pingpong card the file is the baked forward+reverse
    clip, so `playback=once` plays that once."""
    return flags.get("playback") or ref.playback


def shot_sound(ref: MediaRef, flags: dict) -> bool:
    """The screen's sound: the shot's `sound` / `sound=false` over the card's
    `sound:`."""
    if "sound" in flags:
        return flags["sound"] == "true"
    return bool(ref.sound)


def media_html(ref: MediaRef, shot_flags: dict | None = None, css_class: str = "figure-media",
               chain: str | None = None) -> str:
    """One resolved media element (image / video / live capture / placeholder).
    `chain` (a `continue` chain id) marks a slide video the pager hands on,
    still playing, to the next slide of the same chain."""
    flags = shot_flags or {}
    parts = []
    if ref.live:
        if "slide-media" in css_class.split():
            parts.append(live_host_html(ref, css_class=css_class))
        elif ref.poster:
            # document figure: the handout prints the still, never a live stream
            poster = ref.doc_file or ref.poster
            poster_src = poster if Path(poster).is_absolute() else "../" + poster
            parts.append(
                f'<img class="{css_class} media-image" src="{html.escape(poster_src)}" '
                f'alt="{html.escape(ref.alt or ref.slug)}" loading="lazy">'
            )
        else:
            parts.append(
                f'<div class="{css_class} media-note" role="img" '
                f'aria-label="live capture: {html.escape(ref.slug)}">'
                f'<span class="ph-type">live window capture</span>'
                f'<span class="ph-note">shown live in the room; not printed in '
                f'the handout</span></div>'
            )
    elif ref.found and ref.file and ref.doc_file and "slide-media" not in css_class.split():
        # document figure: the handout carries a small JPEG, and a video is
        # only its still (a printed page cannot play it, and a black player
        # box is worse than a frame)
        parts.append(
            f'<img class="{css_class} media-image" src="{html.escape("../" + ref.doc_file)}" '
            f'alt="{html.escape(ref.alt or ref.slug)}" loading="lazy">'
        )
    elif ref.found and ref.file:
        ext = Path(ref.file).suffix.lower()
        if ext in (".mp4", ".webm", ".mov", ".m4v"):
            src = html.escape(ref.file if Path(ref.file).is_absolute() else "../" + ref.file)
            # playback (card `playback:`): `once` drops `loop`, so the video
            # stops on its last frame; `pingpong` is a baked forward+reverse
            # file (mediaresolve.publish) that loops like any other
            # `advance` (shot flag): when the video ends, the pager moves to
            # the next screen. A video that loops never ends, so advance
            # implies once. A shot's `playback=` / `sound` override the card
            # for that screen (shot_playback / shot_sound).
            advance = "advance" in flags
            playback = shot_playback(ref, flags)
            loop = "" if playback == "once" or advance else " loop"
            once = ' data-playback="once"' if playback == "once" or advance else ""
            adv = " data-advance" if advance else ""
            # sound (card `sound: true`): drop `muted`. The pager's play()
            # runs inside the keypress that changed slide, which is the user
            # activation browsers want before they play audio; if one still
            # refuses, the pager falls back to muted (PAGER_JS).
            has_sound = shot_sound(ref, flags)
            muted = "" if has_sound else "muted"
            sound = " data-sound" if has_sound else ""
            if "slide-media" in css_class.split():
                # cinematic: plays muted when the slide is active, no native
                # controls bar (the big play button never belongs on a shot).
                # No `autoplay` and preload="none": the pager plays the active
                # slide's video and warms the next few (PAGER_JS warm()). With
                # autoplay + preload="auto" on every slide, a served deck asked
                # for every video at load (L01: 29 files, 754 MB), each range
                # request held one of the browser's six connections to the
                # host, and the images queued behind them never loaded.
                attrs = f'{muted}{loop} playsinline preload="none" data-autoplay{once}{sound}{adv}'
                if chain:
                    attrs += f' data-chain="{html.escape(chain)}"'
            else:
                # document figure: a reader clicks to play
                attrs = f'controls preload="metadata" {muted}{loop} playsinline{once}{sound}'
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


# `kb` values: `in` / `out` are slow sideways drifts over an oversized image;
# `zoom-top` is one slow push-in anchored at the top edge, then a hold (a title
# lettered near the top of the picture stays in frame).
KB_VALUES = ("in", "out", "zoom-top")


def media_fit(flags: dict) -> str:
    """How slide media fits the frame: "contain" (letterbox, never crop) or
    "cover" (fill, crop overflow). An explicit fit=contain / fit=cover wins.
    Otherwise contain is the default (Ryan, 2026-09-28: charts, documents and
    4:3 film were being cropped), except under `kb` drift, whose lens needs the
    picture to overfill the frame so an edge never shows. `fit=hero` is about
    text, not media, so it leaves the media at its default."""
    v = flags.get("fit")
    if v in ("contain", "cover"):
        return v
    return "cover" if flags.get("kb") in KB_VALUES else "contain"


def underlay_html(under: MediaRef, flags: dict) -> str:
    """The `under=` backdrop: a still picture that fills the under-stage, left
    sharp; `dim=` darkens it. It fits like any slide media (contain by default,
    `fit=cover` to fill)."""
    if not (under.found and under.file) or \
            Path(under.file).suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp", ".gif", ".avif"):
        return ""
    src = html.escape(under.file if Path(under.file).is_absolute() else "../" + under.file)
    out = (f'<div class="underlay"><img class="underlay-media" src="{src}" '
           f'alt="" aria-hidden="true"></div>')
    if flags.get("dim"):
        try:
            op = max(0.0, min(1.0, float(flags["dim"])))
        except ValueError:
            op = 0.0
        out += DIM_OVERLAY.format(op=f"{op:.2f}")
    return out


# `under=` media are authored on a 1920x1080 stage: a video's pixel size says how
# much of the frame it takes, so a 1270x880 credits roll is 66% wide and 81% tall
STAGE_W, STAGE_H = 1920, 1080


def under_panel_style(ref: MediaRef, radius: float) -> str:
    style = []
    if radius:
        style.append(f"--frost-blur:{radius:g}px")
    size = None
    if ref.found and ref.origin and Path(ref.origin).suffix.lower() in VIDEO_EXTS:
        size = timing.probe_video_size(ref.origin)
    if size:
        style.append(f"width:{min(100.0, size[0] / STAGE_W * 100):.3f}%")
        style.append(f"height:{min(100.0, size[1] / STAGE_H * 100):.3f}%")
    return f' style="{";".join(style)}"' if style else ""


def under_blur(flags: dict) -> float:
    """`blur=` as a radius in px, clamped; 0 when absent or unreadable."""
    try:
        return max(0.0, min(float(BLUR_MAX), float(flags.get("blur") or 0)))
    except ValueError:
        return 0.0


def reveal_modes(flags: dict) -> set:
    """What a shot's `reveal` asks for: the parts of `reveal=list`, `off`,
    `timer` or a `+` join, and for a bare `reveal` (stored as `all`) every
    revealable thing the screen can hide. This is the one place a new
    revealable gets added: list it in REVEALABLES and the bare form covers it."""
    v = str(flags.get("reveal") or "")
    if v == talkparse.REVEAL_ALL:
        return set(REVEALABLES)
    return set(v.split("+"))


# The things a bare `reveal` reveals (which of them step, not in which order:
# the steps follow the order the elements are written on the screen). A new
# revealable opts in by being added here and to the pager's revealOf().
REVEALABLES = ("list", "timer")


def reveal_named(flags: dict) -> set:
    """Only what the author spelled out (`reveal=list+timer`): a bare `reveal`
    names nothing, so it never trips the warnings about a named part with
    nothing to act on."""
    v = str(flags.get("reveal") or "")
    return set() if v in ("", talkparse.REVEAL_ALL) else set(v.split("+"))


def reveal_is_bare(flags: dict) -> bool:
    return str(flags.get("reveal") or "") == talkparse.REVEAL_ALL


def has_revealable_list(screen: "Screen") -> bool:
    return any(b.kind == "list" and len(b.items) >= 2 for b in screen.blocks)


def revealables_on(screen: "Screen") -> list:
    """The revealable things this screen actually has."""
    out = []
    if has_revealable_list(screen):
        out.append("list")
    if screen.timer is not None:
        out.append("timer")
    return out


def bare_reveal_empty(screen: "Screen") -> bool:
    """A bare `reveal` on a screen with nothing revealable on it (check 45)."""
    return (any(reveal_is_bare(sh.flags) for sh in screen.shots)
            and not revealables_on(screen))


def step_frames_html(frames: list, flags: dict, extra_class: str = "") -> str:
    """A stepped-image card's frames stacked in one `.step-stack`: frame 1 is
    up (`on`) in the markup, the pager moves `on` along them one next-press at
    a time.  Every frame is a plain slide image; the shot's `dim` is drawn once
    over the stack."""
    flags = {k: v for k, v in flags.items() if k != "dim"}
    out = []
    for n, fr in enumerate(frames, 1):
        el = media_html(fr, flags, css_class=f"slide-media step-frame{extra_class}")
        out.append(el.replace("<img ", f'<img data-frame="{n}" ', 1) if "<img " in el
                   else el.replace("<div ", f'<div data-frame="{n}" ', 1))
    out[0] = out[0].replace('class="', 'class="on ', 1)
    return f'<div class="step-stack">{"".join(out)}</div>'


def media_zone_html(ref: MediaRef, flags: dict, chain: str | None = None,
                    under: MediaRef | None = None,
                    frames: list | None = None) -> str:
    """Full-bleed media zone: media element + kb class + fit/dim + role/layout handling."""
    if under is not None and flags.get("layout") in ("piece", "duo", "titled"):
        under = None          # a framed object has no full-bleed ground to put a backdrop on (check 32)
    if under is not None:
        # the shot's own media (a video with a transparent ground) lies over the
        # backdrop, so it takes no kb drift and no dim of its own: dim belongs to
        # the backdrop, or it would darken the very text it is there to protect
        media_flags = {k: v for k, v in flags.items()
                       if k not in ("dim", "kb", "layout", "under", "blur")}
        media = media_html(ref, media_flags, css_class="slide-media", chain=chain)
        radius = under_blur(flags)
        # the media takes its own share of the frame (its pixel size against the
        # 1920x1080 stage), placed by `anchor=`; `blur=` frosts a soft-edged panel
        # behind exactly that box, so a credits roll shorter than the frame leaves
        # the top of the picture (a title) untouched
        anchor = flags.get("anchor") if flags.get("anchor") in ("top", "bottom") else "center"
        panel = f"under-panel anchor-{anchor}" + (" frosted" if radius else "")
        stage = "under-stage" + (" fill" if flags.get("fit") == "cover" else "")
        return (f'<div class="media-zone under"><div class="{stage}">'
                f'{underlay_html(under, flags)}'
                f'<div class="{panel}"{under_panel_style(ref, radius)}>{media}</div>'
                f'</div></div>')
    # Layout flags come from `layout=` (replaces flat piece/duo); read from flags.
    layout_name = flags.get("layout")
    piece = " piece" if layout_name == "piece" else ""
    duo = flags.get("duo")
    # For backward compat, if `layout=duo` or `layout=piece` set directly:
    if layout_name == "duo":
        duo = True  # treat as presence
    duo_cls = ""
    if layout_name == "titled":
        piece = " piece"
    if layout_name == "duo" or (layout_name == "piece" and not piece):
        # duo implies piece (same layering rule as before)
        if not piece:
            piece = " piece"
    # layout=duo puts the object on the right, beside the text column (themes:
    # "object right by default"); it used to fall into the left branch, which
    # laid the picture over the text.
    if layout_name == "duo":
        duo_cls = " duo"
    elif isinstance(duo, str) and duo == "left":
        duo_cls = " duo-left"
    elif duo is not None and not isinstance(duo, bool):
        duo_cls = " duo"
    # Role-driven rendering: stat payloads render as screen objects; lower/credits
    # as overlays. The yaml-backed vocabulary keeps this deterministic.
    if ref.live:
        # a capture is live: Ken Burns drift and a dim scrim both fight it,
        # so a live screen takes neither (fit and layout still apply)
        media_flags = {k: v for k, v in flags.items()
                       if k not in ("dim", "kb", "layout")}
        kbcls = ""
    else:
        media_flags = {k: v for k, v in flags.items() if k != "dim" and k not in ("layout",)} if piece else flags
        kbcls = f" kb-{flags['kb']}" if flags.get("kb") in KB_VALUES else ""
    if frames:
        # stepped images: one stack of frames; camera drift would have to run
        # on every frame in step, so a stepped screen takes no kb
        media = step_frames_html(frames, media_flags)
        if media_flags.get("dim"):
            try:
                op = max(0.0, min(1.0, float(media_flags["dim"])))
            except ValueError:
                op = 0.0
            media += DIM_OVERLAY.format(op=f"{op:.2f}")
        kbcls = ""
    else:
        media = media_html(ref, media_flags, css_class=f"slide-media{kbcls}", chain=chain)
    if kbcls and not piece:
        # camera drift: the lens moves over an oversized, already-rasterized
        # picture — the IMAGE is the animated layer (its texture is the
        # full overscan), the lens only clips. No per-frame sampling, and
        # an edge can never surface because the texture exceeds the clip.
        media = f'<div class="kb-lens">{media}</div>'
    # a piece is always contained by its own CSS, so it takes no fit class
    fit = " fit" if media_fit(flags) == "contain" and not piece else ""
    titled_cls = " titled" if layout_name == "titled" else ""
    return f'<div class="media-zone{fit}{piece}{duo_cls}{titled_cls}">{media}</div>'


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
  // Modules that cannot own the single onChange slot register here instead
  // (the presenter window wants every arrival; the live module owns onChange).
  var listeners = [];
  var stepListeners = [];
  // stepped slides (reveal=list, stepped-image cards): stepAt[i] is slide i's step.
  var stepAt = [];
  totalEl.textContent = String(slides.length);

  // The stepping on slide i, or null when it has none.  Two things step, in
  // lockstep, on one counter k: a stepped-image card's frames (`.step-stack`,
  // frame min(k, n)) and a `reveal=list` list's items (item count min(k, m)).
  // `start` is k on arrival: 1 for images alone (frame 1), else the list's own
  // arrival (1 when it opens the slide, 0 when a title comes first, where frame
  // 1 is already up and press 1 brings bullet 1).  `total` is the larger count.
  function revealOf(i) {
    var sl = slides[i];
    if (!sl) return null;
    var st = sl.querySelector(".step-stack");
    var l = sl.querySelector("[data-reveal]");
    var tr = sl.querySelector("[data-timer-reveal]");
    if (!st && !l && !tr) return null;
    var imgs = st ? st.querySelectorAll("[data-frame]").length : 0;
    var items = l ? l.querySelectorAll("li[data-step]").length : 0;
    // `reveal=timer` adds one last step after the others: the press that shows
    // the countdown and starts it. A slide with only a timer opens at step 0.
    // Document order: a timer written above the list (data-timer-reveal="first")
    // takes the first press, and the list and the images follow it one press
    // later; otherwise the timer is the last step.
    var first = !!(tr && tr.getAttribute("data-timer-reveal") === "first");
    return {
      start: first ? 0 : (l ? (parseInt(l.getAttribute("data-reveal"), 10) || 0) : (st ? 1 : 0)),
      total: Math.max(imgs, items) + (tr ? 1 : 0),
      imgs: imgs,
      items: items,
      timer: !!tr,
      timerFirst: first
    };
  }
  function getStep(i) {
    var r = revealOf(i);
    if (!r) return 0;
    return stepAt[i] === undefined ? r.start : stepAt[i];
  }
  function applyStep(i) {
    var r = revealOf(i);
    if (!r) return;
    var k = getStep(i);
    // kl: the step as the list and the images see it (a first timer takes press 1)
    var kl = r.timerFirst ? k - 1 : k;
    var lis = slides[i].querySelectorAll("li[data-step]");
    for (var n = 0; n < lis.length; n++) {
      lis[n].classList.toggle("pending", n + 1 > kl);
    }
    // the frame on top is frame k; the one before it stays up under it, so a
    // crossfade never dips to the ground
    var tp = slides[i].querySelector("[data-timer-reveal]");
    if (tp) tp.classList.toggle("pending", r.timerFirst ? k < 1 : k < r.total);
    var frames = slides[i].querySelectorAll(".step-stack [data-frame]");
    var f = Math.max(1, Math.min(frames.length, kl));
    for (var j = 0; j < frames.length; j++) {
      frames[j].classList.toggle("on", j + 1 === f);
      frames[j].classList.toggle("prior", j + 1 === f - 1);
    }
  }
  function setHash() {
    var r = revealOf(cur);
    var k = getStep(cur);
    history.replaceState(null, "", "#" + (cur + 1) + (r && k > r.start ? "." + k : ""));
  }

  // NEXT marks in a notes container: `done` presses are behind us, so mark j is
  // "done" (j < done), "up" (the very next press) or untouched (still to come).
  function markNexts(root, done) {
    var m = root.querySelectorAll(".next-mark");
    for (var j = 0; j < m.length; j++) {
      m[j].classList.toggle("done", j < done);
      m[j].classList.toggle("up", j === done);
    }
  }
  function pressesDone(i) {
    var r = revealOf(i);
    return r ? Math.max(0, getStep(i) - r.start) : 0;
  }

  function notesFor(i) {
    var aside = slides[i].querySelector(".notes");
    // notes HTML is builder-escaped (inline_md) static local output, safe
    return aside ? aside.innerHTML : "";
  }

  function restartMotion(slide) {
    // Ken Burns drift is a CSS animation on the kb image (compositor
    // thread, translate only). Restart it fresh on every arrival so each
    // visit begins in phase.
    var els = slide.querySelectorAll(".kb-lens .kb-in, .kb-lens .kb-out, .kb-lens .kb-zoom-top");
    for (var i = 0; i < els.length; i++) {
      var el = els[i];
      el.style.animation = "none";
      void el.offsetWidth;   // force reflow so the restart takes
      el.style.animation = "";
    }
    // a play-once video starts from the top on every arrival, then holds
    // its last frame (it carries no `loop`)
    var once = slide.querySelectorAll('video[data-playback="once"]');
    for (var j = 0; j < once.length; j++) {
      try { once[j].currentTime = 0; } catch (err) { /* not yet seekable */ }
    }
  }

  function render() {
    for (var i = 0; i < slides.length; i++) {
      if (i === cur) { slides[i].classList.add("active"); }
      else { slides[i].classList.remove("active"); }
      // a slide you are not on is back at its start step (so the presenter's
      // next-up preview shows it as it will open)
      if (i !== cur) delete stepAt[i];
      applyStep(i);
    }
    if (cur !== lastCur) {
      var carried = carryChain(slides[lastCur], slides[cur]);
      lastCur = cur;
      if (!carried) restartMotion(slides[cur]);
    }
    if (fill) fill.style.width = ((cur + 1) / slides.length * 100) + "%";
    if (curEl) curEl.textContent = String(cur + 1);
    if (panel && panel.classList.contains("open")) { panel.innerHTML = notesFor(cur); markNexts(panel, pressesDone(cur)); }
    if (window.animatic && typeof window.animatic.onChange === "function") {
      try { window.animatic.onChange(cur); } catch (err) { /* never break nav */ }
    }
    for (var li = 0; li < listeners.length; li++) {
      try { listeners[li](cur); } catch (err) { /* never break nav */ }
    }
    // warm before play: a load() after play() would abort that play
    warmAround(cur);
    // autoplay the active slide's video; pause everything else
    for (var i = 0; i < slides.length; i++) {
      var v = slides[i].querySelector("video[data-autoplay]");
      if (v) {
        if (i === cur) { playVideo(v); }
        else { v.pause(); }
      }
    }
  }

  // Quotes that overflow their slide shrink until they fit (a long quote's
  // size class is only an estimate from its length). Hidden slides are still
  // laid out, so every slide is measured up front, and again on resize and
  // once web fonts have loaded. The size is set in em, so it scales with the
  // stage.
  function fitQuotes() {
    for (var i = 0; i < slides.length; i++) {
      var body = slides[i].querySelector(".screen-body");
      var q = body && body.querySelector(".quote-block blockquote");
      if (!q) continue;
      q.style.fontSize = "";
      var base = parseFloat(getComputedStyle(q).fontSize);
      var parent = parseFloat(getComputedStyle(q.parentNode).fontSize) || 1;
      var scale = 1;
      while (body.scrollHeight > body.clientHeight + 1 && scale > 0.4) {
        scale -= 0.05;
        q.style.fontSize = (base * scale / parent).toFixed(3) + "em";
      }
      // still overflowing at the floor: something else on the slide is too
      // tall, so the quote goes back to its own size
      if (body.scrollHeight > body.clientHeight + 1) q.style.fontSize = "";
    }
  }
  // Any other slide whose text overflows shrinks its text a little (the
  // screen's size is not known when the deck is built). Only the text scales:
  // the slide body's font size, which every heading, list and stat is sized
  // from in em; media and layout boxes are in vw/% and do not move. The floor
  // is deliberately close to full size: this is for small adjustments, and a
  // slide that still does not fit at the floor is left at the floor and marked
  // data-fit="floor" (with a console warning) for the author to shorten. A
  // slide that fits is never touched. Hero text (text-fit) sizes itself.
  var FIT_FLOOR = 0.75, FIT_STEP = 0.02;
  // A fenced block (.code-block) wraps its long lines under a hanging indent,
  // so width never shrinks the text: only height decides the size.
  function codeBlocks(sl) { return sl.querySelectorAll(".code-block, .quote-block"); }
  // On a slide with a fenced block the content must also stay inside the
  // body's padding, so a block sized to the last pixel never touches the edge.
  // `pad` forces the padding check on a hero list, stat or table as well.
  function overflows(sl, body, pad) {
    if (body.scrollHeight > body.clientHeight + 1) return true;
    // layout=cols: a column cell is only as wide as its share, so a word that
    // does not fit it (a narrow window, a long term) makes the text shrink
    var cells = body.querySelectorAll("[data-cols] > li");
    for (var c = 0; c < cells.length; c++) {
      if (cells[c].scrollWidth > cells[c].clientWidth + 1) return true;
    }
    if (!pad && !codeBlocks(sl).length) return false;
    var r = body.getBoundingClientRect(), cs = getComputedStyle(body);
    var top = r.top + parseFloat(cs.paddingTop), bot = r.bottom - parseFloat(cs.paddingBottom);
    for (var k = 0; k < body.children.length; k++) {
      var c = body.children[k].getBoundingClientRect();
      if (c.top < top - 1 || c.bottom > bot + 1) return true;
    }
    return false;
  }
  function fitBodies() {
    for (var i = 0; i < slides.length; i++) {
      var sl = slides[i];
      var body = sl.querySelector(".screen-body");
      if (!body || sl.classList.contains("text-fit")) continue;
      body.style.fontSize = "";
      sl.removeAttribute("data-fit");
      if (!overflows(sl, body)) continue;
      var scale = 1;
      while (overflows(sl, body) && scale > FIT_FLOOR + 1e-6) {
        scale = Math.max(FIT_FLOOR, scale - FIT_STEP);
        body.style.fontSize = scale.toFixed(2) + "em";
      }
      if (overflows(sl, body)) {
        sl.setAttribute("data-fit", "floor");
        if (window.console) console.warn("animatic: " + sl.id + " still overflows at " + FIT_FLOOR * 100 + "% text; shorten it");
      } else {
        sl.setAttribute("data-fit", scale.toFixed(2));
      }
    }
  }
  // fit=hero with a fenced block, a quote, a list, a stat or a table: that
  // block takes the biggest size at which the whole slide still fits, between
  // the 75% floor and 300% of its normal size, by height alone (long lines
  // wrap). The title sizes itself (hero text, stepping down beside a list or
  // table, see the themes), and only the block scales. A slide still too tall at the floor is
  // marked data-fit="floor", as above.
  var HERO_CODE_MAX = 3;
  var HERO_BLOCKS = ".code-block, .quote-block, :scope > ul, :scope > ol, " +
    ":scope > .stat, :scope > .md-table, :scope > .paraphrase-block";
  function fitHeroCode() {
    for (var i = 0; i < slides.length; i++) {
      var sl = slides[i];
      var body = sl.querySelector(".screen-body");
      var pre = body && sl.classList.contains("text-fit") &&
        body.querySelector(HERO_BLOCKS);
      if (!pre) continue;
      var bq = pre.querySelector("blockquote");
      if (bq) bq.style.fontSize = "";   // fitQuotes may have shrunk it
      pre.style.fontSize = "";
      sl.removeAttribute("data-fit");
      var base = parseFloat(getComputedStyle(pre).fontSize);
      var parent = parseFloat(getComputedStyle(pre.parentNode).fontSize) || 1;
      var set = function (sc) { pre.style.fontSize = (base * sc / parent).toFixed(3) + "em"; };
      var fits = function () { return !overflows(sl, body, true); };
      var scale = 1;
      if (fits()) {
        var lo = 1, hi = HERO_CODE_MAX;
        set(hi);
        if (fits()) { lo = hi; }
        else {
          for (var n = 0; n < 12; n++) {
            var mid = (lo + hi) / 2;
            set(mid);
            if (fits()) lo = mid; else hi = mid;
          }
        }
        scale = lo;
        set(scale);
      } else {
        while (!fits() && scale > FIT_FLOOR + 1e-6) {
          scale = Math.max(FIT_FLOOR, scale - FIT_STEP);
          set(scale);
        }
        if (!fits()) {
          sl.setAttribute("data-fit", "floor");
          if (window.console) console.warn("animatic: " + sl.id + " still overflows at " + FIT_FLOOR * 100 + "% text; shorten it");
          continue;
        }
      }
      sl.setAttribute("data-fit", scale.toFixed(2));
    }
  }
  function fitAll() { fitQuotes(); fitBodies(); fitHeroCode(); }
  fitAll();
  window.addEventListener("resize", fitAll);
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(fitAll);

  // `continue` shots: slides whose videos share a data-chain show one clip.
  // Moving between two of them swaps the <video> elements, so the one that is
  // playing lands in the new slide and carries on (a move in one step does
  // not pause it); the idle one takes its place in the old slide. Each slide
  // keeps its own classes (fit / kb). Returns true when a video was carried.
  function carryChain(from, to) {
    if (!from || !to || from === to) return false;
    var a = from.querySelector("video[data-chain]");
    var b = to.querySelector("video[data-chain]");
    if (!a || !b || a.getAttribute("data-chain") !== b.getAttribute("data-chain")) return false;
    var ca = a.className, cb = b.className;
    var mark = document.createComment("");
    b.parentNode.replaceChild(mark, b);
    a.parentNode.replaceChild(b, a);
    mark.parentNode.replaceChild(a, mark);
    a.className = cb; b.className = ca;
    return true;
  }

  // `advance` (shot flag): a slide video that plays to its end moves the
  // deck on. Only while its slide is still current: a presenter who has
  // already moved (or gone back) is never overridden.
  (function () {
    var advs = document.querySelectorAll("video[data-advance]");
    for (var a = 0; a < advs.length; a++) {
      advs[a].addEventListener("ended", function (e) {
        if (slides[cur] && slides[cur].contains(e.target) && cur < slides.length - 1) next();
      });
    }
  })();

  // A `sound` video that the browser will not start with audio (autoplay
  // policy: the deck window has had no click or key since it loaded, which is
  // also the case when every move comes from the presenter window) plays muted
  // rather than not at all. The mute is for THIS attempt only: every arrival
  // tries unmuted first, so one early refusal does not silence the clip for
  // the rest of the talk.
  function playVideo(v) {
    if (v.hasAttribute("data-sound")) v.muted = false;
    var p = v.play();
    if (!p || !p.catch) return;
    p.catch(function (err) {
      if (!err) return;
      if (err.name === "NotAllowedError" && !v.muted) {
        v.muted = true;
        var q = v.play(); if (q && q.catch) q.catch(function () {});
        toast("sound blocked by the browser: click once in the deck window, then press R");
      } else if (err.name === "AbortError") {
        // the load was restarted under the play (a warm or reload); play again
        // once the new load can, if this slide is still the one on screen
        v.addEventListener("canplay", function () {
          if (slides[cur] && slides[cur].contains(v)) {
            var q2 = v.play(); if (q2 && q2.catch) q2.catch(function () {});
          }
        }, { once: true });
      }
    });
  }

  // Slide videos are built preload="none" (media_html): nothing loads until
  // the slide is near. warm(i) switches slide i's videos to preload="auto"
  // and starts the load once; the media panel (`m`) calls it for every slide.
  var WARM_AHEAD = 3;      // the next few slides, whatever they hold
  var WARM_VIDEOS = 2;     // plus the next few slides that carry a video
  var KEEP_BEHIND = 2;     // slides behind the current one keep their buffer
  function hasVideo(i) { return !!slides[i].querySelector("video[data-autoplay]"); }

  // Warm what is about to be needed and let go of what has been passed. A
  // deck of cards with a long clip six slides ahead still gets that clip warm
  // in time (the video look-ahead counts video slides, not slides), and a clip
  // far behind gives its buffer back so a whole talk never holds every video
  // in memory at once (Firefox and a screen capture both feel that). A video
  // the media panel's Load all pinned is never released.
  function warmAround(c) {
    var w, found = 0;
    for (w = c; w < slides.length; w++) {
      if (w <= c + WARM_AHEAD) { warm(w); if (w > c && hasVideo(w)) found++; continue; }
      if (found >= WARM_VIDEOS) break;
      if (hasVideo(w)) { warm(w); found++; }
    }
    for (w = 0; w < c - KEEP_BEHIND; w++) release(w);
  }
  function release(i) {
    var vids = slides[i].querySelectorAll("video[data-autoplay][data-warmed]");
    for (var j = 0; j < vids.length; j++) {
      var v = vids[j];
      // a chained clip is carried between slides, so it is never "behind"
      if (v.hasAttribute("data-pinned") || v.hasAttribute("data-chain")) continue;
      v.removeAttribute("data-warmed");
      v.preload = "none";
      v.pause();
      try { v.load(); } catch (err) { /* never break nav */ }
    }
  }

  // A video the browser cancelled before any data arrived (Firefox shows
  // NS_BINDING_ABORTED) sits at readyState 0 and does nothing. If the slide on
  // screen has one, ask again.
  setInterval(function () {
    var s = slides[cur];
    if (!s) return;
    var v = s.querySelector("video[data-autoplay]");
    if (!v || v.error || v.readyState !== 0 || v.networkState === 2) return;
    if (!v.hasAttribute("data-warmed")) { warm(cur); return; }
    try { v.load(); } catch (err) { /* never break nav */ }
    playVideo(v);
  }, 3000);

  function warm(i) {
    var s = slides[i];
    if (!s) return;
    var vids = s.querySelectorAll("video[data-autoplay]");
    for (var j = 0; j < vids.length; j++) {
      var v = vids[j];
      if (v.hasAttribute("data-warmed")) continue;
      v.setAttribute("data-warmed", "");
      v.preload = "auto";
      // a video that has not fetched anything yet needs load() to pick up
      // the new preload; one already playing or buffering is left alone
      if (v.readyState === 0 && v.networkState !== 2) {
        try { v.load(); } catch (err) { /* never break nav */ }
      }
    }
  }

  // `r`: force-load the media of the slide on screen. A video that sits at
  // nothing (a cancelled request, a stalled connection) is dropped and fetched
  // again from the top, and a failed image is re-requested past the cache.
  var toastEl = null, toastTimer = null;
  function toast(msg) {
    if (!toastEl) {
      toastEl = document.createElement("div");
      toastEl.setAttribute("style", "position:fixed;left:50%;bottom:1.2em;" +
        "transform:translateX(-50%);padding:.35em .9em;border-radius:.4em;" +
        "background:rgba(0,0,0,.75);color:#fff;font:14px system-ui,sans-serif;" +
        "z-index:99999;pointer-events:none;opacity:0;transition:opacity .2s");
      document.body.appendChild(toastEl);
    }
    toastEl.textContent = msg;
    toastEl.style.opacity = "1";
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { toastEl.style.opacity = "0"; }, 1800);
  }
  function reloadMedia() {
    var s = slides[cur];
    if (!s) return;
    var vids = s.querySelectorAll("video.media-video"), n = 0, k;
    // First cancel every other slide's in-flight preload: a browser allows only
    // a few connections to one host, and a server that cannot stop a transfer
    // early (no Range) keeps them all busy, so this slide's request would just
    // queue behind them. They warm again once this slide is under way.
    for (k = 0; k < slides.length; k++) { if (k !== cur) release(k); }
    for (k = 0; k < vids.length; k++) {
      var v = vids[k];
      v.setAttribute("data-warmed", "");
      v.removeAttribute("data-stalled");
      v.preload = "auto";
      try { v.pause(); v.load(); } catch (err) { /* never break nav */ }
      if (v.hasAttribute("data-autoplay")) playVideo(v);
      n++;
    }
    var imgs = s.querySelectorAll("img.media-image");
    for (k = 0; k < imgs.length; k++) {
      var im = imgs[k];
      if (im.complete && im.naturalWidth > 0) continue;
      var u = im.getAttribute("src").replace(/[?&]r=\\d+$/, "");
      im.setAttribute("src", u + (u.indexOf("?") < 0 ? "?" : "&") + "r=" + Date.now());
      n++;
    }
    toast(n ? "reloading " + n + " media on this slide" : "no media on this slide");
    setTimeout(function () { warmAround(cur); }, 2500);
  }

  function go(i, updateHash, step) {
    // An index that is not a finite number (a cue id, undefined, NaN) is not a
    // destination.  Ignore it instead of letting cur become NaN: the pager
    // would strip `active` from every slide before restartMotion threw, so the
    // deck went blank and every later next()/prev() stayed NaN until a reload.
    var n = Number(i);
    if (!isFinite(n)) return;
    cur = Math.max(0, Math.min(slides.length - 1, Math.floor(n)));
    var r = revealOf(cur);
    if (r && step !== undefined && step !== null) {
      stepAt[cur] = Math.max(r.start, Math.min(r.total, step));
    } else {
      delete stepAt[cur];
    }
    render();
    if (updateHash !== false) setHash();
  }
  // next/prev move through a reveal list one item at a time, then on to the
  // neighbouring slide. Going back into a revealed slide lands fully shown.
  function stepped() {
    applyStep(cur);
    setHash();
    if (panel.classList.contains("open")) { panel.innerHTML = notesFor(cur); markNexts(panel, pressesDone(cur)); }
    for (var si = 0; si < stepListeners.length; si++) {
      try { stepListeners[si](cur, getStep(cur)); } catch (err) { /* never break nav */ }
    }
  }
  function next() {
    var r = revealOf(cur);
    if (r && getStep(cur) < r.total) { stepAt[cur] = getStep(cur) + 1; stepped(); }
    else go(cur + 1);
  }
  function prev() {
    var r = revealOf(cur);
    if (r && getStep(cur) > r.start) { stepAt[cur] = getStep(cur) - 1; stepped(); return; }
    var t = cur > 0 ? revealOf(cur - 1) : null;
    // back into a slide lands with everything shown except a revealed timer,
    // which is always waiting for its own press (hidden, not started)
    // (a timer that comes first has nothing before its press to land on: the start)
    go(cur - 1, true, t ? (t.timer ? (t.timerFirst ? t.start : t.total - 1) : t.total) : undefined);
  }

  function toggleNotes() {
    if (!panel) return;
    panel.classList.toggle("open");
    if (panel.classList.contains("open")) { panel.innerHTML = notesFor(cur); markNexts(panel, pressesDone(cur)); }
  }

  function fromHash() {
    var m = /^#(\\d+)(?:\\.(\\d+))?$/.exec(location.hash);
    if (m) {
      var n = parseInt(m[1], 10) - 1;
      if (n >= 0 && n < slides.length) {
        go(n, false, m[2] === undefined ? undefined : parseInt(m[2], 10));
      }
    }
  }

  var nextBtn = document.getElementById("next-slide");
  var prevBtn = document.getElementById("prev-slide");
  if (nextBtn) nextBtn.addEventListener("click", next);
  if (prevBtn) prevBtn.addEventListener("click", prev);

  // Tiny public surface for the modules that live beside the pager (live
  // capture reads the current slide to gate its sinks; the hookup panel jumps
  // between demo slides; the presenter window pushes state on every arrival).
  // Additive: nothing here changes pager behaviour, and a listener throwing
  // cannot break navigation. `onChange` stays single-slot (the live module
  // owns it); `addOnChange` is the fan-out for everyone else.
  window.animatic = {
    go: go, next: next, prev: prev, warm: warm, reloadMedia: reloadMedia,
    count: function () { return slides.length; },
    current: function () { return cur; },
    step: function () { return getStep(cur); },
    pressesDone: function () { return pressesDone(cur); },
    steps: function () { var r = revealOf(cur); return r ? r.total : 0; },
    stepImages: function () { var r = revealOf(cur); return r ? r.imgs : 0; },
    addOnStep: function (fn) {
      if (typeof fn === "function") stepListeners.push(fn);
    },
    onChange: null,
    addOnChange: function (fn) {
      if (typeof fn === "function") listeners.push(fn);
    }
  };

  document.addEventListener("keydown", function (e) {
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    switch (e.key) {
      case "ArrowRight": case "ArrowDown": case "PageDown":
      case " ": e.preventDefault(); next(); break;
      case "ArrowLeft": case "ArrowUp": case "PageUp":
        e.preventDefault(); prev(); break;
      case "Home": e.preventDefault(); go(0); break;
      case "End": e.preventDefault(); go(slides.length - 1); break;
      // 'n' = notes in THIS window (a one-screen room); 's' = the second
      // window with the speaker UI, which PRESENTER_JS binds (below).
      case "n": case "N": toggleNotes(); break;
      case "r": case "R": reloadMedia(); break;
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


TIMER_JS = r"""
(function () {
  "use strict";
  // Countdown timers (`[Timer: 8:00]` in screen text; spec: Timer screens).
  // A timer starts the first time its slide is shown in THIS window, then runs
  // on a wall-clock end time (Date.now), never a tick counter, so a throttled
  // tab or a slow frame cannot drift. It keeps running while the presenter is
  // on another slide. Nothing is persisted: a reload starts every timer over.
  // The presenter window gets the state ({mode, endAt, left, duration}) and
  // does its own arithmetic from the same wall clock.
  var A = window.animatic;
  if (!A) return;
  var slides = Array.prototype.slice.call(document.querySelectorAll(".animatic-slide"));
  var st = {};            // slide index -> timer state, once started
  var listeners = [];
  var MIN = 60000;

  function plateOf(i) {
    return slides[i] ? slides[i].querySelector(".timer-plate") : null;
  }
  function dur(i) {
    var p = plateOf(i);
    return p ? (parseInt(p.getAttribute("data-timer"), 10) || 0) * 1000 : 0;
  }
  function two(n) { return (n < 10 ? "0" : "") + n; }
  function fmt(sec) {
    var h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
    return h ? h + ":" + two(m) + ":" + two(s) : m + ":" + two(s);
  }
  // ms left (negative once over); paused and idle states hold their own value
  function leftOf(t, now) { return t.mode === "running" ? t.endAt - now : t.left; }
  // what the digits say: whole seconds rounded up while time remains, then
  // "0:00" for the first second after zero, then "+m:ss" counting up
  function textOf(rem) {
    if (rem > 0) return fmt(Math.ceil(rem / 1000));
    var over = Math.floor(-rem / 1000);
    return over === 0 ? "0:00" : "+" + fmt(over);
  }
  function setDigits(el, text) {
    if (el.getAttribute("data-text") === text) return;
    el.setAttribute("data-text", text);
    el.textContent = "";
    for (var k = 0; k < text.length; k++) {
      var c = document.createElement("span");
      var ch = text.charAt(k);
      c.className = ch === ":" ? "c" : ch === "+" ? "sg" : "d";
      c.textContent = ch;
      el.appendChild(c);
    }
  }
  function paintPlate(p, text, mode, zero) {
    var d = p.querySelector(".timer-digits");
    if (d) setDigits(d, text);
    p.classList.toggle("is-paused", mode === "paused");
    p.classList.toggle("is-zero", !!zero);
    var lab = p.querySelector(".timer-state");
    var want = mode === "paused" ? "paused" : zero ? "over time" : "";
    if (lab && lab.textContent !== want) lab.textContent = want;
  }
  function pulse(p) {
    p.classList.remove("pulse");
    void p.offsetWidth;
    p.classList.add("pulse");
    p.addEventListener("animationend", function () { p.classList.remove("pulse"); }, { once: true });
  }
  function paint(i, now) {
    var t = st[i], p = plateOf(i);
    if (!t || !p) return;
    var rem = leftOf(t, now);
    paintPlate(p, textOf(rem), t.mode, rem <= 0);
  }
  function emit() {
    for (var k = 0; k < listeners.length; k++) {
      try { listeners[k](); } catch (err) { /* never break the timer */ }
    }
  }

  function begin(i) {
    var d = dur(i);
    st[i] = { mode: "running", endAt: Date.now() + d, left: d, dur: d, zeroed: false };
    paint(i, Date.now());
    emit();
  }
  // `reveal=timer`: the plate carries data-timer-reveal. It is hidden and
  // stopped until the slide's last step (the press that reveals it) and starts
  // then, never on arrival. Anything short of that step, including coming back
  // to the slide or stepping back from it, puts it back to hidden and unstarted.
  function armed(i) {
    var p = plateOf(i);
    return !!(p && p.hasAttribute("data-timer-reveal"));
  }
  function arrive(i) {
    var p = plateOf(i);
    if (!p) return;
    if (armed(i)) {
      var p0 = plateOf(i);
      var need = p0.getAttribute("data-timer-reveal") === "first" ? 1 : A.steps();
      if (i === A.current() && A.step() >= need) {
        if (!st[i]) begin(i); else paint(i, Date.now());
      } else {
        if (st[i]) { delete st[i]; emit(); }
        paintPlate(p, fmt(dur(i) / 1000), "idle", false);
        p.classList.remove("pulse");
      }
      return;
    }
    if (st[i]) { paint(i, Date.now()); return; }
    begin(i);
  }

  // the repaint loop only reads the clock: the time is never counted here
  function tick() {
    var now = Date.now(), cur = A.current();
    for (var key in st) {
      var t = st[key], rem = leftOf(t, now);
      if (rem > 0) { t.zeroed = false; }
      else if (!t.zeroed) {
        t.zeroed = true;
        // the soft pulse is for a zero the room can see
        if (t.mode === "running" && Number(key) === cur && plateOf(cur)) {
          paint(cur, now); pulse(plateOf(cur));
        }
      }
    }
    paint(cur, now);
  }

  function command(cmd) {
    var i = A.current(), t = st[i];
    if (!t) return false;
    var now = Date.now();
    if (cmd === "pause") {
      if (t.mode === "running") { t.left = t.endAt - now; t.mode = "paused"; }
      else { t.endAt = now + t.left; t.mode = "running"; }
    } else if (cmd === "reset") {
      t.mode = "running"; t.endAt = now + t.dur; t.left = t.dur; t.zeroed = false;
    } else if (cmd === "add" || cmd === "sub") {
      var dlt = cmd === "add" ? MIN : -MIN;
      if (t.mode === "running") t.endAt += dlt; else t.left += dlt;
    } else return false;
    paint(i, now);
    emit();
    return true;
  }

  // Restart the whole talk: every timer goes back to unstarted (plates show
  // their full duration), then the current slide's timer starts fresh.
  function resetAll() {
    st = {};
    for (var k = 0; k < slides.length; k++) {
      var p = plateOf(k);
      if (!p) continue;
      paintPlate(p, fmt(dur(k) / 1000), "idle", false);
      p.classList.remove("pulse");
    }
    arrive(A.current());
    emit();
  }

  function state() {
    var i = A.current(), t = st[i];
    if (!t) return null;
    return { mode: t.mode, endAt: t.endAt, left: t.left, duration: t.dur };
  }

  // A preview (the presenter's clone of a slide) never runs: put its plate
  // back to the full duration, whatever the deck's own copy says right now.
  function freshen(root) {
    var ps = root.querySelectorAll(".timer-plate");
    for (var k = 0; k < ps.length; k++) {
      var d = (parseInt(ps[k].getAttribute("data-timer"), 10) || 0);
      paintPlate(ps[k], fmt(d), "idle", false);
      ps[k].classList.remove("pulse");
    }
  }

  A.timer = {
    state: state, command: command, freshen: freshen, resetAll: resetAll,
    addOnChange: function (fn) { if (typeof fn === "function") listeners.push(fn); }
  };
  A.addOnChange(arrive);
  if (A.addOnStep) A.addOnStep(function (i) { arrive(i); });
  document.addEventListener("keydown", function (e) {
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    var cmd = null;
    switch (e.key) {
      case "p": case "P": cmd = "pause"; break;
      case "0": cmd = "reset"; break;
      case "+": case "=": cmd = "add"; break;
      case "-": case "_": cmd = "sub"; break;
    }
    if (cmd && command(cmd)) e.preventDefault();
  });
  window.setInterval(tick, 200);
  document.addEventListener("visibilitychange", function () { if (!document.hidden) tick(); });
  arrive(A.current());
})();
"""


LIVE_JS = r"""
(function () {
  "use strict";
  // Live window capture (card `type: live`, spec: docs/live-capture.md).
  //
  // Two properties this module is built around:
  //  1. One capture SESSION per key (a card's `live_group`, else its slug).
  //     Hosts sharing a group share one stream, so several demo slides can
  //     show the same window with a single picker.
  //  2. The session is not the sink. Frames are only pulled while a <video> is
  //     attached to the stream, so every host detaches when its slide is not
  //     active and re-attaches on arrival. The session (and the permission)
  //     survive that, so re-attaching costs nothing and never re-prompts.
  var hosts = Array.prototype.slice.call(
    document.querySelectorAll("[data-live-surface]"));
  if (!hosts.length) return;

  var supportsCapture = !!(navigator.mediaDevices &&
    typeof navigator.mediaDevices.getDisplayMedia === "function");
  var secure = window.isSecureContext;
  var panel = document.getElementById("hookup-panel");
  var rowsEl = document.getElementById("hookup-rows");
  var slides = Array.prototype.slice.call(
    document.querySelectorAll(".animatic-slide"));

  var sessions = {};   // key -> { stream: MediaStream, label: string }
  var byKey = {};      // key -> [host, ...]

  function keyOf(host) {
    return host.getAttribute("data-live-group") ||
           host.getAttribute("data-live-slug");
  }
  function videoOf(host) { return host.querySelector("video.live-surface"); }
  function state(host, s) { host.setAttribute("data-live-state", s); }
  function status(host, msg) {
    var el = host.querySelector(".live-status");
    if (el) el.textContent = msg || "";
  }
  // A capture can die two ways. `ended` is final (stop sharing, and some
  // platforms' response to the window closing). `mute` is Firefox's response to
  // a captured window going away and it CAN recover, so it must never delete
  // the session: it surfaces a stalled state that hands the control back
  // without throwing away a session that might come back.
  function isEnded(session) {
    if (!session || !session.track) return false;
    try { return session.track.readyState === "ended"; } catch (err) { return false; }
  }
  function isStalled(session) {
    if (!session || !session.track) return false;
    try { return session.track.muted === true; } catch (err) { return false; }
  }
  function slideIndexOf(host) {
    var section = host.closest ? host.closest(".animatic-slide") : null;
    return section ? slides.indexOf(section) : -1;
  }
  function isActive(host) {
    var section = host.closest ? host.closest(".animatic-slide") : null;
    return !!(section && section.classList.contains("active"));
  }

  function attach(host) {
    var session = sessions[keyOf(host)];
    var video = videoOf(host);
    if (!session || !video) return;
    if (video.srcObject !== session.stream) video.srcObject = session.stream;
    status(host, "");
    fitFrame(host);
    if (video.readyState === 0 || !video.videoWidth) {
      video.addEventListener("loadedmetadata", function () { fitFrame(host); }, { once: true });
    }
    var p = video.play();
    if (p && p.catch) p.catch(function () {});
    state(host, "live");
  }

  // The frame must hug the PICTURE, not the zone. A `piece` box is inset from
  // the stage and shaped by the viewport, so a capture of any other shape gets
  // `object-fit: contain` bars inside it — and because the border is drawn on
  // the element, the frame outlined the bars: the "side and top bars" the deck
  // appeared to have on a shared window. Publishing the stream's real ratio and
  // letting the host take it removes the letterbox entirely.
  function fitFrame(host) {
    var video = videoOf(host);
    if (!video || !video.videoWidth || !video.videoHeight) return;
    var ratio = video.videoWidth / video.videoHeight;
    host.style.setProperty("--live-ratio", ratio.toFixed(4));
    host.setAttribute("data-live-ratio", "");
  }

  // A shared window can be resized mid-talk (or the capture switched to another
  // window), and the frame has to follow it rather than keep the first shape.
  window.addEventListener("resize", function () {
    hosts.forEach(fitFrame);
  });

  function detach(host) {
    var video = videoOf(host);
    if (!video) return;
    try { video.pause(); video.srcObject = null; } catch (err) {}
    // drop the fitted shape with the stream: a poster or the idle block should
    // get the zone's shape back, and re-attaching re-fits from the stream's own
    // cached metadata, so there is no visible jump.
    host.removeAttribute("data-live-ratio");
    host.style.removeProperty("--live-ratio");
  }

  // Read/measure surface for the diagnostics dump and the layout probe: the
  // states of every live host, and the frame fit, which is otherwise only
  // observable by eye (a letterboxed capture looks like "the frame has bars").
  // It never starts a capture — `fit` only measures an existing stream.
  if (window.animatic) {
    window.animatic.live = {
      hosts: function () { return hosts.slice(); },
      fit: fitFrame,
      accept: accept,
      states: function () {
        return hosts.map(function (h) { return h.getAttribute("data-live-state"); });
      }
    };
  }

  // Frame cost is gated on visibility: only the active slide holds a sink.
  // State follows the SESSION, not history: a hidden host of a hooked group is
  // "armed" the moment the group is hooked, even if it was never attached (it
  // must not offer to hook again), and "idle" means genuinely unhooked.
  // "stalled" means the session exists but the track is not delivering: the
  // control comes back and the session is kept, because a mute can recover.
  // "unavailable" hosts are left alone: they never had a session to report.
  function syncVisibility() {
    for (var i = 0; i < hosts.length; i++) {
      var host = hosts[i];
      if (host.getAttribute("data-live-state") === "unavailable") continue;
      var key = keyOf(host);
      var session = sessions[key];
      if (isEnded(session)) {
        teardown(key, "the shared window closed; hook up again");
        continue;
      }
      var stalled = isStalled(session);
      if (isActive(host)) {
        if (!session) continue;               // stays idle, control offered
        if (stalled) {
          detach(host);
          state(host, "stalled");
          status(host, "the shared window stopped; hook up again");
        } else {
          attach(host);
        }
      } else {
        detach(host);
        state(host, !session ? "idle" : (stalled ? "stalled" : "armed"));
        if (stalled) status(host, "the shared window stopped; hook up again");
      }
    }
    paint();
  }

  function teardown(key, message) {
    var session = sessions[key];
    if (session) {
      try {
        session.stream.getTracks().forEach(function (t) { t.stop(); });
      } catch (err) {}
      if (session.pc) { try { session.pc.close(); } catch (err) {} }
      delete sessions[key];
    }
    var group = byKey[key] || [];
    for (var i = 0; i < group.length; i++) {
      var video = videoOf(group[i]);
      if (video) { try { video.srcObject = null; } catch (err) {} }
      state(group[i], "idle");
      if (message) status(group[i], message);
    }
    paint();
  }

  // Register a stream as the session for `key` and watch its track. Shared by
  // hook() (this window captured it) and accept() (the presenter window did).
  function adopt(key, stream, track, label, pc) {
    sessions[key] = { stream: stream, track: track, label: label, pc: pc };
    if (track && track.addEventListener) {
      track.addEventListener("ended", function () {
        syncVisibility();   // isEnded() sees it and tears the session down
      });
      track.addEventListener("mute", function () {
        syncVisibility();   // stalled, control handed back, session kept
      });
      track.addEventListener("unmute", function () {
        syncVisibility();   // came back: attach again
      });
    }
    syncVisibility();
  }

  // Resolve once the connection has gathered its candidates (or a moment
  // later): the two windows exchange one offer and one answer over postMessage,
  // so there is no trickle channel to send candidates late.
  function gathered(pc) {
    return new Promise(function (resolve) {
      if (pc.iceGatheringState === "complete") { resolve(); return; }
      var done = function () { pc.removeEventListener("icegatheringstatechange", check); resolve(); };
      var check = function () { if (pc.iceGatheringState === "complete") done(); };
      pc.addEventListener("icegatheringstatechange", check);
      setTimeout(done, 2500);
    });
  }

  // The presenter window picked the window (the browser only starts a capture
  // from a click in the document that calls getDisplayMedia, and the deck
  // cannot be clicked from there) and sends it here over a local peer
  // connection: its offer in, our answer out. Same session as hook() makes.
  function accept(slug, offer, label) {
    var host = null;
    for (var i = 0; i < hosts.length; i++) {
      if (hosts[i].getAttribute("data-live-slug") === slug) { host = hosts[i]; break; }
    }
    if (!host || host.getAttribute("data-live-state") === "unavailable" ||
        typeof RTCPeerConnection !== "function") {
      return Promise.reject(new Error("no live host for " + slug));
    }
    var key = keyOf(host);
    if (sessions[key]) teardown(key, "");
    status(host, "");
    var pc = new RTCPeerConnection({ iceServers: [] });
    pc.ontrack = function (ev) {
      if (sessions[key] && sessions[key].pc === pc) return;
      var stream = ev.streams && ev.streams[0] ? ev.streams[0] : new MediaStream([ev.track]);
      adopt(key, stream, ev.track, label || "", pc);
    };
    pc.onconnectionstatechange = function () {
      if (pc.connectionState !== "failed" && pc.connectionState !== "closed") return;
      var s = sessions[key];
      if (s && s.pc === pc) teardown(key, "the shared window closed; hook up again");
    };
    return pc.setRemoteDescription({ type: "offer", sdp: offer })
      .then(function () { return pc.createAnswer(); })
      .then(function (answer) { return pc.setLocalDescription(answer); })
      .then(function () { return gathered(pc); })
      .then(function () { return pc.localDescription.sdp; });
  }

  function hook(key) {
    var group = byKey[key] || [];
    if (!group.length) return;
    // Re-hooking replaces whatever is there: a stalled or dead session must not
    // linger, and a live one must not be silently doubled.
    if (sessions[key]) teardown(key, "");
    status(group[0], "");
    navigator.mediaDevices.getDisplayMedia({
      video: { displaySurface: "window" },
      audio: false,
      // never offer this deck's own tab: the hall of mirrors
      selfBrowserSurface: "exclude",
      surfaceSwitching: "include"
    }).then(function (stream) {
      var track = stream.getVideoTracks()[0];
      var label = "";
      try { label = (track && track.label) || ""; } catch (err) {}
      adopt(key, stream, track, label, null);
    }).catch(function (err) {
      var name = err && err.name ? err.name : "error";
      status(group[0], "capture refused: " + name);
      paint();
    });
  }

  // ---- the hookup panel: one row per session key -------------------------

  function makeButton(text, onClick) {
    var b = document.createElement("button");
    b.type = "button";
    b.className = "hookup-button";
    b.textContent = text;
    b.addEventListener("click", onClick);
    return b;
  }

  function paint() {
    // every state change ends here: tell the presenter window, which would
    // otherwise show the state as of the last slide change
    try { document.dispatchEvent(new Event("animatic-live-state")); } catch (err) {}
    if (!rowsEl) return;
    rowsEl.textContent = "";
    var keys = Object.keys(byKey);
    for (var i = 0; i < keys.length; i++) {
      var key = keys[i];
      var group = byKey[key];
      var session = sessions[key];
      var row = document.createElement("div");
      row.className = "hookup-row";
      if (session) row.setAttribute("data-hooked", "1");

      var name = document.createElement("p");
      name.className = "hookup-name";
      name.textContent = key;
      row.appendChild(name);

      var cues = [];
      for (var j = 0; j < group.length; j++) {
        var idx = slideIndexOf(group[j]);
        if (idx >= 0) cues.push(idx + 1);
      }
      var where = document.createElement("p");
      where.className = "hookup-where";
      where.textContent = cues.length > 1
        ? "slides " + cues.join(", ")
        : "slide " + (cues[0] || "?");
      row.appendChild(where);

      var stateEl = document.createElement("p");
      stateEl.className = "hookup-state";
      stateEl.textContent = session
        ? ("hooked" + (session.label ? ": " + session.label : ""))
        : "not hooked";
      row.appendChild(stateEl);

      var actions = document.createElement("div");
      actions.className = "hookup-actions";
      if (session) {
        actions.appendChild(makeButton("stop", function () { teardown(key, ""); }));
      } else {
        actions.appendChild(makeButton("hook up", function () { hook(key); }));
      }
      actions.appendChild(makeButton("go", function () {
        var idx = slideIndexOf(group[0]);
        if (idx >= 0 && window.animatic && window.animatic.go) {
          window.animatic.go(idx);
        }
        closePanel();
      }));
      row.appendChild(actions);
      rowsEl.appendChild(row);
    }
  }

  function openPanel() {
    if (!panel) return;
    panel.classList.add("open");
    paint();
  }
  function closePanel() {
    if (panel) panel.classList.remove("open");
  }
  function togglePanel() {
    if (!panel) return;
    if (panel.classList.contains("open")) closePanel();
    else openPanel();
  }

  // ---- wiring ------------------------------------------------------------

  for (var i = 0; i < hosts.length; i++) {
    (function (host) {
      var key = keyOf(host);
      if (!byKey[key]) byKey[key] = [];
      byKey[key].push(host);

      var start = host.querySelector(".live-start");
      var stop = host.querySelector(".live-stop");

      if (!supportsCapture || !videoOf(host)) {
        state(host, "unavailable");
        if (start) start.disabled = true;
        status(host, secure
          ? "This browser does not offer window capture."
          : "Window capture needs a secure context: open this deck over file:// or http://localhost.");
        return;
      }

      if (start) {
        start.addEventListener("click", function () { hook(key); });
      }
      if (stop) {
        stop.addEventListener("click", function () { teardown(key, "stopped"); });
      }
    })(hosts[i]);
  }

  document.addEventListener("keydown", function (e) {
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    if (e.key === "d" || e.key === "D") { e.preventDefault(); togglePanel(); }
    else if (e.key === "Escape") closePanel();
  });

  if (window.animatic) window.animatic.onChange = function () { syncVisibility(); };
  paint();
  syncVisibility();
})();
"""


# ---------------------------------------------------------------------------
# PRESENTER window (the deck side: docs/presenter-view.md)
# ---------------------------------------------------------------------------

PRESENTER_JS = r"""
(function () {
  "use strict";
  // Two-window presenter view. 's' opens a SECOND window holding the speaker
  // UI; this module owns that window, holds its handle, and pushes the current
  // state on every pager change. The deck stays the single source of truth and
  // nothing is read back except navigation requests.
  //
  // Why postMessage and not BroadcastChannel/localStorage: a deck opened from
  // file:// has an opaque origin and every file:// document gets its own, so
  // two windows over the same folder are NOT same-origin and the same-origin
  // channels never connect. postMessage is origin-agnostic by design, which is
  // exactly what a folder-opened deck needs. `event.origin` is the string
  // "null" for an opaque origin and is useless as a check, so the window
  // handle (event.source) is what identifies the peer here.
  var WIN_NAME = "animatic-presenter";
  var win = null;
  var slides = Array.prototype.slice.call(
    document.querySelectorAll(".animatic-slide"));
  var statusEl = document.getElementById("deck-status");
  var startedAt = Date.now();   // the talk clock; the presenter can restart it

  function say(msg) {
    if (!statusEl) return;
    statusEl.textContent = msg || "";
    if (msg) statusEl.classList.add("open");
    else statusEl.classList.remove("open");
  }

  function notesOf(sec) {
    var vo = [], stage = [];
    var aside = sec.querySelector(".notes");
    if (aside) {
      var kids = aside.children;
      for (var i = 0; i < kids.length; i++) {
        var k = kids[i];
        // stage notes carry `stage-note`, never `stage`: `.stage` is the
        // present view's fixed full-viewport slide container, and a paragraph
        // matching it leaves the notes panel entirely.
        if (k.className && /(^|\s)stage-note(\s|$)/.test(k.className)) {
          stage.push(k.innerHTML);
        } else {
          // a list or a code block keeps its wrapper: the innerHTML of a <ul>
          // is a row of bare <li>s, and the bullets the presenter reads would
          // lose their markers in the other window.
          var tag = k.tagName ? k.tagName.toUpperCase() : "";
          vo.push((tag === "UL" || tag === "OL" || tag === "PRE")
                  ? k.outerHTML : k.innerHTML);
        }
      }
    }
    return { vo: vo, stage: stage };
  }

  // A preview is a clone of the slide the deck already renders: same markup,
  // same relative srcs (presenter.html sits beside index.html), so the theme
  // styles it with no second stylesheet and no second build path.
  function previewOf(i) {
    if (i < 0 || i >= slides.length) return null;
    var sec = slides[i];
    // A live screen has nothing to preview, and a second sink attached to the
    // capture stream would pull frames for a thumbnail. It is never cloned:
    // the presenter shows a plain label instead.
    if (sec.querySelector("[data-live-surface]")) return null;
    var clone = sec.cloneNode(true);
    if (window.animatic.timer) window.animatic.timer.freshen(clone);
    var notes = clone.querySelector(".notes");
    if (notes && notes.parentNode) notes.parentNode.removeChild(notes);
    clone.classList.add("active");
    // A preview is a look, not a playback, and a second <video> costs a decoder
    // (a machine with hardware decoding has only a handful: the presenter's
    // previews were starving the deck's own video). So no <video> goes into the
    // presenter at all: each is swapped for a still frame taken from the deck's
    // own copy, or a labelled box when that copy has nothing decoded yet.
    var vids = clone.querySelectorAll("video");
    var srcs = sec.querySelectorAll("video");
    for (var j = 0; j < vids.length; j++) {
      var still = frameOf(srcs[j]);
      var rep;
      if (still) {
        rep = document.createElement("img");
        rep.setAttribute("src", still);
        rep.setAttribute("alt", vids[j].getAttribute("aria-label") || "video frame");
      } else {
        rep = document.createElement("div");
        rep.setAttribute("style", "aspect-ratio:16/9;width:100%;background:#111;" +
          "color:#bbb;display:flex;align-items:center;justify-content:center;" +
          "font:14px system-ui,sans-serif;text-align:center");
        rep.textContent = "video: " + ((vids[j].getAttribute("src") || "").split("/").pop() || "clip");
        waitForFrame(srcs[j]);
      }
      rep.className = vids[j].className;
      vids[j].parentNode.replaceChild(rep, vids[j]);
    }
    var focusable = clone.querySelectorAll("button, [tabindex]");
    for (var k = 0; k < focusable.length; k++) {
      focusable[k].setAttribute("tabindex", "-1");
    }
    return clone.outerHTML;
  }

  // One frame of the deck's own video as a small JPEG, or null when nothing is
  // decoded yet (or the canvas is tainted, as on file://).
  function frameOf(v) {
    try {
      if (!v || v.readyState < 2 || !v.videoWidth) return null;
      var w = Math.min(640, v.videoWidth);
      var h = Math.max(1, Math.round(w * v.videoHeight / v.videoWidth));
      var c = document.createElement("canvas");
      c.width = w; c.height = h;
      c.getContext("2d").drawImage(v, 0, 0, w, h);
      return c.toDataURL("image/jpeg", 0.7);
    } catch (err) { return null; }
  }
  // A video that has no frame yet (the next slide's, not warmed until after
  // the arrival is pushed) gets the presenter its still when it does.
  function waitForFrame(v) {
    if (!v || v.hasAttribute("data-preview-wait")) return;
    v.setAttribute("data-preview-wait", "");
    v.addEventListener("loadeddata", function () {
      v.removeAttribute("data-preview-wait");
      push();
    }, { once: true });
  }

  function liveCueOf(i) {
    var sec = slides[i];
    var host = sec ? sec.querySelector("[data-live-surface]") : null;
    if (!host) return null;
    return {
      slug: host.getAttribute("data-live-slug"),
      key: host.getAttribute("data-live-group") || host.getAttribute("data-live-slug"),
      state: host.getAttribute("data-live-state"),
      status: (host.querySelector(".live-status") || {}).textContent || ""
    };
  }

  function payload() {
    var i = window.animatic.current();
    var n = slides.length;
    return {
      type: "animatic-state",
      schema: "animatic.presenter.v1",
      index: i,
      count: n,
      step: window.animatic.step(),
      pressesDone: window.animatic.pressesDone(),
      steps: window.animatic.steps(),
      stepImages: window.animatic.stepImages(),
      startedAt: startedAt,
      notes: notesOf(slides[i]),
      nextNotes: i + 1 < n ? notesOf(slides[i + 1]) : null,
      preview: previewOf(i),
      nextPreview: previewOf(i + 1),
      liveCue: liveCueOf(i),
      timer: window.animatic.timer ? window.animatic.timer.state() : null
    };
  }

  // The presenter window may STOP a capture, never start one. getDisplayMedia
  // requires transient user activation in the document that calls it (MDN), and
  // a postMessage confers none, so a Start there would be refused by the browser
  // rather than honoured. Stopping needs no activation, and releasing a capture
  // is the thing you want within reach while presenting. Every live screen keeps
  // its own buttons in the deck either way, so nothing depends on this path.
  function stopLive(slug) {
    var all = document.querySelectorAll("[data-live-surface]");
    for (var i = 0; i < all.length; i++) {
      if (all[i].getAttribute("data-live-slug") !== slug) continue;
      var btn = all[i].querySelector(".live-stop");
      if (btn) btn.click();
      return;
    }
  }

  // The slide's Share / Stop buttons give way to the presenter window's while
  // it is open (body.presenter-open hides them), so the projector shows the
  // slide and the controls sit with the notes. The window handle is the only
  // truth: sync it wherever it can change.
  function syncOpen() {
    if (win && win.closed) win = null;
    document.body.classList.toggle("presenter-open", !!win);
  }
  document.addEventListener("animatic-live-state", function () { push(); });
  window.setInterval(syncOpen, 2000);   // a window closed with no goodbye

  function push() {
    if (!win || win.closed) { win = null; syncOpen(); return; }
    try { win.postMessage(payload(), "*"); }
    catch (err) { win = null; }
  }

  function openPresenter() {
    var w = window.open("presenter.html", WIN_NAME, "width=1180,height=820");
    if (!w) {
      // A keypress is a user gesture, so this only fires when the browser is
      // blocking pop-ups outright. Say so on the deck's own screen: a silent
      // failure here looks like a broken key.
      say("The presenter window was blocked. Allow pop-ups for this page, "
        + "then press s again.");
      return;
    }
    win = w;
    syncOpen();
    say("");
    push();
  }

  function closePresenter() {
    if (win && !win.closed) { try { win.close(); } catch (err) {} }
    win = null;
    syncOpen();
  }

  function togglePresenter() {
    if (win && !win.closed) closePresenter();
    else openPresenter();
  }

  window.addEventListener("message", function (e) {
    var d = e.data;
    if (!d || typeof d !== "object" || typeof d.type !== "string") return;
    if (d.type === "animatic-presenter-ready") {
      // the presenter loaded or was reloaded by hand: adopt its handle when
      // ours is gone, then re-push, so a reload re-syncs with nothing to click
      // The presenter repeats this hello every couple of seconds (it cannot see
      // a deck reload), carrying the deck run it last heard from. Answer only
      // when it is new to us or out of date, so a steady hello costs nothing.
      var fresh = !win || win.closed;
      if (fresh && e.source && e.source !== window) { win = e.source; syncOpen(); }
      if (fresh || d.have !== startedAt) push();
      return;
    }
    if (!win || e.source !== win || !window.animatic) return;
    if (d.type === "animatic-presenter-closed") { win = null; syncOpen(); return; }
    if (d.type === "animatic-live-offer" && d.slug && typeof d.sdp === "string") {
      var peer = e.source;
      var reply = function (m) { try { peer.postMessage(m, "*"); } catch (err) {} };
      if (!window.animatic.live) { reply({ type: "animatic-live-answer", slug: d.slug, error: "no live screens" }); return; }
      window.animatic.live.accept(d.slug, d.sdp, d.label).then(function (sdp) {
        reply({ type: "animatic-live-answer", slug: d.slug, sdp: sdp });
      }, function (err) {
        reply({ type: "animatic-live-answer", slug: d.slug, error: String(err && err.message || err) });
      });
      return;
    }
    if (d.type === "animatic-next") window.animatic.next();
    else if (d.type === "animatic-prev") window.animatic.prev();
    else if (d.type === "animatic-reload-media") window.animatic.reloadMedia();
    else if (d.type === "animatic-go" && typeof d.index === "number") {
      window.animatic.go(d.index);
    }
    else if (d.type === "animatic-restart-clock") {
      startedAt = Date.now();
      if (window.animatic.timer) window.animatic.timer.resetAll();
      push();
    }
    else if (d.type === "animatic-timer" && window.animatic.timer) {
      window.animatic.timer.command(d.cmd);
    }
    else if (d.type === "animatic-live" && d.action === "stop" && d.slug) {
      stopLive(d.slug);
    }
  });

  document.addEventListener("keydown", function (e) {
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    if (e.key === "s" || e.key === "S") { e.preventDefault(); togglePresenter(); }
  });

  // Every arrival, including the ones the live module drives.
  window.animatic.addOnChange(push);
  window.animatic.addOnStep(push);
  if (window.animatic.timer) window.animatic.timer.addOnChange(push);

  // Read-only surface for the diagnostics dump: whether a presenter window is
  // actually open right now. Nothing here drives the presenter.
  window.animatic.presenter = {
    open: function () { return !!(win && !win.closed); }
  };
})();
"""


# ---------------------------------------------------------------------------
# PRESENTER page (the presenter side: what runs in the second window)
# ---------------------------------------------------------------------------

PRESENTER_UI_JS = r"""
(function () {
  "use strict";
  // The presenter window (docs/presenter-view.md). It owns no deck: the deck
  // window pushes state in, and everything shown here comes from that message
  // plus the cue index the builder wrote into this page. Identity facts (cue
  // id, movement, ordinal, title, whether the screen is live) come from the
  // index so they come from the same parse as cues.json; the script, the
  // stage notes and the previews come from the deck, which owns them.
  var cues = [];
  try {
    cues = (JSON.parse(document.getElementById("cue-index").textContent) || {}).cues || [];
  } catch (err) { cues = []; }

  var state = null;
  var el = {};
  ["wall", "elapsed", "ordinal", "count", "cue", "title", "next-title",
   "preview", "next-preview", "notes", "next-notes", "status", "live"]
    .forEach(function (key) {
      el[key] = document.getElementById("presenter-" + key);
    });

  var KIND_LABEL = {
    black: "black beat", media: "media screen", stat: "stat screen",
    card: "card screen", lower: "lower third", credits: "credits roll"
  };

  function say(msg) {
    if (!el.status) return;
    el.status.textContent = msg || "";
    if (msg) el.status.classList.add("open");
    else el.status.classList.remove("open");
  }

  function label(text) {
    var p = document.createElement("p");
    p.className = "preview-note";
    p.textContent = text;
    return p;
  }

  function cueTitle(cue) {
    if (!cue) return "end of deck";
    return cue.title || KIND_LABEL[cue.kind] || "screen " + cue.ordinal;
  }

  function fillNotes(node, notes) {
    if (!node) return;
    node.textContent = "";
    if (!notes) return;
    var i, p, box;
    for (i = 0; i < notes.vo.length; i++) {
      var m = notes.vo[i];
      if (/^\s*<(ul|ol|pre|div|blockquote)\b/i.test(m)) {
        // a list, a code block or a quote is a block of its own: any of them
        // inside a <p> is invalid markup, and the bullets would lose their
        // indentation
        box = document.createElement("div");
        box.className = "note-block";
        box.innerHTML = m;
        node.appendChild(box);
        continue;
      }
      p = document.createElement("p");
      // the deck's own notes markup, builder-escaped static output
      p.innerHTML = m;
      node.appendChild(p);
    }
    for (i = 0; i < notes.stage.length; i++) {
      p = document.createElement("p");
      // `stage-note`, not `stage`: `.stage` is the deck's fixed
      // full-viewport slide container and would swallow this paragraph
      p.className = "stage-note";
      p.innerHTML = notes.stage[i];
      node.appendChild(p);
    }
  }

  // A cloned video is a still: one decode, one frame, no second playback.
  function holdStill(video) {
    function seek() {
      try { video.currentTime = Math.min(0.05, video.duration || 0.1); }
      catch (err) {}
    }
    if (video.readyState >= 1) seek();
    else video.addEventListener("loadedmetadata", seek, { once: true });
  }

  // A removed <video> is not a stopped one: it keeps its connection and its
  // decoder until the browser garbage-collects it, and a machine with hardware
  // decoding has only a handful. Two new previews per slide change used to pile
  // up that way and starve the deck window's own video. Let go explicitly.
  function releaseVideos(node) {
    var old = node.querySelectorAll("video");
    for (var i = 0; i < old.length; i++) {
      try { old[i].pause(); old[i].removeAttribute("src"); old[i].load(); }
      catch (err) { /* never break the presenter */ }
    }
  }

  function fillPreview(node, html, cue) {
    if (!node) return;
    releaseVideos(node);
    node.textContent = "";
    if (!cue) { node.appendChild(label("end of deck")); return; }
    if (cue.live) {
      // a live window has nothing to preview, and a second sink would pull
      // frames off the capture for a thumbnail
      node.appendChild(label("live window capture, no preview"));
      return;
    }
    if (!html) { node.appendChild(label("no preview")); return; }
    node.innerHTML = html;
    var vids = node.querySelectorAll("video[data-preview-still]");
    for (var i = 0; i < vids.length; i++) holdStill(vids[i]);
  }

  function two(n) { return (n < 10 ? "0" : "") + n; }

  function tick() {
    var now = new Date();
    if (el.wall) {
      el.wall.textContent = two(now.getHours()) + ":" + two(now.getMinutes())
        + ":" + two(now.getSeconds());
    }
    if (el.elapsed && state && state.startedAt) {
      var s = Math.max(0, Math.floor((Date.now() - state.startedAt) / 1000));
      var h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60);
      el.elapsed.textContent = (h ? h + ":" + two(m) : String(m)) + ":" + two(s % 60);
    }
  }

  // The current screen's countdown (state comes from the deck: mode, end time,
  // time left, duration). The arithmetic is local, from the same wall clock,
  // so it stays live between pushes; the deck pushes again on every change.
  function timerText(rem) {
    function fmtT(sec) {
      var h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
      return h ? h + ":" + two(m) + ":" + two(s) : m + ":" + two(s);
    }
    if (rem > 0) return fmtT(Math.ceil(rem / 1000));
    var over = Math.floor(-rem / 1000);
    return over === 0 ? "0:00" : "+" + fmtT(over);
  }
  function paintTimer() {
    var box = document.getElementById("presenter-timer");
    if (!box) return;
    var t = state && state.timer;
    box.hidden = !t;
    if (!t) return;
    var rem = t.mode === "running" ? t.endAt - Date.now() : t.left;
    var digits = document.getElementById("presenter-timer-digits");
    var lab = document.getElementById("presenter-timer-state");
    if (digits) digits.textContent = timerText(rem);
    if (lab) lab.textContent = t.mode === "paused" ? "paused" : rem <= 0 ? "over time" : "";
    box.classList.toggle("is-paused", t.mode === "paused");
    box.classList.toggle("is-zero", rem <= 0);
  }

  function fitNotes() {
    // Fit ladder for the pane being read from. The notes are why this window
    // exists, so a scroll mid-sentence is the LAST resort, not the default.
    // Measured on the deck's own worst screen (3300 chars of notes):
    //   rung 0 natural flow        - fits a median screen
    //   rung 1 two columns         - fits the worst screen at 1080p, not at 800
    //   rung 2 solo                - the current pane takes the whole width and
    //                                next-up steps aside (the presenter still
    //                                has cue id, movement and position in the
    //                                header, and the next notes come back the
    //                                moment a screen fits again)
    // Beyond that the pane scrolls and says nothing, which is honest: there is
    // no font size left that is still readable at a glance.
    var panes = document.querySelector(".presenter-panes");
    var pane = document.querySelector(".presenter-pane-current");
    if (!pane || !panes) return;
    var notes = pane.querySelector(".presenter-notes");
    if (!notes) return;
    panes.classList.remove("solo");
    notes.classList.remove("two-col");
    if (pane.scrollHeight <= pane.clientHeight + 2) { tieNextPreview(panes); return; }   // rung 0 holds
    notes.classList.add("two-col");
    if (pane.scrollHeight <= pane.clientHeight + 2) { tieNextPreview(panes); return; }   // rung 1 holds
    panes.classList.add("solo");                              // rung 2
  }

  // The current screen's preview is the one that gives up space, so next-up's
  // must never end up the bigger of the two: it reads as "the next screen is the
  // important one". Measured (probe, 1920x1080, long notes): current shrank to
  // 219px while next-up sat at 238px. CSS cannot compare two boxes, so the
  // settled height is published as a variable and next-up caps itself to it.
  function tieNextPreview(panes) {
    var cur = document.querySelector(".presenter-pane-current .preview");
    if (!cur || !panes) return;
    panes.style.setProperty("--cur-preview-h", Math.round(cur.getBoundingClientRect().height) + "px");
  }

  function paint() {
    if (!state) return;
    var i = state.index;
    var cur = cues[i] || null, nxt = cues[i + 1] || null;
    if (el.ordinal) el.ordinal.textContent = String(i + 1);
    if (el.count) el.count.textContent = String(cues.length || state.count);
    if (el.cue) {
      el.cue.textContent = cur
        ? cur.id + (cur.movement_label ? " \u00b7 " + cur.movement_label : "")
          + (state.steps
            ? (state.stepImages
                ? " \u00b7 step " + state.step + " of " + state.steps
                : " \u00b7 item " + state.step + " / " + state.steps)
            : "")
        : "";
    }
    if (el.title) el.title.textContent = cueTitle(cur);
    if (el["next-title"]) el["next-title"].textContent = cueTitle(nxt);
    fillPreview(el.preview, state.preview, cur);
    fillPreview(el["next-preview"], state.nextPreview, nxt);
    fillNotes(el.notes, state.notes);
    fillNotes(el["next-notes"], state.nextNotes);
    if (el.notes) {
      var nm = el.notes.querySelectorAll(".next-mark");
      for (var mj = 0; mj < nm.length; mj++) {
        nm[mj].classList.toggle("done", mj < (state.pressesDone || 0));
        nm[mj].classList.toggle("up", mj === (state.pressesDone || 0));
      }
    }
    fillLive(state.liveCue);
    paintTimer();
    fitNotes();
    say("");
  }

  function liveLabel(state_) {
    return state_ === "live" ? "sharing a window"
      : state_ === "stalled" ? "share stopped"
      : state_ === "armed" ? "hooked, on another screen"
      : state_ === "unavailable" ? "window capture is not available here"
      : "not hooked up";
  }

  // Share and Stop live here while this window is open (the deck hides its own
  // slide buttons then). getDisplayMedia wants a click in the document that
  // calls it, so THIS window captures and sends the stream to the deck over a
  // local peer connection: offer out, answer back, both over postMessage. The
  // deck owns the session either way; this window only owns the capture.
  var cap = null;        // { key, stream, pc } while this window holds a capture
  var liveNote = "";
  var liveSig = null;
  var canShare = !!(navigator.mediaDevices && navigator.mediaDevices.getDisplayMedia &&
                    typeof RTCPeerConnection === "function");

  function releaseCapture() {
    if (!cap) return;
    var c = cap;
    cap = null;
    try { c.stream.getTracks().forEach(function (t) { t.stop(); }); } catch (err) {}
    try { c.pc.close(); } catch (err) {}
  }
  function noteLive(msg) {
    liveNote = msg || "";
    liveSig = null;
    if (state) fillLive(state.liveCue);
  }
  function gathered(pc) {
    return new Promise(function (resolve) {
      if (pc.iceGatheringState === "complete") { resolve(); return; }
      var done = function () { pc.removeEventListener("icegatheringstatechange", check); resolve(); };
      var check = function () { if (pc.iceGatheringState === "complete") done(); };
      pc.addEventListener("icegatheringstatechange", check);
      setTimeout(done, 2500);
    });
  }
  function giveUp(mine, msg) {
    if (cap !== mine) return;
    releaseCapture();
    post({ type: "animatic-live", action: "stop", slug: mine.slug });
    noteLive(msg);
  }

  function shareLive(cue) {
    releaseCapture();
    noteLive("");
    navigator.mediaDevices.getDisplayMedia({
      video: { displaySurface: "window" },
      audio: false,
      selfBrowserSurface: "exclude",
      surfaceSwitching: "include"
    }).then(function (stream) {
      var track = stream.getVideoTracks()[0];
      var pc = new RTCPeerConnection({ iceServers: [] });
      var mine = { key: cue.key, slug: cue.slug, stream: stream, pc: pc };
      cap = mine;
      pc.addTrack(track, stream);
      // the browser's own "stop sharing" bar ends the track here, not in the deck
      track.addEventListener("ended", function () { giveUp(mine, ""); });
      pc.onconnectionstatechange = function () {
        if (pc.connectionState === "failed") {
          giveUp(mine, "could not link to the deck window; close this window and share from the slide");
        }
      };
      setTimeout(function () {
        if (cap === mine && pc.connectionState !== "connected") {
          giveUp(mine, "could not link to the deck window; close this window and share from the slide");
        }
      }, 10000);
      return pc.createOffer().then(function (o) { return pc.setLocalDescription(o); })
        .then(function () { return gathered(pc); })
        .then(function () {
          post({ type: "animatic-live-offer", slug: cue.slug,
                 sdp: pc.localDescription.sdp, label: (track && track.label) || "" });
        });
    }).catch(function (err) {
      releaseCapture();
      noteLive("capture refused: " + (err && err.name ? err.name : "error"));
    });
  }

  function fillLive(cue) {
    var node = el.live;
    if (!node) return;
    // The deck pushes constantly (clock, timers). Rebuilding the buttons under
    // a click in progress would swallow it, so only repaint on a change.
    var sig = cue ? [cue.slug, cue.state, liveNote, !!cap].join("|") : "";
    if (sig === liveSig) return;
    liveSig = sig;
    node.textContent = "";
    if (!cue) { node.classList.remove("open"); return; }
    // the deck dropped the session (its d panel, a closed window): let go of
    // the capture so the browser's sharing indicator goes out with it
    if (cap && cap.key === cue.key && cue.state === "idle" &&
        cap.pc.connectionState === "connected") {
      releaseCapture();
      sig = [cue.slug, cue.state, liveNote, false].join("|");
      liveSig = sig;
    }
    node.classList.add("open");
    // NOT label(): that helper makes a `.preview-note`, which is absolutely
    // positioned to cover the preview box — it would swallow the whole pane
    var text = document.createElement("span");
    text.className = "presenter-live-state";
    text.textContent = liveNote || liveLabel(cue.state);
    node.appendChild(text);
    function add(cls, label, onClick) {
      var b = document.createElement("button");
      b.type = "button";
      b.className = cls;
      b.textContent = label;
      b.addEventListener("click", onClick);
      node.appendChild(b);
    }
    if (canShare && cue.state !== "unavailable" && cue.state !== "live" && cue.state !== "armed") {
      add("presenter-live-start", cue.state === "stalled" ? "Share again" : "Share a window",
          function () { shareLive(cue); });
    }
    if (cue.state === "live" || cue.state === "stalled" || cue.state === "armed") {
      add("presenter-live-stop", "Stop sharing", function () {
        releaseCapture();
        post({ type: "animatic-live", action: "stop", slug: cue.slug });
      });
    }
  }

  function post(msg) {
    if (window.opener) window.opener.postMessage(msg, "*");
  }

  function hello() {
    if (!window.opener) {
      say("Open this window from the deck: press s in the deck window.");
      return;
    }
    post({ type: "animatic-presenter-ready", schema: "animatic.presenter.v1",
           have: state ? state.startedAt : null });
  }

  window.addEventListener("message", function (e) {
    var d = e.data;
    if (!d || typeof d !== "object") return;
    if (window.opener && e.source !== window.opener) return;
    if (d.type === "animatic-live-answer") {
      if (!cap || cap.slug !== d.slug) return;
      var mine = cap;
      if (d.error) { giveUp(mine, "the deck could not take the share: " + d.error); return; }
      mine.pc.setRemoteDescription({ type: "answer", sdp: d.sdp }).catch(function () {
        giveUp(mine, "could not link to the deck window; close this window and share from the slide");
      });
      return;
    }
    if (d.type !== "animatic-state") return;
    state = d;
    paint();
    tick();
  });

  // tell the deck we are gone so its slide gets its own buttons back
  window.addEventListener("pagehide", function () {
    releaseCapture();
    post({ type: "animatic-presenter-closed" });
  });

  var restartBtn = document.getElementById("presenter-restart");
  if (restartBtn) {
    restartBtn.addEventListener("click", function () { post({ type: "animatic-restart-clock" }); });
  }
  // Notes above or below the slide image: a laptop held at standing height
  // wants the notes at the top of the screen. Default is the image on top.
  // Remembered per browser, never required (file:// storage can be blocked).
  var flipBtn = document.getElementById("presenter-flip");
  function setNotesTop(on, save) {
    document.body.classList.toggle("notes-top", on);
    if (flipBtn) flipBtn.setAttribute("aria-pressed", on ? "true" : "false");
    if (save) { try { localStorage.setItem("animatic-notes-top", on ? "1" : "0"); } catch (err) {} }
    fitNotes();
  }
  function flipNotes() { setNotesTop(!document.body.classList.contains("notes-top"), true); }
  try { if (localStorage.getItem("animatic-notes-top") === "1") setNotesTop(true, false); } catch (err) {}
  if (flipBtn) flipBtn.addEventListener("click", flipNotes);
  // Text size of the current screen's notes only (next-up stays small).
  // Steps of 10%, remembered like the flip.
  var notesScale = 1;
  function setNotesScale(x, save) {
    notesScale = Math.max(0.6, Math.min(2.5, Math.round(x * 10) / 10));
    document.body.style.setProperty("--notes-scale", String(notesScale));
    if (save) { try { localStorage.setItem("animatic-notes-scale", String(notesScale)); } catch (err) {} }
    fitNotes();
  }
  try {
    var savedScale = parseFloat(localStorage.getItem("animatic-notes-scale"));
    if (savedScale > 0) setNotesScale(savedScale, false);
  } catch (err) {}
  var smallerBtn = document.getElementById("presenter-smaller");
  var biggerBtn = document.getElementById("presenter-bigger");
  if (smallerBtn) smallerBtn.addEventListener("click", function () { setNotesScale(notesScale - 0.1, true); });
  if (biggerBtn) biggerBtn.addEventListener("click", function () { setNotesScale(notesScale + 0.1, true); });
  var prevBtn = document.getElementById("presenter-prev");
  var nextBtn = document.getElementById("presenter-next");
  if (prevBtn) {
    prevBtn.addEventListener("click", function () { post({ type: "animatic-prev" }); });
  }
  if (nextBtn) {
    nextBtn.addEventListener("click", function () { post({ type: "animatic-next" }); });
  }

  document.addEventListener("keydown", function (e) {
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    switch (e.key) {
      case "ArrowRight": case "ArrowDown": case "PageDown": case " ":
        e.preventDefault(); post({ type: "animatic-next" }); break;
      case "ArrowLeft": case "ArrowUp": case "PageUp":
        e.preventDefault(); post({ type: "animatic-prev" }); break;
      case "r": case "R":
        post({ type: "animatic-reload-media" });
        say("reloading this slide's media in the deck");
        window.setTimeout(function () { say(""); }, 1800);
        break;
      case "s": case "S": e.preventDefault(); window.close(); break;
      case "t": case "T": post({ type: "animatic-restart-clock" }); break;
      case "f": case "F": flipNotes(); break;
      case "[": setNotesScale(notesScale - 0.1, true); break;
      case "]": setNotesScale(notesScale + 0.1, true); break;
      case "p": case "P": post({ type: "animatic-timer", cmd: "pause" }); break;
      case "0": post({ type: "animatic-timer", cmd: "reset" }); break;
      case "+": case "=": post({ type: "animatic-timer", cmd: "add" }); break;
      case "-": case "_": post({ type: "animatic-timer", cmd: "sub" }); break;
    }
  });

  window.setInterval(tick, 1000);
  window.setInterval(paintTimer, 250);
  hello();
  tick();
  if (window.opener && !state) say("Waiting for the deck to send its state.");
  window.setTimeout(hello, 1500);   // a slow deck still gets its handshake
  // A reloaded deck forgets this window and a presenter has no way to see that
  // happen, so keep saying hello: the deck re-adopts us and re-pushes state, and
  // ignores the hello while nothing has changed.
  window.setInterval(hello, 2000);

  // Test surface for the layout harness (tools/presenter-probe.html): it fills
  // this page with a constructed state and drives the REAL paint path, so what
  // it measures is what a live push renders — including the notes fit ladder,
  // which only runs inside paint(). Render-only by design: it never posts back
  // to a deck, so a probe can never move a talk.
  window.presenter = {
    apply: function (s) { state = s; paint(); },
    current: function () { return state; }
  };
})();
"""


DEBUG_JS = r"""
(function () {
  "use strict";
  // Diagnostic dump on `i`. Three audiences, one payload:
  //   - the console, so the presenter can copy-paste it as a bug report
  //   - an on-screen panel, because devtools may not be open in a room
  //   - window.animatic.debug(), so an agent driving the deck can read it
  // The load-bearing part is the HIT TEST: today's two bugs were "the control
  // is there but something is on top of it" and "the state hides the control",
  // and neither is visible to a state-only check. This dump answers both.
  var slides = Array.prototype.slice.call(
    document.querySelectorAll(".animatic-slide"));
  var stage = document.getElementById("stage");
  var box = document.getElementById("debug-panel");
  var out = document.getElementById("debug-output");
  var problems = [];

  window.addEventListener("error", function (e) {
    problems.push("error: " + String(e.message || e));
  });
  window.addEventListener("unhandledrejection", function (e) {
    var r = e && e.reason;
    problems.push("rejection: " + String((r && r.message) || r));
  });

  function describe(el) {
    if (!el) return null;
    var cls = (typeof el.className === "string" && el.className)
      ? "." + el.className.split(" ")[0] : "";
    return el.tagName + cls;
  }

  // Inactive slides are hidden with visibility, not display, so their controls
  // still have a real rect. Without this, a hit test on a screen you are not
  // looking at blames a cover that does not exist (measured: the deck reported
  // "covered" on a healthy slide before this check existed).
  function hiddenAncestor(el) {
    var n = el;
    var outermost = null;
    while (n && n !== document.body) {
      var s = window.getComputedStyle(n);
      if (s.display === "none" || s.visibility === "hidden" || s.opacity === "0") {
        outermost = describe(n);   // keep walking: the useful answer is the
      }                            // outermost hider (the slide), not the leaf
      n = n.parentElement;
    }
    return outermost;
  }

  function hit(el) {
    if (!el) return null;
    var r = el.getBoundingClientRect();
    if (!r.width || !r.height) {
      return { target: describe(el), visible: false, note: "zero size" };
    }
    var hidden = hiddenAncestor(el);
    if (hidden) {
      return {
        target: describe(el),
        visible: false,
        hiddenBy: hidden,
        note: "not on the active screen"
      };
    }
    var top = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
    return {
      target: describe(el),
      visible: true,
      rect: [Math.round(r.left), Math.round(r.top),
             Math.round(r.width), Math.round(r.height)],
      topAtCentre: describe(top),
      reachable: !!(top && (el === top || el.contains(top) || top.contains(el)))
    };
  }

  function trackOf(video) {
    try {
      var s = video && video.srcObject;
      return s && s.getVideoTracks ? s.getVideoTracks()[0] : null;
    } catch (err) { return null; }
  }

  function liveDump() {
    return Array.prototype.slice
      .call(document.querySelectorAll("[data-live-surface]"))
      .map(function (host) {
        var video = host.querySelector("video.live-surface");
        var state = host.getAttribute("data-live-state");
        var control = host.querySelector(
          state === "live" || state === "stalled" ? ".live-stop" : ".live-start");
        var track = trackOf(video);
        // letterbox: the frame hugging the picture is the thing a person
        // actually notices ("why does it have bars?"), and it is invisible to
        // every state check
        var box = host.getBoundingClientRect();
        var frameRatio = box.height ? box.width / box.height : null;
        var streamRatio = (video && video.videoWidth && video.videoHeight)
          ? video.videoWidth / video.videoHeight : null;
        return {
          slug: host.getAttribute("data-live-slug"),
          group: host.getAttribute("data-live-group"),
          state: state,
          video: video ? {
            hasStream: !!video.srcObject,
            paused: video.paused,
            readyState: video.readyState,
            size: video.videoWidth + "x" + video.videoHeight
          } : null,
          frame: { w: Math.round(box.width), h: Math.round(box.height) },
          streamRatio: streamRatio ? +streamRatio.toFixed(3) : null,
          letterboxed: (frameRatio && streamRatio)
            ? Math.abs(frameRatio - streamRatio) > 0.02 : null,
          track: track ? {
            label: track.label,
            muted: track.muted,
            readyState: track.readyState,
            enabled: track.enabled
          } : null,
          control: hit(control),
          status: (host.querySelector(".live-status") || {}).textContent || ""
        };
      });
  }

  function collect() {
    var cur = (window.animatic && window.animatic.current)
      ? window.animatic.current() : 0;
    var sec = slides[cur] || null;
    var heading = sec ? sec.querySelector(".slide-title") : null;
    var presenter = null;
    try {
      presenter = (window.animatic && window.animatic.presenter
        && window.animatic.presenter.open) ? window.animatic.presenter.open() : null;
    } catch (err) { presenter = "error: " + String(err); }
    return {
      schema: "animatic.debug.v1",
      deck: {
        slug: stage ? stage.getAttribute("data-deck") : null,
        title: document.title,
        screens: slides.length,
        hash: location.hash || "(none)"
      },
      env: {
        href: location.href,
        protocol: location.protocol,
        secureContext: window.isSecureContext,
        captureApi: !!(navigator.mediaDevices &&
                       navigator.mediaDevices.getDisplayMedia),
        viewport: window.innerWidth + "x" + window.innerHeight,
        dpr: window.devicePixelRatio
      },
      position: {
        ordinal: cur + 1,
        cue: sec ? sec.id : null,
        movement: sec ? Number(sec.getAttribute("data-movement")) : null,
        kind: sec ? sec.getAttribute("data-kind") : null,
        title: heading ? heading.textContent.trim() : null
      },
      panels: {
        notes: !!(document.getElementById("notes-panel") &&
                  document.getElementById("notes-panel").classList.contains("open")),
        hookup: !!(document.getElementById("hookup-panel") &&
                   document.getElementById("hookup-panel").classList.contains("open")),
        debug: !!(box && box.classList.contains("open"))
      },
      presenterOpen: presenter,
      hitTests: {
        nextButton: hit(document.getElementById("next-slide")),
        prevButton: hit(document.getElementById("prev-slide"))
      },
      live: liveDump(),
      problems: problems.slice(-8)
    };
  }

  function render(info) {
    var text = JSON.stringify(info, null, 2);
    if (out) out.textContent = text;
    console.log("--- animatic debug ---\n" + text + "\n--- end animatic debug ---");
    return text;
  }

  function toggle() {
    if (!box) return null;
    var opening = !box.classList.contains("open");
    if (opening) {
      var info = collect();
      box.classList.add("open");
      render(info);
      if (out && window.getSelection && document.createRange) {
        // pre-selected so a copy is one keystroke, no dragging
        var range = document.createRange();
        range.selectNodeContents(out);
        var sel = window.getSelection();
        sel.removeAllRanges();
        sel.addRange(range);
      }
      return info;
    }
    box.classList.remove("open");
    return null;
  }

  document.addEventListener("keydown", function (e) {
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    if (e.key === "i" || e.key === "I") { e.preventDefault(); toggle(); }
    else if (e.key === "Escape" && box && box.classList.contains("open")) {
      box.classList.remove("open");
    }
  });

  if (window.animatic) {
    window.animatic.debug = collect;
    window.animatic.debugToggle = toggle;
  }
})();
"""


MEDIA_JS = r"""
(function () {
  "use strict";
  // Media panel on `m`: every image and video in the deck, in slide order,
  // with what the browser has actually got (read from the elements, not
  // guessed), and a Load all button. Built for presenting from a served
  // folder, where a slow link used to leave slides blank with no error:
  //   ready    image decoded / video can play through without stalling
  //   loading  partly there (videos show how much is buffered)
  //   waiting  not asked for yet (videos stay preload="none" until near)
  //   failed   the request failed: a missing file shows up here
  // Load all warms videos two at a time, so images and the slide on screen
  // keep getting connections while it runs.
  var box = document.getElementById("media-panel");
  var list = document.getElementById("media-list");
  var sumEl = document.getElementById("media-summary");
  var btn = document.getElementById("media-load-all");
  if (!box || !list) return;
  var slides = Array.prototype.slice.call(
    document.querySelectorAll(".animatic-slide"));
  // A video that makes no progress for STALL_MS is skipped (marked stalled) so
  // one dead connection cannot hold the queue; MAX_MS caps a slow-but-moving one.
  var CONCURRENT = 2, STALL_MS = 12000, MAX_MS = 90000;
  var timer = null, running = false;

  // one row per file; a file shown on several slides is one row
  function inventory() {
    var rows = [], bySrc = {};
    for (var i = 0; i < slides.length; i++) {
      var els = slides[i].querySelectorAll("img.media-image, video.media-video");
      for (var j = 0; j < els.length; j++) {
        var el = els[j];
        // the attribute, not currentSrc: currentSrc stays "" on a video
        // until it loads, which would split one file into two rows
        var src = el.getAttribute("src") || "";
        if (!src) continue;
        var row = bySrc[src];
        if (!row) {
          row = { src: src, kind: el.tagName === "VIDEO" ? "video" : "image",
                  slides: [], els: [] };
          bySrc[src] = row; rows.push(row);
        }
        if (row.slides.indexOf(i) < 0) row.slides.push(i);
        row.els.push(el);
      }
    }
    return rows;
  }

  function bufferedPct(v) {
    var d = v.duration;
    if (!isFinite(d) || d <= 0) return 0;
    var got = 0;
    for (var k = 0; k < v.buffered.length; k++) got += v.buffered.end(k) - v.buffered.start(k);
    return Math.min(100, Math.round(got / d * 100));
  }

  function stateOf(row) {
    var best = { s: "waiting", pct: 0 };
    for (var k = 0; k < row.els.length; k++) {
      var el = row.els[k], st;
      if (row.kind === "image") {
        if (el.complete && el.naturalWidth > 0) st = { s: "ready", pct: 100 };
        else if (el.complete) st = { s: "failed", pct: 0 };
        else st = { s: "loading", pct: 0 };
      } else {
        var pct = bufferedPct(el);
        if (el.error || el.networkState === 3) st = { s: "failed", pct: 0 };
        else if (el.readyState >= 4 || (pct >= 100 && el.readyState >= 3)) st = { s: "ready", pct: pct };
        else if (el.hasAttribute("data-stalled")) st = { s: "stalled", pct: pct };
        else if (el.readyState > 0 || el.networkState === 2) st = { s: "loading", pct: pct };
        else st = { s: "waiting", pct: 0 };
      }
      if (rank(st.s) > rank(best.s)) best = st;
    }
    return best;
  }
  function rank(s) { return { failed: 5, ready: 4, loading: 3, stalled: 2, waiting: 1 }[s] || 0; }

  function name(src) {
    var q = src.split("?")[0];
    return decodeURIComponent(q.substring(q.lastIndexOf("/") + 1));
  }

  function paint() {
    var rows = inventory(), counts = { image: {}, video: {} }, html = [];
    for (var r = 0; r < rows.length; r++) {
      var row = rows[r], st = stateOf(row);
      counts[row.kind][st.s] = (counts[row.kind][st.s] || 0) + 1;
      counts[row.kind].all = (counts[row.kind].all || 0) + 1;
      var label = st.s;
      if (row.kind === "video" && st.s !== "failed" && st.s !== "waiting") label += " " + st.pct + "%";
      var nums = row.slides.map(function (n) { return n + 1; }).join(", ");
      html.push('<li class="media-row media-' + st.s + '" data-slide="' + row.slides[0] + '">' +
        '<span class="media-state">' + label + '</span>' +
        '<span class="media-kind">' + row.kind + '</span>' +
        '<span class="media-name">' + esc(name(row.src)) + '</span>' +
        '<span class="media-where">' + nums + '</span></li>');
    }
    list.innerHTML = html.join("");
    function line(kind) {
      var c = counts[kind];
      if (!c.all) return "";
      return kind + "s " + (c.ready || 0) + "/" + c.all + " ready" +
        (c.stalled ? " · " + c.stalled + " stalled" : "") +
        (c.failed ? " · " + c.failed + " failed" : "");
    }
    var parts = [line("image"), line("video")].filter(Boolean);
    sumEl.textContent = parts.join(" · ") + (running ? " · loading all…" : "");
    btn.disabled = running;
  }

  function esc(t) {
    return String(t).replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  }

  function isReady(v) {
    return v.readyState >= 4 || (v.readyState >= 3 && bufferedPct(v) >= 100);
  }

  // Every video in the deck, autoplay or not. Running it again retries the
  // ones that stalled or failed.
  function loadAll() {
    if (running) return;
    running = true;
    var queue = [];
    for (var i = 0; i < slides.length; i++) {
      var vids = slides[i].querySelectorAll("video.media-video");
      for (var j = 0; j < vids.length; j++) {
        // pinned: the pager's look-behind release leaves it alone
        vids[j].setAttribute("data-pinned", "");
        if (!isReady(vids[j])) queue.push({ v: vids[j], i: i });
      }
    }
    var active = 0;
    function pump() {
      while (active < CONCURRENT && queue.length) start(queue.shift());
      if (!active && !queue.length) { running = false; }
      paint();
    }
    function kick(v, i) {
      var retry = v.hasAttribute("data-stalled") || v.error || v.networkState === 3;
      v.removeAttribute("data-stalled");
      if (window.animatic && window.animatic.warm) window.animatic.warm(i);
      // warm() only touches autoplay videos, and only once; cover the rest,
      // and re-request one that stalled or failed
      if (v.preload !== "auto") v.preload = "auto";
      if (retry || (v.readyState === 0 && v.networkState !== 2)) {
        try { v.load(); } catch (err) { /* never break the panel */ }
      }
    }
    function start(job) {
      active++;
      var v = job.v, done = false, poll, lastSig = "", lastMove = Date.now(), began = Date.now();
      function finish(stalled) {
        if (done) return;
        done = true; clearInterval(poll);
        v.removeEventListener("canplaythrough", onDone);
        v.removeEventListener("error", onDone);
        if (stalled === true && !isReady(v)) v.setAttribute("data-stalled", "");
        active--; pump();
      }
      function onDone() { finish(false); }
      v.addEventListener("canplaythrough", onDone);
      v.addEventListener("error", onDone);
      kick(v, job.i);
      poll = setInterval(function () {
        if (isReady(v)) { finish(false); return; }
        var sig = v.readyState + ":" + bufferedPct(v) + ":" + v.networkState;
        if (sig !== lastSig) { lastSig = sig; lastMove = Date.now(); }
        if (Date.now() - lastMove > STALL_MS || Date.now() - began > MAX_MS) finish(true);
      }, 1000);
      if (isReady(v)) finish(false);
    }
    pump();
  }

  function open() {
    box.classList.add("open");
    paint();
    if (!timer) timer = setInterval(paint, 500);
  }
  function close() {
    box.classList.remove("open");
    if (timer) { clearInterval(timer); timer = null; }
  }
  function toggle() { if (box.classList.contains("open")) close(); else open(); }

  btn.addEventListener("click", function (e) { e.preventDefault(); loadAll(); });
  list.addEventListener("click", function (e) {
    var li = e.target.closest ? e.target.closest("li[data-slide]") : null;
    if (li && window.animatic) window.animatic.go(Number(li.getAttribute("data-slide")));
  });
  document.addEventListener("keydown", function (e) {
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    if (e.key === "m" || e.key === "M") { e.preventDefault(); toggle(); }
    else if (e.key === "Escape" && box.classList.contains("open")) close();
  });

  if (window.animatic) {
    window.animatic.media = function () {
      return inventory().map(function (row) {
        var st = stateOf(row);
        return { file: name(row.src), kind: row.kind, state: st.s,
                 buffered: st.pct, slides: row.slides.map(function (n) { return n + 1; }) };
      });
    };
    window.animatic.loadAllMedia = loadAll;
  }
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
    # the capture script ships only to decks that have a live screen, so a
    # deck with no live card keeps byte-identical HTML
    has_live = any(
        resolver.resolve(s.media_shot.slug).live
        for s in talk.screens
        if s.media_shot and s.media_shot.slug
    )
    live_script = f"<script>\n{LIVE_JS}\n</script>\n" if has_live else ""
    # the timer module ships only to decks that have a timer, so a deck with
    # none keeps byte-identical HTML
    timer_script = (f"<script>\n{TIMER_JS}\n</script>\n"
                    if any(s.timer is not None for s in talk.screens) else "")
    hookup = (
        '<aside class="hookup-panel" id="hookup-panel" aria-label="demo hookup">\n'
        '<h2 class="hookup-title">Demo hookup</h2>\n'
        '<p class="hookup-lede">Hook each live screen before the talk. '
        'The permission cannot be remembered, so this is once per session. '
        'Press <kbd>d</kbd> to close.</p>\n'
        '<div class="hookup-rows" id="hookup-rows"></div>\n'
        '</aside>\n'
    ) if has_live else ""
    doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} — present view</title>
{theme_style_blocks(theme)}
</head>
<body class="view-present">
<main class="stage" id="stage" data-deck="{html.escape(deck_slug(talk))}">
{chr(10).join(sections)}
</main>
<div class="progress-track"><div class="progress-fill" id="progress-fill"></div></div>
<nav class="pager-ui" aria-label="slides">
<button type="button" id="prev-slide" aria-label="previous">&#8249;</button>
<span class="counter"><span id="slide-cur">1</span> / <span id="slide-total">1</span></span>
<button type="button" id="next-slide" aria-label="next">&#8250;</button>
</nav>
<aside class="notes-panel" id="notes-panel" aria-live="polite"></aside>
<aside class="debug-panel" id="debug-panel" aria-label="diagnostics">
<div class="debug-head">diagnostics &middot; <code>i</code> to refresh &middot; <code>Esc</code> to close</div>
<pre id="debug-output" tabindex="0"></pre>
</aside>
<aside class="media-panel" id="media-panel" aria-label="media">
<div class="debug-head">media &middot; <code>m</code> or <code>Esc</code> to close &middot; click a row to go to its slide</div>
<div class="media-bar"><span id="media-summary"></span><button type="button" id="media-load-all" class="hookup-button">Load all</button></div>
<ol class="media-list" id="media-list"></ol>
</aside>
<p class="deck-status" id="deck-status" role="status" aria-live="polite"></p>
{hookup}<script>
{PAGER_JS}
</script>
{timer_script}<script>
{PRESENTER_JS}
</script>
<script>
{DEBUG_JS}
</script>
<script>
{MEDIA_JS}
</script>
{live_script}</body>
</html>
"""
    path = out_dir / "index.html"
    path.write_text(doc, encoding="utf-8")
    return path


def render_presenter(talk: Talk, resolver: MediaResolver, out_dir: Path) -> Path:
    """The presenter window: present/presenter.html (docs/presenter-view.md).

    The speaker UI lives in a SECOND window, which means it cannot be a copy of
    the present view: two windows over the same folder may not be same-origin
    (a deck opened from `file://` gets an opaque origin per document), so the
    presenter cannot be loaded with its own pager and driven from outside. The
    split is therefore: this page carries the identity half of every cue (id,
    ordinal, movement, title, kind, live) as a build-time index, and the deck
    pushes the runtime half (script, stage notes, previews, position) by
    postMessage. The index is emitted from the same parse as cues.json, so a
    live screen is marked preview-less BEFORE anything runs, and the property
    suite can assert it without a browser.

    Relative-path rule: this file sits beside `index.html` in the out root's
    `present/` dir, which is what lets the deck's cloned slide markup (with its
    `../_media/...` srcs) render here unchanged.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    theme = resolve_theme(talk)
    meta = talk.meta
    title = html.escape(str(meta.get("title", deck_slug(talk))))

    index = []
    for screen in talk.screens:
        shot = screen.media_shot
        ref = resolver.resolve(shot.slug) if (shot and shot.slug) else None
        mv = next((m for m in talk.movements if m.index == screen.movement), None)
        index.append({
            "id": f"{deck_slug(talk)}-{screen.idx:03d}",
            "ordinal": screen.idx,
            "movement": screen.movement,
            "movement_label": mv.label if mv is not None else "",
            "kind": screen_kind(screen),
            "title": plain_md(screen_title(screen)) if screen_title(screen) else "",
            # a live screen has nothing to preview: the presenter labels it
            # instead of showing a thumbnail
            "live": bool(ref is not None and ref.live),
        })

    cue_index = json.dumps(
        {"schema": "animatic.presenter.v1",
         "deck": str(meta.get("title", deck_slug(talk))),
         "cues": index},
        ensure_ascii=False, separators=(",", ":"),
    ).replace("<", "\\u003c")   # cannot open a script element from data

    doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} — presenter view</title>
{theme_style_blocks(theme)}
</head>
<body class="view-presenter">
<div class="presenter">
<header class="presenter-head">
<p class="presenter-deck">{title}</p>
<p class="presenter-timer" id="presenter-timer" hidden><span class="presenter-timer-label">timer</span>
<span class="presenter-timer-digits" id="presenter-timer-digits">0:00</span>
<span class="presenter-timer-state" id="presenter-timer-state"></span>
<span class="presenter-timer-keys">p pause &middot; 0 reset &middot; + / - one minute</span></p>
<p class="presenter-clock"><span id="presenter-wall">--:--:--</span>
<span class="presenter-elapsed">elapsed <span id="presenter-elapsed">0:00</span>
<button type="button" id="presenter-restart" class="presenter-restart" title="Restart elapsed time and all timers (t)">restart (t)</button></span></p>
<nav class="presenter-nav" aria-label="deck navigation">
<button type="button" id="presenter-prev" aria-label="previous screen">&#8249;</button>
<span class="presenter-pos"><span id="presenter-ordinal">1</span> / <span id="presenter-count">1</span></span>
<button type="button" id="presenter-smaller" aria-label="smaller notes text" title="Smaller notes text ([)">A&minus;</button>
<button type="button" id="presenter-bigger" aria-label="bigger notes text" title="Bigger notes text (])">A+</button>
<button type="button" id="presenter-flip" class="presenter-flip" aria-label="put the notes above the slide image" title="Swap notes and slide image, top / bottom (f)">&#8645;</button>
<button type="button" id="presenter-next" aria-label="next screen">&#8250;</button>
</nav>
</header>
<p class="presenter-cue" id="presenter-cue"></p>
<main class="presenter-panes">
<section class="presenter-pane presenter-pane-current">
<h2 class="presenter-label">On screen now</h2>
<p class="presenter-title" id="presenter-title"></p>
<div class="preview" id="presenter-preview"></div>
<div class="presenter-live" id="presenter-live"></div>
<div class="presenter-notes" id="presenter-notes"></div>
</section>
<section class="presenter-pane presenter-pane-next">
<h2 class="presenter-label">Next up</h2>
<p class="presenter-title" id="presenter-next-title"></p>
<div class="preview" id="presenter-next-preview"></div>
<div class="presenter-notes" id="presenter-next-notes"></div>
</section>
</main>
<p class="presenter-status" id="presenter-status" role="status"></p>
<script type="application/json" id="cue-index">{cue_index}</script>
<script>
{PRESENTER_UI_JS}
</script>
</div>
</body>
</html>
"""
    path = out_dir / "presenter.html"
    path.write_text(doc, encoding="utf-8")
    return path


def quote_paras_html(text: str) -> str:
    """A quote's paragraphs (blank `>` lines, kept as "\n\n") as <p>s."""
    return "".join(f"<p>{inline_md(p.strip()).replace(chr(10), '<br>')}</p>"
                   for p in text.split("\n\n") if p.strip())


# Quote length tiers on the slide (visible characters). A short quote gets a
# column wide enough to stay on one line; a long one a wide column at reading
# size. The pager's fitQuotes() still shrinks any quote that overflows.
QUOTE_SHORT_MAX = 60
QUOTE_LONG_MIN = 320


# A quote that is only one `code span` is text to type in, not words someone said
# (`> `Hi.``): the views give its blockquote the type-in class.
TYPE_IN_RE = re.compile(r"^`[^`\n]+`$")


def quote_kind_attr(text: str) -> str:
    return ' class="type-in"' if TYPE_IN_RE.match(text.strip()) else ""


def quote_size_class(text: str) -> str:
    n = len(re.sub(r"[*`]", "", text).replace("\n\n", " "))
    if n <= QUOTE_SHORT_MAX:
        return " quote-short"
    if n >= QUOTE_LONG_MIN or text.count("\n\n") >= 2:
        return " quote-long"
    return ""


def timer_clock(seconds: int) -> str:
    """`m:ss`, or `h:mm:ss` from an hour up (the same rule the pager script uses)."""
    h, rem = divmod(int(seconds), 3600)
    m, sec = divmod(rem, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


def timer_digits_html(text: str) -> str:
    """The digits as fixed-width cells, so the figures never jiggle whatever
    the display face's numerals are (the pager script builds the same markup)."""
    cls = {":": "c", "+": "sg"}
    return "".join(f'<span class="{cls.get(ch, "d")}">{ch}</span>' for ch in text)


def timer_plate_html(timer: tuple, shape: str) -> str:
    """The present view's countdown for a screen's timer (seconds, phrase,
    corner).  `shape`: `inline` (in a line of text), `block` (a token alone on
    its line) or `corner` (a plate in the lower-right of the frame).  The pager's
    timer module (TIMER_JS) animates it; built as it is on arrival, it reads the
    full duration."""
    seconds, phrase, _corner = timer
    tag = "span" if shape == "inline" else "div"
    return (
        f'<{tag} class="timer-plate timer-{shape}" role="timer" data-timer="{seconds}" '
        f'aria-label="{html.escape(phrase)} timer">'
        f'<span class="timer-digits" aria-hidden="true">{timer_digits_html(timer_clock(seconds))}</span>'
        f'<span class="timer-state"></span></{tag}>'
    )


def timer_reveal_wanted(screen: Screen) -> bool:
    """True when any shot of the screen says `reveal=timer`."""
    return any("timer" in reveal_modes(sh.flags) for sh in screen.shots)


def timer_armed(screen: Screen) -> bool:
    """A screen whose countdown stays hidden and stopped until a next-press
    shows it and starts it: `reveal=timer` on a screen that has a valid timer.
    Without a timer the flag is ignored (check 44)."""
    return screen.timer is not None and timer_reveal_wanted(screen)


def timer_first(screen: Screen) -> bool:
    """Document order for the revealables: a revealed timer comes BEFORE the
    revealed list's items when its `[Timer: ...]` is written above the list (a
    corner timer has no visual position, so where the line is written decides).
    Written below the list, or inside the list's own items, or with no revealed
    list on the screen, the timer is the last step, as it always was."""
    if not timer_armed(screen) or not any("list" in reveal_modes(sh.flags) for sh in screen.shots):
        return False
    lst = next((b for b in screen.blocks if b.kind == "list" and len(b.items) >= 2), None)
    tb = screen.timer_block
    return lst is not None and tb is not None and tb is not lst and tb.line < lst.line


def timer_sub(text_html: str, b, mode: str = "present") -> str:
    """Replace the block's live `[Timer: ...]` token (the first valid one, which
    the parser accepted) inside already-rendered HTML.  Present view: the
    countdown in place, or nothing for `corner` (the plate goes to the corner).
    Document view: the quiet words `8 minute timer`, or nothing for `corner`.
    Any other token (invalid, a second one) stays literal text."""
    if b.timer is None:
        return text_html
    for m in TIMER_TOKEN_RE.finditer(text_html):
        got = parse_timer_token(m.group(1))
        if got is None:
            continue
        if got[2]:
            rep_ = ""
        elif mode == "present":
            rep_ = timer_plate_html(b.timer, "inline")
        else:
            rep_ = ""       # the reading copy never prints a timer
        return text_html[:m.start()] + rep_ + text_html[m.end():]
    return text_html


def list_html(b, reveal: bool = False, start: int = 0, cols: bool = False) -> str:
    """A list block: `<ol>` for numbered items, `<ul>` otherwise.  Sub-points
    (`b.depths`) nest as `<ul>` inside the item above.

    `reveal` (shot flag `reveal=list`) marks each item, sub-points included,
    with its step number in document order and the list with `data-reveal`;
    `start` items are showing when the slide opens.  The pager hides the rest
    and shows one more per next-press.

    `cols` (shot flag `layout=cols`) sets the list as a two-column grid: the
    top-level items fill the left column first, so `--cols-rows` is half of
    them, rounded up (the stylesheet does the rest).
    """
    tag = "ol" if b.ordered else "ul"
    depths = list(b.depths) or [0] * len(b.items)
    top = sum(1 for dp in depths if dp == 0) or 1
    out = [f"<{tag}" + (f' data-reveal="{start}"' if reveal else "")
           + (f' data-cols style="--cols-rows:{-(-top // 2)}"' if cols else "") + ">"]
    d = 0
    for n, (text, depth) in enumerate(zip(b.items, depths), 1):
        depth = min(depth, d + 1) if n > 1 else 0
        if n == 1:
            pass
        elif depth > d:
            out.append("<ul>")
        else:
            out.append("</li>" + "</ul></li>" * (d - depth))
        d = depth
        out.append(f'<li data-step="{n}">' if reveal else "<li>")
        out.append(inline_md(text))
    out.append("</li>" + "</ul></li>" * d + f"</{tag}>")
    return "".join(out)


def table_html(b) -> str:
    """A table block; rows[0] is a header row when the source marked one."""
    rows = list(b.rows)
    head = ""
    if b.header and rows:
        cells = "".join(f"<th>{inline_md(c)}</th>" for c in rows.pop(0))
        head = f"<thead><tr>{cells}</tr></thead>"
    body = "".join(
        "<tr>" + "".join(f"<td>{inline_md(c)}</td>" for c in row) + "</tr>"
        for row in rows)
    return f'<table class="md-table">{head}<tbody>{body}</tbody></table>'


# a source line that starts with a list marker or indentation hangs its wrapped
# rows under the text after it (layout only; the characters never change)
_HANG_RE = re.compile(r"^([ \t]*(?:[-*+]|\d+[.)])[ \t]+|[ \t]+)")


def code_html(b) -> str:
    """A fenced block (spec: Text, fenced code): the lines exactly as written,
    HTML-escaped, in a <pre>.  No markdown, no inline code, no cites.  Each
    source line is its own block <span> that ends in its own newline, so the
    text (and copy/paste) is the source's lines exactly, while a long line can
    wrap under a hanging indent: padding-left and a negative text-indent of
    the marker width, in ch."""
    out = []
    for line in b.text.split("\n"):
        m = _HANG_RE.match(line)
        hang = len(m.group(1).expandtabs(4)) if m else 0
        style = f' style="padding-left:{hang}ch;text-indent:-{hang}ch"' if hang else ""
        out.append(f'<span class="cl"{style}>{html.escape(line, quote=False)}\n</span>')
    return f'<pre class="code-block">{"".join(out)}</pre>'


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
    has_body = any(b.kind in ("heading", "stat", "quote", "list", "table")
                   or (b.kind == "code" and b.text.strip())
                   or (b.kind == "timer" and not (b.timer and (b.timer[2] or b.timer_quiet)))
                   for b in screen.blocks)
    tm = screen.timer

    inner = []
    if ref is not None:
        # fit=contain / fit=cover always reach the media; fit=hero is read
        # at slide level (text-fit below) and leaves the media at its default
        under_ref = resolver.resolve(flags["under"]) if flags.get("under") else None
        frames = None
        if ref.steps and not ref.live:
            if mshot.cont:
                # a `continue` screen is the same picture carrying on, so it
                # opens on the frame the last screen ended on and does not step
                ref = dataclasses.replace(resolver.resolve(ref.steps[-1]), slug=ref.slug,
                                          alt=ref.alt)
            elif "off" not in reveal_modes(flags) and under_ref is None:
                frames = [resolver.resolve(n) for n in ref.steps]
        inner.append(media_zone_html(ref, dict(flags), chain=mshot.chain, under=under_ref,
                                     frames=frames))

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
        # `reveal=list` (any shot of the screen): the first list's items appear
        # one per next-press.  With nothing on screen before the list, item 1
        # is showing on arrival; with a title first, none are.
        cols_done = False
        reveal_list = any("list" in reveal_modes(sh.flags) for sh in screen.shots)
        if reveal_list and not any(b.kind == "list" and len(b.items) >= 2 for b in blocks):
            if any("list" in reveal_named(sh.flags) for sh in screen.shots):
                print(f"warn      : {cue_id}: reveal=list needs a list of 2 or more items on the screen; ignored")
            reveal_list = False
        while i < len(blocks):
            b = blocks[i]
            # VO never renders on the slide body (cinematic slides; VO is
            # spoken, shown in speaker notes only).
            if b.kind == "vo":
                i += 1
                continue
            if b.kind == "heading":
                lvl = min(b.level or 2, 3)
                # a heading right after a shallower one is its subtitle
                prev = blocks[i - 1] if i > 0 else None
                sub = (prev is not None and prev.kind == "heading"
                       and (b.level or 2) > (prev.level or 2))
                cls = "slide-title subtitle" if sub else "slide-title"
                body.append(f"<h{lvl} class='{cls}'>{timer_sub(inline_md(b.text), b)}</h{lvl}>")
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
                    f'<div class="quote-block{quote_size_class(b.text)}">'
                    f'<div class="quote-plate" aria-hidden="true"></div>'
                    f"<blockquote{quote_kind_attr(b.text)}>{timer_sub(quote_paras_html(b.text), b)}</blockquote>"
                    f"{src}</div>"
                )
            elif b.kind == "list":
                as_cols = sflags.get("layout") == "cols" and not cols_done
                cols_done = cols_done or as_cols   # only the first list takes the columns
                if reveal_list:
                    body.append(timer_sub(list_html(b, True, 0 if (body or timer_first(screen)) else 1, as_cols), b))
                    reveal_list = False   # only the first list reveals
                else:
                    body.append(timer_sub(list_html(b, cols=as_cols), b))
            elif b.kind == "table":
                body.append(table_html(b))
            elif b.kind == "code":
                if b.text.strip():
                    body.append(code_html(b))
            elif b.kind == "stat":
                body.append(f'<div class="stat">{timer_sub(inline_md(b.text), b)}</div>')
            elif b.kind == "paraphrase":
                # Our words, not the source's: no quotation styling. The block
                # rides alongside the quote above it on the same screen (the
                # both-up screen, spec: Roles).
                if b.text.strip():
                    body.append(
                        f'<div class="paraphrase-block">'
                        f'<p class="paraphrase-text">{timer_sub(inline_md(b.text), b)}</p></div>'
                    )
            elif b.kind == "timer":
                # a token alone on its line: the countdown as a block of large
                # digits in the flow (a `corner` token draws nothing here); an
                # invalid or second token is left as literal text
                if b.timer is None:
                    body.append(f'<p class="timer-literal">{html.escape(b.text)}</p>')
                elif b.timer_quiet:
                    # `([Timer: 5m])`: runs for the presenter window only; the
                    # audience's slide draws nothing
                    body.append(timer_plate_html(b.timer, "block").replace(
                        'class="timer-plate ', 'class="timer-plate timer-private ', 1))
                elif not b.timer[2]:
                    body.append(timer_plate_html(b.timer, "block"))
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

    if tm is not None and tm[2]:
        inner.append(timer_plate_html(tm, "corner"))

    # speaker notes: VO + stage directions (never on the slide body). The
    # stage-note class is deliberately NOT "stage": `.stage` is the present
    # view's fixed, full-viewport slide container, so a paragraph carrying
    # `class="stage"` inside the notes panel resolved to `position: fixed;
    # inset: 0` and covered the whole screen instead of sitting in the panel.
    notes = []
    # speaker notes: VO + stage directions (never on the slide body). The
    # stage-note class is deliberately NOT "stage": `.stage` is the present
    # view's fixed, full-viewport slide container, so a paragraph carrying
    # `class="stage"` inside the notes panel resolved to `position: fixed;
    # inset: 0` and covered the whole screen instead of sitting in the panel.
    #
    # The notes are a reading copy of the slide: his words, the payloads he
    # reads off, and the screen's text that follows his words — or all of the
    # slide's text, on a screen with no words of its own (spec: Text — The
    # reading copy).
    notes_html = "".join(html for _b, html in speaker_notes(screen))

    cls = "animatic-slide" + first
    if sflags.get("fit") == "hero" and not credits_screen and (
            screen.media_shot is None or has_body):
        # fit=hero = hero text as big as the slide allows, including over
        # full-bleed media. fit=contain / fit=cover only say how media fits:
        # before 2026-09-28 any fit on a screen with a heading also turned on
        # hero text and dropped the contain (bots-traffic, mania-vs-ai)
        cls += " text-fit"
    if any(b.kind == "code" and b.text.strip() for b in screen.blocks):
        cls += " has-code"
    if tm is not None:
        cls += " has-timer" + (" timer-has-corner" if tm[2] else "")
    layout_name = sflags.get("layout")
    if layout_name == "duo" and screen.media_shot is not None:
        cls += " duo"
        # A duo screen whose object is a LIVE capture is a demo slide, and it
        # takes demo proportions (themes/components.css): the capture leads and
        # the text is the margin note. The plain duo split gives the capture
        # 32vw, which is a framed object's size and reads as a small window in
        # the room (Ryan, 2026-10-18: "it works but the window is very small").
        if ref is not None and ref.live:
            cls += " duo-live"
    if layout_name == "titled" and screen.media_shot is not None:
        cls += " titled"
    if layout_name == "cols":
        cls += " cols"
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
    slide_inner = "".join(inner)
    if bare_reveal_empty(screen):
        print(f"warn      : {cue_id}: reveal has nothing to reveal on this screen "
              f"(no list of 2 or more items, no timer); ignored")
    if timer_reveal_wanted(screen):
        if screen.timer is None:
            if any("timer" in reveal_named(sh.flags) for sh in screen.shots):
                print(f"warn      : {cue_id}: reveal=timer needs a [Timer: ...] on the screen; ignored")
        else:
            # hidden from the start (the pager's step shows it); the timer
            # module starts it on that step, never on arrival
            slide_inner = slide_inner.replace(
                'class="timer-plate ',
                f'data-timer-reveal="{"first" if timer_first(screen) else "last"}" class="timer-plate pending ', 1)
    return (
        f'<section id="{cue_id}" class="{cls}" data-movement="{mv}"'
        f' data-kind="{screen_kind(screen)}">'
        f'{slide_inner}'
        f'<aside class="notes">{notes_html}</aside>'
        f"</section>"
    )


# ---------------------------------------------------------------------------
# DOCUMENT view (static HTML handout; print-to-PDF via @media print)
# ---------------------------------------------------------------------------


def _figure_css(talk: Talk, override=None) -> str:
    """The handout's figure width (frontmatter `handout-figures:`, or the
    `override` from the command line): `capped` (the default: natural width,
    at most 68 mm tall), `full` (the text column's width), or a share of it
    (`80%`).  Print only; the web page already fits its column."""
    value = str(override or talk.meta.get("handout-figures") or "capped").strip().lower()
    m = re.fullmatch(r"(\d{1,3})%", value)
    if value == "full":
        w, h = "100%", "none"
    elif m and 10 <= int(m.group(1)) <= 100:
        w, h = f"{int(m.group(1))}%", "none"
    else:
        if value != "capped":
            print(f"warn      : handout-figures {value!r} is not capped, full or n%; using capped")
        return ""
    return (f"<style>@media print {{ figure.shot img {{ width: {w}; "
            f"max-height: {h}; object-fit: contain; }} }}</style>")


def _footer_css(talk: Talk, deck_title: str) -> str:
    """Print footer: the deck title (or frontmatter `handout-footer:`) on the
    left, "Page n of N" on the right.  `handout-footer: off` leaves it out.
    Page margin boxes, so it needs a browser that prints them (Chromium 131+)."""
    raw = talk.meta.get("handout-footer")
    text = deck_title if raw is None else str(raw).strip()
    if text.lower() in ("off", "no", "false", "0"):
        return ""
    esc = text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")
    box = "font: 8.5pt sans-serif; color: #777;"
    return (f'<style>@page {{ @bottom-left {{ content: "{esc}"; {box} }} '
            f'@bottom-right {{ content: "Page " counter(page) " of " counter(pages); {box} }} }}</style>\n')


def _screen_cite_numbers(screen: Screen, cite_no: dict) -> list[int]:
    """The handout's source numbers this screen cites, ascending.

    The prose already carries a numbered marker at each claim; this is the
    same set, collected, so a reader at the bottom of a screen can see what it
    rested on without scrolling to the list.  `print` blocks hold nested
    blocks (a `[notes]` run), so the walk is recursive.
    """
    seen: set[int] = set()

    def walk(blocks) -> None:
        for b in blocks:
            for rid, _tail in b.refs or ():
                n = cite_no.get(rid)
                if n:
                    seen.add(n)
            if b.kind == "print":
                walk(b.inner)

    walk(screen.blocks)
    return sorted(seen)


def _screen_sources_html(screen: Screen, cite_no: dict) -> str:
    nums = _screen_cite_numbers(screen, cite_no)
    if not nums:
        return ""
    links = ", ".join(f'<a href="#src-{n}">{n}</a>' for n in nums)
    return f'<p class="screen-sources">Sources: {links}</p>'


def _toc_html(entries: list) -> str:
    """The contents list: the talk's own headings, in screen order.

    Grouped by part, so a two-column index can break between parts and never
    mid-part (a column that starts at "The bill" with no part title above it
    reads as a lost item).  A second heading on the same screen points at the
    same anchor and is left out only when it is the same label too.  Below two
    entries a list is noise, so nothing is emitted.
    """
    groups: list = []          # [(part label, part anchor, [rows])]
    for lvl, label, anchor in entries:
        label = label.strip()
        if not label or not anchor:
            continue
        row = (lvl, label, anchor)
        if lvl == 2:
            groups.append((label, anchor, []))
            continue
        if not groups:
            groups.append(("", "", []))
        rows = groups[-1][2]
        if rows and rows[-1] == row:
            continue
        rows.append(row)
    total = sum(len(rows) + (1 if part else 0) for part, _a, rows in groups)
    if total < 2:
        return ""
    blocks = []
    for part, part_anchor, rows in groups:
        items = "".join(
            f'<li class="toc-h{lvl}"><a href="#{html.escape(a)}">'
            f"{html.escape(lab)}</a></li>"
            for lvl, lab, a in rows
        )
        head = (f'<a class="toc-part" href="#{html.escape(part_anchor)}">'
                f"{html.escape(part)}</a>") if part else ""
        blocks.append(f'<section class="toc-group">{head}'
                      f'<ol class="toc-list">{items}</ol></section>')
    return (
        '<nav class="doc-toc" aria-label="Contents">'
        '<h2 class="toc-title">Contents</h2>'
        f'<div class="toc-cols">{"".join(blocks)}</div></nav>'
    )


def _is_pool_slug(resolver: MediaResolver, slug: str | None) -> bool:
    """True for a pool pick: a card with `pool:`, or the `<card>--NN` name a
    pick is given once the draws are made."""
    if not slug:
        return False
    m = re.fullmatch(r"(.+)--\d{2,}", slug)
    card = resolver.card_for(m.group(1) if m else slug)
    return bool(card and card.get("pool"))


def render_document(talk: Talk, resolver: MediaResolver, out_dir: Path,
                    figures: str | None = None,
                    pools: bool | None = None,
                    placeholders: bool | None = None) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    theme = resolve_theme(talk)
    meta = talk.meta
    deck_title = str(meta.get("title", deck_slug(talk)))
    meta_bits = [str(v) for v in
                 (meta.get("venue"), meta.get("date"), meta.get("format"), meta.get("dur"))
                 if v]

    # The handout's citation list, numbered in first-appearance order.  The
    # `[^id]` refs in the prose become links to these numbers.
    #
    # `cites:` (optional frontmatter map, id -> public citation): the
    # registry entries are working receipts (repo paths, "verify this"), so
    # a deck that declares `cites:` prints those in the handout instead.  An
    # id with no public form is left out, never printed raw; build.py warns.
    cited = cited_sources(talk)
    cites = talk.meta.get("cites")
    if isinstance(cites, dict):
        cited = [{"id": c["id"], "source": str(cites[c["id"]])}
                 for c in cited if str(cites.get(c["id"], "")).strip()]
    elif str(talk.meta.get("handout-sources", "")).strip().lower() != "working":
        # No public citations declared: the working receipts never print.
        # `handout-sources: working` opts a draft copy back in.
        cited = []
    cite_no = {c["id"]: n for n, c in enumerate(cited, start=1)}

    fig_css = _figure_css(talk, figures)
    fig_css = fig_css + "\n" if fig_css else ""
    fig_css += _footer_css(talk, deck_title)
    # Pool art is decoration (a random pick from a folder), so a handout can
    # leave it out: frontmatter `handout-pools: off`, or `--no-handout-pools`.
    if pools is None:
        pools = str(talk.meta.get("handout-pools", "on")).strip().lower() not in ("off", "no", "false", "0")
    # A card with no picture yet prints a grey box naming the slug and why.
    # For a copy that goes out for review: `handout-placeholders: off`, or
    # `--no-handout-placeholders`.  The screen's text still prints.
    if placeholders is None:
        placeholders = str(talk.meta.get("handout-placeholders", "on")).strip().lower() not in ("off", "no", "false", "0")

    opening = []
    movement_sections = []
    current = {"idx": 0, "items": opening}
    last_fig = None   # slug of the figure just before: a repeat is left out
    toc: list = []    # (level, label, anchor) for the contents list
    for screen in talk.screens:
        if is_black_screen(screen) or screen.live_only:
            continue  # black beats have no prose; live-only screens stay off paper
        cue_id = f"{deck_slug(talk)}-{screen.idx:03d}"   # same key nav.json uses
        if screen.movement != current["idx"]:
            m = next((m for m in talk.movements if m.index == screen.movement), None)
            current = {"idx": screen.movement, "items": []}
            if m is not None:
                movement_sections.append(
                    (m.label, current["items"])
                )
                # the part title is a chapter in the contents, anchored at the
                # first screen under it (the movement heading has no id of its
                # own, so this is where a jump should land)
                toc.append((2, m.label, f"cue-{cue_id}"))
        slug = screen.media_shot.slug if screen.media_shot else None
        # A `continue` shot, or any shot naming the slug of the figure just
        # before it, is the same picture again: the handout shows it once,
        # at its first appearance.  The screen's text still prints.
        repeat = bool(slug) and slug == last_fig
        if slug:
            last_fig = slug
        current["items"].append(
            f'<div class="screen" id="cue-{cue_id}">'
            + _doc_screen_blocks(
                talk, screen, resolver, skip_deck_h1=deck_title,
                cite_no=cite_no,
                skip_figure=(repeat
                             or (not pools and _is_pool_slug(resolver, slug))
                             or (not placeholders and bool(slug)
                                 and not resolver.resolve(slug).found)),
                toc=toc, anchor=f"cue-{cue_id}")
            + _screen_sources_html(screen, cite_no)
            + "</div>")

    def render_flow(blocks) -> str:
        return "".join(blocks)

    open_html = f'<section class="opening">{render_flow(opening)}</section>' if opening else ""
    mov_html = "".join(
        f'<section class="movement" data-movement="{i}"><h2 class="movement">{html.escape(label)}</h2>{render_flow(items)}</section>'
        for i, (label, items) in enumerate(movement_sections, start=1)
    )

    # Receipts surface once, as the handout citation list (spec: Text): every
    # referenced `sources:` registry entry, first-appearance order.  The
    # registry value is the citation — ids are authoring keys and stay in
    # cues.json, never on the page.  No receipts, no section.
    sources_html = ""
    if cited:
        items = "".join(
            f'<li id="src-{n}">{html.escape(src["source"])}</li>'
            for n, src in enumerate(cited, start=1)
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
    # The contents list has three lives, all from one function: a rail on a wide
    # screen (a 151-screen page needs an outline that stays on screen), a folded
    # "Contents" line on a phone (an inline 38-item index owns the first screen),
    # and the plain list on paper, where there is nothing to fold.
    toc_html = _toc_html(toc)
    toc_rail = toc_html.replace('class="doc-toc"', 'class="doc-toc doc-toc-rail"')
    toc_inline = toc_html.replace('class="doc-toc"', 'class="doc-toc doc-toc-inline"')
    toc_mobile = ('<details class="doc-toc-mobile"><summary>Contents</summary>'
                  + toc_html.replace('class="doc-toc"', 'class="doc-toc doc-toc-mobile-body"')
                  + "</details>") if toc_html else ""

    doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(deck_title)}</title>
{theme_style_blocks(theme)}
{fig_css}</head>
<body class="view-document">
{toc_rail}
<article>
<header class="doc-head">
<h1>{html.escape(deck_title)}</h1>
<p class="meta">{html.escape(" · ".join(b for b in meta_bits if b))}</p>
</header>{toc_mobile}{toc_inline}
{body_sections}
</article>
</body>
</html>
"""
    path = out_dir / "index.html"
    path.write_text(doc, encoding="utf-8")
    return path


CITE_OPEN, CITE_CLOSE = "\ue000", "\ue001"   # private-use fences round a citation number through inline_md


def _with_cites(b: Block, cite_no: dict) -> str:
    """The block's text with a citation marker where each `[^id]` sat.  The
    parser kept only the text just before each ref; find that text (a shorter
    tail if parentheticals were stripped since) and mark the spot, else the
    end of the block.  Run the result through `_cite_links` after
    inline_md."""
    text = b.text
    if not b.refs or not cite_no:
        return text
    points = []   # (offset, number)
    pos = 0
    for rid, tail in b.refs:
        n = cite_no.get(rid)
        if n is None:
            continue
        at = -1
        for cut in (len(tail), 24, 12):
            t = tail[-cut:] if cut < len(tail) else tail
            if t:
                at = text.find(t, pos)
                if at >= 0:
                    at += len(t)
                    break
        if at < 0:
            at = len(text)
        pos = at
        points.append((at, n))
    for at, n in sorted(points, reverse=True):
        text = f"{text[:at]}{CITE_OPEN}{n}{CITE_CLOSE}{text[at:]}"
    return text


def _cite_links(rendered: str) -> str:
    return re.sub(
        CITE_OPEN + r"(\d+)" + CITE_CLOSE,
        lambda m: f'<sup class="cite"><a href="#src-{m.group(1)}">{m.group(1)}</a></sup>',
        rendered)


def _doc_screen_blocks(talk: Talk, screen: Screen, resolver: MediaResolver,
                       skip_deck_h1: str, cite_no: dict | None = None,
                       skip_figure: bool = False,
                       toc: list | None = None, anchor: str = "") -> str:
    out = []
    cite_no = cite_no or {}
    headings = toc if toc is not None else []
    media_shot = screen.media_shot
    ref = resolver.resolve(media_shot.slug) if (media_shot and media_shot.slug) else None
    if ref is not None and media_shot.flags.get("still") and ref.doc_file and not ref.live:
        # this shot's own `still=` frame beats the card's
        own = resolver.doc_still(ref, media_shot.flags["still"])
        if own:
            ref = dataclasses.replace(ref, doc_file=own)
    credits_entries_ = credits_entries(screen)
    is_credits = is_credits_screen(screen)
    # a handout heading (written just before the screen's shot) leads the
    # screen in the handout, ahead of its figure; it never reaches a slide
    for b in screen.blocks:
        if b.kind != "handout-heading":
            continue
        if b.text.strip() == skip_deck_h1 and screen.movement == 0:
            continue  # deck title already in the header
        lvl = 2 if (b.level or 2) <= 1 else min(b.level or 3, 4)
        headings.append((lvl, plain_md(strip_timer_tokens(b.text)), anchor))
        out.append(f"<h{lvl} class='screen-heading'>{_cite_links(inline_md(_with_cites(b, cite_no)))}</h{lvl}>")
    # figure first (media shot leads the screen), then flow blocks
    consumed = set()
    if ref is not None and not skip_figure:
        # the shot's playback / sound overrides hold in the handout as the
        # card's do; slide-only flags (advance, kb, fit) stay out
        doc_flags = {k: v for k, v in media_shot.flags.items()
                     if k in ("playback", "sound")}
        inner = media_html(ref, doc_flags, css_class="figure-media")
        cap = "".join(
            f'<figcaption>{html.escape(b.text)}</figcaption>'
            for b in screen.blocks if b.kind in ("lower", "credits") and b.text.strip()
        )
        out.append(f'<figure class="shot" data-slug="{html.escape(ref.slug)}">{inner}{cap}</figure>')
        # lower/credits already rendered as the figure caption: don't repeat them
        consumed = {id(b) for b in screen.blocks if b.kind in ("lower", "credits")}
    flow = []
    for b in screen.blocks:      # a `[handout]` run prints in place, in the flow
        flow.extend(b.inner if b.kind == "print" else [b])
    for b in flow:
        if id(b) in consumed:
            continue
        if b.kind == "vo":
            if b.text.strip():
                out.append(f'<p class="vo">{_cite_links(inline_md(_with_cites(b, cite_no)))}</p>')
        elif b.kind == "heading":
            if b.text.strip() == skip_deck_h1 and screen.movement == 0:
                continue  # deck title already in the header
            lvl = 2 if (b.level or 2) <= 1 else min(b.level or 3, 4)
            headings.append((lvl, plain_md(strip_timer_tokens(b.text)), anchor))
            out.append(f"<h{lvl} class='screen-heading'>{timer_sub(_cite_links(inline_md(_with_cites(b, cite_no))), b, 'doc')}</h{lvl}>")
        elif b.kind == "quote":
            out.append(f"<blockquote{quote_kind_attr(b.text)}>{timer_sub(_cite_links(quote_paras_html(_with_cites(b, cite_no))), b, 'doc')}</blockquote>")
        elif b.kind == "quote-source":
            out.append(f'<p class="doc-quote-source">{inline_md(b.text)}</p>')
        elif b.kind == "list":
            out.append(timer_sub(list_html(b), b, "doc"))
        elif b.kind == "table":
            out.append(table_html(b))
        elif b.kind == "code":
            if b.text.strip():
                out.append(code_html(b))
        elif b.kind == "timer":
            # the clock never prints: one quiet line (a `corner` timer's line
            # comes last, below the screen's content)
            if b.timer is None:
                out.append(f'<p class="vo">{html.escape(b.text)}</p>')
            # a timer is the room's clock: the reading copy prints nothing
        elif b.kind == "stat":
            if b.text.strip():
                out.append(f'<div class="stat-callout"><p>{timer_sub(_cite_links(inline_md(_with_cites(b, cite_no))), b, "doc")}</p></div>')
        elif b.kind == "paraphrase":
            # Callout-level object in the prose flow (the stat-callout
            # treatment is the model), never a figure: our words beside the
            # source's, in the handout as on the stage (spec: Roles).
            if b.text.strip():
                out.append(
                    f'<div class="paraphrase-block">'
                    f'<p class="paraphrase-text">{timer_sub(_cite_links(inline_md(_with_cites(b, cite_no))), b, "doc")}</p></div>'
                )
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
# CUES (ordered slide id -> script) + nav + media manifest
# ---------------------------------------------------------------------------


def render_cues(talk: Talk, resolver: MediaResolver, out_dir: Path) -> Path:
    """The machine contract: one entry per screen, in presentation order.

    Each cue carries its script, on-screen text, shots, resolved media, and
    `est_seconds` — the estimated timing tier (spec: Timing).  The estimate is
    computed here, on the way into the artifact, because it is a product of
    the parse model (words, screen kind, media file); authored and measured
    overrides live in the deck-local `timing.yaml` (timing.py) and are
    deliberately not echoed into cues.json, which stays a pure builder output.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    tt = timing.load(Path(talk.source).parent if talk.source else Path.cwd())
    cues = []
    by_movement: dict[int, list[str]] = {}

    for screen in talk.screens:
        cue_id = f"{deck_slug(talk)}-{screen.idx:03d}"
        by_movement.setdefault(screen.movement, []).append(cue_id)

        screen_obj = {"kind": "screen"}
        text = []
        timer_at = None
        for b in screen.blocks:
            if b.kind == "heading":
                text.append({"kind": "heading", "level": b.level, "text": b.text})
            elif b.kind == "quote":
                text.append({"kind": "quote", "text": b.text})
            elif b.kind == "quote-source":
                text.append({"kind": "source", "text": b.text})
            elif b.kind == "list":
                entry = {"kind": "list", "items": list(b.items)}
                if b.depths:
                    entry["depths"] = list(b.depths)
                if b.ordered:
                    entry["ordered"] = True
                if b.spoken:
                    entry["spoken"] = True     # read aloud as well as shown
                text.append(entry)
            elif b.kind == "table":
                text.append({"kind": "table", "header": b.header,
                             "rows": [list(r) for r in b.rows]})
            elif b.kind in ("stat", "lower", "credits", "paraphrase", "code", "timer"):
                if b.text.strip():
                    text.append({"kind": b.kind, "text": b.text})
            if b.timer is not None and text and text[-1]["kind"] == b.kind:
                timer_at = len(text) - 1
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
            "est_seconds": cue_estimate(screen, resolver, tt.wpm),
            # live-only: shown in the live deck, never in a recorded video or
            # the handout.  A video renderer must skip cues where this is true.
            **({"live_only": True} if screen.live_only else {}),
            # a countdown (spec: Timer screens): integer seconds, the index of
            # the `screen_text` entry whose text holds the token, and `corner`
            **({"timer": screen.timer[0], "timer_in": timer_at,
                **({"timer_corner": True} if screen.timer[2] else {}),
                **({"timer_reveal": True} if timer_armed(screen) else {}),
                **({"timer_reveal_first": True} if timer_first(screen) else {})}
               if screen.timer is not None else {}),
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
            # `sources:` registry value (spec: Text).  Empty when the deck has
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


def screen_steps(screen: Screen, resolver: MediaResolver) -> MediaRef | None:
    """The media ref of a screen that steps through images in the present view
    (a stepped-image card, not `reveal=off`, not a `continue` screen), else None."""
    shot = screen.media_shot
    if shot is None or not shot.slug or shot.cont:
        return None
    ref = resolver.resolve(shot.slug)
    if not ref.steps or ref.live or "off" in reveal_modes(shot.flags):
        return None
    if shot.flags.get("under"):
        return None
    return ref


def handout_label(ref: MediaRef) -> str:
    """How a stepped card's handout image reads in the build summary."""
    if ref.handout == ref.slug:
        return "own image"
    if ref.handout == ref.steps[-1]:
        return "last"
    if ref.handout == ref.steps[0]:
        return "first"
    return f"step {ref.steps.index(ref.handout) + 1}"


def step_count_notes(talk: Talk, resolver: MediaResolver) -> list:
    """Check 34: a stepped-image card and a `reveal=list` list on one screen
    advance together, so their counts should match; the shorter one holds at
    its last item or frame.  [(screen, line, message)]."""
    notes = []
    for s in talk.screens:
        ref = screen_steps(s, resolver)
        if ref is None or not any("list" in reveal_modes(sh.flags) for sh in s.shots):
            continue
        lst = next((b for b in s.blocks if b.kind == "list" and len(b.items) >= 2), None)
        if lst is not None and len(lst.items) != len(ref.steps):
            notes.append((s, s.media_shot.line,
                f"'{ref.slug}' has {len(ref.steps)} image steps and the reveal=list list "
                f"has {len(lst.items)} items: they advance together, and the shorter one "
                f"holds on its last until the longer finishes"))
    return notes


def next_mark_notes(talk: Talk, resolver: MediaResolver) -> list:
    """Check 40: a screen's `[n]` / `[next]` marks should equal its next-presses
    that stay on the screen (the steps after the one showing on arrival).
    [(screen, line, message)]."""
    notes = []
    for s in talk.screens:
        marks = sum(len(b.nexts) for b in s.blocks if b.kind == "vo")
        if not marks:
            continue
        ref = screen_steps(s, resolver)
        imgs = len(ref.steps) if ref is not None else 0
        lst = next((b for b in s.blocks if b.kind == "list" and len(b.items) >= 2), None)
        if lst is not None and not any("list" in reveal_modes(sh.flags) for sh in s.shots):
            lst = None
        items = len(lst.items) if lst is not None else 0
        tarm = timer_armed(s)
        if lst is None and not imgs and not tarm:
            presses, how = 0, "nothing on it steps"
        else:
            # the list's own arrival: item 1 showing when nothing precedes it,
            # none when a title comes first; images alone open on frame 1
            # (a handout-only heading, written before the shot comment, is not on the slide)
            first = next((b for b in s.blocks if b.kind not in ("vo", "handout-heading")), None)
            start = (1 if first is lst else 0) if lst is not None else (1 if imgs else 0)
            if timer_first(s):
                start = 0
            steps_n = max(imgs, items) + (1 if tarm else 0)
            presses = steps_n - start
            how = f"{steps_n} steps"
        if marks != presses:
            line = next((b.line for b in s.blocks if b.kind == "vo" and b.nexts), s.line_range[0])
            notes.append((s, line,
                f"{marks} [next] mark(s) in the script but {presses} next-press(es) "
                f"stay on this screen ({how}): the marks and the presses drift apart"))
    return notes


def media_ref_dict(ref: MediaRef) -> dict:
    d = {
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
    # live refs are the one shape with no file, so they carry their own two
    # fields and nothing else in the manifest changes shape (goldens stay put)
    if ref.live:
        d["live"] = True
        d["poster"] = ref.poster
    # likewise playback appears only when it is not the default loop
    if ref.playback != "loop":
        d["playback"] = ref.playback
    if ref.sound:
        d["sound"] = True
    # a stepped-image card names its frames and the image the handout prints
    if ref.steps:
        d["steps"] = list(ref.steps)
        d["handout"] = ref.handout
    return d


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


def render_nav(talk: Talk, out_dir: Path) -> Path:
    """The addressability sidecar (spec: Outputs — cue id -> line range,
    movement, kind).

    One entry per screen, keyed by cue id, in presentation order: the source
    line range the screen owns, its movement, its kind (the same `kind` cues
    carries, so the two sidecars never disagree about a screen), and whether
    the document view contains it.  A screen the document view skips — a
    black beat, which carries no prose to print — is marked here with its
    reason, so the sidecar is the honest map of what each view contains:
    `present/` holds every screen 1:1 with cues, `document/` holds every
    screen whose entry is not marked absent.

    Generated, never authored: the ranges come from the line spans the parser
    attaches to each screen's shots and blocks, so there is zero author
    maintenance and the map cannot drift from the talkfile.  Keys are cue ids
    and nothing else — no unit ids, no `id` field, no grouping spans (spec:
    Screens — the screen is the smallest addressable unit).
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    screens = {}
    for screen in talk.screens:
        cue_id = f"{deck_slug(talk)}-{screen.idx:03d}"
        start, end = screen.line_range
        omitted = is_black_screen(screen) or screen.live_only
        document: dict = {"present": not omitted}
        if omitted:
            document["reason"] = "black-beat" if is_black_screen(screen) else "live-only"
        screens[cue_id] = {
            "ordinal": screen.idx,
            "movement": screen.movement,
            "kind": screen_kind(screen),
            "lines": {"start": start, "end": end},
            "document": document,
            **({"include": screen.include} if screen.include else {}),
        }
    payload = {
        "schema": "animatic.nav.v1",
        "deck": {"slug": str(meta_get(talk, "slug", deck_slug(talk)))},
        "screens": screens,
    }
    path = out_dir / "nav.json"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path
