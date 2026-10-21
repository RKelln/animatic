# Animatic — the talkfile format (v1.0)

A **talkfile** is a single markdown file that describes an entire talk or
lecture. It is the only source of truth. Parse it once and it renders three
ways:

- **Present view** — the cinematic slides: full-bleed media, spoken words in
  the speaker notes.
- **Document view** — the handout: the spoken words as readable prose, with
  figures and citations.
- **cues.json** — the machine contract: the structured form every tool reads.

A talkfile reads like a **video-essay narration script**. The spoken words are
the default river. Shots drop in where the image changes. On-screen text is an
explicit, rare, designed object. Because the handout is the voice-over as
prose, a lecture can be almost pure image-and-few-words on screen and still
read as a complete document.

---

## The model

A talkfile is a sequence of **screens**. A screen is the atomic unit: one
slide in the present view, one cue in cues.json, one step in the document
view.

- A **shot** is a directive (`<!-- shot … -->`) that opens a screen. The word
  *shot* names the directive; *screen* names the output unit it opens. Most
  shots open a screen; a text role is written onto a media shot's own
  directive (see "The shot directive").
- A screen closes when the next shot appears, or at a movement boundary.
- Text and media attach to the screen that is open when they appear, in file
  order.
- A `## Movement N · Title` heading is **structure, not a slide**: it closes
  the current screen and appears in the document view as a section header. The
  present view has no divider slides; to make one, put a shot before the
  heading.

Every piece of text in a talkfile is exactly one of these kinds:

| Kind | Spoken? | On screen? | In the handout? |
|---|---|---|---|
| **Voice-over** — a plain paragraph | yes | no | yes, as prose |
| **Screen text** — a role payload, heading, quote, or list after a shot | role-dependent | yes | yes, at its level |
| **Spoken list** — a list that follows spoken voice-over (see "Spoken lists") | yes | yes | yes, once, as a list |
| **Fenced code** — a block between ``` fences (see "Fenced code") | no | yes, verbatim | yes, verbatim, as a `<pre>` |
| **Handout heading** — a heading directly before a shot | no | no | yes, leading the next screen |
| **Stage note** — a parenthetical `(…)` | no | no | no (speaker notes only) |

A line's fate is decided by two things, in order: its **markdown shape**, then
its **position**.

1. **Shape decides the default.** A paragraph is spoken. A heading, quote, or
   list is screen text — on screen, never spoken (a list that follows spoken
   voice-over is the one exception; see "Spoken lists"). A parenthetical is a stage
   note. This is the whole rule for headings, quotes, and lists: they are
   always screen text, with or without a role. A list is `-` (or `*`, `+`)
   items, or numbered `1.` / `1)` items, which render as a numbered list; a
   switch between the two starts a new list. A pipe table (rows starting
   `|`, with an optional `|---|` delimiter row marking the row above it as
   the header) is screen text too. A pipe in the middle of a paragraph
   stays prose. A fenced block (a line of three or more backticks or tildes opens
   it, see "Fenced code") is screen text too, shown verbatim. The one
   exception is a list that follows spoken voice-over on its screen: it is
   spoken as well as shown (see "Spoken lists").
2. **Position overrides a paragraph's default.** A paragraph directly after a
   `role=` shot becomes that role's payload (on screen; `stat` is also spoken,
   `lower` and `credits` are not). A paragraph on a credits screen becomes a
   credits entry. A `~ ` paragraph directly under a quote becomes attribution.
   Position also decides a list's voice: a list after spoken voice-over on the
   same screen is spoken too.
3. **Position also decides a heading's screen.** A heading directly after a
   shot is that screen's on-screen title. A heading directly before a shot,
   and not directly after one, is a **handout heading**: it leads the next
   screen in the handout and names it in `nav.json` and `cues.json`
   (`title`), but it is never drawn on a slide, so a picture that carries its
   own words needs no overlay. Blank lines and non-shot comments between the
   heading and the shot do not count; any other block does. A heading
   directly after one shot and before the next stays on screen (a title
   card), and so does every heading in a run of headings that starts right
   after a shot (`# Title`, `## Date`, `### Website`); only a heading outside
   such a run is a handout heading (2026-10-05: the last heading of a
   multi-heading card used to be pulled off the slide). Movement headings are structure and are unaffected, and a credits
   screen still consumes its headings as entries. (Added 2026-09-29: such a
   heading used to be drawn at the end of the previous screen.)

   ```
   # AI Everywhere, All At Once
   <!-- shot: garden-title -->        handout heading: the picture carries the title

   <!-- shot: garden-title -->
   # AI Everywhere, All At Once       on-screen title over the picture
   ```

So a role changes only the one paragraph that follows it. With no role,
paragraphs stay spoken and headings, quotes, and lists stay on screen. Five
outcomes are possible: spoken (voice-over), on screen (screen text), both
(`stat` reads the number it shows; a spoken list reads the bullets it shows),
or neither (a stage note). Voice-over is spoken to the audience; speaker notes
are private to the presenter — different things.

---

## Design principles

Rules are judged against these. When the format is ambiguous, the reading that
serves them wins.

1. **One source, every output.** No output-specific authoring. If a fact must
   appear in two outputs, it is written once.
2. **The default river is speech.** Anything unmarked is spoken.
3. **No lookahead semantics.** A directive's meaning must be decidable from
   the directive itself and the content of its own screen; it must not change
   meaning based on blocks that appear after it. (Backward attachment is the
   model: a paragraph belongs to the screen open before it. That is not a
   violation of this principle.)
4. **Non-directive comments are inert, always.** Any `<!-- … -->` comment
   other than the `shot` directive may be added, moved, or removed without
   changing any output.
5. **Format and semantics are expensive; code is cheap.** A grammar change
   costs re-authoring of every existing talk. Prefer changes that keep old
   files building.
6. **Agent-first, human-readable.** Every construct must be machine-addressable
   (an agent can seek, extract, lint, verify) without being machine-only (a
   human can edit the file at 11pm without a tool).

---

## Frontmatter

A talkfile is YAML frontmatter followed by the talk itself.

```yaml
---
type: Talk                # the concept kind (Open Knowledge Format)
format-version: 1.0       # REQUIRED — the grammar this file targets
content-version: 4        # this talk's own content revision
slug: l01-opening         # REQUIRED — cue ids derive from its slugified form
title: "AI Everywhere, All At Once"   # REQUIRED
theme: lecture            # REQUIRED — visual identity
media: media              # OPTIONAL — the deck's local media dir (default "media")
timestamp: 2026-09-08T14:30:00-04:00  # ISO 8601, last meaningful change
logline: "One sentence: the thesis."  # what `animatic search` returns
---
```

### Required fields

- **`type: Talk`** — the concept kind, and only `Talk`. A talk is a *flat*
  concept: the file itself is the output, not a header pointing at
  sub-concepts. A file with no `type:` builds and is treated as `Talk`.
- **`format-version`** — the grammar the file was written against. Missing
  means "assume the current version," with one warning.
- **`slug`** — slugified at parse: lowercased, every run of characters outside
  `[a-z0-9]` collapsed to `-`. `L01-Opening` and `l01-opening` are the same
  deck.
- **`title`** — the talk's title.
- **`theme`** — selects the visual identity (the theme layer every view
  inlines). Two themes ship with the system: `lecture` (default — a warm dark
  room, image-forward) and `workshop` (a daylight room, text-forward). Missing,
  unknown, or pending values fall back to `lecture` with one warning. The full
  token contract lives in `docs/tokens.md`.

### Media directory

`media:` names the deck's local media directory — the home of `cards.yaml` and
the deck's media files — default `media`. The resolution order ("Media") and
the card path rule ("Media pipeline contract") are written against that name.

### Version fields

`format-version` names the grammar; `content-version` is the talk's own
revision, a monotonically increasing integer bumped on any meaningful content
change, never on cosmetic edits. The two are independent axes. A talk drafted
twenty minutes before delivery is a valid talk: `date`, `venue`, `dur`, and
`content-version` are all optional and must not fail a build.

### Receipts and provenance

Per-claim attribution is a body footnote `[^id]` at the claim site (see
"Receipts"); the registry those footnotes key into lives in frontmatter, next
to the per-concept provenance:

```yaml
sources:                  # id = footnote label
  prince-2026: "Cloudflare CEO Matthew Prince, June 3 2026"
generated: { by: agent, at: 2026-09-08T10:00:00-04:00 }
verified:
  - { by: human:ryan, at: 2026-09-09T18:00:00-04:00 }
```

- `sources:` is a flat map `id: "one-line attribution"`; ids are lowercase
  `[a-z0-9-]+`. This is the only block the builder reads, and only for the
  entries a `[^id]` reference names.
- `generated:` and `verified:` record who wrote and who confirmed the content;
  the builder never reads them.

### Recommended, unenforced

`date`, `venue`, `dur`, `status`, `description`, `tags`, `timestamp`,
`logline`. Unknown keys pass through untouched and are never an error.

### OKF conformance

- **Reserved filenames.** A talkfile must not be named `index.md` or `log.md`
  — those names are read as a directory listing and an update log, never as a
  concept.
- **Timestamps.** Every timestamp-valued key is ISO 8601 with an explicit
  offset; `date` is ISO 8601 calendar form (`2026-09-05`). No other form.

---

## The shot directive

A shot is the `<!-- shot … -->` comment. Its first token decides what kind of
screen opens; the remaining tokens are flags.

| Directive | Opens |
|---|---|
| `<!-- shot: <slug> -->` | a media screen — the slug resolves to an image or video |
| `<!-- shot: <slug> role=<role> -->` | a media screen carrying that text role |
| `<!-- shot: role=<role> -->` | a screen with only that text role |
| `<!-- shot: black -->` | a black beat — deliberate silence, no media, no payload |
| `<!-- shot: continue [flags] -->` | a new screen on the previous screen's media (alias `cont`) |
| `<!-- shot: <flag> -->` | a card-only screen — no media, no role; the flags speak for it |

An unknown first token is a slug (it names media); a slug that resolves to
nothing surfaces honestly as a placeholder.

A shot directive may span multiple lines; interior whitespace is insignificant.

**`continue`** (alias `cont`) opens a new screen that carries on the previous
screen's media: it takes that screen's slug and flags, and any flag or role
written on the continue shot applies on top (`<!-- shot: continue role=stat
dim=0.4 -->`). Text never carries: each screen has its own heading, roles and
VO. A video keeps playing across the step instead of starting over, in both
directions and along a chain of continue screens; its playback (`loop`,
`once`, `advance`, `sound`) is the same on every screen of the chain, so a
`playback=`, `sound` or `silent` written on a continue shot warns and is
dropped: write it on the chain's first shot. A continue shot with no media
screen before it warns and opens without media.

### Flags and layout

Flags are the per-shot knobs. The top-level namespace is fixed:

| Flag | Values | Meaning |
|---|---|---|
| `fit` | `cover` / `contain` / `hero` | how media fits the frame |
| `kb` | `in` / `out` / `zoom-top` | slow drift of the media layer inside a static lens; `zoom-top` is one slow push-in (about 30 s) anchored at the top edge that then holds, for a picture with lettering near its top |
| `dim` | `0`–`1` | a dark scrim at that opacity, to keep on-screen text readable; on a screen with no on-screen text it is check 30's warning (fix a too-bright image in the file instead) |
| `text` | `light` / `dark` | per-screen text treatment, overriding the theme default |
| `advance` | (none) | when the screen's video ends, move to the next screen; the video plays once instead of looping. On media that is not a video it is check 31's warning |
| `playback` | `once` / `loop` / `advance` | this screen's playback, over the card's `playback:`; `playback=advance` is the same flag as `advance`. `pingpong` is card-only (a baked file) and is check 25's warning. On media that is not a video it is check 31's warning |
| `sound` | (none) / `true` / `false` | this screen's sound, over the card's `sound:`: bare `sound` is `sound=true`. On media that is not a video it is check 31's warning |
| `silent` | (none) | `sound=false`: mutes a `sound: true` card on this screen |
| `under` | an image slug | a still backdrop drawn beneath the shot's own media, left sharp and fitted like any slide media (contain by default, `fit=cover` to fill). For a video with a transparent ground (a credits roll, a lower-third loop) that should sit over a picture the deck already has. Backdrop and media share a 16:9 stage, so they stay registered in any window shape. The media takes the share of the stage its pixel size gives it against 1920x1080 (a 1270x880 video is 66% wide, 81% tall; with no ffprobe it takes the whole stage) and sits where `anchor` says. It takes no kb drift; `dim` darkens the backdrop, never the media. Ignored under a framed layout (`piece`, `duo`, `titled`), and the backdrop has to be a still image: both are check 32's warning |
| `blur` | `0`–`100` | frosts a panel behind the `under` media: a blur radius in pixels over the media's box plus a margin, all edges feathered. With no `under` it has nothing to frost: check 32's warning |
| `anchor` | `top` / `center` / `bottom` | where an `under` media smaller than the stage sits; `center` by default. A credits roll 200 px shorter than the frame and `anchor=bottom` leaves a title at the top of the picture clear. With no `under` it is check 32's warning |
| `reveal` | (no value) / `list` / `off` / `timer`, or a `+` join (`list+off`, `list+timer`, `off+timer`, `list+off+timer`) | `list`: the screen's first list appears one item per next-press (previous steps back). A list that opens the screen shows item 1 on arrival; with a title or paragraph before it, none show. Hidden items keep their space, so nothing moves. Going back into the slide from the next one lands with every item shown; jumping in lands at the start. The hash carries the step (`#5.3`). **Presentation only:** the document view and the handout PDF show every item. Needs a list of 2+ items; without one, or with another value, it warns and is ignored. On a screen whose media is a stepped-image card (a card with `steps:`, see Media, "Stepped images"), the list and the images step together. `off`: this screen's media does not step although its card has `steps:`; it shows the card's handout image alone. `list+off` is both: the list reveals, the images do not (a shot carries one `reveal` value, so the pair is spelled out). On a screen with no stepped card `off` does nothing. `timer`: the screen's `[Timer: ...]` stays hidden and stopped until a next-press shows it and starts it (see Timer screens, "Revealed timers"); with `list` it is the press after the last item. The parts may come in any order; a repeated or unknown part warns and the whole value is ignored (check 25). **A bare `reveal` (no value)** reveals everything the screen can hide, now or in a later version of the format, one step per next-press in **document order**, the order the elements are written on the screen: today that is the first list's items (one per press) and the `[Timer: ...]` countdown. A timer written below the list is the press after the last item; a timer written above the list is the first press, and the items follow it one per press. This is exactly `reveal=list+timer`, which stays as the spelled-out form and follows the same document order. For a `corner` timer, which has no visual position, where its `[Timer: ...]` line is written decides. A timer inside the list's own items counts as after the list. A screen with only a list behaves as `reveal=list`, one with only a timer as `reveal=timer`. It never needs editing when a new revealable is added to the format: anything new opts in to the bare `reveal` by being added to the revealables list in `render.py` (`REVEALABLES`), and then steps in document order with the rest. A bare `reveal` on a screen with nothing revealable (no list of 2 or more items, no valid timer) warns (check 45) and does nothing. A stepped-image card steps on its own (see Media, "Stepped images") and does not count as something for `reveal` to reveal; with a list the images and items still step together. `reveal=list` or `reveal=timer` spelled out on a screen without that thing keeps its own warning (checks 43 and 44); a bare `reveal` never triggers those two, because it names nothing |
| `role` | a `roles.yaml` name | the screen's text role (see "Roles") |
| `layout` | a `layouts.yaml` name | the screen's config-driven layout |

**`fit` — explicit values only.** `fit=contain` shows the whole image,
letterboxed on the stage colour; it is the default for all slide media. `fit=cover`
fills the frame and crops overflow; it is the default only under `kb` drift,
whose lens needs the picture to overfill the frame. `fit=hero` scales on-screen
text as large as the slide allows and says nothing about the media, which keeps
its default. Each value means only that: a `fit=contain` screen that also
carries a heading keeps its media contained and its text at normal size.
(Changed 2026-09-28: `cover` was the default, and any `fit` on a screen with a
heading turned on hero text and dropped the contain.) A shot must not carry two `fit=`
values; a valueless `fit` is a warning with a did-you-mean hint.

**`layout=`** names an entry in `layouts.yaml`:

```yaml
layouts:
  piece: {description: "media floats as a framed object"}
  duo: {description: "object + text layout; implies piece"}
  titled: {description: "heading centred at the top, framed media centred below; implies piece"}
```

Layouts are config, not grammar: the vocabulary grows by adding entries to
`layouts.yaml` (`duo_right`, `duo_left`, …), never by editing the parser. A
layout that implies another (as `duo` implies `piece`) records that in its
description. If a layout ever needs parameters, the reserved form is a
function call — `layout=duo(side=…, object=…)` — and the parameter names are
`side=` / `object=`, never `text=` (which collides with the colour flag).

**Flag interactions.** `dim` is ignored on `layout=piece` (a full-zone scrim
would paint a box around the framed object). `kb` drift is not applied on
`layout=piece` (the lens wraps full-bleed media only). Slide-level flags
(`fit`, `layout=`, `text=`) are read from the screen's first shot; the same
flag on a `role=` shot is read but never duplicated. Media flags (`kb`, `dim`,
`fit`) read from the media shot.

---

## Screens

- **One screen = one present-view section = one cue.** Counts are identical,
  always. The document view may omit screens that carry no content (black
  beats); `nav.json` records the omission. Document step count ≤ screen count
  is the invariant.
- **Cue ids** are `<slug>-NNN`: the slugified `slug`, a hyphen, and the
  1-based screen ordinal zero-padded to three digits. Ids are unique, sort
  lexically in presentation order up to 999 screens, and are stable for a
  given file.
- **No sub-screen ids.** The screen is the smallest addressable unit; nothing
  below it carries an id. Role overlays, text blocks, and media objects are
  addressed positionally (cue ordinal, then position within the screen).
  Content that needs its own address is promoted to its own screen.

### Sections (movements)

A talk is divided into **sections** — its parts, acts or chapters — marked by a
`##` heading. A `##` heading is a section break unless it is part of a
title-card run (a run of headings that starts right after a shot, as in
`# Title` / `## Date` / `### Website`), where it stays on the slide. The
section heading is never drawn on a slide. `## Movement N · Title` is the
numbered spelling of the same thing and keeps its number; an unnumbered
section takes the next ordinal. `---` is inert.

A `###` heading that follows a section heading and precedes a shot is that
screen's handout heading, so `## Act 5` then `### Title` then a shot works as
written. The rest of this section says "movement"; read it as "section".

- **When to use them.** At argumentative boundaries — where the talk turns
  from one idea to the next. Sparingly: a handful per talk, not one per screen
  (a fifty-screen talk uses four). Numbered in order, 1, 2, 3, …
- **Why they exist.** A talk longer than a handful of screens needs coarse
  structure: the handout reads as prose with sections rather than fifty
  undifferentiated steps; "movement 3" is a chunk worth naming and seeking to;
  and the talk's own argument has parts the structure should mirror.
- **What they do.** A movement heading closes the current screen and labels
  everything after it as that movement. It appears in the document view as a
  section header; the present view has no divider slide for it (to make one,
  put a shot before the heading). The opening — everything before the first
  movement heading — is movement 0, the title zone.
- **What they are not.** A movement is not a slide, and text never attaches to
  it. Text attaches to screens; a movement only closes the current screen and
  renames the section.

### Tolerance rules

The parser tolerates a fixed set of authoring shapes, each as written here:

- **Prose before the first shot is the opening screen** — the title slide.
- **`---` horizontal rules are inert** — they separate, never create or close.
- **A shot that opens a screen with no content by end of file is dropped**
  with a warning; an empty trailing screen never reaches any view.
- **Consecutive shots with no content between them warn** — the second opens a
  new screen and the first stays an empty beat. (There is no implicit merge: a
  text role that overlays media is written on the media shot itself, as
  `role=`, not as a second shot.)
- **A bare `role=` shot directly after another shot warns** — the would-be
  implicit merge — with a hint to write `role=` on the media shot instead. It
  still opens its own screen.

---

## Text

### Voice-over

A plain paragraph is spoken. It belongs to the screen open before it. A screen
with no paragraphs has no voice-over (a "beat screen") — that is the default
and needs no marker.

### Spoken lists

A list is screen text: it shows on the slide and it is never spoken. **A list
that follows spoken voice-over on the same screen is spoken as well as shown.**
The speaker says the lead-in, then reads the bullets; the list is written once
and lands on the slide, in the speaker notes, in the script, in the captions
and in the timing estimate — the copy under `[notes]` or in a parenthetical
that used to carry the same words is now redundant (check 42).

```
<!-- shot -->
# Title

Spoken line is here, then I say and display:

- bullet point is in notes and on slide
- same same

More spoken text
```

- **The trigger.** Spoken voice-over *before* the list, on the same screen: a
  voice-over paragraph (one with words in it), or a spoken role payload
  (`stat`, `paraphrase`). A stage note is not voice-over, so a list under a
  `(…)` note stays screen text. A list that stands *before* any spoken text
  on its screen is screen text too: the rule does not reach back. Each screen
  counts on its own.
- **The script.** The items join the script where the list stands, one item
  per paragraph, exactly as written — the words and their punctuation
  untouched, markdown markers stripped as everywhere else in the script. A
  parenthetical inside an item is never spoken: it comes out of the speech and
  travels as a stage note, while the slide keeps the item as written.
- **The speaker notes.** The list appears in the notes as the bullets the
  speaker is reading, in file order between the spoken paragraphs.
- **The handout.** The list prints once, as a list. The duplication the
  feature removes is the copy, not the list.
- **Everything else is unchanged.** The slide shows the list as before,
  `reveal=list` still steps the bullets one per press, and a screen's
  estimated time grows by the words now read aloud.
- **`cues.json`.** The list's `screen_text` entry carries `"spoken": true`,
  and the items are in the cue's `script`.
- **Check 42** (warning): a `[notes]` block that repeats a spoken list word for
  word. The list is read aloud already, so the copy would be read twice.

### The reading copy

The speaker notes are a **reading copy of the screen**. They carry:

- the presenter's **voice-over** paragraphs;
- the **payloads he reads off** — a `stat` (the number), a `paraphrase` (our
  line under a quoted source). Both are spoken, so both are in the script; the
  notes now show them too, so the number is in front of him;
- the screen's **text that follows his words** — a list, a quote (with its
  attribution), a code block — copied with the markup the slide uses: bullets,
  the quote and its credit, the code verbatim. On a screen with **no words of
  its own**, all of the screen's text is copied: the slide is what he has, and
  the notes let him read it without looking at it.

```
<!-- shot -->
### Before we share

Ok let's show off what you've made:

> Tell it: "Time to share."

- make sure it plays from the start
- write your NOTES.md with your assistant
```

The notes for that screen read: the lead-in, the quote, the two bullets — the
whole screen, in the order it stands.

- **The trigger.** Spoken voice-over *before* the text: a voice-over paragraph
  (one with words in it), or a spoken payload (a `stat`, a `paraphrase`). A
  stage note is not voice-over. A screen with no spoken text at all copies all
  of its text. Text that stands *before* the presenter's words is not copied:
  the notes show what comes after the words, and the slide shows the rest.
- **It is not speech.** A copy never reaches the script, the captions or the
  clock — it is a reading aid, exactly like a `[notes]` block. The only text
  that is spoken is what the spoken-list rule already speaks (see "Spoken
  lists"). The handout prints the screen's text once, as the slide does; the
  copies are the presenter's, and stay off the page.
- **Order.** The notes follow the screen: his words, then the text that
  follows them, then his `[notes]` blocks, then the stage notes.
- **Check 42** (warning): a `[notes]` block that repeats what the notes
  already carry. The copy can go.

### Fenced code

A line of three or more backticks (or tildes, `~~~`) opens a **fenced block**;
it closes on a line of the same character with at least as many, with nothing
after it. Both fence lines may be indented up to three spaces. Whatever follows
the opening fence on its line (an info string) is allowed and ignored; the
documented spelling is `text`. Use it to put a whole file on screen exactly as
written:

````
<!-- shot: fit=hero -->
### Timer screens

`[Timer: 8:00]` in screen text puts a **countdown** on the screen. It exists for
a break while a picture stays up, a group activity, a question window, a short
paper exercise. The token is written as part of the screen's own text, so it
appears wherever it sits among the other text; there is no shot flag (`timer=`
is an unknown flag like any other; the one shot flag that touches a timer is
`reveal=timer`, below).

```
<!-- shot -->
### Break
[Timer: 8:00]

<!-- shot -->
### Back in [Timer: 8:00]

<!-- shot: w02-agent-anatomy -->
### Break
[Timer: 8:00 corner]
```

- **The token.** Square brackets, the keyword `Timer`, a colon, a duration, and
  optionally the word `corner`. Everything is **case-insensitive and forgiving
  about spacing**: `[Timer: 8:00]`, `[timer:8:00]`, `[TIMER : 8:00]`, `[ Timer:  8m ]`
  and `[Timer: 3M CORNER]` all match (one or more spaces before `corner`).
  Durations: `90s`, `8m`, `1h`, `1h30m`, `1m30s`, `5:00` and `12:30` (mm:ss, the
  seconds two digits under 60), and a bare integer (seconds); units in either case.
  Zero is not a duration.
- **Where it works.** In screen text: alone on its line (a **block**), or inline in
  a heading, a list item, a quote, or a `stat` / `paraphrase` payload. Elsewhere
  (table cells, a quote's attribution, `lower` / `credits` lines) it is plain text.
  **At most one timer per screen**: the first valid token is the timer.
- **Where it does not.** In a **plain paragraph** (voice-over) the token would be
  read aloud, so it is dropped from the voice-over, starts nothing, and warns
  (check 39). Inside a **fenced code block** it stays literal text. Inside a
  **parenthetical** `( ... )` it stays inert stage-note text: parentheticals never
  have behaviour (see "Directions"), and this is not an exception. A bracketed
  phrase that does not start with `timer:` is ordinary text. A `continue` screen
  does not inherit a timer (text never carries); write a new token on it for a new
  countdown, which starts when that screen is shown.
- **Anything that starts `[Timer:` and does not parse** (a typo in the duration, zero,
  an unknown trailing word) warns (check 37) and is **left as literal text** on the
  screen, so the mistake is visible. A second timer on one screen warns (check 37),
  is ignored and stays literal. Over 3 hours warns (check 38) and is kept.

**Present view.** The digits replace the token in place, in the text flow, in the
theme's display face with fixed-width cells (so they never jiggle): `m:ss`, or
`h:mm:ss` from an hour.

- A token **alone on its line** is a block: large digits (7.4em of the slide's
  text, about 16% of the frame height at 1080p) centred like other screen text;
  with `fit=hero` they grow with the slide (up to 14em).
- A token **inside** a heading, list item, quote or stat is inline, at that text's
  own size.
- With the word **`corner`** the token is not in the flow: the countdown is a plate
  in the lower-right of the frame (4.4em digits, a mostly opaque plate in the stage
  colour with a hairline edge), for a screen whose picture must stay uncovered.
  The token's own text is removed from the flow. A credits line or a paper-theme
  lower third on the same screen is lifted clear of the plate.
- Lecture uses the dark stage tokens, workshop the paper tokens. The one new token
  is `--stage-alert` (see docs/tokens.md).

**Run rules.**

- **Start.** The countdown starts the first time the screen is shown in the present
  view (next, previous, a jump, a button, or arriving from the hash). It runs on a
  wall-clock end time (`Date.now`), never a tick count, so a throttled tab or a slow
  frame cannot drift. It **keeps running** while the presenter is on another screen,
  so coming back shows the true remaining time. State is **not persisted**: reloading
  the page restarts every timer. Presenter-view previews and the document view never
  start or run a timer (a preview shows the full duration).
- **End.** At 0:00 the digits take the alert colour and a one-second `0:00` shows;
  then it **counts up with a leading `+`** (`+0:42`) and the label reads `over time`.
  One soft pulse at zero (a one-shot animation, none under `prefers-reduced-motion`).
  No sound. The slide never advances by itself.
- **Controls** (deck window, and the presenter window sends the same commands; they
  act on the current screen's timer and do nothing on a screen without one):

  | Key | Does |
  |---|---|
  | `p` | pause / resume (paused: digits dim and the label reads `paused`; inline timers only dim) |
  | `0` | reset to the full duration and **run** (a reset restarts it, from paused or from overtime) |
  | `+` or `=` | add one minute |
  | `-` | take one minute off (may put it into overtime) |

  The pager's keys (`n`, `s`, `r`, `d`, `i`, `m`, arrows, space, Home, End, PageUp,
  PageDown, Escape) are untouched.
- **Presenter view.** The header shows the current screen's countdown (large digits,
  `paused` / `over time`) and the keys. The deck pushes `{mode, endAt, left,
  duration}` on every change and the presenter counts from the same wall clock, so it
  stays live; it reuses the existing postMessage channel and adds one request type,
  `animatic-timer`, from the presenter to the deck.

**Document view and handout.** No clock. A token alone on its line (or a `corner`
one, below the screen's content) prints one quiet line, `<duration> timer`; an inline
token prints inline as the same words (`Back in 8 minute timer`). The words use the
duration as written, singular: `8 minute`, `90 second`, `1 hour 30 minute`, `5:00` is
`5 minute`, `12:30` is `12 minute 30 second`.

**`cues.json`.** A screen with a timer carries `timer` (integer seconds), `timer_in`
(the index of the `screen_text` entry whose text holds the token) and, with `corner`,
`timer_corner: true`. A block token is a `screen_text` entry `{"kind": "timer", "text":
"[Timer: 8:00]"}`. The media manifest is unaffected. The token stays in `screen_text`
as written; it is never in `script`.

**Timing.** A screen with a timer and **no voice-over** has `est_seconds` equal to the
timer's seconds (a video's real duration still floors it). A screen **with** voice-over
keeps the word-count estimate; the timer adds nothing, so nothing is counted twice.
(For a stat whose payload is only the token, the token is not spoken, so the screen
has no voice-over.)

**Revealed timers.** `reveal=timer` on the screen's shot keeps the countdown
hidden and stopped on arrival, so the facilitator can put the directions up, talk
through them, and start the clock with one press while the room works.

```
<!-- shot: reveal=timer -->
### Type the three lines
[Timer: 9:00]
```

- **Arrival.** The slide shows its other text. The timer's space is kept (the plate
  is invisible, nothing shifts when it appears) and nothing is counting. It does not
  start on arrival, from a jump or from the hash.
- **The press.** The first next-press (any key or button that advances: arrow,
  space, page down, clicker, the next button) reveals the plate and starts the
  countdown from its full duration, on the same screen. The press after that leaves
  for the next screen as usual. `reveal=timer` is one more step on the screen's own
  step counter, the last one, so the hash carries it (`#5.1`) and a deep link to
  that step arrives with the timer already running.
- **With `reveal=list`** (`reveal=list+timer`): the steps follow document order. A
  timer written below the list comes last: the list's items appear one per press and
  the press after the last item reveals the timer. A timer written above the list
  comes first: the first press shows it and starts it with no item showing, then the
  items follow one per press (a list that would open the slide with item 1 showing
  opens empty instead, so the timer's press really is the first). A `corner` timer
  takes its place from where its line is written. A timer inside the list's own items
  counts as after the list. With a stepped-image card the images step with the items
  as before; a timer-first slide shifts both one press later, a timer-last slide
  adds its step after the last frame. The cue carries `timer_reveal_first: true` when
  the timer comes first.
- **Back and return.** Stepping back from the revealed step, or leaving the screen
  and coming back to it (Back included), puts the timer back to hidden and unstarted,
  full duration. When the timer is first, stepping back one press from step 2 to 1
  keeps it running (it is still revealed) and only stepping back past its own press,
  to step 0, hides and stops it; coming back into such a slide from the next one lands
  on its start (nothing shown), because the timer's press is the first one. When the
  timer is last, coming back lands on every step but the timer's, which is always
  waiting for its own press. Timer controls (`p`, `0`, `+`, `-`) act on a revealed,
  running timer and do nothing while it is hidden. Restarting the talk (`t`) hides
  it again.
- **Zero** is the same as any timer: alert colour, a one-second `0:00`, then `+m:ss`
  and `over time`; the slide never advances by itself.
- **`corner` and inline** tokens work the same way: the plate is hidden until the
  press.
- **Document view, handout, previews.** Unchanged: the quiet line `9 minute timer`
  and a full-duration plate in previews. `cues.json` adds `timer_reveal: true` on the
  cue (next to `timer`); nothing else changes, and a screen without the flag has no
  new keys.
- **Timing.** Unchanged (the timer's seconds still stand as the estimate for a screen
  with no voice-over). `[next]` marks in a screen's script count the timer's press
  (check 40).
- **No timer, no effect.** On a screen with no valid timer the flag warns (check 44;
  the build prints `warn : <cue id>: reveal=timer needs a [Timer: ...] on the
  screen; ignored`) and nothing is hidden. A bad or zero duration or a second timer
  is check 37 as always, so the screen then has no valid timer and check 44 follows.

**Bare `reveal`.** Writing `reveal` with no value on the shot reveals the timer too,
with anything else the screen can reveal, one press at a time **in document order**:
the elements in the order they are written. Spelled out, that is `reveal=list+timer`;
with only a timer on the screen it is `reveal=timer`. A timer written below the list
is the last press; written above the list it is the first. See the `reveal` flag in
Shot flags.

```
<!-- shot: reveal -->
### Type the three lines
- Line one
- Line two
[Timer: 9:00]
```

**Checks.** 37 (a token that is not a timer, or a second one), 38 (over 3 hours),
39 (a token in a spoken paragraph), 44 (`reveal=timer` with no valid timer), 45 (a
bare `reveal` on a screen with nothing to reveal).

### SOUL.md
```text
You are a thoughtful, creative collaborator.

* Explore possibilities without pretending certainty
- Avoid sycophancy
```
````

- **Nothing inside is parsed.** No shot directive or other `<!-- -->` comment,
  no heading, list, quote, table, parenthetical, footnote marker, include or
  role handling, no markdown, and no text lint (check 23, em dashes) reads it.
  Lines are kept exactly as written: blank lines, indentation (the fence's own
  indent is not removed from its lines), tabs, `*` and `-` bullets, `<!--`. The
  text is HTML-escaped for output, never interpreted. A longer opener is
  closed only by an equally long (or longer) fence line, so a fence can hold
  shorter fence lines (four backticks around three, `~~~` around backticks).
- **Kind and fate: screen text.** On screen, never spoken, never counted in the
  voice-over word count or the timing estimate (`script` and `est_seconds` are
  what the paragraphs alone give). In the document view and the handout it
  appears at its level as a verbatim `<pre>`. It sits where it is written: a
  heading directly after a shot is still the screen's title, and the block is
  drawn beneath it, in file order with the screen's other blocks. A fence
  interrupts a paragraph or list that runs straight into it, and may follow a
  heading on the very next line.
- **Not a role payload.** The `role=` payload rule applies only to a paragraph.
  A `role=` shot followed by a fence behaves as it does for a list or quote:
  the fence is a screen object that rides ahead of the payload, is still drawn,
  and the role keeps waiting for its paragraph (no warning is added).
- **Not stepped.** It takes no part in `reveal=list` or stepped images: it is
  shown whole from arrival. Several fences on one screen are all shown.
- **`cues.json`.** The block is a `screen_text` entry `{"kind": "code",
  "text": "<the lines, joined with \n, no trailing newline>"}`, kept verbatim
  (the em-dash and parenthetical hygiene rules that apply to other screen text
  do not apply to it). An empty fence emits nothing.
- **Unclosed fence (check 35).** A fence that never closes is treated as
  closing at the end of its screen: just before the next `<!-- shot` line or
  `## Movement` heading, else at the end of the file (trailing blank lines are
  not content). It warns. Beware that a fence is closed by the *next* matching
  fence line anywhere later in the file, shot lines and movement headings
  included, so a forgotten closer can swallow the screens after it up to the next
  fence line of that kind (the same as markdown). Check 35 fires only when no
  such line exists; if a screen after a fence goes missing, look for a missing
  closer.
- **Empty fence (check 36).** A fence with no lines, or only blank ones, warns
  and shows nothing.

**Present view.** The block is set in the theme's `--font-mono` token,
left-aligned, whitespace preserved, on a quiet plate in the family of the quote
plate (`--quote-panel-bg` and its shadow, with a hairline edge and an accent
rule on the left; backdrop blur over media). The text is the list's weight
(`1.15em` of the slide's text, in mono, about 37 px at 1080p), and the slide
gives the block the room (tight side padding). The lecture theme sets it light on
a dark plate; the workshop theme sets it ink on a paper plate with an olive-clay
rule and no glow.

**Wrapping: width never shrinks the text.** A line longer than the plate wraps
(`white-space: pre-wrap`, `overflow-wrap: anywhere` as a last resort), at
whatever size the block is. A source line that begins with a list marker
(`- `, `* `, `+ `, `1. `, `1) `) or with spaces or tabs **hangs**: its wrapped
rows align under the text after the marker or indent (tabs count as 4), so a
wrapped bullet still reads as one bullet. Each source line is a block `<span
class="cl">` carrying `padding-left` and a negative `text-indent` of the marker
width in `ch`, and ending in its own newline: the characters, and what a copy
and paste returns, are exactly the source's; only layout changes. The same
markup is used in the document view.

**Fitting: only height decides the size.** Without `fit=hero` the block stays at
its normal size. If the slide's text is too **tall**, it shrinks step by step to
a floor of 75% (the pager's rule for overflowing slide text); the content must
also stay inside the slide body's padding. A slide still too tall at the floor
stays at the floor, is marked `data-fit="floor"`, and logs a console warning:
its top and bottom are clipped by the slide edge, so shorten or split the block
(a `continue` screen carries on). Under `fit=hero` the title steps down to a
heading size (the block is the hero), and the block takes the **largest size at
which the wrapped block fits the available height, from the 75% floor up to 300%
of its normal size**; a short block grows to fill the slide, and a long line
wraps instead of holding the size down. Beyond the floor under hero the
behaviour is the same as above (clipped, marked `floor`). `reveal=list` on a
screen whose only block is a fence has no list to step: the builder prints
`warn      : <cue id>: reveal=list needs a list of 2 or more items on the screen; ignored`
(a build note, not a numbered check) and the flag does nothing.

**Document view and handout.** A `<pre class="code-block">` with the theme's
code styling (mono, a tinted callout panel and an accent rule), `white-space:
pre-wrap` so a long line wraps and nothing is cut off on paper, the same hanging
indent, and not split across a page where it fits.

### Roles

Roles are the kinds of on-screen text. They exist because a video essay is
text layered over media: some text is spoken (the number you read out), some
is a label that names the image, some is a credit that sits in the corner.
Roles let a script distinguish these with one word, and let the renderer treat
each kind the way it should.

The role vocabulary is config, not grammar. Four roles ship in `roles.yaml`;
`black` is built in:

| Role | Spoken? | On screen | Form |
|---|---|---|---|
| `stat` | yes | yes | callout — a big number the speaker reads |
| `lower` | no | yes | lower-third — a transient label naming the image |
| `credits` | no | yes | end-roll — persistent attribution |
| `paraphrase` | yes | yes | paraphrase — our plain-language line under a quoted source |
| `black` | — | — | a deliberate black beat, no payload |

```yaml
# roles.yaml (shared default; a deck may override at deck/roles.yaml)
roles:
  stat: {spoken: true, form: callout}
  lower: {spoken: false, form: lower-third}
  credits: {spoken: false, form: end-roll}
  paraphrase: {spoken: true, form: paraphrase}
```

A role is written with the `role=` flag:

```
<!-- shot: river-personhood role=credits -->
<!-- shot: letters dim=0.5 role=lower -->
```

**The vocabulary grows by yaml, never by grammar.** Add a `quote` entry to
`roles.yaml` with its `spoken` / `form`, and `role=quote` works
— no parser change. The names above are the frozen starting set; the
mechanism is additive.

**The payload** is the next paragraph on the screen, after any leading quote,
attribution, or list blocks. It becomes that role's screen text (for `stat`
and `paraphrase`, it is also spoken — the speaker reads it). A role shot whose
payload never arrives warns.

**One role per screen.** A second `role=` of the same value on one screen
warns; an unknown role warns against the effective yaml and never fails.

To speak a credits line, place it as voice-over before the credits shot:
credits payloads are screen text, never script.

### Credits (end rolls)

A bare `credits` shot (`<!-- shot: role=credits -->`) opens an end-roll screen
that consumes what follows as screen entries until the next shot or movement
boundary. It consumes exactly: a paragraph (one entry), a list (one entry per
item), a heading (the roll's title). A quote is not consumed — it stays a
quote, and the would-be payload fires the never-consumed warning instead of
silently absorbing into the roll.

### Attribution

Attribution is the `~` form only: a paragraph beginning `~` whose immediately
preceding block is a quote. Three spellings are equivalent: `> ~ Source` as the
quote's last line, `~ Source` on the line under it, and `~Source` (no space). It is screen text (right-aligned under the quote),
never spoken, and travels with the quote. Same-line attribution (`> q ~ Name`)
is unsupported — the whole line renders as the quote. An attribution-shaped
paragraph anywhere else is spoken, with a warning.

Consecutive `>` lines keep their line breaks (a title card's date and venue
lines stay on separate lines; it is not markdown soft-wrap). A blank `>` line
inside a quote is a paragraph break, shown as separate
paragraphs on the slide and in the document view. The slide sizes a quote by
its length: a short one (60 visible characters or fewer) gets a column wide
enough to stay on one line, a long one (320 or more, or three paragraphs or
more) a wide column at reading size, and any quote that still overflows its
slide shrinks until it fits.

### Showing the source, saying our line (paraphrase)

A source's sentence and our plain-language version of it are two different
objects, and one screen can carry both: the quote stays screen-only and
unspoken, the paraphrase is shown **and** spoken. Write the paraphrase role on
the screen's shot, then the quote, its attribution, and the line you will
actually read:

```
<!-- shot: ostrom-rules-cover role=paraphrase -->

> I would rather address the question of how to enhance the capabilities of those involved to change the constraining rules of the game.
~ Elinor Ostrom, Governing the Commons, 1990, p.6

The question is not who to blame for the game. It is who gets to change the rules.
```

The quote keeps its own treatment (`>` is screen text, never spoken, and the
`~ ` attribution travels with it); the paraphrase renders as our words — no
quotation styling, a distinct weight and accent — and lands in the script, so
the same sentence reaches the speaker notes, the captions, and the recorded
voice-over. The paragraph is the payload *after* the leading quote and
attribution, not necessarily the block that directly follows the shot.

`paraphrase` is the `stat` shape with a different form: shown and spoken. It is
one line of yaml in `roles.yaml`, like every other name in the vocabulary — the
grammar does not change, and a deck may add its own name for the same form in
its own `roles.yaml`.

### Notes text (`[notes]`)

`[notes]` alone on a line keeps the lines directly under it off the slide and
out of the speech: they show in the presenter notes and print in the handout at
that spot. Use it when a picture already carries a list and the written version
should still have the words. (Not a stage note: a `( … )` parenthetical stays
out of the handout.)

```
<!-- shot: notebook-sources -->
### notebook.google.com

[notes]
- Five sources on the left
- A chat in the middle

This paragraph is still spoken.
```

- **Scope.** The consecutive non-blank lines after the marker (a blank line,
  a shot comment or a fence ends it). Anything inside can be a list, table,
  quote, heading or paragraph.
- **Kind.** The block is kind `print` (wrapping `inner` blocks), never in
  cues.json; `onscreen_blocks` skips it, so `dim` still warns on a screen whose
  only text is in `[notes]`.
- **With a spoken list.** `[notes]` is the other door to the notes: it keeps
  a block off the slide, where a spoken list puts it on the slide and reads it
  aloud (see "Spoken lists"), and where the reading copy puts a silent
  screen's list in the notes (see "The reading copy"). A `[notes]` block that
  repeats a list the notes already carry is redundant, and check 42 says so.

### Directions (parentheticals)

Parentheses are never spoken and never on screen. Every parenthetical is
stripped identically and travels as a stage note (speaker notes in the present
view, `stage` in cues.json). Parentheticals do not nest — a nested `(` warns.

One exception, and it predates the spoken lists: a parenthetical *inside* a
list item is part of the item, which is screen text, so it stays on the slide.
If that list is read aloud, the parenthetical comes out of the speech and
travels as a stage note (see "Spoken lists").

A parenthetical may span lines. When a line starts with `(` and the parens do not
balance until a later line, everything up to the closing `)` is one stage note,
list items included (their markers dropped, items joined with `; `). This is the
way to keep a list in the speaker notes without drawing it on the slide:

```
(
- Ask every time
- Ask for anything risky
)
```

It runs over consecutive non-blank lines only. A blank line, heading, shot
comment or fence before the closing `)` cancels it, and the lines parse as they
would without the `(`.

When the list is on the slide and the speaker reads it, this copy is
redundant: a list that follows spoken voice-over is spoken as well as shown
(see "Spoken lists").

A prefix is an authorial convention, never behaviour:

| Prefix | Convention |
|---|---|
| `(Visual: …)` | brief for media generation |
| `(Beat.)` | timing / pause |
| `(Demo: …)` | live demo plan, speaker notes only |
| `(Flesh out: …)` | unwritten beat, speaker notes only |
| `(Note: …)` | note-to-self about the argument |

Recognising a prefix never changes what happens to the parenthetical — it
still strips and still travels. The same holds for anything written inside one: a
`[Timer: 8:00]` token inside a parenthetical is stage-note text and starts nothing
(see "Timer screens").

### Receipts

A claim's source is a body footnote reference `[^id]` at the claim site, keyed
to the frontmatter `sources:` registry:

```markdown
57.5% of web traffic is bots, not people.[^prince-2026]
```

- The reference sits where the claim sits — positionality is the point: the
  source is attached to the sentence it documents, not gathered at the end.
- Footnote references are **inert**: stripped from every text block at parse —
  never spoken, never on screen, never verbatim in any view. The document view
  ends with a **Sources** list carrying every referenced registry entry in
  first-appearance order; cues.json mirrors the same payload as `deck.sources`.
- A `[^id]` with no `sources:` entry is a warning.

---

## Media

Shots reference **extensionless slugs** — `jungle-plantation`, not
`jungle-plantation.jpg`. Type and file format live in the card, never in the
script.

The indirection exists for two reasons:

- **Remix.** The script names an idea, not a file. Swap the file behind the
  slug and the talk does not change; a slug pasted into another deck resolves
  against that deck's media.
- **Output freedom.** The same slug can be a video in the present view and a
  still — or an entirely different image — in the PDF. The slides and the
  handout need not carry the same art.

### Stepped images

A card may carry a **`steps:`** list: a diagram built in frames, say, that the
presenter walks through on one screen. It is declared on the card (a
`library.yaml` entry may carry it the same way), so any screen whose media slug
is that card steps, with no shot flag.

```yaml
- slug: text-to-action
  type: image
  steps: [tta-1, tta-2, tta-3, tta-4, tta-5, tta-6]   # image slugs or card slugs, in order; 2 or more
  handout: last                                        # optional: last | first | <a slug from steps> | a 1-based integer
```

- **Frames.** Each entry resolves like any media slug (cards, deck media dir,
  library) and has to be a still image. Each is published with the card. A frame
  that is itself a stepped card contributes its own image, not its steps.
- **The one image (document view and handout).** A stepped screen prints
  exactly one image, never the frames, and shows no stepping control. The rule:
  `handout:`, when written, names it (`last`, `first`, a slug from `steps`, or
  a 1-based number). When it is not written, the card's own image (`approved:`,
  `file:`, `outputs[]` or a deck-dir file) is that image, so a card that has
  its own summary picture keeps it; a card with no image of its own prints its
  **last** frame. So `last` is the default for a card with no image of its own,
  and `handout:` is only needed to override. This one image is what the card
  resolves to wherever a single image is wanted: the document view, the
  manifest and `cues.json` `file`, and a `reveal=off` screen.
- **Present view.** Arriving shows frame 1. Each next-press shows the next frame
  (a short crossfade with the previous frame held beneath it so nothing dips to
  the ground; a hard swap under `prefers-reduced-motion`); after the last frame,
  next goes on to the next slide. Previous steps back; going back into the slide
  from the next one lands on the **last** frame; jumping in lands on frame 1. The
  hash carries the step like `reveal=list`: `#5.3` is slide 5, frame 3 (frame 1
  is just `#5`). The presenter view reads `step N of M` where it reads
  `item N / M` for a list. A stepped screen takes no `kb` drift, and with `under=`
  it does not step (it shows the handout image).
- **`reveal=off`** on the shot turns the stepping off for that screen: it shows
  the handout image alone. The `still` flag was considered and not reused: it
  picks a frame of a *video* for the handout, a different job.
- **With `reveal=list` (lockstep).** When one screen has a stepped card and a
  `reveal=list` list, one next-press moves both: item N goes with frame N. The
  steps number the larger of the frame count and the item count; if the counts
  differ the shorter holds on its last until the longer finishes (it never
  wraps) and check 34 warns, since it is probably a slip. Arrival: frame 1 shows,
  and the list keeps its own arrival rule (item 1 if the list opens the screen;
  none if a title or paragraph comes first). Where the two disagree, press 1 is
  bullet 1 with frame 1: with a title first, frame 1 is already up on arrival and
  press 1 only brings bullet 1. The hash is one number for both (`#5.2`). Going
  back in lands with every item and the last frame. A list **without**
  `reveal=list` on a stepped screen shows whole while the images step, and nothing
  warns. `reveal=list` on a screen whose media is not a stepped card is
  unchanged. `reveal=off` stops only the images.
- **`continue`.** A `continue` screen is the same picture carrying on, so on a
  stepped card it opens on the **last** frame and does not step (starting over
  at frame 1 would look like the diagram being undone). To step the card again,
  name its slug in a new shot.
- **Handout.** A repeated figure is still printed once (a `continue`, or the
  slug just before), as for any media.
- **Outputs.** The build summary prints a `steps` line for every stepped screen
  (`steps     : text-to-action: 6 steps (handout: last) [deck-014]`). The
  card's media object in `cues.json` and the manifest carries `steps` (the frame
  slugs) and `handout` (the slug of the image the handout prints; the card's own
  slug when its own image is used), on stepped cards only. A frame counts as
  referenced by its card in `unreferenced_cards`.
- **Free-text `steps:`.** Only a YAML list declares stepping. A card whose
  `steps:` is prose (decks have used it as a free note) is left alone, with no
  warning.
- **Check 33** (warning): `steps:` is a list of fewer than 2; a step is not a
  resolvable still image (it resolves to nothing, or to a video or live capture);
  `handout:` is not `first`, `last`, a step's slug, or a number from 1 to the
  step count. The card falls back to a single plain image (its own, or a
  placeholder). **Check 34** (warning): a stepped screen and its `reveal=list`
  list have different lengths.

### Resolution order (frozen)

1. deck `media/cards.yaml` — `approved:`, then `file:`, then `outputs[]`
2. deck `media/<slug>/attempts/<slug>-a<N>.<ext>` — highest N
3. deck `media/<slug>.<ext>`
4. shared `_media/library.yaml` (sibling of the deck dir)
5. `--media-remap` stand-in (deliberately last — real art always wins)
6. placeholder (a grey box carrying slug, status, and reason)

### Pool cards (one slug, a folder of art)

A card with `pool: <folder>` stands for every media file in that folder
(deck-relative or absolute; images and video, hidden files and sidecar yaml
skipped). Each use of the slug in a shot gets the next file of a seeded
shuffle of the folder (seeded by the deck's frontmatter `slug`, so two decks
sharing a pool get different orders), in document order, with no repeats until every file has
been used; the next cycle is reshuffled and never opens on the file that ended
the last.

```yaml
- slug: ryan-art
  type: image
  status: have
  pool: ../_media/ryan/kaleido
  seed: 2          # optional; change it to re-roll the whole deck
  text: light      # optional; default text= for every shot using the pool (any card may carry it)
  pins:            # optional; ids that always resolve to one file
    title-ink: ink_03889_2259_01.png
  alt: Abstract art by Ryan Kelln
  credit: Ryan Kelln
  licence: CC BY-SA
```

- The pick is made at build time, so it cannot change on navigation, and a
  rebuild gives identical bytes. Adding or removing a file in the folder, or
  changing `seed:`, re-rolls the picks.
- A `continue` screen keeps its head's file. `under=<pool-slug>` takes its own pick.
- Each use becomes a virtual slug `<slug>--NN` (NN = use number) in the
  manifest and `_media/`; the build prints a `pool` line per use with the
  chosen file name. The manifest source is `pool`.
- An empty or missing folder renders a placeholder that says so.
- **Pins.** `pins:` maps an id to a file name in the folder. `<!-- shot: title-ink -->`
  then needs no card of its own and shows that file every time. Pinned files
  are left out of the random draw, so a pinned image appears only where it is
  pinned. A pin id follows the slug rules and must not repeat a card or another pin.
- **Text.** A pool takes `text:` like any card; see "Card text default" below. It
  covers draws, pins and `continue` screens.
- **Check 41** (warning): the pool folder is missing or has no unpinned files; a
  pin names a file that is not in the folder (the screen is a placeholder); a pin
  id breaks the slug rule or repeats a card (the pin is ignored); a bad `text:`
  on any card (see below).

### Card text default

Any card, or shared-library entry, may carry `text: light|dark` (`light` for dark
art, `dark` for bright art). It is the default `text=` flag for every shot that
uses the slug, whatever the card is: image, video, live, or a pool (draws, pins and
`continue` screens). A shot's own `text=` wins. Any other value is ignored with a
check 41 warning. A deck card shadows a library entry of the same slug, text included.

```yaml
- slug: lighthouse-harbor
  type: image
  text: light      # shots of this slug get text=light unless they say otherwise
```

### Slug scope and uniqueness

- Charset `[a-z0-9-]`, 3–40 chars, no leading/trailing `-`.
- Must not equal a role name, `black`, `continue` or `cont`. A leading `_` is reserved.
- Unique within a deck. A deck-local card shadows a library entry of the same
  slug (recorded, informational).
- Cross-deck reuse is fine: the library is a lookup by slug.

### Placeholders

An unresolved slug always renders a placeholder — never silently nothing — and
the manifest records `status` and `reason`. Default: present view on, document
view off; `--show-placeholders` includes them in a document build (a handout
with placeholders is a draft, not a deliverable).

### Highest-N is a convenience, not an approval

The moment a card has a signed-off output, record `approved:`; it outranks the
attempts heuristic. Deleting or renaming attempt files is a last resort — it
damages the archaeology.

---

## Outputs

Three views, the presenter page, and two sidecars, all generated from the one
talkfile. `present/presenter.html` is a 1.x additive (2026-09-15): the frozen
1.0 table below stays exhaustive because the row is here, not appended elsewhere.

| Artifact | What it is | Why it exists |
|---|---|---|
| **present/** | the cinematic slides | the thing you speak from — full-bleed media, speaker notes, keyboard navigation, and a diagnostics dump (`i`) for bug reports |
| **present/presenter.html** | the speaker UI for the second window (`s`) | notes, the next cue and a preview of both screens, off the projection |
| **document/** | the handout (printable HTML, then PDF) | the talk as readable prose — the voice-over with figures and citations |
| **cues.json** | the structured form | the machine contract every tool reads (schema `animatic.cues.v1`) |
| **media-manifest.json** | the per-slug resolution audit | honesty about what resolved and what is still a placeholder |
| **nav.json** | cue id → line range, movement, kind | addressability — an agent told "insert after cue 17" seeks instead of counting |

### Determinism

Builds are deterministic — no timestamps, no set-iteration ordering —
byte-identical across runs. Required, because the golden suite depends on it.

### No personal paths

No emitted artifact may contain a machine-local absolute path. Paths in
emitted artifacts are relative to the deck, the out root, or the library file —
never absolute. A build that would leak a personal path is a defect, not a
warning.

### Addressable positions

Each cue carries `src_line`. An agent told "insert after cue 17" seeks instead
of counting shots.

---

## Verification

`animatic check` is the deterministic verifier: one command, one exit code.
Property assertions (not goldens):

```
no remote assets      no http(s):// in src/href/@import
video attributes      data-autoplay muted loop playsinline preload="none", no controls,
                      no bare autoplay (the pager plays the active slide's video and
                      warms the next 3; `m` lists all media and loads them)
                      (`playback: once` drops loop and carries data-playback="once";
                      `sound: true` drops muted and carries data-sound)
cue invariants        ids unique, ordinals 1..N, len(cues) == len(sections)
spoken lists          a list marked spoken has every item in the script
reading copy          the screen's text that follows the words is in the notes
determinism           build twice, compare hashes
theme completeness    every required token defined in each theme CSS
screen-text hygiene   no em-dashes in screen_text (public-copy rule)
placeholder policy    present on; document off; --show-placeholders overrides
```

Golden files byte-diff only the semantic layers — `cues.json` (the semantic
contract) and `media-manifest.json` (resolution order regresses silently). The
HTML views are deliberately not golden: CSS is inlined per deck and changes
with every feel-round, so a byte-diff would be re-blessed reflexively and
catch nothing. `--update-goldens` re-blesses.

---

## Error and warning taxonomy

**Fatal** — frontmatter never closed · bad YAML · unparseable shot · slug
equal to a role name · a heading that begins with `Movement`
(case-insensitive) but does not match `Movement <integer> [separator]
<title>` (the author intended structure; guessing wrong silently corrupts
screen boundaries).

**Warning** — unknown flag · a token matching no construct · flag value out of
range · unknown theme · possible receipt in parens · a nested `(` inside a
parenthetical · an attribution-shaped paragraph with no preceding quote ·
media unresolved · a card `playback:` or `sound:` that cannot apply as written · a card `steps:` or `handout:` that cannot apply · a stepped card and a `reveal=list` list of different lengths · a fenced block that never closes (check 35) · an empty fenced block (check 36) · a `[Timer: ...]` that is not a timer or a second one (check 37) · a timer over 3 hours (check 38) · a timer token in a spoken paragraph (check 39) · a `[notes]` block that repeats a list the notes already carry (check 42).

**Info** — `kb` on video · deck slug shadowing a library entry.

**Report** — attempt/gen-log drift · numbering gaps · licence-before-public-use
· corpus coverage. Reports print but never fail: a deck carrying archaeology is
not defective.

Warnings are non-fatal (a deck must always build) but must appear in the build
report, `cues.json warnings[]`, and the manifest. `--strict` makes warnings
fatal for pre-delivery checks.

**Every warning names the line that provoked it** — no warning text contains
"line 0". A warning exists to be acted on at thirty screens.

**Unknown vocabulary.** An unknown flag warns, never fails. An unknown tag does
not warn — tags only affect search, which degrades gracefully; flags affect
rendering, which does not. Nothing in a shot comment is silently dropped:
every token must be a slug, a role, a layout, or a known flag; any other token
warns. An unknown first token stays a slug and never warns at parse; when it
resolves to nothing, the placeholder reason carries the hint that the word is
neither a role nor a flag.

**Reserved.** A word that has ever been a valid slug in an authored deck must
not become a role, and vice versa. Before promoting any token, grep the corpus
for it as a slug.

---

## Media pipeline contract

`media/cards.yaml` — current state. `media/gen-log.md` — append-only
archaeology. `media/style.md` — inherited defaults. `_media/library.yaml` —
cross-talk reuse and third-party credits.

```yaml
# REQUIRED (builder reads; missing = error)
slug: <unique>          # matches the shot slug it serves
status: brief | to-find | file | url | prompting | candidate | shortlist | approved | rejected
type: image | video | chart | composite | audio | live

# OPTIONAL, builder-consumed
approved: <path>        # outranks the attempts heuristic
file: <path>            # then outputs[]
outputs: []
poster: <path>          # live only: the still the document view prints
live_group: <name>      # live only: hosts sharing one capture session
playback: loop | once | pingpong   # video only; default loop
sound: true | false     # video only; default false (muted)
steps: [slug, slug, ...]  # image only: frames the present view steps through (Media: Stepped images)
handout: last | first | <slug> | <n>   # with steps: the frame the handout prints (default: the card's own image, else the last frame)
alt / credit / licence / brief / prompts.{image,video}

# FREE — never read, never validated
style: {}   notes:  refs:  source:  keep:  surprise:  …any future key
```

**`type: live` (additive, 2026-09-15).** A live card declares no file: the
screen hosts a window capture the presenter starts in the browser
(`getDisplayMedia`), so the present view and the document view legitimately
differ, and the manifest records `source: live` with `file: null`. It still
counts as found — the screen is complete and never becomes a placeholder.
`poster:` is the one optional disk artifact, and it is the still the handout
prints, because a printed page cannot be live. A live screen takes no `kb` and
no `dim`: drift and a scrim both fight a moving picture. Full contract, and the
secure-context requirement that governs where a deck can be presented:
`docs/live-capture.md`.

**`playback:` (additive, 2026-09-22).** How a video plays while its screen
is up, and a property of the asset rather than the shot, so it lives on the
card. `loop` is the default and what every video did before the key existed.
`once` plays through and holds its last frame, and starts again from the top
on every arrival at the screen: for built animations, charts that draw
themselves, anything with an ending. `pingpong` plays forward then backward,
looping. Browsers cannot reliably play video backwards (negative
`playbackRate` is not supported everywhere, and scrubbing backwards through
H.264 stutters from keyframe to keyframe), so the builder bakes it: the
published file is `_media/<slug>-pingpong.mp4`, forward then reversed, with
the first frame of each leg dropped so neither the turn nor the loop seam
doubles a frame. The bake needs ffmpeg. It reverses a one-second chunk at a
time (ffmpeg's `reverse` filter would hold the whole clip in memory), so any
length of clip bakes in bounded memory, and it is cached by source hash so a
rebuild stays byte-identical. When it cannot bake, the screen plays the
original as `loop` and check 29 says why. An unknown value, or `playback:`
on a card that is not `type: video`, is also a check 29 warning; the build
is unchanged. The manifest carries `playback` only when it is not `loop`, so
existing goldens keep their shape.

**`sound:` (additive, 2026-09-28).** Slide videos play muted. `sound: true`
on a video card plays its audio track while the screen is up, and it
combines with any `playback:` (`once` + `sound` is a clip with an ending and
a soundtrack). Browsers only start audio after a user gesture; the pager's
`play()` runs inside the keypress that changed slide, which counts, so in
practice the one refusal is a deck opened directly on that screen. Then the
video plays muted rather than not at all. Presenter-view previews stay
muted stills. A non-boolean value, or `sound: true` on a card that is not
`type: video`, is a check 29 warning and the screen plays muted. The
manifest carries `sound` only when it is true.

**Shot overrides (additive, 2026-09-28).** The card's `playback:` and
`sound:` are the clip's defaults; a shot's `playback=`, `sound` and `silent`
flags override them for that screen alone (`<!-- shot: clip sound
playback=once -->`), so the same clip can play with its audio on one screen
and silently on another. The present view and the handout both honour the
override; the manifest audits the card and never shows it. On a pingpong
card the published file is the baked one, so `playback=once` plays there and
back once.

- **`status: file`** means a local media file is in hand — buildable now.
  **`status: url`** means a verified remote source is recorded but not yet
  fetched — the deck renders a placeholder until it is. **`status: approved`**
  asserts sign-off on the output file, not the card. Resolution is by file
  presence, never by status: a card may be `approved`, `file`, or `url` with no
  file on disk, and that renders a placeholder, not an error.
- **`type`** is required and never inferred; a missing `type` is an error. A
  card with no file renders a placeholder typed by its declared `type`.
- **Path rule.** All paths in `cards.yaml` are relative to the deck directory;
  all paths in `library.yaml` are relative to the library file's own directory.
  A card-declared path that resolves to no file is a warning.

Unknown keys are never an error at any level of the card.

`gen-log.md` is append-only; entries are never reordered, renumbered, or
edited. Minimum entry: `## <ISO date> · <slug> · a<N>` with `intent`, `delta`,
`verdict`, `keep`, `surprise`. Attempt numbers are per-slug and monotonic.

Checks 13/14 read every shape a log records attempts in, because an
append-only log cannot be rewritten into one shape afterwards:

- the per-take header above;
- a batch take line, `- a<N> ← `<file>` (slug <slug>, …)`, as `ingest.py`
  writes under its `## <date> · ingest · <n> file(s)` header;
- a take line under a bulk subheading, `### <slug> — <n> take(s)`;
- history, replayed in order: a rename `- <old>-a<N>.<ext> -> <new>-a<M>.<ext>`
  moves an attempt's record to its new name, and a split
  `- split: <old>-a<N> -> new slug `<new>`` moves it to the new slug's next
  number. The number a moved attempt leaves behind was used, so it is not a
  numbering gap.

A promote line (`… promoted to …`) names an attempt that already exists; it is
not a record of one.

---

## Timing

The clock: how long the talk runs, per cue and in total, checked against the
declared `dur`. Three provenance tiers, ordered by truth — `measured >
authored > estimated`.

- **`estimated`** — the builder's guess. Script word count ÷ `wpm` (default
  150, tunable in `timing.yaml`), floored per screen kind (black beat, beat
  screen, credits read; a video file's real duration is a hard floor). Emitted
  as `est_seconds` on each cue in `cues.json`.
- **`authored`** — a hand override in `timing.yaml` (deck-local sidecar,
  `animatic.timing.v1`): `cue_id → {seconds, provenance}`.
- **`measured`** — real timing from a recording or a test read: an STT
  transcript with word timestamps is aligned to the script, and each cue's
  measured duration is the gap between its aligned start and end timestamps.

Timing never lives in `talk.md` — it is a property of delivery, not of the
script. `animatic check` reports (never warns) when the effective total
diverges from `dur` by more than 30%.

---

## Remix

The remix unit is the **shot** — the screen its directive opens — falling back
to the movement. Movements are usually too coarse: wanting the Titanic lifeboat
beat does not mean wanting the whole movement.

Extraction carries the shot's slug (which resolves against the destination
deck) plus its card and the media file or library entry. A shot pasted without
its card renders placeholders by design and must still build — that is what
makes remixing safe.

Movement ordinals are presentation order and are not preserved across talks; a
pasted movement is renumbered by the author or agent.

---

## Stability

A conformant builder parses any `animatic-1.0` talkfile and produces the same
screens, cue ids, and media resolution this document describes; it refuses an
unknown major `format-version` rather than guessing. Everything in this
document is the frozen 1.0 contract; a breaking change requires a 2.0. The
only surface that may change within 1.x:

- the visual meaning of any flag;
- motion timings and amplitudes;
- theme token sets and the required-token list;
- present-view markup, pager, and CSS;
- the PDF driver;
- output file layout;
- cues.json fields beyond the invariants above;
- the CLI surface.
