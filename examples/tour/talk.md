---
slug: animatic-tour
title: "Animatic in four minutes"
date: 2026-11-14
venue: Tour
dur: ~4 min
theme: lecture
media: media
author: "Ryan Kelln"
status: public demo, a talk about the tool that built it
---

<!-- shot: lamp kb=in text=light -->
# Write the talk. Get the rest.

This deck is a talkfile: one plain-text file. The slides you are looking at, the handout page and the web page all come from it.

---

## Movement 1 · One file

<!-- shot: pages kb=in dim=0.5 text=light role=stat -->
One script, every format.

A talkfile reads like narration. The spoken words are the default text, and a shot marker drops in wherever the picture changes. Everything you are reading in the handout view is the voice-over: it never appears on the slide.

<!-- shot: lamp text=light reveal -->
### What comes out

Before a list, spoken text stays in the presenter notes.

- The present view: the slides, with your script in the notes
- The document view: a printable handout and a web page
- An agent export: the hands-on parts as plain text

Each press of the next key shows the next line, and the presenter window shows what is coming.

<!-- shot: lamp text=light -->
### Plain text, with a few markers

```markdown
<!-- shot: river kb=in dim=0.4 text=light -->
### The river holds the room

The dim scrim buys the words room over bright ground.
```

Code is set in a mono face on its own plate, and wraps in the handout. A shot names the picture, how it drifts, how much to dim it and whether the text is light or dark.

---

## Movement 2 · Made for pictures and for agents

<!-- shot: river kb=in dim=0.4 text=light role=lower -->
Procedural river, drawn by make-media.py

Media is part of the format. Each picture is a card that records its credit and licence, and the check suite warns about a card with no file or a deck marked public with an unlicensed picture. That lower third will leave when the picture changes.

<!-- shot: ink-vortices layout=duo -->
### An agent can edit this

> The format is the contract. The code behind it can change.
~ AGENTS.md

A talkfile is text with a small checked grammar, so a coding agent can write one, run the check, read the findings and fix them. The `animatic-check` command is deterministic, and so is the build: the same file gives the same bytes.

<!-- shot: lamp text=light -->
### Timing is part of the script

[Timer: 2:00]

The timer counts down on the slide while you talk. The estimate for the whole talk sits in the frontmatter, and a check tells you when the script runs long.

<!-- shot: lamp text=light -->
### In a workshop, tell the room's agents where you are

Mark a slide with a waypoint and the deck publishes one word when you reach it. A hook on each participant's machine can turn that word into a note for their coding agent, so someone who fell behind hears about it without asking.

---

## Movement 3 · Try it

<!-- shot: credits -->
### Credits

- Written by Ryan Kelln
- Built with Animatic
- Pictures drawn by make-media.py

<!-- shot: black -->
