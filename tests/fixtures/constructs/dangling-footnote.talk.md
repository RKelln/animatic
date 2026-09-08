---
type: Talk
format-version: 1.0
content-version: 1
slug: dangling-footnote
title: "Dangling footnote warns"
theme: workshop
status: "construct fixture (spec §5 receipts; register check 28) - a footnote reference with no sources registry entry is stripped and collected but never emitted, and the deck warns."
test-expect: warned
sources:
  real-one: "A real source, 2026"
---
<!-- shot -->

A cited claim.[^real-one]

A ghost claim.[^ghost]

The ghost reference warns; only the real one reaches the citation list.
