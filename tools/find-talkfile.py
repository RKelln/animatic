#!/usr/bin/env python3
"""find-talkfile.py — which talkfile built out-<slug>? Runs on the content box.

    python3 tools/find-talkfile.py --outdir out-demo [--corpus corpus.yaml]

Answers the reverse of the build: given an output folder, the talkfile that
produced it. pull-deck.sh uses it to start a watch without being told where the
deck lives.

It is a READER of the CLI's identity table, not a second copy of it: `animatic
decks` owns the rule ("out- + the first dash-separated segment of the frontmatter
slug, lowercased") and the corpus question, so this asks it instead of parsing
corpus.yaml and the frontmatter again.  That duplicate is what went stale when
corpus.yaml stopped naming the decks.

Exit: 0 and one path on stdout; 1 nothing matched; 2 more than one matched
(candidates on stderr, listed, never guessed).
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import cli  # noqa: E402  (the identity table)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Which talkfile built an out-* folder (reads `animatic "
                    "decks`).")
    ap.add_argument("--outdir", required=True, help="e.g. out-demo")
    ap.add_argument("--corpus", default=None, metavar="PATH",
                    help="a corpus file other than the repo's corpus.yaml")
    a = ap.parse_args(argv)

    hits = [r["talkfile"] for r in cli.deck_rows(corpus=a.corpus)
            if r["outdir"] == a.outdir]
    if len(hits) == 1:
        print(hits[0])
        return 0
    if not hits:
        print(f"no talkfile maps to {a.outdir} under the corpus roots",
              file=sys.stderr)
        return 1
    print(f"{a.outdir} is ambiguous, {len(hits)} talkfiles map to it:",
          file=sys.stderr)
    for h in hits:
        print(f"  {h}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
