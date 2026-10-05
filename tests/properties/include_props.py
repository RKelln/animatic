"""`<!-- include: path [live] -->` (spec: Includes).

A throwaway deck under /tmp, because includes are about files next to files.

- an included file's screens land where the directive stands, and the cues
  match the same talk written inline;
- `live` on the directive marks every screen inside as live-only, and a
  `continue` shot after the include does not inherit it;
- nav.json says which include a screen came from, and every screen from an
  included file points at the directive's line;
- nested includes work; a cycle, a missing file, an absolute path, an unknown
  flag, nesting past the limit and a Movement heading are fatal, with a line;
- an included file's frontmatter `cites:` / `sources:` join the talk's, the
  talk winning.
"""
from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import talkparse  # noqa: E402

HEAD = """---
type: Talk
format-version: 1.0
content-version: 1
slug: inc-props
title: "Include props"
theme: workshop
cites:
  a: "Talk's own citation"
---
"""
SECTION = """---
cites:
  a: "Fragment tries to override"
  b: "Fragment citation"
---
<!-- shot -->
### Section slide

Section voice.

<!-- shot -->
### Second section slide
"""


def _talk(deck: Path, body: str):
    (deck / "talk.md").write_text(HEAD + body, encoding="utf-8")
    return talkparse.build_talk(deck / "talk.md")


def _fatal(deck: Path, body: str, want: str, errors: list, label: str) -> None:
    try:
        _talk(deck, body)
    except ValueError as exc:
        msg = str(exc)
        if "check 22" not in msg or want not in msg:
            errors.append(f"{label}: wrong error {msg!r} (wanted {want!r})")
        return
    errors.append(f"{label}: no error raised")


def check(errors: list) -> None:
    tmp = Path(tempfile.mkdtemp(prefix="animatic-include-"))
    try:
        deck = tmp / "deck"
        (deck / "sections").mkdir(parents=True)
        (deck / "sections" / "s.section.md").write_text(SECTION, encoding="utf-8")
        (deck / "sections" / "outer.section.md").write_text(
            "<!-- include: s.section.md -->\n", encoding="utf-8")

        # same talk, inline vs included
        body_inc = ("<!-- shot -->\n# Open\n\nHello.\n\n"
                    "<!-- include: sections/s.section.md -->\n\n"
                    "<!-- shot -->\n\nAfter.\n")
        body_inl = ("<!-- shot -->\n# Open\n\nHello.\n\n"
                    "<!-- shot -->\n### Section slide\n\nSection voice.\n\n"
                    "<!-- shot -->\n### Second section slide\n\n"
                    "<!-- shot -->\n\nAfter.\n")
        t_inc = _talk(deck, body_inc)
        t_inl = _talk(deck, body_inl)
        sig = lambda t: [(s.movement, [b.kind for b in s.blocks],
                          [b.text for b in s.blocks if hasattr(b, "text")])
                         for s in t.screens]
        if sig(t_inc) != sig(t_inl):
            errors.append("include: screens differ from the same talk written inline")
        if len(t_inc.screens) != 4:
            errors.append(f"include: expected 4 screens, got {len(t_inc.screens)}")
        inc_line = body_inc.split("\n").index("<!-- include: sections/s.section.md -->") + 1 \
            + len(HEAD.split("\n")) - 1
        for s in t_inc.screens[1:3]:
            if s.include != "sections/s.section.md":
                errors.append(f"include: screen {s.idx} include {s.include!r}")
            if s.line_range[0] != inc_line or s.line_range[1] != inc_line:
                errors.append(f"include: screen {s.idx} range {s.line_range} "
                              f"!= directive line {inc_line}")
        if t_inc.screens[0].include or t_inc.screens[3].include:
            errors.append("include: a screen outside the include carries one")
        if t_inc.meta["cites"] != {"a": "Talk's own citation", "b": "Fragment citation"}:
            errors.append(f"include: cites merge wrong: {t_inc.meta['cites']!r}")
        if [p.name for p in t_inc.includes] != ["s.section.md"]:
            errors.append(f"include: talk.includes {t_inc.includes!r}")

        # live modifier, and `continue` after it
        t_live = _talk(deck, "<!-- shot: bg -->\n\nOne.\n\n"
                             "<!-- include: sections/s.section.md live -->\n\n"
                             "<!-- shot: continue -->\n\nThree.\n")
        flags = [s.live_only for s in t_live.screens]
        if flags != [False, True, True, False]:
            errors.append(f"include live: live_only per screen {flags}")

        # nested
        t_nest = _talk(deck, "<!-- include: sections/outer.section.md -->\n")
        if len(t_nest.screens) != 2 or t_nest.screens[0].include != "sections/outer.section.md":
            errors.append("include: nested include did not splice")

        # fatals
        (deck / "sections" / "cyc.section.md").write_text(
            "<!-- include: cyc.section.md -->\n", encoding="utf-8")
        (deck / "sections" / "mv.section.md").write_text(
            "## Movement 1 · Nope\n", encoding="utf-8")
        for n in range(1, 6):
            (deck / "sections" / f"d{n}.section.md").write_text(
                f"<!-- include: d{n + 1}.section.md -->\n", encoding="utf-8")
        (deck / "sections" / "d6.section.md").write_text("x\n", encoding="utf-8")
        _fatal(deck, "<!-- include: sections/none.section.md -->\n",
               "not found", errors, "missing")
        _fatal(deck, "<!-- include: sections/cyc.section.md -->\n",
               "cycle", errors, "cycle")
        _fatal(deck, "<!-- include: /etc/hostname -->\n",
               "relative", errors, "absolute")
        _fatal(deck, "<!-- include: sections/s.section.md loud -->\n",
               "unknown", errors, "flag")
        _fatal(deck, "<!-- include: sections/mv.section.md -->\n",
               "Movement", errors, "movement")
        _fatal(deck, "<!-- include: sections/d1.section.md -->\n",
               "deeper", errors, "depth")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
