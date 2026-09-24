---
type: Talk
format-version: 1.0
content-version: 1
slug: lists-and-tables
title: "Numbered lists and tables"
theme: workshop
status: "construct fixture (spec: Text) - `1.` items are an ordered list and `|` rows are a table: screen objects, never spoken. A `-` run directly after a numbered run is its own list, a delimiter row marks the header, and prose with a stray pipe or a mid-line number stays prose."
---
<!-- shot -->
### Numbered

1. one
2) two
- a bullet list after it, separate

Spoken line after the numbered list.

<!-- shot -->
### Table

| a | b |
|---|:-:|
| 1 | 2 |
| 3 |

A sentence that mentions 1. and | pipes | mid-line stays spoken.

<!-- shot -->
### Headerless

| x | y |
| z | w |
