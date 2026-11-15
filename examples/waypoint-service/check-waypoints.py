#!/usr/bin/env python3
"""Check that a talk and its waypoint list agree.

    python3 check-waypoints.py talk.md hook/waypoints.txt

A waypoint the talk publishes but the list lacks is ignored by every machine, and a line
in the list that no screen publishes never fires. Both fail silently in the room, so this
is what catches them. It checks, and exits 1 on any failure:

- every `waypoint=word` in a shot of the talk (`<!-- shot: waypoint=word -->`) has a line
  `word | note` in the list, and every line in the list has a waypoint in the talk
- words are lowercase letters, digits and hyphens, 1 to 24 characters, used once in the
  talk and once in the list
- the first waypoint in the talk is `start`, so a run never begins on the last run's word
- the removed standalone `<!-- waypoint: word -->` line is reported rather than skipped
- every note is on one line (the hook prints one line) and `start` is the only word whose
  note may be empty

In the list, blank lines and lines starting with # are ignored. Standard library only.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

WORD = re.compile(r"[a-z0-9-]{1,24}")
SHOT = re.compile(r"<!--\s*shot\b(.*?)-->", re.S)
FLAG = re.compile(r"(?:^|\s)waypoint=(\S*)")
OLD = re.compile(r"<!--\s*waypoint\b", re.I)


def talk_words(path: Path) -> tuple[list[tuple[int, str]], list[str]]:
    words, problems = [], []
    text = path.read_text()
    # leave fenced code alone: blank it out but keep the line numbers
    text = re.sub(r"```.*?```", lambda m: "\n" * m.group(0).count("\n"), text, flags=re.S)
    for m in SHOT.finditer(text):
        flag = FLAG.search(m.group(1))
        if flag:
            words.append((text.count("\n", 0, m.start()) + 1, flag.group(1)))
    for number, line in enumerate(text.splitlines(), 1):
        if OLD.search(line):
            problems.append(f"{path}:{number}: the standalone waypoint line is gone; write the word in the "
                            f"screen's shot, <!-- shot: waypoint=word -->: {line.strip()[:60]}")
    return words, problems


def list_words(path: Path) -> tuple[list[tuple[int, str, str]], list[str]]:
    rows, problems = [], []
    for number, line in enumerate(path.read_text().splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if "|" not in line:
            problems.append(f"{path}:{number}: no '|' (expected 'word | note'): {line[:60]}")
            continue
        word, _, note = line.partition("|")
        rows.append((number, word.strip(), note.strip()))
    return rows, problems


def check(talk: Path, listing: Path) -> list[str]:
    in_talk, problems = talk_words(talk)
    rows, more = list_words(listing)
    problems += more
    for number, word in in_talk:
        if not WORD.fullmatch(word):
            problems.append(f"{talk}:{number}: bad word {word!r} (lowercase letters, digits, hyphens, 1 to 24)")
    for number, word, _ in rows:
        if not WORD.fullmatch(word):
            problems.append(f"{listing}:{number}: bad word {word!r}")
    for label, seq in (("talk", [(n, w) for n, w in in_talk]), ("list", [(n, w) for n, w, _ in rows])):
        seen: dict[str, int] = {}
        for number, word in seq:
            if word in seen:
                problems.append(f"{label}: {word!r} appears twice (lines {seen[word]} and {number})")
            seen.setdefault(word, number)
    talk_set, list_set = {w for _, w in in_talk}, {w for _, w, _ in rows}
    for word in sorted(talk_set - list_set):
        problems.append(f"{word!r} is in the talk but has no line in {listing.name}: machines will ignore it")
    for word in sorted(list_set - talk_set):
        problems.append(f"{word!r} is in {listing.name} but no screen in the talk publishes it")
    if in_talk and in_talk[0][1] != "start":
        problems.append(f"{talk}:{in_talk[0][0]}: the first waypoint is {in_talk[0][1]!r}, not 'start'")
    if not in_talk:
        problems.append(f"{talk}: no waypoint directives")
    for number, word, note in rows:
        if not note and word != "start":
            problems.append(f"{listing}:{number}: {word!r} has an empty note (only 'start' may)")
    return problems


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__.split("\n\n")[0], file=sys.stderr)
        return 2
    talk, listing = Path(argv[1]), Path(argv[2])
    for p in (talk, listing):
        if not p.is_file():
            print(f"no such file: {p}", file=sys.stderr)
            return 2
    problems = check(talk, listing)
    for line in problems:
        print("FAIL  " + line)
    if not problems:
        n = len(list_words(listing)[0])
        print(f"ok: {n} waypoints, talk and list agree")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
