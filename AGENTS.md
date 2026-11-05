# AGENTS.md — animatic

Ryan's talk/lecture system: one markdown **talkfile** per talk, rendered to a
present view (cinematic slides), a document view (the spoken words as prose), and
a recorded video-essay. Format and toolchain contract, first deployed for the TPL
Applied AI residency. The code is expected to keep being rewritten; the format
contract is what has to stay stable so authored talks survive.

`CLAUDE.md` in this repo is a symlink to this file — one source of truth for every
coding agent. Edit here, never there.

## Where things live

- **Deck sources live OUTSIDE this repo**: `~/talks/decks/<deck>/talk.md`.
  Their media, `cards.yaml`, `gen-log.md` and `style.md` sit beside each talkfile.
- `corpus.yaml` declares the machine-local content roots the corpus harness scans
  (decks, concepts, banks). A shipped copy rewrites its paths.
- `templates/` — `cards.yaml`, `gen-log.md`, `style.md` as decks inherit them.
- `examples/` — small specimens (`roles-demo`, `timing-demo`, `media-resolution`); not real talks.
- `docs/` — the decision records, including `engine-decision.md` (why this build shape).
- Spec: this repo's `README.md`, plus `docs/*.md`. A longer authoring spec lives in
  the Hermes skill at `~/.hermes/skills/creative/talkfile-decks/`.

## Commands (verify, don't assume)

    python3 build.py <talkfile> [--out OUTDIR]     # render present + document views
    python3 build.py <talkfile> --watch [...]      # rebuild on save, open pages reload (Ctrl-C stops)
    python3 build.py <talkfile> --quick-sections DIR   # trial-build with a quick-select shelf (docs/quick-select.md)
    python3 tools/handout-pdf.py <talkfile> <out.pdf> [--figures full|80%]   # handout PDF (see README: Handout PDF)
    python3 build.py --corpus                      # every deck under corpus.yaml roots
    python3 check.py <talkfile> [--strict] [--cues out/cues.json]
    python3 check.py --register                    # the canonical 1-39 check register
    python3 check.py --corpus [ROOT] --strict      # warnings become deck failures
    python3 tests/run.py                           # golden suite (profiles: 62, passed: 67)
    python3 tests/browser_quick_select.py          # real-browser test for quick select (exit 77: no chromium)

`check.py` exits 0 on a clean deck, 1 on a fatal (or, under `--strict`, a warning),
2 on usage errors. Corpus mode is read-only: it parses and checks, never writes into
a content root. Builds are deterministic — re-running rebuilds identical bytes.

As of 2026-10-19: `--corpus` reports 8/8 decks passed, banks 1, exit 0 (under
`--strict` 6/8: two decks carry concept tag-drift warnings, not deck defects).

## Rules

- **The handout is public.** It prints `cites:` (public citations), never the
  `sources:` working receipts. Check a handout for repo paths, "verify" notes and
  internal comments before anyone is pointed at it. Rebuild it with
  `tools/handout-pdf.py`; PDFs are build products and are not committed.

- **Zero install base.** There are no shipped users and no compatibility burden. Delete
  defects outright rather than grandfathering them behind deprecation shims.
- `+<role>` is the only overlay syntax. Attribution is canonicalized to `~`.
- Deck frontmatter carries the theme and declared `dur`; check 19 reports when effective
  timing drifts more than 30% from the declaration.
- Nothing that parses today may change meaning. The way to prove that is running the
  corpus check over the whole corpus, not arguing from a happy path.
- Ryan reviews and commits talk content himself; leave talkfiles uncommitted unless asked.
