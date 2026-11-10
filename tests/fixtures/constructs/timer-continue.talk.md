---
type: Talk
format-version: 1.0
content-version: 1
slug: timer-continue
title: "A countdown that runs across several screens"
theme: workshop
test-expect: warned
status: "construct fixture (spec: Timer screens, Continued timers) - `[timer]` with no duration shows the countdown of the nearest timer above it: same clock, never restarted. `[timer corner]` is the corner plate, `([timer])` the presenter-only one. The parent carries `data-timer-span` (its last continuation's slide index), each continuation `data-timer-from` and the cue `timer_continues`. Timing: the span lasts the countdown, the parent takes what its span does not use. A continuation with no timer above it warns (check 52) and stays as text; reveal=timer on a continuation is ignored."
---
<!-- shot -->
### A continuation before any timer stays as text

[timer]

<!-- shot: reveal=timer -->
### 3 · Build it

Tell it go.

[Timer: 25m]

<!-- shot -->
### Side talk, corner plate

[timer corner]

A short talk while the room works, a few sentences long so the span has words in it.

<!-- shot -->
### Untimed screen inside the span

No token here: it is inside the span, and draws no clock.

<!-- shot: reveal=timer -->
### Inline continuation [timer] and a reveal that is ignored

More talk while they work.

<!-- shot -->
### Presenter-only continuation

([timer])

The last screen of the span.

<!-- shot -->
### After the span

Talk after the countdown's span ends.

<!-- shot -->
### A plain timer, continued by a block

[Timer: 2m]

<!-- shot -->
### Its continuation, as a block

[timer]
