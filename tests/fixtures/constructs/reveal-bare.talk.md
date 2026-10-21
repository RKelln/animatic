---
type: Talk
format-version: 1.0
content-version: 1
slug: reveal-bare
title: "A bare reveal shows everything the slide can hide"
theme: workshop
test-expect: warned
status: "construct fixture (spec: The shot directive, `reveal`) - a bare `reveal` (no value) reveals whatever the screen can reveal, in step order: today a list's items one per press, then the `[Timer: ...]` countdown on the press after the last item (the same as `reveal=list+timer`). A screen with only a list behaves like `reveal=list`, with only a timer like `reveal=timer`. On a screen with nothing revealable it warns (check 45) and does nothing. `reveal=list`, `reveal=timer` and `reveal=list+timer` still mean exactly what they did."
---
<!-- shot: reveal -->
### List then timer

- first
- second
- third

[Timer: 90s]

<!-- shot: reveal -->
### Only a list

- one
- two

<!-- shot: reveal -->
### Only a timer

[Timer: 2:00]

<!-- shot: reveal -->
### Nothing to reveal

Just a heading and a thought.

<!-- shot: reveal -->
### One item is not a list to reveal

- only one

<!-- shot: reveal=list+timer -->
### The long way, same as bare

- first
- second
- third

[Timer: 90s]

<!-- shot: reveal=list -->
### Named list, no list: check 43 not 45

Nothing here.

<!-- shot: reveal -->
### Bare with a corner timer

- a
- b

[Timer: 45s corner]
