"""render.py — one parse model, three outputs.

- PRESENT view : one self-contained HTML file per deck (no external engine;
  the pager is a small inline script).  One <section> per screen on a
  .stage; VO + stage directions go to the speaker-notes asides ('n' shows
  them in this window; 's' opens the second-window presenter view —
  docs/presenter-view.md); on-screen objects (media, title, stat, lower,
  credits, quotes, lists) render as the slide body.  All look lives in themes/
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

import html
import json
import re
from pathlib import Path

import timing

from talkparse import (
    BLACK_ROLE,
    Block,
    Screen,
    Talk,
    inline_md,
    plain_md,
    slugify,
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
        elif b.spoken and b.text.strip():
            parts.append(plain_md(b.text))
    return "\n\n".join(parts)


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
                video_seconds = timing.probe_video_seconds(ref.file)
    return timing.estimate_seconds(
        words, screen_kind(screen),
        video_seconds=video_seconds, wpm=wpm,
        credits_read=is_credits_screen(screen),
        beat=has_beat_note(screen))


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


def media_html(ref: MediaRef, shot_flags: dict | None = None, css_class: str = "figure-media") -> str:
    """One resolved media element (image / video / live capture / placeholder)."""
    flags = shot_flags or {}
    parts = []
    if ref.live:
        if "slide-media" in css_class.split():
            parts.append(live_host_html(ref, css_class=css_class))
        elif ref.poster:
            # document figure: the handout prints the still, never a live stream
            poster_src = ref.poster if Path(ref.poster).is_absolute() else "../" + ref.poster
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
    elif ref.found and ref.file:
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
    if ref.live:
        # a capture is live: Ken Burns drift and a dim scrim both fight it,
        # so a live screen takes neither (fit and layout still apply)
        media_flags = {k: v for k, v in flags.items()
                       if k not in ("dim", "kb", "layout")}
        kbcls = ""
    else:
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
  // Modules that cannot own the single onChange slot register here instead
  // (the presenter window wants every arrival; the live module owns onChange).
  var listeners = [];
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
    if (window.animatic && typeof window.animatic.onChange === "function") {
      try { window.animatic.onChange(cur); } catch (err) { /* never break nav */ }
    }
    for (var li = 0; li < listeners.length; li++) {
      try { listeners[li](cur); } catch (err) { /* never break nav */ }
    }
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

  // Tiny public surface for the modules that live beside the pager (live
  // capture reads the current slide to gate its sinks; the hookup panel jumps
  // between demo slides; the presenter window pushes state on every arrival).
  // Additive: nothing here changes pager behaviour, and a listener throwing
  // cannot break navigation. `onChange` stays single-slot (the live module
  // owns it); `addOnChange` is the fan-out for everyone else.
  window.animatic = {
    go: go, next: next, prev: prev,
    count: function () { return slides.length; },
    current: function () { return cur; },
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
    var p = video.play();
    if (p && p.catch) p.catch(function () {});
    state(host, "live");
  }

  function detach(host) {
    var video = videoOf(host);
    if (!video) return;
    try { video.pause(); video.srcObject = null; } catch (err) {}
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
      sessions[key] = { stream: stream, track: track, label: label };
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
  var startedAt = Date.now();

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
          vo.push(k.innerHTML);
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
    var notes = clone.querySelector(".notes");
    if (notes && notes.parentNode) notes.parentNode.removeChild(notes);
    clone.classList.add("active");
    var vids = clone.querySelectorAll("video");
    for (var j = 0; j < vids.length; j++) {
      // a preview is a look, not a second playback: hold the first frame
      // rather than run a second decoder on the talk machine
      vids[j].removeAttribute("autoplay");
      vids[j].setAttribute("preload", "auto");
      vids[j].setAttribute("data-preview-still", "");
    }
    var focusable = clone.querySelectorAll("button, [tabindex]");
    for (var k = 0; k < focusable.length; k++) {
      focusable[k].setAttribute("tabindex", "-1");
    }
    return clone.outerHTML;
  }

  function payload() {
    var i = window.animatic.current();
    var n = slides.length;
    return {
      type: "animatic-state",
      schema: "animatic.presenter.v1",
      index: i,
      count: n,
      startedAt: startedAt,
      notes: notesOf(slides[i]),
      nextNotes: i + 1 < n ? notesOf(slides[i + 1]) : null,
      preview: previewOf(i),
      nextPreview: previewOf(i + 1)
    };
  }

  function push() {
    if (!win || win.closed) { win = null; return; }
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
    say("");
    push();
  }

  function closePresenter() {
    if (win && !win.closed) { try { win.close(); } catch (err) {} }
    win = null;
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
      if ((!win || win.closed) && e.source && e.source !== window) win = e.source;
      push();
      return;
    }
    if (!win || e.source !== win || !window.animatic) return;
    if (d.type === "animatic-next") window.animatic.next();
    else if (d.type === "animatic-prev") window.animatic.prev();
    else if (d.type === "animatic-go" && typeof d.index === "number") {
      window.animatic.go(d.index);
    }
  });

  document.addEventListener("keydown", function (e) {
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    if (e.key === "s" || e.key === "S") { e.preventDefault(); togglePresenter(); }
  });

  // Every arrival, including the ones the live module drives.
  window.animatic.addOnChange(push);

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
   "preview", "next-preview", "notes", "next-notes", "status"]
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
    var i, p;
    for (i = 0; i < notes.vo.length; i++) {
      p = document.createElement("p");
      // the deck's own notes markup, builder-escaped static output
      p.innerHTML = notes.vo[i];
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

  function fillPreview(node, html, cue) {
    if (!node) return;
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

  function paint() {
    if (!state) return;
    var i = state.index;
    var cur = cues[i] || null, nxt = cues[i + 1] || null;
    if (el.ordinal) el.ordinal.textContent = String(i + 1);
    if (el.count) el.count.textContent = String(cues.length || state.count);
    if (el.cue) {
      el.cue.textContent = cur
        ? cur.id + (cur.movement_label ? " \u00b7 " + cur.movement_label : "")
        : "";
    }
    if (el.title) el.title.textContent = cueTitle(cur);
    if (el["next-title"]) el["next-title"].textContent = cueTitle(nxt);
    fillPreview(el.preview, state.preview, cur);
    fillPreview(el["next-preview"], state.nextPreview, nxt);
    fillNotes(el.notes, state.notes);
    fillNotes(el["next-notes"], state.nextNotes);
    say("");
  }

  function post(msg) {
    if (window.opener) window.opener.postMessage(msg, "*");
  }

  function hello() {
    if (!window.opener) {
      say("Open this window from the deck: press s in the deck window.");
      return;
    }
    post({ type: "animatic-presenter-ready", schema: "animatic.presenter.v1" });
  }

  window.addEventListener("message", function (e) {
    var d = e.data;
    if (!d || typeof d !== "object" || d.type !== "animatic-state") return;
    if (window.opener && e.source !== window.opener) return;
    state = d;
    paint();
    tick();
  });

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
      case "s": case "S": e.preventDefault(); window.close(); break;
    }
  });

  window.setInterval(tick, 1000);
  hello();
  tick();
  if (window.opener && !state) say("Waiting for the deck to send its state.");
  window.setTimeout(hello, 1500);   // a slow deck still gets its handshake
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
<p class="deck-status" id="deck-status" role="status" aria-live="polite"></p>
{hookup}<script>
{PAGER_JS}
</script>
<script>
{PRESENTER_JS}
</script>
<script>
{DEBUG_JS}
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
<p class="presenter-clock"><span id="presenter-wall">--:--:--</span>
<span class="presenter-elapsed">elapsed <span id="presenter-elapsed">0:00</span></span></p>
<nav class="presenter-nav" aria-label="deck navigation">
<button type="button" id="presenter-prev" aria-label="previous screen">&#8249;</button>
<span class="presenter-pos"><span id="presenter-ordinal">1</span> / <span id="presenter-count">1</span></span>
<button type="button" id="presenter-next" aria-label="next screen">&#8250;</button>
</nav>
</header>
<p class="presenter-cue" id="presenter-cue"></p>
<main class="presenter-panes">
<section class="presenter-pane">
<h2 class="presenter-label">On screen now</h2>
<p class="presenter-title" id="presenter-title"></p>
<div class="preview" id="presenter-preview"></div>
<div class="presenter-notes" id="presenter-notes"></div>
</section>
<section class="presenter-pane">
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

    # speaker notes: VO + stage directions (never on the slide body). The
    # stage-note class is deliberately NOT "stage": `.stage` is the present
    # view's fixed, full-viewport slide container, so a paragraph carrying
    # `class="stage"` inside the notes panel resolved to `position: fixed;
    # inset: 0` and covered the whole screen instead of sitting in the panel.
    notes = []
    for b in vo_paragraphs(screen):
        notes.append(f"<p>{inline_md(b.text)}</p>")
    for b in screen.blocks:
        for st in b.stage:
            notes.append(f'<p class="stage-note">({html.escape(st)})</p>')
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
        f'<section id="{cue_id}" class="{cls}" data-movement="{mv}"'
        f' data-kind="{screen_kind(screen)}">'
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

    # Receipts surface once, as the handout citation list (spec: Text): every
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
            "est_seconds": cue_estimate(screen, resolver, tt.wpm),
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
        omitted = is_black_screen(screen)
        document: dict = {"present": not omitted}
        if omitted:
            document["reason"] = "black-beat"
        screens[cue_id] = {
            "ordinal": screen.idx,
            "movement": screen.movement,
            "kind": screen_kind(screen),
            "lines": {"start": start, "end": end},
            "document": document,
        }
    payload = {
        "schema": "animatic.nav.v1",
        "deck": {"slug": str(meta_get(talk, "slug", deck_slug(talk)))},
        "screens": screens,
    }
    path = out_dir / "nav.json"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path
