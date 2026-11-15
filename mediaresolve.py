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
  3. shared media, `_media/` beside the deck dir; cross-talk reuse:
       a. a `library.yaml` entry with a `file:` path (relative to `_media/`);
       b. a file named for the slug, `_media/<slug>.<ext>` or
          `_media/<slug>/<slug>.<ext>`.  No entry needed; the entry carries what
          a file cannot (alt, credit, licence, type, playback, `steps:`, `pool:`).
          Two matching files: the flat one, then MEDIA_EXTS order, with a
          check 50 warning.

  4. explicit `--media-remap` stand-ins — a real file standing in for a
     slug whose art is still brief/to-find/prompting (style tests, early
     drafts).  Last in order ON PURPOSE: when real art lands in the deck
     media dir or library, it wins and the stand-in evaporates.  Card
     metadata (credit/licence/alt) is untouched; refs carry source
     "standin" so the manifest audit stays honest.

Pool cards (card or shared-library entry `pool: <folder>`, deck-relative): one slug stands for a
folder of art.  `expand_pools()` runs after the parse and gives every use of
the slug its own concrete virtual slug (`<slug>--NN`, NN = use number in
document order); the resolver maps NN to a file by a seeded shuffle of the
folder that never repeats until every file has been used (then reshuffles,
never starting a cycle on the file that ended the last).  A `continue` screen
keeps its head's file.  Chosen at build time, so navigation cannot change it
and a rebuild gives identical bytes; `seed:` on the card re-rolls.
`pins: {id: file name}` on a pool card makes each id a slug that always
resolves to that file; pinned files are left out of the random draw.  `text: light|dark` on a pool
card is the default `text=` flag of every shot using the pool.

SECTION MEDIA.  A shot from a section (an include, or the quick-select shelf) is
registered in `MediaResolver.shared` by `expand_pools()` and resolves by stage 3
and the stand-in only: never the deck's cards.yaml or media/.  The library entry
is its card.  When the deck owns something of the same slug (a card, a pin, a
media file) the section's shot is renamed `<slug>--lib` first, so both can be
published, listed in the manifest and cued without meeting.  An unresolved slug
on a shelf screen is check 48 (`shelf_media_errors`); in an include it is a
placeholder.

When nothing resolves, the slug becomes a PLACEHOLDER (found=False) with the
card's type/status carried through for the renderer.  The script never knows
about file formats; the resolver is the only place extensions exist.

Media found outside this repo (in a deck's own folder) is REFERENCED by absolute
path, never copied: reads stay read-only, per the ticket constraint.

Playback (card `playback:`, video only; spec: Media pipeline contract):
  loop      the default: the video loops while its screen is up
  once      plays through once and holds its last frame; each arrival restarts it
  pingpong  forward then backward, looping.  Browsers cannot play video
            backwards reliably, so `publish()` bakes a forward+reverse copy with
            ffmpeg into `_media/<slug>-pingpong.mp4`, cached by source hash so a
            rebuild copies identical bytes.  The reverse runs a chunk at a time,
            so memory does not grow with the clip's length.  With no ffmpeg, or
            a failed encode, it falls back to `loop` and records why (check 29).

Sound (card `sound: true`, video only): the screen plays the file's audio.
Slide videos are muted by default; anything else plays muted (check 29).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import dataclasses
import hashlib
import os
import shutil
import subprocess
import tempfile
import warnings

import re

import yaml

from talkparse import parse_still, valid_bg

MEDIA_EXTS = {
    ".mp4": "video", ".webm": "video", ".mov": "video", ".m4v": "video",
    ".webp": "image", ".png": "image", ".jpg": "image", ".jpeg": "image",
    ".gif": "image", ".svg": "image",
}
VIDEO_EXTS = {e for e, t in MEDIA_EXTS.items() if t == "video"}

DOC_MAX_WIDTH = 1100              # handout figures: about 150 dpi across a letter page
DOC_JPEG_QUALITY = 70
DOC_RECIPE = f"doc-v1|{DOC_MAX_WIDTH}|{DOC_JPEG_QUALITY}"

PLAYBACK_VALUES = ("loop", "once", "pingpong")
PINGPONG_CHUNK_SECONDS = 1        # the reverse holds one chunk of frames, never the clip
# Bump when the recipe changes, so cached pingpong files are re-baked.
PINGPONG_RECIPE = ("pingpong-v2", "chunked reverse", "trim first frame of each leg",
                   "libx264 crf 16 slow yuv420p")


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
    group: Optional[str] = None        # live only: hosts sharing one capture session
    playback: str = "loop"             # video only: loop | once | pingpong (card `playback:`)
    sound: bool = False                # video only: play the audio track (card `sound: true`)
    origin: Optional[str] = None       # absolute source path; `file` becomes out-root-relative once published
    still: Optional[tuple] = None      # video only: the handout frame (card `still:`, see talkparse.parse_still); None = a quarter in
    doc_file: Optional[str] = None     # out-root-relative small JPEG the handout prints (image) or shows as the still (video)
    steps: Optional[list] = None       # stepped-image card: the frame slugs, in order (card `steps:`); None = a plain image
    handout: Optional[str] = None      # stepped-image card: slug of the image the document view and handout print
    reading_copy: bool = True          # False (card `reading-copy: false`): slides only; the document view, handout and web export leave the picture out
    web_video: bool = True             # video only: False (card `web-video: false`): the web export keeps the still, never the clip (rights, size)

    @property
    def label(self) -> str:
        """The slug as an author wrote it: a section's `pic--lib` is `pic`.  What
        a picture with no alt falls back to."""
        return re.sub(r"--lib(?=--|$)", "", self.slug)



def _place(src, dst: Path, link: bool = False) -> None:
    """Publish one media file into the output: a copy, or with `link` an
    absolute symlink to the source (throwaway builds, no disk cost)."""
    dst = Path(dst)
    if link:
        if dst.is_symlink() or dst.exists():
            dst.unlink()
        dst.symlink_to(Path(src).resolve())
    else:
        shutil.copyfile(src, dst)

POOL_RE = re.compile(r"^(.+)--(\d{2,})$")
PIN_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,38}[a-z0-9]$")


def _pins(card: dict) -> dict:
    """A pool card's `pins:` as {id: file name}; non-string entries are skipped."""
    raw = card.get("pins")
    if not isinstance(raw, dict):
        return {}
    return {str(k): v for k, v in raw.items() if isinstance(v, str) and v}


def pool_files(card: dict, talk_dir: Path) -> list:
    """The media files of a pool card's folder, sorted by name (hidden files,
    sidecar yaml and sub-folders are not media)."""
    folder = card.get("pool")
    if not isinstance(folder, str) or not folder.strip():
        return []
    d = (Path(talk_dir) / folder).resolve()
    if not d.is_dir():
        return []
    pinned = set(_pins(card).values())      # a pinned file is used only where it is pinned
    return sorted(p for p in d.iterdir()
                  if p.is_file() and not p.name.startswith(".")
                  and p.suffix.lower() in MEDIA_EXTS and p.name not in pinned)


def pool_pick(slug: str, card: dict, files: list, n: int, deck: str = ""):
    """The file for use number `n` (1-based) of pool `slug`: cycle k is a
    shuffle seeded by (seed|deck|slug|k), `deck` being the talk's slug so two
    talks sharing a pool get different orders; a cycle never opens on the
    file that closed the one before."""
    import random

    if not files:
        return None
    seed = str(card.get("seed", ""))
    order, k, prev_last = [], 0, None
    while len(order) < n:
        cyc = list(files)
        random.Random(f"{seed}|{deck}|{slug}|{k}").shuffle(cyc)
        if len(cyc) > 1 and cyc[0] == prev_last:
            cyc[0], cyc[1] = cyc[1], cyc[0]
        order.extend(cyc)
        prev_last = cyc[-1]
        k += 1
    return order[n - 1]


def expand_pools(talk, resolver) -> None:
    """Give every use of a pool slug its own virtual slug (`<slug>--NN`),
    in document order, then apply each card's `text:` and `bg:` defaults to its shots.
    Call once, right after the resolver is made."""
    _expand_pool_uses(talk, resolver)
    _apply_text_defaults(talk, resolver)
    _apply_bg_defaults(talk, resolver)


def _apply_bg_defaults(talk, resolver) -> None:
    """A card's `bg:` (`#rrggbb` or `auto`) is the default `bg=` for every shot
    that uses its slug; the shot's own `bg=` wins."""
    for scr in talk.screens:
        for shot in scr.shots:
            if shot.slug and "bg" not in shot.flags:
                val = resolver.bg_default_for(shot.slug)
                if val:
                    shot.flags["bg"] = val


def _apply_text_defaults(talk, resolver) -> None:
    """A card's `text: light|dark` (any card, or a shared-library entry) is the
    default `text=` for every shot that uses its slug (a use, a pin, a
    continue); the shot's own `text=` wins.  Runs even when the deck has no pool."""
    for scr in talk.screens:
        for shot in scr.shots:
            if shot.slug and "text" not in shot.flags:
                val = resolver.text_default_for(shot.slug)
                if val:
                    shot.flags["text"] = val


def _expand_pool_uses(talk, resolver) -> None:
    """One pass over every shot, in document order.

    A shot from a section (an include, or the quick-select shelf) is registered
    as SHARED: it resolves from the shared `_media/` only, never from the deck's
    `cards.yaml` or `media/` (`resolver.shared`).  When the deck has its own
    card, pin or file of the same slug, the section's slug is renamed
    `<slug>--lib` so the two cannot meet in one output name.  A pool slug (deck
    card, or shared-library entry) gets a virtual `<slug>--NN` per use."""
    pools = {str(c["slug"]) for c in resolver.cards
             if isinstance(c, dict) and c.get("slug") and c.get("pool")}
    count: dict = {}
    prev_media = None
    prev_orig = (None, None)         # (slug, under) as authored, before any rewrite
    origs: dict = {}                 # id(shot) -> that pair, for the shots rewritten below
    for scr in talk.screens:
        for shot in scr.shots:
            if shot.cont and prev_media is not None:
                # a continuation keeps the head's file (and its `under`)
                if shot.slug == prev_orig[0] and shot.slug != prev_media.slug:
                    shot.slug = prev_media.slug
                if shot.flags.get("under") and shot.flags.get("under") == prev_orig[1] \
                        and prev_media.flags.get("under"):
                    shot.flags["under"] = prev_media.flags["under"]
                continue
            section = shot.include is not None or scr.shelf
            origs[id(shot)] = (shot.slug, shot.flags.get("under"))
            for name in ("slug", "under"):
                cur = shot.slug if name == "slug" else shot.flags.get("under")
                if not cur:
                    continue
                if section:
                    label = resolver.section_label(cur)
                    lib = resolver.lib_pools.get(cur)
                    if lib is not None:
                        count[label] = count.get(label, 0) + 1
                        virtual = f"{label}--{count[label]:02d}"
                        resolver.shared[virtual] = (cur, count[label])
                        f = pool_pick(cur, lib, pool_files(lib, resolver.talk_dir),
                                      count[label], resolver.deck_id())
                        resolver.pool_log.append((virtual, f.name if f else None, shot.line))
                        final = virtual
                    else:
                        resolver.shared[label] = (cur, None)
                        final = label
                elif cur in pools:
                    count[cur] = count.get(cur, 0) + 1
                    final = f"{cur}--{count[cur]:02d}"
                    card = resolver.card_for(cur)
                    f = pool_pick(cur, card, pool_files(card, resolver.talk_dir), count[cur],
                                  resolver.deck_id())
                    resolver.pool_log.append((final, f.name if f else None, shot.line))
                else:
                    continue
                if name == "slug":
                    shot.slug = final
                else:
                    shot.flags["under"] = final
        m = scr.media_shot
        if m is not None:
            prev_media = m
            prev_orig = origs.get(id(m), prev_orig)


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
    # check-29 register: (slug, message) for a card `playback:` that cannot
    # apply as written — an unknown value, a non-video card, or a pingpong
    # the publish step could not bake (the screen falls back to `loop`).
    playback_issues: list = field(default_factory=list)
    playback_fallback: dict = field(default_factory=dict)   # slug -> "loop"
    doc_files: dict = field(default_factory=dict)           # slug -> out-root-relative handout JPEG
    out_root: Optional[Path] = None                         # set by publish()
    # check 33: (slug, message) for a card `steps:` / `handout:` that cannot
    # apply as written; the card then renders as one plain image.
    steps_issues: list = field(default_factory=list)
    _steps_cache: dict = field(default_factory=dict)        # slug -> spec dict | None
    # --link-media: symlink published files instead of copying them. For
    # throwaway and test builds only: the output folder is no longer portable.
    link_media: bool = False
    # pool cards: (virtual slug, chosen file name or None, shot line), filled by expand_pools()
    pool_log: list = field(default_factory=list)
    # check 41: (slug, message) for a pool card that cannot apply as written
    pool_issues: list = field(default_factory=list)
    _pin_map: dict = field(default_factory=dict)            # pin id -> (pool card, file name)
    # Section media (a shot from an include or the shelf) resolves from the shared
    # `_media/` only.  expand_pools() fills `shared`: final slug -> (library slug,
    # pool use number or None).  Every other slug resolves deck-first, as ever.
    shared: dict = field(default_factory=dict)
    deck_cards: list = field(default_factory=list)          # cards.yaml only (no library pools)
    lib_pools: dict = field(default_factory=dict)           # library entries with `pool:`, by slug
    _lib_pin_map: dict = field(default_factory=dict)        # library pool pins: id -> (entry, file name)
    # check 50: (slug, message) when two files in `_media/` match one slug
    shared_issues: list = field(default_factory=list)
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
        self.deck_cards = list(self.cards)
        # shared library: sibling `_media/library.yaml` of the deck dir
        lib = self.talk_dir.parent / "_media" / "library.yaml"
        if lib.is_file():
            try:
                loaded = yaml.safe_load(lib.read_text(encoding="utf-8"))
                if isinstance(loaded, list):
                    self.library = loaded
                    self.library_path = lib
                    # a library entry with `pool:` is a shared pool card: it joins
                    # the deck's cards (a deck card of the same slug wins); its
                    # `pool:` folder is still deck-relative, so one entry serves
                    # every deck that sits beside `_media/`
                    self.lib_pools = {str(e["slug"]): e for e in loaded
                                      if isinstance(e, dict) and e.get("pool") and e.get("slug")}
                    for e in self.lib_pools.values():
                        for pid, fname in _pins(e).items():
                            if PIN_SLUG_RE.fullmatch(pid) and not POOL_RE.match(pid):
                                self._lib_pin_map.setdefault(pid, (e, fname))
                    have = {c.get("slug") for c in self.cards if isinstance(c, dict)}
                    self.cards = list(self.cards) + [
                        e for e in loaded
                        if isinstance(e, dict) and e.get("pool") and e.get("slug") not in have]
            except yaml.YAMLError:
                pass

        # check 10 (missing-checks register): every
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

        self._check_pools()

        # check 29: a card's `playback:` must be one of the known values, and
        # only a video card plays.  Like check 10 this runs over ALL cards.
        for c in self.cards:
            if not isinstance(c, dict) or not c.get("slug") or "playback" not in c:
                continue
            slug, value = str(c["slug"]), c.get("playback")
            if value not in PLAYBACK_VALUES:
                self.playback_issues.append((slug,
                    f"card '{slug}' has playback: {value!r}; expected one of "
                    f"{', '.join(PLAYBACK_VALUES)} (plays as loop)"))
            elif c.get("type") != "video":
                self.playback_issues.append((slug,
                    f"card '{slug}' has playback: {value} but type: "
                    f"{c.get('type')}; playback applies to video cards only"))
        # ...and so must `sound:`, which is a plain boolean
        for c in self.cards:
            if not isinstance(c, dict) or not c.get("slug") or "sound" not in c:
                continue
            slug, value = str(c["slug"]), c.get("sound")
            if not isinstance(value, bool):
                self.playback_issues.append((slug,
                    f"card '{slug}' has sound: {value!r}; expected true or "
                    f"false (plays muted)"))
            elif value and c.get("type") != "video":
                self.playback_issues.append((slug,
                    f"card '{slug}' has sound: true but type: "
                    f"{c.get('type')}; sound applies to video cards only"))

    def _check_pools(self) -> None:
        """Index every pool card's `pins:` and record what cannot apply (check 41)."""
        card_slugs = {str(c["slug"]) for c in self.cards
                      if isinstance(c, dict) and c.get("slug")}
        # `text:` on any card or shared-library entry (pool cards from the
        # library are already in self.cards, so each slug is checked once)
        seen = set()
        for c in list(self.cards) + list(self.library):
            if not (isinstance(c, dict) and c.get("slug")) or "text" not in c:
                continue
            if str(c["slug"]) in seen or c["text"] in ("light", "dark"):
                continue
            seen.add(str(c["slug"]))
            kind = "pool" if c.get("pool") else "card"
            self.pool_issues.append((str(c["slug"]),
                f"{kind} '{c['slug']}': text: {c['text']!r}; expected light or dark (ignored)"))
        seen_bg = set()
        for c in list(self.cards) + list(self.library):
            if not (isinstance(c, dict) and c.get("slug")) or "bg" not in c:
                continue
            if str(c["slug"]) in seen_bg or valid_bg(c["bg"]):
                continue
            seen_bg.add(str(c["slug"]))
            kind = "pool" if c.get("pool") else "card"
            self.pool_issues.append((str(c["slug"]),
                f"{kind} '{c['slug']}': bg: {c['bg']!r}; expected #rrggbb, #rgb, a colour name or auto (ignored)"))
        for c in self.cards:
            if not (isinstance(c, dict) and c.get("slug") and c.get("pool")):
                continue
            slug = str(c["slug"])
            folder = (self.talk_dir / str(c["pool"])).resolve()
            if not folder.is_dir():
                self.pool_issues.append((slug,
                    f"pool '{slug}': folder {c['pool']!r} does not exist (joined to deck dir)"))
                continue
            if not pool_files(c, self.talk_dir):
                self.pool_issues.append((slug,
                    f"pool '{slug}': no unpinned media files in {c['pool']!r}; "
                    f"its uses render placeholders"))
            if c.get("pins") is not None and not isinstance(c.get("pins"), dict):
                self.pool_issues.append((slug,
                    f"pool '{slug}': pins: must be a mapping of id to file name"))
            for pid, fname in _pins(c).items():
                if not PIN_SLUG_RE.fullmatch(pid) or POOL_RE.match(pid):
                    self.pool_issues.append((pid,
                        f"pool '{slug}': pin id {pid!r} breaks the slug rule "
                        f"[a-z0-9-], 3-40 chars, no leading/trailing '-' (and no "
                        f"trailing '--NN'); it is ignored"))
                    continue
                if pid in card_slugs or pid in self._pin_map:
                    self.pool_issues.append((pid,
                        f"pool '{slug}': pin id {pid!r} is already a card or another "
                        f"pin; the pin is ignored"))
                    continue
                self._pin_map[pid] = (c, fname)
                f = folder / fname
                if not f.is_file():
                    self.pool_issues.append((pid,
                        f"pool '{slug}': pin '{pid}' names {fname!r}, which is not in "
                        f"{c['pool']!r}; the screen renders a placeholder"))

    # -- lookups -------------------------------------------------------------

    def card_for(self, slug: str) -> Optional[dict]:
        reg = self.shared.get(slug)
        if reg is not None:         # section media: only a shared pool card applies
            base, n = reg
            pin = self._lib_pin_map.get(base) if n is None else None
            return pin[0] if pin else self.lib_pools.get(base)
        for c in self.cards:
            if isinstance(c, dict) and c.get("slug") == slug:
                return c
        if slug in self._pin_map:
            return self._pin_map[slug][0]
        m = POOL_RE.match(slug)
        if m:                       # a pool use answers with its pool's card
            c = self.card_for(m.group(1))
            if c is not None and c.get("pool"):
                return c
        return None

    def deck_id(self) -> str:
        """The talk's frontmatter slug (else its folder name): seeds pool picks."""
        return str(self.meta.get("slug", "") or self.talk_dir.name)

    def _pool_ref(self, slug: str, base: str, n: int, card: dict) -> MediaRef:
        files = pool_files(card, self.talk_dir)
        f = pool_pick(base, card, files, n, self.deck_id())
        if f is None:
            return MediaRef(
                slug=slug, type="image", status="missing", found=False,
                alt=card.get("alt", ""), credit=card.get("credit", ""),
                licence=card.get("licence", ""),
                reason=f"pool '{base}': no media files in {card.get('pool')!r}")
        # a pool's own `type:` is the card's default; the file decides here
        return self._make(slug, {**card, "type": None}, f, "pool")

    def text_default_for(self, slug: str) -> Optional[str]:
        """The `text:` default (light or dark) of the card, else the shared-library
        entry, that this slug resolves to; None when there is none or it is invalid."""
        for src in (self.card_for(slug), self.library_entry_for(slug)):
            if isinstance(src, dict) and src.get("text") in ("light", "dark"):
                return src["text"]
            if isinstance(src, dict) and "text" in src:
                return None
        return None

    def bg_default_for(self, slug: str) -> Optional[str]:
        """The `bg:` default of the card, else the shared-library entry, that
        this slug resolves to; None when there is none or it is invalid."""
        for src in (self.card_for(slug), self.library_entry_for(slug)):
            if isinstance(src, dict) and "bg" in src:
                return src["bg"] if valid_bg(src["bg"]) else None
        return None

    def library_entry_for(self, slug: str) -> Optional[dict]:
        reg = self.shared.get(slug)
        if reg is not None:
            slug = reg[0] if reg[1] is None else None
        return self._lib_entry(slug)

    def _lib_entry(self, slug) -> Optional[dict]:
        for e in self.library:
            if isinstance(e, dict) and slug and e.get("slug") == slug:
                return e
        return None

    # -- shared media --------------------------------------------------------

    @property
    def shared_dir(self) -> Path:
        """The shared `_media/` folder: always beside THIS deck's folder, whatever
        directory a section was read from (`--quick-sections DIR` included)."""
        return self.talk_dir.parent / "_media"

    def deck_differs(self, slug: str) -> bool:
        """Does the deck own something named `slug` (a card, a pool pin, a file in
        its media dir)?  Then a section's `slug` must not share its name."""
        return (any(isinstance(c, dict) and c.get("slug") == slug for c in self.deck_cards)
                or (slug in self._pin_map
                    and any(self._pin_map[slug][0] is c for c in self.deck_cards))
                or self._deckdir_file(slug) is not None
                or self._attempts_file(slug) is not None)

    def section_label(self, slug: str) -> str:
        """The slug a section shot is known by: itself, or `<slug>--lib` when the
        deck has its own `<slug>` (so both can be published side by side)."""
        return f"{slug}--lib" if self.deck_differs(slug) else slug

    def _named_shared_file(self, slug: str) -> Optional[Path]:
        """`_media/<slug>.<ext>`, else `_media/<slug>/<slug>.<ext>`.  Two matches is
        check 50: the flat file wins, then the extension order of MEDIA_EXTS."""
        if not slug or "/" in slug or "\\" in slug or slug.startswith("."):
            return None
        d = self.shared_dir
        found = []
        for base in (d, d / slug):
            for ext in MEDIA_EXTS:
                p = base / f"{slug}{ext}"
                if p.is_file():
                    found.append(p)
        if len(found) > 1:
            issue = (slug, f"shared media '{slug}' matches {len(found)} files in {d} "
                           f"({', '.join(str(f.relative_to(d)) for f in found)}); using "
                           f"{found[0].relative_to(d)}. Keep one.")
            if issue not in self.shared_issues:
                self.shared_issues.append(issue)
        return found[0] if found else None

    def _shared_stage(self, slug: str, look: str, card: Optional[dict],
                      section: bool = False) -> Optional[MediaRef]:
        """Library entry with a `file:`, else a file named for the slug.  The entry
        is the card (alt, credit, licence, type, playback...) for a section's media
        and for a deck slide with no card of its own; a deck's card keeps its own
        words.  An entry whose `file:` is not there falls through and warns."""
        entry = self._lib_entry(look)
        entry_is_card = section or card is None
        if entry_is_card:
            card = entry
        if entry and entry.get("file") and self.library_path is not None:
            p = self.library_path.parent / str(entry["file"])
            if p.is_file():
                ref = self._make(slug, card, p, "library")
                if entry.get("note") and ((not ref.note) if entry_is_card else (not ref.alt)):
                    ref.note = entry["note"]
                return ref
            msg = (f"library entry '{look}' has file: {entry['file']!r}, which is not "
                   f"there; looking for a file named for the slug instead")
            if (look, msg) not in self.shared_issues:
                self.shared_issues.append((look, msg))
        p = self._named_shared_file(look)
        if p is not None:
            return self._make(slug, card, p, "library")
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

    def _live_ref(self, slug: str, card: dict, root: Optional[Path] = None) -> MediaRef:
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
            p = (root or self.talk_dir) / raw
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
            group=(str(card.get("live_group")) if card.get("live_group") else None),
        )
        brief = card.get("brief")
        if isinstance(brief, str) and brief.strip():
            ref.note = brief.strip().splitlines()[0]
        elif isinstance(brief, list) and brief:
            ref.note = str(brief[0])
        return ref

    # -- stepped images ------------------------------------------------------

    def _steps_source(self, slug: str) -> Optional[dict]:
        """The card (else the library entry) that may carry `steps:`."""
        for src in (self.card_for(slug), self.library_entry_for(slug)):
            if src and "steps" in src:
                return src
        return None

    def steps_spec(self, slug: str) -> Optional[dict]:
        """A card's validated `steps:` (spec: Media, stepped images), or None
        when it has none or cannot apply (check 33; the card is then one plain
        image).  `{"steps": [slug, ...], "handout": <frame slug or the card's
        own slug>}`.  Cached: validation reports each problem once."""
        if slug in self._steps_cache:
            return self._steps_cache[slug]
        spec = self._steps_cache[slug] = None
        src = self._steps_source(slug)
        if src is None:
            return None

        def bad(msg):
            self.steps_issues.append((slug, f"card '{slug}' {msg}; it renders as one plain image"))

        steps = src.get("steps")
        if not isinstance(steps, list):
            return None     # a string or number is a free note (decks already write `steps:` as prose), not a declaration
        if len(steps) < 2:
            bad(f"has steps: {steps!r}; a stepped card needs a list of 2 or more image slugs")
            return None
        orig = [str(x) for x in steps]
        names = orig
        if slug in self.shared:
            # section media: the frames are shared media too, and keep clear of
            # any deck slug of the same name
            names = []
            for n in orig:
                label = self.section_label(n)
                self.shared.setdefault(label, (n, None))
                names.append(label)
        problems = []
        for n in names:
            r = self._resolve_plain(n)
            ext = Path(r.file).suffix.lower() if r.found and r.file else ""
            if r.live or (r.found and MEDIA_EXTS.get(ext) == "video") or r.type == "video":
                problems.append(f"'{n}' is a video (steps are still images)")
            elif not r.found or MEDIA_EXTS.get(ext) != "image":
                problems.append(f"'{n}' does not resolve to an image")
        if problems:
            bad("has steps that cannot show: " + "; ".join(problems))
            return None
        own = self._resolve_plain(slug)
        own_ok = own.found and not own.live
        if "handout" in src:
            h = src["handout"]
            if h == "first":
                pick = names[0]
            elif h == "last":
                pick = names[-1]
            elif isinstance(h, int) and not isinstance(h, bool):
                if not 1 <= h <= len(names):
                    bad(f"has handout: {h}, but steps has {len(names)} frames (1 to {len(names)})")
                    return None
                pick = names[h - 1]
            elif isinstance(h, str) and h in orig:
                pick = names[orig.index(h)]
            elif isinstance(h, str) and h.isdigit() and 1 <= int(h) <= len(names):
                pick = names[int(h) - 1]
            else:
                bad(f"has handout: {h!r}, which is not first, last, a number from 1 to "
                    f"{len(names)}, or one of its steps")
                return None
        elif own_ok:
            pick = slug               # the card's own image is the handout image
        else:
            pick = names[-1]
        spec = self._steps_cache[slug] = {"steps": names, "handout": pick}
        return spec

    def validate_steps(self) -> None:
        """Validate every card's (and library entry's) `steps:`, so check 33
        reports on cards no screen uses, like checks 10 and 29."""
        for c in list(self.cards) + list(self.library):
            if isinstance(c, dict) and c.get("slug") and "steps" in c:
                self.steps_spec(str(c["slug"]))

    def _resolve(self, slug: str) -> MediaRef:
        ref = self._resolve_plain(slug)
        spec = self.steps_spec(slug)
        if spec is None:
            return ref
        ref.steps = list(spec["steps"])
        ref.handout = spec["handout"]
        if spec["handout"] != slug:
            # the handout image is one of the frames: the card shows that file
            # wherever a single image is wanted (document view, handout,
            # `reveal=off`, a continue screen's first frame, the manifest)
            fr = self._resolve_plain(spec["handout"])
            ref = dataclasses.replace(
                fr, slug=slug, alt=ref.alt or fr.alt, credit=ref.credit or fr.credit,
                licence=ref.licence or fr.licence, note=ref.note or fr.note,
                steps=ref.steps, handout=ref.handout, live=False, reason="")
        return ref

    def _pin_ref(self, slug: str, pcard: dict, fname: str) -> MediaRef:
        f = (self.talk_dir / str(pcard["pool"])).resolve() / fname
        if f.is_file():
            return self._make(slug, {**pcard, "type": None}, f, "pool")
        return MediaRef(
            slug=slug, type="image", status="missing", found=False,
            alt=pcard.get("alt", ""), credit=pcard.get("credit", ""),
            licence=pcard.get("licence", ""),
            reason=f"pin '{slug}': {fname!r} is not in pool folder {pcard.get('pool')!r}")

    def _resolve_shared(self, slug: str, base: str, n: Optional[int]) -> MediaRef:
        """Section media: shared pool, then the shared `_media/` stage, then a
        stand-in.  The deck's cards.yaml and media dir are never read."""
        if n is None and base in self._lib_pin_map:
            return self._pin_ref(slug, *self._lib_pin_map[base])
        card = self.lib_pools.get(base)
        if card is not None:
            return self._pool_ref(slug, base, n or 1, card)
        entry = self._lib_entry(base)
        if entry and str(entry.get("type") or "").lower() == "live" and self.library_path:
            return self._live_ref(slug, entry, self.library_path.parent)
        ref = self._shared_stage(slug, base, None, section=True)
        if ref is not None:
            return ref
        p = self.remap.get(slug)    # `<slug>--lib` by that name: a deck's stand-in stays the deck's
        if p is not None and p.is_file():
            return self._make(slug, None, p, "standin")
        return MediaRef(
            slug=slug, type="unknown", status="missing", found=False,
            reason=f"no shared media for '{base}': no library entry with a file, and "
                   f"no {self.shared_dir}/{base}.<ext> or {base}/{base}.<ext> "
                   f"(a section never uses the deck's own cards or media)")

    def _resolve_plain(self, slug: str) -> MediaRef:
        reg = self.shared.get(slug)
        if reg is not None:
            return self._resolve_shared(slug, *reg)
        card = self.card_for(slug)
        if slug in self._pin_map:
            return self._pin_ref(slug, *self._pin_map[slug])
        if card is not None and card.get("pool"):
            m = POOL_RE.match(slug)
            if m and m.group(1) == card.get("slug"):
                return self._pool_ref(slug, m.group(1), int(m.group(2)), card)
            return self._pool_ref(slug, slug, 1, card)    # the bare pool slug: its first pick
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

        # 3) shared media: a library entry's `file:`, else a file named for the slug
        ref = self._shared_stage(slug, slug, card)
        if ref is not None:
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
        if slug in self.playback_fallback:
            ref.playback = self.playback_fallback[slug]
        if slug in self.doc_files:
            ref.doc_file = self.doc_files[slug]
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
        self.out_root = Path(out_root)
        # a stepped card's frames travel with it
        slugs = list(slugs)
        for slug in list(slugs):
            spec = self.steps_spec(slug)
            if spec:
                slugs.extend(n for n in spec["steps"] if n not in slugs)
        for slug in slugs:
            if slug in self.published or (slug + "-poster") in self.published:
                continue
            ref = self._resolve(slug)
            if ref.found and ref.file:
                self._doc_derivative(ref.file, media_dir, slug, slug, ref.still)
            if ref.live:
                # the poster is the only file a live screen contributes
                if not ref.poster:
                    continue
                ext = Path(ref.poster).suffix.lower() or ".bin"
                dst = media_dir / f"{slug}-poster{ext}"
                _place(ref.poster, dst, self.link_media)
                self.published[slug + "-poster"] = str(
                    Path("_media") / f"{slug}-poster{ext}")
                self._doc_derivative(ref.poster, media_dir, slug + "-poster", slug)
                continue
            if not (ref.found and ref.file):
                continue
            ext = Path(ref.file).suffix.lower() or ".bin"
            if ref.playback == "pingpong":
                dst = media_dir / f"{slug}-pingpong.mp4"
                why = bake_pingpong(Path(ref.file), dst, link=self.link_media)
                if why is None:
                    self.published[slug] = str(Path("_media") / dst.name)
                    continue
                self.playback_fallback[slug] = "loop"
                self.playback_issues.append((slug,
                    f"card '{slug}' asks for playback: pingpong but {why}; "
                    f"it plays as loop"))
            dst = media_dir / f"{slug}{ext}"
            _place(ref.file, dst, self.link_media)
            self.published[slug] = str(Path("_media") / f"{slug}{ext}")

    def doc_still(self, ref: "MediaRef", spec: str) -> Optional[str]:
        """A shot's own `still=` frame (it overrides the card's): a JPEG
        beside the slug's default one, named for the spec.  None on failure."""
        want = parse_still(spec)
        if want is None or not ref.origin or self.out_root is None:
            return None
        key = re.sub(r"[^a-z0-9.]+", "-", str(spec).lower().replace("%", "pct")).strip("-")
        name = f"{ref.slug}@{key}"
        self._doc_derivative(ref.origin, self.out_root / "_media", name, name, want)
        return self.doc_files.get(name)

    def _doc_derivative(self, src, media_dir: Path, name: str, slug: str,
                        still: Optional[tuple] = None) -> None:
        """The handout's own copy of a figure: a small JPEG under
        `_media/doc/` (an image downscaled and recompressed; a video
        reduced to one still).  The present view keeps the full-size
        originals; a printed page never needs them, and a PDF built from
        the originals runs to hundreds of MB.  Cached on the source's
        size and mtime, so rebuilds are quick and byte-stable.  Silent on
        failure: the figure then falls back to the original file."""
        src = Path(src)
        ext = src.suffix.lower()
        if ext == ".svg" or not src.is_file():
            return
        doc_dir = media_dir / "doc"
        doc_dir.mkdir(parents=True, exist_ok=True)
        dst = doc_dir / f"{name}.jpg"
        stamp = doc_dir / f"{name}.stamp"
        st = src.stat()
        key = f"{DOC_RECIPE}|{st.st_size}|{int(st.st_mtime)}|{still}"
        if not (dst.exists() and stamp.exists() and stamp.read_text() == key):
            if ext in VIDEO_EXTS:
                ok = _video_still(src, dst, still)
            else:
                ok = _image_small(src, dst)
            if not ok:
                return
            stamp.write_text(key)
        self.doc_files[slug] = str(Path("_media") / "doc" / f"{name}.jpg")

    def _make(self, slug: str, card: Optional[dict], path: Path, source: str) -> MediaRef:
        ext = path.suffix.lower()
        ref = MediaRef(
            slug=slug,
            type=(card.get("type") if card else None) or MEDIA_EXTS.get(ext, "file"),
            status=(card.get("status") if card else None) or "have",
            found=True,
            file=str(path.resolve()),
            origin=str(path.resolve()),
            source=source,
            alt=card.get("alt", "") if card else "",
            credit=card.get("credit", "") if card else "",
            licence=card.get("licence", "") if card else "",
        )
        # playback only means something for a video file; an unknown value
        # plays as the default (check 29 reports it)
        if card and ext in VIDEO_EXTS and card.get("playback") in PLAYBACK_VALUES:
            ref.playback = card["playback"]
        if card and ext in VIDEO_EXTS and card.get("sound") is True:
            ref.sound = True
        if card and ext in VIDEO_EXTS and "still" in card:
            ref.still = parse_still(card["still"])
            if ref.still is None:
                self.playback_issues.append((slug,
                    f"card '{slug}' has still: {card['still']!r}; use start, end, "
                    f"seconds, or n%; the handout uses a quarter in"))
        if card and card.get("reading-copy") is False:
            ref.reading_copy = False
        if card and card.get("web-video") is False:
            ref.web_video = False
        if card and card.get("brief"):
            brief = card["brief"]
            if isinstance(brief, str) and brief.strip():
                ref.note = brief.strip().splitlines()[0]
            elif isinstance(brief, list) and brief:
                ref.note = str(brief[0])
        return ref

    def unreferenced_cards(self, referenced: set) -> list:
        """Card slugs never referenced by any shot (authoring info).  A stepped
        card's frames count as referenced by it."""
        # a section's slug uses only the shared library: it counts for a shared
        # pool card (a library entry), never for a deck card of the same name
        shared_used = {self.shared[s][0] for s in referenced if s in self.shared}
        referenced = {s for s in referenced if s not in self.shared}
        for slug in list(referenced):       # a pool use or pin counts for its pool
            m = POOL_RE.match(slug)
            if m:
                referenced.add(m.group(1))
            if slug in self._pin_map:
                referenced.add(str(self._pin_map[slug][0]["slug"]))
        for slug in list(referenced):
            spec = self.steps_spec(slug)
            if spec:
                referenced.update(spec["steps"])
        for pid in list(shared_used):
            if pid in self._lib_pin_map:
                shared_used.add(str(self._lib_pin_map[pid][0]["slug"]))
        return [str(c["slug"]) for c in self.cards
                if isinstance(c, dict) and c.get("slug") not in referenced
                and not (self.lib_pools.get(str(c.get("slug"))) is c
                         and c.get("slug") in shared_used)]


UNCREDITED = ("shared media '{}' has no credit, so the handout credits nobody: "
              "add a library.yaml entry with `credit:` and `licence:`")


def uncredited_shared(talk, resolver) -> dict:
    """Check 51: {slug as written: first line} for each file from `_media/` with
    no credit.  A file named for its slug needs no library entry to show, so
    nothing else notices it has none to credit it."""
    out = {}
    for scr in talk.screens:
        for shot in scr.shots:
            for slug in (shot.slug if shot.is_media else None, shot.flags.get("under")):
                if slug:
                    ref = resolver.resolve(slug)
                    if ref.found and ref.source == "library" and not ref.credit:
                        out.setdefault(ref.label, shot.line_begin)
    return out


def shelf_media_errors(talk, resolver) -> list:
    """Check 48, media half: (line, message) for every shelf screen whose media
    does not resolve.  Nobody pages through hidden slides, so unlike an ordinary
    include (a placeholder and a warning) a shelf section must be complete.
    Call after expand_pools() (and after any stand-in remap is loaded)."""
    out, seen = [], set()
    for scr in talk.screens:
        if not scr.shelf:
            continue
        sec = scr.section[0] if scr.section else "?"
        for shot in scr.shots:
            for slug in (shot.slug if shot.is_media else None, shot.flags.get("under")):
                if not slug or (sec, slug) in seen:
                    continue
                seen.add((sec, slug))
                ref = resolver.resolve(slug)
                if not ref.found:
                    base = resolver.shared.get(slug, (slug, None))[0]
                    out.append((shot.line_begin or 1,
                        f"check 48: shelf section {sec}: media '{base}' does not "
                        f"resolve ({ref.reason or 'no file'}); a shelf screen is "
                        f"never paged to, so it cannot be a placeholder. Add the "
                        f"file to the shared _media/ or fix the slug"))
    return out


# ---------------------------------------------------------------------------
# pingpong baking
# ---------------------------------------------------------------------------


def _cache_dir() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "animatic" / "pingpong"


def _image_small(src: Path, dst: Path) -> bool:
    try:
        from PIL import Image, ImageOps
        with Image.open(src) as im:
            im = ImageOps.exif_transpose(im)
            if im.mode in ("RGBA", "LA", "P"):
                im = im.convert("RGBA")
                flat = Image.new("RGB", im.size, (255, 255, 255))
                flat.paste(im, mask=im.getchannel("A"))
                im = flat
            else:
                im = im.convert("RGB")
            if im.width > DOC_MAX_WIDTH:
                im = im.resize((DOC_MAX_WIDTH, round(im.height * DOC_MAX_WIDTH / im.width)),
                               Image.LANCZOS)
            im.save(dst, "JPEG", quality=DOC_JPEG_QUALITY, optimize=True, progressive=True)
        return True
    except Exception:
        return False


_CORNER_CACHE: dict = {}


def corner_colour(path) -> Optional[str]:
    """`#rrggbb` of the top-left corner of an image, or of a video's first
    frame (the mean of a 3x3 block, so one noisy JPEG pixel does not decide);
    None when it cannot be read or the corner is transparent."""
    if not path:
        return None
    key = str(path)
    if key not in _CORNER_CACHE:
        _CORNER_CACHE[key] = _read_corner(Path(path))
    return _CORNER_CACHE[key]


def _read_corner(src: Path) -> Optional[str]:
    try:
        if src.suffix.lower() in VIDEO_EXTS:
            if shutil.which("ffmpeg") is None:
                return None
            proc = subprocess.run(
                ["ffmpeg", "-v", "error", "-i", str(src), "-frames:v", "1",
                 "-vf", "crop=3:3:0:0,scale=1:1:flags=area", "-f", "rawvideo",
                 "-pix_fmt", "rgb24", "-"], capture_output=True, timeout=120)
            px = proc.stdout[:3]
            if proc.returncode != 0 or len(px) < 3:
                return None
            r, g, b = px
        else:
            from PIL import Image
            with Image.open(src) as im:
                im = im.convert("RGBA").crop((0, 0, min(3, im.width), min(3, im.height)))
                px = list(im.getdata())
            if not px or sum(p[3] for p in px) / len(px) < 128:
                return None   # a transparent corner has no ground colour
            r, g, b = (round(sum(p[i] for p in px) / len(px)) for i in range(3))
        return f"#{r:02x}{g:02x}{b:02x}"
    except Exception:
        return None


def _video_still(src: Path, dst: Path, spec: Optional[tuple] = None) -> bool:
    """One frame, scaled to the handout width: `spec` (talkparse.parse_still)
    picks start, end, a time or a share of the clip; the default is a quarter
    of the way in (the first frame is often black)."""
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        return False
    spec = spec or ("frac", 0.25)
    seek = []
    if spec[0] == "end":
        seek = ["-sseof", "-0.2"]
    elif spec[0] == "start":
        seek = ["-ss", "0"]
    else:
        try:
            out = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=nw=1:nk=1", str(src)],
                capture_output=True, text=True, timeout=60).stdout.strip()
            dur = float(out)
        except Exception:
            dur = 0.0
        at = spec[1] * dur if spec[0] == "frac" else spec[1]
        if dur:
            at = min(at, max(0.0, dur - 0.2))   # a time past the end shows the last frame
        seek = ["-ss", f"{max(0.0, at):.2f}"]
    why = _ffmpeg(seek + ["-i", str(src), "-frames:v", "1",
                          "-vf", f"scale='min({DOC_MAX_WIDTH},iw)':-2",
                          "-q:v", "6", str(dst)], timeout=120)
    return why is None and dst.exists()


def _ffmpeg(args: list, timeout: int = 600) -> Optional[str]:
    """Run ffmpeg quietly; None on success, else its last error line."""
    try:
        proc = subprocess.run(["ffmpeg", "-v", "error", "-y"] + args,
                              capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        return str(exc)
    if proc.returncode != 0:
        return (proc.stderr.strip().splitlines() or ["unknown error"])[-1]
    return None


def bake_pingpong(src: Path, dst: Path, link: bool = False) -> Optional[str]:
    """Write a forward-then-reversed copy of `src` to `dst`, for looping.

    Returns None on success, else a short reason the caller reports (the
    screen then plays the original as a loop).

    ffmpeg's `reverse` filter buffers every decoded frame, so memory would
    grow with the clip (about 0.9 GB per 10 s of 1080p).  Instead the reverse
    leg is built a chunk at a time, which only ever holds one chunk:
      1. cut the clip into PINGPONG_CHUNK_SECONDS pieces, lossless, cut
         exactly on forced keyframes;
      2. reverse each piece on its own;
      3. play the source forward, then the reversed pieces last-first, and
         encode once.
    Proven frame-identical to the single-pass reverse filter (2026-09-22).
    The first frame of each leg is dropped so neither the turn nor the loop
    seam shows a doubled frame.  What memory remains is the H.264 encoder's,
    which scales with CPU threads, not clip length.

    The result is cached under ~/.cache/animatic/pingpong/ by a hash of the
    source bytes and the recipe: a rebuild copies the same bytes (the build
    stays deterministic) and never re-encodes.
    """
    if shutil.which("ffmpeg") is None:
        return "ffmpeg is not installed"
    h = hashlib.sha256()
    h.update("|".join(PINGPONG_RECIPE).encode())
    with open(src, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    cached = _cache_dir() / f"{h.hexdigest()}.mp4"
    if not cached.is_file():
        cached.parent.mkdir(parents=True, exist_ok=True)
        lossless = ["-an", "-c:v", "libx264", "-qp", "0", "-preset", "ultrafast"]
        with tempfile.TemporaryDirectory(prefix="pingpong-", dir=cached.parent) as work:
            work = Path(work)
            (work / "fwd").mkdir()
            (work / "rev").mkdir()
            why = _ffmpeg(["-i", str(src)] + lossless + [
                "-force_key_frames", f"expr:gte(t,n_forced*{PINGPONG_CHUNK_SECONDS})",
                "-f", "segment", "-segment_time", str(PINGPONG_CHUNK_SECONDS),
                "-reset_timestamps", "1", str(work / "fwd" / "c%06d.mkv")])
            if why:
                return f"ffmpeg failed splitting the clip ({why})"
            pieces = sorted((work / "fwd").glob("c*.mkv"))
            if not pieces:
                return "ffmpeg produced no frames from the clip"
            for piece in pieces:
                why = _ffmpeg(["-i", str(piece), "-vf", "reverse"] + lossless
                              + [str(work / "rev" / piece.name)])
                if why:
                    return f"ffmpeg failed reversing a chunk ({why})"
            listing = work / "reversed.txt"
            listing.write_text("".join(
                "file '" + str(work / "rev" / p.name).replace("'", "'\\''") + "'\n"
                for p in reversed(pieces)), encoding="utf-8")
            baked = work / "pingpong.mp4"
            why = _ffmpeg([
                "-i", str(src), "-f", "concat", "-safe", "0", "-i", str(listing),
                "-filter_complex",
                "[0:v]trim=start_frame=1,setpts=PTS-STARTPTS[fw];"
                "[1:v]trim=start_frame=1,setpts=PTS-STARTPTS[bw];"
                "[fw][bw]concat=n=2:v=1:a=0,format=yuv420p[out]",
                "-map", "[out]", "-an", "-c:v", "libx264", "-crf", "16", "-preset", "slow",
                "-movflags", "+faststart", str(baked)])
            if why:
                return f"ffmpeg failed joining the pingpong ({why})"
            os.replace(baked, cached)
    _place(cached, dst, link)
    return None
