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
- A section's media comes only from the shared `_media/` (a library entry, or a file named
  `<slug>.<ext>` / `<slug>/<slug>.<ext>`), never the including deck's `cards.yaml` or
  `media/`, so a section looks the same in every deck. A slug with no shared media is a
  placeholder and the usual warnings. If the deck has its own card or file of that slug, the
  section's copy is published as `<slug>--lib` beside it (`docs/media-pipeline.md`).
- `--watch` follows included files. Properties: `tests/properties/include_props.py`.

## Quick select

During Q&A someone asks about a topic the talk does not cover. In the presenter window
press `/`, type "agents", pick a result with Up / Down / Enter, and that slide appears on
the projector. `Esc` returns to exactly where the talk was (same slide, same reveal step).
Full design: `docs/quick-select.md`.

- A talk opts in with one frontmatter line, `quick_sections: ../_sections` (relative to
  the talkfile). A section joins the **shelf** by declaring `quick:` in its own
  frontmatter: `title:` (required) and `keywords:` (a list). A section with no `quick:`
  block stays off the shelf. A section the talk already includes is not shelved twice;
  its title and keywords still reach the search.
- Shelf sections are built into the deck **after the last real screen**, so slide numbers
  and `#N` links do not move. Paging never leaves the talk, and on the shelf it never
  leaves the section; only a jump crosses. They are in the present view, the presenter
  window, `cues.json` (`quick: true`, `live_only: true`), `nav.json` and the media
  manifest, and **not** in the document view, the handout or the web export. The shelf
  does not count toward timing (check 19). A shelf section's `cites:` / `sources:` serve
  its own screens only and never reach the handout.
- `python3 build.py <talk> --quick-sections DIR` trial-builds a deck with a shelf from
  DIR without editing the talkfile (it overrides the frontmatter line; DIR is relative to
  the working directory). `--watch` follows shelf files; a newly added section file needs
  a fresh build.
- A deck with no `quick_sections` has an empty shelf: its slides, document view, handout and `cues.json` / `nav.json` / `media-manifest.json` are unchanged (only the inline scripts and the presenter page differ).
- Check 48 (fatal): `quick_sections` names a missing directory, a `quick:` block has no
  `title` or a `keywords` that is not a list, or a shelf screen's media does not resolve
  from the shared `_media/` (no placeholder: nobody pages to a hidden slide; the error
  names the section file). `--quick-sections DIR` reads sections from DIR but media from
  the `_media/` beside the deck, not one beside DIR.
- Properties: `tests/properties/quick_props.py`; the browser test is
  `tests/browser_quick_select.py`.

## Waypoints

When the talk reaches a marked slide the deck publishes one word, so participants'
agents can tell them where the room is. Full design: `docs/waypoints.md` (the service and
the machine-side hook are other repos; this is the deck's half).

- Mark a slide with `waypoint=expanding` in its shot (`<!-- shot: waypoint=expanding -->`, or
  alongside other tokens: `<!-- shot: reveal=timer live waypoint=expanding -->`), and give the talk `waypoints: { url: https://.../W11 }` in its
  frontmatter. A word is lowercase letters, digits and hyphens, up to 24, used once. Put
  `start` on the first screen. It belongs in the talkfile, never in a section.
- `ANIMATIC_WAYPOINT_TOKEN=... python3 build.py <talk>` builds a deck that publishes. The
  token goes into `present/index.html` and nowhere else, and is never printed. Without it
  the build is **inert**: nothing is sent and there is no status line or `w` key, so a
  rehearsal build cannot touch a live room.
- A publishing deck POSTs the bare word with `Authorization: Bearer <token>` (async, 3 s
  timeout, one retry, never blocks paging) when `next()` arrives at a marked slide later
  than the last word sent, and on load at screen 1 with no `#` in the address (`start`).
  Never on prev, a hash change, a quick-select jump or return, or a `next()` pressed while
  a jump is out. It works from `file://` and localhost.
- The presenter window shows `Waypoint: expanding ✓ 7:04pm` or `✗ not sent, w to retry`.
  `w` (deck or presenter window) re-sends the latest word at or before the current slide,
  which is also how to correct a mistake: go back, press `w`.
- `cues.json` and `nav.json` gain a `waypoint` field on marked screens; nothing else in a
  deck changes. Check 49 (fatal): a bad word, a duplicate, a waypoint inside a section's shot, one
  on a shot that opens no screen, the old standalone `<!-- waypoint: ... -->` line, or waypoints without a valid `waypoints.url`.
- Properties: `tests/properties/waypoint_props.py`; the browser test is
  `tests/browser_waypoint.py`.

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
- `tools/timing-report.py` — the clock as a report: total against `dur` (or `--dur`), the
  total at 130 and 150 wpm, and time by movement, timer and longest screen, split into
  spoken, timer, video, minimum and override. A plain timer runs while the words are
  spoken (the longer counts); a `reveal=timer` follows them (the two add).
- `corpus.yaml` — the machine-local content-root declaration the corpus
  harness (check 21) scans; a shipped copy rewrites its paths.

### Build

    python3 build.py <talkfile> [--out OUTDIR]
    python3 build.py <talkfile> [--out OUTDIR] --watch   # rebuild on every save; open pages reload
    python3 build.py <talkfile> --watch --lease <path>   # ...and stop when that heartbeat goes stale
                                                         # (pull-deck.sh heartbeats it, so a watcher
                                                         # cannot outlive the pull that started it)

One watcher per `--out`: starting `--watch` on an `--out` that already has one stops the old
watcher first (it prints `replacing the watcher already running…`), so the newest wins. The
owner is recorded in `.<out>.watch.pid` beside the folder (git-ignored); only a pid that is
still a `build.py --watch` is signalled, and plain builds never are. This is how a watcher
started without `ANIMATIC_WAYPOINT_TOKEN` is swapped for one with it. Linux only (`/proc`).

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
  cue `"live_only": true` so a video render must skip it. The bare flag `do`
  marks an exercise screen: presented, left out of the handout and reading copy
  like `live`, but kept in the agent export (`tools/agent-export.py`; spec:
  Screen kinds, Agent export). `(Do: ...)` is an agent-only instruction.
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
    python3 tools/web-export.py --home <talkfile> <out-dir> [--agent-url URL] [--coding-agent-url URL]

`--home` is the version for a person working at home beside their own coding agent: exercise screens and `(Do: ...)` notes become exercise cards with a paste box, code blocks get Copy buttons (spec: "Home page and agent export").

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
