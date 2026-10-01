# Animatic

A personal system for writing talks, lectures, and workshops as scripts, and
rendering them as films. Named for the animatic: the timed, moving pre-visual of
a film. The automatic ring is intentional: agents do the assembly, Ryan directs
and curates.

## What a talk is here

One plain-text file per talk (the "talkfile") reads like a video-essay narration
script. The spoken words are the default text; visual shots drop in where the
picture changes; on-screen text is rare and explicit.

The same file renders as:
- present view: cinematic slides for the live talk (image-forward, slow motion, few words)
- document view: the spoken text as prose with visuals embedded = PDF handout and scrolling web page
- recorded narrated web version and YouTube video (audio captured live, sliced per slide by the advance timeline; no hand-timed subtitles)

## Repo layout

- `docs/format-spec-v1.md` — the talkfile grammar (normative; v1.0 draft, hardening 2026-09-08)
- `docs/format-spec.md` — retired v0.5 (superseded marker only; see v1)
- `docs/media-pipeline.md` — media cards, generation log, style cascade, engine posture
- `docs/live-capture.md` — `type: live` screens: window capture, secure-context rule, hookup panel, diagnostics dump
- `docs/presenter-view.md` — the second window: `s` for the speaker UI, `n` for in-page notes, and why the sync is postMessage
- `docs/engine-decision.md` — builder spike decision record (engine, PDF path, parse model)
- `templates/` — starter media card set (style, cards, gen-log)
- `build.py` + `talkparse.py` + `mediaresolve.py` + `render.py` + `timing.py` — the builder (E2 spike):
  one talkfile in, four views out: present view (own-pager deck, VO in
  speaker notes), presenter view (`present/presenter.html`, the second-window
  speaker UI on `s`), document view (static HTML handout, print-to-PDF via print CSS),
  cues.json (ordered slide id to script text + `est_seconds`, the estimated
  clock, for the future controller), plus two
  generated sidecars: nav.json (cue id -> source line range, movement, kind —
  addressability, and the document view's black-beat omissions) and
  media-manifest.json (the resolution audit). Generated output lives in `out/`
  (gitignored).
- `timing.yaml` — the optional deck-local timing sidecar (`animatic.timing.v1`),
  read and never written: an `authored` hand override or a `measured` value per
  cue id, plus `settings.wpm`. The estimate stays in cues.json; the spec's
  Timing section owns the clock.
- `check.py` — the deterministic check suite: the full 1-32 check register
  (spec §6/§7/§10/§11) with the fatal/warning/info/report taxonomy and
  `--strict` (warnings fatal). Check 19 reports when the deck's effective
  timing diverges from the declared `dur` by more than 30% (never a warning).
  See `python3 check.py --register`.
- `corpus.yaml` — the machine-local content-root declaration the corpus
  harness (check 21) scans; a shipped copy rewrites its paths.

### Build

    python3 build.py <talkfile> [--out OUTDIR]
    python3 build.py <talkfile> [--out OUTDIR] --watch   # rebuild on every save; open pages reload

### Handout PDF

    python3 tools/handout-pdf.py <talkfile> <out.pdf> [--figures capped|full|80%]

Builds the deck, then prints the document view with headless Chromium. Rebuild
it after any edit to the talkfile or its media; the PDF is a build product, so
it is not committed. For the L01 talk, from this repo:

    D=~/talks/decks/L01-opening-talk
    python3 tools/handout-pdf.py $D/talk.md $D/handout/L01-handout.pdf

What the handout does (all from the one talkfile):

- A video prints as one JPEG still, a quarter of the way in. Change it with the
  card field `still:` or the shot flag `still=` (`start`, `end`, seconds like
  `3` or `3.5s`, or `50%`); the shot beats the card. Images print as small
  downscaled JPEGs (`_media/doc/`, 1100 px wide), so the PDF stays near 8 MB.
- A figure with the same slug as the figure just before it (including a
  `continue` shot) prints once; that screen's text still prints.
- `[^id]` refs print as numbered links to the Sources list. If the frontmatter
  has a `cites:` map (id to public citation), the list prints those. The
  `sources:` entries are working receipts and may hold repo paths and "verify
  this" notes, so with `cites:` declared an id that has none is left out, with
  a build warning.
- Figure width: frontmatter `handout-figures:` or `--figures`; `capped` (the
  default, at most 68 mm tall), `full` (the text column), or a share like `80%`.
- Print is white, 11 pt. The web page keeps the theme's paper colour.

Chromium notes: a snap-packaged Chromium cannot read or write `/tmp` or hidden
directories, so the tool builds into `~/animatic-handout-build/<deck>/`
(override with `--work`, which must be under `$HOME` and not hidden).

### Check

    python3 check.py <talkfile> [--strict] [--cues out/cues.json]

`check` exits 0 on a clean deck, 1 on any fatal (or, under `--strict`, any
warning), 2 on usage errors. Importable: `from check import check_file` is the
per-deck seam the future `animatic` wrapper and the corpus harness drive.

### Corpus check (register 21)

    python3 build.py --corpus              # roots declared in corpus.yaml
    python3 build.py --corpus <root>       # scan one directory as a corpus

Runs the full check over every deck under the declared content roots —
per-deck PASS/FAIL with finding counts, cross-deck slug collisions (check 5)
once, a shared-bank health sweep, and the tag drift / coverage reports
(spec §10) across deck and wiki concept tags. Reads only; never writes into a
content root; deterministic output. Strict variant: `python3 check.py
--corpus [ROOT] --strict` (warnings become deck failures).

Specimen (read-only input, TPL repo):

    python3 build.py ~/talks/decks/L01-opening-talk/talk.md

Deterministic output; re-running rebuilds the same bytes. See
`docs/engine-decision.md` for the decisions encoded in the builder.

## Instances

- TPL Applied AI residency (first deployment): `~/talks/decks/` — content, banks, and per-talk files; its README points here for the spec.

## Related

- Hermes skill `talkfile-decks` (creative/) — authoring workflow (draft decks from content banks)
- Kanban board `animatic` — build tickets (E1-E5, T01-T15 hardening)
- Controller (Phase 2): live captions + voice/script advance, designed as a Peripherous plugin family — design brief t_dc90108c on the `peripherous` board

Status: format v1.0 draft in hardening (`docs/format-spec-v1.md`); the
grammar freezes behind a Ryan gate (kanban T12), then v1.0 ships.
