"""check.py — animatic deterministic check suite (T08).

One talkfile in, one exit code out.  Deterministic: same input, same findings,
same order, same exit code.  No LLM, no network, no writes outside the caller's
out dir.

Run::

    python3 check.py TALKFILE [TALKFILE ...] [--strict] [--cues FILE] [--register]
    python3 check.py --corpus [ROOT] [--strict]      # corpus mode (check 21)

Exit codes:
    0  clean — no fatal finding (warnings are fine; a deck must always build)
    1  a fatal finding (or, under --strict, any warning), or a parse error
    2  usage error (missing/invalid talkfile, unknown flag)

Severity taxonomy (spec: Error and warning taxonomy as the register defines it):

    fatal     build must refuse: malformed frontmatter/bad YAML, an H2 that
              looks like a Movement heading but does not match the pattern
              (check 22), a media slug equal to a role name (check 3), a
              cue-id space that cannot hold the deck (check 18).  Under
              --strict, warnings escalate to this class for the exit code.
    warning   authoring defect the author must see: duplicate card slug,
              slug charset violations, duplicate `fit=`, duplicate overlay
              roles, an orphaned media brief (no card), a `[^id]` footnote
              with no `sources:` registry entry, and every parser warning
              (checks 23/24/25/26 ship from talkparse).  Non-fatal: a deck
              always builds.  --strict makes these fatal.
    info      legal, but the author probably wants to know: flags on non-first
              shots are ignored, piece/dim & kb/piece interactions, a
              (Visual:) brief with no media shot on its screen, an approved
              card with no resolvable file.
    report    archaeology and delivery reports, printed, never an exit
              failure: attempt/gen-log drift (13), attempt numbering gaps
              (14), licence-before-public-use (16), timing divergence from
              `dur` (19).  Not diagnostics: a deck carrying them is not
              defective.

Register canonicalization (engine-decision Verification/Error and warning taxonomy: "register canonicalization
is T08").  The 1-30 register table with owner + status lives in REGISTER below
and prints with --register.  Rows implemented here: 1-9, 11-16, 18 (model
assert + artifact assert), 19 (the timing clock; the estimate itself ships
from render.py/timing.py), 21 (corpus harness), 28.  Rows enforced by the
parser/resolver ships from earlier tickets: 10 (mediaresolve), 17 (render,
T02), 22-26 (talkparse), 27 (T07 fixture).  Explicitly deferred with reason:
20 (the --variant build lands with T14; T14's file scope includes check.py).

Check 19 reads the deck-local `timing.yaml` sidecar (timing.py) next to the
talkfile: the clock compares sum(effective seconds) against the declared
`dur`, where effective is measured > authored > estimated per cue.  A missing
or unreadable sidecar is never an error — it just leaves every cue at its
estimate.

Importable by build.py and a future `animatic` wrapper (there is no animatic
CLI today).  check_file() is the per-deck seam the --corpus driver (T11)
reuses; corpus mode builds each deck's cues.json into a temp dir so the
artifact assertions 17/18 fire per deck, and the suite never edits
talkparse.py/render.py and never writes outside /tmp or the caller's chosen
output.  Corpus content roots are declared in corpus.yaml (spec: Media).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import tempfile
import warnings
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

import talkparse
import render
import timing
from mediaresolve import MEDIA_EXTS, MediaResolver, expand_pools

# ---------------------------------------------------------------------------
# Severity + register
# ---------------------------------------------------------------------------

FATAL = "fatal"
WARNING = "warning"
INFO = "info"
REPORT = "report"
_SEV_ORDER = {FATAL: 0, WARNING: 1, INFO: 2, REPORT: 3}

# Spec anchors used by several checks.
ROLE_WORDS = (set(talkparse.ROLES_DYNAMIC) | {talkparse.BLACK_ROLE}
              | set(talkparse.CONTINUE_WORDS))   # vocab roles + black + continue/cont
SLUG_RE = re.compile(r"^[a-z0-9-]{3,40}$")                    # Media: charset + length
PERSONAL_PATH_RE = re.compile(r"^/(?:[^/]+/)+[^/]+$")         # absolute, no scheme
FOOTNOTE_REF_RE = talkparse.FOOTNOTE_REF_RE
COMMENT_SPAN_RE = re.compile(r"<!--.*?-->", re.DOTALL)
GENLOG_HEADER_RE = re.compile(
    r"^##\s+(\S+)\s*·\s*([a-z0-9][a-z0-9-]*)\s*·\s*a(\d+)\s*$")
# The batch shapes a gen-log also records attempts in (spec: Media pipeline
# contract).  A take line names one attempt; its slug is given inline, as
# ingest.py writes `(slug <slug>, ...)`, or by the `### <slug> — N take(s)`
# subheading of a bulk block.  A promote line names an attempt that already
# exists, so it is not a record of one.
GENLOG_TAKE_RE = re.compile(r"^-\s+a(\d+)\s+←\s+`[^`]*`(.*)$")
GENLOG_TAKE_SLUG_RE = re.compile(r"\(slug\s+([a-z0-9][a-z0-9-]*)")
GENLOG_BULK_RE = re.compile(r"^###\s+([a-z0-9][a-z0-9-]*)\s+—\s+\d+\s+takes?")
# History: an attempt that moved keeps its record under its new name.
GENLOG_RENAME_RE = re.compile(
    r"^-\s+([a-z0-9][a-z0-9-]*)-a(\d+)\.\S+\s+->\s+([a-z0-9][a-z0-9-]*)-a(\d+)\.\S+\s*$")
GENLOG_SPLIT_RE = re.compile(
    r"^-\s+split:\s+([a-z0-9][a-z0-9-]*)-a(\d+)\s+->\s+new slug\s+`([a-z0-9][a-z0-9-]*)`")

# Canonical register (work-spec: Text coverage table + report Part 4/6 additions).
# status: implemented (this file) | enforced (owner ticket) | fixture |
#         deferred (owner ticket).
REGISTER = [
    (1,  "duplicate slug within one cards.yaml",                     WARNING, "implemented"),
    (2,  "media slug charset/length (Media rule)",                      WARNING, "implemented"),
    (3,  "slug equal to a role name or black",                       FATAL,   "implemented"),
    (4,  "movement ordinals: duplicates/non-monotonic/gaps",         WARNING, "implemented"),
    (5,  "deck-slug slugification collisions across a content root", WARNING, "implemented"),
    (6,  "two `fit=` values on one shot",                            WARNING, "implemented"),
    (7,  "flags on non-first shots of a screen (ignored)",           INFO,    "implemented"),
    (8,  "`piece`+`dim` / `kb`+`piece` info notes",                  INFO,    "implemented"),
    (9,  "duplicate overlay roles on one screen",                    WARNING, "implemented"),
    (10, "card-declared path resolves to an existing file",          WARNING, "enforced: mediaresolve.py (T01)"),
    (11, "media shot with no card (orphaned brief)",                 WARNING, "implemented"),
    (12, "`(Visual:)` stage note with no media shot on the screen",  INFO,    "implemented"),
    (13, "attempt files vs gen-log entries drift",                   REPORT,  "implemented"),
    (14, "attempt numbering gapped/non-monotonic per slug",          REPORT,  "implemented"),
    (15, "`status: approved` card with no resolvable file",          INFO,    "implemented"),
    (16, "licence-before-public-use (third-party on a public deck)", REPORT,  "implemented"),
    (17, "no absolute paths in cues.json",                           FATAL,   "enforced: render.py (T02); artifact check in check.py"),
    (18, "lexical sort of cue ids == ordinal order",                 FATAL,   "implemented"),
    (19, "sum(est_seconds) vs frontmatter dur divergence",           REPORT,  "implemented: check.py + timing.py"),
    (20, "variant build emits included/excluded manifest",           REPORT,  "deferred: T14"),
    (21, "corpus: all decks parse/build/pass",                       REPORT,  "implemented"),
    (22, "malformed Movement heading fatal",                         FATAL,   "enforced: talkparse.py (T05)"),
    (23, "nested parens warning",                                    WARNING, "enforced: talkparse.py (T06)"),
    (24, "attribution-shaped line with no quote warns",              WARNING, "enforced: talkparse.py (T06)"),
    (25, "no silent token drop in a shot comment",                   WARNING, "enforced: talkparse.py (T05)"),
    (26, "no warning text contains 'line 0'",                        WARNING, "enforced: talkparse.py (T07); guard in check.py"),
    (27, "multi-line shot fixture",                                  WARNING, "fixture: tests/fixtures/constructs/multiline-shot.talk.md (T07)"),
    (28, "`[^id]` footnote with no sources: registry entry",         WARNING, "implemented"),
    (29, "card `playback:`/`sound:` value unknown, on a non-video, or unbakeable", WARNING, "implemented: check.py + mediaresolve.py"),
    (30, "`dim` on a media screen with no on-screen text",              WARNING, "implemented"),
    (31, "`advance`/`playback=`/`sound` shot flag on a screen whose media is not a video", WARNING, "implemented"),
    (32, "`under=`/`blur=`/`anchor=` shot flag that cannot work: backdrop not a still image, `blur=`/`anchor=` with no `under=`, or a framed layout", WARNING, "implemented"),
    (33, "card `steps:`/`handout:` that cannot apply: a step that is not an image or is a video, fewer than 2 steps, or a `handout:` outside the steps (the card falls back to one plain image)", WARNING, "implemented: check.py + mediaresolve.py"),
    (34, "a stepped-image card and a `reveal=list` list of different lengths on one screen (they advance together; the shorter holds)", WARNING, "implemented"),
    (35, "a fenced block (```) that never closes: it ends at the end of its screen", WARNING, "enforced: talkparse.py"),
    (36, "an empty fenced block (nothing to show)", WARNING, "enforced: talkparse.py"),
    (37, "a `[Timer: ...]` token that is not a timer (bad or zero duration, unknown trailing word) or a second timer on one screen; it stays as literal text", WARNING, "enforced: talkparse.py"),
    (38, "a `[Timer: ...]` over 3 hours (sanity; the timer is kept)", WARNING, "enforced: talkparse.py"),
    (39, "a `[Timer: ...]` token in a spoken paragraph: dropped from the voice-over, starts nothing", WARNING, "enforced: talkparse.py"),
    (40, "a screen's `[next]` / `[n]` marks differ in number from its next-presses (stepped images, `reveal=list` items)", WARNING, "implemented"),
    (41, "pool card that cannot apply: folder missing or empty, a `pins:` file not in the folder, or a pin id that breaks the slug rule or repeats a card (a bad pin renders a placeholder or is ignored)", WARNING, "implemented: check.py + mediaresolve.py"),
    (42, "a `[notes]` block that repeats a list the notes already carry (a list read aloud, or a screen's reading copy): the copy is redundant", WARNING, "implemented"),
    (43, "`reveal=list` on a screen with no list of 2 or more items: the flag is ignored", WARNING, "implemented"),
    (44, "`reveal=timer` on a screen with no valid `[Timer: ...]` (none written, or the token is bad, zero or a second one; check 37 says which): the flag is ignored and nothing is hidden", WARNING, "implemented: check.py + render.py"),
    (45, "a bare `reveal` on a screen with nothing revealable on it (no list of 2 or more items, no valid timer): the flag does nothing", WARNING, "implemented: check.py + render.py"),
]

DEFERRED = {
    20: "check 20 needs the --variant build that emits the included/excluded "
        "manifest; that lands with T14 (dense renumbering + canonical remap), "
        "whose file scope includes check.py.",
}


DEFERRED_LINE = ("deferred : check 20 -> T14 (variant manifest) — full reason "
                 "under --register")


@dataclass
class Finding:
    check: Optional[int]          # register number; None = suite/parse-level
    severity: str
    message: str
    line: Optional[int] = None
    screen: Optional[int] = None

    def sort_key(self):
        return (_SEV_ORDER.get(self.severity, 9), self.check or 0,
                self.line or 0, self.screen or 0, self.message)

    def render(self) -> str:
        loc = ""
        if self.line is not None:
            loc = f" line {self.line}"
        elif self.screen is not None:
            loc = f" screen {self.screen}"
        tag = f"check {self.check:>2}" if self.check else "suite "
        return f"{self.severity:<7} {tag}{loc}  {self.message}"


@dataclass
class Report:
    source: str
    findings: list = field(default_factory=list)
    strict: bool = False
    parse_error: Optional[str] = None      # fatal raised before a model existed

    def add(self, check, severity, message, line=None, screen=None):
        self.findings.append(Finding(check, severity, message, line, screen))

    def sorted(self) -> list:
        return sorted(self.findings, key=Finding.sort_key)

    @property
    def fatal_count(self) -> int:
        n = 1 if self.parse_error else 0
        return n + sum(1 for f in self.findings if f.severity == FATAL)

    @property
    def exit_code(self) -> int:
        if self.fatal_count:
            return 1
        if self.strict and any(f.severity == WARNING for f in self.findings):
            return 1
        return 0

    def render(self) -> str:
        out = []
        out.append(f"animatic check — {self.source}")
        if self.parse_error:
            out.append(f"fatal    parse error: {self.parse_error}")
        for f in self.sorted():
            out.append(f.render())
        counts = {s: 0 for s in _SEV_ORDER}
        for f in self.findings:
            counts[f.severity] = counts.get(f.severity, 0) + 1
        strict_note = ""
        if self.strict and counts[WARNING]:
            strict_note = " — warnings fatal under --strict"
        out.append(
            f"summary  : {counts[FATAL]} fatal, {counts[WARNING]} warning, "
            f"{counts[INFO]} info, {counts[REPORT]} report — "
            f"exit {self.exit_code}{strict_note}")
        return "\n".join(out)


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def deck_slug(talk: talkparse.Talk) -> str:
    """Mirror render.deck_slug: the slugified frontmatter slug (spec: Frontmatter/Screens)."""
    raw = str(talk.meta.get("slug", "") or Path(talk.source).stem)
    return talkparse.slugify(raw)


def slug_ok(slug: str) -> bool:
    """Spec Media: charset [a-z0-9-], 3-40 chars, no leading/trailing '-'.
    (Leading '_' is reserved, so '_' is outside the charset and fails here.)"""
    return bool(SLUG_RE.fullmatch(slug)) and not slug.startswith("-") \
        and not slug.endswith("-")


def _fm_slug(path: Path) -> Optional[str]:
    """Frontmatter `slug` of a talkfile without parsing the whole deck.
    Mirrors talkparse._lex_frontmatter's split (private API)."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return None
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        return None
    try:
        meta = yaml.safe_load("\n".join(lines[1:end])) or {}
    except yaml.YAMLError:
        return None
    if not isinstance(meta, dict):
        return None
    raw = str(meta.get("slug", "") or path.stem)
    return talkparse.slugify(raw)


def iter_footnote_refs(body_lines: list) -> list:
    """[(line_no, ref_id), ...] for `[^id]` refs in body text, skipping
    fenced code blocks (verbatim text), comment spans (shot directives and inert comments) and `[^id]:`
    definition shapes (receipts have no body-level definition form, Text)."""
    out = []
    in_comment = False
    fenced = talkparse.fenced_line_indexes(body_lines)   # fenced text is literal
    for lineno, raw in enumerate(body_lines, start=1):
        if lineno - 1 in fenced:
            continue
        line = raw
        # mask comment spans (may cross lines)
        if in_comment:
            idx = line.find("-->")
            if idx < 0:
                continue
            line = line[idx + 3:]
            in_comment = False
        while True:
            start = line.find("<!--")
            if start < 0:
                break
            end = line.find("-->", start)
            if end < 0:
                in_comment = True
                line = line[:start]
                break
            line = line[:start] + line[end + 3:]
        for m in FOOTNOTE_REF_RE.finditer(line):
            out.append((lineno, m.group(1)))
    return out


def _bad_cards_error(resolver) -> Optional[str]:
    return getattr(resolver, "_error", None)


# ---------------------------------------------------------------------------
# Grammar checks (1-9)
# ---------------------------------------------------------------------------


def check_1_dup_card_slug(talk, resolver, report: Report) -> None:
    seen = {}
    for c in resolver.cards:
        if not isinstance(c, dict) or not c.get("slug"):
            continue
        slug = str(c["slug"])
        if slug in seen:
            report.add(1, WARNING,
                       f"duplicate slug '{slug}' in cards.yaml — the first "
                       f"card wins and the duplicate is silently dead (spec "
                       f"Media: unique within a deck); both cards at positions "
                       f"{seen[slug]} and {len(seen) + 1}")
        else:
            seen[slug] = len(seen) + 1


def check_2_slug_charset(talk, resolver, report: Report) -> None:
    for c in resolver.cards:
        if isinstance(c, dict) and c.get("slug") and not slug_ok(str(c["slug"])):
            report.add(2, WARNING,
                       f"card slug {str(c['slug'])!r} violates the slug rule "
                       f"[a-z0-9-], 3-40 chars, no leading/trailing '-' "
                       f"(spec: Media) — a shot can never reference it "
                       f"(cards.yaml)")
    for e in resolver.library:
        if isinstance(e, dict) and e.get("slug") and not slug_ok(str(e["slug"])):
            report.add(2, WARNING,
                       f"library slug {str(e['slug'])!r} violates the slug "
                       f"rule [a-z0-9-], 3-40 chars, no leading/trailing '-' "
                       f"(spec: Media) — a shot can never reference it "
                       f"(library.yaml)")
    # shot slugs: the token-position rule makes any bare first token a slug,
    # so a shot slug violating Media is exactly the kind of typo to name.
    for s in talk.screens:
        for sh in s.shots:
            if sh.slug and not slug_ok(sh.slug):
                report.add(2, WARNING,
                           f"shot slug {sh.slug!r} violates the slug rule "
                           f"[a-z0-9-], 3-40 chars, no leading/trailing '-' "
                           f"(spec: Media)", line=sh.line, screen=s.idx)


def check_3_slug_role(talk, resolver, report: Report) -> None:
    for surface, entries, where in (
        ("card", resolver.cards, "cards.yaml"),
        ("library entry", resolver.library, "library.yaml"),
    ):
        for c in entries:
            if not isinstance(c, dict):
                continue
            slug = c.get("slug")
            if slug is None:
                continue
            if str(slug) in ROLE_WORDS:
                report.add(3, FATAL,
                           f"{surface} slug {slug!r} equals a role name, "
                           f"'black' or 'continue'/'cont' — a shot token can never reference it "
                           f"(the tokenizer reads it as a role), so the "
                           f"visual is unreachable (spec: Media/Error and warning taxonomy) ({where})")


def check_4_movements(talk, resolver, report: Report) -> None:
    seen = set()
    prev = None
    for m in talk.movements:
        idx = m.index
        if idx in seen:
            report.add(4, WARNING,
                       f"duplicate movement ordinal {idx} "
                       f"({m.label!r}) — two sections share one number "
                       f"(movement ordinals are presentation order, Screens/Remix)",
                       line=None)
        elif prev is not None and idx < prev:
            report.add(4, WARNING,
                       f"movement ordinal {idx} ({m.label!r}) follows "
                       f"{prev} — ordinals must be non-decreasing in file "
                       f"order (spec: Screens: movement ordinals are presentation "
                       f"order)")
        elif prev is not None and idx > prev + 1:
            report.add(4, INFO,
                       f"movement ordinal {idx} skips "
                       f"{', '.join(str(n) for n in range(prev + 1, idx))} — "
                       f"renumbering debris or a deleted movement (legal; "
                       f"renumber by the author, spec: Remix)")
        seen.add(idx)
        prev = idx


def check_5_deck_slug_collisions(files: list, report: Report) -> None:
    """Across a content root (any multi-talkfile invocation): two frontmatter
    slugs slugifying equal.  Single-deck runs cannot evaluate this — corpus
    wiring arrives with T11's --corpus; the detector lives here so T11 calls
    it over the root."""
    if len(files) < 2:
        return
    by_slug = {}
    for p in files:
        p = Path(p)
        s = _fm_slug(p)
        if s:
            by_slug.setdefault(s, []).append(str(p))
    for s in sorted(by_slug):
        paths = sorted(by_slug[s])
        if len(paths) > 1:
            report.add(5, WARNING,
                       f"frontmatter slug slugifies to {s!r} in multiple "
                       f"decks: {', '.join(paths)} — cue-id namespaces "
                       f"collide across a content root (spec: Frontmatter/Screens)")


def check_6_dup_fit(talk, resolver, report: Report) -> None:
    for s in talk.screens:
        for sh in s.shots:
            m = talkparse.SHOT_RE.match(sh.raw)
            spec = (m.group(1) or "").strip() if m else ""
            tokens = spec.split()
            fits = [t for t in tokens if t.startswith("fit=")]
            if len(fits) > 1:
                report.add(6, WARNING,
                           f"shot carries two fit= values "
                           f"({', '.join(fits)}) — the last silently wins; "
                           f"spec: The shot directive: a shot MUST NOT carry two fit= values",
                           line=sh.line, screen=s.idx)


def check_7_flags_nonfirst(talk, resolver, report: Report) -> None:
    for s in talk.screens:
        for sh in s.shots[1:]:
            if sh.flags:
                names = ", ".join(sorted(sh.flags))
                report.add(7, INFO,
                           f"flags on a non-first shot are ignored — "
                           f"slide-level and media flags are read from the "
                           f"screen's first shot only (spec: The shot directive interaction "
                           f"table): {names}",
                           line=sh.line, screen=s.idx)


def check_8_flag_combos(talk, resolver, report: Report) -> None:
    for s in talk.screens:
        mshot = s.media_shot
        if mshot is None:
            continue
        flags = mshot.flags
        layout_name = flags.get("layout")
        framed = layout_name in ("piece", "duo", "titled")
        if not framed:
            continue
        framed_desc = f"layout={layout_name}"
        if flags.get("dim"):
            report.add(8, INFO,
                       f"dim is ignored on {framed_desc} — a full-zone "
                       f"scrim behind a framed object would paint a box "
                       f"around it (spec: The shot directive interaction table)",
                       line=mshot.line, screen=s.idx)
        if flags.get("kb"):
            report.add(8, INFO,
                       f"kb is not applied on {framed_desc} — the camera "
                       f"lens wraps full-bleed media only; a framed object "
                       f"has no lens (spec: The shot directive interaction table)",
                       line=mshot.line, screen=s.idx)
    # Validate role=/layout= against the deck's effective vocabulary
    # (spec: Text/The shot directive redesign): deck -> shared -> built-in,
    # resolved once at parse and carried on the model, so check and parser can
    # never disagree about which names this deck knows (a deck-local
    # roles.yaml is what makes `role=<new name>` a yaml-only change).
    roles_yaml = talk.role_names
    layouts_yaml = set(getattr(talk, "layout_vocab", ()) or talkparse.LAYOUTS_DYNAMIC)
    for s in talk.screens:
        for sh in s.shots:
            role_val = sh.flags.get("role")
            if role_val is not None and str(role_val) not in roles_yaml:
                report.add(8, WARNING,
                           f"unknown role value {str(role_val)!r} (not in roles.yaml vocabulary) — line {sh.line}, screen {s.idx}")
            layout_val = sh.flags.get("layout")
            if layout_val is not None and str(layout_val) not in layouts_yaml:
                report.add(8, WARNING,
                           f"unknown layout value {str(layout_val)!r} (not in layouts.yaml vocabulary) — line {sh.line}, screen {s.idx}")


def check_9_dup_overlay_roles(talk, resolver, report: Report) -> None:
    for s in talk.screens:
        roles = {}
        for sh in s.shots:
            if sh.role in talk.role_names:
                roles.setdefault(sh.role, []).append(sh.line)
        for role, lines in sorted(roles.items()):
            if len(lines) > 1:
                report.add(9, WARNING,
                           f"more than one role={role} on one screen (shot lines "
                           f"{', '.join(str(n) for n in lines)}) — one "
                           f"overlay per role per screen; an unbounded stack "
                           f"is a slide trying to be three things "
                           f"(spec: Text)",
                           screen=s.idx)


# ---------------------------------------------------------------------------
# Media pipeline checks (10-16)
# ---------------------------------------------------------------------------


def check_10_declared_paths(talk, resolver, report: Report) -> None:
    for slug, raw in resolver.declared_missing:
        report.add(10, WARNING,
                   f"card '{slug}' declares a path that does not resolve: "
                   f"{raw} (joined to deck dir; spec: Media order + Media pipeline contract path "
                   f"rule)")


def check_11_media_no_card(talk, resolver, report: Report) -> None:
    by_slug = {}
    for s in talk.screens:
        for sh in s.shots:
            if sh.is_media and sh.slug:
                by_slug.setdefault(sh.slug, []).append(sh.line)
    for slug in sorted(by_slug):
        if resolver.card_for(slug) is None \
                and resolver.library_entry_for(slug) is None:
            lines = ", ".join(str(n) for n in sorted(set(by_slug[slug])))
            report.add(11, WARNING,
                       f"media shot with no card — the visual's brief is "
                       f"orphaned: '{slug}' (shot line(s) {lines}); the deck "
                       f"builds, but nothing documents this media (spec: Media pipeline contract)")


def check_12_visual_no_media(talk, resolver, report: Report) -> None:
    vis_re = re.compile(r"^\s*visual\s*:", re.IGNORECASE)
    for s in talk.screens:
        if s.media_shot is not None:
            continue
        for b in s.blocks:
            for st in b.stage:
                if vis_re.match(st):
                    report.add(12, INFO,
                               f"(Visual:) stage note on a screen with no "
                               f"media shot — a brief with nothing to "
                               f"brief ({st[:60]!r}); add the media shot or "
                               f"drop the note (spec: Text Tier B)",
                               line=b.line, screen=s.idx)


def _attempt_facts(media_dir: Path) -> tuple:
    """(files, log, logged, moved) — attempt numbers per slug from disk and gen-log.md.

    files:  {slug: {n: relative-path}} for media/<slug>/attempts/<slug>-aN.ext
            (media extensions only — *.expanded.txt sidecars are diagnostics
            of the same attempt, not attempts).
    log:    {slug: [(n, log_line_no)]} — the direct records, in log order:
            `## <date> · <slug> · a<N>` headers, ingest's `- aN ← `file`
            (slug <slug>, ...)` lines, and `- aN ← ...` lines under a bulk
            `### <slug> — N take(s)` subheading.  Promote lines are not records.
    logged: {slug: {n: log_line_no}} — where every recorded attempt lives now,
            after replaying the log's renames (`- old-aN.<ext> -> new-aM.<ext>`)
            and splits (`- split: old-aN -> new slug `X``, which lands as the
            new slug's next attempt) in log order.  A moved attempt is recorded
            under its new name and no longer under its old one.
    moved:  {slug: {n}} — attempt numbers that were used and then moved away.
            A split leaves a hole in the old slug's numbers, and that hole is
            history, not a numbering gap (check 14).
    """
    files = {}
    log = {}
    logged = {}
    moved = {}
    if media_dir.is_dir():
        for slug_dir in sorted(p for p in media_dir.iterdir() if p.is_dir()):
            slug = slug_dir.name
            adir = slug_dir / "attempts"
            if not adir.is_dir():
                continue
            pat = re.compile(rf"^{re.escape(slug)}-a(\d+)\.([a-z0-9]+)$")
            nums = files.setdefault(slug, {})
            for p in sorted(adir.iterdir()):
                m = pat.match(p.name)
                if m and ("." + m.group(2)) in MEDIA_EXTS:
                    nums[int(m.group(1))] = str(p.relative_to(media_dir))
        gl = media_dir / "gen-log.md"
        if gl.is_file():
            try:
                lines = gl.read_text(encoding="utf-8").split("\n")
            except OSError:
                lines = []

            def record(slug, n, lineno):
                log.setdefault(slug, []).append((n, lineno))
                logged.setdefault(slug, {}).setdefault(n, lineno)

            def move(old, n, new, m, lineno):
                moved.setdefault(old, set()).add(n)
                origin = logged.get(old, {}).pop(n, lineno)
                logged.setdefault(new, {}).setdefault(m, origin)

            bulk = None                   # the current `### <slug> — N take(s)` block
            for lineno, raw in enumerate(lines, start=1):
                line = raw.strip()
                if line.startswith("## "):
                    bulk = None
                    m = GENLOG_HEADER_RE.match(line)
                    if m:
                        record(m.group(2), int(m.group(3)), lineno)
                    continue
                m = GENLOG_BULK_RE.match(line)
                if m:
                    bulk = m.group(1)
                    continue
                m = GENLOG_TAKE_RE.match(line)
                if m:
                    rest = m.group(2)
                    if "promoted to" in rest:
                        continue
                    inline = GENLOG_TAKE_SLUG_RE.search(rest)
                    slug = inline.group(1) if inline else bulk
                    if slug:
                        record(slug, int(m.group(1)), lineno)
                    continue
                m = GENLOG_RENAME_RE.match(line)
                if m:
                    move(m.group(1), int(m.group(2)), m.group(3), int(m.group(4)), lineno)
                    continue
                m = GENLOG_SPLIT_RE.match(line)
                if m:
                    new = m.group(3)
                    nxt = max(logged.get(new, {}) or [0]) + 1
                    move(m.group(1), int(m.group(2)), new, nxt, lineno)
    return files, log, logged, moved


def check_13_14_attempts(talk, resolver, report: Report) -> None:
    media_dir = resolver.media_dir
    files, log, logged, moved = _attempt_facts(media_dir)
    log_present = (media_dir / "gen-log.md").is_file()
    for slug in sorted(set(files) | set(logged)):
        fset = set(files.get(slug, {}))
        lset = set(logged.get(slug, {}))
        for n in sorted(fset - lset):
            report.add(13, REPORT,
                       f"attempt file with no gen-log entry: "
                       f"{files[slug][n]} — archaeology drift (media/"
                       f"gen-log.md; spec: Media pipeline contract append-only)")
        for n in sorted(lset - fset):
            report.add(13, REPORT,
                       f"gen-log entry with no attempt file on disk: "
                       f"{slug} a{n} (media/gen-log.md line "
                       f"{logged[slug][n]}) — archaeology drift")
        # numbering: union must be contiguous 1..max (a number that moved to
        # another slug was used, so it is not a gap)
        union = sorted(fset | lset | moved.get(slug, set()))
        if union:
            missing = [n for n in range(1, union[-1] + 1) if n not in union]
            if missing:
                report.add(14, REPORT,
                           f"attempt numbering gapped for '{slug}': seen "
                           f"{', '.join('a' + str(n) for n in union)} — "
                           f"missing {', '.join('a' + str(n) for n in missing)} "
                           f"(per-slug attempt numbers are monotonic, spec: Media pipeline contract)")
        # non-monotonic in the log itself (append-only means a3 after a2)
        seen_in_log = []
        for n, _ in log.get(slug, []):
            if seen_in_log and n < seen_in_log[-1]:
                report.add(14, REPORT,
                           f"gen-log attempt numbers not monotonic for "
                           f"'{slug}': a{seen_in_log[-1]} followed by a{n} "
                           f"(gen-log.md is append-only; entries are never "
                           f"renumbered, spec: Media pipeline contract)")
            seen_in_log.append(n)


def check_15_approved_no_file(talk, resolver, report: Report) -> None:
    for c in resolver.cards:
        if not isinstance(c, dict):
            continue
        if c.get("status") != "approved":
            continue
        slug = str(c.get("slug", ""))
        if not slug:
            continue
        ref = resolver.resolve(slug)
        if not ref.found:
            report.add(15, INFO,
                       f"card '{slug}' is status approved but no file "
                       f"resolves — it renders a placeholder; legal per "
                       f"spec: Media pipeline contract (resolution is by file presence, never by "
                       f"status), but the author wants this list before "
                       f"delivery")


def check_16_licence(talk, resolver, report: Report) -> None:
    status = str(talk.meta.get("status", "") or "")
    if not re.search(r"\b(delivered|public)\b", status, re.IGNORECASE):
        return
    seen = set()
    for s in talk.screens:
        for sh in s.shots:
            if not (sh.is_media and sh.slug):
                continue
            slug = sh.slug
            if slug in seen:
                continue
            seen.add(slug)
            card = resolver.card_for(slug) or resolver.library_entry_for(slug)
            if not card:
                continue
            credit = str(card.get("credit", "") or "")
            licence = str(card.get("licence", "") or "")
            third_party = ("ryan" not in credit.lower()) if credit else True
            licence_tbd = (not licence) or licence.strip().upper() in \
                ("TBD", "?", "NONE", "UNKNOWN", "TO BE DETERMINED")
            if third_party or licence_tbd:
                problems = []
                if third_party and credit:
                    problems.append(f"credit {credit!r} is not Ryan")
                elif not credit:
                    problems.append("no credit recorded")
                if licence_tbd:
                    problems.append(f"licence {licence or 'missing'!r}")
                report.add(16, REPORT,
                           f"deck status says {status!r} but referenced "
                           f"media '{slug}' is not delivery-clean: "
                           f"{'; '.join(problems)} — licence-before-public-"
                           f"use (library.yaml header convention)")


# ---------------------------------------------------------------------------
# Output checks (17-18) + footnote checks (28)
# ---------------------------------------------------------------------------


def check_cues_json(path: Path, report: Report) -> None:
    """Artifact-mode checks against a cues.json (register 17 + 18).  The
    suite is source-first: these run only when the caller hands over a built
    cues.json (--cues, or T10/T11 driving the artifact)."""
    try:
        text = path.read_text(encoding="utf-8")
        data = json.loads(text)
    except (OSError, ValueError) as exc:
        report.add(None, FATAL, f"cannot read cues.json {path}: {exc}")
        return
    # check 17: no absolute / personal paths in any emitted artifact (Outputs —
    # a build that leaks one is a defect, not a warning).
    hits = []

    def walk(node):
        if isinstance(node, str):
            if "://" in node:
                return
            if re.search(r"(?:/home/|/Users/|/root/|/tmp/)", node) \
                    or re.search(r"^[A-Za-z]:[\\/]", node) \
                    or PERSONAL_PATH_RE.match(node):
                hits.append(node)
        elif isinstance(node, dict):
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(data)
    for h in sorted(set(hits))[:20]:
        report.add(17, FATAL,
                   f"cues.json contains an absolute/personal path: {h!r} "
                   f"(spec: Outputs: no emitted artifact may contain a "
                   f"machine-local path)")
    if len(set(hits)) > 20:
        report.add(17, FATAL,
                   f"...and {len(set(hits)) - 20} more absolute/personal "
                   f"paths")
    # check 18: cue ids sort lexically in ordinal order.
    cues = data.get("cues") if isinstance(data, dict) else None
    if isinstance(cues, list):
        ids = [str(c.get("id", "")) for c in cues if isinstance(c, dict)]
        if ids != sorted(ids):
            first = next(i for i in range(len(ids) - 1)
                         if ids[i] > ids[i + 1])
            report.add(18, FATAL,
                       f"cues.json ids are not lexically sorted == ordinal: "
                       f"{ids[first]!r} precedes {ids[first + 1]!r} at "
                       f"position {first + 1} (spec: Screens/Outputs — padding cliff "
                       f"past 99 screens with 2-digit ids)")


def check_18_model_ids(talk, resolver, report: Report) -> None:
    """Cue-id space must hold the deck: ids are `<slug>-NNN` (3-digit,
    Screens) and lexically sort in presentation order up to 999 screens."""
    n = len(talk.screens)
    if n > 999:
        dslug = deck_slug(talk)
        report.add(18, FATAL,
                   f"{n} screens exceed the 3-digit cue-id space "
                   f"'{dslug}-NNN' — lexical sort diverges from ordinal "
                   f"past 999 (spec: Screens)")


# ---------------------------------------------------------------------------
# Timing (19) — the clock: est_seconds + timing.yaml vs the declared dur
# ---------------------------------------------------------------------------


def _dur_label(seconds: float) -> str:
    if seconds >= 60:
        return f"{seconds / 60:.1f} min ({seconds:.0f} s)"
    return f"{seconds:.1f} s"


def check_19_timing(talk, resolver, report: Report) -> None:
    """The deck's clock against its declared `dur` (spec: Timing).

    Effective seconds are per cue — measured > authored > estimated — and the
    estimate comes from render.cue_estimate, the same function that writes
    `est_seconds` into cues.json, so the artifact and this check can never
    disagree about a cue's guess.

    Past 30% divergence this *reports*: never a warning, never an error.  The
    estimate is crude by design, and a hard failure would train people to
    ignore the check.  No `dur`, or a `dur` this cannot read, means there is
    nothing to compare — a talkfile stays valid with no `dur` at all.
    """
    deck_dir = Path(talk.source).parent if talk.source else Path.cwd()
    tt = timing.load(deck_dir)
    for problem in tt.problems:
        report.add(19, REPORT, problem)

    cue_ids = [f"{deck_slug(talk)}-{s.idx:03d}" for s in talk.screens]
    owned = set(cue_ids)
    for cid in sorted(tt.cues):
        if cid not in owned:
            report.add(19, REPORT,
                       f"timing.yaml overrides cue id {cid!r}, which no "
                       f"screen in this deck owns — the entry never applies "
                       f"(spec: Timing)")

    total = 0.0
    authors = 0
    for screen, cid in zip(talk.screens, cue_ids):
        est = render.cue_estimate(screen, resolver, tt.wpm)
        seconds, tier = tt.effective(cid, est)
        if tier != "estimated":
            authors += 1
        total += seconds

    raw_dur = talk.meta.get("dur")
    dur = timing.parse_dur(raw_dur)
    if dur is None:
        if raw_dur not in (None, ""):
            report.add(19, REPORT,
                       f"dur {raw_dur!r} is not a duration this check can "
                       f"read — the clock has nothing to compare against "
                       f"(spec: Timing)")
        return

    divergence = (total - dur) / dur
    if abs(divergence) <= timing.DIVERGENCE:
        return
    overrides = f"{authors} cue(s) overridden; " if authors else ""
    report.add(19, REPORT,
               f"effective timing {_dur_label(total)} vs declared dur "
               f"{_dur_label(dur)}: diverges {divergence:+.0%} (past the "
               f"{timing.DIVERGENCE:.0%} report threshold) — {overrides}"
               f"the estimate is crude by design (spec: Timing)")


def check_29_playback(talk, resolver, report: Report) -> None:
    """A card `playback:` that cannot apply as written plays as `loop`, and a
    `sound:` that cannot apply plays muted; say so.

    The resolver records unknown values and non-video cards for every card.
    Whether a pingpong can be baked is only known at publish time, so the
    check can only predict the one environment failure: no ffmpeg at all."""
    for slug, msg in resolver.playback_issues:
        report.add(29, WARNING, f"{msg} (spec: Media pipeline contract)")
    if shutil.which("ffmpeg") is None:
        for c in resolver.cards:
            if isinstance(c, dict) and c.get("playback") == "pingpong" \
                    and c.get("type") == "video":
                report.add(29, WARNING,
                           f"card '{c.get('slug')}' asks for playback: pingpong but "
                           f"ffmpeg is not installed; it will play as loop "
                           f"(spec: Media pipeline contract)")


def check_33_steps(talk, resolver, report: Report) -> None:
    """A card `steps:` / `handout:` that cannot apply as written leaves the
    card a plain single image; the resolver validates every card."""
    resolver.validate_steps()
    for slug, msg in resolver.steps_issues:
        report.add(33, WARNING, f"{msg} (spec: Media, stepped images)")


def check_34_step_counts(talk, resolver, report: Report) -> None:
    """Image steps and `reveal=list` items advance together on one press; a
    count mismatch leaves the shorter holding on its last, which is probably a
    slip."""
    for s, line, msg in render.step_count_notes(talk, resolver):
        report.add(34, WARNING, msg, line=line, screen=s.idx)


def check_43_reveal_without_list(talk, resolver, report: Report) -> None:
    """`reveal=list` steps the screen's first list; with no list of 2 or more
    items the build warns and ignores it. Say so here too, so a clean check
    means a clean build."""
    for s in talk.screens:
        for sh in s.shots:
            if "list" not in render.reveal_named(sh.flags):
                continue
            if any(b.kind == "list" and len(b.items) >= 2 for b in s.blocks):
                break
            report.add(43, WARNING,
                       "`reveal=list` needs a list of 2 or more items on the "
                       "screen; the flag is ignored (spec: Shot flags, `reveal`)",
                       line=sh.line, screen=s.idx)
            break


def check_44_reveal_timer_without_timer(talk, resolver, report: Report) -> None:
    """`reveal=timer` hides the screen's countdown until a next-press. With no
    valid timer on the screen the build warns and ignores it (nothing is
    hidden). Say so here too, and say which of the two mistakes it is."""
    for s in talk.screens:
        for sh in s.shots:
            if "timer" not in render.reveal_named(sh.flags):
                continue
            if s.timer is not None:
                break
            texts = [t for b in s.blocks for t in ([b.text or ""] + list(b.items or []))]
            if any(talkparse.TIMER_TOKEN_RE.search(t) for t in texts):
                why = ("the `[Timer: ...]` on it is not a valid timer (a bad or zero "
                       "duration, an unknown word, or a second timer: check 37)")
            else:
                why = "there is no `[Timer: ...]` on it"
            report.add(44, WARNING,
                       f"`reveal=timer` needs a valid timer on the screen, but {why}; "
                       "the flag is ignored and nothing is hidden (spec: Timer screens, "
                       "Revealed timers)",
                       line=sh.line, screen=s.idx)
            break


def check_45_bare_reveal_empty(talk, resolver, report: Report) -> None:
    """A bare `reveal` reveals whatever the screen has that can be revealed.
    On a screen with none of it, there is nothing to do; the build warns and
    ignores it. A stepped-image card already steps on its own, so it does not
    count."""
    for s in talk.screens:
        if not render.bare_reveal_empty(s):
            continue
        sh = next(sh for sh in s.shots if render.reveal_is_bare(sh.flags))
        report.add(45, WARNING,
                   "a bare `reveal` has nothing to reveal on this screen (no list of 2 or "
                   "more items, no valid `[Timer: ...]`); the flag does nothing (spec: Shot "
                   "flags, `reveal`)",
                   line=sh.line, screen=s.idx)


def check_41_pools(talk, resolver, report: Report) -> None:
    """A pool card's folder, `pins:` files and pin ids must hold up."""
    for slug, msg in resolver.pool_issues:
        report.add(41, WARNING, f"{msg} (spec: Media, pool cards)")


def check_40_next_marks(talk, resolver, report: Report) -> None:
    """`[next]` marks in the script should match the presses the screen takes."""
    for s, line, msg in render.next_mark_notes(talk, resolver):
        report.add(40, WARNING, msg, line=line, screen=s.idx)


def _norm_item(text: str) -> str:
    """A list item as a comparable string: case and spacing do not matter."""
    return " ".join(str(text).split()).lower()


def check_42_redundant_copy(talk, resolver, report: Report) -> None:
    """A `[notes]` block that repeats what the notes already carry is a copy
    of nothing.

    The notes carry the screen's text in three ways: a list the speaker reads
    aloud is in them (spec: Text — Spoken lists), a screen with nothing of
    its own to say copies its list or quote there (spec: Text — The reading
    copy), and a quote that follows the words is copied too. Either way the
    words the author wrote out again under `[notes]` would be read twice:
    once by the screen, once by the copy.  The copy can go.
    """
    for s in talk.screens:
        carried = [b for b, _html in render.speaker_notes(s)
                   if b.kind in ("list", "quote") and
                   (b.items if b.kind == "list" else b.text.strip())]
        if not carried:
            continue
        for b in s.blocks:
            if b.kind != "print":
                continue
            for ib in b.inner:
                if ib.kind != "list" or not ib.items:
                    continue
                for lb in carried:
                    if lb.kind != "list" or len(ib.items) != len(lb.items):
                        continue
                    if [_norm_item(i) for i in ib.items] != \
                            [_norm_item(i) for i in lb.items]:
                        continue
                    report.add(42, WARNING,
                               f"a `[notes]` block repeats the list on this "
                               f"screen word for word, and the notes already "
                               f"carry that list: the copy is redundant — "
                               f"delete the `[notes]` block",
                               line=b.line, screen=s.idx)


def check_30_dim_without_text(talk, resolver, report: Report) -> None:
    """`dim` exists to keep on-screen text readable over a picture. On a screen
    with no text it only darkens the picture: a chart or photo that is too
    bright should be fixed in the file, not dimmed (Ryan, 2026-09-28).
    Framed layouts ignore dim already (check 8 says so)."""
    for s in talk.screens:
        mshot = s.media_shot
        if mshot is None or not mshot.flags.get("dim"):
            continue
        if mshot.flags.get("layout") in ("piece", "duo", "titled"):
            continue
        if mshot.flags.get("under"):
            continue          # dim darkens the backdrop under the shot's own media, which carries the text
        if render.onscreen_blocks(s):
            continue
        report.add(30, WARNING,
                   f"dim={mshot.flags.get('dim')} on '{mshot.slug}' but the screen "
                   f"has no on-screen text: dim only darkens the picture. Drop it, "
                   f"or fix a too-bright image in the file itself",
                   line=mshot.line, screen=s.idx)


def check_31_advance_not_video(talk, resolver, report: Report) -> None:
    """`advance` moves the deck on when a slide video ends. On an image, a
    placeholder or a live capture nothing ever ends, so the screen waits for
    the presenter as usual; say so rather than let a rehearsal find out.
    A shot's `playback=` and `sound` only change a video, so they warn the
    same way."""
    for s in talk.screens:
        mshot = s.media_shot
        if mshot is None:
            continue
        names = [n for n in ("advance", "playback", "sound") if n in mshot.flags]
        if not names:
            continue
        ref = resolver.resolve(mshot.slug)
        ext = Path(ref.file).suffix.lower() if ref.found and ref.file else ""
        if ref.live or MEDIA_EXTS.get(ext) != "video":
            what = ("a live capture" if ref.live else
                    "a placeholder" if not ref.found else f"a {ext} file")
            if names == ["advance"]:
                why = "only a slide video that ends can move the deck on"
            else:
                why = "only a slide video plays, loops or has sound"
            report.add(31, WARNING,
                       f"{', '.join(names)} on '{mshot.slug}' but it resolves to {what}: "
                       f"{why}",
                       line=mshot.line, screen=s.idx)


def check_32_under_backdrop(talk, resolver, report: Report) -> None:
    """`under=<slug>` lays a still backdrop beneath the shot's own media and
    `blur=` softens it. Say so when that cannot happen: the backdrop slug is not
    a resolvable still image, `blur=` has nothing to blur, or the layout is a
    framed object (piece, duo, titled) with no full-bleed ground to put it on."""
    for s in talk.screens:
        mshot = s.media_shot
        if mshot is None:
            continue
        flags = mshot.flags
        under, blur = flags.get("under"), flags.get("blur")
        if blur is not None and not under:
            report.add(32, WARNING,
                       f"blur={blur} on '{mshot.slug}' without under=: blur frosts the "
                       f"panel behind the video, so it does nothing here",
                       line=mshot.line, screen=s.idx)
        if flags.get("anchor") and not under:
            report.add(32, WARNING,
                       f"anchor={flags['anchor']} on '{mshot.slug}' without under=: "
                       f"anchor places the media over a backdrop, so it does nothing here",
                       line=mshot.line, screen=s.idx)
        if not under:
            continue
        if flags.get("layout") in ("piece", "duo", "titled"):
            report.add(32, WARNING,
                       f"under={under} on '{mshot.slug}' with layout={flags['layout']}: "
                       f"a framed object has no full-bleed ground, so the backdrop is dropped",
                       line=mshot.line, screen=s.idx)
        ref = resolver.resolve(under)
        ext = Path(ref.file).suffix.lower() if ref.found and ref.file else ""
        if ref.live or MEDIA_EXTS.get(ext) != "image":
            what = ("a live capture" if ref.live else
                    "nothing (no card or file)" if not ref.found else f"a {ext} file")
            report.add(32, WARNING,
                       f"under={under} on '{mshot.slug}' resolves to {what}: the backdrop "
                       f"has to be a still image",
                       line=mshot.line, screen=s.idx)


def check_28_footnotes(talk, resolver, source_text: str, report: Report) -> None:
    meta = talk.meta
    sources = meta.get("sources")
    registry = sources if isinstance(sources, dict) else {}
    lines = source_text.split("\n")
    body_start = 0
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                body_start = i + 1
                break
    for lineno, rid in iter_footnote_refs(lines[body_start:]):
        # lineno is body-relative; re-base to the file
        if rid not in registry:
            report.add(28, WARNING,
                       f"footnote [^{rid}] (line {lineno + body_start}) has "
                       f"no sources: registry entry — the receipt cites "
                       f"nothing and no citation renders (spec: Frontmatter/Text)")


# ---------------------------------------------------------------------------
# Parser-surface checks (22-26 arrive from talkparse; surface + guard)
# ---------------------------------------------------------------------------


def surface_parse_errors(talk, resolver, report: Report) -> None:
    """talk.warnings are the parser's register findings (checks 23/24/25 and
    the unnumbered removed-form/tolerance warnings).  Normalize each into a
    Finding, pulling the line prefix and any embedded check label."""
    for w in talk.warnings:
        line = None
        m = re.match(r"line (\d+): (.*)$", w)
        text = w
        if m:
            line = int(m.group(1))
            text = m.group(2)
        check = None
        cm = re.match(r"check (\d+): (.*)$", text)
        if cm:
            check = int(cm.group(1))
            text = cm.group(2)
        report.add(check, WARNING, text, line=line)
        # check 26 guard: no warning text contains "line 0" (spec: Error and warning taxonomy).
        if "line 0" in w:
            report.add(26, WARNING,
                       f"parser warning text contains 'line 0': {w!r} — "
                       f"every warning must name its real source line "
                       f"(spec: Error and warning taxonomy)")


# ---------------------------------------------------------------------------
# Suite entry points
# ---------------------------------------------------------------------------


def run_checks(talk, resolver, source_text: str,
               extra_files: tuple = (), cues_path: Optional[Path] = None,
               report: Optional[Report] = None) -> Report:
    """Run the whole register over one parsed deck (+ optional extras)."""
    if report is None:
        report = Report(source=str(talk.source))
    bad = _bad_cards_error(resolver)
    if bad:
        report.add(None, WARNING, f"cards.yaml unreadable: {bad} — all cards "
                   f"ignored by the resolver")
    check_1_dup_card_slug(talk, resolver, report)
    check_2_slug_charset(talk, resolver, report)
    check_3_slug_role(talk, resolver, report)
    check_4_movements(talk, resolver, report)
    check_6_dup_fit(talk, resolver, report)
    check_7_flags_nonfirst(talk, resolver, report)
    check_8_flag_combos(talk, resolver, report)
    check_9_dup_overlay_roles(talk, resolver, report)
    check_10_declared_paths(talk, resolver, report)
    check_11_media_no_card(talk, resolver, report)
    check_12_visual_no_media(talk, resolver, report)
    check_13_14_attempts(talk, resolver, report)
    check_15_approved_no_file(talk, resolver, report)
    check_16_licence(talk, resolver, report)
    check_18_model_ids(talk, resolver, report)
    check_19_timing(talk, resolver, report)
    check_28_footnotes(talk, resolver, source_text, report)
    check_29_playback(talk, resolver, report)
    check_30_dim_without_text(talk, resolver, report)
    check_31_advance_not_video(talk, resolver, report)
    check_32_under_backdrop(talk, resolver, report)
    check_33_steps(talk, resolver, report)
    check_34_step_counts(talk, resolver, report)
    check_40_next_marks(talk, resolver, report)
    check_41_pools(talk, resolver, report)
    check_42_redundant_copy(talk, resolver, report)
    check_43_reveal_without_list(talk, resolver, report)
    check_44_reveal_timer_without_timer(talk, resolver, report)
    check_45_bare_reveal_empty(talk, resolver, report)
    surface_parse_errors(talk, resolver, report)
    check_5_deck_slug_collisions(list(extra_files), report)
    if cues_path is not None:
        check_cues_json(cues_path, report)
    return report


def check_file(path, *, strict=False, extra_files=(), cues_path=None) -> Report:
    """Per-deck seam (T11's --corpus drives this per deck).  Raises nothing:
    parse errors become a fatal parse_error on the Report."""
    p = Path(path)
    report = Report(source=str(p), strict=strict)
    try:
        text = p.read_text(encoding="utf-8")
    except OSError as exc:
        report.parse_error = f"cannot read {p}: {exc}"
        return report
    try:
        talk = talkparse.build_talk(p)
    except ValueError as exc:
        msg = str(exc)
        m = re.search(r":(\d+): check 22:", msg)
        if m:
            report.parse_error = f"{msg}"
            report.add(22, FATAL, msg, line=int(m.group(1)))
        else:
            report.parse_error = msg
        return report
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")     # mediaresolve warns check 10 via
        resolver = MediaResolver(talk_dir=p.parent, meta=talk.meta)
        # the warnings module; the suite surfaces declared_missing itself.
        expand_pools(talk, resolver)
    for inc in talk.includes:            # footnote refs inside included files
        try:
            text += "\n" + inc.read_text(encoding="utf-8")
        except OSError:
            pass
    return run_checks(talk, resolver, text, extra_files=extra_files,
                      cues_path=cues_path, report=report)


# ---------------------------------------------------------------------------
# Corpus harness (check 21, T11) — content roots -> per-deck pass/fail + drift
# ---------------------------------------------------------------------------

CORPUS_CONFIG = "corpus.yaml"            # repo-root content-root declaration
BANK_STATUSES = frozenset({"brief", "to-find", "file", "url", "prompting",
                           "candidate", "shortlist", "approved", "rejected"})
BANK_REQUIRED = ("slug", "status", "type")
_TAG_FILE_SKIP = frozenset({"index.md", "log.md"})   # OKF reserved (Frontmatter)
_RAW_SUBTREES = frozenset({"raw", "scrapes"})        # collected, not authored
_SUGGEST_TOP = 3
_MAX_PAIR_ROWS = 60
_MAX_COVERAGE_ROWS = 40
_WORD_RE = re.compile(r"[a-z0-9]{3,}")


def _frontmatter_meta(path: Path) -> tuple:
    """(meta dict, text head).  meta is None when the file has no YAML
    frontmatter (not an OKF concept).  Text head feeds tag suggestions."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None, ""
    head = text[:12000]
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return None, head
    end = None
    for i in range(1, min(len(lines), 200)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        return None, head
    try:
        meta = yaml.safe_load("\n".join(lines[1:end]))
    except yaml.YAMLError:
        meta = None
    if not isinstance(meta, dict):
        meta = {}
    return meta, head


def _meta_tags(meta: dict) -> list:
    """Frontmatter `tags` (OKF shared field, spec: Frontmatter) normalized: lowercase,
    strings only, deduped, order preserved."""
    if not isinstance(meta, dict):
        return []
    raw = meta.get("tags")
    if raw is None:
        return []
    if isinstance(raw, str):
        raw = re.split(r"[,\s]+", raw)
    if not isinstance(raw, list):
        return []
    out = []
    for t in raw:
        if isinstance(t, str):
            t = t.strip().lower()
            if t and t not in out:
                out.append(t)
    return out


def _walk_md(root: Path, *, skip_media: bool, skip_raw: bool) -> list:
    """Sorted .md files under root.  Always skips dot entries, node_modules
    and stale build dirs (out/, out-*); optionally media/_media (deck scan)
    or raw/scrapes (concept scan: machine-collected, never authored)."""
    found = []
    skip = {"node_modules"}
    if skip_media:
        skip |= {"media", "_media"}
    if skip_raw:
        skip |= set(_RAW_SUBTREES)
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(
            d for d in dirnames
            if not d.startswith(".")
            and d not in skip
            and d != "out" and not d.startswith("out-"))
        for fn in sorted(filenames):
            if not fn.startswith(".") and fn.endswith(".md"):
                found.append(Path(dirpath) / fn)
    return found


def discover_corpus(roots: dict) -> dict:
    """roots: {decks: [Path], concepts: [Path], banks: [Path]} -> found sets.

    deck     = talk.md / *.talk.md under a deck root (media/_media, out/,
               dot dirs skipped — those hold cards, gen-logs and stale
               builds, never deck sources).
    concept  = .md with frontmatter under a concept root, minus deck files
               and OKF-reserved index.md/log.md.  Feeds tag drift/coverage.
    bank     = explicit bank files from config + every library.yaml found
               under deck roots (shared banks).  Per-deck media/cards.yaml
               pools are owned by their deck's check run and are not swept
               here (a dup slug there already fires check 1 on the deck).
    All lists are sorted and deduped — deterministic iteration."""
    decks: list = []
    deck_roots = [Path(p) for p in roots.get("decks", [])]
    for root in deck_roots:
        for p in _walk_md(root, skip_media=True, skip_raw=False):
            if p.name == "talk.md" or p.name.endswith(".talk.md"):
                decks.append(p.resolve())
    decks = sorted(set(decks))
    deck_set = set(decks)

    concepts: list = []
    for root in [Path(p) for p in roots.get("concepts", [])]:
        for p in _walk_md(root, skip_media=True, skip_raw=True):
            if p.name in _TAG_FILE_SKIP or p.resolve() in deck_set:
                continue
            meta, _ = _frontmatter_meta(p)
            if meta is not None:
                concepts.append(p.resolve())
    concepts = sorted(set(concepts))

    banks: list = []
    for root in deck_roots:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = sorted(
                d for d in dirnames if not d.startswith(".")
                and d != "out" and not d.startswith("out-"))
            for fn in sorted(filenames):
                if fn == "library.yaml":
                    banks.append((Path(dirpath) / fn).resolve())
    for p in [Path(p) for p in roots.get("banks", [])]:
        banks.append(p.resolve())
    banks = sorted(set(banks))
    return {"decks": decks, "concepts": concepts, "banks": banks}


def _rel_label(root: Path, path: Path) -> str:
    """Root-basename-prefixed relative path for display, e.g.
    decks/L01-opening-talk/talk.md — roots are named dirs, so the prefix is
    unambiguous when the same relative layout exists under two roots."""
    try:
        rel = path.relative_to(root)
    except ValueError:
        return str(path)
    return f"{root.name}/{rel}"


def _sweep_bank(path: Path, label: str, crep: Report) -> None:
    """Shared-bank health row (REPORT: banks are content, never an exit
    failure — a broken bank fails the deck that references it instead)."""
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        crep.add(None, REPORT, f"bank {label}: unreadable: {exc}")
        return
    except yaml.YAMLError as exc:
        crep.add(None, REPORT, f"bank {label}: bad YAML: {exc}")
        return
    if not isinstance(raw, list):
        crep.add(None, REPORT,
                 f"bank {label}: top level is {type(raw).__name__}, not a "
                 f"list of cards — the resolver never reads it")
        return
    cards = [c for c in raw if isinstance(c, dict) and c.get("slug")]
    non_card = len(raw) - len(cards)
    seen = {}
    dups = []
    missing_req = []
    bad_status = []
    hist = Counter()
    for c in raw:
        if not isinstance(c, dict) or not c.get("slug"):
            continue
        slug = str(c["slug"])
        if slug in seen:
            dups.append(slug)
        else:
            seen[slug] = True
        for key in BANK_REQUIRED:
            if key not in c or c.get(key) in (None, ""):
                missing_req.append(f"{slug}:{key}")
        status = c.get("status")
        if status is not None and status not in BANK_STATUSES:
            bad_status.append(f"{slug}:{status}")
        if isinstance(status, str):
            hist[status] += 1
    parts = [f"{len(cards)} cards"]
    if hist:
        parts.append("status " + ", ".join(
            f"{s}={hist[s]}" for s in sorted(hist)))
    if non_card:
        parts.append(f"{non_card} non-card entr{'y' if non_card == 1 else 'ies'} "
                     f"ignored")
    if dups:
        crep.add(None, REPORT,
                 f"bank {label}: duplicate slug(s) in one bank file — the "
                 f"first entry wins for every referencing deck: "
                 f"{', '.join(sorted(set(dups)))}")
    if missing_req:
        crep.add(None, REPORT,
                 f"bank {label}: card(s) missing a required key "
                 f"{'/'.join(BANK_REQUIRED)} (spec: Media pipeline contract): "
                 f"{', '.join(sorted(set(missing_req))[:8])}"
                 + (" …" if len(set(missing_req)) > 8 else ""))
    if bad_status:
        crep.add(None, REPORT,
                 f"bank {label}: unknown status value(s): "
                 f"{', '.join(sorted(set(bad_status))[:8])}")
    crep.add(None, REPORT, f"bank {label}: {'; '.join(parts)}")


def _lev(a: str, b: str, cap: int = 2) -> int:
    """Levenshtein distance with an early exit past `cap` (returns cap+1)."""
    if a == b:
        return 0
    la, lb = len(a), len(b)
    if abs(la - lb) > cap:
        return cap + 1
    prev = list(range(lb + 1))
    for i in range(1, la + 1):
        cur = [i] + [0] * lb
        row_min = cur[0]
        ca = a[i - 1]
        for j in range(1, lb + 1):
            cost = 0 if ca == b[j - 1] else 1
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
            if cur[j] < row_min:
                row_min = cur[j]
        if row_min > cap:
            return cap + 1
        prev = cur
    return prev[lb]


def _near_miss_pairs(vocab: Counter) -> list:
    """[(dist, tag_a, tag_b)] sorted; same first char and length gap <= 2
    prefilter keeps the scan linear-ish (spec: Error and warning taxonomy drift: catches
    `#enclosive` beside `#enclosure`).

    Two noise filters, because a drift report that cries wolf gets ignored:
    - both tags must be >= 4 chars — 3-letter tags are acronym space where
      edit-distance neighbours (ai/api/arc/art) are usually distinct legit
      terms, not drift;
    - a numbered family (l01/l02, phase-1/phase-2) is deliberate parallel
      vocabulary, not a misspelling — equal alphabetic prefixes ending in
      digits are skipped."""
    by_first = defaultdict(list)
    for t in vocab:
        if len(t) >= 4:
            by_first[t[0]].append(t)
    pairs = []
    for bucket in by_first.values():
        bucket.sort(key=lambda t: (len(t), t))
        for i in range(len(bucket)):
            a = bucket[i]
            for b in bucket[i + 1:]:
                if len(b) - len(a) > 2:
                    break
                if _same_numbered_family(a, b):
                    continue
                d = _lev(a, b)
                if 0 < d <= 2:
                    pairs.append((d, a, b))
    pairs.sort()
    return pairs


_NUM_FAMILY_RE = re.compile(r"^(.+?)[-_]?(\d{1,3})$")


def _same_numbered_family(a: str, b: str) -> bool:
    ma = _NUM_FAMILY_RE.fullmatch(a)
    mb = _NUM_FAMILY_RE.fullmatch(b)
    if not ma or not mb:
        return False
    return ma.group(1).rstrip("-_") == mb.group(1).rstrip("-_") \
        and ma.group(2) != mb.group(2)


def _suggest_tags(vocab2: Counter, meta: dict, head: str) -> list:
    """Suggest existing corpus tags (use >= 2 only) for an untagged file, by
    word overlap with its frontmatter prose + body head.  Suggest-only: the
    agent proposes, Ryan confirms (spec: Error and warning taxonomy); never auto-applied."""
    if not vocab2:
        return []
    prose = " ".join(str(meta.get(k, "")) for k in
                     ("title", "description", "logline", "session"))
    words = set(_WORD_RE.findall((prose + " " + head).lower()))
    scored = []
    for tag, cnt in vocab2.items():
        parts = [p for p in re.split(r"[^a-z0-9]+", tag) if len(p) >= 3]
        if not parts:
            continue
        hits = sum(1 for p in parts if p in words)
        if hits and hits * 2 >= len(parts):
            scored.append((hits / len(parts), cnt, tag))
    scored.sort(key=lambda t: (-t[0], -t[1], t[2]))
    return [t for _, _, t in scored[:_SUGGEST_TOP]]


def run_corpus(roots: dict, *, strict: bool = False,
               label: str = "corpus") -> int:
    """Corpus check (register 21): every deck under the declared roots gets
    check_file() (full register, model checks 1-16/18/28 + parser-enforced
    22-26); deck-slug collisions (check 5) fire once across the root; shared
    banks get a health sweep; OKF concept files (decks + wiki) feed the tag
    drift / coverage reports (spec: Error and warning taxonomy).  Reads only — never writes into any
    content root.  Deterministic: same roots, same output."""
    found = discover_corpus(roots)
    decks = found["decks"]
    concepts = found["concepts"]
    banks = found["banks"]

    print(f"animatic corpus — {label}")
    print(f"roots     : decks={len(roots.get('decks', []))} "
          f"concepts={len(roots.get('concepts', []))} "
          f"banks={len(roots.get('banks', []))}")
    print(f"decks     : {len(decks)} found — per-deck check_file() (checks "
          f"1-16, 18 model, 22-29); artifact asserts 17/18 live in the T10 "
          f"golden suite where a real build exists")

    deck_results = []
    for p in decks:
        report = check_file(p, strict=strict)
        deck_results.append((p, report))

    crep = Report(source="corpus")
    check_5_deck_slug_collisions(decks, crep)
    for p in banks:
        root = next((r for r in [Path(x) for x in roots.get("decks", [])]
                     if str(p).startswith(str(r))), None)
        label_b = _rel_label(root, p) if root is not None else p.name
        _sweep_bank(p, label_b, crep)

    # -- per-deck verdicts ---------------------------------------------------
    n_pass = 0
    for p, report in deck_results:
        rel = _rel_label(_root_of(p, roots), p)
        counts = Counter(f.severity for f in report.findings)
        if report.parse_error:
            counts[FATAL] += 1
        ok = report.exit_code == 0
        n_pass += 1 if ok else 0
        verdict = "PASS" if ok else "FAIL"
        line = (f"deck  {rel:<52} {verdict}  "
                f"fatal {counts[FATAL]} · warning {counts[WARNING]} · "
                f"info {counts[INFO]} · report {counts[REPORT]}")
        print(line)
        if not ok:
            if report.parse_error:
                print(f"  fatal    parse error: {report.parse_error}")
            for f in report.sorted():
                if f.severity == FATAL or (strict and f.severity == WARNING):
                    print("  " + f.render())
    print()

    if crep.findings:
        print("corpus    : cross-deck + bank findings")
        for f in crep.sorted():
            print(f.render())
        print()

    # -- tag drift + coverage (spec: Error and warning taxonomy, report taxonomy — never exit) ------
    tag_files = []          # (label, tags, meta, head)
    for p in decks:
        meta, head = _frontmatter_meta(p)
        if meta is not None:
            tag_files.append((_rel_label(_root_of(p, roots), p),
                              _meta_tags(meta), meta, head))
    for p in concepts:
        meta, head = _frontmatter_meta(p)
        if meta is not None:
            tag_files.append((_rel_label(_root_of(p, roots), p),
                              _meta_tags(meta), meta, head))
    tag_files.sort(key=lambda t: t[0])

    vocab: Counter = Counter()
    for _, tags, _, _ in tag_files:
        for t in tags:
            vocab[t] += 1
    untagged = [(label, meta, head) for label, tags, meta, head in tag_files
                if not tags]
    vocab2 = Counter({t: c for t, c in vocab.items() if c >= 2})
    n_single = sum(1 for c in vocab.values() if c == 1)

    print(f"tags      : {len(tag_files)} concept file(s) · "
          f"{len(vocab)} distinct tags · {sum(vocab.values())} uses · "
          f"{n_single} single-use")
    if vocab:
        top = ", ".join(f"{t}({vocab[t]})"
                        for t, _ in vocab.most_common(15))
        print(f"  top      : {top}")
    pairs = _near_miss_pairs(vocab)
    if pairs:
        print(f"  drift    : {len(pairs)} near-miss pair(s) "
              f"(levenshtein <= 2):")
        for d, a, b in pairs[:_MAX_PAIR_ROWS]:
            print(f"    {a} ~ {b}   [{vocab[a]} vs {vocab[b]} use(s)]")
        if len(pairs) > _MAX_PAIR_ROWS:
            print(f"    … and {len(pairs) - _MAX_PAIR_ROWS} more")
    else:
        print("  drift    : no near-miss pairs — vocabulary is clean")
    if untagged:
        print(f"coverage  : {len(untagged)} untagged concept file(s) — "
              f"suggest-only, never auto-applied (spec: Error and warning taxonomy):")
        for label, meta, head in untagged[:_MAX_COVERAGE_ROWS]:
            sugg = _suggest_tags(vocab2, meta, head)
            line = f"    {label}"
            if sugg:
                line += f"  suggest: {', '.join(sugg)}"
            print(line)
        if len(untagged) > _MAX_COVERAGE_ROWS:
            print(f"    … and {len(untagged) - _MAX_COVERAGE_ROWS} more")
    else:
        print("coverage  : every concept file is tagged")
    print()

    crep_exit = crep.exit_code
    code = 1 if any(report.exit_code for _, report in deck_results) \
        else crep_exit
    print(f"corpus summary: {n_pass}/{len(decks)} decks passed · "
          f"banks {len(banks)} · exit {code}"
          + ("  (warnings fatal under --strict)" if strict else ""))
    return code


def _root_of(path: Path, roots: dict) -> Path:
    """The declared root that contains `path` (longest-prefix win); falls
    back to path.parent.parent so labels stay stable for odd layouts."""
    candidates = [Path(r) for r in (roots.get("decks", [])
                                    + roots.get("concepts", []))]
    best = None
    for r in candidates:
        if str(path).startswith(str(r)):
            if best is None or len(str(r)) > len(str(best)):
                best = r
    return best if best is not None else Path(path).parent.parent


def corpus_config_path() -> Path:
    return Path(__file__).resolve().parent / CORPUS_CONFIG


def load_corpus_config() -> Optional[dict]:
    """{decks: [Path], concepts: [Path], banks: [Path]} from corpus.yaml.
    None when the file is absent (the --corpus ROOT form needs no config)."""
    p = corpus_config_path()
    if not p.is_file():
        return None
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        data = {}
    if not isinstance(data, dict):
        data = {}
    roots = {}
    for key in ("decks", "concepts", "banks"):
        vals = data.get(key) or []
        roots[key] = [Path(str(v)).expanduser().resolve()
                      for v in vals
                      if isinstance(v, str) and str(v).strip()]
    return roots


def corpus_main(root: Optional[str] = None, *, strict: bool = False) -> int:
    """--corpus driver: no ROOT -> corpus.yaml content roots; ROOT -> that
    directory scanned as one decks + concepts + banks root (the acceptance
    form: `python3 build.py --corpus <root>` / `check.py --corpus <root>`)."""
    if root is not None:
        p = Path(root).expanduser().resolve()
        if not p.is_dir():
            print(f"check.py: error: corpus root not found: {p}",
                  file=sys.stderr)
            return 2
        roots = {"decks": [p], "concepts": [p], "banks": []}
        label = f"root {p}"
    else:
        cfg = load_corpus_config()
        if cfg is None:
            print(f"check.py: error: no {CORPUS_CONFIG} beside check.py "
                  f"({corpus_config_path()}) — create it from the template or "
                  f"pass --corpus ROOT", file=sys.stderr)
            return 2
        roots = cfg
        label = f"{CORPUS_CONFIG} ({corpus_config_path()})"
    missing = sorted({str(x) for key in ("decks", "concepts", "banks")
                      for x in roots[key] if not x.exists()})
    usable = {}
    for key in ("decks", "concepts", "banks"):
        usable[key] = [x for x in roots[key] if x.exists()]
    if not any(usable.values()):
        print(f"check.py: error: no usable corpus root under {label} — "
              f"missing: {', '.join(missing) or 'none declared'}",
              file=sys.stderr)
        return 2
    if missing:
        print(f"warn      : corpus root(s) missing, skipped: "
              f"{', '.join(missing)}", file=sys.stderr)
    return run_corpus(usable, strict=strict, label=label)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="check.py",
        description="animatic deterministic check suite (spec: Verification/Error and warning taxonomy)")
    ap.add_argument("talkfiles", nargs="*", metavar="TALKFILE",
                    help="talkfile(s) to check (≥2 enables the cross-deck "
                         "slug-collision check)")
    ap.add_argument("--strict", action="store_true",
                    help="make warnings fatal (pre-delivery checks, spec: Error and warning taxonomy)")
    ap.add_argument("--cues", metavar="JSON",
                    help="also check a built cues.json (register checks "
                         "17 + 18 artifact assertions)")
    ap.add_argument("--corpus", nargs="?", const="__config__", metavar="ROOT",
                    help="corpus mode (check 21): with ROOT, scan that "
                         "directory as one decks+concepts+banks root; "
                         "without, use the corpus.yaml content roots.  "
                         "Exclusive with TALKFILE and --cues.")
    ap.add_argument("--register", action="store_true",
                    help="print the canonical 1-28 check register and exit")
    args = ap.parse_args(argv)

    if args.register:
        print(f"{'#':<3} {'taxonomy':<8} {'rule':<56} status")
        print("-" * 100)
        for num, rule, sev, status in REGISTER:
            print(f"{num:<3} {sev:<8} {rule:<56} {status}")
        print()
        print("Deferred rows:")
        for num in sorted(DEFERRED):
            print(f"  check {num}: {DEFERRED[num]}")
        return 0

    if args.corpus is not None:
        if args.talkfiles:
            ap.error("--corpus is exclusive with TALKFILE arguments")
        if args.cues:
            ap.error("--corpus is exclusive with --cues (artifact checks "
                     "live in the golden suite, T10)")
        root = None if args.corpus == "__config__" else args.corpus
        return corpus_main(root, strict=args.strict)

    files = [Path(a).expanduser() for a in args.talkfiles]
    if not files:
        ap.print_usage(sys.stderr)
        print("check.py: error: at least one TALKFILE is required", file=sys.stderr)
        return 2
    missing = [f for f in files if not f.is_file()]
    if missing:
        for f in missing:
            print(f"check.py: error: talkfile not found: {f}", file=sys.stderr)
        return 2
    cues_path = Path(args.cues).expanduser() if args.cues else None
    if cues_path is not None and not cues_path.is_file():
        print(f"check.py: error: cues.json not found: {cues_path}",
              file=sys.stderr)
        return 2

    code = 0
    for i, f in enumerate(files):
        report = check_file(f, strict=args.strict,
                            extra_files=tuple(files),
                            cues_path=cues_path)
        print(report.render())
        if i < len(files) - 1:
            print()
        if report.exit_code:
            code = 1
    print(DEFERRED_LINE)
    return code


if __name__ == "__main__":
    sys.exit(main())
