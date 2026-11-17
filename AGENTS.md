# AGENTS.md — animatic

Animatic turns one markdown **talkfile** per talk into a present view (cinematic
slides), a document view (the spoken words as prose: handout and web page) and an
agent export. Read `README.md` first for what it is and how to install it.
The code is expected to keep being rewritten; the **talkfile format is the stable
contract** (`docs/format-spec-v1.md`), because authored talks must survive.

`CLAUDE.md` in this repo is a symlink to this file: one source of truth for every
coding agent. Edit `AGENTS.md`, never the symlink.

## Setup

    uv sync                                  # or: python3 -m venv .venv && .venv/bin/pip install -e .
    uv run python tests/run.py               # expect "failed: 0"

Python 3.10+. Runtime dependencies are `pyyaml` and `pillow`. Chromium (handout PDF,
browser tests) and ffmpeg/ffprobe (video features) are optional; tests that need a
missing browser exit 77 (skipped), they do not fail.

## Where things live

- A deck is a folder holding `talk.md`, plus `media/` (pictures, `cards.yaml`,
  `gen-log.md`, `style.md`) beside it. Decks usually live **outside** this repo; the
  specimens here are in `examples/`.
- `corpus.yaml` lists the content roots the corpus harness scans. It is **not tracked**
  (it names where your talks live); copy `corpus.example.yaml` to `corpus.yaml` and
  edit it. With none, the harness checks `examples/` and says so.
- `cli.py`: the `animatic` dispatcher (`build`, `check`, `serve`, `decks`, `pack`).
  The verbs own deck identity and exit codes; `build.py`/`check.py` stay the
  importable plumbing they call.
- `templates/`: `cards.yaml`, `gen-log.md`, `style.md` as new decks inherit them.
- `docs/`: the format spec and feature docs (`format-spec-v1.md` is normative).
- `themes/`: CSS tokens and the two themes. `tests/README.md` explains the test layers.

## Commands (verify, don't assume)

    animatic build [DECK] [--out DIR] [--watch] [...]  # the CLI; DECK = talkfile or folder, omitted = CWD; default out-<slug>
    animatic check [DECK ...] [--corpus [ROOT]] [--strict] [--json]   # --json = findings as JSON
    animatic decks [--json]                        # deck identity: outdir, slug, theme, dur (--json for tools/scripts)
    animatic pack  [DECK] [--out DIR] [--strict]   # sealed release: plain build + check + BUILD.json; never a watch build
    animatic pack  --verify --out DIR              # re-hash a carried pack against its manifest (needs no source tree)
    animatic serve [--port N] [--bind ADDR]         # local deck server (video Range, request log; file:// is the recommended venue path)
    python3 build.py <talkfile> [--out OUTDIR]     # render present + document views (the CLI's plumbing; same output)
    ANIMATIC_WAYPOINT_TOKEN=... python3 build.py <talkfile>   # a deck that publishes waypoints; without it, inert (docs/waypoints.md)
    python3 build.py <talkfile> --watch [...]      # rebuild on save, open pages reload (Ctrl-C stops); replaces any watcher already on that --out
    python3 build.py <talkfile> --quick-sections DIR   # trial-build with a quick-select shelf (docs/quick-select.md)
    python3 tools/handout-pdf.py <talkfile> <out.pdf> [--figures full|80%]   # handout PDF (see docs/reference.md)
    python3 tools/agent-export.py <talkfile> <out.md> --core <core.md> --page-url URL --home-url URL   # plain-text file: the hands-on parts, for a coding agent beside the home page
    python3 tools/web-export.py --home <talkfile> <out-dir> --agent-url URL --coding-agent-url URL    # home page: do screens in place, Copy buttons, setup card
    python3 tools/timing-report.py <talkfile> [--dur 2h] [--wpm N] [--screens] [--json]   # how long it runs, by movement, timer and screen
    python3 tools/shorten-includes.py [PATH ...] [--write]   # rewrite `../_sections/x.section.md` includes to the bare section name (proves each rewrite; no PATH = corpus roots)
    python3 build.py --corpus                      # every deck under corpus.yaml roots
    python3 check.py <talkfile> [--strict] [--cues out/cues.json]
    python3 check.py --register                    # the canonical check register (1-53)
    python3 check.py --corpus [ROOT] --strict      # warnings become deck failures
    python3 tests/run.py                           # golden suite: expect "profiles: 65  passed: 74  failed: 0"
    python3 tests/browser_waypoint.py              # real-browser test for waypoints (exit 77: no chromium)
    python3 tests/browser_quick_select.py          # real-browser test for quick select (exit 77: no chromium)

`check.py` exits 0 on a clean deck, 1 on a fatal (or, under `--strict`, a warning),
2 on usage errors. Corpus mode is read-only: it parses and checks, never writes into
a content root. Builds are deterministic — re-running rebuilds identical bytes.

## Rules

- **The handout is public.** It prints `cites:` (public citations), never the
  `sources:` working receipts. Before pointing anyone at a handout or web page, check it
  for local paths, "verify" notes and internal comments (`tools/reading-audit.py`).
  Rebuild it with `tools/handout-pdf.py`; PDFs are build products and are not committed.
- **A packed artifact is path-free and reproducible.** `BUILD.json` carries no host
  paths (check 17's rule, and the artifact travels) and no timestamps, so re-packing
  the same talkfile gives identical bytes and `animatic pack --verify` means something
  on another machine.
- **Zero install base.** There are no shipped users and no compatibility burden. Delete
  defects outright rather than grandfathering them behind deprecation shims.
- `+<role>` is the only overlay syntax. Attribution is canonicalized to `~`.
- Deck frontmatter carries the theme and declared `dur`; check 19 reports when effective
  timing drifts more than 30% from the declaration.
- Nothing that parses today may change meaning. Prove it by running the corpus check over
  every deck you have, not by arguing from a happy path.
- Builds are deterministic: re-running rebuilds identical bytes. Keep it that way.
- Golden files in `tests/expected/` change only through `python3 tests/run.py
  --update-goldens`, and only after you have read the diff and meant it.
- Secrets (such as `FAL_KEY` for image generation) come from the environment, never a file in the repo.
- Leave an author's talkfiles uncommitted unless asked; they review and commit their own content.
