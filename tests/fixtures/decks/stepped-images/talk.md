---
type: Talk
format-version: 1.0
content-version: 1
slug: stepped-images
title: "Stepped images"
theme: workshop
status: "composite fixture (spec: Media, stepped images; The shot directive, `reveal`) - a card with `steps:` steps through its frames one per next-press in the present view and prints ONE image (the handout one) in the document view. Covers: the default handout (last frame), handout first / integer / named / the card's own image, a stepped card with a reveal=list list of the SAME length (lockstep, list opening the screen and list after a title), a list with no reveal flag (images step, list shows whole), reveal=off, and a continue screen. Clean: no warnings."
---
# Opening

<!-- shot: build-up -->
### Default handout

The diagram builds in three steps.

<!-- shot: build-first -->
Handout first.

<!-- shot: build-two -->
Handout by number.

<!-- shot: build-named -->
Handout by slug.

<!-- shot: build-own -->
The card's own image prints.

<!-- shot: build-up reveal=list -->
- one
- two
- three

<!-- shot: build-up reveal=list -->
### Title first

- one
- two
- three

<!-- shot: build-up -->
### No reveal flag

- shown whole
- while the images step

<!-- shot: build-up reveal=off -->
### Stepping off

Shows only the handout image.

<!-- shot: build-up reveal=list+off -->
### List only

- one
- two

<!-- shot: build-up -->
### Before a continue

<!-- shot: continue -->
### After a continue
