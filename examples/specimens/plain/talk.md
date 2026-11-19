---
slug: specimen-plain
title: "Specimen: plain screens"
date: 2026-11-18
venue: Style check
dur: ~22 min
theme: lecture
media: ../../tour/media
author: "Ryan Kelln"
status: style specimen, not a talk; tools/contact-sheet.py renders it as a sheet
---

<!-- The screens of ../hero/talk.md without fit=hero, plus the features that
     only exist off hero (lower thirds, credits, black beats, drift, dim,
     text and ground colour, under, heading levels, overflowing text).
     python3 tools/contact-sheet.py examples/specimens/plain/talk.md sheet.png
     The heading is the only label a thumbnail has: keep it descriptive. -->

## Titles

<!-- shot: -->
# Hero

One word, the largest the slide allows.

<!-- shot: -->
### A long title that has to wrap across more than one line of the slide

A title of a dozen words.

<!-- shot: -->
### Title
#### with a subtitle under it

A heading straight after a shallower one is a subtitle.

<!-- shot: -->
### Title with `inline code` and **an accent**

Inline marks inside a hero title.

---

## Quotes

<!-- shot: -->
### Short quote

> Less is more.

<!-- shot: -->
### Quote of inline code

> `quote textbox`

<!-- shot: -->
### Quote with code inside

> Type `animatic check` and read what it says before you build.

<!-- shot: -->
### Quote with a source

> The format is the contract. The code behind it can change.
~ AGENTS.md

<!-- shot: -->
### Long quote with a source

> I would rather address the question of how to enhance the capabilities of those involved to change the constraining rules of the game. The question is not only what the rules are, but who gets to change them, and how often, and at what cost to the people who live under them.
~ Elinor Ostrom, Governing the Commons, 1990, p.6

<!-- shot: -->
### Two quotes

> First, make it work.
~ One engineer

> Then make it right.
~ Another engineer

<!-- shot: -->
> A quote with no title above it at all.
~ Nobody in particular

<!-- shot: -->
> Line one of a quote
> line two keeps its break
> and line three

---

## Lists

<!-- shot: -->
### Three short items

- One
- Two
- Three

<!-- shot: -->
### Eight items

- Read the talkfile
- Run the check
- Fix the findings
- Build the deck
- Open the present view
- Open the presenter window
- Rehearse with the timer
- Pack the release

<!-- shot: -->
### Numbered, with long items

1. A numbered item long enough that it has to wrap onto a second line of the slide
2. A second item, shorter
3. A third item that also runs long enough to wrap when the slide is narrow

<!-- shot: -->
### Nested list

- Present view
  - slides
  - presenter window
- Document view
  - handout
  - web page

<!-- shot: -->
### List with code

- `animatic build`
- `animatic check --strict`
- `animatic serve --watch`

<!-- shot: layout=cols -->
### Columns

- Voice-over
- Shot
- Card
- Role
- Layout
- Timer
- Waypoint
- Shelf

<!-- shot: layout=cols -->
### Columns, long items

- The talkfile is the stable contract
- Builds give identical bytes every time
- One file holds the voice-over and the slides
- The handout prints citations, never receipts
- Checks run over every deck you have
- A packed release carries no host paths

<!-- shot: layout=cols bullets=check -->
### Columns, checked

- Install
- Build
- Rehearse
- Present
- Pack

<!-- shot: bullets=dot -->
### Dot bullets

- The round bullet
- As lists used to look
- Asked for with bullets=dot

<!-- shot: bullets=check -->
### Check boxes

- Install the tool
- Open the deck
- Press s for the presenter

<!-- shot: bullets=arrow -->
### Arrows

- A prompt goes in
- The model predicts
- Text comes out

<!-- shot: bullets=dash -->
### Dashes

- Quiet marks
- For a list that needs a little help
- But not a bullet

<!-- shot: bullets=check -->
### Check boxes with sub-points

- Before the session
  - charge the laptop
  - test the projector
- After it
  - send the handout

<!-- shot -->
### Bare items that wrap

- A bare item long enough that it has to wrap onto a second line of the slide
- A second item, also long enough to wrap when the window is narrow
- A third, short

<!-- shot: reveal=list -->
### Revealed list, on arrival

- First shows on arrival
- Second waits
- Third waits

<!-- shot: -->
- A list with no title
- above it
- at all

---

## Code

<!-- shot: -->
### Short fence

```
uv run python tests/run.py
```

<!-- shot: -->
### Long fence

```
<!-- shot: river kb=in dim=0.4 text=light -->
### The river holds the room

- a list item that is long enough to wrap under its hanging indent on the slide
    an indented continuation line that also needs to wrap when the window is narrow
```

<!-- shot: -->
```
A fence with no title above it
```

<!-- shot: -->
### Quote and fence

> Run this first.

```
animatic check
```

---

## Roles, tables, timers

<!-- shot: role=stat -->
73%

<!-- shot: role=stat -->
12,400 decks a year

<!-- shot: role=paraphrase -->
> I would rather address the question of how to enhance the capabilities of those involved to change the constraining rules of the game.
~ Elinor Ostrom, 1990

The question is who gets to change the rules.

<!-- shot: -->
### Table

| View | For |
|---|---|
| present | the room |
| document | the reader |
| agent | the machine |

<!-- shot: -->
### Break

[Timer: 8:00]

<!-- shot: -->
### Back in [Timer: 5:00]

<!-- shot: -->
### Corner timer over a list

- An item that runs toward the lower right corner of the slide
- Another item that runs toward the lower right corner
- A third item that runs toward the lower right corner

[Timer: 3:00 corner]

---

## Over media

<!-- shot: lamp text=light dim=0.4 -->
### Hero title over a picture

<!-- shot: river text=light dim=0.5 -->
### Quote over a picture

> The river holds the room.
~ The tour

<!-- shot: river text=light dim=0.5 -->
### List over a picture

- One
- Two
- Three

<!-- shot: ink-vortices layout=duo -->
### Duo with a quote

> The format is the contract.
~ AGENTS.md

<!-- shot: ink-vortices layout=split -->
### Split with a list

- Text on the left
- Media on the right

<!-- shot: ink-vortices layout=titled -->
### Titled

<!-- shot: pages layout=piece -->
### Piece

A framed object, with its title.

---

## Off-hero features

<!-- shot -->
# H1 title

<!-- shot -->
## H2 title

<!-- shot -->
#### H4 title

<!-- shot: river dim=0.4 text=light role=lower -->
A lower third naming the picture

<!-- shot: lamp kb=in text=light -->
### Drift in, with a title

<!-- shot: lamp kb=zoom-top dim=0.6 text=light -->
### Zoom-top drift, dimmed

<!-- shot: ink-vortices text=dark -->
### Dark text on a pale picture

<!-- shot: ink-vortices bg=auto fit=contain -->
### Contained on its own ground

<!-- shot: ink-vortices under=lamp -->
### Media over an under backdrop

<!-- shot: river fit=cover dim=0.5 text=light -->
> A quote on a plate over a picture, long enough to wrap onto a second line.
~ The tour

<!-- shot: black -->
A beat of silence before the end.


<!-- shot -->
### Slightly too tall

- Jane Doe, Manager, Innovation 1
- Sam Roe, Services Specialist 2
- Jane Doe, Manager, Innovation 3
- Sam Roe, Services Specialist 4
- Jane Doe, Manager, Innovation 5
- Sam Roe, Services Specialist 6
- Jane Doe, Manager, Innovation 7
- Sam Roe, Services Specialist 8

<!-- shot -->
### Title, quote and list together

> A quote above the list.
~ Someone

- First item
- Second item

<!-- shot: role=credits -->
### Credits

Pictures: drawn by make-media.py, MIT

- Writing: the author
- Format: animatic
- Fonts: as the theme sets them
