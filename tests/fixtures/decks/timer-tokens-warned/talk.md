---
type: Talk
format-version: 1.0
content-version: 1
slug: timer-tokens-warned
title: "Timer tokens, warned"
theme: workshop
test-expect: warned
status: "composite fixture (spec: Timer screens; checks 37, 38, 39) - a timer in a spoken paragraph is dropped from the voice-over and starts nothing (39); a bad, zero or typo'd duration and an unknown trailing word are left as literal text (37); a second timer on one screen is ignored (37); the `timer=` shot flag does not exist (an unknown flag, 25); a timer over 3 hours is kept (38)."
---
# Opening

<!-- shot -->
### Spoken
Take five minutes [Timer: 5:00] and write.

<!-- shot -->
### Bad value
[Timer: soon]

<!-- shot -->
### Zero
[Timer: 0:00]

<!-- shot -->
### Typo
[Timer: 8mins]

<!-- shot -->
### Unknown word
[Timer: 8m bottom]

<!-- shot -->
### Two on one screen
[Timer: 5m]

[Timer: 6m]

<!-- shot -->
### Long
[Timer: 4h]

<!-- shot -->
### Ordinary brackets
[Not a timer: just a note] and [Timers] are plain text.

<!-- shot: timer=5m -->
### The old flag is not a flag
