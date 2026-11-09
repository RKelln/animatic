---
type: Talk
format-version: 1.0
content-version: 1
slug: reveal-timer
title: "Reveal a timer on the next press"
theme: workshop
test-expect: warned
status: "construct fixture (spec: Timer screens, Revealed timers) - `reveal=timer` hides the screen's `[Timer: ...]` countdown until the next press, which shows it and starts it. The cue carries `timer_reveal: true`. It combines with `reveal=list` (the timer is the last step). A screen with no valid timer, or a repeated or unknown value, warns and is ignored. A plain timer without the flag still starts on arrival."
---
<!-- shot: reveal=timer -->
### Type the three lines

Read the directions out loud first.

[Timer: 9:00]

<!-- shot: reveal=timer -->
### Corner timer

[Timer: 2:00 corner]

<!-- shot: reveal=list+timer -->
### List then timer

- first
- second
- third

[Timer: 90s]

<!-- shot -->
### A plain timer starts on arrival

[Timer: 1:00]

<!-- shot: reveal=timer -->
### No timer on this screen

Nothing here counts.

<!-- shot: reveal=timer -->
### A bad timer

[Timer: 0:00]

<!-- shot: reveal=timer+timer -->
### Repeated value

[Timer: 3:00]

<!-- shot: reveal=timer+list -->
### Order does not matter

- a
- b

[Timer: 45s]

<!-- shot: reveal=timer -->
### Already has a next cue

Read the directions first. [next] Then the timer runs.

[Timer: 4:00]
