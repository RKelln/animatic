---
type: Talk
format-version: 1.0
content-version: 1
slug: spoken-list-warned
title: "A copy of a list that is read aloud"
theme: lecture
status: "construct fixture (spec: Text - Spoken lists; register check 42) - a `[notes]` block that repeats a list the speaker already reads aloud is redundant: the copy is read twice."
test-expect: warned
---
<!-- shot -->
### The two steps

Here is the whole thing, and I read it as we go:

- Open the file.
- Press the button.

[notes]
- Open the file.
- Press the button.
