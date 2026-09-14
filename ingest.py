#!/usr/bin/env python3
"""ingest.py — file hand-dropped media into the animatic pipeline.

Drop media into a deck's inbox and this files it: matches each file to a slug,
moves it to `media/<slug>/attempts/<slug>-a<N>.<ext>` with N counting up, and
appends an ingest entry to `media/gen-log.md` with the original filename kept
for provenance. Nothing is deleted and nothing is approved: a take landing in
the pipeline is not a take being chosen (see docs/media-pipeline.md).

Why the numbering matters: the resolver checks `attempts/` and the HIGHEST N
wins, so the last file you drop is the one the built deck shows. Drop a better
take and it appears on the next build with no other edit.

Usage:
    python3 ingest.py <talk.md>                 # drain <deck>/media/_incoming/
    python3 ingest.py <talk.md> --from DIR      # drain somewhere else
    python3 ingest.py <talk.md> --dry-run       # say what would happen
    python3 ingest.py <talk.md> --no-new-cards  # refuse unknown slugs

Naming: a file may be
  * `<slug>.<ext>`                        — exact slug
  * `<slug>-anything.<ext>`               — slug is a prefix
  * `<slug>/<anything>.<ext>`             — a folder named for the slug
  * a raw fal.ai download name            — `ai_race_Yzz..._minimax-h3.mp4`
    normalises to `ai-race` (see _normalise), so re-downloads file themselves

An unknown slug is filed under its derived name and gets a minimal card
(status: candidate, prompt not on record) unless --no-new-cards.
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import shutil
import sys
from pathlib import Path

from mediaresolve import MEDIA_EXTS


def _normalise(name: str) -> str:
    """Filename (no extension) -> candidate slug.

    Strips fal.ai download decoration: trailing id tokens (mixed-case, 6+ chars)
    and the engine suffix, then kebab-cases.  `ai_race_Yzz25yd8D2kAjiTEeVy_s
    _minimax-h3` -> `ai-race`; `sealed-hammer-take2` -> `sealed-hammer-take2`.
    """
    stem = name
    for suffix in ("_minimax-h3", "-minimax-h3", "_minimax", "-minimax"):
        if stem.endswith(suffix):
            stem = stem[: -len(suffix)]
    toks = stem.split("_")
    keep = []
    for i, t in enumerate(toks):
        if i > 0 and len(t) >= 6 and re.search(r"[A-Z]", t):
            break  # an id token: everything after is decoration
        keep.append(t)
    stem = "_".join(keep) if keep else stem
    return stem.replace("_", "-").lower().strip("-.")


def _match_slug(candidate: str, slugs: list[str]) -> tuple[str | None, str]:
    """(slug, how) — exact, else longest known slug that prefixes it."""
    if candidate in slugs:
        return candidate, "exact"
    pref = [s for s in slugs if candidate.startswith(s + "-")]
    if pref:
        return max(pref, key=len), "prefix"
    return None, "unmatched"


def _next_attempt(media_dir: Path, slug: str) -> int:
    adir = media_dir / slug / "attempts"
    n = 0
    if adir.is_dir():
        for p in adir.iterdir():
            m = re.match(rf"^{re.escape(slug)}-a(\d+)\.[a-z0-9]+$", p.name)
            if m:
                n = max(n, int(m.group(1)))
    return n + 1


def _load_slugs(talk: Path) -> list[str]:
    cards = talk.parent / "media" / "cards.yaml"
    slugs: list[str] = []
    if cards.is_file():
        import yaml
        data = yaml.safe_load(cards.read_text()) or []
        slugs = [c["slug"] for c in data if isinstance(c, dict) and c.get("slug")]
    lib = talk.parent.parent / "_media" / "library.yaml"
    if lib.is_file():
        import yaml
        data = yaml.safe_load(lib.read_text()) or []
        slugs += [c["slug"] for c in data if isinstance(c, dict) and c.get("slug")]
    return slugs


def _new_card(slug: str, kind: str) -> str:
    return (
        f"\n- slug: {slug}\n"
        f"  type: {kind}\n"
        f"  status: candidate\n"
        f"  brief: |\n"
        f"    - filed by ingest.py, no card existed; prompt not on record\n"
        f"    - replace this brief: what the shot is for, and where it belongs\n"
        f"  prompts:\n"
        f"    image: \"\"\n"
        f"    video: \"\"\n"
        f"  outputs: []\n"
        f"  credit: Ryan Kelln (generated)\n"
        f"  licence: CC BY-SA\n"
        f"  alt: \"\"\n"
    )


def _collect(src: Path) -> list[Path]:
    """Files directly in src, plus files one level down in slug-named folders."""
    if not src.is_dir():
        return []
    out = []
    for p in sorted(src.rglob("*")):
        if p.is_file() and p.suffix.lower() in MEDIA_EXTS and p.name != "README.md":
            out.append(p)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("talk", type=Path, help="the deck's talk.md (locates media/)")
    ap.add_argument("--from", dest="src", type=Path, default=None,
                    help="inbox to drain (default: <deck>/media/_incoming/)")
    ap.add_argument("--dry-run", action="store_true", help="report, change nothing")
    ap.add_argument("--no-new-cards", action="store_true",
                    help="refuse slugs with no card instead of creating one")
    args = ap.parse_args(argv)

    talk = args.talk.resolve()
    if not talk.is_file():
        print(f"error: no such talkfile: {talk}", file=sys.stderr)
        return 2
    media_dir = talk.parent / "media"
    src = (args.src or (media_dir / "_incoming")).resolve()
    files = _collect(src)
    if not files:
        print(f"nothing to ingest in {src}")
        return 0

    slugs = _load_slugs(talk)
    filed, unmatched, made = [], [], []
    counters: dict[str, int] = {}
    for f in files:
        base = f.parent.name if f.parent != src else f.stem
        candidate = _normalise(base)
        slug, how = _match_slug(candidate, slugs)
        if slug is None:
            slug = candidate
            if args.no_new_cards:
                unmatched.append((f, slug))
                continue
            how = "new"
        kind = MEDIA_EXTS.get(f.suffix.lower(), "file")
        # Number incrementally: several files can target one slug in a single
        # run, and two takes must never land on the same attempt number (the
        # second move would silently destroy the first).
        if slug not in counters:
            counters[slug] = _next_attempt(media_dir, slug) - 1
        counters[slug] += 1
        n = counters[slug]
        dest = media_dir / slug / "attempts" / f"{slug}-a{n}{f.suffix.lower()}"
        filed.append((f, slug, n, dest, how, kind))
        if how == "new":
            made.append((slug, kind))
            slugs.append(slug)

    width = max((len(str(f)) for f, *_ in filed), default=10)
    for f, slug, n, dest, how, _kind in filed:
        rel = dest.relative_to(talk.parent)
        print(f"  {str(f.relative_to(src)):<{width}}  ->  {rel}   [{how}]")
    for f, slug in unmatched:
        print(f"  {str(f.relative_to(src)):<{width}}  --  left in place: no card for "
              f"'{slug}' (--no-new-cards)")

    if args.dry_run:
        print(f"\ndry run: {len(filed)} file(s) would move, {len(made)} new card(s), "
              f"{len(unmatched)} left in place")
        return 0

    for f, slug, n, dest, _how, _kind in filed:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(f), str(dest))

    cards = media_dir / "cards.yaml"
    if made:
        with cards.open("a") as fh:
            fh.write(f"\n# --- filed by ingest.py {dt.date.today().isoformat()} ---\n")
            for slug, kind in made:
                fh.write(_new_card(slug, kind))

    today = dt.date.today().isoformat()
    with (media_dir / "gen-log.md").open("a") as fh:
        fh.write(f"\n## {today} · ingest · {len(filed)} file(s)\n")
        if src != (media_dir / "_incoming"):
            fh.write(f"- source: `{src}`\n")
        fh.write("- intent: file hand-dropped media into the pipeline\n")
        fh.write("- delta: ingest, no new generation\n")
        fh.write("- verdict: not-yet-reviewed — candidates only, no take approved\n")
        for f, slug, n, _dest, how, _kind in filed:
            fh.write(f"- a{n} ← `{f.name}` (slug {slug}"
                     + (", new card" if how == "new" else "") + ")\n")

    filed_slugs = {slug for _f, slug, *_ in filed}
    print(f"\nfiled {len(filed)} file(s) into {len(filed_slugs)} slug(s); "
          f"{len(made)} new card(s); gen-log updated")
    if unmatched:
        print(f"{len(unmatched)} file(s) left in {src} (no card; see above)")
    print("rebuild the deck to see them: python3 build.py <talk.md> --out OUT")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
