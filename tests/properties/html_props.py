"""Property checks over the two HTML views (spec: Verification property assertions).

HTML is never byte-diffed (highest churn layer), so these properties are the
only thing keeping the views honest: present sections must mirror cues
1:1 with ids and movement attributes, the first slide is active server-side,
media renders found-or-placeholder exactly as the manifest says, no remote
assets and no machine-local paths ever appear, and the document view's
movement and Sources structure must match cues.json.

The presenter page (the second window 's' opens) is checked the same way: it
must exist for every deck, carry no remote asset or machine path, and its
build-time cue index must mirror cues.json cue for cue — including the live
flag, which is the rule that a live screen is never previewed.
"""

from __future__ import annotations

import html as html_mod
import json
import re
from html.parser import HTMLParser

from talkparse import plain_md

from .common import ABS_PATH_RE, err


SECTION_RE = re.compile(
    r'<section id="([^"]+)" class="([^"]*)" data-movement="(\d+)"')
CUE_INDEX_RE = re.compile(
    r'<script type="application/json" id="cue-index">(.*?)</script>',
    re.DOTALL)
# the presenter's stand-in for a preview it must never take (a live screen)
NO_PREVIEW_LABEL = "live window capture, no preview"
FIGURE_RE = re.compile(r'<figure class="shot" data-slug="([^"]+)"')
IMG_SRC_RE = re.compile(r'<img[^>]* src="([^"]+)"')
VIDEO_RE = re.compile(r"<video\b")
H1_RE = re.compile(r"<h1>(.*?)</h1>")
MOVEMENT_H2_RE = re.compile(
    r'<section class="movement" data-movement="\d+"><h2 class="movement">'
    r"(.*?)</h2>")
OPENING_RE = re.compile(r'<section class="opening">')
SOURCES_RE = re.compile(r'<section class="sources">')
SOURCES_LI_RE = re.compile(r'<ol class="doc-sources">(.*?)</ol>', re.DOTALL)
LI_RE = re.compile(r"<li>(.*?)</li>")


def _scan_links(text: str) -> list:
    """Every external-scheme reference a browser would follow."""
    hits = []
    for m in re.finditer(r'(?:src|href)\s*=\s*"([^"]+)"', text):
        u = m.group(1)
        if "://" in u:
            hits.append(u)
    hits += re.findall(r"@import\s+url\(['\"]?(https?://[^)'\"]+)", text)
    hits += re.findall(r"@import\s+['\"]?(https?://[^)'\"]+)", text)
    return hits


def check(fx, errors: list) -> None:
    cues = fx.cues()
    ids = [c["id"] for c in cues["cues"]]
    present = (fx.out / "present" / "index.html")
    presenter = (fx.out / "present" / "presenter.html")
    doc = (fx.out / "document" / "index.html")
    for name, p in (("present", present), ("presenter", presenter),
                    ("document", doc)):
        if not p.is_file():
            err(errors, f"{name}: missing {p}")
            return
    pres_text = present.read_text(encoding="utf-8")
    presenter_text = presenter.read_text(encoding="utf-8")
    doc_text = doc.read_text(encoding="utf-8")

    # -- both views: no remote assets, no machine-local paths ---------------
    for name, text in (("present", pres_text), ("presenter", presenter_text),
                       ("document", doc_text)):
        remote = _scan_links(text)
        if remote:
            err(errors, f"{name} html references remote assets: {remote[:5]}")
        hits = sorted({s for s in re.findall(r'["\']([^"\']+)["\']', text)
                       if ABS_PATH_RE.search(s)})
        if hits:
            err(errors, f"{name} html leaks machine-local paths: {hits[:5]}")
        if "<video" in text:
            if name == "present":
                # file-backed media videos carry the cinematic attribute set
                # (autoplay muted loop playsinline, no native controls). A live
                # capture surface is the exception and is checked below: a live
                # stream has nothing to autoplay until the presenter starts it,
                # and no end to loop.
                for m in re.finditer(r"<video[^>]*>", text):
                    tag = m.group(0)
                    if "live-surface" in tag:
                        for attr in ("muted", "playsinline"):
                            if attr not in tag:
                                err(errors, f"present live surface missing {attr}")
                        if re.search(r"\scontrols\b", tag):
                            err(errors, "present live surface must not carry "
                                        "native controls")
                        continue
                    if "media-video" not in tag:
                        continue
                    for attr in ("autoplay", "muted", "loop", "playsinline"):
                        if attr not in tag:
                            err(errors, f"present video missing {attr}")
                    if re.search(r"\scontrols\b", tag):
                        err(errors, "present video must not carry native controls")
            if 'src="http' in text:
                err(errors, f"{name} video/asset src is remote")

    # -- present view: sections mirror cues --------------------------------
    sections = SECTION_RE.findall(pres_text)
    if [s[0] for s in sections] != ids:
        err(errors, "present sections do not mirror cue ids in order")
    if len(sections) != len(ids):
        err(errors, f"present sections {len(sections)} != cues {len(ids)}")
    for (cid, cls, mv), cue in zip(sections, cues["cues"]):
        if cls.split() and cls.split()[0] != "animatic-slide":
            err(errors, f"section {cid}: first class is not animatic-slide")
        if int(mv) != cue["movement"]:
            err(errors, f"section {cid}: data-movement {mv} != cue movement "
                        f"{cue['movement']}")
        active = "active" in cls.split()
        if cue is cues["cues"][0] and not active:
            err(errors, "first slide is not active server-side")
        if cue is not cues["cues"][0] and active:
            err(errors, f"slide {cid} is active but not the first")
        if "<aside class=\"notes\">" not in pres_text.split(f'id="{cid}"', 1)[-1].split("</section>", 1)[0]:
            err(errors, f"section {cid}: no speaker-notes aside")
        if cue["kind"] == "black" and "black-beat" not in cls.split():
            err(errors, f"section {cid}: black cue lacks black-beat class")

    # media rendering: found -> <img ../_media/...>; placeholder -> aria
    found_srcs = set(IMG_SRC_RE.findall(pres_text))
    for cue in cues["cues"]:
        media = cue.get("media")
        if not media:
            continue
        if media.get("source") == "live":
            # a live screen renders the capture host, never an img/video file
            label = f'data-live-slug="{media.get("slug")}"'
            if label not in pres_text:
                err(errors, f"cue {cue['id']}: live host for "
                            f"{media.get('slug')!r} missing from present html")
            if 'data-live-surface' not in pres_text:
                err(errors, f"cue {cue['id']}: live host lacks data-live-surface")
            poster = media.get("poster")
            if poster:
                want = "../" + poster
                if want not in pres_text:
                    err(errors, f"cue {cue['id']}: live poster {want!r} missing "
                                f"from present html")
            continue
        if media.get("found"):
            want = "../" + media.get("file", "")
            if want not in pres_text:
                err(errors, f"cue {cue['id']}: found media {want!r} missing "
                            f"from present html")
            if media.get("file") not in found_srcs and want not in found_srcs:
                err(errors, f"cue {cue['id']}: img src {want!r} not found")
        else:
            label = f"media pending: {media.get('slug')}"
            if f'aria-label="{label}"' not in pres_text:
                err(errors, f"cue {cue['id']}: placeholder figure for "
                            f"{media.get('slug')!r} missing from present html")

    # the hookup panel ships exactly when the deck has a live screen
    any_live = any(
        (c.get("media") or {}).get("source") == "live" for c in cues["cues"])
    has_panel = 'id="hookup-panel"' in pres_text
    if any_live != has_panel:
        err(errors, "hookup panel presence does not match the deck's live "
                    f"screens (live={any_live}, panel={has_panel})")

    # A live screen puts interactive controls UNDER the presentational text
    # layer, which sits above the media zone. If the text layer is not
    # click-through it swallows every pointer event aimed at the capture: no
    # click, and not even a hover. This bit once (a real engine hit test showed
    # elementFromPoint returning .screen-body at the button's centre while a
    # synthetic .click() still "worked", which is why hit testing, not a
    # synthetic click, is the test). Pin the rule for decks that have one.
    if any_live:
        if not re.search(r"\.screen-body\s*\{[^}]*pointer-events:\s*none",
                         pres_text, re.S):
            err(errors, "live deck: the text layer (.screen-body) is not "
                        "click-through, so it would swallow input aimed at the "
                        "capture's controls")
        if not re.search(r"pointer-events:\s*auto", pres_text):
            err(errors, "live deck: nothing inside the text layer re-enables "
                        "pointer events, so interactive text would be dead")
        # The frame must hug the picture: a `piece` box is shaped by the
        # viewport, so a capture of another shape got `object-fit: contain`
        # bars inside it, and the border (on the element) outlined the bars.
        # Two halves, because checking for the attribute name alone is a
        # false-green generator: the stylesheet mentions `[data-live-ratio]` in
        # a selector, so the CSS satisfies a naive check even when nothing ever
        # sets it (caught by negative control, not by review).
        if "[data-live-ratio]" not in pres_text or "--live-ratio" not in pres_text:
            err(errors, "live deck: no frame-fit rule, so a capture of any "
                        "other shape gets letterbox bars inside the frame")
        if 'setAttribute("data-live-ratio"' not in pres_text:
            err(errors, "live deck: nothing ever sets the frame ratio from the "
                        "stream, so the fit rule can never take effect")

    # -- the deck's side of the presenter window ----------------------------
    # Two bindings moved when the presenter became a second window, and one
    # control appeared with it: the deck must be able to say when the browser
    # refused to open the window (a key that silently does nothing looks
    # broken), and the notes panel moved off 's' to 'n' so a one-screen room
    # keeps it.
    if 'id="deck-status"' not in pres_text:
        err(errors, "present: no deck status line, so a blocked presenter "
                    "window has nowhere to say so on screen")
    if "presenter.html" not in pres_text:
        err(errors, "present: the pager never opens the presenter window")

    # -- diagnostics ---------------------------------------------------------
    # The dump exists because two bugs in one day were invisible to state
    # checks: a control covered by an overlay, and a capture that died by
    # `mute` rather than `ended`. So the panel, the key, and — the part that
    # matters — a real elementFromPoint hit test must all be present. A dump
    # that only reports state would have passed both times.
    if 'id="debug-output"' not in pres_text:
        err(errors, "present: no diagnostics panel, so the dump has nowhere "
                    "to render on screen when devtools is shut")
    if not re.search(r'e\.key === "i"', pres_text):
        err(errors, "present: no key binding for the diagnostics dump")
    if "window.animatic.debug = collect" not in pres_text:
        err(errors, "present: the dump is not exposed on window.animatic, so "
                    "an agent driving the deck cannot read it")
    if "elementFromPoint" not in pres_text:
        err(errors, "present: the diagnostics dump does no hit test, so a "
                    "covered control would report as healthy")
    if "window.animatic.presenter" not in pres_text:
        err(errors, "present: nothing exposes whether a presenter window is "
                    "actually open, so the dump would guess")
    if 'id="presenter-live"' not in presenter_text:
        err(errors, "presenter: no live control slot, so a capture can only be "
                    "stopped from the deck window")
    if "animatic-live" not in presenter_text:
        err(errors, "presenter: the live control cannot reach the deck")
    if "liveCue" not in pres_text:
        err(errors, "present: the payload carries no live cue, so the presenter "
                    "cannot say what the capture is doing")
    if not re.search(r'id="stage"[^>]*data-deck="', pres_text):
        err(errors, "present: the stage carries no deck slug, so a dump "
                    "cannot say which deck produced it")
    if not re.search(r'class="animatic-slide[^"]*"[^>]*data-kind="', pres_text):
        err(errors, "present: screens carry no data-kind, so a dump reports "
                    "position without the screen's kind")
    if re.search(r'case "s":\s*case "S":\s*toggleNotes', pres_text):
        err(errors, "present: 's' still toggles the in-page notes panel; it "
                    "opens the presenter window now")
    if not re.search(r'case "n":\s*case "N":\s*toggleNotes', pres_text):
        err(errors, "present: 'n' does not toggle the in-page notes panel")
    # a note paragraph must never carry `class="stage"`: `.stage` is the fixed
    # full-viewport slide container, so such a paragraph leaves the notes panel
    # and covers the slide. It also swallowed the presenter window's own
    # controls until a hit test caught it.
    if '<p class="stage">' in pres_text:
        err(errors, "present: a note paragraph carries class='stage', which "
                    "matches the fixed full-viewport .stage container")

    # -- presenter view: the second-window speaker UI -----------------------
    # Two windows over one folder may not be same-origin (a deck opened from
    # file:// gives every document its own opaque origin), so the presenter
    # cannot drive a copy of the deck: the presenter page carries the identity
    # half of every cue as a build-time index, and the deck pushes the runtime
    # half (script, stage notes, previews) by postMessage. The index comes from
    # the same parse as cues.json, which is what makes the load-bearing
    # property static: a live screen is marked preview-less before anything
    # runs, so no second sink can ever attach to a capture stream.
    pm = CUE_INDEX_RE.search(presenter_text)
    if not pm:
        err(errors, "presenter: no cue-index block (the speaker UI has no "
                    "identity to render before the deck speaks)")
    else:
        try:
            index = json.loads(pm.group(1))
        except ValueError as exc:
            index = {}
            err(errors, f"presenter: cue index is not JSON: {exc}")
        rows = index.get("cues") or []
        if index.get("schema") != "animatic.presenter.v1":
            err(errors, f"presenter: cue index schema {index.get('schema')!r} "
                        f"!= 'animatic.presenter.v1'")
        if [r.get("id") for r in rows] != ids:
            err(errors, "presenter: cue index ids do not mirror cues.json in "
                        "order")
        labels = {m["index"]: m["label"] for m in cues["movements"]}
        for row, cue in zip(rows, cues["cues"]):
            if row.get("ordinal") != cue["ordinal"]:
                err(errors, f"presenter {row.get('id')}: ordinal "
                            f"{row.get('ordinal')} != cues {cue['ordinal']}")
            if row.get("movement") != cue["movement"]:
                err(errors, f"presenter {row.get('id')}: movement "
                            f"{row.get('movement')} != cues {cue['movement']}")
            want_label = labels.get(cue["movement"], "")
            if (row.get("movement_label") or "") != want_label:
                err(errors, f"presenter {row.get('id')}: movement label "
                            f"{row.get('movement_label')!r} != {want_label!r}")
            if row.get("kind") != cue["kind"]:
                err(errors, f"presenter {row.get('id')}: kind "
                            f"{row.get('kind')!r} != cues {cue['kind']!r}")
            want_title = plain_md(cue["title"]) if cue.get("title") else ""
            if (row.get("title") or "") != want_title:
                err(errors, f"presenter {row.get('id')}: title "
                            f"{row.get('title')!r} != {want_title!r}")
            # the preview-less rule, stated where it can be checked without a
            # browser: live in cues.json == live in the presenter's index
            is_live = (cue.get("media") or {}).get("source") == "live"
            if bool(row.get("live")) != is_live:
                err(errors, f"presenter {row.get('id')}: live="
                            f"{row.get('live')} but cues.json says {is_live}"
                            f" (a live screen must be preview-less, and only "
                            f"a live screen may be)")
        if any(row.get("live") for row in rows) and not re.search(
                r"cue\.live[\s\S]{0,400}?" + re.escape(NO_PREVIEW_LABEL),
                presenter_text):
            err(errors, "presenter: a cue is marked preview-less but the "
                        "presenter never renders the no-preview label for it")
        if not any(row.get("live") for row in rows) and NO_PREVIEW_LABEL \
                not in presenter_text:
            err(errors, "presenter: the no-preview label is missing, so a "
                        "live screen in any deck would render an empty box")

    # -- document view ------------------------------------------------------
    deck = cues["deck"]
    deck_title = str(deck.get("title") or fx.slug)
    h1s = [html_mod.unescape(x) for x in H1_RE.findall(doc_text)]
    if h1s != [deck_title]:
        err(errors, f"document h1 {h1s!r} != deck title {deck_title!r}")
    if doc_text.count("<section class=\"movement\"") != len(cues["movements"]):
        err(errors, "document movement sections != cues movements")
    labels = [html_mod.unescape(x) for x in MOVEMENT_H2_RE.findall(doc_text)]
    want_labels = [m["label"] for m in cues["movements"]]
    if labels != want_labels:
        err(errors, f"document movement labels {labels!r} != cues labels "
                    f"{want_labels!r}")

    # opening section iff any movement-0 screen is not a black beat
    has_opening_content = any(
        c["movement"] == 0 and c["kind"] != "black" for c in cues["cues"])
    if has_opening_content != bool(OPENING_RE.search(doc_text)):
        err(errors, "document opening section presence does not match "
                    "movement-0 content")

    # figures per media screen (black beats are skipped in the document)
    doc_figures = FIGURE_RE.findall(doc_text)
    want_fig_slugs = [
        c["media"]["slug"]
        for c in cues["cues"]
        if c.get("media") and c["kind"] != "black"
    ]
    if doc_figures != want_fig_slugs:
        err(errors, f"document figure data-slugs {doc_figures} != cues media "
                    f"slugs {want_fig_slugs}")

    # Sources section mirrors deck.sources (spec: Text: one citation list)
    sources = deck.get("sources") or []
    if sources:
        m = SOURCES_LI_RE.search(doc_text)
        if not m or not SOURCES_RE.search(doc_text):
            err(errors, "deck cites sources but document has no Sources "
                        "section")
        if m:
            lis = [html_mod.unescape(x) for x in LI_RE.findall(m.group(1))]
            want = [s["source"] for s in sources]
            if lis != want:
                err(errors, f"document Sources list {lis!r} != deck.sources "
                            f"{want!r}")
    elif SOURCES_RE.search(doc_text):
        err(errors, "document shows a Sources section but deck.sources is "
                    "empty")
