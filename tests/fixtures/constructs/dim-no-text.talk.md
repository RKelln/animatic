---
type: Talk
format-version: 1.0
content-version: 1
slug: dim-no-text
title: "Dim without text warns"
theme: workshop
status: "construct fixture (register check 30) - dim keeps on-screen text readable over a picture; on a screen with only voice-over it just darkens the picture, so the deck warns. The second screen carries a heading, so its dim is quiet."
test-expect: warned
---
<!-- shot: sample-art dim=0.5 -->
Only voice-over here, so nothing on screen needs the scrim.

<!-- shot: sample-art dim=0.5 -->
### A heading over the picture

This screen has on-screen text, so its dim is doing its job.
