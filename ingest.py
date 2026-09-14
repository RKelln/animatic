#!/usr/bin/env python3
"""ingest.py — file hand-dropped media into the animatic pipeline from fal's record.

Drop media into a deck's inbox and this files it. The point is that it does NOT
depend on how the files were named: every fal clip carries its own request id in
a C2PA manifest, so the tool reads the generation record back (see `falrec.py`)
and uses the ORIGINAL prompt to decide where the clip belongs.

Matching, strongest evidence first:
  1. slug / alias / prefix   — the card declares `aliases:` for freehand names
  2. prompt family           — the recovered prompt matches an existing card's
                               prompt (Jaccard >= --match-threshold, and clearly
                               ahead of the runner-up)
  3. new slug                — named from the filename, flagged for review

It then writes the card for a new slug (prompt and a first-draft alt from fal's
own description), fills an empty prompt on an existing card, and appends the
generation record to `media/gen-log.md`. Highest attempt number wins in the
resolver, so the last file dropped is what the deck shows.

Usage:
    python3 ingest.py <talk.md>                 # drain <deck>/media/_incoming/
    python3 ingest.py <talk.md> --from DIR
    python3 ingest.py <talk.md> --dry-run       # say what would happen
    python3 ingest.py <talk.md> --no-recover    # name-match only, no fal calls
    python3 ingest.py <talk.md> --no-new-cards  # refuse unknown slugs

Naming, when you do name things: `slug.mp4`, `slug-anything.mp4`,
`slug/anything.mp4`, or a raw fal download name (which normalises).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import shutil
import sys
from pathlib import Path

import falrec
from mediaresolve import MEDIA_EXTS

MATCH_THRESHOLD = 0.45    # measured: real prompt families score ~1.0, spurious <= 0.33
MATCH_MARGIN = 1.35       # best must also clearly beat the runner-up, or it is ambiguous


def _normalise(name: str) -> str:
    """Filename (no extension) -> candidate slug."""
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


def _tokens(s: str) -> set[str]:
    return {w for w in re.sub(r"[^a-z0-9 ]", " ", s.lower()).split() if len(w) > 2}


def _jac(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    return len(ta & tb) / len(ta | tb) if ta and tb else 0.0


def _match_slug(candidate: str, slugs: list[str],
                aliases: dict[str, str] | None = None) -> tuple[str | None, str]:
    """(slug, how) — alias, then exact, then longest known slug that prefixes it."""
    aliases = aliases or {}
    if candidate in aliases:
        return aliases[candidate], "alias"
    for a, s in aliases.items():
        if candidate.startswith(a + "-"):
            return s, "alias-prefix"
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


def _prompt_family(media_dir: Path, cards: dict) -> dict[str, list[str]]:
    """slug -> every prompt known for it (cards + already-recovered takes)."""
    fam: dict[str, list[str]] = {}
    for slug, card in cards.items():
        p = (card.get("prompts") or {}).get("video") if isinstance(card, dict) else None
        if isinstance(p, str) and p.strip():
            fam.setdefault(slug, []).append(p)
    for f in media_dir.glob("*/attempts/*.fal.json"):
        slug = f.parent.parent.name
        try:
            p = falrec.prompt_of(json.loads(f.read_text()))
        except Exception:                                            # noqa: BLE001
            p = ""
        if p:
            fam.setdefault(slug, []).append(p)
    return {k: v for k, v in fam.items() if v}


def _match_prompt(prompt: str, fam: dict[str, list[str]],
                  threshold: float) -> tuple[str | None, float, str | None, float, str]:
    """(slug, score, runner_up_slug, runner_up_score, verdict)."""
    scores = sorted(((max(_jac(prompt, p) for p in ps), s) for s, ps in fam.items()),
                    reverse=True)
    if not scores:
        return None, 0.0, None, 0.0, "empty"
    best, runner = scores[0], (scores[1] if len(scores) > 1 else (0.0, None))
    if best[0] < threshold:
        return None, best[0], runner[1], runner[0], "below-threshold"
    if runner[0] and best[0] < runner[0] * MATCH_MARGIN:
        return None, best[0], runner[1], runner[0], "ambiguous"
    return best[1], best[0], runner[1], runner[0], "prompt"


def _load_cards(talk: Path) -> tuple[list[str], dict[str, str], dict]:
    cards_path = talk.parent / "media" / "cards.yaml"
    slugs: list[str] = []
    aliases: dict[str, str] = {}
    cards: dict = {}
    for src in (cards_path, talk.parent.parent / "_media" / "library.yaml"):
        if not src.is_file():
            continue
        import yaml
        for c in yaml.safe_load(src.read_text()) or []:
            if not (isinstance(c, dict) and c.get("slug")):
                continue
            slugs.append(c["slug"])
            cards[c["slug"]] = c
            al = c.get("aliases")
            if isinstance(al, str):
                al = [al]
            for a in al or []:
                if isinstance(a, str) and a.strip():
                    aliases[_normalise(a)] = c["slug"]
    return slugs, aliases, cards


def _card_block(slug: str, kind: str, prompt: str, alt: str, meta: dict,
                brief_extra: list[str]) -> str:
    def q(s: str) -> str:
        return s.replace("\\", "\\\\").replace('"', '\\"')
    lines = [f"\n- slug: {slug}", f"  type: {kind}", "  status: candidate", "  brief: |"]
    lines += [f"    {b}" for b in brief_extra]
    lines += [f"    fal: {meta.get('endpoint')} · {meta.get('duration')}s · "
              f"{meta.get('resolution')} · expansion {meta.get('expansion')}",
              f"    request {meta.get('request_id')} · queued {meta.get('queued_at')}"]
    lines += ["  prompts:", '    image: ""', f'    video: "{q(prompt)}"',
              "  outputs: []", "  credit: Ryan Kelln (generated)", "  licence: CC BY-SA",
              f'  alt: "{q(alt)}"']
    return "\n".join(lines) + "\n"


def _fill_card(cards_path: Path, slug: str, prompt: str, alt: str) -> list[str]:
    """Fill an EMPTY prompt/alt on an existing card. Never overwrites."""
    body = cards_path.read_text()
    pat = re.compile(rf"(?ms)^- slug: {re.escape(slug)}\n(.*?)(?=^- slug: |\Z)")
    m = pat.search(body)
    if not m:
        return []
    block, notes = m.group(0), []
    new_block = block
    if prompt and re.search(r'(?m)^    video: ""\s*$', new_block):
        new_block = re.sub(r'(?m)^    video: ""\s*$',
                           '    video: "' + prompt.replace("\\", "\\\\").replace('"', '\\"') + '"',
                           new_block, count=1)
        notes.append("prompt filled from fal")
    elif prompt:
        have = re.search(r'(?m)^    video: "(.*)"\s*$', new_block)
        if have and falrec.prompt_of({"json_input": {"prompt": have.group(1)}}) and \
           _jac(have.group(1), prompt) < 0.9:
            notes.append("prompt on card differs from what fal ran (left alone)")
    if alt and re.search(r'(?m)^  alt: ""\s*$', new_block):
        new_block = re.sub(r'(?m)^  alt: ""\s*$',
                           '  alt: "' + alt.replace("\\", "\\\\").replace('"', '\\"') + '"',
                           new_block, count=1)
        notes.append("alt drafted from fal description")
    if new_block != block:
        cards_path.write_text(body.replace(block, new_block, 1))
    return notes


def _collect(src: Path) -> list[Path]:
    if not src.is_dir():
        return []
    return [p for p in sorted(src.rglob("*"))
            if p.is_file() and p.suffix.lower() in MEDIA_EXTS and p.name != "README.md"]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("talk", type=Path, help="the deck's talk.md (locates media/)")
    ap.add_argument("--from", dest="src", type=Path, default=None)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-recover", action="store_true",
                    help="skip the fal record read (name matching only)")
    ap.add_argument("--no-new-cards", action="store_true")
    ap.add_argument("--match-threshold", type=float, default=MATCH_THRESHOLD)
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

    slugs, aliases, cards = _load_cards(talk)
    fam = _prompt_family(media_dir, cards)
    key = None
    if not args.no_recover:
        try:
            key = falrec.load_key()
        except falrec.NoRecord as e:
            print(f"warning: {e}; continuing with name matching only", file=sys.stderr)

    # ---- pass 1: read each clip's record while it is still in the inbox
    found: dict[Path, dict | None] = {}
    for f in files:
        if args.no_recover:
            found[f] = None
            continue
        try:
            found[f] = falrec.recover(f, key)
        except falrec.NoRecord:
            found[f] = None
        except Exception as e:                                       # noqa: BLE001
            print(f"  {f.name}: fal lookup failed ({type(e).__name__}: {e})")
            found[f] = None

    # ---- pass 2: decide the slug, strongest evidence first
    planned, counters, notes = [], {}, []
    for f in files:
        rec = found.get(f)
        prompt = falrec.prompt_of(rec)
        base = f.parent.name if f.parent != src else f.stem
        slug, how = _match_slug(_normalise(base), slugs, aliases)
        why = ""
        if slug is None and prompt and fam:
            slug, score, runner, rscore, verdict = _match_prompt(prompt, fam, args.match_threshold)
            if slug:
                how, why = "prompt", f"prompt {score:.2f} vs {runner} {rscore:.2f}"
            else:
                notes.append(f"  {f.name}: no name match; prompt verdict {verdict} "
                             f"({score:.2f} vs {runner} {rscore:.2f})")
        if slug is None:
            slug = _normalise(base)
            if args.no_new_cards:
                notes.append(f"  {f.name}: no card for '{slug}' (--no-new-cards), left in place")
                continue
            how, why = "new", "name-derived, needs review"
            cards.setdefault(slug, {})
            slugs.append(slug)
            # Takes of one shot dropped together should land together: seed the
            # family with this clip's prompt so later files in the batch match it
            # (this is how five takes of a brand-new gag become one slug).
            if prompt:
                fam[slug] = [prompt]
        kind = MEDIA_EXTS.get(f.suffix.lower(), "file")
        if slug not in counters:
            counters[slug] = _next_attempt(media_dir, slug) - 1
        counters[slug] += 1
        n = counters[slug]
        dest = media_dir / slug / "attempts" / f"{slug}-a{n}{f.suffix.lower()}"
        planned.append({"src": f, "slug": slug, "n": n, "dest": dest, "how": how,
                        "why": why, "rec": rec, "prompt": prompt, "kind": kind})

    width = max((len(p["src"].name) for p in planned), default=10)
    for p in planned:
        rel = p["dest"].relative_to(talk.parent)
        tag = f"{p['how']}" + (f" ({p['why']})" if p["why"] else "")
        print(f"  {p['src'].name:<{width}}  ->  {rel}   [{tag}]")
    for n in notes:
        print(n)
    if args.dry_run:
        print(f"\ndry run: {len(planned)} file(s) would move, "
              f"{sum(1 for p in planned if p['how'] == 'new')} new card(s)")
        return 0

    # ---- pass 3: move the clip and its sidecars
    for p in planned:
        p["dest"].parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(p["src"]), str(p["dest"]))
        for suf in (falrec.SIDECAR, falrec.EXPANDED):
            old = p["src"].with_suffix(suf)
            if old.is_file():
                shutil.move(str(old), str(p["dest"].with_suffix(suf)))

    # ---- pass 4: cards and the log
    cards_path = media_dir / "cards.yaml"
    created, filled = [], []
    for p in planned:
        slug, rec = p["slug"], p["rec"]
        alt = falrec.alt_from_expanded(rec) if rec else ""
        if p["how"] == "new" and not (cards_path.read_text().count(f"- slug: {slug}\n")):
            brief = [f"filed by ingest.py {dt.date.today().isoformat()}; name derived from "
                     f"'{p['src'].name}'" + (" and needs review" if p["how"] == "new" else "")]
            if rec:
                brief.append("prompt recovered from fal; rename the slug to say what the shot is")
            cards_path.open("a").write(_card_block(slug, p["kind"], p["prompt"], alt,
                                                   falrec.summary(rec), brief))
            created.append(slug)
        else:
            got = _fill_card(cards_path, slug, p["prompt"], alt)
            if got:
                filled.append((slug, ", ".join(got)))

    today = dt.date.today().isoformat()
    with (media_dir / "gen-log.md").open("a") as fh:
        fh.write(f"\n## {today} · ingest · {len(planned)} file(s)\n")
        if src != media_dir / "_incoming":
            fh.write(f"- source: `{src}`\n")
        fh.write("- intent: file hand-dropped media and author the card from fal's record\n")
        fh.write("- delta: ingest, no new generation\n")
        fh.write("- verdict: not-yet-reviewed — candidates only, no take approved\n")
        for p in planned:
            m = falrec.summary(p["rec"])
            fh.write(f"- a{p['n']} ← `{p['src'].name}` (slug {p['slug']}, matched by {p['how']})\n")
            if p["prompt"]:
                fh.write(f"  - prompt: {' '.join(p['prompt'].split())}\n")
            if p["rec"]:
                fh.write(f"  - fal: {m['endpoint']} · {m['duration']}s · {m['resolution']} · "
                         f"expansion {m['expansion']} · request {m['request_id']}\n")

    print(f"\nfiled {len(planned)} file(s) into {len({p['slug'] for p in planned})} slug(s); "
          f"{len(created)} new card(s); {len(filled)} card(s) filled; gen-log updated")
    for slug, what in filled:
        print(f"  filled {slug}: {what}")
    print("rebuild the deck to see them: python3 build.py <talk.md> --out OUT")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
