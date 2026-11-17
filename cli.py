#!/usr/bin/env python3
"""cli.py — `animatic`: one door for a deck's whole life.

    animatic build [DECK] [BUILD FLAGS]     render present + document views
    animatic check [DECK ...] [--corpus [ROOT]] [--strict] [--json]
    animatic serve [SERVE FLAGS]            serve built decks on localhost
    animatic decks [--json]                 the decks the corpus roots hold
    animatic pack  [DECK] [--out DIR] [--strict] [--verify]
                                            a sealed, presentable copy

DECK is a talkfile or a folder holding one (talk.md, or its only *.talk.md).
Omitted, it is the current directory, so `cd decks/W04-ai-job-search && animatic
build` does the obvious thing.  Two talkfiles in one folder is an error, never a
guess.

The default output folder is `out-<first dash segment of the slug>` (out-w04 for
W04-ai-job-search), the rule `tools/find-talkfile.py` and pull-deck already use.
build.py's own default stays `out/`; this is the CLI's convention.

Flags after the deck are the module's own — `animatic build` takes build.py's
--watch/--theme/--quick-sections, `animatic serve` takes serve-deck.py's --port
and --bind.  The verbs own the deck question and the exit codes; they never
re-implement what the module already knows.

`pack` is the release artifact: a plain build (never a watch build), a check, and
a path-free BUILD.json holding the hash of every file.  It is deterministic — pack
the same talkfile twice and BUILD.json is byte-identical — so `--verify` on another
machine is a real comparison, and a packed folder needs no server: open
present/index.html (docs/live-capture.md).

Exit: 0 ok · 1 the deck or the pack is not right · 2 usage.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
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

def resolve_deck(arg: Optional[str], base: Optional[Path] = None) -> Path:
    """A talkfile from ARG (a file, or a folder holding one), else from BASE
    (default: the current directory).  Never guesses between two candidates."""
    here = Path(base or Path.cwd()).expanduser()
    if arg:
        p = Path(arg).expanduser()
        if p.is_file():
            return p.resolve()
        if not p.is_dir():
            raise DeckError(f"no such deck: {p}")
        here = p
    if (here / "talk.md").is_file():
        return (here / "talk.md").resolve()
    found = sorted(here.glob("*.talk.md"))
    if len(found) == 1:
        return found[0].resolve()
    if not found:
        raise DeckError(f"no talk.md in {here} — name a deck or cd into one")
    listed = "\n  ".join(str(f) for f in found)
    raise DeckError(f"{here} holds {len(found)} talkfiles; name one:\n  {listed}")


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

def cmd_serve(argv: list) -> int:
    mod = load_tool("serve-deck")
    return int(mod.main(argv) or 0)


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

    rc = build_mod.main([str(talk), "--out", str(out)])
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
}

USAGE = """animatic — decks, checks, builds and packs under one name

  animatic build [DECK] [BUILD FLAGS]   render present + document views
  animatic check [DECK ...] [--corpus [ROOT]] [--strict] [--json]
  animatic serve [SERVE FLAGS]          serve built decks on localhost
  animatic decks [--json]               the decks the content roots hold
  animatic pack  [DECK] [--out DIR] [--strict] [--verify]
                                        a sealed, presentable copy

DECK is a talkfile or a folder holding one; omitted, it is the current
directory. Output defaults to out-<slug>. Exit: 0 ok, 1 not right, 2 usage.
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
