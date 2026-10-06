---
type: Talk
format-version: 1.0
content-version: 1
slug: code-fences
title: "Code fences"
theme: lecture
status: "composite fixture (spec: Text, fenced code) - a fenced block shows its lines verbatim on screen and is never spoken. Covers: the SOUL file under a heading with the fence on the very next line and fit=hero, the same file at the normal size, a fence holding a shot directive, headings, a list, a quote, a table, a parenthetical, a footnote marker, a comment and an em dash that must all stay literal, a longer ~~~ fence holding a ``` line, an indented opener with a longer closer, a fence straight after a paragraph and after a list, a role shot followed by a fence, and a real movement heading after a fenced fake one. Clean: no warnings."
sources:
  real: "A real source, cited outside the fence."
---
# Code fences

<!-- shot: fit=hero -->
### SOUL.md
```
You are a thoughtful, creative collaborator.
You are curious, honest, wise and fair.
A generous expert in all things who understands their own limits.

* Explore possibilities without pretending certainty
* Say when something is a bad idea
- Avoid sycophancy
- Avoid hype, marketing, diplomatic and academic language
```

This is the whole file, as the agent reads it.

<!-- shot -->
### SOUL.md, normal size

```text
You are a thoughtful, creative collaborator.
You are curious, honest, wise and fair.
A generous expert in all things who understands their own limits.

* Explore possibilities without pretending certainty
* Say when something is a bad idea
- Avoid sycophancy
- Avoid hype, marketing, diplomatic and academic language
```

Spoken once, shown once.[^real]

<!-- shot -->
### Nothing inside is parsed

```
<!-- shot: not-a-shot role=stat -->
## Movement 9 · Not a movement
# Not a heading
- not a list item
1. not a numbered one
> not a quote
| not | a table |
(not a stage note (nor a nested one))
This is not [^spoken] and not a footnote.
text <!-- not a comment --> after
    indented four spaces
	tab then text
one em dash — here, and <b>tags</b> & "quotes"
**not bold** and `not code`
<!-- include: nothing.md -->
```

Said aloud: the box above is a file, not a slide script.

<!-- shot -->
### A longer block

~~~yaml
name: soul
version: 3
rules:
  - be kind
  - be brief
```
this fence line is literal, it is shorter than the opener
notes: |
  the opener was tildes, so only a tilde line closes it
  and the closer may be longer than the opener
~~~~

<!-- shot -->
### Indented fence, longer closer

  ```
  two spaces of indent stay as written
  a longer closer (four ticks) closes it
  ````

<!-- shot -->
Before the fence is a paragraph.
```
the fence interrupts the paragraph run
```
- a list
```
and the fence interrupts the list
```
After it, more spoken words.

<!-- shot: role=stat -->
```
a role shot keeps its normal behaviour: the fence is still drawn
```
57.5% of web traffic is bots.

## Movement 1 · After the fence

<!-- shot -->
### Real structure resumes

A real movement closes the screen, and the one inside the fence did not.
