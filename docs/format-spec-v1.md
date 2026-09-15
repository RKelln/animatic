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

Every piece of text in a talkfile is exactly one of three kinds:

| Kind | Spoken? | On screen? | In the handout? |
|---|---|---|---|
| **Voice-over** — a plain paragraph | yes | no | yes, as prose |
| **Screen text** — a role payload, heading, quote, or list after a shot | role-dependent | yes | yes, at its level |
| **Stage note** — a parenthetical `(…)` | no | no | no (speaker notes only) |

A line's fate is decided by two things, in order: its **markdown shape**, then
its **position**.

1. **Shape decides the default.** A paragraph is spoken. A heading, quote, or
   list is screen text — on screen, never spoken. A parenthetical is a stage
   note. This is the whole rule for headings, quotes, and lists: they are
   always screen text, with or without a role.
2. **Position overrides a paragraph's default.** A paragraph directly after a
   `role=` shot becomes that role's payload (on screen; `stat` is also spoken,
   `lower` and `credits` are not). A paragraph on a credits screen becomes a
   credits entry. A `~ ` paragraph directly under a quote becomes attribution.

So a role changes only the one paragraph that follows it. With no role,
paragraphs stay spoken and headings, quotes, and lists stay on screen. Four
outcomes are possible: spoken (voice-over), on screen (screen text), both
(`stat` reads the number it shows), or neither (a stage note). Voice-over is
spoken to the audience; speaker notes are private to the presenter — different
things.

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
| `<!-- shot: <flag> -->` | a card-only screen — no media, no role; the flags speak for it |

An unknown first token is a slug (it names media); a slug that resolves to
nothing surfaces honestly as a placeholder.

A shot directive may span multiple lines; interior whitespace is insignificant.

### Flags and layout

Flags are the per-shot knobs. The top-level namespace is fixed:

| Flag | Values | Meaning |
|---|---|---|
| `fit` | `cover` / `contain` / `hero` | how media fits the frame |
| `kb` | `in` / `out` | slow drift of the media layer inside a static lens |
| `dim` | `0`–`1` | a dark scrim at that opacity |
| `text` | `light` / `dark` | per-screen text treatment, overriding the theme default |
| `role` | a `roles.yaml` name | the screen's text role (see "Roles") |
| `layout` | a `layouts.yaml` name | the screen's config-driven layout |

**`fit` — explicit values only.** `fit=cover` fills the frame and crops
overflow (default for media). `fit=contain` shows the whole image, letterboxed
on the stage colour (default for charts and composites). `fit=hero` scales
on-screen text as large as the slide allows. A shot must not carry two `fit=`
values; a valueless `fit` is a warning with a did-you-mean hint.

**`layout=`** names an entry in `layouts.yaml`:

```yaml
layouts:
  piece: {description: "media floats as a framed object"}
  duo: {description: "object + text layout; implies piece"}
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

### Movements

A talk is divided into **movements** — its parts — marked by a heading:
`## Movement N · Title`.

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

### Roles

Roles are the kinds of on-screen text. They exist because a video essay is
text layered over media: some text is spoken (the number you read out), some
is a label that names the image, some is a credit that sits in the corner.
Roles let a script distinguish these with one word, and let the renderer treat
each kind the way it should.

The role vocabulary is config, not grammar. Three roles ship in `roles.yaml`;
`black` is built in:

| Role | Spoken? | On screen | Form |
|---|---|---|---|
| `stat` | yes | yes | callout — a big number the speaker reads |
| `lower` | no | yes | lower-third — a transient label naming the image |
| `credits` | no | yes | end-roll — persistent attribution |
| `black` | — | — | a deliberate black beat, no payload |

```yaml
# roles.yaml (shared default; a deck may override at deck/roles.yaml)
roles:
  stat: {spoken: true, form: callout}
  lower: {spoken: false, form: lower-third}
  credits: {spoken: false, form: end-roll}
```

A role is written with the `role=` flag:

```
<!-- shot: river-personhood role=credits -->
<!-- shot: letters dim=0.5 role=lower -->
```

**The vocabulary grows by yaml, never by grammar.** Add a `quote` entry to
`roles.yaml` with its `spoken` / `form`, and `role=quote` works
— no parser change. The four names above are the frozen starting set; the
mechanism is additive.

**The payload** is the paragraph that directly follows the role shot. It
becomes that role's screen text (for `stat`, it is also spoken — the speaker
reads the number). A role shot whose payload never arrives warns.

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

Attribution is the `~` form only: a paragraph beginning `~ ` whose immediately
preceding block is a quote. It is screen text (right-aligned under the quote),
never spoken, and travels with the quote. Same-line attribution (`> q ~ Name`)
is unsupported — the whole line renders as the quote. An attribution-shaped
paragraph anywhere else is spoken, with a warning.

### Directions (parentheticals)

Parentheses are never spoken and never on screen. Every parenthetical is
stripped identically and travels as a stage note (speaker notes in the present
view, `stage` in cues.json). Parentheticals do not nest — a nested `(` warns.

A prefix is an authorial convention, never behaviour:

| Prefix | Convention |
|---|---|
| `(Visual: …)` | brief for media generation |
| `(Beat.)` | timing / pause |
| `(Demo: …)` | live demo plan, speaker notes only |
| `(Flesh out: …)` | unwritten beat, speaker notes only |
| `(Note: …)` | note-to-self about the argument |

Recognising a prefix never changes what happens to the parenthetical — it
still strips and still travels.

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

### Resolution order (frozen)

1. deck `media/cards.yaml` — `approved:`, then `file:`, then `outputs[]`
2. deck `media/<slug>/attempts/<slug>-a<N>.<ext>` — highest N
3. deck `media/<slug>.<ext>`
4. shared `_media/library.yaml` (sibling of the deck dir)
5. `--media-remap` stand-in (deliberately last — real art always wins)
6. placeholder (a grey box carrying slug, status, and reason)

### Slug scope and uniqueness

- Charset `[a-z0-9-]`, 3–40 chars, no leading/trailing `-`.
- Must not equal a role name or `black`. A leading `_` is reserved.
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

Three views and two sidecars, all generated from the one talkfile.

| Artifact | What it is | Why it exists |
|---|---|---|
| **present/** | the cinematic slides | the thing you speak from — full-bleed media, speaker notes, keyboard navigation |
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
video attributes      autoplay muted loop playsinline, no controls
cue invariants        ids unique, ordinals 1..N, len(cues) == len(sections)
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
media unresolved.

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
