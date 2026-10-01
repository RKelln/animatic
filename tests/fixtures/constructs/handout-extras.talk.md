---
type: Talk
format-version: 1.0
content-version: 1
slug: handout-extras
title: "Handout extras"
theme: workshop
test-expect: warned
status: "construct fixture (handout, 2026-09-30) - [^id] refs print as numbered links to the Sources list, `cites:` supplies the public citation, a figure naming the slug of the figure just before it prints once, and still= takes start, end, seconds or n% (anything else warns)."
sources:
  prince-2026: "Working receipt: Cloudflare CEO Matthew Prince, June 3 2026, events/L01/notes.md ~ verify"
  other-2026: "Working receipt: a second source, never printed raw"
cites:
  prince-2026: "Matthew Prince, CEO of Cloudflare, June 3 2026."
---
<!-- shot: sample-art -->
Most web traffic is bots, not people.[^prince-2026] This sentence cites nothing.

<!-- shot: sample-art still=end -->
The same picture again: the handout prints it once.

<!-- shot: continue -->
A continue shot is the same thing said another way.[^other-2026]

<!-- shot: sample-art still=start -->
#### A smaller heading

<!-- shot: sample-art still=3s -->
Valid forms: start, end, 3, 3.5s, 25%.

<!-- shot: sample-art still=banana -->
An invalid still warns and is ignored.
