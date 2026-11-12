"""The hands-on parts of a talk, for the agent file (tools/agent-export.py), and
the `agent-export: skip` rule it shares with the home page (tools/web-export.py --home).

A part is a `do` screen, or one `(Do: ...)` stage note on a content screen.  Room screens (`live`), black screens and `agent-export: skip` sections make none.
Spec: docs/format-spec-v1.md, "Home page and agent export".
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import render
import talkparse

_SKIP_CACHE: dict = {}


def section_skipped(screen, talk_dir) -> bool:
    """True when the screen comes from an included section whose own frontmatter says
    `agent-export: skip` (an introduction or credits: fine in the reading copy, noise in a
    self-run workshop)."""
    inc = screen.include
    if not inc:
        return False
    path = Path(inc)
    if not path.is_absolute() and talk_dir is not None:
        path = (Path(talk_dir) / path).resolve()
    if path not in _SKIP_CACHE:
        skip = False
        try:
            text = path.read_text(encoding="utf-8")
            if text.startswith("---"):
                head = text.split("\n---", 1)[0]
                skip = bool(re.search(r"(?m)^agent-export:\s*skip\s*$", head))
        except OSError:
            skip = False
        _SKIP_CACHE[path] = skip
    return _SKIP_CACHE[path]


def plain(text: str) -> str:
    return re.sub(r"[ \t]*\n[ \t]*", "\n", text.strip())


def one_line(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def screen_body(screen) -> str:
    """The screen's own text for an exercise: list, quote, code, table, stat; the
    heading and any timer token are left out (the heading is the card title)."""
    out = []
    first = screen.first_heading
    for b in screen.blocks:
        if b is first or b.kind in ("heading", "handout-heading", "timer") or b.kind == "vo":
            continue
        text = talkparse.strip_timer_tokens(b.text) if b.timer is not None else b.text
        if b.kind == "list":
            items = [talkparse.strip_timer_tokens(i) if "[" in i else i for i in b.items]
            out.append("\n".join(f"{'1.' if b.ordered else '-'} {i}" for i in items))
        elif b.kind == "code":
            out.append("```\n" + b.text + "\n```")
        elif b.kind == "quote":
            if text.strip():
                out.append("\n".join("> " + ln for ln in text.splitlines()))
        elif b.kind == "table":
            rows = ["| " + " | ".join(r) + " |" for r in b.rows]
            if rows:
                out.append("\n".join(rows))
        elif b.kind in ("stat", "paraphrase", "lower", "credits", "quote-source", "print"):
            if b.kind != "print" and text.strip():
                out.append(text.strip())
    return "\n\n".join(x for x in out if x.strip())


@dataclass
class Card:
    """One hands-on part: a `do` screen, or one `(Do: ...)` note on a content screen."""
    idx: int                 # the screen's ordinal
    number: int              # N in the agent file's "### N. <heading>", in page order
    kind: str                # "do" | "note"
    heading: str
    notes: list = field(default_factory=list)   # the Do note text(s)
    spoken: str = ""
    screen_text: str = ""    # markdown
    minutes: int | None = None

    @property
    def title(self) -> str:
        return f"{self.number}. {self.heading}"

    def instructions(self) -> list:
        """What the agent needs to know: the Do note(s), screen text, spoken text, timer."""
        body = [f"**Exercise:** {n}" for n in self.notes]
        if self.screen_text:
            body.append(self.screen_text)
        if self.spoken.strip():
            body.append(plain(self.spoken))
        if self.minutes:
            body.append(f"(about {self.minutes} minutes in the room)")
        return body


def skipped_screens(talk, talk_dir=None) -> set:
    """Ordinals of the screens in `agent-export: skip` sections: left out of the home
    page and the agent export, kept in the plain reading copy."""
    return {s.idx for s in talk.screens if section_skipped(s, talk_dir)}


def collect(talk, talk_dir=None) -> list:
    """Every hands-on part, in page order."""
    moves = {m.index: m.title for m in talk.movements}
    cards = []
    for s in talk.screens:
        if section_skipped(s, talk_dir) or render.is_black_screen(s) or s.room_only:
            continue
        heading = render.screen_title(s) or moves.get(s.movement) or "step"
        say = render.screen_script(s)
        if s.exercise:
            minutes = (max(1, round(s.timer[0] / 60))
                       if s.timer is not None and s.timer_parent is None else None)
            cards.append(Card(s.idx, len(cards) + 1, "do", heading, list(s.do_notes), say,
                              screen_body(s), minutes))
        else:
            for note in s.do_notes:
                cards.append(Card(s.idx, len(cards) + 1, "note", heading, [note], say))
    return cards
