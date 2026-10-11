"""Property checks over media-manifest.json (spec: Media resolution + Outputs).

The manifest is the resolution audit: it must mirror the media slugs the
cues actually reference (first-appearance order and first_cue), every found
slug must be published under out/_media, placeholders must say why, and
unreferenced_cards must equal the card set minus what the deck used.
"""

from __future__ import annotations

import yaml

from .common import (
    ABS_PATH_RE, derived_slug_set, err, first_cue_of, walk_strings,
)


def check(fx, errors: list) -> None:
    man = fx.manifest()
    cues = fx.cues()

    if man.get("schema") != "animatic.media.v1":
        err(errors, f"media-manifest.json: schema is "
                    f"{man.get('schema')!r}, expected 'animatic.media.v1'")
    deck_slug = cues.get("deck", {}).get("slug")
    if man.get("deck_slug") != deck_slug:
        err(errors, f"manifest deck_slug {man.get('deck_slug')!r} != "
                    f"cues deck.slug {deck_slug!r}")

    refs = man.get("referenced", [])
    slugs = [r.get("slug") for r in refs]
    if not isinstance(man.get("referenced"), list):
        err(errors, "manifest referenced must be a list")
        return

    # mirror: manifest slugs == slug-bearing shots across cues, in order
    want_slugs = derived_slug_set(cues)
    if slugs != want_slugs:
        err(errors, f"manifest referenced slugs {slugs} != slugs derived "
                    f"from cues {want_slugs}")
    if len(slugs) != len(set(slugs)):
        err(errors, f"manifest referenced slugs repeat: "
                    f"{[s for s in slugs if slugs.count(s) > 1]}")

    for r in refs:
        slug, first = r.get("slug"), r.get("first_cue")
        md = r.get("media")
        if not isinstance(md, dict):
            err(errors, f"slug {slug!r}: media entry missing")
            continue
        if md.get("slug") != slug:
            err(errors, f"slug {slug!r}: media.slug {md.get('slug')!r}")
        if first != first_cue_of(cues, slug):
            err(errors, f"slug {slug!r}: first_cue {first!r} != first cue "
                        f"containing it ({first_cue_of(cues, slug)!r})")
        found = md.get("found")
        f = md.get("file")
        src = md.get("source")
        if src == "live":
            # `type: live`: a runtime window capture (docs/live-capture.md).
            # There is no file by definition, and the one disk artifact it can
            # contribute is a poster for the document view.
            if not md.get("live"):
                err(errors, f"slug {slug!r}: source 'live' without live flag")
            if f is not None:
                err(errors, f"slug {slug!r}: live ref carries a file {f!r}")
            if md.get("reason"):
                err(errors, f"slug {slug!r}: live ref carries a reason: "
                            f"{md.get('reason')[:80]!r}")
            if md.get("type") != "live":
                err(errors, f"slug {slug!r}: live ref type {md.get('type')!r} "
                            f"!= 'live'")
            poster = md.get("poster")
            if poster is not None:
                if not (isinstance(poster, str) and poster.startswith("_media/")):
                    err(errors, f"slug {slug!r}: live poster {poster!r} must be "
                                f"an out-root-relative _media/ path")
                else:
                    if not (fx.out / poster).is_file():
                        err(errors, f"slug {slug!r}: published poster missing "
                                    f"on disk: {poster}")
                    if not poster.split("/")[-1].startswith(slug + "-poster."):
                        err(errors, f"slug {slug!r}: published poster name "
                                    f"{poster!r} must start with "
                                    f"'{slug}-poster.'")
            continue
        if found:
            if src not in ("cards", "deckdir", "library", "standin", "pool"):
                err(errors, f"slug {slug!r}: found but source {src!r} not in "
                            f"cards/deckdir/library/standin")
            if md.get("live"):
                err(errors, f"slug {slug!r}: live flag on a file-backed ref")
            if not (isinstance(f, str) and f.startswith("_media/")):
                err(errors, f"slug {slug!r}: found media file {f!r} must be "
                            f"an out-root-relative _media/ path")
            else:
                p = fx.out / f
                if not p.is_file():
                    err(errors, f"slug {slug!r}: published file missing on "
                                f"disk: {f}")
                if not f.split("/")[-1].startswith(slug + "."):
                    err(errors, f"slug {slug!r}: published name {f!r} does "
                                f"not start with '<slug>.'")
            if md.get("reason"):
                err(errors, f"slug {slug!r}: found media carries a reason: "
                            f"{md.get('reason')[:80]!r}")
        else:
            if src != "none":
                err(errors, f"slug {slug!r}: unresolved but source "
                            f"{src!r} != 'none'")
            if f is not None:
                err(errors, f"slug {slug!r}: unresolved but file {f!r}")
            if not md.get("reason"):
                err(errors, f"slug {slug!r}: placeholder carries no reason")
            if md.get("status") not in ("missing", "brief", "to-find",
                                        "prompting", "candidate",
                                        "shortlist", "rejected"):
                err(errors, f"slug {slug!r}: placeholder status "
                            f"{md.get('status')!r} unexpected")

    # unreferenced_cards == deck cards.yaml minus referenced slugs
    cards_path = fx.deck_dir / "media" / "cards.yaml"
    card_slugs = []
    if cards_path.is_file():
        loaded = yaml.safe_load(cards_path.read_text(encoding="utf-8"))
        if loaded is None:
            loaded = []
        if not isinstance(loaded, list):
            err(errors, f"cards.yaml must be a list, got "
                        f"{type(loaded).__name__}")
            loaded = []
        card_slugs = [c.get("slug") for c in loaded
                      if isinstance(c, dict) and c.get("slug")]
    # a stepped-image card counts its frames as referenced
    used = set(slugs)
    used.update(s.rsplit("--", 1)[0] for s in slugs if "--" in s)   # a pool use counts for its pool
    for ent in man.get("referenced", []):
        used.update((ent.get("media") or {}).get("steps") or [])
    want_unref = [s for s in card_slugs if s not in used]
    got_unref = man.get("unreferenced_cards", [])
    if got_unref != want_unref:
        err(errors, f"unreferenced_cards {got_unref} != cards.yaml minus "
                    f"referenced {want_unref}")

    # no machine-local paths anywhere in the manifest
    hits = sorted({s for s in walk_strings(man) if ABS_PATH_RE.search(s)})
    if hits:
        err(errors, f"media-manifest.json leaks machine-local paths: "
                    f"{hits[:5]}")
