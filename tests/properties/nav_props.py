"""Property checks over nav.json (spec: Outputs — addressability).

nav.json is generated, never authored: cue id -> source line range, movement,
kind, plus the document view's omission flag.  Nothing else pins it (the spec
golds only cues.json and media-manifest.json), so these properties are what
keeps the map honest:

  - the entries are exactly cues.json's ids, in order, and agree per screen
    (ordinal, movement, kind) — one screen = one cue = one entry, always;
  - the entry shape is frozen: no unit ids, no `id` field, no grouping span;
  - ranges are ordered, never overlap, start at 1 or later, and each start is
    a screen boundary: the shot directive that opens the screen (the
    directive's own first line, even when it wraps across lines), or the
    first line of prose for a shot-opened-nowhere card;
  - every non-blank body line outside the ranges is structurally inert — a
    movement heading, a non-shot comment, or a horizontal rule.  Content left
    unowned means a range ended before the screen it maps (a soft-wrapped
    paragraph whose last line went unrecorded lands here);
  - the document flag mirrors the black kind, which the other layers pin
    independently: cues.json carries the kind, html_props requires the
    present section to wear the black-beat class, and the document view's
    figure list must skip exactly those screens.
"""

from __future__ import annotations

from .common import ABS_PATH_RE, body_lines, err, frontmatter_lines, walk_strings

ENTRY_KEYS = {"ordinal", "movement", "kind", "lines", "document"}
DOCUMENT_OMISSION_REASONS = {"black": "black-beat", "live-only": "live-only"}


def _handout_heading_at(src: list, start: int) -> bool:
    """A handout heading (spec: Text, rule 3) opens its screen's range: a
    heading line whose next non-blank, non-comment line is a shot directive."""
    if not src[start - 1].lstrip().startswith("#"):
        return False
    j = start
    while j < len(src):
        ln = src[j].strip()
        if ln and not (ln.startswith("<!--") and not ln.startswith("<!-- shot")
                       and not ln.startswith("<!--shot")):
            return _shot_comment_at(src, j + 1) is not None
        j += 1
    return False


def _shot_comment_at(lines: list, start: int):
    """The joined comment text beginning at body line `start`, or None.

    A shot directive may wrap (spec: Screens, check 27), so the boundary is
    the comment's first line: accumulate to `-->` and hand back the joined
    text the lexer's own SHOT_RE sees.
    """
    from talkparse import SHOT_RE
    if not (1 <= start <= len(lines)):
        return None
    if not lines[start - 1].lstrip().startswith("<!--"):
        return None
    buf = [lines[start - 1].strip()]
    i = start - 1
    while "-->" not in buf[-1] and i + 1 < len(lines):
        i += 1
        buf.append(lines[i].strip())
    joined = " ".join(buf)
    return joined if SHOT_RE.match(joined) else None


def _inert_lines(lines: list) -> set:
    """1-based body lines the grammar drops, so no screen owns them.

    A non-shot comment occupies every line of its span; a `---` rule is inert
    (spec: Screens tolerance); a level-2 movement heading closes the screen
    above it and belongs to none (spec: Movements).  Blank lines are dropped
    by the paragraph lexer.
    """
    from talkparse import HR_RE, _is_section_heading, _lex_blocks
    inert: set = set()
    # `##` section headings (part / act / movement) are structure, not screen
    # text: classify them with the parser's own rule, on the lexed blocks.
    try:
        raw = _lex_blocks([l + "\n" for l in lines], "nav-props", None, None)
        for k, rb in enumerate(raw):
            if _is_section_heading(raw, k):
                inert.add(rb["line"])
    except Exception:
        pass
    i = 0
    total = len(lines)
    while i < total:
        line = lines[i]
        if line.lstrip().startswith("<!--"):
            j = i
            buf = [line]
            while "-->" not in buf[-1] and j + 1 < total:
                j += 1
                buf.append(lines[j])
            if _shot_comment_at(lines, i + 1) is None:
                inert.update(range(i + 1, j + 2))
            i = j + 1
            continue
        stripped = line.strip()
        if stripped:
            if HR_RE.match(line):
                inert.add(i + 1)
        else:
            inert.add(i + 1)
        i += 1
    return inert


def check(fx, errors: list) -> None:
    path = fx.out / "nav.json"
    if not path.is_file():
        err(errors, f"nav.json: missing from the build output ({path})")
        return
    nav = fx.nav()
    cues = fx.cues()

    if nav.get("schema") != "animatic.nav.v1":
        err(errors, f"nav.json: schema is {nav.get('schema')!r}, expected "
                    f"'animatic.nav.v1'")
    deck_slug = cues.get("deck", {}).get("slug")
    if nav.get("deck", {}).get("slug") != deck_slug:
        err(errors, f"nav deck.slug {nav.get('deck', {}).get('slug')!r} != "
                    f"cues deck.slug {deck_slug!r}")

    screens = nav.get("screens")
    if not isinstance(screens, dict):
        err(errors, "nav.json: `screens` must be an object keyed by cue id")
        return

    ids = [c["id"] for c in cues["cues"]]
    if list(screens) != ids:
        err(errors, f"nav.json: keys are not the cue ids in order "
                    f"({list(screens)[:3]}... vs {ids[:3]}...)")

    src = body_lines(fx.source_text)
    fm = frontmatter_lines(fx.source_text)
    # the frontmatter is dropped whole; scan the rest for inert lines with
    # the frontmatter blanked so its `---` is not read as a rule
    inert = _inert_lines(["" if k + 1 in fm else l for k, l in enumerate(src)]) | fm
    ranges = []

    for cue in cues["cues"]:
        entry = screens.get(cue["id"])
        if entry is None:
            err(errors, f"nav.json: no entry for cue {cue['id']}")
            continue
        if set(entry) != ENTRY_KEYS:
            err(errors, f"nav.json {cue['id']}: entry keys {sorted(entry)} != "
                        f"{sorted(ENTRY_KEYS)} — the map is cue id -> line "
                        f"range, movement, kind (no unit ids, no id field, no "
                        f"grouping span)")
        for field, want in (("ordinal", cue["ordinal"]),
                            ("movement", cue["movement"]),
                            ("kind", cue["kind"])):
            if entry.get(field) != want:
                err(errors, f"nav.json {cue['id']}: {field} "
                            f"{entry.get(field)!r} != cues {want!r}")

        # -- document view omission (spec: Screens) --------------------------
        doc = entry.get("document")
        if not isinstance(doc, dict) or "present" not in doc:
            err(errors, f"nav.json {cue['id']}: document flag missing")
        else:
            live = bool(cue.get("live_only"))
            want_present = cue["kind"] != "black" and not live
            want_reason = "live-only" if live and cue["kind"] != "black" else "black-beat"
            if doc.get("present") is not want_present:
                err(errors, f"nav.json {cue['id']}: document.present "
                            f"{doc.get('present')!r} but kind is "
                            f"{cue['kind']!r} — only a black beat or a live-only "
                            f"screen is omitted from the document view")
            if want_present and "reason" in doc:
                err(errors, f"nav.json {cue['id']}: document present but "
                            f"carries an omission reason")
            if not want_present and doc.get("reason") != want_reason:
                err(errors, f"nav.json {cue['id']}: document omission reason "
                            f"{doc.get('reason')!r} != {want_reason!r}")

        # -- line range ------------------------------------------------------
        lines = entry.get("lines") or {}
        start, end = lines.get("start"), lines.get("end")
        if not isinstance(start, int) or not isinstance(end, int):
            err(errors, f"nav.json {cue['id']}: lines must be integers "
                        f"(got {lines!r})")
            continue
        if start < 1:
            err(errors, f"nav.json {cue['id']}: range starts at line {start}; "
                        f"talkfile lines are 1-based")
        if end < start:
            err(errors, f"nav.json {cue['id']}: range {start}-{end} ends "
                        f"before it starts")
        ranges.append((cue["id"], start, end))

        line = src[start - 1] if 1 <= start <= len(src) else ""
        if not line.strip():
            err(errors, f"nav.json {cue['id']}: range starts at line {start}, "
                        f"which is blank — not a screen boundary")
        elif start in inert:
            err(errors, f"nav.json {cue['id']}: range starts at line {start}, "
                        f"which the grammar drops (comment / rule / movement "
                        f"heading) — not a screen boundary")
        elif (cue["shots"] and _shot_comment_at(src, start) is None
              and not _handout_heading_at(src, start)):
            err(errors, f"nav.json {cue['id']}: screen opens with a shot "
                        f"directive but the range starts at line {start}, "
                        f"which is not one")

    for (pid, _ps, pe), (cid, cs, _ce) in zip(ranges, ranges[1:]):
        if cs <= pe:
            err(errors, f"nav.json: {cid} starts at line {cs}, inside "
                        f"{pid}'s range (which ends at {pe}) — ranges must "
                        f"not overlap")

    owned: set = set()
    for _cid, s, e in ranges:
        owned.update(range(s, e + 1))
    stray = sorted(l for l in range(1, len(src) + 1)
                   if l not in owned and l not in inert)
    if stray:
        err(errors, f"nav.json: body line(s) {stray[:6]} belong to no range — "
                    f"a range ends before the screen it maps")

    for s in walk_strings(nav):
        if ABS_PATH_RE.search(s):
            err(errors, f"nav.json leaks a machine-local path: {s!r}")
