# tests/ — the golden + property suite (T10)

One command, one exit code:

    python3 tests/run.py                  # build all -> diff -> assert -> exit 0/1
    python3 tests/run.py --update-goldens # re-bless expected/ (only after the
                                          # change is understood and intended)
    python3 tests/run.py --only cue       # one fixture subtree, for debugging
    python3 tests/run.py --verbose        # echo builder output

## Layers (spec §9)

- `fixtures/constructs/*.talk.md` — one minimal synthetic file per frozen
  construct or register rule. Constructs are media-free or placeholder-only
  (see the media pool below); the composite decks own real resolution.
  `multiline-shot.talk.md` is the T07 construct fixture (register check 27),
  committed before this suite and included unchanged except status quoting.
  `cue-id-space.talk.md` is generated (103 one-card screens) and pins the
  three-digit cue-id space past the 99 cliff (register check 18).
  `soft-wrap.talk.md` pins merged line spans — a soft-wrapped paragraph, a
  two-line quote, a two-line list — the spans `nav.json` ranges are built
  from (a range that stops at a block's first line leaves body lines
  belonging to no screen; T13).
  `timing-drift.talk.md` declares `dur: 45 min` on a two-screen deck: the
  clock (check 19) must report the divergence and the deck must still build
  (spec: Timing; T15).
- `fixtures/constructs/media/cards.yaml` — the construct-corpus media pool.
  Flat constructs share one deck dir, hence one pool: every media slug any
  construct references must be carded here (check 11 silence). Pool cards
  are `status: brief` with no declared paths, so construct slugs always
  render placeholders whose reasons carry no machine-local path. Add a row
  when a new construct introduces a slug; never delete one in use.
- `fixtures/decks/<deck>/talk.md` — composite golden decks with their own
  media dirs:
  - `flow-demo` — movements, prose-before-shot opening, media + stat/lower
    overlays, quote + tilde attribution, a content-less beat screen, a
    flag-only hero card, credits end roll, a closing black beat, and
    footnote receipts; two deck-dir media files and one brief placeholder.
  - `media-resolution` — one slug per resolution stage (spec §6): cards
    approved path, deck media dir, attempts highest-N, shared library, remap
    stand-in, placeholder. A sibling `remaps.yaml` gives the deck a second
    build profile (`standin`) whose goldens live in
    `expected/decks/media-resolution/standin/`. The remap decoys prove real
    art beats a stand-in: only `standin-only` changes between profiles.
  - `decks/_media/library.yaml` — the shared library home for deck
    fixtures (sibling of each deck dir, per spec §11).
  - `timing-demo` (T15) — the clock end to end: `dur: ~1 min` sits inside the
    report threshold only because the deck-local `timing.yaml` applies an
    `authored` override (9.0 s) and a `measured` value (14.5 s) over the
    estimates; `settings.wpm: 175` proves the sidecar's speech rate is read.
    Media-free, so the fixture stays about timing; the video hard floor is
    pinned by `timing_props` against a generated clip.
- `expected/<...>/{cues,media-manifest}.json` — byte goldens for the two
  semantic layers only. HTML is never byte-diffed (spec §9: highest churn
  layer); the views are property-checked instead. `nav.json` is generated per
  build like the others but carries no golden: the spec's Verification section
  names two golden layers, so nav rides the determinism tree hash (byte-stable
  across builds) with `nav_props` pinning its semantics.
- `properties/` — structural invariants, run against every fixture profile
  and independent of the goldens:
  - `cue_props` — id shape `<slug>-NNN`, ordinals 1..N, lexical == ordinal,
    movement partitions mirror `cue_ids`, `deck.sources` equals a fresh
    derivation from the source text (receipts never go stale), parens and
    footnote markers never reach script/screen text, no em dashes in screen
    text (public-copy hygiene), no machine-local paths anywhere.
  - `manifest_props` — referenced slugs mirror the cues' slug shots
    first-appearance order and `first_cue`; found media is published under
    `out/_media/<slug>.<ext>`; placeholders always carry a reason; source
    values stay in {cards, deckdir, library, standin, none};
    `unreferenced_cards` equals cards.yaml minus what the deck used.
  - `html_props` — present sections mirror cues 1:1 (id, order,
    data-movement), first slide is active server-side, notes asides exist,
    media renders found-vs-placeholder exactly as the manifest says,
    black-beat sections carry the class; the presenter page exists for every
    deck with no remote asset or machine-local path, its build-time cue index
    mirrors cues.json cue for cue (ordinal, movement, label, kind, title, and
    the live flag that makes a live screen preview-less), and the deck carries
    the moved `n` notes binding plus the `s` presenter target and its status
    line; the document's movement sections,
    Sources list, figures, and opening section must match cues.json; no
    remote assets or machine-local paths in any view.
  - `nav_props` — the addressability map (T13): entries are exactly the cue
    ids in order and agree per screen on ordinal/movement/kind; the entry
    shape is frozen (no unit ids, no `id` field, no grouping span); ranges are
    ordered, never overlap, and each starts at a screen boundary (the opening
    shot directive, first line of it when the directive wraps); every
    non-blank body line outside the ranges is inert (comment, `---`, movement
    heading) so a range that ends early fails; the document flag mirrors the
    black kind.
  - `timing_props` — the clock (T15, spec: Timing): every cue carries a
    positive-float `est_seconds` at least as long as its pure read time at the
    deck's speech rate; the build never writes `timing.yaml` and never puts the
    estimate in it; check 19 reports on `timing-drift` and stays silent on
    `timing-demo`, and neither is ever a failure; an authored override beats
    the estimate and a measured value beats both; plus unit assertions on
    `timing.py` — tolerant `dur` parsing, the kind floors, the video hard floor
    (ffprobe against a generated clip), precedence, and malformed-sidecar
    handling (rows report and skip; a broken sidecar never breaks a build).
  - `check_props` — every fixture is run through `check.check_file` (the
    T11 per-deck seam) with the built cues.json, with and without --strict,
    so the artifact assertions (checks 17 and 18) fire per fixture.
- `run.py` — per fixture profile: build twice into temp dirs and require the
  trees byte-identical (determinism, spec §8; `nav.json` rides this tree
  hash); diff the two golden layers; run the six property modules. Exit 0
  only when everything passes. Determinism hashes print on the `ok` lines
  (cues# manifest#).

## Fixture expectations

- Clean fixtures (no `test-expect` key) must build with zero warnings:
  the check suite's --strict run must exit 0. Infos/reports are permitted
  by the taxonomy and are pinned by the goldens where they occur.
- Tolerant fixtures declare `test-expect: warned` in frontmatter: the
  warning IS the construct (consecutive shots, junk tokens, nested parens,
  attribution fallthrough, dangling footnote). Non-strict check must exit 0
  with at least one warning finding; --strict must exit 1; no fatal ever.
  The exact warning text and line numbers are byte-pinned by the goldens.

## Golden discipline

Blessed on 2026-09-08 against HEAD 452a6ef (T01-T09 all merged and green);
re-blessed 2026-09-09 (media status have -> file) and 2026-09-10 (T15:
`est_seconds` on every cue — one added field per cue object and nothing else).
A builder change that alters emitted semantics shows as a golden diff and
must be understood before re-blessing; a golden that starts failing for an
unexplained reason is the suite doing its job. `--update-goldens` rewrites
expected/ from fresh builds and never skips the property or determinism
passes.

## Known behaviors the fixtures pin (do not "fix" silently)

- `both-art` in media-resolution has both a direct deck file and an attempts
  file. The builder tries the direct file first (mediaresolve._resolve);
  spec §6 lists attempts before the direct file. The golden pins the code's
  order (file: `_media/both-art.svg`, source deckdir). Reordering the stages
  must be a conscious change with its own diff and re-bless.
- Placeholder `reason` strings embed machine-local paths only when a media
  shot is cardless or a `status: have` card declares nothing and resolves to
  nothing (mediaresolve._resolve reason branches); check 17 then fails the
  artifact run. The fixture corpus deliberately avoids those two shapes.
  Until that leak is fixed, no cardless-orphan (remix-paste) fixture can
  join this suite; it should land with the fix.
- The spec's "empty trailing screen is dropped with a warning" tolerance is
  not observable in the current assembler: a trailing shot screen is kept as
  a beat (it has shots), and shotless screens cannot exist. Consecutive-shot
  warnings are pinned by the consecutive-shots fixture instead.
- Every source line number is body-relative — 1-based in the talkfile *after*
  the frontmatter is stripped (`talkparse._lex_frontmatter`), which is how
  every warning and every `nav.json` range reads. Adding frontmatter shifts
  no number; the fixtures pin the numbering both ways (a warning's line and a
  range's line are the same number for the same line).
- Consecutive non-blank prose lines merge into one paragraph, and consecutive
  quote markers / list items merge into one block. The block's span is its
  first line through its last, and `nav.json` ranges are the envelope of
  those spans: a range that stopped at the opening line would leave the
  wrapped lines belonging to no screen. `soft-wrap.talk.md` pins it.
