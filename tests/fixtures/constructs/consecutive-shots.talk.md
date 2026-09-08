---
type: Talk
format-version: 1.0
content-version: 1
slug: consecutive-shots
title: "Consecutive shots warn"
theme: workshop
status: "construct fixture (spec §3 tolerance; §10 warnings) - two shot directives with no content between warn: the second opens a new screen and the first stays an empty beat."
test-expect: warned
---
<!-- shot: cons-a -->
<!-- shot: cons-b -->

The second shot opened its own screen; the first remains an empty beat that still counts as a cue.
