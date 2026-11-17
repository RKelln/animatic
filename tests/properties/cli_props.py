"""CLI property checks (`cli.py`: one door for deck identity, build, check, pack).

The CLI's whole value is that it answers "which deck?" and "which folder?" in one
place, and that `pack` produces a release artifact you can verify on another
machine.  What belongs here:

- deck resolution: an explicit talkfile, a folder's talk.md, a folder's only
  *.talk.md, and a refusal (never a guess) when two candidates exist;
- the out-folder rule matches find-talkfile.py / pull-deck (out- + first dash
  segment of the slug);
- `decks --json` lists a corpus with that rule applied;
- `check --json` carries the same verdict the text form does;
- `pack`: builds, refuses to seal a watch build, writes a path-free manifest,
  is deterministic (two packs, identical bytes), and `--verify` catches a
  changed file, an unlisted file and a missing manifest.
"""
from __future__ import annotations

import io
import json
import shutil
import sys
import tempfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import cli

from .common import err

TALK = """\
---
type: Talk
format-version: 1.0
slug: {slug}
title: "{title}"
theme: workshop
dur: "5 min"
---

<!-- shot: black -->
# {title}

<!-- shot: black -->
The second screen.
"""


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _run(argv: list) -> tuple:
    """(exit code, stdout) with the CLI's chatter captured."""
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = cli.main(argv)
    return code, buf.getvalue()


def _code(argv: list) -> int:
    """Exit code only: every word the CLI says is swallowed, both streams."""
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        return cli.main(argv)


def check(errors: list) -> None:
    tmp = Path(tempfile.mkdtemp(prefix="animatic-cli-props-"))
    try:
        # -- deck resolution ---------------------------------------------------
        one = tmp / "one"
        _write(one / "talk.md", TALK.format(slug="solo-one", title="Solo"))
        if cli.resolve_deck(str(one)) != (one / "talk.md").resolve():
            err(errors, "a folder's talk.md must resolve to that talkfile")

        dash = tmp / "dash"
        _write(dash / "only.talk.md", TALK.format(slug="dash-one", title="Dash"))
        if cli.resolve_deck(None, base=dash) != (dash / "only.talk.md").resolve():
            err(errors, "a folder's only *.talk.md must resolve when talk.md is absent")

        two = tmp / "two"
        _write(two / "a.talk.md", TALK.format(slug="a-one", title="A"))
        _write(two / "b.talk.md", TALK.format(slug="b-two", title="B"))
        try:
            cli.resolve_deck(str(two))
            err(errors, "two talkfiles must be a refusal, not a guess")
        except cli.DeckError:
            pass

        empty = tmp / "empty"
        empty.mkdir()
        try:
            cli.resolve_deck(str(empty))
            err(errors, "a folder with no talkfile must be an error")
        except cli.DeckError:
            pass

        # -- the out-folder rule ----------------------------------------------
        w04 = tmp / "W04-ai-job-search"
        _write(w04 / "talk.md", TALK.format(slug="w04-ai-job-search", title="W04"))
        if cli.deck_outdir(w04 / "talk.md") != "out-w04":
            err(errors, f"out-<first slug segment> rule broken: "
                        f"{cli.deck_outdir(w04 / 'talk.md')}")
        if cli.deck_slug(w04 / "talk.md") != "w04-ai-job-search":
            err(errors, "slug must come from the frontmatter")

        # -- decks --json ------------------------------------------------------
        corpus = tmp / "corpus.yaml"
        corpus.write_text(f"decks:\n  - {tmp}\nconcepts: []\nbanks: []\n",
                          encoding="utf-8")
        code, out = _run(["decks", "--json", "--corpus", str(corpus)])
        if code != 0:
            err(errors, f"decks --json exited {code}")
        try:
            rows = json.loads(out)["decks"]
        except (json.JSONDecodeError, KeyError) as exc:
            err(errors, f"decks --json is not JSON: {exc}")
            rows = []
        outdirs = {r["outdir"] for r in rows}
        for want in ("out-solo", "out-dash", "out-w04"):
            if want not in outdirs:
                err(errors, f"decks --json missing {want} (got {sorted(outdirs)})")
        for r in rows:
            for key in ("outdir", "slug", "title", "theme", "dur", "talkfile"):
                if key not in r:
                    err(errors, f"decks --json row missing {key!r}: {r}")

        # -- check --json ------------------------------------------------------
        code, out = _run(["check", "--json", str(one / "talk.md")])
        try:
            row = json.loads(out)["decks"][0]
        except (json.JSONDecodeError, KeyError, IndexError) as exc:
            err(errors, f"check --json is not JSON: {exc}")
            row = {}
        if code != 0:
            err(errors, f"a clean deck must exit 0 from check --json, got {code}")
        if row and row.get("fatal") != 0:
            err(errors, f"clean deck reported {row.get('fatal')} fatals")
        if code == 0 and row and row.get("exit_code") != 0:
            err(errors, "check --json disagrees with its own exit code")

        # -- pack --------------------------------------------------------------
        out_dir = tmp / "out-pack"
        code, _ = _run(["pack", str(one / "talk.md"), "--out", str(out_dir)])
        if code != 0:
            err(errors, f"pack exited {code}")
        manifest_path = out_dir / cli.PACK_FILE
        if not manifest_path.is_file():
            err(errors, "pack wrote no BUILD.json")
            return
        if (out_dir / "_watch.js").exists():
            err(errors, "a packed folder must never carry _watch.js")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("watch") is not False:
            err(errors, "the manifest must say watch is false")
        if manifest.get("format") != cli.PACK_FORMAT:
            err(errors, f"manifest format is {manifest.get('format')!r}")
        files = manifest.get("files") or {}
        if "present/index.html" not in files:
            err(errors, "the manifest must hash present/index.html")
        if str(tmp) in manifest_path.read_text(encoding="utf-8"):
            err(errors, "BUILD.json must be path-free (check 17 rules)")

        first = manifest_path.read_bytes()
        code, _ = _run(["pack", str(one / "talk.md"), "--out", str(out_dir)])
        if code != 0:
            err(errors, f"re-pack exited {code}")
        if manifest_path.read_bytes() != first:
            err(errors, "pack is not deterministic: two packs, different manifests")

        if _code(["pack", "--verify", "--out", str(out_dir)]) != 0:
            err(errors, "verify rejected an untouched pack")

        target = out_dir / "present" / "index.html"
        target.write_bytes(target.read_bytes() + b"<!--tampered-->")
        if _code(["pack", "--verify", "--out", str(out_dir)]) == 0:
            err(errors, "verify accepted a pack with a changed file")

        (out_dir / "extra.txt").write_text("not in the manifest", encoding="utf-8")
        if _code(["pack", "--verify", "--out", str(out_dir)]) == 0:
            err(errors, "verify accepted an unlisted file")

        if _code(["pack", "--verify", "--out", str(tmp)]) == 0:
            err(errors, "verify must refuse a folder with no BUILD.json")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
