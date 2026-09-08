---
type: Talk
format-version: 1.0
content-version: 1
slug: nested-parens
title: "Parentheticals do not nest"
theme: workshop
status: "construct fixture (spec §5; register check 23) - the strip recognizes one level only; a nested opening paren warns so nesting never silently corrupts the spoken text."
test-expect: warned
---
<!-- shot -->

A flat parenthetical strips cleanly. (Visual: a flat stage note.)

A nested (outer (inner) tail) would corrupt the spoken text unless it warned.
