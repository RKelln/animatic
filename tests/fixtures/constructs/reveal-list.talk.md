---
type: Talk
format-version: 1.0
content-version: 1
slug: reveal-list
title: "Reveal a list one item at a time"
theme: workshop
test-expect: warned
status: "construct fixture (spec: The shot directive, `reveal`) - `reveal=list` marks the first list's items for the presentation pager to show one per next-press. A title before the list means none show on arrival (data-reveal=0); a list that opens the screen shows item 1 (data-reveal=1). The document view is untouched. A reveal on a screen with no list, a one-item list, or an unknown value warns and is ignored."
---
<!-- shot: reveal=list -->
### Title first

1. one
2. two
3. three

<!-- shot: reveal=list -->
- list first
- second

<!-- shot: reveal=list -->
### No list here

<!-- shot: reveal=list -->
### One item

- only one

<!-- shot: reveal=images -->
### Unknown value

- a
- b

<!-- shot: reveal=list -->
### Sub-points reveal in order

- "Our league changes game times by email."
  - real problem
- "I am bad at keeping up with my email."
  - symptom
    - deeper still
