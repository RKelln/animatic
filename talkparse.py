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
- A role's payload is the NEXT PARAGRAPH ON ITS SCREEN after any leading
  quote / attribution / list blocks (`<!-- shot: <slug> role=paraphrase -->`
  with a `>` quote, its `~ ` attribution, then a paragraph: the paragraph is
  the payload).  One screen therefore carries the source's words AND our own
  line.  The payload is that role's screen text; a spoken role (`stat`,
  `paraphrase`) is also VO.  A role whose screen never produces a paragraph
  warns — the payload is still required, only the position is relaxed.
- Roles attach to a screen through the `role=` flag, written on the screen's
  own shot (`<!-- shot: <slug> role=<role> -->`).  There is NO implicit merge:
  a bare role shot always opens its own screen, and one that directly follows
  another shot warns with a did-you-mean hint to write `role=` on the media
  shot instead (spec: Text).
- A bare credits shot opens a credits SCREEN (end roll) that consumes every
  following paragraph, list item, and heading as screen content until the
  next shot or movement boundary.
- `<!-- shot: black -->` opens a deliberate black-beat screen: full-stage
  silence, no payload, nothing consumed. Author a shot afterwards to
  continue.
- Parentheses `( ... )` are never spoken and never on screen (grammar rule 2).
  They are extracted into stage directions that travel with the cue.
  Parens do not nest: a nested `(` is a warning (register check 23, spec: Text)
  — the strip recognizes one level only, and nesting would corrupt the
  spoken text.
- Numbered lists (`1.` or `1)`) are lists with `ordered` set, and pipe tables
  (rows starting `|`, an optional `|---|` delimiter row marking the header)
  are `table` blocks. Both are screen objects like `-` lists: on the slide
  and in the handout, never spoken.
- Footnote references `[^id]` are inert like parentheticals: stripped from
  every text block — never spoken, never on screen, never verbatim in the
  handout — and each referenced id is collected on Talk.footnote_ids in
  first-appearance order, for the handout citation list (spec: Text).
- `## Movement N · Title` headers are structural: they close the current
  screen, open a new movement, and never become slides themselves.  An H2
  beginning with "Movement" (case-insensitive) that fails the pattern is a
  FATAL error (register check 22) — left silent, it becomes an on-screen
  heading and merges screens.
- No token in a shot comment is silently dropped: a token that is neither a
  slug, a role, a layout, nor a known flag WARNS (register check 25).  An
  unknown FIRST token stays a slug (token-position rule, The shot directive); its
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
from pathlib import Path
from typing import Optional

import yaml

SHOT_RE = re.compile(r"^\s*<!--\s*shot(?::\s*(.*?))?\s*-->\s*$")
# `<!-- include: path [live] -->` on its own line splices another file's
# screens in (spec: Includes).  Only the `live` modifier exists so far.
INCLUDE_RE = re.compile(r"^\s*<!--\s*include:\s*(\S+)((?:\s+\S+)*?)\s*-->\s*$")
INCLUDE_FLAGS = ("live",)
INCLUDE_MAX_DEPTH = 3
# Role vocabulary (Tier A frozen, config-driven via roles.yaml).
# The yaml drives the vocabulary; this set is the frozen token set the
# tokenizer recognizes as `role=<name>` (replaces the old +overlay syntax).
ROLES = ("stat", "lower", "credits")
BLACK_ROLE = "black"
# `<!-- shot: continue ... -->` (alias `cont`): the screen takes the previous
# screen's media and flags, and a video keeps playing across the step instead
# of starting over.  Reserved like `black`: a first token, never a slug.
CONTINUE_WORDS = ("continue", "cont")
# Config-driven vocabulary loaded from roles.yaml + per-deck override.
# Fallback when no yaml present: the built-in roles above.
# Layout vocabulary (Tier B, config-driven via layouts.yaml).
LAYOUTS = ("piece", "duo", "titled")
# Known flags (spec: The shot directive Tier B table — per-shot flags; role/layout now config flags).
KNOWN_FLAGS = ("kb", "dim", "fit", "text", "advance", "playback", "sound", "silent",
               "under", "blur", "anchor", "still", "reveal", "live")
# `reveal=` shows a screen's content one piece per next-press.  `list` is the
# only form so far (a list's items); the value leaves room for more.
REVEAL_VALUES = ("list",)
# `still=` (and a card's `still:`) picks the frame a video becomes in the
# handout: start, end, a time in seconds (`3`, `3.5`, `3s`) or a share of the
# clip (`25%`).  Unset, a quarter of the way in.
STILL_RE = re.compile(r"(start|end|\d+(?:\.\d+)?s?|\d+(?:\.\d+)?%)")


def parse_still(spec) -> Optional[tuple]:
    """('start',) | ('end',) | ('sec', t) | ('frac', f), or None if invalid."""
    spec = str(spec).strip().lower()
    if not STILL_RE.fullmatch(spec):
        return None
    if spec in ("start", "end"):
        return (spec,)
    if spec.endswith("%"):
        pct = float(spec[:-1])
        return ("frac", pct / 100.0) if pct <= 100 else None
    return ("sec", float(spec.rstrip("s")))

FIT_VALUES = ("cover", "contain", "hero")
# `playback=` on a shot overrides the card's `playback:` for that screen.
# `advance` is stored as the `advance` flag; `pingpong` is card-only (a baked
# forward+reverse file, so one screen cannot switch to it).
SHOT_PLAYBACK_VALUES = ("once", "loop", "advance")
SOUND_VALUES = ("true", "false")
# `blur=` softens the `under=` backdrop only, in CSS pixels
BLUR_MAX = 100
# `anchor=` places an `under=` media that is smaller than the frame
ANCHOR_VALUES = ("top", "center", "bottom")
# `silent` is `sound=false`: mutes a card's `sound: true` on this screen
# Movement recognition is case-insensitive (the frozen rule is the *shape*,
# `Movement <integer> [separator] [title]`, not the typography — report Media).
MOVEMENT_RE = re.compile(
    r"^Movement\s+(\d+)\s*[|.:\-\u00b7]?\s*(.*)$", re.IGNORECASE)
# Fatal-start probe for check 22: an H2 whose text begins with the *word*
# "Movement" (case-insensitive) but fails MOVEMENT_RE.
MOVEMENT_LOOK_RE = re.compile(r"^movement\b", re.IGNORECASE)
HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
QUOTE_RE = re.compile(r"^>\s?(.*)$")
LIST_ITEM_RE = re.compile(r"^[-*+]\s+(.*)$")
HR_RE = re.compile(r"^\s*(?:-{3,}|\*{3,}|_{3,})\s*$")
ORDERED_ITEM_RE = re.compile(r"^\d+[.)]\s+(.*)$")
# an indented list item (a sub-point under the list item above it)
SUB_ITEM_RE = re.compile(r"^(\s+)(?:[-*+]|\d+[.)])\s+(.*)$")
# a pipe table row: starts with `|` (GFM's leading pipe is required here, so a
# prose line with a stray pipe never becomes a table); the delimiter row
# (`|---|:--:|`) marks the row above it as the header
TABLE_ROW_RE = re.compile(r"^\|(.*)$")
TABLE_DELIM_RE = re.compile(r"^\|?\s*:?-+:?\s*(?:\|\s*:?-+:?\s*)*\|?\s*$")
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
    """Effective (roles, layouts) vocabulary for a deck.

    `deck_path` is the directory that holds the talkfile — resolution is
    deck -> shared -> built-in (spec: Roles): a `roles.yaml` sitting next to
    the talkfile layers over the shared repo vocabulary, and the built-in
    sets stand in only when no yaml exists at all.  Callers that pass nothing
    (or a directory with no yaml, e.g. the historic literal `deck/`) get the
    shared vocabulary alone.
    """
    from pathlib import Path
    base = Path(__file__).resolve().parent
    deck_path = Path(str(deck_path) if deck_path else base / "deck")
    roles = set()
    for p in [base / "roles.yaml", deck_path / "roles.yaml"]:
        if p.exists():
            roles |= _load_roles_yaml(p)
    roles = roles or set(ROLES)
    layouts = set()
    for p in [base / "layouts.yaml", deck_path / "layouts.yaml"]:
        if p.exists():
            layouts |= _load_layouts_yaml(p)
    layouts = layouts or set(LAYOUTS)
    return tuple(sorted(roles)), tuple(sorted(layouts))

ROLES_DYNAMIC, LAYOUTS_DYNAMIC = load_vocab()

# Full role bundles (name -> {spoken, form}) drive the parser's
# role -> block-kind mapping and spoken routing.  The hardcoded defaults are
# the fallback when no roles.yaml is present; the yaml (deck -> shared)
# overrides them.  Adding a role = adding one line to roles.yaml (Text).
_DEFAULT_ROLE_BUNDLES = {
    "stat": {"spoken": True, "form": "callout"},
    "lower": {"spoken": False, "form": "lower-third"},
    "credits": {"spoken": False, "form": "end-roll"},
}

# form -> canonical block kind (the fixed IR vocabulary render.py consumes).
FORM_TO_KIND = {"callout": "stat", "lower-third": "lower", "end-roll": "credits",
                "paraphrase": "paraphrase"}


def load_role_bundles(deck_path=None):
    """Role name -> {spoken, form} from roles.yaml (deck wins over shared)
    with the hardcoded defaults as fallback.

    `deck_path` is the directory that holds the talkfile (spec: Roles — the
    per-deck override); the shared repo roles.yaml is always layered in
    first, so a deck's own file adds to the vocabulary and may restate a
    shared role to change it.
    """
    from pathlib import Path
    base = Path(__file__).resolve().parent
    deck_path = Path(str(deck_path) if deck_path else base / "deck")
    bundles = {}
    for p in [base / "roles.yaml", deck_path / "roles.yaml"]:
        if p.exists():
            try:
                data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
                roles = data.get("roles", {})
                if isinstance(roles, dict):
                    for name, b in roles.items():
                        if isinstance(b, dict):
                            bundles[str(name)] = {
                                "spoken": bool(b.get("spoken", False)),
                                "form": str(b.get("form", "")),
                            }
            except Exception:
                pass
    return bundles or dict(_DEFAULT_ROLE_BUNDLES)


ROLE_BUNDLES = load_role_bundles()


def _canonical_role_kind(role: str, bundles: Optional[dict] = None) -> str:
    """Role name -> canonical block kind via the yaml form.

    `bundles` is the CALLING deck's role vocabulary (deck -> shared ->
    built-in); the module-level bundles are the fallback for callers that
    parsed with no deck context.
    """
    bundles = ROLE_BUNDLES if bundles is None else bundles
    form = bundles.get(role, {}).get("form", "")
    return FORM_TO_KIND.get(form, role)


def _role_spoken(role: str, bundles: Optional[dict] = None) -> bool:
    bundles = ROLE_BUNDLES if bundles is None else bundles
    return bool(bundles.get(role, {}).get("spoken", False))


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


@dataclass
class Shot:
    """One parsed shot directive.

    slug    extensionless media slug.  Present unless the shot is role-only,
            flag-only, or bare.  An unknown first token becomes the slug by
            the token-position rule (The shot directive); role/flag typos surface later as a
            placeholder-reason hint (Media) and register check 25 warnings on
            the remaining tokens.
    role    the role this shot brings to its screen: 'stat' | 'lower' |
            'credits' (Tier A) or BLACK_ROLE for a black beat.  Set from a
            `role=<name>` flag token or a bare role/black first token.
    flags   {'kb': 'in', 'dim': '0.35', ...} — known flags only (The shot directive).
    warnings  token-level notes (register check 25): no token in a shot
            comment is silently dropped.
    """

    slug: Optional[str] = None
    role: Optional[str] = None       # 'stat' | 'lower' | 'credits' | 'black' | None
    flags: dict = field(default_factory=dict)   # {'kb': 'in', 'dim': '0.35', ...}
    raw: str = ""
    line: int = 0
    # First source line the directive occupies.  Equal to `line` for a
    # single-line shot; earlier when the directive is wrapped across lines
    # (spec: Screens, check 27).  `line` stays the *reported* line — where the
    # directive closes — because warnings anchor there (check 26); `line_begin`
    # is the screen boundary the nav sidecar seeks to (spec: Outputs,
    # addressability).
    line_begin: int = 0
    warnings: list = field(default_factory=list)
    # `continue` shot: True from the tokenizer; the assembler then fills
    # `slug`/`flags` from the previous screen's media shot.
    cont: bool = False
    # Chain id shared by a media shot and every `continue` screen after it
    # (the head's line number as a string); None when the shot is in no chain.
    chain: Optional[str] = None
    # The include directive's path as authored, when this shot came from an
    # included file (nav.json reports it); None for the talkfile's own shots.
    include: Optional[str] = None

    @property
    def is_role(self) -> bool:
        return self.role in ROLES_DYNAMIC

    @property
    def is_media(self) -> bool:
        """A slug always resolves as media — even on a shot that also carries
        a role (spec: Text)."""
        return self.slug is not None


@dataclass
class Block:
    """One content block on a screen, in document order."""

    kind: str                     # vo|heading|handout-heading|quote|quote-source|list|table|stat|lower|credits|paraphrase
    text: str = ""                # for vo/heading/quote/stat/lower/credits/paraphrase
    level: Optional[int] = None   # heading depth (1..6)
    items: list = field(default_factory=list)   # list items
    ordered: bool = False         # numbered list (`1.` items)
    depths: list = field(default_factory=list)  # list: nesting depth per item (0 = top); empty when flat
    rows: list = field(default_factory=list)    # table: list of rows of cell strings
    header: bool = False          # table: rows[0] is the header row
    stage: list = field(default_factory=list)   # extracted parentheticals
    spoken: bool = False          # role payload is spoken VO (from roles.yaml)
    line: int = 0                 # first source line of the block
    line_end: int = 0             # last source line: merged soft-wrap or a
                                  # multi-line quote / list occupies every line
                                  # in between, so the screen's range must too
    refs: list = field(default_factory=list)    # handout only: (source id, the text just before the `[^id]`)


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
    def include(self) -> Optional[str]:
        """The authored include path this screen came from, if any."""
        return self.shots[0].include if self.shots else None

    @property
    def live_only(self) -> bool:
        """True when any shot carries the bare `live` flag: the screen belongs
        to the live deck only (present + presenter views).  The document view
        / handout leaves it out and cues.json marks it, so a video render
        skips it."""
        return any("live" in s.flags for s in self.shots)

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

    @property
    def line_range(self) -> tuple[int, int]:
        """(first, last) source line this screen owns — the addressable span.

        A screen is a run of the source file: its opening shot and every block
        that follows, up to the last line it occupies (spec: Outputs —
        `nav.json` maps cue id -> line range).  The range is the envelope of
        the spans its items carry, so a soft-wrapped paragraph or a multi-line
        shot directive extends it to its real last line, and a range never
        crosses the next screen's boundary.  Lines the grammar drops (blank
        lines, non-shot comments, `---`, movement headings) belong to no screen
        and fall between ranges.
        """
        starts: list[int] = []
        ends: list[int] = []
        for shot in self.shots:
            if shot.line:
                starts.append(shot.line_begin or shot.line)
                ends.append(shot.line)
        for b in self.blocks:
            if b.line:
                starts.append(b.line)
                ends.append(b.line_end or b.line)
        if not starts:
            return (self.line, self.line)
        return (min(starts), max(ends))


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
    footnote_ids: list = field(default_factory=list)   # `[^id]` refs, doc order (Text)
    # The vocabulary THIS deck parsed with (deck -> shared -> built-in, spec:
    # Roles / The shot directive).  Carried on the model so a checker can ask
    # "was this role known for this deck?" without re-deriving the deck dir.
    role_vocab: tuple = ()
    layout_vocab: tuple = ()
    role_bundles: dict = field(default_factory=dict)
    # Every file pulled in by `include:` (resolved, nested ones too), for
    # --watch and the footnote check.
    includes: list = field(default_factory=list)

    @property
    def role_names(self) -> set:
        """Vocabulary roles for this deck (module-level fallback for a model
        built without deck context)."""
        return set(self.role_vocab or ROLES_DYNAMIC)


# ---------------------------------------------------------------------------
# Inline helpers (shared by present + document views)
# ---------------------------------------------------------------------------


def split_parens(text: str) -> tuple[str, list]:
    """Return (text with ( ... ) removed, list of parenthetical contents).

    Parentheticals are never spoken / never on screen; they travel as stage
    notes.  Parens do NOT nest: the strip recognizes one level only — the
    innermost pair wins and the outer markers vanish from the spoken text.
    A nested `(` is a warning (register check 23, spec: Text), never a silent
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
    or None.  Register check 23 (spec: Text): parentheticals do not nest —
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


def strip_footnote_refs(text: str, collected: list, marks: Optional[list] = None) -> str:
    """Remove `[^id]` body-footnote references (spec: Text) from text.

    References are inert: never spoken, never on screen, never verbatim in
    the handout.  Each referenced id is appended to `collected` on first
    appearance (document order), giving the handout citation list its keys
    into the frontmatter `sources:` registry.  The `(?!:)` guard leaves an
    in-body `[^id]: …` definition line intact — receipts have no body-level
    definition form; a definition is its `sources:` registry entry (Frontmatter).
    """
    out = []
    last = 0
    for m in FOOTNOTE_REF_RE.finditer(text):
        out.append(text[last:m.start()])
        last = m.end()
        rid = m.group(1)
        if rid not in collected:
            collected.append(rid)
        if marks is not None:
            # where the ref sat: the text just before it, so the handout can
            # put the citation number back (Block.refs)
            marks.append((rid, "".join(out)[-40:]))
    out.append(text[last:])
    return "".join(out)


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


# A non-shot comment that trails prose on its own line (`text. <!-- note -->`,
# possibly running over several lines).  Comments that start a line are handled
# by the lexer; these would otherwise be read as spoken text (spec principle 4:
# non-directive comments are inert).
_TRAILING_COMMENT_RE = re.compile(r"(?<=\S)[ \t]*<!--(?!\s*shot\b).*?-->", re.S)


def _strip_trailing_comments(lines: list) -> list:
    """Drop trailing comments, keeping every newline so later lines keep
    their numbers."""
    text = "".join(l if l.endswith("\n") else l + "\n" for l in lines)
    if "<!--" not in text:
        return lines
    text = _TRAILING_COMMENT_RE.sub(lambda m: "\n" * m.group(0).count("\n"), text)
    return text.splitlines(keepends=True)


def _lex_blocks(lines: list, source: str, role_vocab=None, layout_vocab=None,
                line_offset: int = 0) -> list:
    """Tokenize source lines into primitive blocks (list of dicts).

    Blank lines separate paragraphs; consecutive non-blank prose lines merge
    (markdown soft-wrap).  Markers (heading / quote / list / comment / hr)
    always start a fresh block.  Non-shot comments are dropped: provenance and
    receipts live in the bank, per grammar rule 3.

    `role_vocab` / `layout_vocab` are the deck's effective vocabularies
    (deck -> shared -> built-in); they decide which `role=` / `layout=`
    tokens are known.
    """
    lines = _strip_trailing_comments(lines)
    blocks: list[dict] = []
    para_buf: list[str] = []
    para_line = 0
    para_end = 0
    cont = None  # (kind, block, last_lineno) for quote/list line merging
    comment_buf: Optional[list] = None
    comment_start = 0

    def flush_para():
        nonlocal para_buf, cont, para_end
        if para_buf:
            blocks.append({"kind": "para", "text": " ".join(para_buf),
                           "line": para_line, "line_end": para_end})
            para_buf = []
        para_end = 0
        cont = None

    # line numbers are the talkfile's own (an editor's), so the frontmatter
    # lines stripped before this point are counted back in via line_offset
    for lineno, raw in enumerate(lines, start=1 + line_offset):
        line = raw.rstrip("\n")

        # --- multi-line comment accumulation --------------------------------
        if comment_buf is not None:
            comment_buf.append(line)
            if "-->" in line:
                comment = " ".join(comment_buf)
                comment_buf = None
                if SHOT_RE.match(comment):
                    flush_para()
                    shot = _parse_shot(comment, lineno, role_vocab, layout_vocab)
                    shot.line_begin = comment_start
                    blocks.append(
                        {"kind": "shot", "shot": shot, "line": lineno,
                         "line_end": lineno}
                    )
            continue
        if line.lstrip().startswith("<!--"):
            if "-->" not in line:
                comment_buf = [line]
                comment_start = lineno
                continue
            if SHOT_RE.match(line):
                flush_para()
                shot = _parse_shot(line, lineno, role_vocab, layout_vocab)
                shot.line_begin = lineno
                blocks.append(
                    {"kind": "shot", "shot": shot, "line": lineno,
                     "line_end": lineno}
                )
            else:
                im = INCLUDE_RE.match(line)
                if im:
                    flush_para()
                    blocks.append(
                        {"kind": "include", "path": im.group(1),
                         "flags": im.group(2).split(), "line": lineno,
                         "line_end": lineno}
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
                 "line": lineno, "line_end": lineno}
            )
            continue

        # --- blockquote lines ------------------------------------------------
        qm = QUOTE_RE.match(line)
        if qm:
            if cont and cont[0] == "quote" and lineno == cont[2] + 1:
                # a blank `>` line is a paragraph break inside the quote,
                # kept as "\n\n" in the text (the views split on it)
                piece = qm.group(1).strip()
                if not piece:
                    cont[1]["para_break"] = True
                elif cont[1].pop("para_break", False) and cont[1]["text"]:
                    cont[1]["text"] += "\n\n" + piece
                else:
                    cont[1]["text"] += " " + piece
                cont[1]["line_end"] = lineno
                cont[2] = lineno
            else:
                flush_para()
                block = {"kind": "quote", "text": qm.group(1).strip(),
                         "line": lineno, "line_end": lineno}
                blocks.append(block)
                cont = ["quote", block, lineno]
            continue

        # --- list items -------------------------------------------------------
        # `-` and `1.` items make separate lists: a switch starts a new block.
        lm = LIST_ITEM_RE.match(line)
        om = None if lm else ORDERED_ITEM_RE.match(line)
        # An indented item directly under a list item is a sub-point (either
        # marker); indented anywhere else it is not a list item, as before.
        sub = None
        if not (lm or om) and line[:1] in (" ", "\t") \
                and cont and cont[0] in ("list", "olist") and lineno == cont[2] + 1:
            sub = SUB_ITEM_RE.match(line)
        if sub:
            blk = cont[1]
            ind = len(sub.group(1).expandtabs(4))
            stack = blk["indents"]
            while len(stack) > 1 and ind < stack[-1]:
                stack.pop()
            if ind > stack[-1]:
                stack.append(ind)
            blk["items"].append(sub.group(2).strip())
            blk["depths"].append(len(stack) - 1)
            blk["line_end"] = lineno
            cont[2] = lineno
            continue
        if lm or om:
            ckind = "olist" if om else "list"
            item = (lm or om).group(1).strip()
            if cont and cont[0] == ckind and lineno == cont[2] + 1:
                cont[1]["items"].append(item)
                cont[1]["depths"].append(0)
                cont[1]["indents"] = [0]
                cont[1]["line_end"] = lineno
                cont[2] = lineno
            else:
                flush_para()
                block = {"kind": "list", "items": [item], "ordered": bool(om),
                         "depths": [0], "indents": [0],
                         "line": lineno, "line_end": lineno}
                blocks.append(block)
                cont = [ckind, block, lineno]
            continue

        # --- table rows -------------------------------------------------------
        tm = TABLE_ROW_RE.match(line.strip())
        if tm:
            if cont and cont[0] == "table" and lineno == cont[2] + 1:
                block = cont[1]
            else:
                flush_para()
                block = {"kind": "table", "rows": [], "header": False,
                         "line": lineno, "line_end": lineno}
                blocks.append(block)
                cont = ["table", block, lineno]
            if TABLE_DELIM_RE.match(line.strip()):
                # the delimiter row marks the rows above it as the header
                if len(block["rows"]) == 1:
                    block["header"] = True
            else:
                cells = line.strip()[1:]
                if cells.rstrip().endswith("|"):
                    cells = cells.rstrip()[:-1]
                block["rows"].append([c.strip() for c in cells.split("|")])
            block["line_end"] = lineno
            cont[2] = lineno
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
        para_end = lineno

    flush_para()
    return blocks


def _apply_role_flag(shot: Shot, value: str, token: str, vocab=None) -> None:
    """Apply a `role=<name>` flag token against the deck's role vocabulary."""
    vocab = tuple(vocab) if vocab is not None else ROLES_DYNAMIC
    if value not in set(vocab):
        shot.warnings.append(
            f"check 25: {token!r} names unknown role {value!r}; "
            f"known roles: {', '.join(vocab)} — token ignored"
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


def _apply_layout_flag(shot: Shot, value: str, token: str, vocab=None) -> None:
    """Apply a `layout=<name>` flag token (replaces flat piece/duo)."""
    vocab = tuple(vocab) if vocab is not None else LAYOUTS_DYNAMIC
    if value not in set(vocab):
        shot.warnings.append(
            f"check 25: {token!r} names unknown layout {value!r}; "
            f"known layouts: {', '.join(vocab)} — token ignored"
        )
        return
    shot.flags["layout"] = value


def _apply_flag(shot: Shot, name: str, value: str, token: str) -> None:
    """Apply one known-flag token.  Unknown names and the removed valueless
    `fit` warn (check 25 / spec: The shot directive); nothing is silently accepted or dropped.

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
        # Removed form (The shot directive): historic bare `fit` took its meaning from what
        # followed the shot (lookahead).  No meaning of its own now.
        shot.warnings.append(
            f"valueless 'fit' has no meaning (removed form); write "
            f"fit={', fit='.join(FIT_VALUES)}"
        )
        return
    if name == "playback":
        if value not in SHOT_PLAYBACK_VALUES:
            why = (" (pingpong is card-only: it is a baked file)"
                   if value == "pingpong" else "")
            shot.warnings.append(
                f"check 25: {token!r}: a shot's playback is "
                f"playback={', playback='.join(SHOT_PLAYBACK_VALUES)}{why} "
                f"— token ignored"
            )
            return
        if value == "advance":
            # alias: the same flag as a bare `advance`
            shot.flags["advance"] = ""
            return
    if name == "under" and not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,38}[a-z0-9]", value or ""):
        shot.warnings.append(
            f"check 25: {token!r}: under names the backdrop image by slug, "
            f"under=<slug> — token ignored"
        )
        return
    if name == "blur":
        try:
            ok = 0 <= float(value) <= BLUR_MAX
        except ValueError:
            ok = False
        if not ok:
            shot.warnings.append(
                f"check 25: {token!r}: blur is a radius in pixels, blur=0 to "
                f"blur={BLUR_MAX} — token ignored"
            )
            return
    if name == "still" and parse_still(value) is None:
        shot.warnings.append(
            f"check 25: {token!r}: still picks the video frame the handout "
            f"prints, still=start, still=end, still=<seconds> or still=<n>% "
            f"— token ignored"
        )
        return
    if name == "reveal" and value not in REVEAL_VALUES:
        shot.warnings.append(
            f"check 25: {token!r}: reveal says what appears one by one, "
            f"reveal={', reveal='.join(REVEAL_VALUES)} — token ignored"
        )
        return
    if name == "anchor" and value not in ANCHOR_VALUES:
        shot.warnings.append(
            f"check 25: {token!r}: anchor places the media on the frame, "
            f"anchor={', anchor='.join(ANCHOR_VALUES)} — token ignored"
        )
        return
    if name == "silent":
        if value:
            shot.warnings.append(
                f"check 25: {token!r}: silent takes no value — token ignored")
            return
        name, value = "sound", "false"
    if name == "sound":
        value = value or "true"
        if value not in SOUND_VALUES:
            shot.warnings.append(
                f"check 25: {token!r}: write sound, sound=true or sound=false "
                f"— token ignored"
            )
            return
    shot.flags[name] = value


def _parse_shot(raw: str, line: Optional[int] = None,
                role_vocab=None, layout_vocab=None) -> Shot:
    """Parse a full `<!-- shot ... -->` comment into a Shot.

    `line` is the directive's 1-based source line, threaded from every
    `_lex_blocks` call site so the Shot is never born with line 0: warnings
    raised from a shot must name the directive's real line to be actionable
    (check 26, spec: Error and warning taxonomy — no warning text contains "line 0").  A shot
    directive MAY span multiple lines (spec: Screens, check 27); interior
    whitespace is insignificant, and a multi-line directive is reported at
    the line where it closes.

    `role_vocab` / `layout_vocab` are the deck's effective vocabularies; they
    decide which `role=` / `layout=` tokens are known.

    Token vocabulary (spec: Screens/Text/The shot directive): the FIRST token is the shot's slug, its
    role (stat/lower/credits/black), a `role=<name>` flag, a `layout=<name>`
    flag, or — for flag-only shots — a known flag.  Later tokens are flags
    (`name=value`).  An unknown first token stays a slug (token-position rule,
    The shot directive).  Every other unrecognized token WARNS (register check 25): nothing in
    a shot comment is silently dropped.
    """
    m = SHOT_RE.match(raw)
    spec = (m.group(1) or "").strip() if m else ""
    shot = Shot(raw=raw, line=line or 0)
    if not spec:
        return shot
    tokens = spec.split()
    first = tokens[0]
    vocab = tuple(role_vocab) if role_vocab is not None else ROLES_DYNAMIC

    # --- first token: slug | role=<name> flag | layout=<name> | black | known flag ----------
    if first in CONTINUE_WORDS:
        # continue the previous screen's media (resolved in assemble)
        shot.cont = True
    elif first in vocab or first == BLACK_ROLE:
        # Bare role shot (e.g. `<!-- shot: stat -->`) — opens its own screen.
        # The `role=` syntax is preferred; bare role preserved for backward compat.
        shot.role = first
    elif first.startswith("role="):
        value = first[5:]
        _apply_role_flag(shot, value, first, vocab)
    elif first.startswith("layout="):
        value = first[7:]
        _apply_layout_flag(shot, value, first, layout_vocab)
    else:
        fm = FLAG_RE.match(first)
        if fm and fm.group(1) in KNOWN_FLAGS:
            # flag-only shot (Screens): the first token is a known flag, so the
            # screen is card-only — no media slug, no role.
            _apply_flag(shot, fm.group(1), fm.group(2) or "", first)
        elif fm and fm.group(2) is not None:
            # `name=value` shape with an unknown name: slugs are bare tokens,
            # so this cannot be a slug — a flag typo.
            _apply_flag(shot, fm.group(1), fm.group(2), first)
        else:
            # Unknown first token: stays a slug (token-position rule, The shot directive).
            # A role/flag typo surfaces honestly later: media resolution
            # fails and the placeholder reason adds the "if 'hero' was meant
            # as a role or flag, it is neither" hint (Media, mediaresolve.py).
            shot.slug = first

    # --- remaining tokens: flags (role=/layout=/kb=/dim=/fit=/text=) -------
    for tok in tokens[1:]:
        if tok.startswith("role="):
            value = tok[5:]
            _apply_role_flag(shot, value, tok, vocab)
            continue
        if tok.startswith("layout="):
            value = tok[7:]
            _apply_layout_flag(shot, value, tok, layout_vocab)
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
        if name in (tuple(layout_vocab) if layout_vocab is not None else LAYOUTS_DYNAMIC):
            shot.warnings.append(
                f"check 25: {name!r} is no longer a flat flag — use "
                f"layout={name!r} (spec: The shot directive redesign) — token ignored"
            )
            continue
        _apply_flag(shot, name, value, tok)
    return shot


# ---------------------------------------------------------------------------
# Screen assembler
# ---------------------------------------------------------------------------


def _resolve_continue(shot: Shot, screens: list, talk) -> None:
    """Point a `continue` shot at the previous screen's media.

    The previous screen must carry media; the shot takes its slug and flags,
    with any flag written on the continue shot winning.  Head and continuation
    share a chain id, which the present view uses to hand the playing video
    from one slide to the next.  Without a media screen before it, the shot
    warns and stays a media-less screen.
    """
    prev = screens[-1].media_shot if screens else None
    if prev is None:
        talk.warnings.append(
            f"line {shot.line}: 'continue' shot has no media screen before it "
            f"to continue; the screen opens without media"
        )
        return
    if "advance" in shot.flags and "advance" not in prev.flags:
        # the playing video is the chain head's element, carried along, so
        # its playback is the head's: a looping head never ends
        talk.warnings.append(
            f"line {shot.line}: 'advance' on a continue shot has no effect; "
            f"write it on the first shot of the chain (line {prev.chain or prev.line})"
        )
    for name in ("playback", "sound"):
        if name in shot.flags and shot.flags[name] != prev.flags.get(name):
            talk.warnings.append(
                f"line {shot.line}: '{name}={shot.flags[name]}' on a continue shot "
                f"has no effect; write it on the first shot of the chain "
                f"(line {prev.chain or prev.line})"
            )
        # the chain plays as its head says, even on a slide reached directly
        shot.flags.pop(name, None)
    if prev.chain is None:
        prev.chain = str(prev.line)
    shot.chain = prev.chain
    shot.slug = prev.slug
    own_live = "live" in shot.flags
    shot.flags = {**prev.flags, **shot.flags}
    if not own_live:
        shot.flags.pop("live", None)     # live-only belongs to one screen


def _heading_run_opens_at_shot(raw_blocks: list, i: int) -> bool:
    """True when heading `i` belongs to a run of headings that starts right
    after a shot: a title card (`# Title`, `## Date`, `### Website`) keeps every
    heading on its slide, not only the first.  Movement headings are structure
    and end the run."""
    j = i - 1
    while j >= 0 and raw_blocks[j]["kind"] == "heading" and not (
            raw_blocks[j]["level"] == 2 and MOVEMENT_RE.match(raw_blocks[j]["text"])):
        j -= 1
    return j >= 0 and raw_blocks[j]["kind"] == "shot"


def _include_error(source: str, line: int, msg: str) -> ValueError:
    # same shape as check 22 so check.py reports it as a fatal with its line
    return ValueError(f"{source}:{line}: check 22: {msg}")


def _expand_includes(raw_blocks: list, host: "Path", source: str, role_vocab,
                     layout_vocab, stack: tuple, includes: list,
                     frag_meta: list) -> list:
    """Replace each `include` block with the included file's blocks.

    Each file is lexed on its own, so line numbers, paragraph state and
    comments never cross files.  Every block from an included file is pinned
    to the include directive's line in the file that wrote it, so warnings
    and nav.json ranges point somewhere the author can find.  Flags written
    on the directive (`live`) are applied to every shot inside.
    """
    out: list = []
    for rb in raw_blocks:
        if rb["kind"] != "include":
            out.append(rb)
            continue
        line, rel = rb["line"], rb["path"]
        bad = [f for f in rb["flags"] if f not in INCLUDE_FLAGS]
        if bad:
            raise _include_error(source, line, f"include flag {bad[0]!r} unknown; "
                                 f"known: {', '.join(INCLUDE_FLAGS)}")
        if Path(rel).is_absolute():
            raise _include_error(source, line, f"include path {rel!r} must be "
                                 f"relative to the including file")
        target = (host.parent / rel).resolve()
        if not target.is_file():
            raise _include_error(source, line, f"include file not found: {rel}")
        if target in stack:
            raise _include_error(source, line, f"include cycle through {rel}")
        if len(stack) >= INCLUDE_MAX_DEPTH:
            raise _include_error(source, line, f"includes nested deeper than "
                                 f"{INCLUDE_MAX_DEPTH}")
        body = target.read_text(encoding="utf-8")
        fsource = str(target)
        meta, lines = _lex_frontmatter(body, fsource)
        offset = body.count("\n") + 1 - len(lines)
        fblocks = _lex_blocks(lines, fsource, role_vocab, layout_vocab,
                              line_offset=offset)
        fblocks = _expand_includes(fblocks, target, fsource, role_vocab,
                                   layout_vocab, stack + (target,), includes,
                                   frag_meta)
        if target not in includes:
            includes.append(target)
        frag_meta.append(meta)
        for fb in fblocks:
            if fb["kind"] == "heading" and fb["level"] == 2 \
                    and MOVEMENT_LOOK_RE.match(fb["text"]):
                raise _include_error(fsource, fb["line"], "a section cannot "
                                     "hold a Movement heading; it lives inside "
                                     "the including talk's movement")
            fb["line"] = fb["line_end"] = line
            if fb["kind"] == "shot":
                sh = fb["shot"]
                sh.line_begin = line
                sh.include = rel          # the outermost directive wins
                for f in rb["flags"]:
                    sh.flags[f] = ""
            out.append(fb)
    return out


def build_talk(path, source: Optional[str] = None) -> Talk:
    """Parse a talkfile path into a Talk model.

    The deck directory is the directory that HOLDS the talkfile: that is
    where a deck-local `roles.yaml` / `layouts.yaml` lives (deck -> shared ->
    built-in, spec: Roles), so the vocabulary the parser accepts and the one
    the checker reports against are resolved once, here.
    """
    source = source or str(path)
    with open(path, "r", encoding="utf-8") as fh:
        body = fh.read()
    deck_dir = Path(path).resolve().parent
    role_vocab, layout_vocab = load_vocab(deck_dir)
    role_bundles = load_role_bundles(deck_dir)
    meta, lines = _lex_frontmatter(body, source)
    # every line number is the talkfile's own, frontmatter included
    # (2026-09-28; was body-relative, which put L01's warnings 64 lines off)
    offset = body.count("\n") + 1 - len(lines)
    raw_blocks = _lex_blocks(lines, source, role_vocab, layout_vocab,
                             line_offset=offset)
    includes: list = []
    frag_meta: list = []
    raw_blocks = _expand_includes(raw_blocks, Path(path).resolve(), source,
                                  role_vocab, layout_vocab,
                                  (Path(path).resolve(),), includes, frag_meta)
    # an included file's `cites:` / `sources:` join the talk's; the talk wins
    for fm in frag_meta:
        for key in ("cites", "sources"):
            if isinstance(fm.get(key), dict):
                merged = dict(fm[key])
                merged.update(meta.get(key) if isinstance(meta.get(key), dict) else {})
                meta[key] = merged
    talk = assemble(meta, raw_blocks, source, role_vocab=role_vocab,
                    layout_vocab=layout_vocab, role_bundles=role_bundles)
    talk.includes = includes
    return talk


def assemble(meta: dict, raw_blocks: list, source: str,
             role_vocab=None, layout_vocab=None, role_bundles=None) -> Talk:
    talk = Talk(meta=meta, source=source)
    vocab = tuple(role_vocab) if role_vocab is not None else tuple(ROLES_DYNAMIC)
    bundles = dict(role_bundles) if role_bundles is not None else dict(ROLE_BUNDLES)
    talk.role_vocab = vocab
    talk.layout_vocab = (tuple(layout_vocab) if layout_vocab is not None
                         else tuple(LAYOUTS_DYNAMIC))
    talk.role_bundles = bundles
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

    # Handout headings: a heading written directly before a shot (and not
    # directly after one) titles the NEXT screen in the handout and nav only;
    # it is never drawn on a slide. Held here until that shot opens its screen.
    pending_handout: list[Block] = []

    def take_handout() -> None:
        nonlocal pending_handout
        if pending_handout and cur is not None:
            cur.blocks[0:0] = pending_handout
            pending_handout = []

    for i_rb, rb in enumerate(raw_blocks):
        kind = rb["kind"]

        if kind == "shot":
            shot: Shot = rb["shot"]
            shot.line = rb.get("line", 0) or 0
            for w in shot.warnings:          # tokenizer notes (check 25)
                talk.warnings.append(f"line {shot.line}: {w}")
            if shot.cont:
                _resolve_continue(shot, screens, talk)
            role = shot.role
            is_role = role in vocab          # any vocab role; payload becomes a role block

            # A role's payload paragraph never crosses a shot boundary: if a
            # previous role shot is still waiting for its paragraph, it lost
            # it the moment the next shot arrived (spec: Text — the paragraph
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
                # removed (Text); a role shot directly following another shot is
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
                take_handout()
                credits_open = shot.slug is None and _canonical_role_kind(role or "", bundles) == "credits"  # bare end-roll screen
                pending_role = role
                role_line = shot.line
                continue

            # Ordinary screen opener: media shot, flag-only shot, black beat,
            # or a media shot that also carries a role (role written on the
            # screen's own shot).
            if (cur is not None and cur.shots and not cur.has_content()
                    and not cur.live_only):   # a live-only slide is a deliberate wordless beat
                talk.warnings.append(
                    f"line {shot.line}: consecutive shot directives with no "
                    f"content between; the second opens a new screen and the "
                    f"first stays an empty beat"
                )
            new_screen(shot.line).shots.append(shot)
            take_handout()
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
                    f"fatal (spec: Error and warning taxonomy: a malformed movement heading is "
                    f"never silently treated as screen text)"
                )

        # --- content blocks ---------------------------------------------------
        # Role payloads (stat / lower / overlay credits / paraphrase) expect a
        # paragraph.  The paragraph is the NEXT PARAGRAPH ON THIS SCREEN, not
        # necessarily the block that directly follows the shot: a leading
        # quote, its `~ ` attribution, and list items are screen objects that
        # ride ahead of the payload (spec: Roles — this is what lets one
        # screen carry the source's words AND our paraphrase).  Any other
        # block kind still means the payload is missing.
        # On a credits SCREEN (credits_open), paragraphs, list items, and
        # headings are screen content, consumed until the next shot.
        if (pending_role is not None and not credits_open
                and kind not in ("para", "vo", "quote", "list", "table")):
            # role shot expects a payload paragraph; a non-paragraph arrived
            talk.warnings.append(
                f"line {role_line}: '{pending_role}' shot not followed by a "
                f"paragraph payload (next block: {kind})"
            )
            pending_role = None

        if (kind == "heading" and not credits_open
                and i_rb + 1 < len(raw_blocks)
                and raw_blocks[i_rb + 1]["kind"] == "shot"
                and not _heading_run_opens_at_shot(raw_blocks, i_rb)):
            hmarks: list = []
            pending_handout.append(
                Block(kind="handout-heading", refs=hmarks,
                      text=strip_footnote_refs(rb["text"], talk.footnote_ids, hmarks),
                      level=rb["level"],
                      line=rb.get("line", 0),
                      line_end=rb.get("line_end", 0) or rb.get("line", 0))
            )
            continue

        if cur is None:
            new_screen(rb.get("line", 0))

        assert cur is not None

        if credits_open and kind == "heading":
            # A credits screen consumes paragraphs, list items, and headings
            # as screen content (spec: Text).  A quote is NOT consumed: it stays
            # a quote object, never satisfies the credits role, and the role
            # keeps waiting — so a quote in the would-be payload position
            # fires the never-consumed warning at the next boundary instead
            # of silently absorbing into the end roll.
            pending_role = None  # heading content satisfies the credits role

        if kind == "heading":
            if pending_role is not None and rb["level"] == 2:
                pass  # handled above; defensive
            hmarks: list = []
            cur.blocks.append(
                Block(kind="heading", refs=hmarks,
                      text=strip_footnote_refs(rb["text"], talk.footnote_ids, hmarks),
                      level=rb["level"],
                      line=rb.get("line", 0),
                      line_end=rb.get("line_end", 0) or rb.get("line", 0))
            )
            continue

        if kind == "quote":
            qmarks: list = []
            cur.blocks.append(
                Block(kind="quote", refs=qmarks,
                      text=strip_footnote_refs(rb["text"], talk.footnote_ids, qmarks),
                      line=rb.get("line", 0),
                      line_end=rb.get("line_end", 0) or rb.get("line", 0))
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
                            f"flat (spec: Text)"
                        )
                    spoken, stage = split_parens(clean)
                    cur.blocks.append(
                        Block(kind="credits", text=spoken, stage=stage,
                              line=rb.get("line", 0),
                              line_end=rb.get("line_end", 0) or rb.get("line", 0))
                    )
                pending_role = None
                continue
            cur.blocks.append(
                Block(kind="list",
                      items=[strip_footnote_refs(i, talk.footnote_ids)
                             for i in rb["items"]],
                      ordered=rb.get("ordered", False),
                      depths=(rb["depths"] if any(rb.get("depths", ())) else []),
                      line=rb.get("line", 0),
                      line_end=rb.get("line_end", 0) or rb.get("line", 0))
            )
            continue

        if kind == "table":
            cur.blocks.append(
                Block(kind="table",
                      rows=[[strip_footnote_refs(c, talk.footnote_ids)
                             for c in row] for row in rb["rows"]],
                      header=rb.get("header", False),
                      line=rb.get("line", 0),
                      line_end=rb.get("line_end", 0) or rb.get("line", 0))
            )
            continue

        if kind == "para":
            pmarks: list = []
            clean = strip_footnote_refs(rb["text"], talk.footnote_ids, pmarks)
            spoken, stage = split_parens(clean)
            np = nested_paren_at(clean)
            if np is not None:
                # check 23: the strip recognizes one level only — nesting
                # half-speaks the outer parenthetical unless the author fixes
                # it.  Warn once per paragraph, naming the collision site.
                talk.warnings.append(
                    f"line {rb.get('line', 0)}: check 23: parentheticals do "
                    f"not nest — '...{clean[max(0, np - 12):np + 12].strip()}...'; "
                    f"rewrite the parenthetical flat (spec: Text)"
                )
            bkind = "vo"
            is_spoken = False
            if (
                not credits_open
                and cur.blocks
                and cur.blocks[-1].kind == "quote"
                and spoken.startswith("~ ")
            ):
                # quote attribution: screen text, never VO.  Grammar: a
                # "~ Name, venue" paragraph whose immediately preceding block
                # is a quote (tilde stripped on screen).  `~` is the ONLY
                # attribution form (spec: Text; the `Source: ` shape was deleted
                # — T03/D4 — and falls through to VO with a check-24 warning).
                #
                # Attribution OUTRANKS a pending role payload: on the both-up
                # screen (quote + attribution + our paraphrase) the credit line
                # belongs to the quote, and the payload is the next paragraph.
                bkind = "quote-source"
                spoken = spoken[2:]
            elif pending_role is not None:
                bkind = _canonical_role_kind(pending_role, bundles)
                is_spoken = _role_spoken(pending_role, bundles)
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
                # quote (spec: Text); warn so the author never hears a credit
                # line read aloud by accident.
                talk.warnings.append(
                    f"line {rb.get('line', 0)}: check 24: attribution-looking "
                    f"line will be spoken — {spoken[:40]!r}; attribution is "
                    f"'~ ' on its own paragraph directly under a quote "
                    f"(spec: Text)"
                )
            cur.blocks.append(
                Block(kind=bkind, text=spoken, stage=stage, line=rb.get("line", 0),
                      line_end=rb.get("line_end", 0) or rb.get("line", 0),
                      spoken=is_spoken, refs=pmarks)
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
    # Line spans (spec: Outputs — nav.json maps cue id -> line range).  Every
    # item carries where it starts; anything built without an explicit end
    # occupies exactly one line, so the default here — never a silent 0 —
    # keeps screen.line_range an honest envelope for every construct.
    for s in talk.screens:
        for shot in s.shots:
            if not shot.line_begin:
                shot.line_begin = shot.line
        for b in s.blocks:
            if not b.line_end:
                b.line_end = b.line
    talk.warnings.sort()
    return talk
