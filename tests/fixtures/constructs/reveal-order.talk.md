---
type: Talk
format-version: 1.0
content-version: 1
slug: reveal-order
title: "Reveal steps follow the order things are written"
theme: workshop
status: "construct fixture (spec: The shot directive, `reveal`; Timer screens, Revealed timers) - reveal steps follow document order. A `[Timer: ...]` written above the revealed list is the first step (the press shows it and starts it, with no list item showing), then the items follow one per press; written below the list it is the last step. A corner timer has no visual position, so where its line is written decides. A timer inside the list's own items counts as after the list. `reveal=list+timer` and a bare `reveal` are the same thing. Cues carry `timer_reveal_first: true` when the timer comes first."
---
<!-- shot: reveal -->
### Timer above the list

[Timer: 9:00]

- first
- second
- third

<!-- shot: reveal=list+timer -->
### The long way, timer above

[Timer: 9:00]

- first
- second
- third

<!-- shot: reveal -->
### Corner timer written above

[Timer: 2:00 corner]

- a
- b

<!-- shot: reveal -->
### Back in [Timer: 1:00]

- x
- y

<!-- shot: reveal -->
### Timer below the list

- one
- two

[Timer: 90s]

<!-- shot: reveal -->
### Timer inside the list

- one
- two [Timer: 30s]

<!-- shot: reveal=timer -->
### Timer only, list not revealed

[Timer: 45s]

- plain
- bullets

<!-- shot: reveal -->
[Timer: 2:00 corner]

- a
- b

<!-- shot: reveal -->
- a
- b

[Timer: 2:00 corner]
