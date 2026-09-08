---
slug: multiline-shot
title: "Multi-line shot directive"
date: 2026-09-08
venue: Internal construct fixture
format: Construct fixture
dur: ~1 min
theme: workshop
status: construct fixture (spec §3, check 27) — a shot directive MAY span multiple lines; interior whitespace is insignificant. A lexer rewrite that drops wrapped directives breaks this deck's build.
---

<!-- construct fixture, check 27: every shot directive below is wrapped across
     lines. Each wrapped directive must parse exactly as its single-line twin;
     only the whitespace between tokens crossed lines, never a token itself. -->

<!-- shot:
    stat -->
57 percent of fixtures fit on one line anyway.

<!-- shot:
    fit=hero
    text=light -->
## Two words

Flag-only directives wrap the same way: the first token on its own line, the rest below. This hero card crossed three lines.

<!-- shot: fit=cover
    text=light -->
## End of fixture

Every token stayed whole. A future lexer that reads comments line by line instead of accumulating them would drop this deck's screens.
