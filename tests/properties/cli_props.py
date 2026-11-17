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

import getpass
import io
import json
import os
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


def _call(main_fn, argv: list) -> tuple:
    """(exit code, stdout, stderr) for a tools/*.py main(), both streams captured."""
    out, errbuf = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(errbuf):
        code = main_fn(argv)
    return code, out.getvalue(), errbuf.getvalue()


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

        dup = tmp / "dup"
        _write(dup / "a.talk.md", TALK.format(slug="a-three", title="A three"))

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

        # -- deck by name: the name you would type is the name it knows -------
        for name in ("out-solo", "solo-one", "SOLO"):
            got = cli.resolve_deck(name, corpus=str(corpus))
            if got != (one / "talk.md").resolve():
                err(errors, f"resolve_deck({name!r}) -> {got}, wanted the solo deck")
        try:
            cli.resolve_deck("a", corpus=str(corpus))     # a-one and a-three both
            err(errors, "a name matching two decks must be a refusal")
        except cli.DeckError:
            pass
        try:
            cli.resolve_deck("nope", corpus=str(corpus))
            err(errors, "an unknown deck name must be an error")
        except cli.DeckError:
            pass

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

        # -- find-talkfile.py: the reverse lookup, over the same table --------
        finder = cli.load_tool("find-talkfile")
        code, out, _ = _call(finder.main, ["--outdir", "out-solo",
                                           "--corpus", str(corpus)])
        want = str((one / "talk.md").resolve())
        if code != 0 or out.strip() != want:
            err(errors, f"find-talkfile mapped out-solo to {out.strip()!r} "
                        f"(exit {code}), wanted {want}")
        code, _, _ = _call(finder.main, ["--outdir", "out-a", "--corpus",
                                         str(corpus)])
        if code != 2:
            err(errors, f"find-talkfile must refuse an ambiguous outdir (exit 2), "
                        f"got {code}")
        code, _, _ = _call(finder.main, ["--outdir", "out-nope", "--corpus",
                                         str(corpus)])
        if code != 1:
            err(errors, "find-talkfile must exit 1 when nothing matches")

        # -- animatic token: stores 0600, never prints the value -----------------
        token_path = tmp / "cfg" / "waypoint-token"
        saved_env = {k: os.environ.get(k) for k in
                     ("ANIMATIC_WAYPOINT_TOKEN", "ANIMATIC_WAYPOINT_TOKEN_FILE")}
        saved_prompt = getpass.getpass
        try:
            os.environ.pop("ANIMATIC_WAYPOINT_TOKEN", None)
            os.environ["ANIMATIC_WAYPOINT_TOKEN_FILE"] = str(token_path)
            getpass.getpass = lambda prompt="": "TEST-TOKEN-not-real"
            code, out = _run(["token"])
            if code != 0:
                err(errors, f"animatic token exited {code}")
            if "TEST-TOKEN-not-real" in out:
                err(errors, "animatic token printed the token value")
            if not token_path.is_file():
                err(errors, "animatic token wrote no key file")
            else:
                if (token_path.stat().st_mode & 0o777) != 0o600:
                    err(errors, f"the key file must be 0600, got "
                                f"{token_path.stat().st_mode & 0o777:04o}")
                if token_path.read_text(encoding="utf-8").strip() != "TEST-TOKEN-not-real":
                    err(errors, "the key file does not hold the token")
            code, out = _run(["token", "--show"])
            if code != 0 or "sha256:" not in out:
                err(errors, f"animatic token --show: exit {code}, {out!r}")
            if "TEST-TOKEN-not-real" in out:
                err(errors, "animatic token --show printed the value")
            getpass.getpass = lambda prompt="": ""
            if _code(["token"]) == 0:
                err(errors, "an empty entry must not overwrite the key file")
        finally:
            getpass.getpass = saved_prompt
            for k, v in saved_env.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

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
        if manifest.get("waypoints") is not False:
            err(errors, "a deck with no waypoints must seal waypoints: false")
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

        # --inert: a copy that cannot publish, safe to hand out
        inert_dir = tmp / "out-inert"
        code, _ = _run(["pack", str(one / "talk.md"), "--out", str(inert_dir),
                        "--inert"])
        if code != 0:
            err(errors, f"pack --inert exited {code}")
        else:
            m = json.loads((inert_dir / cli.PACK_FILE).read_text(encoding="utf-8"))
            if m.get("waypoints") is not False:
                err(errors, "pack --inert must seal waypoints: false")

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
