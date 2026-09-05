"""talkparse.py — talkfile lexer + screen assembler.

Grammar source: docs/format-spec.md (talkfile v0.5, canonical in this repo).
Encoded parse-model decisions (rationale in docs/engine-decision.md):

- A SCREEN (present-view slide, document-view step, cues.json cue) is opened
  by a shot directive comment (`<!-- shot ... -->`).  Text never opens a
  screen except as a tolerance fallback (stray heading with no shot).
- Paragraphs are VO (spoken).  They attach to the screen open at the moment
  the paragraph appears in the file, i.e. the screen opened by the shot that
  precedes them.  Text spoken while a screen is up sits between this screen's
  shot and the next screen's shot in file order.
- A paragraph immediately following a stat / lower shot (or a credits shot
  merged as an overlay onto an unvoiced media screen) is CONSUMED as that
  role's on-screen payload: screen text, not VO.
- A credits shot that opens its OWN screen (a credits screen / end roll)
  consumes every following paragraph, list item, and heading as screen
  content until the next shot or movement boundary.
- `<!-- shot: black -->` opens a deliberate black-beat screen: full-stage
  silence, no payload, nothing consumed. Author a shot afterwards to
  continue.
- Parentheses `( ... )` are never spoken and never on screen (grammar rule 2).
  They are extracted into stage directions that travel with the cue.
- `## Movement N · Title` headers are structural: they close the current
  screen, open a new movement, and never become slides themselves.
- Card-capable blocks after a shot (heading / quote / list) are on-screen
  objects.  The first heading of a screen is its title.
- Screen order is document order; ids are assigned later by the cue renderer.

Deterministic: same file in -> same model out.  No timestamps, no ordering
from set iteration.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

import yaml

SHOT_RE = re.compile(r"^\s*<!--\s*shot(?::\s*(.*?))?\s*-->\s*$")
ROLES = ("stat", "lower", "credits")
BLACK_ROLE = "black"  # deliberate black beat: full-stage silence, no payload
MOVEMENT_RE = re.compile(r"^Movement\s+(\d+)\s*[|.:\-\u00b7]?\s*(.*)$")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
QUOTE_RE = re.compile(r"^>\s?(.*)$")
LIST_ITEM_RE = re.compile(r"^[-*+]\s+(.*)$")
HR_RE = re.compile(r"^\s*(?:-{3,}|\*{3,}|_{3,})\s*$")
PAREN_SPLIT_RE = re.compile(r"\(([^()]*)\)|([^()]+)")
FLAG_RE = re.compile(r"([A-Za-z][A-Za-z0-9_\-]*)(?:=([^\s]+))?")


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


@dataclass
class Shot:
    """One parsed shot directive."""

    slug: Optional[str] = None       # extensionless media slug (or None)
    role: Optional[str] = None       # 'stat' | 'lower' | 'credits' | None
    flags: dict = field(default_factory=dict)   # {'kb': 'in', 'dim': '0.35', ...}
    raw: str = ""
    line: int = 0

    @property
    def is_role(self) -> bool:
        return self.role in ROLES

    @property
    def is_media(self) -> bool:
        return self.slug is not None and not self.is_role


@dataclass
class Block:
    """One content block on a screen, in document order."""

    kind: str                     # vo|heading|quote|list|stat|lower|credits
    text: str = ""                # for vo/heading/quote/stat/lower/credits
    level: Optional[int] = None   # heading depth (1..6)
    items: list = field(default_factory=list)   # list items
    stage: list = field(default_factory=list)   # extracted parentheticals
    line: int = 0


@dataclass
class Screen:
    idx: int                      # 1-based, document order
    movement: int                 # 0 = opening/title zone, else 1..N
    shots: list = field(default_factory=list)
    blocks: list = field(default_factory=list)   # list[Block]
    line: int = 0

    def has_content(self) -> bool:
        return bool(self.blocks)

    def has_vo_or_screen_text(self) -> bool:
        """True when the screen carries spoken text or an on-screen object.

        Stage-only paragraphs ((Visual: ...), (Beat.), (Flesh out: ...)) become
        empty vo blocks; they must not block a role overlay from merging onto
        the media screen they describe.
        """
        for b in self.blocks:
            if b.kind != "vo" or b.text.strip():
                return True
        return False

    @property
    def media_shot(self) -> Optional[Shot]:
        """First media slug shot on this screen (overlay shots come after)."""
        for s in self.shots:
            if s.is_media:
                return s
        return None

    @property
    def first_heading(self) -> Optional[Block]:
        for b in self.blocks:
            if b.kind == "heading":
                return b
        return None


@dataclass
class Movement:
    index: int
    title: str
    label: str                    # original heading text


@dataclass
class Talk:
    meta: dict
    source: str                   # display source path
    movements: list = field(default_factory=list)   # list[Movement]
    screens: list = field(default_factory=list)     # list[Screen]
    warnings: list = field(default_factory=list)    # human-readable notes


# ---------------------------------------------------------------------------
# Inline helpers (shared by present + document views)
# ---------------------------------------------------------------------------


def split_parens(text: str) -> tuple[str, list]:
    """Return (text with ( ... ) removed, list of parenthetical contents).

    Parentheticals are never spoken / never on screen; they travel as stage
    notes.  Nesting is not expected in talkfiles; if present, the inner text
    is kept inside the parenthetical verbatim.
    """
    spoken_parts: list[str] = []
    stage: list[str] = []
    for m in PAREN_SPLIT_RE.finditer(text):
        if m.group(1) is not None:
            stage.append(m.group(1).strip())
        else:
            spoken_parts.append(m.group(2))
    spoken = re.sub(r"\s+", " ", " ".join(spoken_parts)).strip()
    spoken = re.sub(r"\s+([.,;:!?])", r"\1", spoken)   # 'Residence (..).' -> 'Residence.'
    return spoken, [s for s in stage if s]


_INLINE_TOK = re.compile(r"(\*\*.+?\*\*|`[^`]+`|\*[^*\s][^*]*\*)")


def html_escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def inline_md(text: str) -> str:
    """Escape + minimal inline markdown (bold / code / italic) -> HTML."""
    esc = html_escape(text)
    parts = []
    pos = 0
    for m in _INLINE_TOK.finditer(esc):
        parts.append(esc[pos:m.start()])
        tok = m.group(0)
        if tok.startswith("**") and tok.endswith("**"):
            parts.append("<strong>%s</strong>" % tok[2:-2])
        elif tok.startswith("`") and tok.endswith("`"):
            parts.append("<code>%s</code>" % tok[1:-1])
        elif tok.startswith("*") and len(tok) > 2 and tok.endswith("*"):
            parts.append("<em>%s</em>" % tok[1:-1])
        else:
            parts.append(tok)
        pos = m.end()
    parts.append(esc[pos:])
    return "".join(parts)


def plain_md(text: str) -> str:
    """Strip inline markdown markers -> plain text (cues script / TTS)."""
    s = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    s = re.sub(r"`([^`]+)`", r"\1", s)
    s = re.sub(r"(?<!\w)\*([^*\s][^*]*)\*(?!\w)", r"\1", s)
    return re.sub(r"\s+", " ", s).strip()


def slugify(text: str, maxlen: int = 48) -> str:
    s = text.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return s[:maxlen].rstrip("-") or "untitled"


# ---------------------------------------------------------------------------
# Lexer
# ---------------------------------------------------------------------------


def _lex_frontmatter(body: str, source: str) -> tuple[dict, list]:
    """Split YAML frontmatter (--- ... ---) from the body. Returns (meta, lines)."""
    lines = body.split("\n")
    meta: dict = {}
    if lines and lines[0].strip() == "---":
        end = None
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                end = i
                break
        if end is None:
            raise ValueError(f"{source}: frontmatter never closed")
        fm = "\n".join(lines[1:end])
        try:
            meta = yaml.safe_load(fm) or {}
        except yaml.YAMLError as exc:
            raise ValueError(f"{source}: bad frontmatter YAML: {exc}") from exc
        if not isinstance(meta, dict):
            raise ValueError(f"{source}: frontmatter must be a mapping")
        rest = lines[end + 1:]
    else:
        rest = lines
    return meta, rest


def _lex_blocks(lines: list, source: str) -> list:
    """Tokenize source lines into primitive blocks (list of dicts).

    Blank lines separate paragraphs; consecutive non-blank prose lines merge
    (markdown soft-wrap).  Markers (heading / quote / list / comment / hr)
    always start a fresh block.  Non-shot comments are dropped: provenance and
    receipts live in the bank, per grammar rule 3.
    """
    blocks: list[dict] = []
    para_buf: list[str] = []
    para_line = 0
    cont = None  # (kind, block, last_lineno) for quote/list line merging
    comment_buf: Optional[list] = None

    def flush_para():
        nonlocal para_buf, cont
        if para_buf:
            blocks.append({"kind": "para", "text": " ".join(para_buf), "line": para_line})
            para_buf = []
        cont = None

    for lineno, raw in enumerate(lines, start=1):
        line = raw.rstrip("\n")

        # --- multi-line comment accumulation --------------------------------
        if comment_buf is not None:
            comment_buf.append(line)
            if "-->" in line:
                comment = " ".join(comment_buf)
                comment_buf = None
                if SHOT_RE.match(comment):
                    flush_para()
                    blocks.append(
                        {"kind": "shot", "shot": _parse_shot(comment), "line": lineno}
                    )
            continue
        if line.lstrip().startswith("<!--"):
            if "-->" not in line:
                comment_buf = [line]
                continue
            if SHOT_RE.match(line):
                flush_para()
                blocks.append({"kind": "shot", "shot": _parse_shot(line), "line": lineno})
            continue

        # --- blank line ------------------------------------------------------
        if not line.strip():
            flush_para()
            continue

        # --- headings --------------------------------------------------------
        hm = HEADING_RE.match(line)
        if hm:
            flush_para()
            blocks.append(
                {"kind": "heading", "level": len(hm.group(1)), "text": hm.group(2).strip(),
                 "line": lineno}
            )
            continue

        # --- blockquote lines ------------------------------------------------
        qm = QUOTE_RE.match(line)
        if qm:
            if cont and cont[0] == "quote" and lineno == cont[2] + 1:
                cont[1]["text"] += " " + qm.group(1).strip()
                cont[2] = lineno
            else:
                flush_para()
                block = {"kind": "quote", "text": qm.group(1).strip(), "line": lineno}
                blocks.append(block)
                cont = ["quote", block, lineno]
            continue

        # --- list items -------------------------------------------------------
        lm = LIST_ITEM_RE.match(line)
        if lm:
            if cont and cont[0] == "list" and lineno == cont[2] + 1:
                cont[1]["items"].append(lm.group(1).strip())
                cont[2] = lineno
            else:
                flush_para()
                block = {"kind": "list", "items": [lm.group(1).strip()], "line": lineno}
                blocks.append(block)
                cont = ["list", block, lineno]
            continue

        # --- thematic break (ignored; movement H2s carry structure) ----------
        if HR_RE.match(line):
            flush_para()
            continue

        # --- prose ------------------------------------------------------------
        cont = None
        if not para_buf:
            para_line = lineno
        para_buf.append(line.strip())

    flush_para()
    return blocks


def _parse_shot(raw: str, line: Optional[int] = None) -> Shot:
    """Parse a full `<!-- shot ... -->` comment.  '' spec -> bare shot."""
    m = SHOT_RE.match(raw)
    spec = (m.group(1) or "").strip() if m else ""
    shot = Shot(raw=raw, line=line or 0)
    if not spec:
        return shot
    tokens = spec.split()
    first = tokens[0]
    if first in ROLES or first == BLACK_ROLE:
        shot.role = first
    elif first in ("fit", "piece"):
        # flag-only shot: no slug, carries slide flags only.
        # e.g. `<!-- shot: fit -->` = hero card scaled to the slide.
        pass
    else:
        shot.slug = first
    start = 0 if shot.slug is None and shot.role is None else 1
    for tok in tokens[start:]:
        fm = FLAG_RE.match(tok)
        if fm:
            shot.flags[fm.group(1)] = fm.group(2) or ""
    return shot


# ---------------------------------------------------------------------------
# Screen assembler
# ---------------------------------------------------------------------------


def build_talk(path, source: Optional[str] = None) -> Talk:
    """Parse a talkfile path into a Talk model."""
    source = source or str(path)
    with open(path, "r", encoding="utf-8") as fh:
        body = fh.read()
    meta, lines = _lex_frontmatter(body, source)
    raw_blocks = _lex_blocks(lines, source)
    return assemble(meta, raw_blocks, source)


def assemble(meta: dict, raw_blocks: list, source: str) -> Talk:
    talk = Talk(meta=meta, source=source)
    screens: list[Screen] = []
    cur: Optional[Screen] = None
    movement_index = 0            # 0 = opening/title zone, then 1..N
    pending_role: Optional[str] = None   # role shot waiting to consume a para
    role_line = 0
    credits_open = False                 # credits screen: consume following content

    def new_screen(line: int) -> Screen:
        nonlocal cur
        cur = Screen(idx=len(screens) + 1, movement=movement_index, line=line)
        screens.append(cur)
        return cur

    for rb in raw_blocks:
        kind = rb["kind"]

        if kind == "shot":
            shot: Shot = rb["shot"]
            overlay = shot.role in ("lower", "credits", "stat")
            merged = False
            if (
                overlay
                and cur is not None
                and cur.shots
                and not cur.has_vo_or_screen_text()
            ):
                # role overlay on a media screen that has not voiced yet
                cur.shots.append(shot)
                merged = True
            else:
                if cur is not None and cur.shots and not cur.has_content():
                    talk.warnings.append(
                        f"line {cur.line}: consecutive shot directives that do not "
                        f"merge; second opens an empty screen"
                    )
                new_screen(shot.line).shots.append(shot)
            credits_open = False  # any new shot ends a credits region
            if shot.role == "credits" and not merged:
                credits_open = True  # a credits SCREEN: text follows as content
            if shot.is_role:
                pending_role = shot.role
                role_line = shot.line
            continue

        if kind == "hr":
            continue

        if kind == "heading" and rb["level"] == 2:
            mm = MOVEMENT_RE.match(rb["text"])
            if mm:
                cur = None  # movement boundary closes any open screen
                credits_open = False
                movement_index = int(mm.group(1))
                talk.movements.append(
                    Movement(index=movement_index,
                             title=mm.group(2).strip() or rb["text"],
                             label=rb["text"])
                )
                if pending_role is not None:
                    talk.warnings.append(
                        f"line {role_line}: role shot never consumed a payload "
                        f"(movement boundary crossed first)"
                    )
                    pending_role = None
                continue

        # --- content blocks ---------------------------------------------------
        # Role payloads (stat / lower / overlay credits) expect a paragraph.
        # On a credits SCREEN (credits_open), paragraphs, list items, and
        # headings are screen content, consumed until the next shot.
        if pending_role is not None and kind not in ("para", "vo") and not credits_open:
            # role shot expects a payload paragraph; a non-paragraph arrived
            talk.warnings.append(
                f"line {role_line}: '{pending_role}' shot not followed by a "
                f"paragraph payload (next block: {kind})"
            )
            pending_role = None

        if cur is None:
            new_screen(rb.get("line", 0))

        assert cur is not None

        if credits_open and kind in ("heading", "quote"):
            pending_role = None  # screen content satisfies the credits role

        if kind == "heading":
            if pending_role is not None and rb["level"] == 2:
                pass  # handled above; defensive
            cur.blocks.append(
                Block(kind="heading", text=rb["text"], level=rb["level"],
                      line=rb.get("line", 0))
            )
            continue

        if kind == "quote":
            cur.blocks.append(Block(kind="quote", text=rb["text"], line=rb.get("line", 0)))
            continue

        if kind == "list":
            if credits_open:
                for item in rb["items"]:
                    spoken, stage = split_parens(item)
                    cur.blocks.append(
                        Block(kind="credits", text=spoken, stage=stage,
                              line=rb.get("line", 0))
                    )
                pending_role = None
                continue
            cur.blocks.append(Block(kind="list", items=rb["items"], line=rb.get("line", 0)))
            continue

        if kind == "para":
            spoken, stage = split_parens(rb["text"])
            bkind = "vo"
            if (
                pending_role is None
                and not credits_open
                and cur.blocks
                and cur.blocks[-1].kind == "quote"
                and (spoken.startswith("~ ") or spoken.startswith("Source: "))
            ):
                # quote attribution: screen text, never VO. Grammar: a
                # "~ Name, venue" line directly under a quote blockquote
                # (tilde stripped on screen; "Source: " accepted too).
                bkind = "quote-source"
                spoken = spoken[2:] if spoken.startswith("~ ") else spoken[len("Source: "):]
            elif pending_role is not None:
                bkind = pending_role
                if not spoken:
                    talk.warnings.append(
                        f"line {role_line}: '{pending_role}' shot payload is empty "
                        f"after stripping parentheticals"
                    )
                pending_role = None
            elif credits_open:
                bkind = "credits"   # credits screen entries: screen text, never VO
            cur.blocks.append(
                Block(kind=bkind, text=spoken, stage=stage, line=rb.get("line", 0))
            )
            continue

        talk.warnings.append(f"line {rb.get('line', 0)}: unhandled block kind {kind}")

    if pending_role is not None:
        talk.warnings.append(
            f"line {role_line}: role shot never consumed a payload paragraph"
        )

    # drop empty trailing screens (a shot directive with no content at EOF)
    kept = []
    for s in screens:
        if s.shots or s.has_content():
            kept.append(s)
        else:
            talk.warnings.append(f"line {s.line}: empty screen dropped (no content)")
    talk.screens = kept
    for i, s in enumerate(talk.screens, start=1):
        s.idx = i
    talk.warnings.sort()
    return talk
