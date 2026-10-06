---
type: Talk
format-version: 1.0
content-version: 1
slug: code-fences-wrap
title: "Code fences, wrapping"
theme: lecture
status: "composite fixture (spec: Text, fenced code, Fitting) - width never shrinks a fenced block: long lines wrap, under a hanging indent for a list marker or leading space, and only height sets the size. Covers: four bullets, one long, under fit=hero with a reveal=list that has no list to step (printed, ignored); a 400-character single line; 18 short lines (shrinks to fit) and 25 (past the 75% floor: clipped and marked), the 25 also under fit=hero; and every hanging-indent shape. Clean: no warnings."
---
# Code fences, wrapping

<!-- shot: reveal=list fit=hero -->
### What's on the page

```
- Ryan: plans-first. Fresh independent takes valued.
- Ryan shares ideas as context, not tasks: engage first, don't produce until asked.
- TPL copy: grade 6, no em-dashes.
- Research briefs: holistic not hype, ~ vs ✓; continuation: primary→thread→investigation→counter-claims.
```

Four bullets, one long, as large as the slide allows.

<!-- shot -->
### One very long line

```
A single very long line with no markers that just keeps going and going so that it must wrap many times on the slide A single very long line with no markers that just keeps going and going so that it must wrap many times on the slide A single very long line with no markers that just keeps going and going so that it must wrap many times on the slide A single very long line with no markers that just
```

<!-- shot -->
### Tall, shrinks to fit

```
row 01
row 02
row 03
row 04
row 05
row 06
row 07
row 08
row 09
row 10
row 11
row 12
row 13
row 14
row 15
row 16
row 17
row 18
```

<!-- shot -->
### Tall, past the floor

```
row 01
row 02
row 03
row 04
row 05
row 06
row 07
row 08
row 09
row 10
row 11
row 12
row 13
row 14
row 15
row 16
row 17
row 18
row 19
row 20
row 21
row 22
row 23
row 24
row 25
```

<!-- shot: fit=hero -->
### Tall, hero, past the floor

```
row 01
row 02
row 03
row 04
row 05
row 06
row 07
row 08
row 09
row 10
row 11
row 12
row 13
row 14
row 15
row 16
row 17
row 18
row 19
row 20
row 21
row 22
row 23
row 24
row 25
```

<!-- shot -->
### Hanging indents

```
- dash marker with a line long enough that it has to wrap onto a second row on the slide
* star marker with a line long enough that it has to wrap onto a second row on the slide
+ plus marker with a line long enough that it has to wrap onto a second row on the slide
1. numbered with a line long enough that it has to wrap onto a second row on the slide
2) numbered paren with a line long enough that it has to wrap onto a second row on the slide
    four spaces then text long enough that it has to wrap onto a second row on the slide
	tab then text long enough that it has to wrap onto a second row on the slide, and on
no marker at all: a line long enough that it has to wrap onto a second row on the slide
```
