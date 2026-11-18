#!/usr/bin/env python3
"""cli.py — `animatic`: one door for a deck's whole life.

    animatic build [DECK] [BUILD FLAGS]     render present + document views
    animatic check [DECK ...] [--corpus [ROOT]] [--strict] [--json]
    animatic serve [DECK] [--watch]         serve built decks; with DECK and
                                            --watch, keep that deck building in
                                            the same process (one terminal)
    animatic decks [--json]                 the decks the corpus roots hold
    animatic pack  [DECK] [--out DIR] [--strict] [--verify] [--inert]
                                            a sealed, presentable copy
    animatic token [--show|--check]         store or inspect the waypoint token

DECK is a talkfile, a folder holding one (talk.md, or its only *.talk.md), or a
deck's name from the content roots — `W04`, `out-w04`, `w04-ai-job-search` — so
`animatic pack W04` works from any directory.  Omitted, it is the current
directory.  Two talkfiles in one folder is an error, never a guess.

The default output folder is `out-<first dash segment of the slug>` (out-w04 for
W04-ai-job-search), the rule `tools/find-talkfile.py` and pull-deck already use.
build.py's own default stays `out/`; this is the CLI's convention.

Flags after the deck are the module's own — `animatic build` takes build.py's
--watch/--theme/--quick-sections, `animatic serve` takes serve-deck.py's --port
and --bind.  The verbs own the deck question and the exit codes; they never
re-implement what the module already knows.

`animatic serve DECK --watch` is the one exception to "one verb, one module": it
runs the server in a thread beside build.py's watcher, in this process, because
keeping a deck building and reachable is one task.  `--bind tailscale` saves
looking up the address a laptop has to open.

`pack` is the release artifact: a plain build (never a watch build), a check, and
a path-free BUILD.json holding the hash of every file.  It is deterministic — pack
the same talkfile twice and BUILD.json is byte-identical — so `--verify` on another
machine is a real comparison, and a packed folder needs no server: open
present/index.html (docs/live-capture.md).

Exit: 0 ok · 1 the deck or the pack is not right · 2 usage.
"""
from __future__ import annotations

import argparse
import getpass
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Optional

import build as build_mod
import check as check_mod

ROOT = Path(__file__).resolve().parent
PACK_FORMAT = "animatic.pack.v1"
PACK_FILE = "BUILD.json"


class DeckError(Exception):
    """A deck question the CLI cannot answer (no deck, two decks, missing)."""


def _version() -> str:
    try:
        from importlib.metadata import version
        return version("animatic")
    except Exception:
        return "0+uninstalled"


# ---------------------------------------------------------------------------
# Deck identity: the one place that answers "which deck?" and "which folder?"
# ---------------------------------------------------------------------------

def resolve_deck(arg: Optional[str], base: Optional[Path] = None,
                 corpus: Optional[str] = None) -> Path:
    """A talkfile from ARG, else from BASE (default: the current directory).

    ARG may be a talkfile, a folder holding one, or a deck's name from the
    content roots — `W04`, `out-w04` or `w04-ai-job-search`, the names pull-deck
    and the deck folders use.  Never guesses between two candidates."""
    here = Path(base or Path.cwd()).expanduser()
    if arg:
        p = Path(arg).expanduser()
        if p.is_file():
            return p.resolve()
        if p.is_dir():
            here = p
        elif "/" in arg or "\\" in arg or arg.lower().endswith(".md"):
            raise DeckError(f"no such deck: {p}")
        else:
            return deck_by_name(arg, corpus=corpus)
    if (here / "talk.md").is_file():
        return (here / "talk.md").resolve()
    found = sorted(here.glob("*.talk.md"))
    if len(found) == 1:
        return found[0].resolve()
    if not found:
        raise DeckError(f"no talk.md in {here} — name a deck or cd into one")
    listed = "\n  ".join(str(f) for f in found)
    raise DeckError(f"{here} holds {len(found)} talkfiles; name one:\n  {listed}")


def deck_by_name(name: str, corpus: Optional[str] = None) -> Path:
    """A deck from the content roots, by the name you would type about it:
    its outdir (`out-w04`), its slug (`w04-ai-job-search`), or the slug's first
    segment (`w04`) — the same name pull-deck.sh takes.  Refuses to guess."""
    want = name.strip().lower()
    hits = {}
    for row in deck_rows(corpus=corpus):
        seg = row["slug"].split("-")[0]
        if (want in (row["outdir"], row["slug"], seg)
                or "out-" + want == row["outdir"]):
            hits[row["talkfile"]] = row
    if len(hits) == 1:
        return Path(next(iter(hits)))
    if not hits:
        raise DeckError(f"no deck called {name!r} under the content roots "
                        f"(`animatic decks` lists them)")
    listed = "\n  ".join(f"{h['outdir']:<10} {h['slug']:<24} {p}"
                         for p, h in sorted(hits.items()))
    raise DeckError(f"{name!r} matches {len(hits)} decks; name one:\n  {listed}")


def deck_meta(talk: Path) -> dict:
    """Frontmatter, tolerantly: the CLI must be able to list a half-saved deck."""
    meta, _ = check_mod.frontmatter_meta(talk)
    return meta if isinstance(meta, dict) else {}


def deck_slug(talk: Path) -> str:
    meta = deck_meta(talk)
    slug = str(meta.get("slug") or talk.parent.name).strip().lower()
    return slug or talk.parent.name.lower()


def deck_outdir(talk: Path) -> str:
    """`out-<first dash segment of the slug>` — the rule find-talkfile.py and
    pull-deck.sh already use, kept in one place here."""
    return "out-" + deck_slug(talk).split("-")[0]


def _split_deck(argv: list) -> tuple:
    """(DECK or None, the rest verbatim) — DECK is the first token, when it is
    a bare word.  A leading flag means the deck is the current directory."""
    if argv and not argv[0].startswith("-"):
        return argv[0], argv[1:]
    return None, list(argv)


def _has_out_flag(argv: list) -> bool:
    return any(t == "--out" or t.startswith("--out=") for t in argv)


def load_tool(name: str):
    """Import a hyphenated script in tools/ by path: a filename with a dash is
    not importable, and renaming it would move a documented command."""
    path = ROOT / "tools" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), path)
    if spec is None or spec.loader is None:
        raise DeckError(f"cannot load tools/{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _files_under(root: Path) -> list:
    """Every regular file in the built tree, relative to it, sorted.  The pack
    stamp itself is not a member of the set it describes."""
    return [p for p in sorted(root.rglob("*"))
            if p.is_file() and not (p.parent == root and p.name == PACK_FILE)]


# ---------------------------------------------------------------------------
# build
# ---------------------------------------------------------------------------

def cmd_build(argv: list) -> int:
    deck, rest = _split_deck(argv)
    talk = resolve_deck(deck)
    if not _has_out_flag(rest):
        rest = ["--out", deck_outdir(talk)] + rest
    return build_mod.main([str(talk)] + rest)


# ---------------------------------------------------------------------------
# check
# ---------------------------------------------------------------------------

def _cues_for(talk: Path) -> Optional[Path]:
    """The built cues.json for this deck, when one is lying where a build would
    have put it (CWD, or beside the talkfile)."""
    name = deck_outdir(talk) + "/cues.json"
    for candidate in (Path.cwd() / name, talk.parent / name):
        if candidate.is_file():
            return candidate
    return None


def cmd_check(argv: list) -> int:
    ap = argparse.ArgumentParser(prog="animatic check",
                                 description="The deterministic check suite, per "
                                             "deck or over the corpus roots.")
    ap.add_argument("decks", nargs="*", metavar="DECK",
                    help="talkfile or folder; none = the current directory")
    ap.add_argument("--corpus", nargs="?", const="__config__", metavar="ROOT",
                    help="corpus mode: with ROOT scan that directory; without, "
                         "the corpus.yaml content roots")
    ap.add_argument("--strict", action="store_true",
                    help="warnings count as failures (pre-delivery)")
    ap.add_argument("--json", action="store_true",
                    help="machine-readable findings (one deck at a time)")
    a = ap.parse_args(argv)

    if a.corpus is not None:
        if a.json:
            print("animatic check: --json covers named decks, not --corpus "
                  "(the corpus report is per-deck already)", file=sys.stderr)
            return 2
        return check_mod.corpus_main(None if a.corpus == "__config__" else a.corpus,
                                     strict=a.strict)

    talks = [resolve_deck(d) for d in a.decks] if a.decks else [resolve_deck(None)]
    if not a.json:
        return check_mod.main([str(t) for t in talks]
                             + (["--strict"] if a.strict else []))

    rows = []
    for talk in talks:
        report = check_mod.check_file(talk, strict=a.strict, cues_path=_cues_for(talk))
        counts = {sev: 0 for sev in (check_mod.FATAL, check_mod.WARNING,
                                     check_mod.INFO, check_mod.REPORT)}
        for f in report.findings:
            counts[f.severity] = counts.get(f.severity, 0) + 1
        rows.append({
            "talkfile": str(talk),
            "slug": deck_slug(talk),
            "outdir": deck_outdir(talk),
            "exit_code": report.exit_code,
            "fatal": counts[check_mod.FATAL] + (1 if report.parse_error else 0),
            "warning": counts[check_mod.WARNING],
            "info": counts[check_mod.INFO],
            "report": counts[check_mod.REPORT],
            "parse_error": report.parse_error,
            "findings": [{"check": f.check, "severity": f.severity,
                          "message": f.message, "line": f.line,
                          "screen": f.screen} for f in report.sorted()],
        })
    print(json.dumps({"decks": rows}, indent=2, sort_keys=True, ensure_ascii=False))
    return 1 if any(r["exit_code"] for r in rows) else 0


# ---------------------------------------------------------------------------
# serve
# ---------------------------------------------------------------------------

def _tailscale_ip() -> Optional[str]:
    """The box's tailnet IPv4, for `--bind tailscale`.  None if there is none:
    a missing client and a logged-out one both mean "no address to give"."""
    try:
        proc = subprocess.run(["tailscale", "ip", "-4"], capture_output=True,
                              text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    words = proc.stdout.split()
    return words[0] if proc.returncode == 0 and words else None


def cmd_serve(argv: list) -> int:
    ap = argparse.ArgumentParser(
        prog="animatic serve",
        description="Serve built decks over HTTP (Range, request log).  With "
                    "DECK and --watch it also keeps that deck building, so one "
                    "terminal and one command do both.")
    ap.add_argument("deck", nargs="?", metavar="DECK",
                    help="the deck to point at (and, with --watch, to rebuild)")
    ap.add_argument("--watch", action="store_true",
                    help="rebuild DECK on every save, in this same process")
    ap.add_argument("--reload", dest="reload", action="store_true", default=True,
                    help="with --watch (the default): open pages reload themselves "
                         "after each build")
    ap.add_argument("--no-reload", dest="reload", action="store_false",
                    help="with --watch: inject no reload snippet; refresh yourself")
    ap.add_argument("--verbose", action="store_true",
                    help="with --watch: the full build summary on every rebuild, "
                         "not just one line")
    ap.add_argument("--port", type=int, default=8787)
    ap.add_argument("--bind", default="127.0.0.1", metavar="ADDR",
                    help='address to listen on: an IP, or "tailscale" for this '
                         "box's tailnet address (default 127.0.0.1)")
    ap.add_argument("--directory", default=None, metavar="DIR",
                    help="folder to serve (default: the current directory)")
    ap.add_argument("--quiet", action="store_true",
                    help="no request log, and no per-build summary")
    a = ap.parse_args(argv)

    bind = a.bind
    if bind == "tailscale":
        ip = _tailscale_ip()
        if not ip:
            raise DeckError('--bind tailscale: `tailscale ip -4` returned no '
                            'address (is tailscaled up?)')
        bind = ip

    talk = resolve_deck(a.deck) if a.deck else None
    if a.watch and talk is None:
        raise DeckError("--watch needs a deck: animatic serve W14 --watch")
    out = deck_outdir(talk) if talk else None
    directory = a.directory or str(Path.cwd())

    mod = load_tool("serve-deck")
    try:
        srv = mod.make_server(bind, a.port, directory, quiet=a.quiet)
    except OSError as err:
        mod.bind_failure(err, bind, a.port)
        return 2
    mod.banner(directory, bind, a.port, quiet=a.quiet, deck=out)

    if talk is None:
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            print("\nstopped")
        return 0

    # The build does the blocking work on the main thread (its own Ctrl-C, its
    # own watcher lease); the server answers in a thread until that returns.
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    # No "watching…" line of our own: the build's first line says which deck it
    # is watching and that Ctrl-C stops it, and the banner already said the
    # server is up.  One statement each, not three.
    build_argv = [str(talk), "--out", out, "--watch"]
    for flag, on in (("--reload", a.reload), ("--no-reload", not a.reload),
                     ("--verbose", a.verbose), ("--quiet", a.quiet)):
        if on:
            build_argv.append(flag)
    try:
        return build_mod.main(build_argv)
    finally:
        srv.shutdown()


# ---------------------------------------------------------------------------
# decks
# ---------------------------------------------------------------------------

def _corpus_roots(corpus: Optional[str]) -> dict:
    """The declaration the checker itself uses, so `decks` cannot disagree with
    `check --corpus` about what content exists."""
    if corpus:
        cfg = check_mod.load_corpus_config(Path(corpus).expanduser())
        if cfg is None:
            raise DeckError(f"no corpus file at {corpus}")
        return cfg
    cfg = check_mod.load_corpus_config()
    if cfg is None:
        print(f"animatic decks: no {check_mod.CORPUS_CONFIG} beside the tool — "
              f"listing the built-in examples/ root "
              f"(cp {check_mod.CORPUS_EXAMPLE} {check_mod.CORPUS_CONFIG} for yours)",
              file=sys.stderr)
        return check_mod.builtin_corpus_config()
    return cfg


def deck_rows(corpus: Optional[str] = None, cfg: Optional[dict] = None) -> list:
    """The identity table: one row per deck under the content roots.

    `outdir`, `slug`, `title`, `theme`, `dur`, `talkfile`.  Shared by
    `animatic decks` and `tools/find-talkfile.py`, so the out-folder rule and the
    corpus question exist in exactly one place."""
    cfg = cfg if cfg is not None else _corpus_roots(corpus)
    rows = []
    for root in cfg.get("decks", []):
        if not root.is_dir():
            print(f"animatic: skipping missing content root {root}",
                  file=sys.stderr)
            continue
        for talk in check_mod.discover_decks(root):
            meta = deck_meta(talk)
            rows.append({
                "outdir": deck_outdir(talk),
                "slug": deck_slug(talk),
                "title": str(meta.get("title") or ""),
                "theme": str(meta.get("theme") or ""),
                "dur": str(meta.get("dur") or ""),
                "talkfile": str(talk),
            })
    rows.sort(key=lambda r: (r["outdir"], r["talkfile"]))
    return rows


def cmd_decks(argv: list) -> int:
    ap = argparse.ArgumentParser(prog="animatic decks",
                                 description="Every deck the content roots hold, "
                                             "with the folder it builds into.")
    ap.add_argument("--json", action="store_true", help="machine-readable rows")
    ap.add_argument("--corpus", metavar="PATH",
                    help="a corpus file other than the repo's corpus.yaml")
    a = ap.parse_args(argv)

    cfg = _corpus_roots(a.corpus)
    rows = deck_rows(cfg=cfg)

    if a.json:
        print(json.dumps({"decks": rows}, indent=2, sort_keys=True,
                         ensure_ascii=False))
        return 0
    if not rows:
        print("animatic decks: the content roots hold no decks")
        return 0
    width = max(len(r["outdir"]) for r in rows)
    for r in rows:
        print(f"{r['outdir']:<{width}}  {r['slug']:<26}  {r['theme']:<9}  "
              f"{r['dur']:<7}  {r['talkfile']}")
    print(f"\n{len(rows)} deck(s) under "
          f"{', '.join(str(p) for p in cfg.get('decks', []))}")
    return 0


# ---------------------------------------------------------------------------
# token (waypoint publishing)
# ---------------------------------------------------------------------------

def _fingerprint(token: str) -> str:
    """Enough to recognise a token, never enough to use one."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:12]


def _token_path() -> Path:
    return Path(os.environ.get(build_mod.TOKEN_FILE_ENV, "").strip()
                or build_mod.TOKEN_FILE).expanduser()


def cmd_token(argv: list) -> int:
    ap = argparse.ArgumentParser(
        prog="animatic token",
        description="The waypoint publishing token: store it, or report on it. "
                    "Never prints the token itself.")
    group = ap.add_mutually_exclusive_group()
    group.add_argument("--show", action="store_true",
                       help="a fingerprint of the token in use")
    group.add_argument("--check", action="store_true",
                       help="where the token comes from, and whether the file is safe")
    a = ap.parse_args(argv)

    path = _token_path()
    token, source = build_mod.waypoint_token()

    if a.show or a.check:
        if not token:
            print("token    : none — store one with `animatic token` (it is kept "
                  f"in {path})", file=sys.stderr)
            return 1
        print(f"token    : sha256:{_fingerprint(token)} ({len(token)} chars) "
              f"from {source}")
        if a.check:
            if source == "ANIMATIC_WAYPOINT_TOKEN":
                print(f"note     : the environment wins over {path}; unset "
                      f"ANIMATIC_WAYPOINT_TOKEN to use the file")
            else:
                try:
                    mode = path.stat().st_mode & 0o777
                    safe = (mode & 0o077) == 0
                    print(f"file     : {path} mode {mode:04o}"
                          + ("" if safe else "  (group or others can read it: "
                                             "chmod 600)"))
                except OSError as exc:
                    print(f"file     : {path} ({exc})", file=sys.stderr)
        return 0

    entered = getpass.getpass("waypoint token (not echoed): ").strip()
    if not entered:
        print("animatic token: nothing entered; the token is unchanged",
              file=sys.stderr)
        return 2
    try:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        # create with 0600 in one call: no window where the file is readable
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(entered + "\n")
        os.chmod(path, 0o600)
    except OSError as exc:
        print(f"animatic token: cannot write {path}: {exc}", file=sys.stderr)
        return 1
    print(f"stored   : sha256:{_fingerprint(entered)} ({len(entered)} chars) "
          f"in {path}")
    if os.environ.get("ANIMATIC_WAYPOINT_TOKEN", "").strip():
        print("note     : ANIMATIC_WAYPOINT_TOKEN is set in this shell and wins; "
              "unset it to use the file", file=sys.stderr)
    print("next     : every build reads it — a remote --watch included")
    return 0


# ---------------------------------------------------------------------------
# pack
# ---------------------------------------------------------------------------

def _manifest(talk: Path, out: Path, *, strict: bool) -> dict:
    """The sealed record of one build.  Path-free on purpose: check 17 and the
    nav/html property tests forbid machine-local paths in an artifact, and this
    one is meant to travel.  No timestamps: re-packing the same talkfile must
    produce identical bytes, or `--verify` cannot mean anything."""
    meta = deck_meta(talk)
    talk_bytes = talk.stat().st_size
    files = {p.relative_to(out).as_posix(): _sha256(p) for p in _files_under(out)}
    return {
        "format": PACK_FORMAT,
        "animatic": _version(),
        "slug": deck_slug(talk),
        "title": str(meta.get("title") or ""),
        "theme": str(meta.get("theme") or ""),
        "dur": str(meta.get("dur") or ""),
        "watch": False,
        # Publishing state, read off the built page rather than assumed: a packed
        # copy can carry the waypoint token (it posts from the room), and that
        # should be visible in the manifest, not discovered later.
        "waypoints": bool(build_mod.publishes_waypoints(
            out / "present" / "index.html")),
        "strict": bool(strict),
        "source": {"talkfile_sha256": _sha256(talk), "bytes": talk_bytes},
        "total_bytes": sum((out / rel).stat().st_size for rel in files),
        "files": files,
    }


def _write_manifest(out: Path, manifest: dict) -> Path:
    path = out / PACK_FILE
    text = json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    path.write_text(text, encoding="utf-8")
    return path


def verify_pack(out: Path) -> int:
    """Re-hash a packed folder against its own BUILD.json.  Works anywhere the
    folder travels: this is the venue check, and it needs no source tree."""
    path = out / PACK_FILE
    if not path.is_file():
        print(f"animatic pack --verify: no {PACK_FILE} in {out} — this is not a "
              f"packed deck (run `animatic pack`)", file=sys.stderr)
        return 1
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"animatic pack --verify: unreadable {PACK_FILE}: {exc}",
              file=sys.stderr)
        return 1
    if manifest.get("format") != PACK_FORMAT:
        print(f"animatic pack --verify: {PACK_FILE} is "
              f"{manifest.get('format')!r}, not {PACK_FORMAT}", file=sys.stderr)
        return 1

    problems = []
    if manifest.get("watch") is not False:
        problems.append("the manifest says this is a watch build")
    if (out / "_watch.js").exists():
        problems.append("this copy carries _watch.js: it is a watch build, "
                        "not a packed one")
    files = manifest.get("files") or {}
    for rel, want in sorted(files.items()):
        p = out / rel
        if not p.is_file():
            problems.append(f"missing: {rel}")
        elif _sha256(p) != want:
            problems.append(f"changed: {rel}")
    for p in _files_under(out):
        rel = p.relative_to(out).as_posix()
        if rel not in files:
            problems.append(f"not in the manifest: {rel}")

    if problems:
        print(f"animatic pack --verify: {out} does not match its manifest",
              file=sys.stderr)
        for problem in problems[:20]:
            print(f"  {problem}", file=sys.stderr)
        if len(problems) > 20:
            print(f"  … and {len(problems) - 20} more", file=sys.stderr)
        return 1
    print(f"sealed   : {manifest.get('slug')} · {len(files)} file(s) · "
          f"{manifest.get('total_bytes', 0) / (1 << 20):.1f} MB · hashes match")
    return 0


def cmd_pack(argv: list) -> int:
    deck, rest = _split_deck(argv)
    ap = argparse.ArgumentParser(prog="animatic pack",
                                 description="Seal a presentable build: plain "
                                             "build, check, and a hashed manifest.")
    ap.add_argument("--out", metavar="DIR", help="output folder (default "
                    "out-<slug> in the current directory)")
    ap.add_argument("--strict", action="store_true",
                    help="warnings fail the pack, as pre-delivery")
    ap.add_argument("--verify", action="store_true",
                    help="do not build: re-hash an existing pack against BUILD.json")
    ap.add_argument("--inert", action="store_true",
                    help="seal a copy that cannot publish waypoints (safe to hand "
                         "out), whatever the token sources say")
    a = ap.parse_args(rest)

    def _out_path(value: Optional[str], default_name: str) -> Path:
        p = Path(value).expanduser() if value else Path(default_name)
        return (p if p.is_absolute() else Path.cwd() / p).resolve()

    if a.verify:
        # --verify is about a folder that already exists, possibly on another
        # machine with no source tree: it needs --out, not a deck.
        if a.out:
            return verify_pack(_out_path(a.out, ""))
        if deck:
            return verify_pack(_out_path(None, deck_outdir(resolve_deck(deck))))
        raise DeckError("pack --verify needs --out DIR (or a DECK to derive "
                        "out-<slug>)")

    talk = resolve_deck(deck)
    out = _out_path(a.out, deck_outdir(talk))

    rc = build_mod.main([str(talk), "--out", str(out)]
                        + (["--inert"] if a.inert else []))
    if rc != 0:
        print(f"animatic pack: the build failed, so nothing was sealed ({out})",
              file=sys.stderr)
        return 1
    if (out / "_watch.js").exists():
        print(f"animatic pack: {out} holds _watch.js — a watcher is building it. "
              f"Stop that watch and pack again.", file=sys.stderr)
        return 1

    report = check_mod.check_file(talk, strict=a.strict,
                                  cues_path=out / "cues.json")
    if report.exit_code != 0:
        blocking = (check_mod.FATAL, check_mod.WARNING) if a.strict \
            else (check_mod.FATAL,)
        print(f"animatic pack: {talk} does not pass the check, so nothing was "
              f"sealed:", file=sys.stderr)
        for f in report.sorted():
            if f.severity in blocking:
                where = f" line {f.line}" if f.line else ""
                print(f"  {f.severity} check {f.check}{where}  {f.message}",
                      file=sys.stderr)
        if not a.strict and any(f.severity == check_mod.WARNING
                                for f in report.findings):
            print("  (warnings do not fail a pack; add --strict to make them)",
                  file=sys.stderr)
        return 1

    manifest = _manifest(talk, out, strict=a.strict)
    _write_manifest(out, manifest)
    print(f"sealed   : {out}")
    print(f"           {manifest['slug']} · {len(manifest['files'])} file(s) · "
          f"{manifest['total_bytes'] / (1 << 20):.1f} MB · {PACK_FILE} written")
    if manifest["waypoints"]:
        print("publishing: this copy carries the waypoint token — leave it in "
              "the room, do not hand it out or publish the folder")
    elif a.inert:
        print("publishing: none (--inert: this copy cannot publish)")
    else:
        print("publishing: none (the deck posts no waypoints)")
    print("present  : open present/index.html (file:// is a supported way to "
          "present — docs/live-capture.md)")
    print("verify   : animatic pack --verify --out " + str(out))
    return 0


# ---------------------------------------------------------------------------
# dispatch
# ---------------------------------------------------------------------------

VERBS = {
    "build": cmd_build,
    "check": cmd_check,
    "serve": cmd_serve,
    "decks": cmd_decks,
    "pack": cmd_pack,
    "token": cmd_token,
}

USAGE = """animatic — decks, checks, builds and packs under one name

  animatic build [DECK] [BUILD FLAGS]   render present + document views
  animatic check [DECK ...] [--corpus [ROOT]] [--strict] [--json]
  animatic serve [DECK] [--watch] [--port N] [--bind ADDR|tailscale]
                                        serve built decks; with DECK and --watch,
                                        keep that deck building in this process
                                        (one command, one terminal)
  animatic decks [--json]               the decks the content roots hold
  animatic pack  [DECK] [--out DIR] [--strict] [--verify] [--inert]
                                        a sealed, presentable copy
  animatic token [--show|--check]       store or inspect the waypoint token
                                        (kept in ~/.config/animatic/waypoint-token)

DECK is a talkfile, a folder holding one, or a deck's name (W04); omitted, it is
the current directory. Output defaults to out-<slug>. Exit: 0 ok, 1 not right,
2 usage.
"""


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print(USAGE, end="")
        return 2
    if argv[0] in ("-h", "--help"):
        print(USAGE, end="")
        return 0
    if argv[0] in ("-V", "--version"):
        print(f"animatic {_version()}")
        return 0
    verb = argv.pop(0)
    fn = VERBS.get(verb)
    if fn is None:
        print(f"animatic: unknown command {verb!r} (try animatic --help)",
              file=sys.stderr)
        return 2
    try:
        return int(fn(argv) or 0)
    except DeckError as exc:
        print(f"animatic {verb}: {exc}", file=sys.stderr)
        return 2
    except BrokenPipeError:                  # `animatic decks | head`
        return 0
    except KeyboardInterrupt:
        print()
        return 130


if __name__ == "__main__":
    sys.exit(main())
