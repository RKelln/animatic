---
type: Talk
format-version: 1.0
content-version: 1
slug: reveal-list-title
title: "Reveal a list: the title above or below the shot"
theme: workshop
status: "construct fixture (spec: The shot directive, `reveal`; check 40) - a title written BELOW the shot comment is on the slide, so no item shows on arrival and every item needs a next-press. A heading written ABOVE the shot comment is handout-only, so the slide has no title and item 1 shows on arrival: one press fewer. Check 40 must count the marks the same way the renderer steps, so both screens are clean."
---
<!-- shot: reveal=list -->
### Title on the slide

- first
- second
- third

Three items, nothing showing yet. [n] This is the first one. [n] This is the second one. [n] This is the third one.

### Title above the shot, handout only
<!-- shot: reveal=list -->

- first
- second
- third

Item one is already up. This is the opening line. [n] This is the second one. [n] This is the third one.
