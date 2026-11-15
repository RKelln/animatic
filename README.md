# Animatic

Write a talk as a script. Get slides, a handout, a web page and a recorded video from the same file.

Animatic is a talk-writing system for people who speak. You write one plain-text
file (a **talkfile**) that reads like a video-essay narration: the spoken words are
the default text, and a shot marker drops in wherever the picture changes. The same
file renders as:

- **Present view**: image-forward slides for the live talk, with the script in the speaker notes and a second presenter window (`s`).
- **Document view**: the spoken words as prose with the visuals embedded. Print it to a PDF handout or publish it as a scrolling web page.
- **Video**: a narrated web version and a video, with audio captured live and sliced per slide. (Experimental.)

The name is the *animatic*, the timed, moving pre-visual of a film.

It was built for, and first used in, the Toronto Public Library's Applied AI
Innovator in Residence programme (2026), where the same talk had to work live, as a
printable handout, and as a web page for people who could not attend.

## Quick start

Requires Python 3.10 or newer. Python 3.12 is what it is developed on.

```sh
git clone <this repo> animatic && cd animatic
uv sync                      # or: python3 -m venv .venv && .venv/bin/pip install -e .
uv run animatic examples/roles-demo/talk.md --out /tmp/demo
```

Then open `/tmp/demo/present/index.html` in a browser. Arrow keys page through the
slides; `s` opens the presenter window. `/tmp/demo/document/index.html` is the
handout view. Without uv, run the scripts directly with a Python that has
`pyyaml` and `pillow` installed: `python3 build.py examples/roles-demo/talk.md --out /tmp/demo`.

Check that everything works on your machine:

```sh
uv run python tests/run.py   # the golden suite: 65 profiles, should end "failed: 0"
```

Optional tools, used only by the features that need them:

| Tool | Needed for |
|---|---|
| Chromium or Chrome | the handout PDF (`tools/handout-pdf.py`) and the browser tests |
| ffmpeg / ffprobe | video stills, timing from recordings, web-sized video |

Without them, builds still work; the affected feature says what is missing.

## Your first talk

Save this as `talk.md`:

```markdown
---
slug: hello
title: "Hello, animatic"
theme: lecture
---

<!-- shot -->
# Hello, animatic

The spoken words go underneath every screen. They show up in the speaker notes
and in the handout, never on the slide.

---

## Movement 1 · The idea

<!-- shot -->
### One idea per screen

Headings are the rare on-screen text.

<!-- shot -->
> A quote can have a screen of its own.
~ Someone worth quoting
```

```sh
uv run animatic-check talk.md     # 0 fatal means the file is well formed
uv run animatic talk.md --out out    # render
uv run animatic talk.md --out out --watch   # rebuild on every save
```

Each `<!-- shot -->` starts a screen. A shot can name a picture
(`<!-- shot: river kb=in dim=0.4 text=light -->`), and the name is resolved from a
media card, a file in the deck's `media/` folder or a shared library.
`examples/roles-demo/talk.md` exercises every screen role and is the best next read.
The full grammar is `docs/format-spec-v1.md`.

## Commands

| Command | What it does |
|---|---|
| `animatic <talkfile> [--out DIR]` | render present view, document view and the JSON sidecars (same as `python3 build.py`) |
| `animatic-check <talkfile> [--strict]` | the check suite; `--register` lists every check |
| `python3 tools/handout-pdf.py <talkfile> <out.pdf>` | handout PDF (needs Chromium) |
| `python3 tools/web-export.py <talkfile> <out-dir>` | the document view as a self-contained web folder |
| `python3 tools/timing-report.py <talkfile>` | how long the talk runs, by movement and screen |
| `python3 tools/agent-export.py ...` | a plain-text file of the hands-on parts, for a coding agent |
| `python3 tools/serve-deck.py` | serve a built deck locally, with video Range support |
| `python3 tests/run.py` | golden and property tests |

Builds are deterministic: running one twice gives identical bytes.

## For coding agents

Read `AGENTS.md` first (`CLAUDE.md` is a symlink to it) or `llms.txt`. The talkfile
format is the stable contract (`docs/format-spec-v1.md`); the code behind it is
expected to change. `python3 check.py <talkfile> --strict` is the quickest way to
verify a talkfile you have edited, and `python3 tests/run.py` verifies a code change.

## Documentation

| Doc | About |
|---|---|
| `docs/format-spec-v1.md` | the talkfile grammar (normative) |
| `docs/media-pipeline.md` | media cards, generation log, style cascade |
| `docs/media-engines.md` | image and video generation engines, endpoints, conventions |
| `docs/presenter-view.md` | the second window and why it syncs over postMessage |
| `docs/live-capture.md` | `type: live` screens: a live window capture inside the deck |
| `docs/quick-select.md` | answering questions by jumping to a shelf slide |
| `docs/waypoints.md` | publishing "where the room is" for participants' agents |
| `docs/styling.md` | styling reference: layers, tokens, themes, how to add one |
| `tests/README.md` | how the test suite is built |

## Features

### Includes

`<!-- include: path [live] -->` on its own line splices another file's screens in at
that point, so a standard piece (a privacy slide, an about-me, credits) is
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

### Quick select

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

### Waypoints

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

## Reference

### Build

    python3 build.py <talkfile> [--out OUTDIR]
    python3 build.py <talkfile> [--out OUTDIR] --watch   # rebuild on every save; open pages reload
    python3 build.py <talkfile> --watch --lease <path>   # ...and stop when that heartbeat file goes stale

One watcher per `--out`: starting `--watch` on an `--out` that already has one stops the old
watcher first (it prints `replacing the watcher already running…`), so the newest wins. The
owner is recorded in `.<out>.watch.pid` beside the folder (git-ignored); only a pid that is
still a `build.py --watch` is signalled, and plain builds never are. This is how a watcher
started without `ANIMATIC_WAYPOINT_TOKEN` is swapped for one with it. Linux only (`/proc`).

### Handout PDF

    python3 tools/handout-pdf.py <talkfile> <out.pdf> [--figures capped|full|80%]

Builds the deck, then prints the document view with headless Chromium. Rebuild
it after any edit to the talkfile or its media; the PDF is a build product, so
it is not committed. For example:

    python3 tools/handout-pdf.py examples/roles-demo/talk.md handout.pdf

What the handout does (all from the one talkfile):

- A video prints as one JPEG still, a quarter of the way in. Change it with the
  card field `still:` or the shot flag `still=` (`start`, `end`, seconds like
  `3` or `3.5s`, or `50%`); the shot beats the card. Images print as small
  downscaled JPEGs (`_media/doc/`, 1100 px wide), so the PDF stays near 8 MB.
- A figure with the same slug as the figure just before it (including a
  `continue` shot) prints once; that screen's text still prints.
- A screen whose shot carries the bare flag `live` (`<!-- shot: demo-screen live -->`)
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

`--home` is the version for a person working at home beside their own coding agent: `do` screens print in place, code blocks and typed prompts get Copy buttons, a setup card leads (spec: "Home page and agent export").

Writes the document view as one self-contained folder: `index.html` plus
`media/` holding only the web-sized images the page uses. Every link is
relative, so the folder drops into a static-site `static/` directory or any file
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

## Layout

- `build.py`, `talkparse.py`, `mediaresolve.py`, `render.py`, `timing.py`: the builder. One talkfile in, four views out: present view (own-pager deck, script in the speaker notes), presenter view (`present/presenter.html`), document view (static HTML handout, print-to-PDF via print CSS), and `cues.json` (ordered cue id to script text and an estimated duration). Two sidecars are also written: `nav.json` (cue id to source line range, movement and kind) and `media-manifest.json` (the media resolution audit). Output goes to `out/` by default (gitignored).
- `check.py`: the deterministic check suite (`--register` prints all of them) with a fatal / warning / info / report taxonomy and `--strict`.
- `themes/`: CSS tokens and the two starter themes (`lecture`, `workshop`).
- `templates/`: a starter media card set (`cards.yaml`, `style.md`, `gen-log.md`).
- `tools/`: handout PDF, web export, agent export, timing report, deck server and other helpers.
- `examples/`: small specimens, not real talks.
- `tests/`: golden and property suites, and browser tests.
- `timing.yaml`: an optional deck-local timing sidecar (`animatic.timing.v1`), read and never written.
- `corpus.yaml`: content roots for the corpus check (`python3 build.py --corpus`).

## Status

Format v1.0 draft. The grammar is meant to stay stable so that talks you write survive
rewrites of the code; the code is not. There is no compatibility burden yet, so
defects are removed rather than deprecated. Issues and pull requests are welcome, see
`CONTRIBUTING.md`.

## Licence

MIT, see `LICENSE`.
