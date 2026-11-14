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

import talkparse
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
LI_RE = re.compile(r"<li(?: [^>]*)?>(.*?)</li>")


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
    # the parse model, for the checks that need a screen's block order (the
    # reading copy depends on where the presenter's words stand)
    talk = talkparse.build_talk(str(fx.talkfile))
    screens = talk.screens

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
                # (data-autoplay muted loop playsinline preload=none, no native
                # controls; the pager plays and warms them). A live
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
                    # a play-once video (card `playback: once`) is the one
                    # that must NOT loop: it holds its last frame
                    once = 'data-playback="once"' in tag
                    for attr in ("data-autoplay", "muted", "playsinline") + (() if once else ("loop",)):
                        if not re.search(r"\s" + re.escape(attr) + r"\b", tag):
                            err(errors, f"present video missing {attr}")
                    # the pager plays and warms slide videos; a bare autoplay
                    # or an eager preload makes a served deck fetch every video
                    # at load and starve the images (2026-09-28)
                    if re.search(r"\sautoplay\b", tag):
                        err(errors, "present video must not carry autoplay (the pager plays it)")
                    if 'preload="none"' not in tag:
                        err(errors, "present video must be preload=\"none\" (the pager warms it)")
                    if once and re.search(r"\sloop\b", tag):
                        err(errors, "present play-once video must not loop")
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
    for (cid, cls, mv), cue, screen in zip(sections, cues["cues"], screens):
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
        # -- the reading copy: the notes carry the screen's text that follows
        #    the presenter's words, or all of it on a screen with no words
        #    (spec: Text — The reading copy).  Checked against the built HTML.
        section = pres_text.split(f'id="{cid}"', 1)[-1].split("</section>", 1)[0]
        nm = re.search(r'<aside class="notes">(.*?)</aside>', section, re.S)
        notes_html = html_mod.unescape(nm.group(1)) if nm else ""
        silent = not (cue.get("script") or "").strip()
        spoken_before = False
        for b in screen.blocks:
            if (b.kind == "vo" and b.text.strip()) or \
                    (b.kind in ("stat", "paraphrase") and b.spoken and b.text.strip()):
                spoken_before = True
                continue
            if b.kind == "list" and b.items:
                probe = plain_md(str(b.items[0]))
            elif b.kind == "quote" and b.text.strip():
                probe = plain_md(b.text.split("\n")[0])
            elif b.kind == "code" and b.text.strip():
                probe = b.text.split("\n")[0].strip()
            else:
                continue
            if not (spoken_before or silent):
                continue        # the text stands before his words: not copied
            if probe and probe not in notes_html:
                err(errors, f"cue {cid}: the notes do not carry the screen's "
                            f"{b.kind} ({probe[:40]!r}) — the reading copy is "
                            f"missing")
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
        if media.get("steps"):
            # stepped-image card: the section is either a stack of one frame
            # per step (each frame the step slug's published file), or, with
            # reveal=off or on a continue screen, the one plain image
            sect = pres_text.split(f'id="{cue["id"]}"', 1)[-1].split("</section>", 1)[0]
            frames = re.findall(r'<img data-frame="(\d+)"[^>]* src="([^"]+)"', sect)
            off = any("off" in str(sh.get("flags", {}).get("reveal", "")).split("+")
                      for sh in cue.get("shots", []))
            if off and frames:
                err(errors, f"cue {cue['id']}: reveal=off but the section still steps")
            if frames:
                if [int(n) for n, _ in frames] != list(range(1, len(media["steps"]) + 1)):
                    err(errors, f"cue {cue['id']}: step frames {frames!r} != "
                                f"{len(media['steps'])} steps")
                if sect.count('class="on ') != 1 or not frames[0][1].endswith(
                        tuple(f"{media['steps'][0]}.{e}" for e in
                              ("png", "jpg", "jpeg", "webp", "gif", "svg"))):
                    err(errors, f"cue {cue['id']}: frame 1 is not the one shown first")
            elif "<img " not in sect:
                err(errors, f"cue {cue['id']}: stepped card renders no image at all")
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
        # A capture in the DUO column has to size ITSELF: the duo zone is left
        # at auto height by `top: 50%; transform: translateY(-50%)`, and it is
        # size-contained, so `100cqh` measures 0 and the host collapsed to a
        # 2px sliver beside the text (measured in a real engine on W04's
        # "Meet Search Desk" screen, 2026-10-18). The fix is a duo-local rule,
        # so assert the rule AND its shape: a check for the selector alone
        # passes against an empty rule.
        duo_live = [c for c in cues["cues"]
                    if (c.get("media") or {}).get("source") == "live"
                    and (((c.get("shots") or [{}])[0].get("flags") or {})
                         .get("layout") == "duo")]
        if duo_live:
            for c in duo_live:
                cls = next((cl for cid, cl, _ in sections if cid == c["id"]), "")
                if "duo" not in cls.split():
                    err(errors, f"cue {c['id']}: live screen declares layout=duo "
                                f"but its slide carries no duo class ({cls!r})")
                # A live duo screen is a DEMO slide and takes demo
                # proportions; the plain duo split gives the capture the
                # object-sized 32vw column, which reads as a small window in
                # the room (Ryan, 2026-10-18).
                if "duo-live" not in cls.split():
                    err(errors, f"cue {c['id']}: live screen in the duo layout "
                                f"is not marked duo-live, so the capture keeps "
                                f"the object-sized column ({cls!r})")
            if not re.search(r"\.animatic-slide\.duo-live \.media-zone\.piece\.duo"
                             r"\s*\{[^}]*width:", pres_text, re.S):
                err(errors, "live deck with a duo screen: no duo-live rule gives "
                            "the capture its own pane, so it keeps the "
                            "object-sized column")
            rule = re.search(r"\.animatic-slide\.duo-live \.media-zone\.piece\.duo "
                             r"\.live-host,\s*\.animatic-slide\.duo-live "
                             r"\.media-zone\.piece\.duo \.live-host\[data-live-ratio\]"
                             r"\s*\{([^}]*)\}", pres_text, re.S)
            if not rule:
                err(errors, "live deck with a duo screen: no rule sizes the "
                            "capture to the duo pane, where the zone's own "
                            "height is 0")
            else:
                body = " ".join(rule.group(1).split())
                for need in ("width: 100%", "height: 100%", "aspect-ratio: auto"):
                    if need not in body:
                        err(errors, f"duo live pane rule is missing {need!r}: "
                                    f"{body[:160]}")
                if "cqh" in body:
                    err(errors, "duo live pane rule measures against the zone's "
                                "container height, which is 0 in a duo column")

    # -- layout=split: half text, half media ----------------------------------
    # The slide carries `split`, and the stylesheet gives the pane the right
    # half edge to edge (inset: 0 0 0 auto; width: 50%) and the text the left
    # half. Assert the rules' shape, not the selector alone.
    split_cues = [c for c in cues["cues"]
                  if (((c.get("shots") or [{}])[0].get("flags") or {}).get("layout")
                      == "split")]
    for c in split_cues:
        cls = next((cl for cid, cl, _ in sections if cid == c["id"]), "")
        if "split" not in cls.split():
            err(errors, f"cue {c['id']}: declares layout=split but its slide "
                        f"carries no split class ({cls!r})")
    if split_cues:
        pane = re.search(r"\.media-zone\.split\s*\{([^}]*)\}", pres_text, re.S)
        body = " ".join(pane.group(1).split()) if pane else ""
        if "inset: 0 0 0 auto" not in body or "width: 50%" not in body:
            err(errors, f"split deck: no rule puts the media in the right half, "
                        f"edge to edge: {body[:160]!r}")
        text = re.search(r"\.animatic-slide\.split \.screen-body\s*\{([^}]*)\}",
                         pres_text, re.S)
        if not text or "width: 50%" not in text.group(1):
            err(errors, "split deck: no rule gives the text the left half")

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
    # `reveal=list` is a presentation effect only: the handout and its PDF show
    # every item, so the document view carries no reveal markup at all.
    if "data-reveal" in doc_text or "data-step" in doc_text:
        err(errors, "document view carries reveal markup (reveal is present-only)")
    # stepped images are present-only too: the document and handout print the
    # card's one handout image, never the frames
    if "class=\"step-stack\"" in doc_text or " data-frame=\"" in doc_text:
        err(errors, "document view carries stepped-image markup (steps are present-only)")
    for cue in cues["cues"]:
        m = cue.get("media") or {}
        if m.get("steps"):
            for st in m["steps"]:
                if re.search(rf'<figure class="shot" data-slug="{re.escape(st)}"', doc_text):
                    err(errors, f"cue {cue['id']}: document prints step frame {st!r} as its own figure")

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
        c["movement"] == 0 and c["kind"] != "black" and not c.get("live_only")
        for c in cues["cues"])
    if has_opening_content != bool(OPENING_RE.search(doc_text)):
        err(errors, "document opening section presence does not match "
                    "movement-0 content")

    # figures per media screen (black beats are skipped in the document)
    doc_figures = FIGURE_RE.findall(doc_text)
    want_fig_slugs = [
        c["media"]["slug"]
        for c in cues["cues"]
        if c.get("media") and c["kind"] != "black" and not c.get("live_only")
        # a live capture with no poster prints nothing (no figure, words only)
        and not (c["media"].get("live") and not c["media"].get("poster"))
    ]
    # a figure naming the slug of the figure just before it (a `continue`
    # shot, or the same slug again) is printed once, at its first appearance
    want_fig_slugs = [slug for i, slug in enumerate(want_fig_slugs)
                      if i == 0 or slug != want_fig_slugs[i - 1]]
    if doc_figures != want_fig_slugs:
        err(errors, f"document figure data-slugs {doc_figures} != cues media "
                    f"slugs {want_fig_slugs}")

    # Sources section mirrors deck.sources (spec: Text: one citation list)
    sources = deck.get("sources") or []
    # no `cites:` map: the working receipts never print (unless the deck opts in)
    prints = (isinstance(fx.meta.get("cites"), dict)
              or str(fx.meta.get("handout-sources", "")).strip().lower() == "working")
    if sources and not prints:
        if SOURCES_RE.search(doc_text):
            err(errors, "deck has `sources:` but no `cites:`, yet the document "
                        "prints a Sources section")
    elif sources:
        m = SOURCES_LI_RE.search(doc_text)
        if not m or not SOURCES_RE.search(doc_text):
            err(errors, "deck cites sources but document has no Sources "
                        "section")
        if m:
            lis = [html_mod.unescape(x) for x in LI_RE.findall(m.group(1))]
            want = [s["source"] for s in sources]
            cites = fx.meta.get("cites")
            if isinstance(cites, dict):
                # the handout prints the public form, and leaves out an id with none
                want = [str(cites[s["id"]]) for s in sources
                        if str(cites.get(s["id"], "")).strip()]
            if lis != want:
                err(errors, f"document Sources list {lis!r} != deck.sources "
                            f"{want!r}")
    elif SOURCES_RE.search(doc_text):
        err(errors, "document shows a Sources section but deck.sources is "
                    "empty")

    # -- the reading page's addressability -----------------------------------
    # Every screen the document prints carries the cue id nav.json uses, so a
    # link into the handout has the same address as a cue in the deck.  The
    # contents list is generated from the talk's own headings, so its jumps
    # must resolve and must run in screen order; the per-screen source lines
    # must point at the one numbered list.  (These are the web-edition pass-1
    # contract: render.py emits `cue-<id>` wrappers, `_toc_html`, and
    # `_screen_sources_html`.)
    nav = json.loads((fx.out / "nav.json").read_text(encoding="utf-8"))
    doc_ids = re.findall(r'id="([^"]+)"', doc_text)
    id_set = set(doc_ids)
    dupes = sorted({i for i in doc_ids if doc_ids.count(i) > 1})
    if dupes:
        err(errors, f"document: duplicate id(s) {dupes[:3]} — an anchor jump "
                    "lands on the first one")
    want_cues = [k for k, v in nav["screens"].items() if v["document"]["present"]]
    missing = [k for k in want_cues if f"cue-{k}" not in id_set]
    if missing:
        err(errors, f"document: {len(missing)} present screen(s) carry no "
                    f"cue anchor, first {missing[:3]}")
    if [k for k in doc_ids if k.startswith("cue-") and k[4:] not in nav["screens"]]:
        err(errors, "document: cue anchor(s) that nav.json does not name")

    toc_blocks = re.findall(r'<nav class="doc-toc[^"]*"[^>]*>(.*?)</nav>',
                            doc_text, re.DOTALL)
    ordinal = {k: v["ordinal"] for k, v in nav["screens"].items()}
    for block in toc_blocks:
        hrefs = re.findall(r'href="#([^"]+)"', block)
        dead = [h for h in hrefs if h not in id_set]
        if dead:
            err(errors, f"document: contents link(s) with no target {dead[:3]}")
        order = [ordinal[h[4:]] for h in hrefs if h.startswith("cue-") and h[4:] in ordinal]
        if order != sorted(order):
            err(errors, "document: contents entries are not in screen order")
    for block in re.findall(r'<p class="screen-sources">(.*?)</p>', doc_text, re.DOTALL):
        dead = [h for h in re.findall(r'href="#(src-\d+)"', block) if h not in id_set]
        if dead:
            err(errors, f"document: screen source link(s) with no target {dead[:3]}")

