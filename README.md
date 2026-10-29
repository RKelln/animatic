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
- document view: the spoken text as prose with visuals embedded = PDF handout and scrolling web page (contents rail, a per-screen anchor keyed by cue id, and per-screen sources; no script)
- recorded narrated web version and YouTube video (audio captured live, sliced per slide by the advance timeline; no hand-timed subtitles)

## Includes

`<!-- include: path [live] -->` on its own line splices another file's screens in at
that point, so a standard piece (TPL's privacy slides, an about-me, credits) is
written once and used by every talk. The path is relative to the including file;
absolute paths are refused. Name included files `*.section.md` (the corpus check
treats `*.talk.md` as decks).

- Each file is lexed on its own. Every screen from an included file points at the
  directive's line in the talk (warnings, `nav.json` ranges), and `nav.json` adds
  `"include": "<path as written>"` to those screens.
- `live` marks every screen inside as live-only (see the `live` shot flag in
  "What the handout does"). A `continue` shot after the include does not inherit it.
- Includes nest to 3 deep. A missing file, a cycle, an absolute path, an unknown flag
  or a `## Movement` heading inside the section is a fatal error with its line (check 22).
- An included file's frontmatter `cites:` / `sources:` join the talk's; the talk wins.
- `--watch` follows included files. Properties: `tests/properties/include_props.py`.

## Repo layout

- `docs/format-spec-v1.md` — the talkfile grammar (normative; v1.0 draft, hardening 2026-09-08)
- `docs/format-spec.md` — retired v0.5 (superseded marker only; see v1)
- `docs/media-pipeline.md` — media cards, generation log, style cascade, engine posture
- `docs/live-capture.md` — `type: live` screens: window capture, secure-context rule, hookup panel, diagnostics dump
- `docs/presenter-view.md` — the second window: `s` for the speaker UI, `n` for in-page notes, and why the sync is postMessage
- `docs/engine-decision.md` — builder spike decision record (engine, PDF path, parse model)
- `docs/web-edition-report.md` — proposal only, nothing built: what the SAgE trends page suggests for a web edition of the document view
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
- `check.py` — the deterministic check suite: the full 1-39 check register
  (spec §6/§7/§10/§11) with the fatal/warning/info/report taxonomy and
  `--strict` (warnings fatal). Check 19 reports when the deck's effective
  timing diverges from the declared `dur` by more than 30% (never a warning).
  See `python3 check.py --register`.
- `corpus.yaml` — the machine-local content-root declaration the corpus
  harness (check 21) scans; a shipped copy rewrites its paths.

### Build

    python3 build.py <talkfile> [--out OUTDIR]
    python3 build.py <talkfile> [--out OUTDIR] --watch   # rebuild on every save; open pages reload
    python3 build.py <talkfile> --watch --lease <path>   # ...and stop when that heartbeat goes stale
                                                         # (pull-deck.sh heartbeats it, so a watcher
                                                         # cannot outlive the pull that started it)

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
- A screen whose shot carries the bare flag `live` (`<!-- shot: tpl-privacy-01 live -->`)
  is for the room only: the present and presenter views show it, the handout
  leaves it out (nav.json says `reason: "live-only"`), and cues.json marks the
  cue `"live_only": true` so a video render must skip it.
- `[^id]` refs print as numbered links to the Sources list. If the frontmatter
  has a `cites:` map (id to public citation), the list prints those. The
  `sources:` entries are working receipts and may hold repo paths and "verify
  this" notes, so with `cites:` declared an id that has none is left out, with
  a build warning.
- Figure width: frontmatter `handout-figures:` or `--figures`; `capped` (the
  default, at most 68 mm tall), `full` (the text column), or a share like `80%`.
- Pool art (a random pick from a folder) can stay out of the handout: frontmatter `handout-pools: off`, or `--no-handout-pools` on build.py / `--no-pools` on handout-pdf.py. Slides keep it.
- A card with no picture yet prints a grey box naming the slug; leave it out of a copy for review with frontmatter `handout-placeholders: off`, or `--no-handout-placeholders` (`--no-placeholders` on handout-pdf.py). The text still prints.
- A slide never splits across pages, and the contents list may run on from the title's page.
- Print footer: the deck title on the left and "Page n of N" on the right; frontmatter `handout-footer: <text>` changes the left text, `off` removes both.
- Print is white, 11 pt. The web page keeps the theme's paper colour.

Chromium notes: a snap-packaged Chromium cannot read or write `/tmp` or hidden
directories, so the tool builds into `~/animatic-handout-build/<deck>/`
(override with `--work`, which must be under `$HOME` and not hidden).

### Web page

    python3 tools/web-export.py <talkfile> <out-dir>

Writes the document view as one self-contained folder: `index.html` plus
`media/` holding only the web-sized images the page uses. Every link is
relative, so the folder drops into a Hugo `static/` directory or any file
server. It adds `description` / `og:` tags from the title and `logline`, and
refuses to export a page that links outside its folder or shows a local path
(`/home/...`, `~/Documents/...`). Screens flagged `live` are not in it.

Sources: a deck's `[^id]` refs print as a Sources list only when the deck
declares `cites:` (public citations). With only `sources:` (working receipts)
the page and the PDF print no list and the build warns; `handout-sources:
working` in the frontmatter opts a draft copy back in.

### Reading-copy audit and skill

    python3 tools/reading-audit.py <talkfile>

One compact report on a talk's web page and PDF: checker findings, Sources status, screens that
print as a bare heading, spoken text aimed at the room, timers, and anything in the page that should not be
public. `skills/reading-copy/SKILL.md` is the skill that runs it and fixes a talk from the report; it is
written to run on one talk per subagent.

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
