---
type: Talk
format-version: 1.0
content-version: 1
slug: card-text-warned
title: "Card text default, with a bad value"
date: 2026-10-10
venue: Internal fixture
format: Golden deck
dur: ~1 min
theme: workshop
test-expect: warned
status: "golden deck - text: on a plain (non-pool) card is the default text= for its shots; a shot's own text= wins; a bad value is ignored with a check 41 warning"
---
<!-- shot: dark-art -->
## Card says light

<!-- shot: continue -->
A continue keeps the light default.

<!-- shot: dark-art text=dark -->
## The shot says dark and wins

<!-- shot: bad-art -->
## Bad card value, ignored with a warning

<!-- shot: plain-art -->
## No card value, no flag
