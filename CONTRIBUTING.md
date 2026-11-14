# Contributing

Thanks for looking. Issues and pull requests are welcome.

## Setup

    git clone <repo> animatic && cd animatic
    uv sync            # or: python3 -m venv .venv && .venv/bin/pip install -e .
    uv run python tests/run.py

The suite should end with `failed: 0`. Browser tests (`tests/browser_*.py`) need
Chromium and exit 77 (skipped) without it.

## Before you open a pull request

- Run `python3 tests/run.py`. If you changed output on purpose, run
  `python3 tests/run.py --update-goldens`, read the diff in `tests/expected/`, and say in
  the PR why it changed.
- Run `python3 build.py --corpus` if you touched the parser, since nothing that parses
  today may change meaning.
- Keep builds deterministic: no timestamps, random values without a fixed seed, or
  machine paths in output.
- The talkfile format is the contract (`docs/format-spec-v1.md`). A change to the grammar
  needs a spec edit, a check in `check.py` where it can fail, and a test fixture under
  `tests/fixtures/constructs/`.
- Don't commit secrets, local paths, or media you don't have the right to share.

## Reporting a bug

Include the talkfile (or the smallest piece that shows it), the command you ran, what you
expected and what happened, and your Python version and OS. `python3 check.py <talk.md>`
output helps.

By contributing you agree your work is released under the MIT licence.
