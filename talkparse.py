"""talkparse.py — talkfile lexer + screen assembler.

Grammar source: docs/format-spec-v1.md (the normative spec in this repo).
Encoded parse-model decisions (rationale in docs/engine-decision.md):

- A SCREEN (present-view slide, document-view step, cues.json cue) is opened
  by a shot directive comment (`<!-- shot ... -->`).  Text never opens a
  screen except as a tolerance fallback (stray heading with no shot).
- Paragraphs are VO (spoken).  They attach to the screen open at the moment
  the paragraph appears in the file, i.e. the screen opened by the shot that
  precedes them.  Text spoken while a screen is up sits between this screen's
  shot and the next screen's shot in file order.
- A paragraph immediately following a role shot (`<!-- shot: role=stat -->`)
  is CONSUMED as that role's on-screen payload: screen text, never VO.
- Roles attach to a screen through the `role=` flag, written on the screen's
  own shot (`<!-- shot: <slug> role=<role> -->`).  There is NO implicit merge:
  a bare role shot always opens its own screen, and one that directly follows
  another shot warns with a did-you-mean hint to write `role=` on the media
  shot instead (spec §4).
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
  slug, a role, a layout, nor a known flag WARNS (register check 25).  An
  unknown FIRST token stays a slug (token-position rule, §1); its
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
# Role vocabulary (Tier A frozen, config-driven via roles.yaml).
# The yaml drives the vocabulary; this set is the frozen token set the
# tokenizer recognizes as `role=<name>` (replaces the old +overlay syntax).
ROLES = ("stat", "lower", "credits")
BLACK_ROLE = "black"
# Config-driven vocabulary loaded from roles.yaml + per-deck override.
# Fallback when no yaml present: the built-in roles above.
# Layout vocabulary (Tier B, config-driven via layouts.yaml).
LAYOUTS = ("piece", "duo")
# Known flags (spec §7 Tier B table — per-shot flags; role/layout now config flags).
KNOWN_FLAGS = ("kb", "dim", "fit", "text")
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
# Config-driven vocabulary loaders (roles.yaml / layouts.yaml)
# ---------------------------------------------------------------------------


def _load_roles_yaml(path):
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        roles = data.get("roles", {})
        if isinstance(roles, dict):
            return set(str(k) for k in roles)
        if isinstance(roles, list):
            return set(str(item.get("name", "")) for item in roles if isinstance(item, dict))
    except Exception:
        pass
    return set()


def _load_layouts_yaml(path):
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        layouts = data.get("layouts", {})
        if isinstance(layouts, dict):
            return set(str(k) for k in layouts)
        if isinstance(layouts, list):
            return set(str(item.get("name", "")) for item in layouts if isinstance(item, dict))
    except Exception:
        pass
    return set()


def load_vocab(deck_path=None):
    from pathlib import Path
    base = Path(__file__).resolve().parent
    deck_path = Path(str(deck_path) if deck_path else base / "deck")
    roles = set()
    for p in [deck_path / "roles.yaml", base / "roles.yaml"]:
        if p.exists():
            roles |= _load_roles_yaml(p)
    roles = roles or set(ROLES)
    layouts = set()
    for p in [deck_path / "layouts.yaml", base / "layouts.yaml"]:
        if p.exists():
            layouts |= _load_layouts_yaml(p)
    layouts = layouts or set(LAYOUTS)
    return tuple(sorted(roles)), tuple(sorted(layouts))

ROLES_DYNAMIC, LAYOUTS_DYNAMIC = load_vocab()

# Full role bundles (name -> {spoken, on_screen, form}) drive the parser's
# role -> block-kind mapping and spoken routing.  The hardcoded defaults are
# the fallback when no roles.yaml is present; the yaml (deck -> shared)
# overrides them.  Adding a role = adding one line to roles.yaml (§4).
_DEFAULT_ROLE_BUNDLES = {
    "stat": {"spoken": True, "on_screen": True, "form": "callout"},
    "lower": {"spoken": False, "on_screen": True, "form": "lower-third"},
    "credits": {"spoken": False, "on_screen": True, "form": "end-roll"},
}

# form -> canonical block kind (the fixed IR vocabulary render.py consumes).
FORM_TO_KIND = {"callout": "stat", "lower-third": "lower", "end-roll": "credits"}


def load_role_bundles(deck_path=None):
    """Role name -> {spoken, on_screen, form} from roles.yaml (deck -> shared)
    with the hardcoded defaults as fallback."""
    from pathlib import Path
    base = Path(__file__).resolve().parent
    deck_path = Path(str(deck_path) if deck_path else base / "deck")
    bundles = {}
    for p in [deck_path / "roles.yaml", base / "roles.yaml"]:
        if p.exists():
            try:
                data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
                roles = data.get("roles", {})
                if isinstance(roles, dict):
                    for name, b in roles.items():
                        if isinstance(b, dict):
                            bundles[str(name)] = {
                                "spoken": bool(b.get("spoken", False)),
                                "on_screen": bool(b.get("on_screen", True)),
                                "form": str(b.get("form", "")),
                            }
            except Exception:
                pass
    return bundles or dict(_DEFAULT_ROLE_BUNDLES)


ROLE_BUNDLES = load_role_bundles()


def _canonical_role_kind(role: str) -> str:
    """Role name -> canonical block kind (stat|lower|credits) via the yaml form."""
    form = ROLE_BUNDLES.get(role, {}).get("form", "")
    return FORM_TO_KIND.get(form, role)


def _role_spoken(role: str) -> bool:
    return bool(ROLE_BUNDLES.get(role, {}).get("spoken", False))


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
            `role=<name>` flag token or a bare role/black first token.
    flags   {'kb': 'in', 'dim': '0.35', ...} — known flags only (§7).
    warnings  token-level notes (register check 25): no token in a shot
            comment is silently dropped.
    """

    slug: Optional[str] = None
    role: Optional[str] = None       # 'stat' | 'lower' | 'credits' | 'black' | None
    flags: dict = field(default_factory=dict)   # {'kb': 'in', 'dim': '0.35', ...}
    raw: str = ""
    line: int = 0
    warnings: list = field(default_factory=list)

    @property
    def is_role(self) -> bool:
        return self.role in ROLES_DYNAMIC

    @property
    def is_media(self) -> bool:
        """A slug always resolves as media — even on a shot that also carries
        a role (spec §4 canonical overlay)."""
        return self.slug is not None


@dataclass
class Block:
    """One content block on a screen, in document order."""

    kind: str                     # vo|heading|quote|quote-source|list|stat|lower|credits
    text: str = ""                # for vo/heading/quote/stat/lower/credits
    level: Optional[int] = None   # heading depth (1..6)
    items: list = field(default_factory=list)   # list items
    stage: list = field(default_factory=list)   # extracted parentheticals
    spoken: bool = False          # role payload is spoken VO (from roles.yaml)
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
        empty vo blocks; they must not count as content when deciding whether
        a following shot is consecutive (no content between).
        """
        for b in self.blocks:
            if b.kind != "vo" or b.text.strip():
                return True
        return False

    @property
    def media_shot(self) -> Optional[Shot]:
        """First media slug shot on this screen.  A shot carrying both a slug
        and a role is still the media shot."""
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
                        {"kind": "shot", "shot": _parse_shot(comment, lineno),
                         "line": lineno}
                    )
            continue
        if line.lstrip().startswith("<!--"):
            if "-->" not in line:
                comment_buf = [line]
                continue
            if SHOT_RE.match(line):
                flush_para()
                blocks.append(
                    {"kind": "shot", "shot": _parse_shot(line, lineno), "line": lineno}
                )
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


def _apply_role_flag(shot: Shot, value: str, token: str) -> None:
    """Apply a `role=<name>` flag token."""
    vocab = set(ROLES_DYNAMIC)
    if value not in vocab:
        shot.warnings.append(
            f"check 25: {token!r} names unknown role {value!r}; "
            f"known roles: {', '.join(ROLES_DYNAMIC)} — token ignored"
        )
        return
    # Role is now a config flag; it drives payload consumption (pending_role)
    # but is stored separately from flags so render can read it from yaml.
    if shot.flags.get("role") is not None and shot.flags.get("role") != value:
        shot.warnings.append(
            f"check 25: duplicate role flag on one shot — {token!r} ignored"
        )
        return
    shot.flags["role"] = value
    # Set role attribute for backward compatibility in screen assembler
    if shot.role is None:
        shot.role = value


def _apply_layout_flag(shot: Shot, value: str, token: str) -> None:
    """Apply a `layout=<name>` flag token (replaces flat piece/duo)."""
    vocab = set(LAYOUTS_DYNAMIC)
    if value not in vocab:
        shot.warnings.append(
            f"check 25: {token!r} names unknown layout {value!r}; "
            f"known layouts: {', '.join(LAYOUTS_DYNAMIC)} — token ignored"
        )
        return
    shot.flags["layout"] = value


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

    `line` is the directive's 1-based source line, threaded from every
    `_lex_blocks` call site so the Shot is never born with line 0: warnings
    raised from a shot must name the directive's real line to be actionable
    (check 26, spec §10 — no warning text contains "line 0").  A shot
    directive MAY span multiple lines (spec §3, check 27); interior
    whitespace is insignificant, and a multi-line directive is reported at
    the line where it closes.

    Token vocabulary (spec §3/§4/§7): the FIRST token is the shot's slug, its
    role (stat/lower/credits/black), a `role=<name>` flag, a `layout=<name>`
    flag, or — for flag-only shots — a known flag.  Later tokens are flags
    (`name=value`).  An unknown first token stays a slug (token-position rule,
    §1).  Every other unrecognized token WARNS (register check 25): nothing in
    a shot comment is silently dropped.
    """
    m = SHOT_RE.match(raw)
    spec = (m.group(1) or "").strip() if m else ""
    shot = Shot(raw=raw, line=line or 0)
    if not spec:
        return shot
    tokens = spec.split()
    first = tokens[0]

    # --- first token: slug | role=<name> flag | layout=<name> | black | known flag ----------
    if first in ROLES_DYNAMIC or first == BLACK_ROLE:
        # Bare role shot (e.g. `<!-- shot: stat -->`) — opens its own screen.
        # The `role=` syntax is preferred; bare role preserved for backward compat.
        shot.role = first
    elif first.startswith("role="):
        value = first[5:]
        _apply_role_flag(shot, value, first)
    elif first.startswith("layout="):
        value = first[7:]
        _apply_layout_flag(shot, value, first)
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

    # --- remaining tokens: flags (role=/layout=/kb=/dim=/fit=/text=) -------
    for tok in tokens[1:]:
        if tok.startswith("role="):
            value = tok[5:]
            _apply_role_flag(shot, value, tok)
            continue
        if tok.startswith("layout="):
            value = tok[7:]
            _apply_layout_flag(shot, value, tok)
            continue
        fm = FLAG_RE.match(tok)
        if not fm:
            shot.warnings.append(
                f"check 25: token {tok!r} matches no flag or overlay "
                f"pattern; token ignored"
            )
            continue
        name = fm.group(1)
        value = fm.group(2) or ""
        # `piece` and `duo` are no longer flat flags; they come via `layout=`.
        if name in LAYOUTS_DYNAMIC:
            shot.warnings.append(
                f"check 25: {name!r} is no longer a flat flag — use "
                f"layout={name!r} (spec §7 redesign) — token ignored"
            )
            continue
        _apply_flag(shot, name, value, tok)
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
            is_role = role in ROLES_DYNAMIC  # any vocab role; payload becomes a role block

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

            if is_role:
                # A role shot always opens its own screen.  Implicit merge is
                # removed (§4); a role shot directly following another shot is
                # the would-be merge and gets the did-you-mean hint.
                if cur is not None and cur.shots and not cur.has_vo_or_screen_text():
                    talk.warnings.append(
                        f"line {shot.line}: role '{role}' shot directly "
                        f"follows another shot with no content between; "
                        f"implicit merge is removed — write role={role} on the "
                        f"media shot instead (e.g. '<!-- shot: <slug> "
                        f"role={role} -->'); this shot opens its own screen"
                    )
                new_screen(shot.line).shots.append(shot)
                credits_open = shot.slug is None and _canonical_role_kind(role) == "credits"  # bare end-roll screen
                pending_role = role
                role_line = shot.line
                continue

            # Ordinary screen opener: media shot, flag-only shot, black beat,
            # or a media shot that also carries a role (role written on the
            # screen's own shot).
            if cur is not None and cur.shots and not cur.has_content():
                talk.warnings.append(
                    f"line {shot.line}: consecutive shot directives with no "
                    f"content between; the second opens a new screen and the "
                    f"first stays an empty beat"
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
            is_spoken = False
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
                bkind = _canonical_role_kind(pending_role)
                is_spoken = _role_spoken(pending_role)
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
                Block(kind=bkind, text=spoken, stage=stage, line=rb.get("line", 0),
                      spoken=is_spoken)
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
