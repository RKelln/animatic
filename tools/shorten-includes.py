#!/usr/bin/env python3
"""shorten-includes — rewrite `<!-- include: ../_sections/x.section.md -->` to the bare name.

    python3 tools/shorten-includes.py [PATH ...] [--write] [--quiet]

A bare name (`<!-- include: ai-terms -->`) is a section in the talk's section
directory, so the long form is noise. This walks talkfiles and section files,
finds every include the short form can express EXACTLY, and rewrites it:

    <!-- include: ../_sections/ai-terms.section.md -->      ->  <!-- include: ai-terms -->
    <!-- include: ../_sections/tpl-privacy.section.md live -->  ->  <!-- include: tpl-privacy live -->

What it will NOT touch, by design:

- an include whose target is NOT `<sections>/<stem>.section.md`: another folder,
  a one-off file, or a name that would still contain a dot. The bare name could
  not reach that file, so the path stays and the reason is printed.
- a name already short, and anything inside a fenced code block (a fence shows
  the directive, it does not run it).

Nothing is written without `--write`: the default prints the plan. Every rewrite
is PROVED before it lands — the file is parsed old and new and the screens must
match (same count, same block kinds, same text) with the same set of resolved
include files. A rewrite that cannot be proved is refused, not written.

    PATH  deck directories, talkfiles, section files or content roots (scanned
          for talk.md, *.talk.md and *.section.md). None -> corpus.yaml roots.

Exit: 0 clean (wrote, or had nothing to do), 1 a rewrite was refused or
verification failed, 2 usage.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import check as check_mod        # noqa: E402  (corpus.yaml roots)
import talkparse                 # noqa: E402  (the one include resolver)

SOURCE_SUFFIXES = (".section.md",)


def _iter_sources(path: Path, out: list) -> None:
    """A deck directory, a content root, or the file itself; sorted, so the plan
    reads in a stable order. `out/`, `media/`, `_media/` and dot dirs are skipped:
    they hold build products and cards, never authored prose."""
    if path.is_file():
        if path.name.endswith(".md"):
            out.append(path)
        return
    if not path.is_dir():
        return
    for d in sorted(path.iterdir()):
        if d.is_file() and d.name.endswith(".md"):
            if d.name == "talk.md" or d.name.endswith(".talk.md") \
                    or d.name.endswith(SOURCE_SUFFIXES):
                out.append(d)
        elif d.is_dir() and not d.name.startswith(".") \
                and d.name not in ("media", "_media", "out") \
                and not d.name.startswith("out-"):
            _iter_sources(d, out)


def _sections_dir(path: Path, meta: dict) -> Path:
    """Where a bare name in THIS file resolves.

    A talkfile answers with the parser's own rule (`include_sections:`, else
    `../_sections`), so the tool cannot disagree with the engine. A section file
    has no say in it — the talk does — but a section sits IN the deck's section
    directory by construction, so its own directory is the one a talk's names
    resolve in."""
    if path.name.endswith(SOURCE_SUFFIXES) and "include_sections" not in meta:
        return path.parent
    return talkparse._include_sections(meta, path, str(path))


def _shorten(token: str, path: Path, sdir: Path) -> tuple:
    """(bare name, '') when the token is exactly `<sdir>/<stem>.section.md`,
    else ('', reason it cannot be shortened)."""
    if talkparse._is_include_name(token):
        return "", "already a name"
    target = (path.parent / token).resolve()
    if target.parent != sdir:
        return "", f"not in {sdir}"
    stem = target.name[:-len(talkparse.INCLUDE_SECTION_EXT)] \
        if target.name.endswith(talkparse.INCLUDE_SECTION_EXT) else ""
    if not stem or not talkparse._is_include_name(stem):
        return "", f"{target.name} is not a `<name>{talkparse.INCLUDE_SECTION_EXT}` file"
    if not target.is_file():
        return "", "no such file"
    return stem, ""


def _sig(talk) -> tuple:
    """What an include rewrite must leave untouched: the screens, block for
    block (a dropped `live` flag changes `live_only`, so that is in here too),
    and the files the talk resolves to."""
    screens = tuple(
        (tuple(b.kind for b in s.blocks),
         tuple(b.text for b in s.blocks if hasattr(b, "text")),
         s.live_only, s.shelf)
        for s in talk.screens)
    return screens, tuple(str(p) for p in talk.includes)


def _proved(new_text: str, path: Path) -> str:
    """'' when the rewrite means the same thing, else the reason it does not.
    The new text is parsed from a temp file in the SAME directory, dot-named so
    nothing else picks it up: relative includes resolve exactly as they will
    once written."""
    tmp = path.parent / f".{path.name}.shorten-check"
    try:
        tmp.write_text(new_text, encoding="utf-8")
        try:
            before = talkparse.build_talk(path)
        except ValueError as exc:
            return f"the file does not parse as it stands: {exc}"
        after = talkparse.build_talk(tmp)
        if _sig(before) != _sig(after):
            return "the screens would change"
        if tuple(str(p) for p in before.includes) != tuple(str(p) for p in after.includes):
            return "the resolved include files would change"
        return ""
    except ValueError as exc:
        return f"the rewritten file would not parse: {exc}"
    finally:
        tmp.unlink(missing_ok=True)


def _plan(path: Path) -> tuple:
    """(changes, skips) for one file: [(line, before, after)], [(line, token, reason)]."""
    text = path.read_text(encoding="utf-8")
    meta, body = talkparse._lex_frontmatter(text, str(path))
    body_start = len(text.split("\n")) - len(body)      # file line index of body[0]
    fenced = talkparse.fenced_line_indexes(body)
    sdir = _sections_dir(path, meta)
    changes, skips = [], []
    for i, line in enumerate(body):
        m = talkparse.INCLUDE_RE.match(line)
        if not m:
            continue
        if i in fenced:
            skips.append((body_start + i + 1, m.group(1), "inside a fenced code block"))
            continue
        stem, why = _shorten(m.group(1), path, sdir)
        if not stem:
            if why != "already a name":
                skips.append((body_start + i + 1, m.group(1), why))
            continue
        changes.append((body_start + i + 1, m.group(1), stem))
    return text, body, body_start, changes, skips


def _rewritten(body: list, changes: list, body_start: int) -> str:
    """The body with each directive's token swapped, everything else byte-for-byte
    (indentation, comment spacing and flags kept as written).  `changes` carry
    file line numbers; `body` is indexed from the end of the frontmatter."""
    out = list(body)
    for line_no, before, after in changes:
        i = line_no - 1 - body_start
        m = talkparse.INCLUDE_RE.match(out[i])
        if m is None:          # cannot happen (the line was matched in _plan)
            continue
        out[i] = out[i][:m.start(1)] + after + out[i][m.end(1):]
    return "\n".join(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Rewrite long-form `<!-- include: ... -->` directives to the "
                    "bare section name. Prints the plan; --write applies it.")
    ap.add_argument("paths", nargs="*",
                    help="deck dirs, talkfiles, section files or content roots; "
                         "none = the corpus.yaml deck roots")
    ap.add_argument("--write", action="store_true", help="apply the rewrites")
    ap.add_argument("--quiet", action="store_true", help="only changed files and errors")
    a = ap.parse_args(argv)

    if a.paths:
        roots = [Path(p).expanduser() for p in a.paths]
    else:
        cfg = check_mod.load_corpus_config() or {}
        roots = [Path(p) for p in cfg.get("decks", [])]
        if not roots:
            print("shorten-includes: no paths given and corpus.yaml lists no deck roots",
                  file=sys.stderr)
            return 2

    sources: list = []
    for r in roots:
        _iter_sources(r, sources)
    if not sources:
        print(f"shorten-includes: no talkfiles or sections under "
              f"{', '.join(str(r) for r in roots)}", file=sys.stderr)
        return 2

    changed = skipped = refused = 0
    for path in sorted(set(sources)):
        text, body, body_start, changes, skips = _plan(path)
        if not changes:
            if skips and not a.quiet:
                print(f"{path}")
                for line_no, token, why in skips:
                    print(f"  keep  line {line_no}: {token}  ({why})")
            skipped += len(skips)
            continue
        new_text = "".join([
            "\n".join(text.split("\n")[:body_start]),
            "\n" if body_start else "",
            _rewritten(body, changes, body_start)])
        why = _proved(new_text, path)
        if why:
            refused += 1
            print(f"REFUSED  {path}: {why}", file=sys.stderr)
            continue
        changed += len(changes)
        verb = "wrote" if a.write else "would write"
        print(f"{verb}  {path}")
        for line_no, before, after in changes:
            print(f"  line {line_no}: {before} -> {after}")
        for line_no, token, rwhy in skips:
            print(f"  keep  line {line_no}: {token}  ({rwhy})")
        if a.write:
            path.write_text(new_text, encoding="utf-8")

    verb = "rewrote" if a.write else "would rewrite"
    print(f"\n{verb} {changed} directive(s) in {len(set(sources))} file(s) scanned"
          + (f"; {skipped} left long (see above)" if skipped else "")
          + (f"; {refused} file(s) REFUSED" if refused else "")
          + ("" if a.write else "  — re-run with --write to apply"))
    return 1 if refused else 0


if __name__ == "__main__":
    sys.exit(main())
