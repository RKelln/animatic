---
type: Talk
format-version: 1.0
content-version: 1
slug: attribution-fallthrough
title: "Attribution shapes warn"
theme: workshop
status: "construct fixture (spec §4 attribution; register check 24) - attribution is tilde on its own paragraph directly under the quote; an attribution-shaped line anywhere else is spoken, with a warning."
test-expect: warned
---
<!-- shot -->
> A real quote with a real source.
~ The specimen voice, 2026

~ A lone tilde with no quote above it.

Source: the deleted shape, 2026

Both stray shapes above are spoken, tilde and all, because the warning is the migration path.
