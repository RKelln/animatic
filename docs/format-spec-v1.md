# Animatic format spec — talkfile v1.0 (draft, 2026-09-07)

> **Status:** proposed normative rewrite. Supersedes `docs/format-spec.md` (v0.5,
> 2026-09-05) and folds in E3 supersessions from `docs/engine-decision.md` §6,
> the style grammar from `docs/tokens.md`, and the review additions of
> 2026-09-07. Nothing here is history; history lives in the decision logs.
> A decision is not landed until it is written here in the present tense; the
> logs record why, this spec records what.
>
> **Animatic is general-purpose**: it is a system for talks, lectures, and
> workshops. The TPL Applied AI residency (Oct–Dec 2026) is its first
> deployment, not its definition.

A talk is one plain-text file that reads like a **video-essay narration
script**. Spoken text is the default river; shots drop in where the image
changes; on-screen text is an explicit, rare, designed object. The handout is
the VO as prose, so a lecture can be pure image-and-few-words on screen.

The 5_directions failure was not the engine: every talk was a giant bespoke
file fusing argument, rendering directives, and media plumbing. This format
separates them.

---

## 0. Design principles (normative — rules are judged against these)

1. **One source, every output.** No output-specific authoring. If a fact must
   appear in two outputs, it is written once.
2. **The default river is speech.** Anything unmarked is spoken.
3. **No lookahead semantics.** A directive's meaning must be decidable from
   the directive itself and the content of its own screen. A directive MUST
   NOT change meaning based on blocks that appear after it. (Backward
   attachment is the river: a paragraph belongs to the screen open before it.
   That is the model, not a violation of it.)
4. **Non-directive comments are inert, always.** Any `<!-- -->` comment other
   than the `shot` directive this spec defines may be added, moved, or removed
   without changing any output. (Inertness is what makes provenance comments,
   append markers, and other tool conventions safe to edit mechanically.)
5. **File format and semantics are expensive; code is cheap.** Grammar changes
   cost human re-authoring. Rendering changes cost a rebuild. Bias the freeze
   toward the file.
6. **Agent-first, human-readable.** Every construct must be machine-addressable
   without being machine-only: an agent must be able to seek, extract, lint,
   and verify; Ryan must be able to edit the file at 11pm without a tool.

---

## 1. Conformance

A talkfile declares the format version it was written against (and, when
kept, the revision of its own content — §2):

```yaml
---
format-version: 1.0      # REQUIRED — the animatic format this file targets (§2)
content-version: 4       # RECOMMENDED — this talk's own content revision (§2)
---
```

- A builder MUST parse any `animatic-1.0` file and produce the same screen
  sequence, cue ids, and media resolution this spec describes.
- An `animatic-1.0` file MUST NOT require editing to build under any later
  1.x builder.
- Missing `format-version` ⇒ assume the current version, warn once (files
  written before the field existed still build).
- Unknown *major* `format-version` ⇒ refuse to build, do not guess.

### Frozen in 1.x (breaking change requires 2.0)

The shot comment and its regex · token position (a shot's first token is
its slug, its role, or — for flag-only shots — a known flag) · flag-only
shots · default-text-is-VO · parens never spoken · non-directive comments
inert · screen as the unit of screens and cues (the document view may omit
black beats; §3) · `## Movement N` as structure · extensionless slugs ·
media resolution order with stand-ins last · role payload VO rules ·
`~` attribution (the only attribution form) · cue-id format `<slug>-NNN` ·
tolerance rules (prose-before-shot fallback · inert `---` · dropped empty
screens · consecutive-shot warnings) · parentheticals strip identically,
with prefixes a Tier B registry (§5) · the card path rule (§11) · one
overlay per role per screen (§4).

### Unfrozen (may change in any 1.x)

The visual meaning of any flag · motion timings and amplitudes · theme token
sets and the required-token list · present-view markup, pager, and CSS · PDF
driver · output file layout · cues.json fields beyond the invariants in §8 ·
CLI surface.

---

## 2. Frontmatter

A talkfile is an **OKF concept document** — one markdown file with YAML
frontmatter, per the Open Knowledge Format. `type: Talk` declares the concept
kind; the fields below are animatic's typed extension on top of the OKF
shared fields (`title`, `description`, `timestamp`, `tags`).

```yaml
---
type: Talk                # OKF REQUIRED — this format defines one concept type
format-version: 1.0       # REQUIRED — the animatic format this file targets (§1)
content-version: 4        # RECOMMENDED — this talk's own content revision
slug: l01-opening         # REQUIRED; cue ids derive from its slugified form (§3.3)
title: "AI Everywhere, All At Once"   # REQUIRED (also the OKF title)
theme: lecture            # REQUIRED; unknown/TBD -> lecture + one warning
media: media              # OPTIONAL, default "media"
timestamp: 2026-09-08T14:30:00-04:00  # OKF recommended — ISO 8601, last meaningful change
session: "Talk with live demos"       # RECOMMENDED prose — what kind of session this is
logline: "..."            # RECOMMENDED: one sentence, the thesis
---
```

### OKF conformance

- **`type: Talk`, and only `Talk`.** A talk is a *flat* concept: the file
  itself is the output — script, shots, and on-screen text in one document —
  not a bundle header pointing at sub-concepts. A file with no `type:` builds
  and is treated as `Talk` (OKF: absence carries meaning but is never
  rejected); conformance is declared, not enforced.
- **Reserved filenames.** OKF reserves `index.md` and `log.md` at every tree
  level: a file with either name is read as a directory listing or an update
  log, never as a concept. A talkfile MUST NOT be named `index.md` or
  `log.md`.
- **Timestamps.** Every timestamp-valued key (`timestamp`, `generated.at`,
  `verified[].at`) is ISO 8601 with an explicit offset. `date` (the talk's
  delivery date) is ISO 8601 calendar form (`2026-09-05`). No other
  date/time forms.

### Version fields

`format-version` names the grammar the file was written against (§1): it
changes only when the format changes. `content-version` is the talk's own
revision — a monotonically increasing integer that the author or agent bumps
on any meaningful content change, never on cosmetic edits. Format and content
versions are independent axes, and derived artifacts that depend on content
state (recordings, `timing.yaml` overrides, goldens) MAY record the
`content-version` they were produced from. A talk drafted twenty minutes
before delivery is a valid talk: `date`, `venue`, `dur`, and `content-version`
are all optional, and missing ones MUST NOT fail a build.

### Slug and identity

`slug` is REQUIRED and is slugified at parse time: lowercased, every run of
characters outside `[a-z0-9]` collapsed to `-`. `L01-Opening` and
`l01-opening` are therefore the same deck. The slugified form is what cue ids
(§3.3), lookups, and deck paths use.

### Recommended, unenforced

`date`, `venue`, `dur`, `bank` (the content bank the talk composes from),
`status`, `description` (OKF), `tags` (OKF), `timestamp`, `session`,
`logline`. `session:` is prose — "Talk with live demos" — a description of
the session, never a machine field. Unknown keys pass through untouched and
are never an error.

`logline:` exists so `animatic search` across a dozen decks returns something
an author can scan. It is free to write and is the single highest-value
one-liner in the file.

### Receipts and provenance

Per-claim attribution is a body footnote `[^id]` placed at the claim site
(§5); the `sources:` registry those footnotes key into, plus the per-concept
`generated` / `verified` blocks saying who wrote the file and who confirmed
it, all live in frontmatter:

```yaml
sources:                  # per-claim receipts key here; id = footnote label (§5)
  prince-2026: "Cloudflare CEO Matthew Prince, June 3 2026"
generated: { by: agent, at: 2026-09-08T10:00:00-04:00 }
verified:                 # who confirmed the content against its sources
  - { by: human:ryan, at: 2026-09-09T18:00:00-04:00 }
```

- `sources:` is a flat map — `id: "one-line attribution"`. Ids are lowercase
  `[a-z0-9-]+`; a `[^id]` footnote with no registry entry is a warning.
- `generated:` and `verified:` are **per-concept** (whole talk), distinct from
  per-claim footnotes: `generated` says how the current content was produced,
  `verified` records who confirmed it against its sources. `by` follows the
  OKF actor convention (`human:<name>` for people, `<producer>/<version>` for
  agents).
- None of the three blocks is required for a build. `sources:` is the one the
  builder reads, and only for the entries a `[^id]` reference names — the
  handout citation list and `deck.sources` are built from referenced entries
  alone (§5); an unreferenced entry never surfaces in any view. `generated:`
  and `verified:` are never read by the builder.

---

## 3. Screens — the unit of everything

1. A **screen** opens when a `<!-- shot ... -->` directive appears and closes
   when the next shot or a movement boundary appears.
2. One screen ⇒ one present-view section and one cue. Screen and cue counts
   are identical, always. The document view MAY omit screens that carry no
   document content (black beats); when it does, `nav.json` records the
   omission. Document step count is therefore ≤ screen count, and that is the
   invariant.
3. Cue ids are `<slug>-NNN`: the slugified frontmatter `slug`, a hyphen, and
   the 1-based screen ordinal zero-padded to three digits. Ids are unique,
   sort lexically in presentation order up to 999 screens, and are stable for
   a given file. One cue id per present-view section.
4. `## Movement N · Title` is **structure, not a slide**. It closes the current
   screen and appears only in document view as a section header. Present view
   has no divider slides; to get one, put a `<!-- shot -->` before the header.
5. Paragraphs attach to the screen whose shot precedes them. A screen may
   therefore have no VO (a "beat screen"); that is the mechanical reading and
   is normative. See §12 open question (b).

### Identity boundary — no sub-screen ids

The screen is the smallest addressable unit. Nothing below it carries an id:
role overlays, text blocks, VO paragraphs, and media objects are addressed
positionally relative to the screen (cue ordinal, then position within the
screen). Content that needs its own address is promoted to a unit or to its
own screen — never given a sub-screen id.

### Flag-only shots and tolerance rules (frozen)

A shot whose first token is a **known flag** (not a slug, not a role) opens a
card-only screen: no media slug, no role — the flags speak for the screen
(`<!-- shot: fit=hero -->` is a hero text card). This is the flag-only
exception to the token-position rule.

The parser tolerates, without erroring, a small set of authoring shapes; each
is frozen as written:

- **Prose before the first shot** opens a shotless screen (a heading with no
  preceding shot starts a screen where it stands).
- **`---` horizontal rules are inert.** They may separate movements or
  screens; they never create or close anything.
- **A shot that opens a screen with no content by EOF is dropped** with a
  warning; an empty trailing screen never reaches any view.
- **Consecutive shots that do not merge** (the second is not a `+<role>`
  overlay) warn; the second opens a new screen, and the first, if it stayed
  empty, is dropped under the rule above.
- **A shot directive MAY span multiple lines**; interior whitespace is
  insignificant. A directive wrapped for readability (agents that wrap long
  shot lines, humans breaking them) parses exactly as the same tokens on one
  line — frozen with the multi-line-shot construct fixture (check 27) so a
  lexer rewrite cannot silently drop it.

### Beats and units

Speech does not respect shot boundaries, so the file also carries an optional
addressable layer:

```markdown
<!-- unit: bots-traffic tags=enclosure,bots variant=workshop -->
<!-- shot: bots-traffic fit=contain dim=0.5 -->
<!-- shot: stat -->
57.5% of web traffic is bots, not people.
```

A **unit** runs from its marker to the next `<!-- unit:`, `## Movement`, or
EOF. Fields:

| Field | Axis | Job | Required |
|---|---|---|---|
| `bots-traffic` | address | stable id; extraction boundary; cross-reference target | yes, if the marker is present |
| `tags=` | discovery | many-to-many, groups across decks | no |
| `variant=` | filtering | which builds include this unit | no |

- Units are **optional**. Unnamed screens stay addressable by cue ordinal.
- Unit ids MUST be unique within a deck. Two units with the same id is an error.
- A unit's meaning does not depend on what follows it (principle 3).
- Tags use the existing flag tokenizer (`FLAG_RE`), so commas are the only new
  surface. Tag vocabulary is **open** — no controlled list. See §10 for hygiene.
- `variant=` filtering is a build-time concept. A build MUST emit a manifest of
  included/excluded units so the deck's shape is visible before delivery.

**Why not headings:** a heading inside a shot is on-screen card text; using
H1–6 for units would make the same glyph mean two different things depending
on position — the exact defect being eliminated in `fit` below.

---

## 4. Text roles

| Construct | Spoken? | On screen | In handout |
|---|---|---|---|
| default paragraph | yes | no | yes, as prose |
| heading / quote / list after a shot | no | yes | yes, at its level |
| `~` attribution under a quote | no | yes (right-aligned) | with the quote |
| `stat` payload | **yes** (speaker reads the number) | yes | callout box |
| `lower` payload | no (attribution) | yes, transient | figcaption |
| `credits` payload | no | yes, persistent | figcaption |
| parenthetical `(...)` | no | no | no (stage only) |
| HTML comment | no | no | no (inert) |

### Attribution — `~` only, its own paragraph under the quote

Attribution is the `~` form only: a paragraph beginning `~ ` whose
immediately preceding block is a quote.  It is screen text (right-aligned
under the quote), never VO, and travels with the quote in the handout.
(`Source: ` was deleted in T03 — it is not a grammar form.)

- **Same-line attribution is unsupported.** `> The line. ~ Someone, 2026` is
  not split: the whole line renders as one quote, attribution and all.
  Attribution must be its own paragraph directly under the quote.
- **An attribution-shaped paragraph anywhere else is spoken, with a
  warning.** A `~ ` paragraph that does not directly follow a quote — and the
  deleted `Source: ` shape — falls through to VO (check 24: "attribution-looking
  line will be spoken").  The warning is the migration path: rewrite as `~ `
  under the quote, or make it ordinary prose.

### Roles (Tier A — frozen, additive-only, never reinterpreted)

- `stat` — big number. Payload is scripted.
- `lower` — transient overlay naming the image. Never script.
- `credits` — persistent attribution. Never script.
- `black` — deliberate black beat, full-stage silence, no payload.

To speak a credits line, place it as VO before the credits shot: credits
payloads are screen text, never script.

### Credits screens (end rolls)

A bare `credits` shot opens a credits screen — an end roll — that consumes
the blocks that follow it as screen entries until the next shot or movement
boundary.  It consumes exactly these kinds:

- a **paragraph** — one credits entry;
- a **list** — one credits entry per item;
- a **heading** — the roll's title.

A **quote is not consumed**: a quote on a credits screen stays a quote
object, never becomes a credits entry, and does not satisfy the credits
role.  A credits screen whose would-be payload is a quote fires the
never-consumed warning (§10) instead of silently absorbing the quote into
the roll.

### Overlay merge — `+<role>` is the only form

A role is attached to a screen by writing `+<role>` on the screen's shot:

```markdown
<!-- shot: river-personhood +credits -->
<!-- shot: letters dim=0.5 +lower -->
```

`+<role>` attaches the role unconditionally; the paragraph that follows the
shot is the role's payload.

There is no implicit merge. A bare role shot (`<!-- shot: credits -->`) always
opens its own screen — a standalone stat, lower, or credits screen — and a
bare role shot that directly follows another shot (the would-be implicit
merge) is a warning with a did-you-mean hint naming `+<role>`. The
merge-by-omission form is removed, not deprecated.

**One overlay per role per screen.** A screen may carry at most one `+stat`,
one `+lower`, one `+credits`. A second `+<role>` of the same role on the same
screen is a warning: rendering is tested only to one overlay per role, and an
unbounded stack is a slide trying to be three things.

---

## 5. Directions (parentheticals)

Parentheses are never spoken and never on screen. Every parenthetical — no
matter what it contains — is stripped identically and travels as a stage note
(speaker notes in present view, `stage` list in cues.json). That is the frozen
semantics: no prefix changes what happens to a parenthetical, and the parser
routes none of them anywhere.

**Parentheticals do not nest** (check 23).  A nested `(` inside a
parenthetical is a warning — the strip recognizes one level only, and
without the warning the nesting would corrupt the spoken text (the inner
pair wins and the outer markers vanish).  The author rewrites the
parenthetical flat.  Nothing in the registry below changes this: prefixes
are authorial conventions, never behaviour.

The prefix vocabulary below is a **Tier B registry, additive-only**: a set of
authorial conventions that tools MAY act on (linting, timing, card drafting),
listed for reference.  Recognising a prefix never changes the parenthetical's
rendering behaviour, and a new or unrecognised prefix changes nothing — it
still strips and still travels.

| Prefix | Meaning (convention) |
|---|---|
| `(Visual: …)` | human brief for media generation → tool MAY draft the card brief |
| `(Beat.)` | timing / pause → tool MAY use it in timing estimates |
| `(Demo: …)` | live demo plan; speaker notes only |
| `(Flesh out: …)` | unwritten beat; speaker notes only |
| `(Note: …)` | note-to-self about the argument; speaker notes only |

### Receipts — body footnotes keyed to `sources:`

A claim's source is a **body footnote reference** `[^id]` placed at the claim
site, keyed to the frontmatter `sources:` registry (registry anatomy: §2):

```markdown
57.5% of web traffic is bots, not people.[^prince-2026]
```

```yaml
sources:
  prince-2026: "Cloudflare CEO Matthew Prince, June 3 2026"
```

- The reference sits where the claim sits — positionality is the point: the
  source is attached to the sentence it documents, not gathered at the end.
- Footnote references are **inert**: stripped from every text block at parse
  — never spoken, never on screen, never verbatim in any view.  The parser
  collects each referenced id in first-appearance order.  The document view
  ends with a **Sources** list — the citation list — carrying every
  referenced registry entry in first-appearance order; cues.json mirrors the
  same payload verbatim under `deck.sources` (§8), so the frozen IR and the
  handout can never disagree about what a deck cites.
- A reference's definition is its `sources:` registry entry (§2): inert
  agent-facing metadata — never spoken, never on screen, never woven into
  the document's prose.  Its only output surface is the handout Sources list
  (whose data cues.json carries as `deck.sources`).  Receipts have no
  body-level definition form.
- A `[^id]` whose id has no `sources:` entry is a warning.
- Receipts are not comments and not parentheticals. A parenthetical matching
  a receipt pattern (`(✓ …)`, `(Source: …)`) is a **lint warning** naming the
  line ("possible receipt in parens — move to a footnote"). It still builds
  and still strips; the warning is the migration path.

---

## 6. Media: slugs and resolution

Shots reference **extensionless slugs**. Type and file format live in the card,
never in the script.

```markdown
<!-- shot: jungle-plantation kb=in dim=0.35 -->
(Visual: same trees twice; jungle left, plantation right.)
```

### Resolution order (frozen)

1. deck `media/cards.yaml` — `approved:` then `file:` then `outputs[]`
2. deck `media/<slug>/attempts/<slug>-a<N>.<ext>` — highest N
3. deck `media/<slug>.<ext>`
4. shared `_media/library.yaml` (sibling of the deck dir)
5. `--media-remap` stand-in (deliberately last — real art always wins)
6. placeholder (grey box carrying slug, status, and reason)

Stand-ins are last on purpose: a stand-in evaporates automatically the day real
art lands. The manifest records `source: standin` so the audit stays honest.

**Placeholder visibility.** Placeholders are the build's honesty: an
unresolved referenced slug always renders one — never silently nothing — and
the manifest records `status` and `reason` for every placeholder. Visibility
default: present view ON, document view OFF; `--show-placeholders` includes
them in a document build (a handout with placeholders is a draft, not a
deliverable).

The shared library's default home is `_media/` beside the deck dir. Content
roots are config-declared (`docs/shipping.md`), so that home is a convention
with an escape hatch, not a hardwired path; wherever the library file lives,
its own `file:` paths are relative to the library file's directory (§11).

### Slug scope and uniqueness

- Charset `[a-z0-9-]`, 3–40 chars, no leading/trailing `-`.
- MUST NOT equal a role name or `black`. Leading `_` is reserved.
- Unique within a deck. A deck-local card **shadows** a library entry of the
  same slug; the builder records `shadowed_library: true` (informational).
- Cross-deck collisions are not an error: the shared library is a lookup by
  slug, and two decks may reuse one entry by design.

### Highest-N is a convenience, not an approval

The moment a card has an output Ryan has signed off on, record it:

```yaml
approved: media/<slug>/attempts/<slug>-a2.mp4
```

`approved:` outranks the attempts heuristic. Deleting or renaming attempt files
is a last resort — it damages the archaeology.

---

## 7. Flags (Tier B — additive-only)

| Flag | Values | Meaning |
|---|---|---|
| `kb` | `in` \| `out` | slow drift of the media layer inside a static lens. Opposite starting phases, not speeds. Duration/amplitude are theme business and are NOT guaranteed across versions. Ignored on video (info note). Disabled under reduced-motion. |
| `dim` | `0`–`1` | solid `--stage-dim` scrim at that opacity |
| `fit` | `cover` \| `contain` \| `hero` | see below |
| `piece` | — | media floats as a framed object (border + shadow on the image itself, never a container box) |
| `duo` | — \| `left` | object + text layout |
| `text` | `light` \| `dark` | per-screen text treatment; overrides theme default |

### `fit` — explicit values only

- `fit=cover` — fill the frame, crop overflow. Default for media.
- `fit=contain` — show the whole image, letterboxed on the stage colour.
  **Default for `type: chart` and `type: composite` cards.**
- `fit=hero` — on-screen text scales as large as the slide allows.

A shot MUST NOT carry two `fit=` values, and a valueless `fit` has no meaning
of its own: it is a warning with a did-you-mean hint naming the three values.
(The historic bare `fit` took its meaning from what followed the shot —
"contain" on media, "hero" once text appeared. That lookahead is removed with
the bare form.)

### `text=` default

Themes MUST declare `--stage-over-media-ink-default` (absent from the required
token set today). A screen relying on contrast over media SHOULD set `text=`
explicitly; the same deck built under two themes without `text=` may
legitimately look different.

### Flag interactions (frozen)

| Combination | Behaviour |
|---|---|
| `piece` + `dim` | `dim` is ignored on a piece — a full-zone scrim behind a framed object would paint a box around it. Info note. |
| `duo` (any value) | implies `piece`: the media renders as a framed object on the object side even when `piece` is not written. |
| `kb` + `piece` | drift is not applied — the camera lens wraps full-bleed media only; a framed object has no lens. Info note. |
| slide-level flags on a role shot | slide-level flags (`fit`, `duo`, `text=`) are read from the screen's FIRST shot only; the same flags on a merged `+<role>` shot are ignored. Info note. |

Media flags (`kb`, `dim`, `fit`) are read from the screen's media shot; on
every ordinary screen that is also the first shot, so the two reads agree.

---

## 8. Outputs

| Artifact | Schema | Invariants |
|---|---|---|
| `cues.json` | `animatic.cues.v1` | flat ordered array; one entry per screen; `id`, `ordinal`, `script`; ids unique; ordinals 1..N; 1:1 with present sections; `deck.sources` carries the handout citation list — every referenced receipt id (first-appearance order) plus its registry value (§5) |
| `media-manifest.json` | `animatic.media.v1` | per-slug `found`/`source`/`file`/`status`/`reason`; lists unreferenced cards |
| `nav.json` / `nav.md` | `animatic.nav.v1` | unit + cue id → line range, movement, kind, tags, variant, first words |

**`nav.*` is generated, never embedded in the talkfile.** An embedded nav block
in a file being actively rewritten goes stale and stops being trusted; the
builder already tracks lines on `Screen` and `Block`, so it emits the map as a
sidecar. Zero maintenance, and it knows about shots, roles, and slugs — strictly
more than a heading-derived map can.

### Determinism

Builds are deterministic: no timestamps, no set-iteration ordering, byte-identical
output across runs. Required, because the golden suite (§9) depends on it.

### No personal paths

No emitted artifact — `cues.json`, `media-manifest.json`, `nav.*`, or the
HTML views — may contain a machine-local absolute path (build host, user
home, mount point). Paths in emitted artifacts are relative: to the deck, the
out root, or the library file — never absolute. A build that would leak a
personal path is a defect, not a warning.

### Addressable positions

Each cue carries `src_line`. An agent told "insert after cue 17" seeks
instead of counting shots.

---

## 9. Verification (`animatic check`)

Deterministic checks. Agent-first: one command, one exit code.

**Property assertions (not goldens):**

```
no remote assets      no http(s):// in src/href/@import   (the reveal.js failure)
first slide active    slide 1 carries class="active" server-side
video attributes      autoplay muted loop playsinline, no controls
cue invariants        ids unique, ordinals 1..N, len(cues) == len(sections)
determinism           build twice, compare hashes
theme completeness    every required token defined in each theme CSS
screen-text hygiene   no em-dashes in screen_text (public-copy rule)
placeholder policy    present ON; document OFF; --show-placeholders overrides
```

**Golden files (byte-diff only on the semantic layers):**

| Layer | Golden? | Why |
|---|---|---|
| `cues.json` | yes | the semantic contract — what breaks decks |
| `media-manifest.json` | yes | resolution order regresses silently |
| `document/index.html` | no | style churn |
| `present/index.html` | no | highest churn rate in the system |

You tune in small dials (plate alpha, max-width), and CSS is inlined per deck
at build time — a byte-diff on HTML invalidates on every feel-round and would
be re-blessed reflexively within a week, after which it catches nothing.

**Layout:**

```
tests/
  fixtures/constructs/*.talk.md      one minimal file PER construct
  fixtures/decks/roles-demo/
  fixtures/decks/l01/                pins its --media-remap
  expected/.../{cues,media-manifest}.json
  properties/
  run.py                             build all -> diff -> assert -> exit 0/1
```

`--update-goldens` re-blesses. Construct-per-fixture matters more than
deck-per-fixture as the format grows: a new flag gets one tiny file, and a
regression names it.

---

## 10. Error / warning taxonomy

**Fatal** — frontmatter never closed · bad YAML · unparseable shot · duplicate
unit id · slug equal to a role name · an H2 whose text begins with `Movement`
(case-insensitive) that fails the movement pattern (check 22 — the author
intended structure; guessing wrong silently corrupts screen boundaries and
both views).

**Warning** — unknown flag name · a shot token matching no construct · a
`+<role>` naming a role outside the §4 set · flag value out of range · unknown
theme · possible receipt in parens · a nested `(` inside a parenthetical
(check 23 — "parentheticals do not nest", §5) · an attribution-shaped
paragraph with no preceding quote (check 24 — "attribution-looking line will
be spoken", §4) · media unresolved.

**Info** — `kb` on video · deck slug shadowing a library entry.

Warnings are non-fatal (a deck must always build) but MUST appear in the build
report, `cues.json warnings[]`, and the manifest. `--strict` makes warnings
fatal for pre-delivery checks.

**Every warning names the line that provoked it (check 26): no warning text
contains `line 0`.** A warning exists to be acted on at 30+ screens; the
parser threads each shot directive's source line into the shot at parse time
(the consecutive-shot, empty-screen, role-payload, and tokenizer warnings all
carry a real line).

### Unknown vocabulary

- Unknown flag ⇒ warn, never fail.
- Unknown **tag** ⇒ do not warn. Tags only affect search, which degrades
  gracefully; flags affect rendering, which does not. Different blast radius.
- **A shot's tokenizer is honest (check 25): nothing in a shot comment is
  silently dropped.** Every token must be a slug (first position only), a
  role, a `+<role>` overlay, or a known flag; any other token warns (see the
  warning list above) and is not applied.
- **Unknown first token** stays a slug (token-position rule, §1) and never
  warns at parse — the default reading of an unrecognized first token is
  media. When such a slug is cardless and resolves to nothing, the
  placeholder reason carries the hint "if 'X' was meant as a role or flag, it
  is neither" — added only for single-word slugs, the only shape that could
  have been a role or flag (§6, §8).
- **Reserved:** a word that has ever been a valid slug in an authored deck MUST
  NOT become a role, and vice versa. Before promoting any Tier B token to Tier
  A, grep the corpus for it as a slug.

### Tag hygiene (reports, never build warnings)

1. **Drift** — `animatic tags` prints every tag with counts; near-miss pairs by
   edit distance and singletons are surfaced. Catches `#enclosive` beside
   `#enclosure`.
2. **Coverage** — untagged units, with suggested tags derived from VO text. The
   agent proposes; Ryan confirms. Suggest-only, never auto-applied.

Untagged units are a **report, not a diagnostic**. "Unit 17 is untagged" as a
build warning trains you to ignore warnings, and the real ones (unknown flag,
unresolved media) matter.

---

## 11. Media pipeline contract

`media/cards.yaml` — current state. `media/gen-log.md` — append-only
archaeology. `media/style.md` — inherited defaults. Shared
`_media/library.yaml` — cross-talk reuse + third-party credits.

```yaml
# REQUIRED (builder reads; missing = error)
slug: <unique>          # slugified form (§2); matches the shot slug it serves
status: brief | to-find | have | prompting | candidate | shortlist | approved | rejected
type: image | video | chart | composite | audio    # Tier B, additive

# OPTIONAL, builder-consumed
approved: <path>        # outranks the attempts heuristic
file: <path>            # then outputs[]
outputs: []
alt / credit / licence / brief / prompts.{image,video}

# FREE / agent-facing — never read, never validated
style: {}   notes:  refs:  source:  keep:  surprise:  ...any future key
```

Unknown keys are never an error at any level of the card.

**Path rule (frozen).** All paths in `cards.yaml` are relative to the deck
directory (the directory containing the talkfile); all paths in
`library.yaml` are relative to the library file's own directory. A
card-declared path that resolves to no file is a warning naming the card and
path — §6 resolves by this rule.

`type` is REQUIRED at the builder level; a missing `type` is an error, never
inferred. A card with no file at all renders a placeholder typed by its
declared `type`.

`status: have` means the file is already in hand — nothing to find and nothing
to generate. Shared-library entries are `have`; a deck card becomes `have`
when media is supplied rather than produced. `status: approved` asserts
sign-off on the **output file**, not on the card. Resolution is by file
presence, never by status: a card may be `approved` or `have` with no file —
that renders a placeholder and is not an error.

`gen-log.md` is append-only; entries are never reordered, renumbered, or edited.
Minimum entry: `## <ISO date> · <slug> · a<N>` with `intent`, `delta`,
`verdict`, `keep`, `surprise`. `keep`/`surprise` SHOULD be present even when
empty (write `—`); they are the mining surface. Attempt numbers are per-slug
and monotonic. The starter template (`templates/gen-log.md`) documents the
fuller SHOULD-level anatomy (prompt text, engine and params, output refs)
that deck logs add on top of this minimum; the minimum here is the contract.

---

## 12. Open questions (human calls — not decided here)

(a) **Is the closing credits line spoken?** L01's last screen is a promise to
    the audience and is currently screen-only.
(b) **Beat screens** — screens with no VO are common in the WIP corpus. If a
    second deck lands near 30%, the "paragraphs belong to the preceding
    screen" default is wrong and deserves either a flip or an explicit "VO
    continues across this shot" marker. Decide on two data points, not one.
(c) **Stat parentheticals on screen** — `(~$20.8 trillion.)`. Speaker sees it;
    audience and handout don't. The handout probably should carry it; the slide
    probably shouldn't. Splitting them weakens the parens rule.
(d) **Unit marker word** — `unit:` vs `phrase:` (`beat:` is out: `(Beat.)`
    already means pause).
(e) **Duo object side** — object-right only is tested; book covers may read
    better object-left.

Resolved in this draft and moved to normative text (2026-09-08): version
field name → `format-version` + `content-version` (§1/§2); placeholder
visibility → present ON, document OFF, `--show-placeholders` (§6/§9); third
theme slot → deleted (`tokens.md`, D9). The letters were renumbered when the
resolved items left this list.

---

## 13. Remix

The remix unit is the **unit** (§3), falling back to the movement. Movements
are usually too coarse: wanting the Titanic lifeboat beat does not mean
wanting the whole movement.

Extraction carries: the shot slugs (which resolve per the destination deck) +
the cards for those slugs + the media files or a library entry. A unit pasted
without its cards renders placeholders **by design** and must still build —
that is what makes remixing safe.

Movement ordinals are presentation order and are not preserved across talks;
a pasted movement is renumbered by the author or agent.

---

## Changelog

| Version | Date | Change | Compat impact |
|---|---|---|---|
| 1.0 (draft) | 2026-09-08 | Handout citation list (receipt emission, closes the T06 gap): the document view ends with a **Sources** list rendering every referenced `sources:` registry entry in first-appearance order, and cues.json carries the same payload as `deck.sources` — the §5 promise ("the handout renders a citation list") becomes literally true in code. §5 names the emission shape; §2 stops claiming the builder never reads `sources:` (it reads referenced entries only; `generated:`/`verified:` are still never read); §8 pins `deck.sources` on the cues.json row. Registry values are plain text, escaped, never markdown; a referenced id with no registry entry stays out of the list until its parse warning (check 28, T08) lands | none for decks without receipts — roles-demo's structure is byte-identical outside the inlined stylesheet and its cues.json merely gains an empty `deck.sources` (CSS is inlined into every deck at build, so the new .sources rules travel into all HTML); L01 additionally gains the Sources section in the document view and 15 `deck.sources` entries — no cue, script, screen, or present-view change |
| 1.0 (draft) | 2026-09-08 | Parser edge cases (T06): §5 states parentheticals do not nest — a nested `(` warns (check 23); §4 pins attribution to `~ ` on its own paragraph directly under the quote — same-line `> q ~ Name` is unsupported, the deleted `Source: ` shape is not consumed, and an attribution-shaped paragraph anywhere else is spoken with a warning (check 24); §4 lists exactly what a credits screen consumes (paragraph, list, heading — a quote is not consumed and never satisfies the credits role, so a would-be quote payload fires the never-consumed warning); footnote refs `[^id]` are stripped from every text block at parse and each referenced id is collected for the handout citation list, registry definitions staying inert metadata | none — warnings and clarifications; neither corpus file uses any warned shape; L01's `[^id]` markers leave scripts and screen text (the T03-promised strip lands) with screen/cue counts unchanged |
| 1.0 (draft) | 2026-09-08 | Parser hardening (T05): §10 adds the check-22 fatal — an H2 beginning with `Movement` (case-insensitive) that fails the movement pattern is never silently treated as screen text; warning taxonomy gains the check-25 honesty rule — unknown flag names, `+<role>` outside the §4 set, and tokens matching no construct warn, nothing in a shot comment is silently dropped; unknown first tokens stay slugs and their cardless placeholders carry the "meant as a role or flag?" hint (§6/§8); the `+<role>` tokenizer lands (canonical `slug +<role>` and `+<role>`-only directives, §3/§4); valueless-`fit` and bare-consecutive-role did-you-mean warnings land (D7); movement recognition is case-insensitive (recognition-rule shape, not typography) | none — the parser implements what §3/§4/§7 already promised; the corpus was pre-migrated (T03); roles-demo's flag-only bare `fit` becomes `fit=hero` in the same change |
| 1.0 (draft) | 2026-09-08 | Hygiene (T04): OKF frontmatter rewrite (§2 — `type: Talk`, ISO 8601 timestamps, `index.md`/`log.md` reserved); `format-version` + `content-version` replace the `grammar:` proposal (D1) and prose `format:` becomes `session:`; `sources:` registry anatomy + per-concept `generated`/`verified`; §5 prefix semantics frozen — all parentheticals strip identically, prefixes are a Tier B registry (additive-only); §11 adds `have` (D3), freezes the card path rule, restates the `type`-required posture (missing = error, never inferred), states the slugified-form rule; overlay stacking limited to one per role per screen (D5); placeholder visibility default present ON / document OFF / `--show-placeholders` (D10); §14 moved to `docs/shipping.md`, no-personal-paths kept as a §8 output invariant; open questions (a)/(e)/(f) resolved and the list renumbered; dead-layer sweep — `tokens.md` engine row + spare theme slot removed (D9), stale `docs/format-spec.md` marked superseded | none — additive or clarifications; renamed/removed frontmatter keys pass through as unknown keys; corpus frontmatter (type/session/version) catches up at freeze |
| 1.0 (draft) | 2026-09-08 | Defect removal (T03): principles 3/4 rewritten (no lookahead semantics; non-directive comments inert); bare `fit`, implicit overlay merge, and `Source: ` attribution deleted — explicit forms only (`fit=cover|contain|hero`, `+<role>`, `~`); receipts become `[^id]` body footnotes keyed to a frontmatter `sources:` registry; identity boundary (no sub-screen ids); document view MAY omit black beats (`nav.json` records); cue-id format `<slug>-NNN`; flag-only shots + tolerance rules frozen; flag interaction table added | breaking for the removed forms — the two corpus files (L01, roles-demo) were rewritten to the explicit forms in the same change; engine-decision §8 |
| 1.0 (draft) | 2026-09-07 | Folded E3 (pager, theme layer, role overlays, remaps) into normative text; added conformance, design principles, error taxonomy, verification, units/tags/variant, generated nav sidecar | none — existing decks unchanged; all additions optional |
| 0.5 | 2026-09-05 | Canonical home moved; grammar section left at v0.3 (defect) | — |
