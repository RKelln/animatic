# Animatic format spec — talkfile v1.0 (draft, 2026-09-07)

> **Status:** proposed normative rewrite. Supersedes `docs/format-spec.md` (v0.5,
> 2026-09-05) and folds in E3 supersessions from `docs/engine-decision.md` §6,
> the style grammar from `docs/tokens.md`, and the review additions of
> 2026-09-07. Nothing here is history; history lives in the decision logs.
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

A talkfile declares the grammar it was written against:

```yaml
---
grammar: animatic-1.0
---
```

> **Naming note (TBD, human call):** `format:` is already used for a prose
> session description (`format: Talk with live demos`). `grammar:` is proposed
> because no existing deck uses it and it is unambiguous to an agent reading
> frontmatter. Alternatives: rename the prose field to `session:` and take
> `format:`; or use `talkfile: 1.0`.

- A builder MUST parse any `animatic-1.0` file and produce the same screen
  sequence, cue ids, and media resolution this spec describes.
- An `animatic-1.0` file MUST NOT require editing to build under any later
  1.x builder.
- Missing `grammar:` ⇒ assume current version, warn once. (L01 predates it.)
- Unknown *major* version ⇒ refuse to build, do not guess.

### Frozen in 1.x (breaking change requires 2.0)

The shot comment and its regex · token position (a shot's first token is
its slug, its role, or — for flag-only shots — a known flag) · flag-only
shots · default-text-is-VO · parens never spoken · non-directive comments
inert · screen as the unit of screens and cues (the document view may omit
black beats; §3) · `## Movement N` as structure · extensionless slugs ·
media resolution order with stand-ins last · role payload VO rules ·
`~` attribution (the only attribution form) · cue-id format `<slug>-NNN` ·
tolerance rules (prose-before-shot fallback · inert `---` · dropped empty
screens · consecutive-shot warnings).

### Unfrozen (may change in any 1.x)

The visual meaning of any flag · motion timings and amplitudes · theme token
sets and the required-token list · present-view markup, pager, and CSS · PDF
driver · output file layout · cues.json fields beyond the invariants in §8 ·
CLI surface.

---

## 2. Frontmatter

```yaml
---
grammar: animatic-1.0     # REQUIRED (see §1)
slug: l01-opening         # REQUIRED; cue ids derive from it
title: "AI Everywhere, All At Once"   # REQUIRED
theme: lecture            # REQUIRED; unknown/TBD -> lecture + one warning
media: media              # OPTIONAL, default "media"
logline: "..."            # RECOMMENDED: one sentence, the thesis
---
```

Recommended, unenforced: `date`, `venue`, `dur`, `bank`, `status`, `description`,
`format` (prose session type).

Unknown keys pass through untouched and are never an error. Missing
`date`/`venue`/`dur` MUST NOT fail a build — a talk drafted twenty minutes
before delivery is a valid talk.

`logline:` exists so `animatic search` across a dozen decks returns something
an author can scan. It is free to write and is the single highest-value
one-liner in the file.

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
   is normative. See §12 open question (c).

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

### Roles (Tier A — frozen, additive-only, never reinterpreted)

- `stat` — big number. Payload is scripted.
- `lower` — transient overlay naming the image. Never script.
- `credits` — persistent attribution. Never script.
- `black` — deliberate black beat, full-stage silence, no payload.

To speak a credits line, place it as VO before the credits shot: credits
payloads are screen text, never script.

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
merge) is a warning with a did-you-mean hint naming `+<role>`. The historic
merge-by-omission is removed, not deprecated: nothing shipped on it, and the
corpus was rewritten to the explicit form (engine-decision §8).

---

## 5. Directions (parentheticals)

Parentheses are never spoken and never on screen. They travel as stage notes
(speaker notes in present view, `stage` list in cues.json).

Recognised prefixes, all stripped from VO, captions, and the handout:

| Prefix | Meaning |
|---|---|
| `(Visual: …)` | human brief for media generation → card brief |
| `(Beat.)` | timing / pause |
| `(Demo: …)` | live demo plan |
| `(Flesh out: …)` | unwritten beat; reaches speaker notes only |
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
- Footnote references are **inert**: never spoken, never on screen. The
  handout renders a citation list of every referenced registry entry.
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
(The historic bare `fit` meant "contain" on media and "hero" once text
appeared — meaning decided by what followed the shot. That lookahead is gone;
engine-decision §8.)

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
| `cues.json` | `animatic.cues.v1` | flat ordered array; one entry per screen; `id`, `ordinal`, `script`; ids unique; ordinals 1..N; 1:1 with present sections |
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
placeholder policy    present shows them; document does not
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
unit id · slug equal to a role name.

**Warning** — unknown flag · unknown role-like token in first position (never
silent coercion) · flag value out of range · unknown theme · possible receipt
in parens · media unresolved.

**Info** — `kb` on video · deck slug shadowing a library entry.

Warnings are non-fatal (a deck must always build) but MUST appear in the build
report, `cues.json warnings[]`, and the manifest. `--strict` makes warnings
fatal for pre-delivery checks.

### Unknown vocabulary

- Unknown flag ⇒ warn, never fail.
- Unknown **tag** ⇒ do not warn. Tags only affect search, which degrades
  gracefully; flags affect rendering, which does not. Different blast radius.
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
slug: <unique>
status: brief | to-find | prompting | candidate | shortlist | approved | rejected
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

`status: approved` asserts sign-off on the **output file**, not on the card.
Resolution is by file presence, never by status. A card may be `approved` with
no file — that renders a placeholder and is not an error.

`gen-log.md` is append-only; entries are never reordered, renumbered, or edited.
Minimum entry: `## <ISO date> · <slug> · a<N>` with `intent`, `delta`,
`verdict`, `keep`, `surprise`. `keep`/`surprise` SHOULD be present even when
empty (write `—`); they are the mining surface. Attempt numbers are per-slug
and monotonic.

---

## 12. Open questions (human calls — not decided here)

(a) **Version field name** — `grammar:` vs `format:` vs `talkfile:`.
(b) **Is the closing credits line spoken?** L01's last screen is a promise to
    the audience and is currently screen-only.
(c) **Beat screens** — screens with no VO are common in the WIP corpus. If a
    second deck lands near 30%, the "paragraphs belong to the preceding
    screen" default is wrong and deserves either a flip or an explicit "VO
    continues across this shot" marker. Decide on two data points, not one.
(d) **Stat parentheticals on screen** — `(~$20.8 trillion.)`. Speaker sees it;
    audience and handout don't. The handout probably should carry it; the slide
    probably shouldn't. Splitting them weakens the parens rule.
(e) **Placeholder visibility in the public handout** — recommend present ON,
    document OFF, `--show-placeholders` to override.
(f) **Third theme slot** — `tokens.md` holds an empty "spare." Real plan or
    carried placeholder? An empty slot in a spec invites an agent to invent one.
(g) **Unit marker word** — `unit:` vs `phrase:` (`beat:` is out: `(Beat.)`
    already means pause).
(h) **Duo object side** — object-right only is tested; book covers may read
    better object-left.

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

## 14. Shipping as skills (general-purpose)

Animatic ships with agent skills (copies of what we run ourselves). Consequences
for the spec:

- **No personal paths.** The v0.5 spec points at
  `~/talks/decks/README.md`; every personal path
  and the Tailscale IP, fal.ai, and steamy references in the pipeline skill must
  move to config before shipping.
- **Three skills:** author · media · build.
- **Content roots** are declared in config, so `animatic search` spans the
  research wiki, banks, and decks instead of depending on the agent knowing
  where things live.
- **Theme validation becomes load-bearing.** A third party writes a theme and
  nothing currently verifies they defined every required token. That is a
  property assertion in §9.
- **`animatic check` is the install verification** and the contract any agent
  refactor is judged against.

---

## Changelog

| Version | Date | Change | Compat impact |
|---|---|---|---|
| 1.0 (draft) | 2026-09-08 | Defect removal (T03): principles 3/4 rewritten (no lookahead semantics; non-directive comments inert); bare `fit`, implicit overlay merge, and `Source: ` attribution deleted — explicit forms only (`fit=cover|contain|hero`, `+<role>`, `~`); receipts become `[^id]` body footnotes keyed to a frontmatter `sources:` registry; identity boundary (no sub-screen ids); document view MAY omit black beats (`nav.json` records); cue-id format `<slug>-NNN`; flag-only shots + tolerance rules frozen; flag interaction table added | breaking for the removed forms — the two corpus files (L01, roles-demo) were rewritten to the explicit forms in the same change; engine-decision §8 |
| 1.0 (draft) | 2026-09-07 | Folded E3 (pager, theme layer, role overlays, remaps) into normative text; added conformance, design principles, error taxonomy, verification, units/tags/variant, generated nav sidecar | none — existing decks unchanged; all additions optional |
| 0.5 | 2026-09-05 | Canonical home moved; grammar section left at v0.3 (defect) | — |
