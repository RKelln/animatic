# Command reference

The commands behind the README's quick start: build, handout PDF, web page, audit, check and corpus check.

## The `animatic` CLI

    animatic build [DECK] [--out DIR] [--watch] [...]   # build.py's own flags
    animatic check [DECK ...] [--corpus [ROOT]] [--strict] [--json]
    animatic serve [--port N] [--bind ADDR] [--quiet]   # serve-deck.py's own flags
    animatic decks [--json]
    animatic pack  [DECK] [--out DIR] [--strict] [--verify] [--inert]
    animatic token [--show|--check]

`DECK` is a talkfile, a folder holding one (its `talk.md`, or its only
`*.talk.md`), or a deck's name from the content roots: its outdir (`out-w04`),
its slug (`w04-ai-job-search`) or the slug's first segment (`w04`, which is what
pull-deck takes). Omitted, it is the current directory, so `cd decks/W04 &&
animatic build` does the obvious thing and `animatic pack W04` works from
anywhere the content roots can see. A name matching two decks is an error, never
a guess.

The output folder defaults to `out-<first dash segment of the slug>` (`out-w04`
for `W04-ai-job-search`) — the rule `tools/find-talkfile.py` and pull-deck
already use, kept in one place in `cli.py`. `build.py`'s own default stays
`out/`; the CLI's convention is the deck-named folder.

The verbs own the deck question and the exit codes (0 ok, 1 not right, 2 usage)
and never re-implement what a module already knows: `build` and `check` call
`build.main`/`check.main`, and `serve` loads `tools/serve-deck.py` by path.

## Pack: the release artifact

    animatic pack talk.md [--out DIR] [--strict]
    animatic pack --verify --out DIR

A pack is a plain build (never a watch build), a check, and `BUILD.json` in the
output folder: the slug, title, theme, declared `dur`, the tool version, the
talkfile's SHA-256, and the SHA-256 and size of every file in the tree. It is
path-free on purpose (check 17 and the nav/html property tests forbid
machine-local paths in an artifact) and it carries no timestamps, so packing the
same talkfile twice produces byte-identical `BUILD.json`. That is what makes
`--verify` mean something on the far machine: it re-hashes the tree against the
manifest and reports missing, changed and unlisted files, and it refuses a copy
that carries `_watch.js`. It needs no source tree, so it runs on the laptop at
the venue.

A packed folder needs no server. Open `present/index.html` from disk — that is
the recommended way to present (`docs/live-capture.md`), and the only path where
browser window capture is guaranteed to work without the loopback exception.

`--inert` seals a copy with the waypoint publisher left out, whatever the token
sources say: the folder cannot post anything, so it is safe to hand out. Without
it, a pack made where a token is available records `waypoints: true` and says so
at seal time.

## Token

    animatic token            # store or replace the waypoint token (prompt, no echo)
    animatic token --show     # sha256 fingerprint of the token in use
    animatic token --check    # where it comes from, and the key file's mode

The token is read from `ANIMATIC_WAYPOINT_TOKEN` or from
`~/.config/animatic/waypoint-token` (mode 0600; override the path with
`ANIMATIC_WAYPOINT_TOKEN_FILE`), and never printed. `docs/waypoints.md` explains
why the file matters: a `--watch` started over ssh inherits no environment.

## Build

    python3 build.py <talkfile> [--out OUTDIR]
    python3 build.py <talkfile> [--out OUTDIR] --watch   # rebuild on every save; open pages reload
    python3 build.py <talkfile> --watch --lease <path>   # ...and stop when that heartbeat file goes stale

One watcher per `--out`: starting `--watch` on an `--out` that already has one stops the old
watcher first (it prints `replacing the watcher already running…`), so the newest wins. The
owner is recorded in `.<out>.watch.pid` beside the folder (git-ignored); only a pid that is
still a `build.py --watch` is signalled, and plain builds never are. This is how a watcher
started without a waypoint token is swapped for one with it. Linux only (`/proc`).

## Handout PDF

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

## Web page

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

## Reading-copy audit and skill

    python3 tools/reading-audit.py <talkfile>

One compact report on a talk's web page and PDF: checker findings, Sources status, screens that
print as a bare heading, spoken text aimed at the room, timers, and anything in the page that should not be
public. `skills/reading-copy/SKILL.md` is the skill that runs it and fixes a talk from the report; it is
written to run on one talk per subagent.

## Check

    python3 check.py <talkfile> [--strict] [--cues out/cues.json]

`check` exits 0 on a clean deck, 1 on any fatal (or, under `--strict`, any
warning), 2 on usage errors. Importable: `from check import check_file` is the
per-deck seam `animatic check` (and the corpus harness) drive.

## Corpus check (register 21)

    python3 build.py --corpus              # roots declared in corpus.yaml
    python3 build.py --corpus <root>       # scan one directory as a corpus

With no `corpus.yaml` beside `check.py` (it is machine-local and not tracked;
`corpus.example.yaml` is the template), the corpus form checks this repo's own
`examples/` root and warns that it is doing so.  Relative roots are resolved
against the repo root, so the declaration means the same thing from any
directory.

Runs the full check over every deck under the declared content roots —
per-deck PASS/FAIL with finding counts, cross-deck slug collisions (check 5)
once, a shared-bank health sweep, and the tag drift / coverage reports
(spec §10) across deck and wiki concept tags. Reads only; never writes into a
content root; deterministic output. Strict variant: `python3 check.py
--corpus [ROOT] --strict` (warnings become deck failures).
