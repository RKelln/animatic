"""Property checks over the two HTML views (spec: Verification property assertions).

HTML is never byte-diffed (highest churn layer), so these properties are the
only thing keeping the views honest: present sections must mirror cues
1:1 with ids and movement attributes, the first slide is active server-side,
media renders found-or-placeholder exactly as the manifest says, no remote
assets and no machine-local paths ever appear, and the document view's
movement and Sources structure must match cues.json.
"""

from __future__ import annotations

import html as html_mod
import re
from html.parser import HTMLParser

from .common import ABS_PATH_RE, err


SECTION_RE = re.compile(
    r'<section id="([^"]+)" class="([^"]*)" data-movement="(\d+)"')
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
    doc = (fx.out / "document" / "index.html")
    for name, p in (("present", present), ("document", doc)):
        if not p.is_file():
            err(errors, f"{name}: missing {p}")
            return
    pres_text = present.read_text(encoding="utf-8")
    doc_text = doc.read_text(encoding="utf-8")

    # -- both views: no remote assets, no machine-local paths ---------------
    for name, text in (("present", pres_text), ("document", doc_text)):
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
