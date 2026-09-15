"""mediaresolve.py — extensionless slug -> media reference.

Resolution order (docs/media-pipeline.md):
  1. deck `media/cards.yaml`        — per-visual card: type, status, alt, credit,
                                     licence, brief.  A card's `approved:`,
                                     `file:` or `outputs[]` entries, when
                                     present, declare its sign-off files.
                                     Declared paths are DECK-relative
                                     (`media/<slug>/...`) and are tried in that
                                     order, first existing file wins.
  2. deck `media/` dir              — `media/<slug>.<ext>` directly, or
                                     `media/<slug>/attempts/<slug>-a<N>.<ext>`
                                     (gen-log convention).  When the card lists
                                     no approved output, the highest attempt
                                     number is the current state.
  3. shared `_media/library.yaml`   — sibling of the deck dir; cross-talk reuse,
                                     entries carry an explicit `file:` path.

  4. explicit `--media-remap` stand-ins — a real file standing in for a
     slug whose art is still brief/to-find/prompting (style tests, early
     drafts).  Last in order ON PURPOSE: when real art lands in the deck
     media dir or library, it wins and the stand-in evaporates.  Card
     metadata (credit/licence/alt) is untouched; refs carry source
     "standin" so the manifest audit stays honest.

When nothing resolves, the slug becomes a PLACEHOLDER (found=False) with the
card's type/status carried through for the renderer.  The script never knows
about file formats; the resolver is the only place extensions exist.

Media found outside this repo (the TPL instance) is REFERENCED by absolute
path, never copied: reads stay read-only, per the ticket constraint.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import shutil
import warnings

import re

import yaml

MEDIA_EXTS = {
    ".mp4": "video", ".webm": "video", ".mov": "video", ".m4v": "video",
    ".webp": "image", ".png": "image", ".jpg": "image", ".jpeg": "image",
    ".gif": "image", ".svg": "image",
}
VIDEO_EXTS = {e for e, t in MEDIA_EXTS.items() if t == "video"}


@dataclass
class MediaRef:
    slug: str
    type: str = "unknown"              # image | video | chart | composite | live | unknown
    status: str = "missing"            # card status, else 'missing'
    found: bool = False
    file: Optional[str] = None         # absolute path when found
    source: str = "none"               # cards | deckdir | library | standin | live
    alt: str = ""
    credit: str = ""
    licence: str = ""
    note: str = ""                     # card brief first line / library note
    reason: str = ""                   # why not found (placeholder labelling)
    live: bool = False                 # runtime window capture (card `type: live`)
    poster: Optional[str] = None       # live only: the still the handout prints


@dataclass
class MediaResolver:
    talk_dir: Path
    meta: dict
    cards: list = field(default_factory=list)
    library: list = field(default_factory=list)
    remap: dict = field(default_factory=dict)      # slug -> Path (stand-ins)
    cards_path: Optional[Path] = None
    library_path: Optional[Path] = None
    published: dict = field(default_factory=dict)  # slug -> out-root-relative path
    declared_missing: list = field(default_factory=list)
    # check-10 register: (slug, declared-path) pairs whose file does not exist.
    # Filled in __post_init__; kept for the future `animatic check` runner.

    @classmethod
    def from_talk(cls, talk) -> "MediaResolver":
        talk_dir = Path(talk.source).parent if talk.source else Path.cwd()
        return cls(talk_dir=talk_dir, meta=talk.meta)

    def __post_init__(self):
        media_dir_name = str(self.meta.get("media", "media"))
        self.media_dir = self.talk_dir / media_dir_name
        self.cards_path = self.media_dir / "cards.yaml"
        if self.cards_path.is_file():
            try:
                loaded = yaml.safe_load(self.cards_path.read_text(encoding="utf-8"))
                if isinstance(loaded, list):
                    self.cards = loaded
            except yaml.YAMLError as exc:
                self.cards = []
                self._error = f"bad cards.yaml: {exc}"
        # shared library: sibling `_media/library.yaml` of the deck dir
        lib = self.talk_dir.parent / "_media" / "library.yaml"
        if lib.is_file():
            try:
                loaded = yaml.safe_load(lib.read_text(encoding="utf-8"))
                if isinstance(loaded, list):
                    self.library = loaded
                    self.library_path = lib
            except yaml.YAMLError:
                pass

        # check 10 (missing-checks register, frontier-review Part 4): every
        # card-declared path (`approved:`/`file:`/`outputs[]`) must resolve to
        # an existing file.  Warn naming the card + path; the finding also
        # stays registered so `animatic check` can report it later.  Runs over
        # ALL cards — a broken declared path on an unreferenced card is a
        # defect, not silent authoring info.
        for c in self.cards:
            if not isinstance(c, dict) or not c.get("slug"):
                continue
            slug = c["slug"]
            for raw in self._declared_paths(c):
                if not (self.talk_dir / raw).is_file():
                    self.declared_missing.append((str(slug), raw))
                    warnings.warn(
                        "check 10: card "
                        f"'{slug}' declares path that does not resolve: {raw} "
                        f"(joined to deck dir {self.talk_dir})",
                        stacklevel=3)  # past __post_init__ + dataclass __init__

    # -- lookups -------------------------------------------------------------

    def card_for(self, slug: str) -> Optional[dict]:
        for c in self.cards:
            if isinstance(c, dict) and c.get("slug") == slug:
                return c
        return None

    def library_entry_for(self, slug: str) -> Optional[dict]:
        for e in self.library:
            if isinstance(e, dict) and e.get("slug") == slug:
                return e
        return None

    # -- deck media dir ------------------------------------------------------

    def _deckdir_file(self, slug: str) -> Optional[Path]:
        """media/<slug>.<ext> direct file."""
        for ext in MEDIA_EXTS:
            p = self.media_dir / f"{slug}{ext}"
            if p.is_file():
                return p
        return None

    def _attempts_file(self, slug: str) -> Optional[Path]:
        """media/<slug>/attempts/<slug>-a<N>.<ext> — highest N wins."""
        import re

        adir = self.media_dir / slug / "attempts"
        if not adir.is_dir():
            return None
        pat = re.compile(rf"^{re.escape(slug)}-a(\d+)\.([a-z0-9]+)$")
        best: tuple[int, Optional[Path]] = (-1, None)
        for p in adir.iterdir():
            if not p.is_file():
                continue
            m = pat.match(p.name)
            if m and ("." + m.group(2)) in MEDIA_EXTS:
                n = int(m.group(1))
                if n > best[0]:
                    best = (n, p)
        return best[1]

    # -- resolution ----------------------------------------------------------

    def _declared_paths(self, card: dict) -> list:
        """Card-declared media paths in spec: Media order: `approved:` then
        `file:` then `outputs[]`.  Paths are DECK-relative strings (e.g.
        `media/<slug>/attempts/<slug>-a2.mp4`); existence is the caller's
        check.  Non-string / empty values are skipped.  A live card's
        `poster:` is declared like any other path, so a poster that names a
        file which is not there warns (check 10) instead of silently
        vanishing from the handout."""
        out = []
        for key in ("approved", "file", "poster"):
            v = card.get(key)
            if isinstance(v, str) and v:
                out.append(v)
        outs = card.get("outputs")
        if isinstance(outs, list):
            out.extend(v for v in outs if isinstance(v, str) and v)
        return out

    def _live_ref(self, slug: str, card: dict) -> MediaRef:
        """`type: live` — a runtime window capture, not a file.

        Nothing resolves on disk and nothing should: the present view hosts a
        capture the presenter starts in the browser (`getDisplayMedia`, spec:
        docs/live-capture.md).  `found=True` is correct rather than a lie — the
        screen is complete and the renderer emits the capture host, never a
        placeholder — and `source='live'` keeps the manifest honest that no
        file exists.  `poster:` is the one optional disk artifact: the still
        the document view prints and the fallback the presenter shows when
        capture is unavailable.
        """
        poster = None
        raw = card.get("poster")
        if isinstance(raw, str) and raw:
            p = self.talk_dir / raw
            if p.is_file():
                poster = str(p.resolve())
        ref = MediaRef(
            slug=slug,
            type="live",
            status=str(card.get("status") or "live"),
            found=True,
            file=None,
            source="live",
            alt=str(card.get("alt", "") or ""),
            credit=str(card.get("credit", "") or ""),
            licence=str(card.get("licence", "") or ""),
            live=True,
            poster=poster,
        )
        brief = card.get("brief")
        if isinstance(brief, str) and brief.strip():
            ref.note = brief.strip().splitlines()[0]
        elif isinstance(brief, list) and brief:
            ref.note = str(brief[0])
        return ref

    def _resolve(self, slug: str) -> MediaRef:
        card = self.card_for(slug)
        ctype = card.get("type") if card else None
        cstatus = card.get("status") if card else None

        # 0) a live card never looks for a file: the screen IS the capture
        #    host, and the only disk artifact it can declare is a poster.
        if card and str(ctype or "").lower() == "live":
            return self._live_ref(slug, card)

        # 1) card-declared paths — spec: Media order: `approved:` then `file:`
        #    then `outputs[]`, first existing file wins.  Declared paths are
        #    deck-relative (`media/<slug>/attempts/<slug>-a<N>.<ext>`), so they
        #    join onto the DECK dir, never media_dir (media_dir / "media/..."
        #    double-prefixes — the rainforest-canopy bug).  If none resolves,
        #    the deck-dir / library / stand-in stages below still apply.
        if card:
            for raw in self._declared_paths(card):
                p = self.talk_dir / raw
                if p.is_file():
                    return self._make(slug, card, p, "cards")

        # 2) deck media dir
        p = self._deckdir_file(slug)
        if p is not None:
            return self._make(slug, card, p, "deckdir")
        p = self._attempts_file(slug)
        if p is not None:
            return self._make(slug, card, p, "deckdir")

        # 3) shared library
        entry = self.library_entry_for(slug)
        if entry and entry.get("file") and self.library_path is not None:
            p = self.library_path.parent / str(entry["file"])
            if p.is_file():
                ref = self._make(slug, card, p, "library")
                if not ref.alt and entry.get("note"):
                    ref.note = entry["note"]
                return ref

        # 4) explicit stand-in remap (--media-remap). Deliberately last:
        #    real art from deckdir/library above always wins, so a stand-in
        #    disappears the moment the real file lands.
        p = self.remap.get(slug)
        if p is not None and p.is_file():
            return self._make(slug, card, p, "standin")

        # placeholder
        ref = MediaRef(
            slug=slug,
            type=ctype or "unknown",
            status=cstatus or "missing",
            found=False,
            alt=card.get("alt", "") if card else "",
            credit=card.get("credit", "") if card else "",
            licence=card.get("licence", "") if card else "",
        )
        reasons = []
        if card is not None:
            declared = self._declared_paths(card)
            if declared or cstatus == "have":
                missing = [raw for raw in declared
                           if not (self.talk_dir / raw).is_file()]
                if missing:
                    # check-10 evidence: name the declared paths verbatim so
                    # the manifest audit shows why nothing card-declared won.
                    reasons.append(
                        "card "
                        f"'{slug}' declares path(s) that do not resolve: "
                        + ", ".join(repr(r) for r in missing))
                else:
                    reasons.append(
                        "card "
                        f"'{slug}' is status '{cstatus}' but no file "
                        f"resolves under {self.media_dir}")
            else:
                reasons.append(
                    "card "
                    f"'{slug}' has no approved output (status: "
                    f"{cstatus or '?'})")
        else:
            reasons.append(f"no card for '{slug}' in {self.cards_path or 'cards.yaml'}")
            # Unknown-first-token hint (report Media / register check 25):
            # a single-word, cardless slug may be a role or flag typo that
            # the token-position rule turned into a media slug (`hero`).
            # Hyphenated/digit slugs cannot be roles or flags, so only the
            # word-shaped ones carry the hint.
            if re.fullmatch(r"[a-z]+", slug):
                reasons.append(
                    f"if {slug!r} was meant as a role or flag, it is neither")
        reasons.append("no file under deck media dir")
        if not self.library_entry_for(slug):
            reasons.append("not in shared library")
        ref.reason = "; ".join(reasons)
        if card and card.get("brief"):
            brief = card["brief"]
            if isinstance(brief, str) and brief.strip():
                ref.note = brief.strip().splitlines()[0]
            elif isinstance(brief, list) and brief:
                ref.note = str(brief[0])
        return ref

    def resolve(self, slug: str) -> MediaRef:
        """resolve() + publication override: once media has been published to
        out/_media, refs carry the out-root-relative path instead of the
        absolute source path, so decks render from anywhere (file://, http,
        an sftp mount).  A live ref has no file; its poster (when it has one)
        is published under `<slug>-poster.<ext>` and swapped in the same way,
        so the handout travels with the deck folder."""
        ref = self._resolve(slug)
        if ref.found and slug in self.published:
            ref.file = self.published[slug]
        if ref.live:
            published_poster = self.published.get(slug + "-poster")
            if published_poster:
                ref.poster = published_poster
        return ref

    def publish(self, out_root: Path, slugs: list) -> None:
        """Copy found media for `slugs` into out_root/_media/<slug><ext> and
        record out-root-relative paths. The packaging decision: a deck is a
        portable folder (html + _media side by side), not a bundle of
        absolute machine paths. Idempotent: same bytes every build."""
        media_dir = Path(out_root) / "_media"
        media_dir.mkdir(parents=True, exist_ok=True)
        for slug in slugs:
            if slug in self.published or (slug + "-poster") in self.published:
                continue
            ref = self._resolve(slug)
            if ref.live:
                # the poster is the only file a live screen contributes
                if not ref.poster:
                    continue
                ext = Path(ref.poster).suffix.lower() or ".bin"
                dst = media_dir / f"{slug}-poster{ext}"
                shutil.copyfile(ref.poster, dst)
                self.published[slug + "-poster"] = str(
                    Path("_media") / f"{slug}-poster{ext}")
                continue
            if not (ref.found and ref.file):
                continue
            ext = Path(ref.file).suffix.lower() or ".bin"
            dst = media_dir / f"{slug}{ext}"
            shutil.copyfile(ref.file, dst)
            self.published[slug] = str(Path("_media") / f"{slug}{ext}")

    def _make(self, slug: str, card: Optional[dict], path: Path, source: str) -> MediaRef:
        ext = path.suffix.lower()
        ref = MediaRef(
            slug=slug,
            type=(card.get("type") if card else None) or MEDIA_EXTS.get(ext, "file"),
            status=(card.get("status") if card else None) or "have",
            found=True,
            file=str(path.resolve()),
            source=source,
            alt=card.get("alt", "") if card else "",
            credit=card.get("credit", "") if card else "",
            licence=card.get("licence", "") if card else "",
        )
        if card and card.get("brief"):
            brief = card["brief"]
            if isinstance(brief, str) and brief.strip():
                ref.note = brief.strip().splitlines()[0]
            elif isinstance(brief, list) and brief:
                ref.note = str(brief[0])
        return ref

    def unreferenced_cards(self, referenced: set) -> list:
        """Card slugs never referenced by any shot (authoring info)."""
        return [str(c["slug"]) for c in self.cards
                if isinstance(c, dict) and c.get("slug") not in referenced]
