---
type: Talk
format-version: 1.0
content-version: 1
slug: soft-wrap
title: "Soft-wrapped blocks"
theme: workshop
status: "construct fixture (parser behavior, upstream of the frozen spec) - consecutive non-blank prose lines merge into one paragraph, and consecutive quote markers / list items merge into one block. A screen's nav.json line range must cover the whole merged span, first line through last, not just the opening line: a range that stops at the block's first line leaves body lines belonging to no screen."
---

<!-- shot -->

The first paragraph of this screen is soft-wrapped across
three source lines; the merged span starts on the first of
them and the screen's range must end on the last.

The second paragraph follows, wrapped across
two more lines, and ends the screen.

<!-- shot -->

> A quote that runs
> across two source lines.

~ The specimen voice, 2026

- a list item wrapped across
- a second item on its own line

<!-- shot: black -->
