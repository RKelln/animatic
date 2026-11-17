"""Corpus-harness property checks.

The golden suite's fixtures are deliberately synthetic and committed; the
corpus harness exists precisely so the REAL content root is never committed
and never copied into tests.  What belongs here is regression coverage for
the harness machinery itself, exercised over a tiny throwaway corpus tree
under /tmp:

- deck discovery (talk.md / *.talk.md; media/, _media/, out/, out-*/, dot
  dirs, and OKF-reserved index.md/log.md never discovered as decks);
- per-deck verdicts and exit codes (a fatal deck fails the run);
- check 5 (deck-slug collisions) firing once at corpus level;
- shared-bank sweep rows (dup slugs, bad YAML);
- tag drift pairs (levenshtein <= 2, >= 4 chars, numbered families
  skipped) and coverage rows with suggest-only tags;
- determinism: two runs of the same root print byte-identical output.
"""

from __future__ import annotations

import io
import os
import shutil
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

import check as check_mod

from .common import err

CLEAN_TALK = """\
---
type: Talk
format-version: 1.0
slug: {slug}
title: "{title}"
theme: workshop
tags: [{tags}]
---

## Movement 1

Opening words.

<!-- shot: river-one -->
### A river shot

Spoken over the river.

## Movement 2

Closing words.
"""


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _build_corpus(root: Path) -> None:
    """clean (tagged), drift-pair deck, fatal deck, skip strays, wiki root
    with one tagged concept + one untagged concept, and a shared bank."""
    _write(root / "clean" / "talk.md",
           CLEAN_TALK.format(slug="clean-deck", title="Clean deck",
                             tags="history, memory"))
    # histroy is a 1-edit misspelling of history -> must surface as drift
    _write(root / "drift-b" / "talk.md",
           CLEAN_TALK.format(slug="drift-deck", title="Drift deck",
                             tags="histroy"))
    # fatal: card slug equals a role word (check 3, unreachable visual)
    _write(root / "fatal" / "talk.md",
           CLEAN_TALK.format(slug="fatal-deck", title="Fatal deck",
                             tags=""))
    _write(root / "fatal" / "media" / "cards.yaml",
           "- slug: stat\n  status: have\n  type: image\n")
    # skip strays: stale build output, media-dir junk, reserved index name
    _write(root / "clean" / "out-lecture" / "talk.md",
           "---\nslug: stale\n---\n\nmust never be discovered\n")
    _write(root / "clean" / "media" / "stray.talk.md",
           "---\nslug: stray\n---\n\nmust never be discovered\n")
    _write(root / "clean" / "index.md",
           "---\ntitle: Index\ntags: [meta]\n---\n\nreserved\n")
    # wiki-like concept root: one tagged, one untagged whose body mentions
    # the shared vocabulary tag word-for-word -> suggestion must fire
    wiki = root / "wiki"
    _write(wiki / "tagged.md",
           "---\ntitle: Tagged\ntags: [gate-and-toll, meritocracy]\n---\n\n"
           "Body about gates and tolls.\n")
    _write(wiki / "tagged2.md",
           "---\ntitle: Tagged two\ntags: [gate-and-toll, history]\n---\n\n"
           "Another gate and toll page.\n")
    _write(wiki / "untagged.md",
           "---\ntitle: Untagged\ndescription: gates and tolls everywhere\n---\n\n"
           "More gate and toll text for the suggest scan.\n")
    _write(wiki / "raw" / "scrape.md",
           "---\ntitle: Scrape\n---\n\nmachine-collected, never a concept\n")
    # shared bank with a duplicate slug -> bank row must fire
    _write(root / "_media" / "library.yaml",
           "- slug: river-one\n  status: have\n  type: image\n"
           "- slug: river-one\n  status: have\n  type: image\n"
           "- slug: city-two\n  status: to-find\n  type: image\n")
    # slug collision pair across two decks (frontmatter slug slugifies equal)
    _write(root / "collide-a" / "talk.md",
           CLEAN_TALK.format(slug="Same-Name", title="Collide A", tags="x"))
    _write(root / "collide-b" / "talk.md",
           CLEAN_TALK.format(slug="same_name", title="Collide B", tags="y"))


def check(errors: list) -> None:
    tmp = Path(tempfile.mkdtemp(prefix="animatic-corpus-props-"))
    try:
        root = tmp / "corpus"
        _build_corpus(root)

        buf1 = io.StringIO()
        with redirect_stdout(buf1):
            code1 = check_mod.corpus_main(str(root))
        out1 = buf1.getvalue()

        # determinism: a second run must print byte-identical output
        buf2 = io.StringIO()
        with redirect_stdout(buf2):
            code2 = check_mod.corpus_main(str(root))
        if buf2.getvalue() != out1:
            err(errors, "corpus output is not deterministic across runs")
        if code2 != code1:
            err(errors, f"corpus exit code not deterministic: "
                        f"{code1} vs {code2}")

        # fatal deck -> exit 1, verdict line present
        if code1 != 1:
            err(errors, f"fatal deck must fail the corpus run, exit 1, "
                        f"got {code1}")
        if "FAIL  fatal" not in out1:
            err(errors, "no FAIL verdict for the fatal deck "
                        "(fatal/talk.md expected in output)")
        if "check  3" not in out1:
            err(errors, "fatal deck findings not printed (check 3 expected)")

        # discovery counts: 5 decks, no strays, reserved/skip names excluded
        n_decks = out1.count("deck  ")
        if n_decks != 5:
            err(errors, f"expected 5 decks discovered, got {n_decks}:\n{out1}")
        for banned in ("stale", "stray", "Index", "index.md", "raw/"):
            if banned in out1:
                # 'Index'/'index.md' must never be scanned; raw/ never swept
                err(errors, f"skip rule broken: {banned!r} appears in output")

        # collisions (check 5) once at corpus level
        if "frontmatter slug slugifies to" not in out1:
            err(errors, "deck-slug collision (check 5) not reported")
        if out1.count("collide") > 6:
            err(errors, "check 5 must fire once at corpus level, not per deck")

        # tag drift: histroy ~ history pair surfaced
        if "history ~ histroy" not in out1:
            err(errors, "tag drift pair history ~ histroy not reported")

        # coverage: the untagged wiki concept listed, with a suggestion drawn
        # from the shared vocabulary (gate-and-toll appears in its prose)
        if "wiki/untagged.md" not in out1:
            err(errors, "untagged concept not listed in coverage")
        if "suggest: gate-and-toll" not in out1:
            err(errors, "coverage suggestion for wiki/untagged.md missing "
                        "gate-and-toll")

        # bank sweep: dup slug row + card-count row for the shared bank
        if "duplicate slug" not in out1 or "3 cards" not in out1:
            err(errors, "bank sweep rows missing (dup slug / card count)")

        # clean decks pass (no fatal on clean/drift decks)
        for slug in ("clean-deck", "drift-deck"):
            if f"PASS" not in out1:
                err(errors, f"{slug} should PASS")

        # drift-scan internals: numbered families and 3-char acronyms are
        # deliberate, not drift; the spec's enclosive/enclosure shape fires
        vocab = check_mod.Counter({
            "phase-1": 2, "phase-2": 2, "l01": 9, "l02": 9,
            "ai": 4, "api": 4, "history": 3, "histroy": 1,
            "enclosive": 1, "enclosure": 2})
        pairs = check_mod._near_miss_pairs(vocab)
        got = {(a, b) for _, a, b in pairs}
        want = {("history", "histroy"), ("enclosive", "enclosure")}
        if not want <= got:
            err(errors, f"drift scan missed expected pairs: {want - got} "
                        f"(got {got})")
        if any(("phase-1" in p or "phase-2" in p) for p in got):
            err(errors, "numbered family phase-1/phase-2 must not drift")
        if ("ai", "api") in got:
            err(errors, "3-char acronym pair ai/api must not drift")

        # corpus.yaml is machine-local: relative roots mean repo-root-relative,
        # a missing file is None (not an error), and the tracked template is
        # the thing a machine copies.
        cfgdir = tmp / "cfg"
        _write(cfgdir / "corpus.yaml",
               "decks:\n  - corpus\nconcepts: []\nbanks: []\n")
        loaded = check_mod.load_corpus_config(cfgdir / "corpus.yaml")
        want_abs = (cfgdir / "corpus").resolve()
        if not loaded or loaded["decks"] != [want_abs]:
            err(errors, f"a relative corpus root must resolve against the "
                        f"config file's directory, got {loaded and loaded['decks']}")
        if check_mod.load_corpus_config(cfgdir / "absent.yaml") is not None:
            err(errors, "a missing corpus config must load as None")
        builtin = check_mod.builtin_corpus_config()
        if [p.name for p in builtin["decks"]] != ["examples"]:
            err(errors, "the built-in fallback must be the repo examples/ root")
        example = check_mod.corpus_config_path().with_name(check_mod.CORPUS_EXAMPLE)
        if not example.is_file():
            err(errors, f"{check_mod.CORPUS_EXAMPLE} is missing from the repo root")
        else:
            tmpl = check_mod.load_corpus_config(example)
            if not tmpl or not tmpl["decks"]:
                err(errors, f"{check_mod.CORPUS_EXAMPLE} must declare a deck root")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
