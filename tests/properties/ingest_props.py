"""ingest.py slug matching (name matching only, never fal).

Builds a throwaway deck under /tmp, drops files into its inbox and runs
`ingest.py --no-recover`, because the behaviour is where files land and which
cards get written.

- a card's exact slug and `slug-anything` still land on that card, and a
  card still wins over a shot-named slug that also prefixes the name;
- a slug that a shot in talk.md names, with no card yet, now catches its own
  names: an underscored suffix (`workspace-theatre_by_gpt.png`) and a raw fal
  download name (`tool_collaborator_<id>_minimax-h3.mp4`) (2026-09-29; both
  used to be filed under a new slug with the suffix glued on);
- that card is written once, under the shot's slug, with no "needs review"
  and no rename hint, even when two takes arrive in one batch;
- a name nothing knows is still filed under its own new slug for review;
- `continue` and role shots name no slug, so they catch nothing.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

TALK = """---
type: Talk
format-version: 1.0
content-version: 1
slug: ingest-props
title: "Ingest props"
theme: workshop
status: "property deck (ingest name matching)"
---
<!-- shot: carded -->
A screen whose slug has a card.

<!-- shot: carded-extra -->
A shot-named slug that the card's slug also prefixes.

<!-- shot: continue -->
A continue screen.

<!-- shot: role=stat -->
3 of 4

<!-- shot: workspace-theatre -->
A shot with no card yet.

<!-- shot: tool-collaborator -->
Another shot with no card yet.
"""

CARDS = """- slug: carded
  type: image
  status: candidate
  brief: |
    exists before ingest
  prompts:
    image: ""
    video: ""
  outputs: []
  alt: ""
"""

DROPS = {
    "carded.png": "carded",
    "carded-take2.png": "carded",
    "carded-extra-thing.png": "carded",
    "workspace-theatre_by_gpt.png": "workspace-theatre",
    "workspace-theatre-take2.png": "workspace-theatre",
    "tool_collaborator_wU_onjWgywnc03mUhbxbH_minimax-h3.mp4": "tool-collaborator",
    "mystery_thing.png": "mystery-thing",
    "continue.png": "continue",
}


def check(errors: list) -> None:
    tmp = Path(tempfile.mkdtemp(prefix="animatic-ingest-"))
    try:
        deck = tmp / "deck"
        inbox = deck / "media" / "_incoming"
        inbox.mkdir(parents=True)
        (deck / "talk.md").write_text(TALK, encoding="utf-8")
        (deck / "media" / "cards.yaml").write_text(CARDS, encoding="utf-8")
        for name in DROPS:
            (inbox / name).write_bytes(b"not really media")
        r = subprocess.run([sys.executable, str(ROOT / "ingest.py"), str(deck / "talk.md"),
                            "--no-recover"], capture_output=True, text=True, timeout=120,
                           cwd=ROOT)
        if r.returncode != 0:
            errors.append(f"ingest exited {r.returncode}: {r.stderr.strip()[-300:]}")
            return
        log = (deck / "media" / "gen-log.md").read_text(encoding="utf-8")
        for name, slug in DROPS.items():
            line = next((ln for ln in log.splitlines() if f"`{name}`" in ln), "")
            if f"(slug {slug}," not in line:
                errors.append(f"{name}: expected slug {slug}, log says {line.strip()!r}")
        cards = (deck / "media" / "cards.yaml").read_text(encoding="utf-8")
        for slug in ("workspace-theatre", "tool-collaborator"):
            n = cards.count(f"- slug: {slug}\n")
            if n != 1:
                errors.append(f"card {slug}: written {n} times, expected once")
        if cards.count("- slug: carded\n") != 1:
            errors.append("card carded: duplicated")
        if "- slug: carded-extra\n" in cards:
            errors.append("carded-extra: the card's prefix should have won over the shot")
        for slug in ("workspace-theatre", "tool-collaborator"):
            block = cards.split(f"- slug: {slug}\n", 1)[-1].split("\n- slug:", 1)[0]
            if "matched to its shot in talk.md" not in block:
                errors.append(f"card {slug}: brief does not say it matched a shot")
            if "needs review" in block or "rename the slug" in block:
                errors.append(f"card {slug}: shot-matched card asks for review/rename")
        block = cards.split("- slug: mystery-thing\n", 1)[-1].split("\n- slug:", 1)[0]
        if "needs review" not in block:
            errors.append("card mystery-thing: a new slug no longer says it needs review")
        for bad in ("workspace-theatre-by-gpt", "tool-collaborator-wu"):
            if (deck / "media" / bad).exists():
                errors.append(f"{bad}: filed under the glued-suffix slug")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
