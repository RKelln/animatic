"""check.py — animatic deterministic check suite (T08).

One talkfile in, one exit code out.  Deterministic: same input, same findings,
same order, same exit code.  No LLM, no network, no writes outside the caller's
out dir.

Run::

    python3 check.py TALKFILE [TALKFILE ...] [--strict] [--cues FILE] [--register]

Exit codes:
    0  clean — no fatal finding (warnings are fine; a deck must always build)
    1  a fatal finding (or, under --strict, any warning), or a parse error
    2  usage error (missing/invalid talkfile, unknown flag)

Severity taxonomy (spec §10 as the register defines it):

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
              (14), licence-before-public-use (16).  Not diagnostics: a deck
              carrying them is not defective.

Register canonicalization (engine-decision §9/§10: "register canonicalization
is T08").  The 1-28 register table with owner + status lives in REGISTER below
and prints with --register.  Rows implemented here: 1-9, 11-16, 18 (model
assert + artifact assert), 28.  Rows enforced by the parser/resolver ships
from earlier tickets: 10 (mediaresolve), 17 (render, T02), 22-26 (talkparse),
27 (T07 fixture).  Explicitly deferred with reason: 19 (est_seconds lands with
T15's timing module; T15's file scope includes check.py), 20 (the --variant
build lands with T14; T14's file scope includes check.py), 21 (the corpus
harness needs a config-declared content root and the --corpus flag, T11).

Importable by build.py and a future `animatic` wrapper (there is no animatic
CLI today).  check_file() is the per-deck seam T11's --corpus reuses; the
suite never edits talkparse.py/render.py and never writes outside /tmp or the
caller's chosen output.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

import talkparse
from mediaresolve import MEDIA_EXTS, MediaResolver

# ---------------------------------------------------------------------------
# Severity + register
# ---------------------------------------------------------------------------

FATAL = "fatal"
WARNING = "warning"
INFO = "info"
REPORT = "report"
_SEV_ORDER = {FATAL: 0, WARNING: 1, INFO: 2, REPORT: 3}

# Spec anchors used by several checks.
ROLE_WORDS = set(talkparse.ROLES) | {talkparse.BLACK_ROLE}   # stat/lower/credits/black
SLUG_RE = re.compile(r"^[a-z0-9-]{3,40}$")                    # §6: charset + length
PERSONAL_PATH_RE = re.compile(r"^/(?:[^/]+/)+[^/]+$")         # absolute, no scheme
FOOTNOTE_REF_RE = talkparse.FOOTNOTE_REF_RE
COMMENT_SPAN_RE = re.compile(r"<!--.*?-->", re.DOTALL)
GENLOG_HEADER_RE = re.compile(
    r"^##\s+(\S+)\s*·\s*([a-z0-9][a-z0-9-]*)\s*·\s*a(\d+)\s*$")

# Canonical register (work-spec §5 coverage table + report Part 4/6 additions).
# status: implemented (this file) | enforced (owner ticket) | fixture |
#         deferred (owner ticket).
REGISTER = [
    (1,  "duplicate slug within one cards.yaml",                     WARNING, "implemented"),
    (2,  "media slug charset/length (§6 rule)",                      WARNING, "implemented"),
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
    (19, "sum(est_seconds) vs frontmatter dur divergence",           REPORT,  "deferred: T15"),
    (20, "variant build emits included/excluded manifest",           REPORT,  "deferred: T14"),
    (21, "corpus: all decks parse/build/pass",                       REPORT,  "deferred: T11"),
    (22, "malformed Movement heading fatal",                         FATAL,   "enforced: talkparse.py (T05)"),
    (23, "nested parens warning",                                    WARNING, "enforced: talkparse.py (T06)"),
    (24, "attribution-shaped line with no quote warns",              WARNING, "enforced: talkparse.py (T06)"),
    (25, "no silent token drop in a shot comment",                   WARNING, "enforced: talkparse.py (T05)"),
    (26, "no warning text contains 'line 0'",                        WARNING, "enforced: talkparse.py (T07); guard in check.py"),
    (27, "multi-line shot fixture",                                  WARNING, "fixture: tests/fixtures/constructs/multiline-shot.talk.md (T07)"),
    (28, "`[^id]` footnote with no sources: registry entry",         WARNING, "implemented"),
]

DEFERRED = {
    19: "check 19 needs est_seconds, which lands with T15's timing module "
        "(speech-rate constant, per-screen floors, timing.yaml); T15's file "
        "scope includes check.py and its acceptance fires this report on a "
        "deliberately divergent deck.",
    20: "check 20 needs the --variant build that emits the included/excluded "
        "manifest; that lands with T14 (dense renumbering + canonical remap), "
        "whose file scope includes check.py.",
    21: "check 21 needs a config-declared content root and the --corpus flag; "
        "that is T11, whose file scope is a check.py extension. T11 will drive "
        "this module's check_file() per deck.",
}


DEFERRED_LINE = ("deferred : check 19 -> T15 (est_seconds/timing), check 20 -> "
                 "T14 (variant manifest), check 21 -> T11 (corpus harness) — "
                 "full reasons under --register")


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
    """Mirror render.deck_slug: the slugified frontmatter slug (spec §2/§3.3)."""
    raw = str(talk.meta.get("slug", "") or Path(talk.source).stem)
    return talkparse.slugify(raw)


def slug_ok(slug: str) -> bool:
    """Spec §6: charset [a-z0-9-], 3-40 chars, no leading/trailing '-'.
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
    comment spans (shot directives and inert comments) and `[^id]:`
    definition shapes (receipts have no body-level definition form, §5)."""
    out = []
    in_comment = False
    for lineno, raw in enumerate(body_lines, start=1):
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
                       f"§6: unique within a deck); both cards at positions "
                       f"{seen[slug]} and {len(seen) + 1}")
        else:
            seen[slug] = len(seen) + 1


def check_2_slug_charset(talk, resolver, report: Report) -> None:
    for c in resolver.cards:
        if isinstance(c, dict) and c.get("slug") and not slug_ok(str(c["slug"])):
            report.add(2, WARNING,
                       f"card slug {str(c['slug'])!r} violates the slug rule "
                       f"[a-z0-9-], 3-40 chars, no leading/trailing '-' "
                       f"(spec §6) — a shot can never reference it "
                       f"(cards.yaml)")
    for e in resolver.library:
        if isinstance(e, dict) and e.get("slug") and not slug_ok(str(e["slug"])):
            report.add(2, WARNING,
                       f"library slug {str(e['slug'])!r} violates the slug "
                       f"rule [a-z0-9-], 3-40 chars, no leading/trailing '-' "
                       f"(spec §6) — a shot can never reference it "
                       f"(library.yaml)")
    # shot slugs: the token-position rule makes any bare first token a slug,
    # so a shot slug violating §6 is exactly the kind of typo to name.
    for s in talk.screens:
        for sh in s.shots:
            if sh.slug and not slug_ok(sh.slug):
                report.add(2, WARNING,
                           f"shot slug {sh.slug!r} violates the slug rule "
                           f"[a-z0-9-], 3-40 chars, no leading/trailing '-' "
                           f"(spec §6)", line=sh.line, screen=s.idx)


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
                           f"{surface} slug {slug!r} equals a role name or "
                           f"'black' — a shot token can never reference it "
                           f"(the tokenizer reads it as a role), so the "
                           f"visual is unreachable (spec §6/§10) ({where})")


def check_4_movements(talk, resolver, report: Report) -> None:
    seen = set()
    prev = None
    for m in talk.movements:
        idx = m.index
        if idx in seen:
            report.add(4, WARNING,
                       f"duplicate movement ordinal {idx} "
                       f"({m.label!r}) — two sections share one number "
                       f"(movement ordinals are presentation order, §3/§13)",
                       line=None)
        elif prev is not None and idx < prev:
            report.add(4, WARNING,
                       f"movement ordinal {idx} ({m.label!r}) follows "
                       f"{prev} — ordinals must be non-decreasing in file "
                       f"order (spec §3: movement ordinals are presentation "
                       f"order)")
        elif prev is not None and idx > prev + 1:
            report.add(4, INFO,
                       f"movement ordinal {idx} skips "
                       f"{', '.join(str(n) for n in range(prev + 1, idx))} — "
                       f"renumbering debris or a deleted movement (legal; "
                       f"renumber by the author, spec §13)")
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
                       f"collide across a content root (spec §2/§3.3)")


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
                           f"spec §7: a shot MUST NOT carry two fit= values",
                           line=sh.line, screen=s.idx)


def check_7_flags_nonfirst(talk, resolver, report: Report) -> None:
    for s in talk.screens:
        for sh in s.shots[1:]:
            if sh.flags:
                names = ", ".join(sorted(sh.flags))
                report.add(7, INFO,
                           f"flags on a non-first shot are ignored — "
                           f"slide-level and media flags are read from the "
                           f"screen's first shot only (spec §7 interaction "
                           f"table): {names}",
                           line=sh.line, screen=s.idx)


def check_8_flag_combos(talk, resolver, report: Report) -> None:
    for s in talk.screens:
        mshot = s.media_shot
        if mshot is None:
            continue
        flags = mshot.flags
        framed = "piece" in flags or flags.get("duo") is not None
        if not framed:
            continue
        framed_desc = "piece" if "piece" in flags else "duo (implies piece)"
        if flags.get("dim"):
            report.add(8, INFO,
                       f"dim is ignored on {framed_desc} — a full-zone "
                       f"scrim behind a framed object would paint a box "
                       f"around it (spec §7 interaction table)",
                       line=mshot.line, screen=s.idx)
        if flags.get("kb"):
            report.add(8, INFO,
                       f"kb is not applied on {framed_desc} — the camera "
                       f"lens wraps full-bleed media only; a framed object "
                       f"has no lens (spec §7 interaction table)",
                       line=mshot.line, screen=s.idx)


def check_9_dup_overlay_roles(talk, resolver, report: Report) -> None:
    for s in talk.screens:
        roles = {}
        for sh in s.shots:
            if sh.role in talkparse.ROLES:
                roles.setdefault(sh.role, []).append(sh.line)
        for role, lines in sorted(roles.items()):
            if len(lines) > 1:
                report.add(9, WARNING,
                           f"more than one +{role} on one screen (shot lines "
                           f"{', '.join(str(n) for n in lines)}) — one "
                           f"overlay per role per screen; an unbounded stack "
                           f"is a slide trying to be three things "
                           f"(spec §4)",
                           screen=s.idx)


# ---------------------------------------------------------------------------
# Media pipeline checks (10-16)
# ---------------------------------------------------------------------------


def check_10_declared_paths(talk, resolver, report: Report) -> None:
    for slug, raw in resolver.declared_missing:
        report.add(10, WARNING,
                   f"card '{slug}' declares a path that does not resolve: "
                   f"{raw} (joined to deck dir; spec §6 order + §11 path "
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
                       f"builds, but nothing documents this media (spec §11)")


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
                               f"drop the note (spec §5 Tier B)",
                               line=b.line, screen=s.idx)


def _attempt_facts(media_dir: Path) -> tuple:
    """(files, log) — attempt numbers per slug from disk and gen-log.md.

    files: {slug: {n: relative-path}} for media/<slug>/attempts/<slug>-aN.ext
           (media extensions only — *.expanded.txt sidecars are diagnostics
           of the same attempt, not attempts).
    log:   {slug: [(n, log_line_no)]} from `## <date> · <slug> · a<N>` headers.
    """
    files = {}
    log = {}
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
            for lineno, raw in enumerate(lines, start=1):
                m = GENLOG_HEADER_RE.match(raw.strip())
                if m:
                    log.setdefault(m.group(2), []).append((int(m.group(3)),
                                                           lineno))
    return files, log


def check_13_14_attempts(talk, resolver, report: Report) -> None:
    media_dir = resolver.media_dir
    files, log = _attempt_facts(media_dir)
    log_present = (media_dir / "gen-log.md").is_file()
    for slug in sorted(set(files) | set(log)):
        fset = set(files.get(slug, {}))
        lset = {n for n, _ in log.get(slug, [])}
        for n in sorted(fset - lset):
            report.add(13, REPORT,
                       f"attempt file with no gen-log entry: "
                       f"{files[slug][n]} — archaeology drift (media/"
                       f"gen-log.md; spec §11 append-only)")
        for n in sorted(lset - fset):
            entry_lines = [ln for m, ln in log[slug] if m == n]
            report.add(13, REPORT,
                       f"gen-log entry with no attempt file on disk: "
                       f"{slug} a{n} (media/gen-log.md line "
                       f"{','.join(str(x) for x in entry_lines)}) — "
                       f"archaeology drift")
        # numbering: union must be contiguous 1..max
        union = sorted(fset | lset)
        if union:
            missing = [n for n in range(1, union[-1] + 1) if n not in union]
            if missing:
                report.add(14, REPORT,
                           f"attempt numbering gapped for '{slug}': seen "
                           f"{', '.join('a' + str(n) for n in union)} — "
                           f"missing {', '.join('a' + str(n) for n in missing)} "
                           f"(per-slug attempt numbers are monotonic, spec §11)")
        # non-monotonic in the log itself (append-only means a3 after a2)
        seen_in_log = []
        for n, _ in log.get(slug, []):
            if seen_in_log and n < seen_in_log[-1]:
                report.add(14, REPORT,
                           f"gen-log attempt numbers not monotonic for "
                           f"'{slug}': a{seen_in_log[-1]} followed by a{n} "
                           f"(gen-log.md is append-only; entries are never "
                           f"renumbered, spec §11)")
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
                       f"spec §11 (resolution is by file presence, never by "
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
    # check 17: no absolute / personal paths in any emitted artifact (§8 —
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
                   f"(spec §8: no emitted artifact may contain a "
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
                       f"position {first + 1} (spec §3.3/§8 — padding cliff "
                       f"past 99 screens with 2-digit ids)")


def check_18_model_ids(talk, resolver, report: Report) -> None:
    """Cue-id space must hold the deck: ids are `<slug>-NNN` (3-digit,
    §3.3) and lexically sort in presentation order up to 999 screens."""
    n = len(talk.screens)
    if n > 999:
        dslug = deck_slug(talk)
        report.add(18, FATAL,
                   f"{n} screens exceed the 3-digit cue-id space "
                   f"'{dslug}-NNN' — lexical sort diverges from ordinal "
                   f"past 999 (spec §3.3)")


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
                       f"nothing and no citation renders (spec §2/§5)")


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
        # check 26 guard: no warning text contains "line 0" (spec §10).
        if "line 0" in w:
            report.add(26, WARNING,
                       f"parser warning text contains 'line 0': {w!r} — "
                       f"every warning must name its real source line "
                       f"(spec §10)")


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
    check_28_footnotes(talk, resolver, source_text, report)
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
    return run_checks(talk, resolver, text, extra_files=extra_files,
                      cues_path=cues_path, report=report)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="check.py",
        description="animatic deterministic check suite (spec §9/§10)")
    ap.add_argument("talkfiles", nargs="*", metavar="TALKFILE",
                    help="talkfile(s) to check (≥2 enables the cross-deck "
                         "slug-collision check)")
    ap.add_argument("--strict", action="store_true",
                    help="make warnings fatal (pre-delivery checks, spec §10)")
    ap.add_argument("--cues", metavar="JSON",
                    help="also check a built cues.json (register checks "
                         "17 + 18 artifact assertions)")
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
