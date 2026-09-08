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
- `expected/<...>/{cues,media-manifest}.json` — byte goldens for the two
  semantic layers only. HTML is never byte-diffed (spec §9: highest churn
  layer); the views are property-checked instead.
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
    black-beat sections carry the class; the document's movement sections,
    Sources list, figures, and opening section must match cues.json; no
    remote assets or machine-local paths in either view.
  - `check_props` — every fixture is run through `check.check_file` (the
    T11 per-deck seam) with the built cues.json, with and without --strict,
    so the artifact assertions (checks 17 and 18) fire per fixture.
- `run.py` — per fixture profile: build twice into temp dirs and require the
  trees byte-identical (determinism, spec §8); diff the two golden layers;
  run the four property modules. Exit 0 only when everything passes.
  Determinism hashes print on the `ok` lines (cues# manifest#).

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

Blessed on 2026-09-08 against HEAD 452a6ef (T01-T09 all merged and green).
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
