---
name: reading-copy
description: Turn one animatic talk into a clean reading copy (web page and handout PDF) and publish-check it. Run once per talk, ideally in a subagent. Use when asked to prepare, convert, audit or fix a talk for the web or print, or to mark its live-only screens.
---

# Reading copy for one talk

A talkfile renders as slides for the room and as a reading copy: the spoken words as prose, with figures and
sources. The reading copy is the web page and the handout PDF. This skill takes **one talk** from "builds" to
"fit to publish". One talk per run keeps it cheap: do not read other talks, and read only the screens the audit
names.

Animatic repo: the directory holding `build.py` (the `animatic` repo). Run commands from there.

## 1. Audit

    python3 tools/reading-audit.py <talk.md>

It builds the talk and prints one page: checker findings, how Sources will print, screens that print as a bare
heading, spoken text aimed at the room or the screen, timers in the reading copy, and anything in the page that
should not be public. Fix what it reports in the order below, then run it again until each section is clean or
explained.

## 2. Fix in the talk file (`talk.md`)

Make the smallest edit that works. Never rewrite the author's voice: read `decks/VOICE.md` and the talk's own
style file (`STYLE_WORKSHOP.md` or `STYLE_LECTURE.md`) before touching a sentence, and keep every claim as it is.

- **Checker warnings.** Fix them. An unclosed `(` (check 46) means a stage note is being read as speech: close it.
- **Room-only screens: add `live`.** A screen that only runs the room (Break, Questions, a timer, "Paste with
  Command and V", hands-on steps, a hand-count) gets the bare flag: `<!-- shot: ryan-art live -->` or
  `<!-- shot: live -->`. The slide and the presenter view keep it; the reading copy and any video drop it.
  Whole-slide `live` is the default answer. Do not mark a screen `live` if its spoken text carries an idea a
  reader needs.
- **Timer lines.** A timer prints in the reading copy as "N minute timer". On a screen that stays in the
  reading copy, wrap the timer line in parentheses: `([timer:5m])`. The countdown still runs on the slide;
  the reading copy prints nothing. Use it on every kept screen whose timer is only the room's clock. (A
  screen that is `live` needs no wrapping.)
- **References to a break or the room.** Once a Break screen is `live` it is gone from the reading copy, so
  reword lines that point at it ("after the break", "before the break", "we'll come back to it after") to
  something that holds without the break ("when it finishes", "earlier", "then"). A question-for-the-room line
  ("Any questions before the break?") goes in a stage note, or the screen goes `live`.
- **Screens that print as a bare heading.** A heading with no words under it is usually a room beat. Mark it
  `live`, unless the heading is the point (a section title like "Thank you" may stay).
- **Spoken text aimed at the room.** Where a screen has real content plus a line aimed at the room ("scan the
  code and try it", "the levels are on the screen"), do one of:
  - reword it so it reads as text and still speaks as speech ("The levels are listed on the slide" becomes a
    plain statement of the levels);
  - move the room-only line into a stage note `( ... )`. It is never spoken and never printed, and in the
    presenter notes it stays where it was written, right after that paragraph's words. This is the tool for
    room-only text inside a slide that otherwise reads as prose: a hand-count line, "scan the code and try it".
    A stage note holds one paragraph; a parenthetical does not nest and must close (check 46);
  - leave it, if it reads fine on a page.
  If the whole screen is room business, `live` the slide instead.
- **Sources.** The page prints a Sources list only from `cites:`. If the audit says it has none, write `cites:`
  in the frontmatter, one public citation per cited id: author, title, outlet, date, URL or DOI. Take them from
  the `sources:` receipt and drop the working notes ("read on", "verify", "pasted by", repo paths, "not
  re-read"). Keep a caveat only if a reader needs it ("secondary report, not primary"). Never add a detail the
  receipt does not contain; if a title or journal is missing, say so in your report instead of supplying it
  from memory.
- **Private details.** Anything the audit lists under page leaks that is on a screen on purpose (a real file
  path shown in a demo) is the author's call: do not delete it and do not clear it. Report it, and the author
  adds `web-allow: ["<the path text>"]` to the frontmatter if it may go public.

## 3. Publish-check

    python3 check.py <talk.md> --strict
    python3 tools/handout-pdf.py <talk.md> <out.pdf>
    python3 tools/web-export.py <talk.md> <out-dir>

`web-export` refuses a page that links outside its folder or shows a local path. Write outputs to a scratch
folder, not into the talk's directory. Look at the PDF's first, middle and last pages
(`pdftoppm -r 50 -png`) and one phone-width screenshot of the page (headless Chromium, `--window-size=390,2400`);
the PDF's text (`pdftotext -layout`) is the quickest way to read what actually prints.

## 4. Report

Reply with: what you changed in `talk.md` (each as one line with the screen), what you left for the author with
the reason, the audit's final state, and the output paths. Do not commit.

## What this skill never does

- Never edits animatic's code. If the reading copy is wrong because of the builder (a layout bug, a construct
  that prints badly), describe the failing screen and stop.
- Never touches another talk, `private/` folders, or media cards.
- Never invents a citation, a number or a claim.
