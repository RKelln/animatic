"""talkparse.py — talkfile lexer + screen assembler.

Grammar source: docs/format-spec-v1.md (the normative spec in this repo).
Encoded parse-model decisions:

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

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

SHOT_RE = re.compile(r"^\s*<!--\s*shot(?::\s*(.*?))?\s*-->\s*$")
# `<!-- include: path [live] -->` on its own line splices another file's
# screens in (spec: Includes).  Only the `live` modifier exists so far.
# `(Do: ...)`: a stage note that is never spoken or printed; the agent export
# takes it as the step's exercise instructions (spec: Directions).
DO_NOTE_RE = re.compile(r"^\s*do\s*:\s*(.*)$", re.IGNORECASE | re.DOTALL)
INCLUDE_RE = re.compile(r"^\s*<!--\s*include:\s*(\S+)((?:\s+\S+)*?)\s*-->\s*$")
INCLUDE_FLAGS = ("live", "do")
# A bare name (`<!-- include: ai-terms -->`: no `/` and no `.`) is a section in
# the talk's section directory: frontmatter `include_sections:` when it is
# there, `../_sections` beside the deck directory otherwise.  The extension is
# the section naming convention, so the name stays a name.
INCLUDE_SECTION_EXT = ".section.md"
INCLUDE_SECTIONS_DEFAULT = "../_sections"
# `waypoint=word` in a screen's shot (`<!-- shot: waypoint=word -->`) marks that screen with a
# word the deck publishes when the talk reaches it (docs/waypoints.md).  Check 49.  The old
# standalone `<!-- waypoint: word -->` line is gone; WAYPOINT_OPEN_RE only recognises it to
# say where the word goes now.
WAYPOINT_WORD_RE = re.compile(r"^[a-z0-9-]{1,24}$")
WAYPOINT_OPEN_RE = re.compile(r"^\s*<!--\s*waypoint\b")
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
LAYOUTS = ("piece", "duo", "titled", "split")
# Known flags (spec: The shot directive Tier B table — per-shot flags; role/layout now config flags).
KNOWN_FLAGS = ("kb", "dim", "fit", "text", "advance", "playback", "sound", "silent",
               "under", "blur", "anchor", "still", "reveal", "live", "do", "waypoint", "bg")
# `bg=#rrggbb` / `#rgb` / `auto`: the ground behind slide media (the letterbox).
# `auto` takes the media's own top-left pixel at build time.
# A CSS named colour (`bg=black`, `bg=navy`) is also accepted, case-insensitively.
CSS_COLOUR_NAMES = frozenset("aliceblue antiquewhite aqua aquamarine azure beige bisque black blanchedalmond blue blueviolet brown burlywood cadetblue chartreuse chocolate coral cornflowerblue cornsilk crimson cyan darkblue darkcyan darkgoldenrod darkgray darkgreen darkgrey darkkhaki darkmagenta darkolivegreen darkorange darkorchid darkred darksalmon darkseagreen darkslateblue darkslategray darkslategrey darkturquoise darkviolet deeppink deepskyblue dimgray dimgrey dodgerblue firebrick floralwhite forestgreen fuchsia gainsboro ghostwhite gold goldenrod gray green greenyellow grey honeydew hotpink indianred indigo ivory khaki lavender lavenderblush lawngreen lemonchiffon lightblue lightcoral lightcyan lightgoldenrodyellow lightgray lightgreen lightgrey lightpink lightsalmon lightseagreen lightskyblue lightslategray lightslategrey lightsteelblue lightyellow lime limegreen linen magenta maroon mediumaquamarine mediumblue mediumorchid mediumpurple mediumseagreen mediumslateblue mediumspringgreen mediumturquoise mediumvioletred midnightblue mintcream mistyrose moccasin navajowhite navy oldlace olive olivedrab orange orangered orchid palegoldenrod palegreen paleturquoise palevioletred papayawhip peachpuff peru pink plum powderblue purple rebeccapurple red rosybrown royalblue saddlebrown salmon sandybrown seagreen seashell sienna silver skyblue slateblue slategray slategrey snow springgreen steelblue tan teal thistle tomato turquoise violet wheat white whitesmoke yellow yellowgreen".split())
BG_RE = re.compile(r"#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})|auto|[A-Za-z]+")


def valid_bg(value) -> bool:
    """A `bg` value (shot flag or card key): a hex colour, a CSS colour name or `auto`."""
    if not isinstance(value, str) or BG_RE.fullmatch(value) is None:
        return False
    return value[0] == "#" or value == "auto" or value.lower() in CSS_COLOUR_NAMES
# `reveal=list` shows a list's items one per next-press (and steps a stepped-
# image card's frames in lockstep); `reveal=off` turns a card's image stepping
# off for that screen (spec: The shot directive, `reveal`).
# `reveal=timer` hides the screen's `[Timer: ...]` countdown until the next
# press, which shows it and starts it (spec: Timer screens, "Revealed timers").
# The parts combine with `+` in any order (`list+timer`, `timer+off`).
# A bare `reveal` (no value) means everything the screen can reveal, now or
# later: it is stored as REVEAL_ALL and expanded by render.reveal_modes.
REVEAL_VALUES = ("list", "quote", "source", "off", "timer", "or a + join of them, e.g. quote+source")
REVEAL_PARTS = ("list", "quote", "source", "off", "timer")
REVEAL_ALL = "all"      # the stored value of a bare `reveal`; not writable as `reveal=all`


def valid_reveal(value: str) -> bool:
    """A `reveal=` value: one or more of list / quote / source / off / timer joined with `+`,
    none repeated."""
    parts = str(value).split("+")
    return all(p in REVEAL_PARTS for p in parts) and len(set(parts)) == len(parts)
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

# `[Timer: 8:00]` in screen text: a countdown that starts when the presenter
# arrives at the screen (spec: Timer screens).  Durations: a bare integer
# (seconds), `90s`, `8m`, `1h`, `1h30m`, `1m30s`, `mm:ss` (`5:00`, `12:30`),
# any case.  An optional trailing word `corner` (any case) puts the plate in the
# lower-right corner instead of the text flow.
TIMER_UNITS_RE = re.compile(r"(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?")
TIMER_CLOCK_RE = re.compile(r"(\d+):([0-5]\d)")
TIMER_MAX_SECONDS = 3 * 3600
# Anything bracketed that starts with `timer` and a colon is meant as a timer;
# whether it parses is decided by parse_timer_token.  `[timer]` / `[timer corner]`
# with no colon is a continuation: the same countdown as the nearest timer above
# it (spec: Timer screens, "Continued timers").  Group 1 is what follows the colon,
# None for a continuation; group 2 is a continuation's `corner`.  Other bracketed
# text is ordinary text.
TIMER_PATTERN = r"\[\s*timer(?:\s*:([^\]]*)|(\s+corner)?\s*)\]"
TIMER_TOKEN_RE = re.compile(TIMER_PATTERN, re.IGNORECASE)


def parse_timer(spec) -> Optional[tuple]:
    """(seconds, phrase) for a valid, non-zero duration, else None.

    `phrase` is the duration as the author wrote it, in words and singular
    (`8 minute`, `90 second`, `1 hour 30 minute`), for the document view.
    Zero (`0`, `0m`, `0:00`) is invalid.
    """
    spec = str(spec).strip().lower()
    parts = None          # [(count, unit)] in the order written
    if re.fullmatch(r"\d+", spec):
        parts = [(int(spec), "second")]
    elif TIMER_CLOCK_RE.fullmatch(spec):
        mm, ss = TIMER_CLOCK_RE.fullmatch(spec).groups()
        parts = [(int(mm), "minute"), (int(ss), "second")]
    else:
        m = TIMER_UNITS_RE.fullmatch(spec)
        if m and spec:
            parts = [(int(v), u) for v, u in zip(m.groups(), ("hour", "minute", "second"))
                     if v is not None]
    if not parts:
        return None
    unit_s = {"hour": 3600, "minute": 60, "second": 1}
    seconds = sum(n * unit_s[u] for n, u in parts)
    if seconds <= 0:
        return None
    phrase = " ".join(f"{n} {u}" for n, u in parts if n > 0)
    return seconds, phrase


def parse_timer_token(inner: str) -> Optional[tuple]:
    """(seconds, phrase, corner) for the inside of a `[Timer: ...]` token (what
    follows the colon), or None when it is not a valid timer."""
    words = inner.split()
    if not words or len(words) > 2:
        return None
    parsed = parse_timer(words[0])
    if parsed is None:
        return None
    if len(words) == 2 and words[1].lower() != "corner":
        return None
    return parsed[0], parsed[1], len(words) == 2


def timer_match(m) -> Optional[tuple]:
    """What a TIMER_TOKEN_RE match is: ("timer", (seconds, phrase, corner)) for a
    valid countdown, ("cont", corner) for a continuation, None for an invalid
    `[Timer: ...]`."""
    if m.group(1) is None:
        return "cont", m.group(2) is not None
    got = parse_timer_token(m.group(1))
    return ("timer", got) if got is not None else None


# `[n]` / `[next]` in a spoken paragraph: where the presenter presses next.  It is
# a cue for the presenter, never speech, so the parser takes it out of the text
# (timing, captions, the document view and the handout never see it) and keeps
# only where it stood, as Block.nexts.
# `[notes]` alone on a line: the lines directly under it (to the next blank
# line) are off the slide, in the presenter notes and the handout.
PRINT_MARK_RE = re.compile(r"^\s*\[\s*notes\s*\]\s*$", re.IGNORECASE)
NEXT_TOKEN_RE = re.compile(r"\[\s*(?:n|next)\s*\]", re.IGNORECASE)


def split_next_tokens(text: str) -> tuple:
    """(clean text, offsets): the text without its `[n]` / `[next]` tokens, and
    the character offset in the clean text where each one stood."""
    pieces = NEXT_TOKEN_RE.split(text)
    clean, offsets = pieces[0], []
    for piece in pieces[1:]:
        clean = clean.rstrip()
        offsets.append(len(clean))
        piece = piece.lstrip()
        if clean and piece and piece[0] not in ".,;:!?)":
            clean += " "
        clean += piece
    clean = clean.rstrip()
    return clean, [min(o, len(clean)) for o in offsets]


# `([Timer: 5m])` alone in a paragraph: a timer only the presenter window shows.
QUIET_TIMER_RE = re.compile(r"\(\s*(" + TIMER_PATTERN + r")\s*\)", re.IGNORECASE)


def strip_timer_tokens(text: str) -> str:
    """The text with every `[Timer: ...]` token removed and the gap closed."""
    out = TIMER_TOKEN_RE.sub(" ", text)
    out = re.sub(r"[ \t]+", " ", out).strip()
    return re.sub(r"\s+([.,;:!?])", r"\1", out)


def link_timer_continuations(talk) -> None:
    """Give each `[timer]` continuation its parent: the nearest screen above it
    with a real countdown, and the parent its span.  It runs once per parsed
    file, before a quick-select shelf is appended, so a shelf section links only
    inside itself.  A continuation with no timer above it warns (check 52) and is
    left as literal text, like any token that is not a timer."""
    parent = None
    for pos, s in enumerate(talk.screens):
        b = s.timer_block
        if b is None:
            continue
        if not b.timer_cont:
            parent = s
            continue
        if parent is None:
            talk.warnings.append(
                f"line {b.line}: check 52: [timer] continues the countdown above it, "
                f"but there is no timer above it; write a duration ([timer:5m]) to "
                f"start one — left as text")
            b.timer, b.timer_cont = None, False
            continue
        secs, phrase, _c = parent.timer
        b.timer = (secs, phrase, b.timer[2])
        b.timer_parent = parent
        start = talk.screens.index(parent) + 1
        parent.timer_span = talk.screens[start:pos + 1]


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
# Section labels: the printed label is `<ordinal>. <title>`, numbered from
# structure.  A leading word-and-number prefix in the heading text is dropped.
_ROMAN = r"(?-i:[IVXLC]+)"   # uppercase only: "Part Mix" keeps its title
SECTION_PREFIX_RE = re.compile(
    r"^(?:(?:movement|part|act|chapter|section)\s+(?:\d+|" + _ROMAN + r")\b"
    r"|\d+(?=\s*[|.:\-\u2013\u00b7]))"
    r"\s*[|.:\-\u2013\u00b7]?\s*", re.IGNORECASE)


def section_title(text: str, index: int) -> str:
    """The heading text without any leading 'Movement|Part|Act|Chapter|Section N'
    (digits or roman numerals) or bare 'N.' prefix.  Empty remainder gives
    'Section <index>'."""
    t = SECTION_PREFIX_RE.sub("", text.strip(), count=1).strip()
    return t or f"Section {index}"


def section_label(index: int, text: str, number: Optional[int] = None) -> str:
    """Display label for a section: '<number>. <title>'.  The opening
    (index 0) has no label.  `number` is the printed ordinal (default: the
    index); 0 means the section is unnumbered and shows its title alone.
    Empty remainder gives 'Section <n>'."""
    if index <= 0:
        return ""
    n = index if number is None else number
    t = SECTION_PREFIX_RE.sub("", text.strip(), count=1).strip()
    if n <= 0:
        return t or f"Section {index}"
    return f"{n}. {t}" if t else f"Section {n}"


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
    # `waypoint=word`: the word the deck publishes when the talk reaches this shot's screen.
    # Kept as written; check 49 validates it with the screen's source in hand.
    waypoint: Optional[str] = None
    # Chain id shared by a media shot and every `continue` screen after it
    # (the head's line number as a string); None when the shot is in no chain.
    chain: Optional[str] = None
    # The include directive's path as authored, when this shot came from an
    # included file (nav.json reports it); None for the talkfile's own shots.
    include: Optional[str] = None
    # Quick select (spec: docs/quick-select.md): (section id, title, keywords)
    # when this shot came from a section that declares a `quick:` block, in a
    # deck that has opted in with `quick_sections`.  None everywhere else.
    quick: Optional[tuple] = None

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

    kind: str                     # print|vo|heading|handout-heading|quote|quote-source|list|table|code|stat|lower|credits|paraphrase
    text: str = ""                # for vo/heading/quote/stat/lower/credits/paraphrase; code: the verbatim lines
    level: Optional[int] = None   # heading depth (1..6)
    items: list = field(default_factory=list)   # list items
    ordered: bool = False         # numbered list (`1.` items)
    depths: list = field(default_factory=list)  # list: nesting depth per item (0 = top); empty when flat
    rows: list = field(default_factory=list)    # table: list of rows of cell strings
    header: bool = False          # table: rows[0] is the header row
    stage: list = field(default_factory=list)   # extracted parentheticals
    spoken: bool = False          # role payload is spoken VO (from roles.yaml)
    spoken_items: list = field(default_factory=list)   # a spoken list: the
                                   # items as they are read (parentheticals out)
    line: int = 0                 # first source line of the block
    line_end: int = 0             # last source line: merged soft-wrap or a
                                  # multi-line quote / list occupies every line
                                  # in between, so the screen's range must too
    refs: list = field(default_factory=list)    # handout only: (source id, the text just before the `[^id]`)
    # The screen's one live timer lives in this block: (seconds, phrase, corner).
    # kind "timer" is a token alone on its line; in a heading, list item, quote
    # or stat/paraphrase payload the token sits inside the text.
    timer: Optional[tuple] = None
    # kind "timer" only: written `([Timer: ...])`.  A presenter-only timer: it
    # runs in the presenter window and counts toward the timing estimate, and
    # the audience's slide draws nothing.
    timer_quiet: bool = False
    # A continuation (`[timer]`): `timer` carries the parent's seconds and phrase
    # with this token's own `corner`, and `timer_parent` is the parent Screen
    # (an object, so it survives renumbering).  Set after parsing; None on a real
    # timer.
    timer_cont: bool = False
    timer_parent: Optional["Screen"] = None
    # vo only: offsets in `text` where the author wrote `[n]` / `[next]`, the
    # point the presenter presses next.  Speaker notes show them; nothing else does.
    nexts: list = field(default_factory=list)
    # kind "print" only: the blocks written under a `[notes]` line.  Handout
    # only: never on a slide, never spoken, never in cues.
    inner: list = field(default_factory=list)


@dataclass
class Screen:
    idx: int                      # 1-based, document order
    movement: int                 # 0 = opening/title zone, else 1..N
    shots: list = field(default_factory=list)
    blocks: list = field(default_factory=list)   # list[Block]
    line: int = 0
    # Quick select: True for a screen on the shelf (a section the deck carries
    # but the talk never reaches in normal paging).  Always after the talk.
    shelf: bool = False
    # Waypoints (docs/waypoints.md): the word the deck publishes on reaching
    # this screen, and the directive's source line.  Never on a shelf screen.
    waypoint: Optional[str] = None
    waypoint_line: int = 0
    # A screen whose countdown is continued below (`[timer]`): the screens after
    # it, up to and including its last continuation.  Their time is spent inside
    # the countdown (spec: Timer screens, "Continued timers").  Empty otherwise.
    timer_span: list = field(default_factory=list, repr=False)

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
    def section(self) -> Optional[tuple]:
        """(section id, title, keywords) of the quick-select section this
        screen came from (the shelf, or an include that declares `quick:`)."""
        return self.shots[0].quick if self.shots else None

    @property
    def live_only(self) -> bool:
        """True when any shot carries the bare `live` flag: the screen belongs
        to the live deck only (present + presenter views).  The document view
        / handout leaves it out and cues.json marks it, so a video render
        skips it.  A shelf screen (quick select) is live-only by definition."""
        return self.shelf or any(f in s.flags for s in self.shots
                                 for f in ("live", "do"))

    @property
    def room_only(self) -> bool:
        """True for a room screen: `live` (or a shelf screen).  Presented,
        never in the reading copy, never in the agent export."""
        return self.shelf or any("live" in s.flags for s in self.shots)

    @property
    def exercise(self) -> bool:
        """True for an exercise screen: the bare `do` flag without `live`.
        Presented, never in the reading copy, an Exercise step in the agent
        export (spec: Screen kinds)."""
        return not self.room_only and any("do" in s.flags for s in self.shots)

    @property
    def use(self) -> str:
        """`content` | `exercise` | `room`: who the screen is for."""
        return "room" if self.room_only else "exercise" if self.exercise else "content"

    @property
    def do_notes(self) -> list:
        """The `(Do: ...)` stage notes on this screen, prefix stripped: the
        hands-on instruction for the agent export, spoken nowhere."""
        out = []
        for b in self.blocks:
            for st in b.stage:
                m = DO_NOTE_RE.match(st)
                if m and m.group(1).strip():
                    out.append(m.group(1).strip())
        return out

    @property
    def timer_block(self) -> Optional["Block"]:
        """The block that hosts the screen's `[Timer: ...]` token, if any."""
        return next((b for b in self.blocks if b.timer is not None), None)

    @property
    def timer(self) -> Optional[tuple]:
        """(seconds, phrase, corner) of the screen's timer, or None.  A
        `continue` screen starts clean: text never carries, so a timer does not."""
        b = self.timer_block
        return b.timer if b is not None else None

    @property
    def timer_parent(self) -> Optional["Screen"]:
        """The screen whose countdown this screen continues, or None."""
        b = self.timer_block
        return b.timer_parent if b is not None and b.timer_cont else None

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
    # the printed ordinal: sections made only of room screens (a Break) get 0
    # and no number, so the numbers run without gaps; None until build_talk
    # sets it (then the index stands in)
    number: Optional[int] = None

    @property
    def display(self) -> str:
        """The label shown to readers: '<number>. <title>' (see section_label)."""
        return section_label(self.index, self.label, self.number)


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
    # Quick select: files pulled onto the shelf (resolved, nested ones too),
    # for --watch; the `[^id]` refs the shelf's own screens carry; and each
    # shelf section's own `cites:` / `sources:` (section id -> {key: map}).
    # None of these touch `meta` or `footnote_ids`: the handout is public and
    # prints exactly what the talk cites.
    shelf_files: list = field(default_factory=list)
    shelf_footnote_ids: list = field(default_factory=list)
    shelf_registry: dict = field(default_factory=dict)
    # Ids an included file declares in its own `cites:`, in include order.
    # They print in the Sources list even when no `[^id]` reference points at
    # them: the section carries its citation, the prose need not.
    section_cite_ids: list = field(default_factory=list)

    @property
    def main_screens(self) -> list:
        return [s for s in self.screens if not s.shelf]

    @property
    def shelf_screens(self) -> list:
        return [s for s in self.screens if s.shelf]

    def shelf_cite(self, screen: "Screen", rid: str, key: str = "cites"):
        """Resolve a `[^id]` on a shelf screen: its own section's registry
        first, then the talk's.  None when neither has it."""
        sec = screen.section
        reg = self.shelf_registry.get(sec[0], {}) if sec else {}
        for m in (reg.get(key), self.meta.get(key)):
            if isinstance(m, dict) and rid in m:
                return m[rid]
        return None

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
    text, unmask = _mask_link_targets(text)   # a link's `(url)` is not a stage note
    spoken_parts: list[str] = []
    stage: list[str] = []
    for m in PAREN_SPLIT_RE.finditer(text):
        if m.group(1) is not None:
            stage.append(m.group(1).strip())
        else:
            spoken_parts.append(m.group(2))
    spoken = re.sub(r"\s+", " ", " ".join(spoken_parts)).strip()
    spoken = re.sub(r"\s+([.,;:!?])", r"\1", spoken)   # 'Residence (..).' -> 'Residence.'
    return unmask(spoken), [unmask(s) for s in stage if s]


_LINK_TARGET_RE = re.compile(r"\]\(((?:https?://|mailto:)[^)\s]+)\)")


def _mask_link_targets(text: str):
    """Hide each `[text](url)` target from the paren rules; return the masked
    text and a function that puts the targets back."""
    found: list[str] = []

    def keep(m):
        found.append(m.group(0))
        return f"\ue000{len(found) - 1}\ue001"
    masked = _LINK_TARGET_RE.sub(keep, text)
    if not found:
        return text, lambda t: t
    return masked, lambda t: re.sub(r"\ue000(\d+)\ue001", lambda m: found[int(m.group(1))], t)


def nested_paren_at(text: str) -> Optional[int]:
    """Index of the first `(` that opens inside an already-open parenthetical,
    or None.  Register check 23 (spec: Text): parentheticals do not nest —
    split_parens recognizes one level, so nesting silently corrupts the
    spoken text unless it warns.
    """
    text = _mask_link_targets(text)[0]   # indexes shift; only used to warn
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


def unclosed_paren_at(text: str) -> Optional[int]:
    """Index of the `(` that opens a parenthetical and never closes, or None.
    Register check 46 (spec: Text): an unclosed `(` makes the rest of the
    paragraph, often a whole stage note, read as spoken text and print in the
    handout.
    """
    text = _mask_link_targets(text)[0]   # indexes shift; only used to warn
    opener = None
    for i, ch in enumerate(text):
        if ch == "(" and opener is None:
            opener = i
        elif ch == ")" and opener is not None:
            opener = None
    return opener


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


# `[text](url)`: a link.  Only http(s) and mailto: targets, so `[^id]`,
# `[timer:..]`, `[notes]` and `[n]` never match.  The slide shows the text as
# plain words; the document view, handout and web export make it a link.
_LINK = r"\[[^\]\n^][^\]\n]*\]\((?:https?://|mailto:)[^)\s]+\)"
_INLINE_TOK = re.compile(r"(" + _LINK + r"|\*\*.+?\*\*|`[^`]+`|\*[^*\s][^*]*\*)")
_LINK_RE = re.compile(r"\[([^\]\n^][^\]\n]*)\]\(((?:https?://|mailto:)[^)\s]+)\)")


def html_escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def inline_md(text: str) -> str:
    """Escape + minimal inline markdown (bold / code / italic / link) -> HTML.
    A link is `<a class="md-link">`: the present view styles it as plain text."""
    return _inline_html(html_escape(text))


def link_md(text: str) -> str:
    """Escape, and make `[text](url)` links only: for caption-like lines that
    take no other markup (a lower third, a credits line, a figure caption)."""
    return _LINK_RE.sub(lambda m: '<a class="md-link" href="%s">%s</a>' % (m.group(2), m.group(1)),
                        html_escape(text))


def _inline_html(esc: str) -> str:
    parts = []
    pos = 0
    for m in _INLINE_TOK.finditer(esc):
        parts.append(esc[pos:m.start()])
        tok = m.group(0)
        lm = _LINK_RE.fullmatch(tok) if tok.startswith("[") else None
        if lm:
            parts.append('<a class="md-link" href="%s">%s</a>' % (lm.group(2), _inline_html(lm.group(1))))
        elif tok.startswith("**") and tok.endswith("**"):
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
    s = _LINK_RE.sub(r"\1", text)
    s = re.sub(r"\*\*(.+?)\*\*", r"\1", s)
    s = re.sub(r"`([^`]+)`", r"\1", s)
    s = re.sub(r"(?<!\w)\*([^*\s][^*]*)\*(?!\w)", r"\1", s)
    return re.sub(r"\s+", " ", s).strip()


def spoken_list_items(items: list) -> list:
    """A list's items as the sentences the speaker reads (spec: Text — Spoken
    lists).

    Each item is one utterance, kept as written: markdown markers stripped (as
    everywhere in the script), the words and their punctuation untouched.  The
    items come back as a list so the script can give each one its own
    paragraph — one caption per bullet.
    """
    out = []
    for item in items:
        t = plain_md(item).strip()
        if t:
            out.append(t)
    return out


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


# Fenced code blocks (spec: Text, "Fenced code"): a line of 3+ backticks or
# tildes opens a block that shows its lines verbatim; it closes on a line of
# the same character, at least as long, with nothing after it.  Up to three
# spaces of indent are allowed on the fence lines.  An info string after the
# opening fence is allowed and ignored (a backtick fence's cannot hold a
# backtick, so inline "```code```" is not a fence).
FENCE_OPEN_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
FENCE_SHOT_RE = re.compile(r"^\s*<!--\s*shot\b")
FENCE_MOVEMENT_RE = re.compile(r"^##\s")


def find_fences(lines: list) -> dict:
    """Locate every fenced block in `lines` (as lexed: frontmatter already
    removed, newlines optional).  Returns {open_index: info} with
    `end` (index of the last line the fence owns), `body` (index range
    start, stop of its content lines), `closed`.

    A fence that never closes ends just before the next `<!-- shot` line or
    movement heading, else at the end of the file; trailing blank lines are
    not content.  Lines inside a multi-line comment are never fences.
    """
    out: dict = {}
    n = len(lines)
    i = 0
    in_comment = False
    while i < n:
        line = lines[i].rstrip("\n")
        if in_comment:
            if "-->" in line:
                in_comment = False
            i += 1
            continue
        if line.lstrip().startswith("<!--"):
            if "-->" not in line:
                in_comment = True
            i += 1
            continue
        m = FENCE_OPEN_RE.match(line)
        if not m or (m.group(1)[0] == "`" and "`" in m.group(2)):
            i += 1
            continue
        ch, size = m.group(1)[0], len(m.group(1))
        close_re = re.compile(r"^ {0,3}" + re.escape(ch) + "{" + str(size) + r",}[ \t]*$")
        close = next((j for j in range(i + 1, n)
                      if close_re.match(lines[j].rstrip("\n"))), None)
        if close is not None:
            out[i] = {"end": close, "body": (i + 1, close), "closed": True}
        else:
            stop = n
            for j in range(i + 1, n):
                t = lines[j].rstrip("\n")
                if FENCE_SHOT_RE.match(t) or FENCE_MOVEMENT_RE.match(t):
                    stop = j
                    break
            while stop > i + 1 and not lines[stop - 1].strip():
                stop -= 1
            out[i] = {"end": stop - 1, "body": (i + 1, stop), "closed": False}
        i = out[i]["end"] + 1
    return out


def fenced_line_indexes(lines: list) -> set:
    """0-based indexes of every line a fenced block owns (fence lines too)."""
    out: set = set()
    for i, f in find_fences(lines).items():
        out.update(range(i, f["end"] + 1))
    return out


# A non-shot comment that trails prose on its own line (`text. <!-- note -->`,
# possibly running over several lines).  Comments that start a line are handled
# by the lexer; these would otherwise be read as spoken text (spec principle 4:
# non-directive comments are inert).
_TRAILING_COMMENT_RE = re.compile(r"(?<=\S)[ \t]*<!--(?!\s*shot\b).*?-->", re.S)


def _strip_trailing_comments(lines: list, fenced=frozenset()) -> list:
    """Drop trailing comments, keeping every newline so later lines keep
    their numbers.  Lines in `fenced` (a fenced block) are left untouched:
    nothing inside a fence is parsed."""
    text = "".join(("\n" if k in fenced else (l if l.endswith("\n") else l + "\n"))
                   for k, l in enumerate(lines))
    if "<!--" not in text:
        return lines
    text = _TRAILING_COMMENT_RE.sub(lambda m: "\n" * m.group(0).count("\n"), text)
    out = text.splitlines(keepends=True)
    if len(out) != len(lines):
        return out
    return [lines[k] if k in fenced else out[k] for k in range(len(out))]


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
    fences = find_fences(lines)
    fenced = set()
    for fi, f in fences.items():
        fenced.update(range(fi, f["end"] + 1))
    raw_lines = list(lines)
    lines = _strip_trailing_comments(lines, fenced)
    skip_to = -1
    blocks: list[dict] = []
    para_buf: list[str] = []
    para_line = 0
    para_end = 0
    cont = None  # (kind, block, last_lineno) for quote/list line merging
    comment_buf: Optional[list] = None
    comment_start = 0
    print_ranges: list = []   # (first, last) source lines under a `[notes]` line

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
    for idx, raw in enumerate(lines):
        lineno = idx + 1 + line_offset
        if idx <= skip_to:
            continue
        line = raw.rstrip("\n")

        # --- fenced block: verbatim, nothing inside is parsed ---------------
        if idx in fences and comment_buf is None:
            f = fences[idx]
            flush_para()
            b0, b1 = f["body"]
            text = "\n".join(raw_lines[k].rstrip("\n") for k in range(b0, b1))
            blocks.append({"kind": "code", "text": text, "closed": f["closed"],
                           "line": lineno,
                           "line_end": f["end"] + 1 + line_offset})
            skip_to = f["end"]
            continue

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
                if WAYPOINT_OPEN_RE.match(line):
                    raise _waypoint_error(source, lineno, _WAYPOINT_MOVED)
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
            elif WAYPOINT_OPEN_RE.match(line):
                raise _waypoint_error(source, lineno, _WAYPOINT_MOVED)
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

        # --- [notes]: the lines under it, to the next blank line, are handout-only
        if PRINT_MARK_RE.match(line):
            flush_para()
            end = idx
            while end + 1 < len(lines) and lines[end + 1].strip() \
                    and not lines[end + 1].lstrip().startswith("<!--"):
                if (end + 1) in fences:      # a fence is part of the run
                    end = fences[end + 1]["end"]
                elif (end + 1) in fenced:
                    break
                else:
                    end += 1
            print_ranges.append((lineno + 1, end + 1 + line_offset))
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
                if piece.startswith("~") and not piece.startswith("~~") and piece[1:].strip():
                    # `> ~ Source` ends the quote and is its attribution, the
                    # same as a `~ Source` line right under it
                    blocks.append({"kind": "para", "text": "~ " + piece[1:].strip(),
                                   "line": lineno, "line_end": lineno})
                    cont = None
                    continue
                if not piece:
                    cont[1]["para_break"] = True
                elif cont[1].pop("para_break", False) and cont[1]["text"]:
                    cont[1]["text"] += "\n\n" + piece
                else:
                    cont[1]["text"] += "\n" + piece   # a line break is kept
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

        # --- multi-line direction ----------------------------------------------
        # A line that opens a `(` it does not close starts a stage note that
        # runs to the line where the parens balance, over any lines between
        # (list items included).  One block: the note, never screen text.
        if line.lstrip().startswith("(") and not (cont and cont[0] in ("list", "olist", "quote", "table")):
            end = _direction_end(lines, idx, fenced)
            # directly under a prose line it only takes over when it holds list
            # items; plain prose parentheticals merge into the paragraph as before
            if end is not None and end > idx and (not para_buf or any(
                    LIST_ITEM_RE.match(lines[k].strip()) or ORDERED_ITEM_RE.match(lines[k].strip())
                    for k in range(idx, end + 1))):
                flush_para()
                pieces = []
                for k in range(idx, end + 1):
                    s = lines[k].strip()
                    s = LIST_ITEM_RE.match(s).group(1).strip() if LIST_ITEM_RE.match(s) \
                        else ORDERED_ITEM_RE.match(s).group(1).strip() if ORDERED_ITEM_RE.match(s) else s
                    pieces.append(s)
                text = pieces[0]
                for s in pieces[1:]:
                    sep = "" if text == "(" or s.startswith(")") else ("; " if not text.endswith((".", ":", ";", "?", "!")) else " ")
                    text += sep + s
                blocks.append({"kind": "para", "text": text, "line": lineno,
                               "line_end": end + 1 + line_offset})
                cont = None
                skip_to = end
                continue

        # --- next mark alone on a line: a paragraph break of its own ----------
        if NEXT_TOKEN_RE.fullmatch(line.strip()):
            flush_para()
            blocks.append({"kind": "para", "text": line.strip(),
                           "line": lineno, "line_end": lineno})
            continue

        # --- prose ------------------------------------------------------------
        cont = None
        if not para_buf:
            para_line = lineno
        para_buf.append(line.strip())
        para_end = lineno

    flush_para()
    for b in blocks:
        if any(a <= b.get("line", 0) <= z for a, z in print_ranges):
            b["print"] = True
    return blocks


def _direction_end(lines: list, start: int, fenced: set) -> Optional[int]:
    """Index of the line where a `(` opened on `lines[start]` closes, scanning
    non-blank lines only; None if the parens never balance before a blank
    line, a shot or include comment, a heading or a fence."""
    depth = 0
    for k in range(start, len(lines)):
        line = lines[k].rstrip("\n")
        if k > start and (not line.strip() or k in fenced or HEADING_RE.match(line)
                          or line.lstrip().startswith("<!--")):
            return None
        for ch in line:
            if ch == "(":
                depth += 1
            elif ch == ")" and depth:
                depth -= 1
                if depth == 0:
                    return k
    return None


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
    territory, not the tokenizer's.
    """
    if name not in KNOWN_FLAGS:
        shot.warnings.append(
            f"check 25: unknown flag {token!r}; known flags: "
            f"{', '.join(KNOWN_FLAGS)} — token ignored"
        )
        return
    if name == "waypoint":
        shot.waypoint = value
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
    if name == "bg" and not valid_bg(value):
        shot.warnings.append(
            f"check 25: {token!r}: bg is the ground behind the media, "
            f"bg=#rrggbb (or #rgb), a colour name like bg=black, or bg=auto — token ignored"
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
    if name == "reveal" and not value:
        shot.flags[name] = REVEAL_ALL
        return
    if name == "reveal" and not valid_reveal(value):
        shot.warnings.append(
            f"check 25: {token!r}: reveal says what appears one by one, "
            f"reveal={', reveal='.join(REVEAL_VALUES[:-1])}, {REVEAL_VALUES[-1]} — token ignored"
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
    own = {f for f in ("live", "do") if f in shot.flags}
    shot.flags = {**prev.flags, **shot.flags}
    for f in ("live", "do"):
        if f not in own:
            shot.flags.pop(f, None)     # live-only / exercise belongs to one screen


def _run_start(raw_blocks: list, i: int) -> int:
    """Index of the first block of the heading run that contains heading `i`.
    A `## Movement N` heading is structure and ends the walk."""
    j = i
    while j - 1 >= 0 and raw_blocks[j - 1]["kind"] == "heading" and not (
            raw_blocks[j - 1]["level"] == 2 and MOVEMENT_RE.match(raw_blocks[j - 1]["text"])):
        j -= 1
    return j


def _heading_run_opens_at_shot(raw_blocks: list, i: int, or_start: bool = False) -> bool:
    """True when heading `i` belongs to a run of headings that starts right
    after a shot (with `or_start`, or at the very start of the file): a title card
    (`# Title`, `## Date`, `### Website`) keeps every heading on its slide, not
    only the first.  Section headings and movement headings are structure and
    end the run."""
    s = _run_start(raw_blocks, i)
    return (or_start and s == 0) or (s > 0 and raw_blocks[s - 1]["kind"] == "shot")


def _is_section_heading(raw_blocks: list, i: int) -> bool:
    """A `##` heading is a section break (part / act / chapter) unless it sits
    in a title-card run.  `## Movement N · Title` always is one."""
    rb = raw_blocks[i]
    if rb["kind"] != "heading" or rb["level"] != 2:
        return False
    if MOVEMENT_RE.match(rb["text"]):
        return True
    return not _heading_run_opens_at_shot(raw_blocks, i, or_start=True)


def _include_error(source: str, line: int, msg: str) -> ValueError:
    # same shape as check 22 so check.py reports it as a fatal with its line
    return ValueError(f"{source}:{line}: check 22: {msg}")


def _meta_line(path, key: str) -> int:
    """The line a frontmatter key is written on, for an error message (1 if absent)."""
    try:
        for n, ln in enumerate(Path(path).read_text(encoding="utf-8").split("\n"), 1):
            if ln.startswith(key + ":"):
                return n
    except OSError:
        pass
    return 1


def _is_include_name(rel: str) -> bool:
    """True for `<!-- include: ai-terms -->`: no directory and no extension.
    Anything with a `/` or a `.` is a path, resolved as it always was."""
    return "/" not in rel and "\\" not in rel and "." not in rel


def _include_sections(meta: dict, path, source: str) -> Path:
    """The directory a bare include name resolves in.

    `include_sections:` in the frontmatter (relative to the talkfile), else
    `../_sections` beside the deck directory: the folder every deck's
    `quick_sections:` line already names.  A value that is not a relative
    directory path is fatal (check 22), but a directory that is merely absent
    is only an error when a bare name needs it, so a talk with no sections
    folder parses exactly as it always did.
    """
    if "include_sections" not in meta:
        return (Path(path).resolve().parent / INCLUDE_SECTIONS_DEFAULT).resolve()
    raw = meta["include_sections"]
    line = _meta_line(path, "include_sections")
    if not isinstance(raw, str) or not raw.strip():
        raise _include_error(source, line, "`include_sections:` must be a "
                             "directory path relative to the talkfile")
    val = raw.strip()
    if Path(val).is_absolute():
        raise _include_error(source, line, f"`include_sections: {val}` must be "
                             "relative to the talkfile")
    return (Path(path).resolve().parent / val).resolve()


_WAYPOINT_MOVED = ("the standalone waypoint line is gone: put the word in the screen's shot, "
                    "<!-- shot: waypoint=word -->")


def _waypoint_error(source: str, line: int, msg: str) -> ValueError:
    # register check 49, same shape as check 22 so check.py reports a fatal
    return ValueError(f"{source}:{line}: check 49: {msg}")


def _attach_waypoints(raw_blocks: list, source: str) -> list:
    """Tag each shot that carries `waypoint=word` (`rb["wp"] = (word, line)`), so the
    assembler hands the word to the screen that shot opens.  A word that is not
    lowercase letters, digits and hyphens (up to 24) is check 49."""
    for rb in raw_blocks:
        if rb["kind"] != "shot":
            continue
        word = rb["shot"].waypoint
        if word is None:
            continue
        if not WAYPOINT_WORD_RE.match(word):
            raise _waypoint_error(
                source, rb.get("line", 0),
                f"bad waypoint {word!r}: write <!-- shot: waypoint=word --> with a word "
                f"of lowercase letters, digits and hyphens, up to 24 characters")
        rb["wp"] = (word, rb.get("line", 0))
    return raw_blocks


def _quick_error(source: str, line: int, msg: str) -> ValueError:
    # register check 48, same shape as check 22 so check.py reports a fatal
    return ValueError(f"{source}:{line}: check 48: {msg}")


def _quick_block(raw, source: str, line: int) -> tuple:
    """Validate a section's `quick:` block: (title, keywords).  Check 48."""
    if not isinstance(raw, dict):
        raise _quick_error(source, line, "`quick:` must be a block with a "
                           "`title:` (and optionally `keywords:`)")
    title = raw.get("title")
    if not isinstance(title, str) or not title.strip():
        raise _quick_error(source, line, "`quick:` needs a non-empty `title:`")
    kws = raw.get("keywords", [])
    if kws is None:
        kws = []
    if not isinstance(kws, list):
        raise _quick_error(source, line, "`quick: keywords:` must be a list, "
                           "e.g. [agents, tools]")
    return title.strip(), tuple(str(k).strip() for k in kws if str(k).strip())


def _expand_includes(raw_blocks: list, host: "Path", source: str, role_vocab,
                     layout_vocab, stack: tuple, includes: list,
                     frag_meta: list, quick_on: bool = False,
                     sections_dir: Optional["Path"] = None) -> list:
    """Replace each `include` block with the included file's blocks.

    Each file is lexed on its own, so line numbers, paragraph state and
    comments never cross files.  Every block from an included file is pinned
    to the include directive's line in the file that wrote it, so warnings
    and nav.json ranges point somewhere the author can find.  Flags written
    on the directive (`live`) are applied to every shot inside.

    A bare name (`<!-- include: ai-terms -->`) resolves in `sections_dir`, the
    talk's section directory, wherever the directive is written: one folder,
    one setting, however deep the nesting goes.  A path (`sections/x.section.md`)
    stays relative to the file that wrote it, as it always was.
    """
    if sections_dir is None:
        sections_dir = (host.parent / INCLUDE_SECTIONS_DEFAULT).resolve()
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
        if _is_include_name(rel):
            target = (sections_dir / (rel + INCLUDE_SECTION_EXT)).resolve()
            if not target.is_file():
                raise _include_error(source, line, f"include {rel!r} not found: "
                                     f"no {rel}{INCLUDE_SECTION_EXT} in "
                                     f"{sections_dir} (a bare name is a section; "
                                     f"`include_sections:` names another directory)")
        else:
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
        for fb in fblocks:
            if fb["kind"] == "shot" and fb["shot"].waypoint is not None:
                raise _waypoint_error(fsource, fb["line"], "waypoint= cannot sit in a "
                                      "section's shot: it would fire in every talk "
                                      "that includes it; put it in the talkfile")
        fblocks = _expand_includes(fblocks, target, fsource, role_vocab,
                                   layout_vocab, stack + (target,), includes,
                                   frag_meta, quick_on, sections_dir)
        qtuple = None
        if quick_on and "quick" in meta:
            qtitle, qkw = _quick_block(meta["quick"], fsource, line)
            qtuple = (rel, qtitle, qkw)
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
                if qtuple is not None:
                    sh.quick = qtuple     # so does the outermost `quick:`
                for f in rb["flags"]:
                    sh.flags[f] = ""
            out.append(fb)
    return out


def _check_waypoints(talk: "Talk", source: str) -> None:
    """Check 49 once the screens exist: a talk that marks anything has a
    frontmatter `waypoints: {url: http(s)://...}`, and a `waypoints:` that is
    there is well formed.  (Duplicates are caught in assemble, where each
    directive meets its screen.)"""
    marked = [s_ for s_ in talk.screens if s_.waypoint]
    wp = talk.meta.get("waypoints")
    line = marked[0].waypoint_line if marked else 1
    if wp is None:
        if marked:
            raise _waypoint_error(source, line, "the talk marks waypoints but its "
                                  "frontmatter has no `waypoints: {url: ...}`")
        return
    url = wp.get("url") if isinstance(wp, dict) else None
    if not (isinstance(url, str) and re.match(r"^https?://\S+$", url.strip())):
        raise _waypoint_error(source, line, "`waypoints:` needs a `url:` that "
                              "starts with http:// or https://")


def _quick_dir(meta: dict, path, source: str, override) -> tuple:
    """The shelf directory and the line that names it: (Path or None, line).
    `override` (build.py --quick-sections) beats the frontmatter line and is
    relative to the working directory; the frontmatter value is relative to
    the talkfile.  A missing directory or a non-string value is check 48."""
    line = 1
    try:
        for n, ln in enumerate(Path(path).read_text(encoding="utf-8").split("\n"), 1):
            if ln.startswith("quick_sections:"):
                line = n
                break
    except OSError:
        pass
    if override is not None:
        d = Path(override).expanduser().resolve()
        where = f"--quick-sections {override}"
    elif "quick_sections" in meta:
        raw = meta["quick_sections"]
        if not isinstance(raw, str) or not raw.strip():
            raise _quick_error(source, line, "`quick_sections:` must be a "
                               "directory path relative to the talkfile")
        d = (Path(path).resolve().parent / raw.strip()).resolve()
        where = f"quick_sections: {raw.strip()}"
    else:
        return None, line
    if not d.is_dir():
        raise _quick_error(source, line, f"{where}: no such directory")
    return d, line


def _append_shelf(talk: Talk, path, qdir: Path, qline: int, role_vocab,
                  layout_vocab, role_bundles, source: str,
                  sections_dir: Optional[Path] = None) -> None:
    """Lex every shelf section like an include and append its screens after
    the talk's last real screen (spec: docs/quick-select.md).

    A section is shelved when its frontmatter has a `quick:` block and the
    talk does not already include it; order is by filename.  Each section is
    assembled on its own, so a role payload or `continue` never crosses from
    one into the next.  Its `cites:` / `sources:` go in `talk.shelf_registry`
    for its own screens and never join `talk.meta`: the handout is public.
    """
    host = Path(path).resolve()
    taken = set(talk.includes)
    tail = talk.screens[-1] if talk.screens else None
    movement = tail.movement if tail is not None else 0
    for f in sorted(qdir.glob("*.section.md"), key=lambda q: q.name):
        target = f.resolve()
        if target in taken:
            continue          # the talk includes it: search finds that copy
        body = target.read_text(encoding="utf-8")
        meta, _ = _lex_frontmatter(body, str(target))
        if "quick" not in meta:
            continue
        rel = os.path.relpath(target, host.parent)
        inner: list = []
        frag: list = []
        blocks = _expand_includes(
            [{"kind": "include", "path": rel, "flags": [], "line": qline}],
            host, source, role_vocab, layout_vocab, (host,), inner, frag,
            quick_on=True, sections_dir=sections_dir)
        sub = assemble({}, blocks, source, role_vocab=role_vocab,
                       layout_vocab=layout_vocab, role_bundles=role_bundles)
        if not sub.screens:
            continue
        reg = {}
        for key in ("cites", "sources"):
            merged: dict = {}
            for fm in frag:                      # inner first: the section wins
                if isinstance(fm.get(key), dict):
                    merged.update(fm[key])
            if merged:
                reg[key] = merged
        talk.shelf_registry[rel] = reg
        for rid in sub.footnote_ids:
            if rid not in (reg.get("sources") or {}) \
                    and rid not in (talk.meta.get("sources") or {}):
                talk.warnings.append(
                    f"line {qline}: check 28: footnote [^{rid}] in shelf "
                    f"section {rel} has no sources: registry entry")
        talk.shelf_footnote_ids.extend(sub.footnote_ids)
        talk.warnings.extend(sub.warnings)
        for p_ in [target] + inner:
            if p_ not in talk.shelf_files:
                talk.shelf_files.append(p_)
        for scr in sub.screens:
            scr.shelf = True
            scr.movement = movement
            scr.idx = len(talk.screens) + 1
            talk.screens.append(scr)
    talk.warnings.sort()


def number_sections(talk: Talk) -> None:
    """Give each section its printed ordinal.  A section whose screens are all
    room screens (`live`, or the shelf) is unnumbered: it never prints, and in
    the room a Break needs no number.  The rest count 1, 2, 3 in order, so the
    contents of a reading copy and the presenter's "Section N" agree and have
    no gaps.  An exercise (`do`) screen counts: the home page prints it."""
    n = 0
    for m in sorted(talk.movements, key=lambda m: m.index):
        if m.index <= 0:
            continue
        mine = [s for s in talk.screens if s.movement == m.index]
        if mine and all(s.room_only for s in mine):
            m.number = 0
        else:
            n += 1
            m.number = n


def build_talk(path, source: Optional[str] = None,
               quick_sections: Optional[str] = None) -> Talk:
    """Parse a talkfile path into a Talk model.

    The deck directory is the directory that HOLDS the talkfile: that is
    where a deck-local `roles.yaml` / `layouts.yaml` lives (deck -> shared ->
    built-in, spec: Roles), so the vocabulary the parser accepts and the one
    the checker reports against are resolved once, here.

    `quick_sections` (build.py `--quick-sections DIR`) overrides the
    frontmatter `quick_sections:` line; a deck with neither parses exactly as
    it always did.
    """
    source = source or str(path)
    with open(path, "r", encoding="utf-8") as fh:
        body = fh.read()
    deck_dir = Path(path).resolve().parent
    role_vocab, layout_vocab = load_vocab(deck_dir)
    role_bundles = load_role_bundles(deck_dir)
    meta, lines = _lex_frontmatter(body, source)
    qdir, qline = _quick_dir(meta, path, source, quick_sections)
    sdir = _include_sections(meta, path, source)
    # every line number is the talkfile's own, frontmatter included
    # (file-relative, not body-relative)
    offset = body.count("\n") + 1 - len(lines)
    raw_blocks = _lex_blocks(lines, source, role_vocab, layout_vocab,
                             line_offset=offset)
    includes: list = []
    frag_meta: list = []
    raw_blocks = _expand_includes(raw_blocks, Path(path).resolve(), source,
                                  role_vocab, layout_vocab,
                                  (Path(path).resolve(),), includes, frag_meta,
                                  quick_on=qdir is not None, sections_dir=sdir)
    # an included file's `cites:` / `sources:` join the talk's; the talk wins
    section_cite_ids: list = []
    for fm in frag_meta:
        if isinstance(fm.get("cites"), dict):
            section_cite_ids.extend(k for k in fm["cites"] if k not in section_cite_ids)
        for key in ("cites", "sources"):
            if isinstance(fm.get(key), dict):
                merged = dict(fm[key])
                merged.update(meta.get(key) if isinstance(meta.get(key), dict) else {})
                meta[key] = merged
    raw_blocks = _attach_waypoints(raw_blocks, source)
    talk = assemble(meta, raw_blocks, source, role_vocab=role_vocab,
                    layout_vocab=layout_vocab, role_bundles=role_bundles)
    talk.includes = includes
    talk.section_cite_ids = section_cite_ids
    _check_waypoints(talk, source)
    if qdir is not None:
        _append_shelf(talk, path, qdir, qline, role_vocab, layout_vocab,
                      role_bundles, source, sdir)
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
    # Spoken voice-over seen so far ON THE OPEN SCREEN.  A list that follows
    # it is spoken as well as shown (spec: Text — Spoken lists): the author
    # says the list out loud, so it lands in the script once and the copy in
    # the speaker notes can go.
    spoken_seen = False

    wp_pending = None             # (word, line) waiting for its screen
    wp_seen: dict = {}            # word -> line of the directive that used it

    def new_screen(line: int) -> Screen:
        nonlocal cur, spoken_seen, wp_pending
        cur = Screen(idx=len(screens) + 1, movement=movement_index, line=line)
        screens.append(cur)
        if wp_pending is not None:
            cur.waypoint, cur.waypoint_line = wp_pending
            wp_pending = None
        spoken_seen = False      # a new screen starts the count over
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

    def scan_timer(block: Block, text: str, line: int) -> None:
        """Look for a `[Timer: ...]` token in screen text.  The first valid
        token on a screen becomes its live timer (`block.timer`); an invalid
        one, or a second, warns and stays as literal text so the mistake shows."""
        for m in TIMER_TOKEN_RE.finditer(text):
            tok = m.group(0)
            kind_got = timer_match(m)
            got = kind_got[1] if kind_got else None
            if kind_got is None:
                talk.warnings.append(
                    f"line {line}: check 37: {tok!r} is not a timer: write a duration "
                    f"like 90s, 8m, 1h30m or 5:00 (not zero), then optionally "
                    f"'corner' — left as text")
                continue
            if cur is not None and cur.timer_block is not None or block.timer is not None:
                talk.warnings.append(
                    f"line {line}: check 37: more than one timer on a screen — "
                    f"{tok!r} ignored, the first stays")
                continue
            if kind_got[0] == "cont":
                # seconds and phrase come from the parent, after parsing
                block.timer, block.timer_cont = (0, "", got), True
                continue
            if got[0] > TIMER_MAX_SECONDS:
                talk.warnings.append(
                    f"line {line}: check 38: {tok!r} is a timer over 3 hours; "
                    f"probably a slip (kept as written)")
            block.timer = got

    print_open = None     # (screen, first block index) of a `[notes]` run being read

    def close_print() -> None:
        """Move the blocks a `[notes]` run produced into one handout-only wrapper."""
        nonlocal print_open
        if print_open is None:
            return
        scr, at = print_open
        print_open = None
        moved = scr.blocks[at:]
        if moved:
            scr.blocks[at:] = [Block(kind="print", inner=moved, line=moved[0].line,
                                     line_end=moved[-1].line_end or moved[-1].line)]

    # Written `Movement N` numbers are kept only when every section in the file
    # is numbered; mixed with plain `##` sections, ordinals are by position so
    # they can't collide.
    mixed_sections = any(
        _is_section_heading(raw_blocks, k) and not MOVEMENT_RE.match(b["text"])
        for k, b in enumerate(raw_blocks))
    for i_rb, rb in enumerate(raw_blocks):
        kind = rb["kind"]
        if wp_pending is not None and not (
                pending_handout or cur is None
                or raw_blocks[i_rb - 1]["kind"] == "hr"):
            raise _waypoint_error(source, wp_pending[1], "waypoint= is on a shot "
                                  "that opens no new screen: put it on the shot "
                                  "that starts the screen")
        if rb.get("wp"):
            word, wline = rb["wp"]
            if word in wp_seen:
                raise _waypoint_error(source, wline, f"waypoint {word!r} is used "
                                      f"twice (first at line {wp_seen[word]})")
            wp_seen[word] = wline
            wp_pending = (word, wline)
        close_print()
        if rb.get("print") and kind not in ("shot", "include") and cur is not None:
            print_open = (cur, len(cur.blocks))

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
            if mm or MOVEMENT_LOOK_RE.match(rb["text"]) or _is_section_heading(raw_blocks, i_rb):
                if not mm and MOVEMENT_LOOK_RE.match(rb["text"]):
                    # Register check 22: the author intended a numbered
                    # movement but the shape is wrong.
                    raise ValueError(
                        f"{source}:{rb.get('line', 0)}: check 22: H2 "
                        f"{rb['text']!r} begins with 'Movement' but does not "
                        f"match 'Movement <integer> [separator] <title>' — "
                        f"fatal (spec: Error and warning taxonomy: a malformed movement heading is "
                        f"never silently treated as screen text)"
                    )
                cur = None  # section boundary closes any open screen
                credits_open = False
                if mm and not mixed_sections:
                    movement_index = int(mm.group(1))
                else:
                    movement_index += 1       # by position
                mtitle = section_title(rb["text"], movement_index)
                talk.movements.append(
                    Movement(index=movement_index, title=mtitle, label=rb["text"])
                )
                if pending_role is not None:
                    talk.warnings.append(
                        f"line {role_line}: role shot never consumed a payload "
                        f"(section boundary crossed first)"
                    )
                    pending_role = None
                continue

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
                and kind not in ("para", "vo", "quote", "list", "table", "code")):
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
            hb = Block(kind="heading", refs=hmarks,
                       text=strip_footnote_refs(rb["text"], talk.footnote_ids, hmarks),
                       level=rb["level"],
                       line=rb.get("line", 0),
                       line_end=rb.get("line_end", 0) or rb.get("line", 0))
            scan_timer(hb, hb.text, hb.line)
            cur.blocks.append(hb)
            continue

        if kind == "code":
            # a fenced block: screen text, shown verbatim, never spoken.  Not a
            # role payload (the payload rule is for a paragraph), so a pending
            # role keeps waiting past it like past a list.
            ln = rb.get("line", 0)
            if not rb.get("closed", True):
                talk.warnings.append(
                    f"line {ln}: check 35: fenced block never closes; it ends "
                    f"at line {rb.get('line_end', ln)}, the end of its screen "
                    f"(spec: Text, fenced code)")
            if not rb["text"].strip():
                talk.warnings.append(
                    f"line {ln}: check 36: empty fenced block; nothing is "
                    f"shown for it (spec: Text, fenced code)")
            cur.blocks.append(
                Block(kind="code", text=rb["text"], line=ln,
                      line_end=rb.get("line_end", 0) or ln))
            continue

        if kind == "quote":
            qmarks: list = []
            qb = Block(kind="quote", refs=qmarks,
                       text=strip_footnote_refs(rb["text"], talk.footnote_ids, qmarks),
                       line=rb.get("line", 0),
                       line_end=rb.get("line_end", 0) or rb.get("line", 0))
            scan_timer(qb, qb.text, qb.line)
            cur.blocks.append(qb)
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
            lb = Block(kind="list",
                       items=[strip_footnote_refs(i, talk.footnote_ids)
                              for i in rb["items"]],
                       ordered=rb.get("ordered", False),
                       depths=(rb["depths"] if any(rb.get("depths", ())) else []),
                       spoken=spoken_seen,
                       line=rb.get("line", 0),
                       line_end=rb.get("line_end", 0) or rb.get("line", 0))
            if spoken_seen:
                # The list is read aloud.  A parenthetical inside an item is
                # never spoken (spec: Text — Directions): it comes out of the
                # speech and travels as a stage note, while the slide keeps the
                # item as written.
                for item in lb.items:
                    said, stage = split_parens(item)
                    lb.spoken_items.append(said.strip())
                    lb.stage.extend(stage)
            scan_timer(lb, "\n".join(lb.items), lb.line)
            cur.blocks.append(lb)
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
            qm = QUIET_TIMER_RE.fullmatch(clean.strip())
            if qm:
                # `([Timer: 5m])`: a timer for the presenter window only
                qb = Block(kind="timer", text=qm.group(1), line=rb.get("line", 0),
                           line_end=rb.get("line_end", 0) or rb.get("line", 0),
                           spoken=False, timer_quiet=True)
                scan_timer(qb, qb.text, qb.line)
                cur.blocks.append(qb)
                continue
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
            uc = unclosed_paren_at(clean)
            if uc is not None:
                talk.warnings.append(
                    f"line {rb.get('line', 0)}: check 46: unclosed parenthetical "
                    f"'{clean[uc:uc + 30].strip()}...' is read as spoken text and "
                    f"prints in the handout; close it with ')' (spec: Text)"
                )
            bkind = "vo"
            is_spoken = False
            if spoken.startswith("~") and not spoken.startswith("~~") \
                    and len(spoken) > 1 and not spoken[1].isspace():
                spoken = "~ " + spoken[1:]      # `~Source` is `~ Source`
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
                #  and falls through to VO with a check-24 warning).
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
            pb = Block(kind=bkind, text=spoken, stage=stage, line=rb.get("line", 0),
                       line_end=rb.get("line_end", 0) or rb.get("line", 0),
                       spoken=is_spoken, refs=pmarks)
            if bkind == "vo" and TIMER_TOKEN_RE.search(spoken):
                if TIMER_TOKEN_RE.fullmatch(spoken):
                    # a token alone on its line is a timer block, not speech
                    pb.kind, pb.text, pb.spoken = "timer", spoken, False
                    scan_timer(pb, spoken, pb.line)
                else:
                    talk.warnings.append(
                        f"line {pb.line}: check 39: a [Timer: ...] token in a spoken "
                        f"paragraph would be read aloud, so it is dropped and starts "
                        f"nothing; put it on its own line, or in a heading, list, "
                        f"quote or stat")
                    pb.text = strip_timer_tokens(spoken)
            elif bkind in ("stat", "paraphrase"):
                scan_timer(pb, spoken, pb.line)
            if pb.kind == "vo" and NEXT_TOKEN_RE.search(pb.text):
                pb.text, pb.nexts = split_next_tokens(pb.text)
            cur.blocks.append(pb)
            if (pb.text.strip() and (pb.kind == "vo" or pb.spoken)
                    and not rb.get("print")):
                # spoken voice-over on this screen: a list after it is read
                # aloud too (spec: Text — Spoken lists).  A `[notes]` block's
                # paragraph is never spoken, so it does not count.
                spoken_seen = True
            continue

        talk.warnings.append(f"line {rb.get('line', 0)}: unhandled block kind {kind}")

    close_print()
    if wp_pending is not None:
        raise _waypoint_error(source, wp_pending[1], "nothing follows the waypoint "
                              "directive: it marks the next screen")
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
    link_timer_continuations(talk)
    number_sections(talk)
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
