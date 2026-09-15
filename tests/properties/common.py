"""Shared helpers for the T10 golden/property suite."""

from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

from talkparse import FOOTNOTE_REF_RE, slugify

# A machine-local path in any emitted artifact is a defect (spec: Outputs,
# register check 17).  Same regex family as check.py's walk.
ABS_PATH_RE = re.compile(r"(?:/home/|/Users/|/root/|/tmp/)|^[A-Za-z]:[\\/]")
EM_DASH = "\u2014"
COMMENT_SPAN_RE = re.compile(r"<!--.*?-->", re.DOTALL)

KINDS = ("black", "media", "stat", "lower", "credits", "card")
TEXT_ENTRY_KINDS = ("heading", "quote", "source", "list", "stat", "lower", "credits",
                    "paraphrase")


@dataclass
class Fixture:
    """One built fixture profile: the talkfile, its build output, its goldens."""

    talkfile: Path              # tests/fixtures/<rel>/<name>.talk.md (or talk.md)
    out: Path                   # build output dir (fresh per run)
    expected_dir: Path          # tests/expected/<...>
    profile: str = "base"       # 'base' or a profile name (e.g. 'standin')
    remap: Optional[Path] = None
    meta: dict = field(default_factory=dict)
    source_text: str = ""

    # -- conveniences ------------------------------------------------------
    @property
    def deck_dir(self) -> Path:
        return self.talkfile.parent

    def cues(self) -> dict:
        return json.loads((self.out / "cues.json").read_text(encoding="utf-8"))

    def manifest(self) -> dict:
        return json.loads(
            (self.out / "media-manifest.json").read_text(encoding="utf-8"))

    def nav(self) -> dict:
        return json.loads((self.out / "nav.json").read_text(encoding="utf-8"))

    @property
    def slug(self) -> str:
        return slugify(str(self.meta.get("slug") or self.talkfile.stem))

    @property
    def tolerant(self) -> bool:
        """Fixture expects parser warnings by design (frontmatter
        `test-expect: warned`); the goldens pin the exact warnings."""
        return str(self.meta.get("test-expect", "")).strip() == "warned"


def err(errors: list, msg: str) -> None:
    errors.append(msg)


def load_meta_source(talkfile: Path) -> tuple[dict, str]:
    """Frontmatter meta + full source text of a talkfile."""
    text = talkfile.read_text(encoding="utf-8")
    meta: dict = {}
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            block = text[3:end].strip()
            meta = yaml.safe_load(block) or {}
            if not isinstance(meta, dict):
                meta = {}
    return meta, text


def body_lines(source_text: str) -> list:
    """The body lines exactly as the parser numbers them.

    nav.json ranges are 1-based source lines *of the body* (frontmatter
    stripped) — the same numbering every warning uses.  White-box on purpose:
    the property must read the source through the parser's own split, not a
    lookalike, or a frontmatter change would silently skew every assertion.
    Line k of a range is body_lines(text)[k - 1].
    """
    from talkparse import _lex_frontmatter
    _, lines = _lex_frontmatter(source_text, "<fixture>")
    return lines


def derive_sources(meta: dict, source_text: str) -> list:
    """The citation list a build must emit: every `[^id]` reference in the
    body (comments excluded), first-appearance order, keyed into the
    `sources:` registry; ids with no registry value never emit (check 28).
    Mirrors render.cited_sources over the raw source so a regression in the
    emission path shows as a property failure, not just a stale golden."""
    registry = meta.get("sources")
    if not isinstance(registry, dict):
        return []
    body = source_text
    if source_text.startswith("---"):
        end = source_text.find("\n---", 3)
        if end != -1:
            body = source_text[end + 4:]
    body = COMMENT_SPAN_RE.sub(" ", body)
    out = []
    seen = set()
    for m in FOOTNOTE_REF_RE.finditer(body):
        rid = m.group(1)
        if rid in seen:
            continue
        seen.add(rid)
        value = registry.get(rid)
        if value is not None and str(value).strip():
            out.append({"id": rid, "source": str(value)})
    return out


def derived_slug_set(cues: dict) -> list:
    """Ordered distinct media slugs referenced by shots, from cues.json
    (media shot = a shot carrying a slug)."""
    out = []
    seen = set()
    for c in cues.get("cues", []):
        for s in c.get("shots") or []:
            slug = s.get("slug")
            if slug and slug not in seen:
                seen.add(slug)
                out.append(slug)
    return out


def first_cue_of(cues: dict, slug: str) -> Optional[str]:
    for c in cues.get("cues", []):
        for s in c.get("shots") or []:
            if s.get("slug") == slug:
                return c.get("id")
    return None


def walk_strings(node):
    """Yield every string leaf of a JSON-shaped object (used for the
    no-machine-path scans)."""
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for v in node.values():
            yield from walk_strings(v)
    elif isinstance(node, list):
        for v in node:
            yield from walk_strings(v)


def text_entries(cue: dict) -> list:
    """Plain text payloads of a cue's screen_text entries (for hygiene
    scans): list items count as their own text pieces."""
    out = []
    for t in cue.get("screen_text") or []:
        if "text" in t:
            out.append(t["text"])
        for it in t.get("items") or []:
            out.append(it)
    return out
