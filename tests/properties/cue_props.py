"""Property checks over cues.json (spec: Outputs + Verification invariants).

Byte goldens pin exact content; these pin structural invariants that a
re-blessed golden could otherwise hide: id shape and ordering, movement
partitions, the citation list derivation, and the never-spoken hygiene
rules (parens, footnote markers, em dashes in screen text).
"""

from __future__ import annotations

from .common import (
    ABS_PATH_RE, EM_DASH, KINDS, TEXT_ENTRY_KINDS,
    derive_sources, err, text_entries, walk_strings,
)


def check(fx, errors: list) -> None:
    cues = fx.cues()
    deck = cues.get("deck")
    if not isinstance(deck, dict):
        err(errors, "cues.json: deck object missing")
        return

    if cues.get("schema") != "animatic.cues.v1":
        err(errors, f"cues.json: schema is {cues.get('schema')!r}, "
                    f"expected 'animatic.cues.v1'")

    for key in ("slug", "title", "date", "venue", "format", "dur",
                "theme", "media_dir", "bank"):
        if key not in deck:
            err(errors, f"cues.json deck: missing field {key!r}")
    if not isinstance(deck.get("sources"), list):
        err(errors, "cues.json deck.sources must be a list")

    # citation list must equal the source derivation (receipts Text/Outputs)
    want_sources = derive_sources(fx.meta, fx.source_text)
    if deck.get("sources") != want_sources:
        err(errors, f"deck.sources != derived citations: got "
                    f"{deck.get('sources')!r}, want {want_sources!r}")

    ids = [c.get("id") for c in cues.get("cues", [])]
    if not ids:
        err(errors, "cues.json: no cues (a deck with zero screens is a defect)")
        return
    if len(set(ids)) != len(ids):
        dup = sorted({i for i in ids if ids.count(i) > 1})
        err(errors, f"cue ids not unique: {dup}")
    if ids != sorted(ids):
        err(errors, "cue ids not in lexical (== ordinal) order")

    n = len(cues["cues"])
    prefix = f"{fx.slug}-"
    for i, cue in enumerate(cues["cues"], start=1):
        cid = cue.get("id")
        if cid != f"{prefix}{i:03d}":
            err(errors, f"cue {i}: id {cid!r} != {prefix}{i:03d} "
                        f"(slug/ordinal/padding regression)")
            continue
        if cue.get("ordinal") != i:
            err(errors, f"cue {i}: ordinal {cue.get('ordinal')!r} != {i}")
        kind = cue.get("kind")
        if kind not in KINDS:
            err(errors, f"cue {cid}: unknown kind {kind!r} "
                        f"(not in {KINDS})")
        if cue.get("kind") == "black" and cue.get("media") is not None:
            err(errors, f"cue {cid}: a black beat carries media")
        for field_key in ("script", "stage", "title", "screen_text", "shots"):
            if field_key not in cue:
                err(errors, f"cue {cid}: missing field {field_key!r}")

        # never-spoken hygiene: parentheticals and receipts never reach the
        # script or any screen text; screen text carries no em dashes.
        script = cue.get("script") or ""
        for bad, what in (("(", "a parenthetical"), ("[^", "a footnote marker")):
            if bad in script:
                err(errors, f"cue {cid}: script contains {what}")
        if EM_DASH in (cue.get("title") or ""):
            err(errors, f"cue {cid}: screen title contains an em dash")
        for piece in text_entries(cue):
            if "(" in piece or "[^" in piece:
                err(errors, f"cue {cid}: screen text carries a parenthetical "
                            f"or footnote marker: {piece[:60]!r}")
            if EM_DASH in piece:
                err(errors, f"cue {cid}: screen text contains an em dash: "
                            f"{piece[:60]!r}")
        for t in cue.get("screen_text") or []:
            if t.get("kind") not in TEXT_ENTRY_KINDS:
                err(errors, f"cue {cid}: screen_text kind "
                            f"{t.get('kind')!r} not in {TEXT_ENTRY_KINDS}")
        if cue.get("script") is not None and not isinstance(cue.get("script"), str):
            err(errors, f"cue {cid}: script must be a string")

        media = cue.get("media")
        if media is not None:
            if not isinstance(media, dict):
                err(errors, f"cue {cid}: media must be an object or null")
            elif not media.get("slug"):
                err(errors, f"cue {cid}: media object carries no slug")
            elif cue.get("kind") == "black":
                err(errors, f"cue {cid}: black beat carries media")
            elif "steps" in media:
                # stepped-image card: 2+ frame slugs, and the handout image is
                # one of them or the card's own
                st = media["steps"]
                if not (isinstance(st, list) and len(st) >= 2
                        and all(isinstance(x, str) and x for x in st)):
                    err(errors, f"cue {cid}: media.steps must be 2+ slugs, got {st!r}")
                elif media.get("handout") not in st + [media["slug"]]:
                    err(errors, f"cue {cid}: media.handout {media.get('handout')!r} is "
                                f"neither a step nor the card itself")

    # movement partition: every screen belongs to exactly one movement, and
    # movement.cue_ids must mirror it (spec: Screens / Outputs).
    movements = cues.get("movements", [])
    idxs = [m.get("index") for m in movements]
    if idxs:
        if idxs != sorted(idxs) or idxs != list(range(1, len(idxs) + 1)):
            err(errors, f"movement indexes not contiguous 1..N: {idxs}")
    flat = []
    for m in movements:
        flat.extend(m.get("cue_ids") or [])
    if len(flat) != len(set(flat)):
        err(errors, "movement cue_ids overlap across movements")
    moved = set(flat)
    for c in cues["cues"]:
        cid = c.get("id")
        mv = c.get("movement")
        if idxs:
            if mv not in ({0} | set(idxs)):
                err(errors, f"cue {cid}: movement {mv!r} outside "
                            f"{{0}} + {idxs}")
        elif mv != 0:
            err(errors, f"cue {cid}: movement {mv!r} but no movements "
                        f"declared")
        if mv and mv in set(idxs):
            if cid not in moved:
                err(errors, f"cue {cid}: movement {mv} has no cue_ids entry")
        elif cid in moved:
            err(errors, f"cue {cid}: movement-0 screen listed in a "
                        f"movement's cue_ids")
    for m in movements:
        mlist = m.get("cue_ids") or []
        want = [c.get("id") for c in cues["cues"]
                if c.get("movement") == m.get("index")]
        if mlist != want:
            err(errors, f"movement {m.get('index')}: cue_ids != screens "
                        f"with that movement")

    # stage notes: a list of plain strings when present
    for c in cues["cues"]:
        st = c.get("stage")
        if st is not None and not (isinstance(st, list)
                                   and all(isinstance(x, str) for x in st)):
            err(errors, f"cue {c.get('id')}: stage must be a list of strings")

    # no machine-local paths in any emitted string (spec: Outputs / check 17)
    hits = sorted({s for s in walk_strings(cues) if ABS_PATH_RE.search(s)})
    if hits:
        err(errors, f"cues.json leaks machine-local paths: {hits[:5]}")
