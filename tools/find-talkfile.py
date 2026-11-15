#!/usr/bin/env python3
"""find-talkfile.py — which talk.md built out-<slug>? Runs on the content box.

    python3 tools/find-talkfile.py --outdir out-demo [--corpus corpus.yaml]

Maps an output folder back to the talkfile that produced it, so pull-deck.sh can
start a watch without being told where the deck lives. The rule is the one
pull-deck.sh already uses for the folder name: out- + the first dash-separated
segment of the deck's frontmatter slug, lowercased.

Reads the frontmatter with a regex, not talkparse, on purpose: discovery must not
fail because a deck is half-saved while you are watching it.

Exit: 0 and one path on stdout; 1 nothing matched; 2 more than one matched
(candidates on stderr, listed, never guessed).
"""
import argparse
import pathlib
import re
import sys


def deck_roots(corpus: pathlib.Path) -> list:
    """The `decks:` list from corpus.yaml, without a yaml dependency."""
    try:
        text = corpus.read_text(encoding="utf-8")
    except OSError:
        return []
    roots, inside = [], False
    for line in text.splitlines():
        if re.match(r"^decks:\s*$", line):
            inside = True
            continue
        if inside:
            if re.match(r"^\S", line):      # the next top-level key ends the list
                inside = False
                continue
            m = re.match(r"^\s*-\s*(\S.*?)\s*$", line)
            if m:
                roots.append(pathlib.Path(m.group(1)).expanduser())
    return roots


def slug_of(talk: pathlib.Path) -> str:
    try:
        head = talk.read_text(encoding="utf-8", errors="replace")[:4000]
    except OSError:
        return ""
    m = re.search(r"^---\n(.*?)\n---", head, re.S)
    block = m.group(1) if m else ""
    m = re.search(r"^slug:\s*['\"]?([^'\"\n]+)", block, re.M)
    return (m.group(1).strip() if m else talk.parent.name).lower()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--outdir", required=True, help="e.g. out-demo")
    ap.add_argument("--corpus", default=str(pathlib.Path(__file__).resolve().parent.parent
                                            / "corpus.yaml"))
    a = ap.parse_args(argv)
    hits = []
    for root in deck_roots(pathlib.Path(a.corpus).expanduser()):
        if not root.is_dir():
            continue
        for d in sorted(root.iterdir()):
            talks = ([d / "talk.md"] if (d / "talk.md").is_file() else []) + \
                    sorted(d.glob("*.talk.md"))
            for t in talks:
                if "out-" + slug_of(t).split("-")[0] == a.outdir:
                    hits.append(str(t))
    if len(hits) == 1:
        print(hits[0])
        return 0
    if not hits:
        print(f"no talkfile maps to {a.outdir} under the corpus roots", file=sys.stderr)
        return 1
    print(f"{a.outdir} is ambiguous, {len(hits)} talkfiles map to it:", file=sys.stderr)
    for h in hits:
        print(f"  {h}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
