---
type: Talk
format-version: 1.0
content-version: 1
slug: stepped-images-warned
title: "Stepped images, warned"
theme: workshop
test-expect: warned
status: "composite fixture (spec: Media, stepped images; checks 33 and 34) - a stepped card and a reveal=list list of different lengths (check 34: they advance together, the shorter holds), and cards whose steps cannot apply (check 33: one step, a video step, an unresolved step, a handout naming no step, a handout out of range). A bad card renders as one plain image."
---
# Opening

<!-- shot: two-lists reveal=list -->
### More items than frames

- one
- two
- three
- four

<!-- shot: two-lists reveal=list -->
- fewer items than frames
- two

<!-- shot: one-step -->
One step.

<!-- shot: video-step -->
A video step.

<!-- shot: missing-step -->
A missing step.

<!-- shot: bad-handout-name -->
Handout names no step.

<!-- shot: bad-handout-range -->
Handout out of range.
