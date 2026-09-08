"""talkparse.py — talkfile lexer + screen assembler.

Grammar source: docs/format-spec-v1.md (talkfile v1.0 draft — the normative
spec in this repo; docs/format-spec.md is the retired v0.5 stub).
Encoded parse-model decisions (rationale in docs/engine-decision.md):

- A SCREEN (present-view slide, document-view step, cues.json cue) is opened
  by a shot directive comment (`<!-- shot ... -->`).  Text never opens a
  screen except as a tolerance fallback (stray heading with no shot).
- Paragraphs are VO (spoken).  They attach to the screen open at the moment
  the paragraph appears in the file, i.e. the screen opened by the shot that
  precedes them.  Text spoken while a screen is up sits between this screen's
  shot and the next screen's shot in file order.
- A paragraph immediately following a role shot — bare (`<!-- shot: stat -->`)
  or attached via `+<role>` (`<!-- shot: garden +credits -->`) — is CONSUMED
  as that role's on-screen payload: screen text, never VO.
- Roles attach to a screen ONLY through `+<role>`: written on the screen's
  own shot (canonical form), or as a `+<role>`-only directive directly after
  a shot (which attaches to that shot's screen).  There is NO implicit merge:
  a bare role shot always opens its own screen, and one that directly follows
  another shot warns with a `+<role>` did-you-mean hint (spec §4).
- A bare credits shot opens a credits SCREEN (end roll) that consumes every
  following paragraph, list item, and heading as screen content until the
  next shot or movement boundary.
- `<!-- shot: black -->` opens a deliberate black-beat screen: full-stage
  silence, no payload, nothing consumed. Author a shot afterwards to
  continue.
- Parentheses `( ... )` are never spoken and never on screen (grammar rule 2).
  They are extracted into stage directions that travel with the cue.
  Parens do not nest: a nested `(` is a warning (register check 23, spec §5)
  — the strip recognizes one level only, and nesting would corrupt the
  spoken text.
- Footnote references `[^id]` are inert like parentheticals: stripped from
  every text block — never spoken, never on screen, never verbatim in the
  handout — and each referenced id is collected on Talk.footnote_ids in
  first-appearance order, for the handout citation list (spec §5).
- `## Movement N · Title` headers are structural: they close the current
  screen, open a new movement, and never become slides themselves.  An H2
  beginning with "Movement" (case-insensitive) that fails the pattern is a
  FATAL error (register check 22) — left silent, it becomes an on-screen
  heading and merges screens.
- No token in a shot comment is silently dropped: a token that is neither a
  slug, a role, a `+<role>` overlay, nor a known flag WARNS (register check
  25).  An unknown FIRST token stays a slug (token-position rule, §1); its
  unresolved placeholder reason carries the "meant as a role or flag?" hint.
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
# Known flags (spec §7 Tier B table).  Unit fields (id/tags/variant) are a
# later additive (T13); today every known token is one of these.
KNOWN_FLAGS = ("kb", "dim", "fit", "piece", "duo", "text")
FIT_VALUES = ("cover", "contain", "hero")
# Movement recognition is case-insensitive (the frozen rule is the *shape*,
# `Movement <integer> [separator] [title]`, not the typography — report §6.1).
MOVEMENT_RE = re.compile(
    r"^Movement\s+(\d+)\s*[|.:\-\u00b7]?\s*(.*)$", re.IGNORECASE)
# Fatal-start probe for check 22: an H2 whose text begins with the *word*
# "Movement" (case-insensitive) but fails MOVEMENT_RE.
MOVEMENT_LOOK_RE = re.compile(r"^movement\b", re.IGNORECASE)
HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
QUOTE_RE = re.compile(r"^>\s?(.*)$")
LIST_ITEM_RE = re.compile(r"^[-*+]\s+(.*)$")
HR_RE = re.compile(r"^\s*(?:-{3,}|\*{3,}|_{3,})\s*$")
PAREN_SPLIT_RE = re.compile(r"\(([^()]*)\)|([^()]+)")
FOOTNOTE_REF_RE = re.compile(r"\[\^([a-z0-9][a-z0-9-]*)\](?!:)")
FLAG_RE = re.compile(r"([A-Za-z][A-Za-z0-9_\-]*)(?:=([^\s]+))?")


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


@dataclass
class Shot:
    """One parsed shot directive.

    slug    extensionless media slug.  Present unless the shot is role-only,
            flag-only, or bare.  An unknown first token becomes the slug by
            the token-position rule (§1); role/flag typos surface later as a
            placeholder-reason hint (§6.8) and register check 25 warnings on
            the remaining tokens.
    role    the role this shot brings to its screen: 'stat' | 'lower' |
            'credits' (Tier A) or BLACK_ROLE for a black beat.  Set from a
            `+<role>` overlay token or a bare role/black first token.
    plus    True when the role was written as `+<role>` (overlay syntax).
            slug + role + plus is the canonical overlay form; role + plus
            with no slug is an overlay-only directive that attaches to the
            previous shot's screen.
    flags   {'kb': 'in', 'dim': '0.35', ...} — known flags only (§7).
    warnings  token-level notes (register check 25): no token in a shot
            comment is silently dropped.
    """

    slug: Optional[str] = None
    role: Optional[str] = None       # 'stat' | 'lower' | 'credits' | 'black' | None
    plus: bool = False               # role attached via +<role> overlay syntax
    flags: dict = field(default_factory=dict)   # {'kb': 'in', 'dim': '0.35', ...}
    raw: str = ""
    line: int = 0
    warnings: list = field(default_factory=list)

    @property
    def is_role(self) -> bool:
        return self.role in ROLES

    @property
    def is_media(self) -> bool:
        """A slug always resolves as media — even on a `+<role>` overlay
        shot, which carries slug AND role (spec §4 canonical overlay)."""
        return self.slug is not None


@dataclass
class Block:
    """One content block on a screen, in document order."""

    kind: str                     # vo|heading|quote|quote-source|list|stat|lower|credits
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
        empty vo blocks; they must not block a `+<role>`-only overlay
        directive from attaching to the screen they describe.
        """
        for b in self.blocks:
            if b.kind != "vo" or b.text.strip():
                return True
        return False

    @property
    def media_shot(self) -> Optional[Shot]:
        """First media slug shot on this screen.  A canonical `slug +<role>`
        overlay shot carries the slug, so it IS the media shot; a merged
        `+<role>`-only directive (no slug) appends after it."""
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
    footnote_ids: list = field(default_factory=list)   # `[^id]` refs, doc order (§5)


# ---------------------------------------------------------------------------
# Inline helpers (shared by present + document views)
# ---------------------------------------------------------------------------


def split_parens(text: str) -> tuple[str, list]:
    """Return (text with ( ... ) removed, list of parenthetical contents).

    Parentheticals are never spoken / never on screen; they travel as stage
    notes.  Parens do NOT nest: the strip recognizes one level only — the
    innermost pair wins and the outer markers vanish from the spoken text.
    A nested `(` is a warning (register check 23, spec §5), never a silent
    corruption; authors rewrite the parenthetical flat.
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


def nested_paren_at(text: str) -> Optional[int]:
    """Index of the first `(` that opens inside an already-open parenthetical,
    or None.  Register check 23 (spec §5): parentheticals do not nest —
    split_parens recognizes one level, so nesting silently corrupts the
    spoken text unless it warns.
    """
    depth = 0
    for i, ch in enumerate(text):
        if ch == "(":
            if depth:
                return i
            depth = 1
        elif ch == ")":
            if depth:
                depth -= 1
    return None


def strip_footnote_refs(text: str, collected: list) -> str:
    """Remove `[^id]` body-footnote references (spec §5) from text.

    References are inert: never spoken, never on screen, never verbatim in
    the handout.  Each referenced id is appended to `collected` on first
    appearance (document order), giving the handout citation list its keys
    into the frontmatter `sources:` registry.  The `(?!:)` guard leaves an
    in-body `[^id]: …` definition line intact — receipts have no body-level
    definition form; a definition is its `sources:` registry entry (§2).
    """
    def _drop(m):
        rid = m.group(1)
        if rid not in collected:
            collected.append(rid)
        return ""
    return FOOTNOTE_REF_RE.sub(_drop, text)


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


def _apply_overlay(shot: Shot, token: str) -> None:
    """Apply a `+<role>` overlay token (spec §4 Tier A roles)."""
    rname = token[1:]
    if rname not in ROLES:
        shot.warnings.append(
            f"check 25: {token!r} is not an overlay role; overlays are "
            f"+stat, +lower, +credits — token ignored"
        )
        return
    if shot.role is None:
        shot.role = rname
        shot.plus = True
    elif shot.role == rname and shot.plus:
        shot.warnings.append(
            f"check 25: duplicate +{rname} on one shot — a role attaches "
            f"once; token ignored"
        )
    else:
        shot.warnings.append(
            f"check 25: shot already carries role {shot.role!r}; {token!r} "
            f"ignored (one overlay role per shot)"
        )


def _apply_flag(shot: Shot, name: str, value: str, token: str) -> None:
    """Apply one known-flag token.  Unknown names and the removed valueless
    `fit` warn (check 25 / spec §7); nothing is silently accepted or dropped.

    Valueless `kb`/`dim`/`text` are stored with an empty value and render
    inert — the flag-value-out-of-range taxonomy warning is check-suite
    territory (T08), not the tokenizer's.
    """
    if name not in KNOWN_FLAGS:
        shot.warnings.append(
            f"check 25: unknown flag {token!r}; known flags: "
            f"{', '.join(KNOWN_FLAGS)} — token ignored"
        )
        return
    if name == "fit" and not value:
        # Removed form (§7): historic bare `fit` took its meaning from what
        # followed the shot (lookahead).  No meaning of its own now.
        shot.warnings.append(
            f"valueless 'fit' has no meaning (removed form); write "
            f"fit={', fit='.join(FIT_VALUES)}"
        )
        return
    shot.flags[name] = value


def _parse_shot(raw: str, line: Optional[int] = None) -> Shot:
    """Parse a full `<!-- shot ... -->` comment into a Shot.

    Token vocabulary (spec §3/§4/§7): the FIRST token is the shot's slug, its
    role (stat/lower/credits/black), a `+<role>` overlay, or — for flag-only
    shots — a known flag.  Later tokens are flags (`name=value`, or bare
    `piece`/`duo`) or `+<role>` overlays.  An unknown first token stays a slug
    (token-position rule, §1).  Every other unrecognized token WARNS (register
    check 25): nothing in a shot comment is silently dropped.
    """
    m = SHOT_RE.match(raw)
    spec = (m.group(1) or "").strip() if m else ""
    shot = Shot(raw=raw, line=line or 0)
    if not spec:
        return shot
    tokens = spec.split()
    first = tokens[0]

    # --- first token: role | +<role> overlay | known flag | slug ----------
    if first in ROLES or first == BLACK_ROLE:
        shot.role = first
    elif first.startswith("+"):
        _apply_overlay(shot, first)
    else:
        fm = FLAG_RE.match(first)
        if fm and fm.group(1) in KNOWN_FLAGS:
            # flag-only shot (§3): the first token is a known flag, so the
            # screen is card-only — no media slug, no role.
            _apply_flag(shot, fm.group(1), fm.group(2) or "", first)
        elif fm and fm.group(2) is not None:
            # `name=value` shape with an unknown name: slugs are bare tokens,
            # so this cannot be a slug — a flag typo.
            _apply_flag(shot, fm.group(1), fm.group(2), first)
        else:
            # Unknown first token: stays a slug (token-position rule, §1).
            # A role/flag typo surfaces honestly later: media resolution
            # fails and the placeholder reason adds the "if 'hero' was meant
            # as a role or flag, it is neither" hint (§6.8, mediaresolve.py).
            shot.slug = first

    # --- remaining tokens: flags and +<role> overlays ----------------------
    for tok in tokens[1:]:
        if tok.startswith("+"):
            _apply_overlay(shot, tok)
            continue
        fm = FLAG_RE.match(tok)
        if not fm:
            shot.warnings.append(
                f"check 25: token {tok!r} matches no flag or overlay "
                f"pattern; token ignored"
            )
            continue
        _apply_flag(shot, fm.group(1), fm.group(2) or "", tok)
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
            shot.line = rb.get("line", 0) or 0
            for w in shot.warnings:          # tokenizer notes (check 25)
                talk.warnings.append(f"line {shot.line}: {w}")
            role = shot.role
            is_role = role in ROLES          # stat/lower/credits payload roles
            plus_only = shot.plus and shot.slug is None   # `+<role>`-only directive

            # A role's payload paragraph never crosses a shot boundary: if a
            # previous role shot is still waiting for its paragraph, it lost
            # it the moment the next shot arrived (spec §4 — the paragraph
            # that follows THE shot is the payload).
            if pending_role is not None:
                talk.warnings.append(
                    f"line {role_line}: '{pending_role}' shot never consumed "
                    f"a payload paragraph (next block: shot at line "
                    f"{shot.line})"
                )
                pending_role = None

            if plus_only:
                if cur is not None and cur.shots and not cur.has_vo_or_screen_text():
                    # `+<role>`-only directive directly after a shot: the
                    # overlay attaches to that shot's screen (spec §3 — the
                    # one consecutive case that merges, so it does not warn).
                    cur.shots.append(shot)
                    credits_open = False
                else:
                    talk.warnings.append(
                        f"line {shot.line}: '+{role}' overlay directive "
                        f"follows no adjacent shot to attach to; it opens "
                        f"its own screen"
                    )
                    new_screen(shot.line).shots.append(shot)
                    credits_open = role == "credits"
                if is_role:
                    pending_role = role
                    role_line = shot.line
                continue

            if is_role and not shot.plus:
                # Bare role shot — always opens its own screen.  Implicit
                # merge is removed (§4); directly following another shot is
                # the would-be merge and gets the did-you-mean hint.
                if cur is not None and cur.shots and not cur.has_vo_or_screen_text():
                    talk.warnings.append(
                        f"line {shot.line}: bare '{role}' shot directly "
                        f"follows another shot with no content between; "
                        f"implicit merge is removed — write +{role} on the "
                        f"media shot instead (e.g. '<!-- shot: <slug> "
                        f"+{role} -->'); this shot opens its own screen"
                    )
                new_screen(shot.line).shots.append(shot)
                credits_open = role == "credits"   # a credits SCREEN: end roll
                pending_role = role
                role_line = shot.line
                continue

            # Ordinary screen opener: media shot, flag-only shot, black beat,
            # or the canonical `slug +<role>` overlay (role written on the
            # screen's own shot).
            if cur is not None and cur.shots and not cur.has_content():
                talk.warnings.append(
                    f"line {shot.line}: consecutive shot directives with no "
                    f"content between (the second is not a +<role> overlay); "
                    f"the second opens a new screen and the first stays an "
                    f"empty beat"
                )
            new_screen(shot.line).shots.append(shot)
            credits_open = False
            if is_role:                # canonical overlay: payload para follows
                pending_role = role
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
            if MOVEMENT_LOOK_RE.match(rb["text"]):
                # Register check 22: the author intended structure.  Left
                # silent, this H2 becomes an on-screen heading, never closes
                # the open screen, and merges screens in both views.
                raise ValueError(
                    f"{source}:{rb.get('line', 0)}: check 22: H2 "
                    f"{rb['text']!r} begins with 'Movement' but does not "
                    f"match 'Movement <integer> [separator] <title>' — "
                    f"fatal (spec §10: a malformed movement heading is "
                    f"never silently treated as screen text)"
                )

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

        if credits_open and kind == "heading":
            # A credits screen consumes paragraphs, list items, and headings
            # as screen content (spec §4).  A quote is NOT consumed: it stays
            # a quote object, never satisfies the credits role, and the role
            # keeps waiting — so a quote in the would-be payload position
            # fires the never-consumed warning at the next boundary instead
            # of silently absorbing into the end roll.
            pending_role = None  # heading content satisfies the credits role

        if kind == "heading":
            if pending_role is not None and rb["level"] == 2:
                pass  # handled above; defensive
            cur.blocks.append(
                Block(kind="heading",
                      text=strip_footnote_refs(rb["text"], talk.footnote_ids),
                      level=rb["level"],
                      line=rb.get("line", 0))
            )
            continue

        if kind == "quote":
            cur.blocks.append(
                Block(kind="quote",
                      text=strip_footnote_refs(rb["text"], talk.footnote_ids),
                      line=rb.get("line", 0))
            )
            continue

        if kind == "list":
            if credits_open:
                for item in rb["items"]:
                    clean = strip_footnote_refs(item, talk.footnote_ids)
                    np = nested_paren_at(clean)
                    if np is not None:
                        talk.warnings.append(
                            f"line {rb.get('line', 0)}: check 23: "
                            f"parentheticals do not nest — "
                            f"'...{clean[max(0, np - 12):np + 12].strip()}...' "
                            f"in a credits entry; rewrite the parenthetical "
                            f"flat (spec §5)"
                        )
                    spoken, stage = split_parens(clean)
                    cur.blocks.append(
                        Block(kind="credits", text=spoken, stage=stage,
                              line=rb.get("line", 0))
                    )
                pending_role = None
                continue
            cur.blocks.append(
                Block(kind="list",
                      items=[strip_footnote_refs(i, talk.footnote_ids)
                             for i in rb["items"]],
                      line=rb.get("line", 0))
            )
            continue

        if kind == "para":
            clean = strip_footnote_refs(rb["text"], talk.footnote_ids)
            spoken, stage = split_parens(clean)
            np = nested_paren_at(clean)
            if np is not None:
                # check 23: the strip recognizes one level only — nesting
                # half-speaks the outer parenthetical unless the author fixes
                # it.  Warn once per paragraph, naming the collision site.
                talk.warnings.append(
                    f"line {rb.get('line', 0)}: check 23: parentheticals do "
                    f"not nest — '...{clean[max(0, np - 12):np + 12].strip()}...'; "
                    f"rewrite the parenthetical flat (spec §5)"
                )
            bkind = "vo"
            if (
                pending_role is None
                and not credits_open
                and cur.blocks
                and cur.blocks[-1].kind == "quote"
                and spoken.startswith("~ ")
            ):
                # quote attribution: screen text, never VO.  Grammar: a
                # "~ Name, venue" paragraph whose immediately preceding block
                # is a quote (tilde stripped on screen).  `~` is the ONLY
                # attribution form (spec §4; the `Source: ` shape was deleted
                # — T03/D4 — and falls through to VO with a check-24 warning).
                bkind = "quote-source"
                spoken = spoken[2:]
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
            if bkind == "vo" and (spoken.startswith("~ ")
                                  or spoken.startswith("Source: ")):
                # check 24: the line reads as an attribution but does not sit
                # directly under a quote, so it will be SPOKEN — tilde and
                # all.  Attribution is `~ ` on its own paragraph under the
                # quote (spec §4); warn so the author never hears a credit
                # line read aloud by accident.
                talk.warnings.append(
                    f"line {rb.get('line', 0)}: check 24: attribution-looking "
                    f"line will be spoken — {spoken[:40]!r}; attribution is "
                    f"'~ ' on its own paragraph directly under a quote "
                    f"(spec §4)"
                )
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
