# Command reference

The commands behind the README's quick start: build, handout PDF, web page, audit, check and corpus check.

## Build

    python3 build.py <talkfile> [--out OUTDIR]
    python3 build.py <talkfile> [--out OUTDIR] --watch   # rebuild on every save; open pages reload
    python3 build.py <talkfile> --watch --lease <path>   # ...and stop when that heartbeat file goes stale

One watcher per `--out`: starting `--watch` on an `--out` that already has one stops the old
watcher first (it prints `replacing the watcher already running…`), so the newest wins. The
owner is recorded in `.<out>.watch.pid` beside the folder (git-ignored); only a pid that is
still a `build.py --watch` is signalled, and plain builds never are. This is how a watcher
started without `ANIMATIC_WAYPOINT_TOKEN` is swapped for one with it. Linux only (`/proc`).

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
per-deck seam the `animatic-check` command and the corpus harness drive.

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
