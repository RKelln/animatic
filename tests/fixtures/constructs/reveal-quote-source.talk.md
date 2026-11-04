---
type: Talk
format-version: 1.0
content-version: 1
slug: reveal-quote-source
title: "reveal=quote and reveal=source step quotes and their citations"
theme: workshop
test-expect: warned
status: "construct fixture (spec: The shot directive, `reveal`) - `reveal=quote` shows two or more stacked quotes one per press, citation with its quote; `reveal=source` keeps the quote up and shows its `~` source on a press of its own; `quote+source` steps each quote then its source; a bare `reveal` steps quotes but not sources; `reveal=list` leaves quotes alone. `reveal=quote` with one quote and `reveal=source` with no `~` line warn (check 43) and do nothing."
---
<!-- shot: reveal=source -->
> A smooth I am sure is not evidence.
~ Ryan Kelln

<!-- shot: reveal=quote -->
### Stacked quotes
> one
~ a
> two
~ b

<!-- shot: reveal=quote+source -->
### Quote then source
> one
~ a
> two
~ b

<!-- shot: reveal -->
### Bare reveal
> one
~ a
> two
~ b

<!-- shot: reveal=list -->
### List part leaves quotes alone
> one
> two
- l1
- l2

<!-- shot: reveal=quote -->
### One quote only
> alone

<!-- shot: reveal=source -->
> no citation
