# tests/ — the golden + property suite

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
  `multiline-shot.talk.md` is the construct fixture (register check 27),
  committed before this suite and included unchanged except status quoting.
  `cue-id-space.talk.md` is generated (103 one-card screens) and pins the
  three-digit cue-id space past the 99 cliff (register check 18).
  `lists-and-tables.talk.md` pins numbered lists (`1.` and `1)`, a `-` run
  after them as a separate list) and pipe tables (with and without a header
  delimiter, a ragged row), and that prose with a mid-line pipe stays spoken.
  `soft-wrap.talk.md` pins merged line spans — a soft-wrapped paragraph, a
  two-line quote, a two-line list — the spans `nav.json` ranges are built
  from (a range that stops at a block's first line leaves body lines
  belonging to no screen).
  `reveal-timer.talk.md` pins `reveal=timer` (spec: Timer screens, "Revealed
  timers"): a block timer, a corner timer, `list+timer`, `timer+list` (any order),
  a plain timer that still starts on arrival, and the warned cases (no timer on
  the screen, a bad timer, a repeated value).
  `reveal-bare.talk.md` pins the bare `reveal` with the timer written below the list: list items then the timer, a
  list-only and a timer-only screen, the long form `reveal=list+timer` beside it
  (same markup), a corner timer, and the warned cases (nothing revealable: check
  45; a named `reveal=list` with no list is still check 43).
  `reveal-order.talk.md` pins document order for the reveal steps: a timer
  written above the list is press 1 (the list opens empty), as a block, in the
  heading above, or as a corner line with no heading; a timer below the list or
  inside its items stays last; `reveal=list+timer` and the bare form match;
  `reveal=timer` alone leaves an unrevealed list showing; cues carry
  `timer_reveal_first` only when the timer comes first.
  `timer-continue.talk.md` pins continued countdowns (`[timer]`, `[timer corner]`,
  `([timer])`): `timer_continues` on the cue, `data-timer-from` / `data-timer-span`
  on the plates, a span that counts the countdown once, the orphan (check 52, left
  as text) and `reveal=timer` on a continuation (ignored).
  `browser_reveal_timer.py` is the real-browser check for both: it builds each
  fixture, drives the present page in headless chromium with real
  ArrowRight/ArrowLeft keydowns, and asserts hidden and stopped on arrival,
  revealed and counting after one Next, the next slide after a second, hidden and
  stopped again after Back, the list+timer order, for a bare `reveal` a
  list+timer slide, a list-only slide and a timer-only slide, and for document
  order a timer-above-list slide (press 1 shows and starts the timer with no item
  showing, then one item per press, Back past the timer's press resets it) (run it directly; it
  exits 77 when no chromium is installed, and needs the scratch directory inside
  the repo because a snap chromium cannot read /tmp).
  `fixtures/quick/` is the quick-select deck (not a golden: the runner does not
  build it): `quick/deck/` is the deck and `quick/_media/` its shared library, because
  shelf media comes from `_media/` beside the deck, never from the deck's own cards (the
  tests copy both side by side; the browser test swaps the stand-in `clip-shelf.svg` for a
  generated mp4). A talk with `quick_sections`, a shelf of sections (a plain one, one
  with a video, one with a live screen, one the talk also includes) and a section
  with its own `cites:`. `properties/quick_props.py` builds a copy in /tmp and
  pins the shelf's placement and order, dedupe, absence from the document view
  and the web export, timing, citations not leaking, the cue index, determinism,
  a deck with no shelf (an empty one) having the same slides, document view, cues and nav as with one, and check 48. `browser_quick_select.py`
  is the real-browser half (docs/quick-select.md): the pager, jump and return,
  timers, the warm bookkeeping, and the presenter window's search box driven over
  http through the deck's own `s` popup (exit 77 without chromium; the video
  asserts need ffmpeg).
  `properties/shared_media_props.py` (docs/media-pipeline.md, "Shared media") builds a
  throwaway `decks/{deck,_media,sections}` tree: the same slug in a slide and in a section with
  different files (`pic` and `pic--lib`, both published, distinct in the manifest, cues and
  document view; no rename without a clash); a shared pool ignoring a deck card of its name; a
  file named for its slug with no library entry (flat and `<slug>/<slug>.<ext>`); an entry beating
  a name match; two matching files (fixed pick, check 50 from build.py and check.py); an
  unresolved shelf slug fatal (check 48, section file named, in build.py and check.py) against the
  same section included, which stays a placeholder with the check 11 warning; and
  `--quick-sections` pointing outside the deck's parent (media still from the deck's `_media/`).
  It also holds the `--lib` name through a `continue` screen, a stepped card's frames, a pingpong
  video, the document view and `--no-handout-pools`; pins alt falling back to the slug as written;
  an entry as the card of a slide with none; checks 50 (missing `file:`) and 51 (no credit); and a
  deck's stand-in not filling a section's `--lib`.
  `fixtures/waypoints/` is the waypoint deck (docs/waypoints.md): four marked screens
  (one with the directive between a heading and its shot), a shelf, a `waypoints.url`.
  `properties/waypoint_props.py` pins the parse, check 49 (every case, with its line),
  `waypoint` in `cues.json` / `nav.json` only, the word absent from the document view,
  handout, web export and presenter page, the token in `present/index.html` and nowhere
  else (no other output, no build log, no web export), the inert build, and a deck with
  the directives out being the same deck bar the field.
  `browser_waypoint.py` is the real-browser half: it runs a throwaway HTTP server that
  records every request, preflight included, and drives the publish rules from
  `file://`, the failure and retry paths (the 3 s timeout in real time, because headless
  Chromium's virtual time stands still while a fetch is pending), the presenter's `w`
  and the quick search swallowing it, and an inert build (exit 77 without chromium).
  `timing-drift.talk.md` declares `dur: 45 min` on a two-screen deck: the
  clock (check 19) must report the divergence and the deck must still build
  (spec: Timing).
  `shot-continue.talk.md` pins `continue` / `cont` shots: each opens its own
  screen on the previous screen's media slug and flags, a flag written on
  the continue shot wins (spec: The shot directive).
  `paraphrase-pair.talk.md` pins the `paraphrase` role (spec §4 Roles): one
  screen carries a leading quote and its `~` attribution (source's words,
  screen-only) AND an entry of kind `paraphrase` whose text is also the
  screen's script (our words, shown and spoken), and a second screen pins the
  plain payload shape — the paragraph directly after the role shot. It reuses
  the pool slug `sample-art` rather than adding a row.
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
  - `code-fences` / `code-fences-warned` — fenced code (spec: Text, "Fenced code"):
    the SOUL file under a heading with the fence on the next line and `fit=hero`,
    the same file at normal size, a fence holding a shot directive, headings, a
    list, a quote, a table, a parenthetical, a footnote marker, a comment and an
    em dash that all stay literal, a `~~~` fence holding a ``` line, an indented
    opener with a longer closer, fences straight after a paragraph and a list, a
    role shot followed by a fence, and a real movement after a fenced fake one.
    The warned deck pins check 35 (unclosed before a shot, before a movement
    heading, at end of file) and check 36 (empty, blank-only). `code_props`
    holds the invariants: no fenced text in script or est_seconds, each fence
    once as a `<pre>` in both views, nothing inside became a list, heading or
    comment node.
  - `timer-tokens` / `timer-tokens-warned` — countdown tokens (spec: Timer screens): a
    block on its own line (with a spoken paragraph beside it), inline in a heading, a
    list item, a quote and a stat payload, a `corner` plate over a picture, a
    `continue` screen that carries no timer, a `fit=hero` block, spellings in any case
    and spacing (`[ TIMER :90S ]`, `[timer:3M CORNER]`, `[TIMER:   45]`), and a token
    inside a fence and inside a parenthetical staying inert. The warned deck pins
    check 39 (a token in a spoken paragraph, dropped from the voice-over), check 37
    (bad value, zero, a typo, an unknown trailing word, a second timer; all left as
    literal text) and check 38 (over 3 hours), and that the `timer=` shot flag is an
    unknown flag. `timer_props` holds the invariants: `cues.json` `timer` is an
    integer equal to the first valid token, `timer_in` / `timer_corner` agree with the
    token, no token in `script`, one `.timer-plate` of the right shape per timer cue,
    no plate or clock in the document view, which prints `<duration> timer`, and
    `est_seconds` follows the rule (the longer of the words and a plain timer, the
    two added for a revealed timer). The countdown itself (start, keep running, pause, reset,
    overtime, presenter sync) is browser behaviour and was verified in headless
    Chromium by driving real key presses, not in this suite.
  - `code-fences-wrap` - width never shrinks a fenced block: the four-bullet
    "What's on the page" slide under `fit=hero` (with a `reveal=list` that has no
    list to step), a 400-character single line, 18 and 25 short lines (shrink to
    fit; past the 75% floor, clipped and marked), and every hanging-indent shape
    (`-`, `*`, `+`, `1.`, `2)`, spaces, tab, none).
  - `decks/_media/library.yaml` — the shared library home for deck
    fixtures (sibling of each deck dir, per spec §11).
  - `timing-demo` — the clock end to end: `dur: ~1 min` sits inside the
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
  - `nav_props` — the addressability map: entries are exactly the cue
    ids in order and agree per screen on ordinal/movement/kind; the entry
    shape is frozen (no unit ids, no `id` field, no grouping span); ranges are
    ordered, never overlap, and each starts at a screen boundary (the opening
    shot directive, first line of it when the directive wraps); every
    non-blank body line outside the ranges is inert (comment, `---`, movement
    heading) so a range that ends early fails; the document flag mirrors the
    black kind.
  - `timing_props` — the clock (spec: Timing): every cue carries a
    positive-float `est_seconds` at least as long as its pure read time at the
    deck's speech rate; the build never writes `timing.yaml` and never puts the
    estimate in it; check 19 reports on `timing-drift` and stays silent on
    `timing-demo`, and neither is ever a failure; an authored override beats
    the estimate and a measured value beats both; plus unit assertions on
    `timing.py` — tolerant `dur` parsing, the kind floors, the video hard floor
    (ffprobe against a generated clip), precedence, and malformed-sidecar
    handling (rows report and skip; a broken sidecar never breaks a build).
  - `check_props` — every fixture is run through `check.check_file` (the
    per-deck seam) with the built cues.json, with and without --strict,
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

Blessed against a green suite;
re-blessed 2026-09-09 (media status have -> file) and 2026-09-10 (
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
- Every source line number is the talkfile's own, 1-based with the
  frontmatter counted, which is how every warning and every `nav.json` range
  reads, so a number matches what an editor shows (2026-09-28; before that
  they were body-relative). Editing the
  frontmatter therefore shifts the numbers after it. The fixtures pin the
  numbering both ways (a warning's line and a range's line are the same
  number for the same line); frontmatter lines belong to no range.
- Consecutive non-blank prose lines merge into one paragraph, and consecutive
  quote markers / list items merge into one block. The block's span is its
  first line through its last, and `nav.json` ranges are the envelope of
  those spans: a range that stopped at the opening line would leave the
  wrapped lines belonging to no screen. `soft-wrap.talk.md` pins it.
