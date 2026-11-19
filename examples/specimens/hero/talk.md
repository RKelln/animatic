---
slug: specimen-hero
title: "Specimen: fit=hero"
date: 2026-11-18
venue: Style check
dur: ~18 min
theme: lecture
media: ../../tour/media
author: "Ryan Kelln"
status: style specimen, not a talk; tools/contact-sheet.py renders it as a sheet
---

<!-- Every screen here is fit=hero. Each one is one combination of on-screen
     features, so a styling change can be checked at a glance:
     python3 tools/contact-sheet.py examples/specimens/hero/talk.md sheet.png
     Keep the screens short and the headings descriptive: the heading is the
     only label a thumbnail has. -->

## Titles

<!-- shot: fit=hero -->
# Hero

One word, the largest the slide allows.

<!-- shot: fit=hero -->
### A long title that has to wrap across more than one line of the slide

A title of a dozen words.

<!-- shot: fit=hero -->
### Title
#### with a subtitle under it

A heading straight after a shallower one is a subtitle.

<!-- shot: fit=hero -->
### Title with `inline code` and **an accent**

Inline marks inside a hero title.

---

## Quotes

<!-- shot: fit=hero -->
### Short quote

> Less is more.

<!-- shot: fit=hero -->
### Quote of inline code

> `quote textbox`

<!-- shot: fit=hero -->
### Quote with code inside

> Type `animatic check` and read what it says before you build.

<!-- shot: fit=hero -->
### Quote with a source

> The format is the contract. The code behind it can change.
~ AGENTS.md

<!-- shot: fit=hero -->
### Long quote with a source

> I would rather address the question of how to enhance the capabilities of those involved to change the constraining rules of the game. The question is not only what the rules are, but who gets to change them, and how often, and at what cost to the people who live under them.
~ Elinor Ostrom, Governing the Commons, 1990, p.6

<!-- shot: fit=hero -->
### Two quotes

> First, make it work.
~ One engineer

> Then make it right.
~ Another engineer

<!-- shot: fit=hero -->
> A quote with no title above it at all.
~ Nobody in particular

<!-- shot: fit=hero -->
> Line one of a quote
> line two keeps its break
> and line three

---

## Lists

<!-- shot: fit=hero -->
### Three short items

- One
- Two
- Three

<!-- shot: fit=hero -->
### Eight items

- Read the talkfile
- Run the check
- Fix the findings
- Build the deck
- Open the present view
- Open the presenter window
- Rehearse with the timer
- Pack the release

<!-- shot: fit=hero -->
### Numbered, with long items

1. A numbered item long enough that it has to wrap onto a second line of the slide
2. A second item, shorter
3. A third item that also runs long enough to wrap when the slide is narrow

<!-- shot: fit=hero -->
### Nested list

- Present view
  - slides
  - presenter window
- Document view
  - handout
  - web page

<!-- shot: fit=hero -->
### List with code

- `animatic build`
- `animatic check --strict`
- `animatic serve --watch`

<!-- shot: fit=hero layout=cols -->
### Columns

- Voice-over
- Shot
- Card
- Role
- Layout
- Timer
- Waypoint
- Shelf

<!-- shot: fit=hero layout=cols -->
### Columns, long items

- The talkfile is the stable contract
- Builds give identical bytes every time
- One file holds the voice-over and the slides
- The handout prints citations, never receipts
- Checks run over every deck you have
- A packed release carries no host paths

<!-- shot: fit=hero layout=cols bullets=check -->
### Columns, checked

- Install
- Build
- Rehearse
- Present
- Pack

<!-- shot: fit=hero bullets=dot -->
### Dot bullets

- The round bullet
- As lists used to look
- Asked for with bullets=dot

<!-- shot: fit=hero bullets=check -->
### Check boxes

- Install the tool
- Open the deck
- Press s for the presenter

<!-- shot: fit=hero bullets=arrow -->
### Arrows

- A prompt goes in
- The model predicts
- Text comes out

<!-- shot: fit=hero bullets=dash -->
### Dashes

- Quiet marks
- For a list that needs a little help
- But not a bullet

<!-- shot: fit=hero bullets=check -->
### Check boxes with sub-points

- Before the session
  - charge the laptop
  - test the projector
- After it
  - send the handout

<!-- shot: fit=hero -->
### Bare items that wrap

- A bare item long enough that it has to wrap onto a second line of the slide
- A second item, also long enough to wrap when the window is narrow
- A third, short

<!-- shot: fit=hero reveal=list -->
### Revealed list, on arrival

- First shows on arrival
- Second waits
- Third waits

<!-- shot: fit=hero -->
- A list with no title
- above it
- at all

---

## Code

<!-- shot: fit=hero -->
### Short fence

```
uv run python tests/run.py
```

<!-- shot: fit=hero -->
### Long fence

```
<!-- shot: river kb=in dim=0.4 text=light -->
### The river holds the room

- a list item that is long enough to wrap under its hanging indent on the slide
    an indented continuation line that also needs to wrap when the window is narrow
```

<!-- shot: fit=hero -->
```
A fence with no title above it
```

<!-- shot: fit=hero -->
### Quote and fence

> Run this first.

```
animatic check
```

---

## Roles, tables, timers

<!-- shot: fit=hero role=stat -->
73%

<!-- shot: fit=hero role=stat -->
12,400 decks a year

<!-- shot: fit=hero role=paraphrase -->
> I would rather address the question of how to enhance the capabilities of those involved to change the constraining rules of the game.
~ Elinor Ostrom, 1990

The question is who gets to change the rules.

<!-- shot: fit=hero -->
### Table

| View | For |
|---|---|
| present | the room |
| document | the reader |
| agent | the machine |

<!-- shot: fit=hero -->
### Break

[Timer: 8:00]

<!-- shot: fit=hero -->
### Back in [Timer: 5:00]

<!-- shot: fit=hero -->
### Corner timer over a list

- An item that runs toward the lower right corner of the slide
- Another item that runs toward the lower right corner
- A third item that runs toward the lower right corner

[Timer: 3:00 corner]

---

## Over media

<!-- shot: lamp fit=hero text=light dim=0.4 -->
### Hero title over a picture

<!-- shot: river fit=hero text=light dim=0.5 -->
### Quote over a picture

> The river holds the room.
~ The tour

<!-- shot: river fit=hero text=light dim=0.5 -->
### List over a picture

- One
- Two
- Three

<!-- shot: ink-vortices fit=hero layout=duo -->
### Duo with a quote

> The format is the contract.
~ AGENTS.md

<!-- shot: ink-vortices fit=hero layout=split -->
### Split with a list

- Text on the left
- Media on the right

<!-- shot: ink-vortices fit=hero layout=titled -->
### Titled

<!-- shot: pages fit=hero layout=piece -->
### Piece
