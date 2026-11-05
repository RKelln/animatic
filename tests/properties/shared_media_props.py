"""Section media and the shared `_media/` (docs/media-pipeline.md, "Shared media").

A throwaway tree under /tmp: `decks/<deck>/` beside `decks/_media/` and a
`decks/sections/` folder, built through build.py and checked through check.py.

- a shot from a section (an include or the shelf) never reads the deck's
  `cards.yaml` or `media/`: it resolves from `_media/` only, so a section looks
  the same in every deck.  A shared POOL slug ignores a deck card of the same
  name too;
- one deck can use the same slug in a slide and in a section, with different
  files: the section's shot is `<slug>--lib`; both files are published, under
  different names, and appear apart in the manifest, cues.json and the document
  view.  With no clash the output name is the slug, as ever;
- a file named for its slug, `_media/<slug>.<ext>` or `_media/<slug>/<slug>.<ext>`,
  resolves with no library entry (slides as well as sections); an entry's `file:`
  wins; two matching files is check 50 (a warning, and a fixed pick);
- an unresolved slug on a SHELF screen is fatal (check 48) in build.py and
  check.py, naming the section; in an ordinary include it stays a placeholder
  and a warning;
- `--quick-sections DIR` with a directory outside the deck's parent: the shared
  library is still the one beside the DECK, never one beside DIR.
"""

from __future__ import annotations

import io
import json
import shutil
import tempfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import build as build_mod
import check as check_mod
import mediaresolve
import talkparse
from PIL import Image

from .common import err

HEAD = """---
type: Talk
format-version: 1.0
content-version: 1
slug: shared-props
title: "Shared media props"
theme: workshop
{extra}---
"""


def _png(path: Path, color) -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (16, 16), color).save(path, "PNG")
    return path.read_bytes()


def _build(talk: Path, out: Path, *extra: str):
    buf, ebuf = io.StringIO(), io.StringIO()
    with redirect_stdout(buf), redirect_stderr(ebuf):
        code = build_mod.main([str(talk), "--out", str(out), "--link-media", *extra])
    return code, buf.getvalue(), ebuf.getvalue()


def _json(out: Path, name: str) -> dict:
    return json.loads((out / name).read_text(encoding="utf-8"))


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _resolver(talk: Path, *, quick: str | None = None):
    t = talkparse.build_talk(talk, quick_sections=quick)
    r = mediaresolve.MediaResolver(talk_dir=talk.parent, meta=t.meta)
    mediaresolve.expand_pools(t, r)
    return t, r


def check(errors: list) -> None:
    try:
        _check(errors)
    except Exception as exc:                      # a broken rule often shows up as a missing file
        err(errors, f"shared: the run stopped early: {exc!r}")


def _check(errors: list) -> None:
    tmp = Path(tempfile.mkdtemp(prefix="animatic-shared-"))
    try:
        decks = tmp / "decks"
        deck = decks / "deck"
        shared = decks / "_media"
        red = _png(deck / "media" / "pic-deck.png", (200, 0, 0))
        blue = _png(shared / "pic.png", (0, 0, 200))              # named for its slug, no entry
        green = _png(deck / "media" / "pool-deck.png", (0, 200, 0))
        _png(shared / "poolfolder" / "p1.png", (10, 10, 10))
        _png(shared / "poolfolder" / "p2.png", (240, 240, 240))
        only = _png(shared / "only" / "only.png", (5, 90, 90))     # _media/<slug>/<slug>.png
        entry_file = _png(shared / "entries" / "win-entry.png", (0, 0, 120))
        _png(shared / "win.png", (120, 0, 0))                      # name match the entry beats
        _png(shared / "amb.png", (1, 2, 3))
        _png(shared / "amb.webp", (3, 2, 1))
        _png(shared / "amb" / "amb.png", (9, 9, 9))
        _write(shared / "library.yaml", """
- slug: win
  type: image
  status: file
  file: entries/win-entry.png
  alt: Entry alt for win
  credit: Entry credit
  licence: CC BY-SA
- slug: ryan-pool
  type: image
  status: have
  pool: ../_media/poolfolder
  alt: Pool alt
""")
        _write(deck / "media" / "cards.yaml", """
- slug: pic
  status: file
  type: image
  file: media/pic-deck.png
  alt: The deck's own pic
- slug: ryan-pool
  status: file
  type: image
  file: media/pool-deck.png
  alt: The deck's own card of the pool's name
""")
        _write(decks / "sections" / "s.section.md", """---
timing:
  minutes: 1
---
<!-- shot: pic -->
### Section pic

Section words.

<!-- shot: only -->
### Only in the library

More section words.

<!-- shot: win -->
### The entry wins

Words.

<!-- shot: ryan-pool -->
### A pool

Pool words.
""")
        talk = deck / "talk.md"
        _write(talk, HEAD.format(extra="") + """<!-- shot: pic -->
# The deck's own pic

Deck words.

<!-- include: ../sections/s.section.md -->

<!-- shot: ryan-pool -->
### The deck's own card of that name

Deck words again.
""")

        # --- the same slug in a slide and in a section --------------------
        out = tmp / "out"
        code, stdout, stderr = _build(talk, out)
        if code != 0:
            err(errors, f"shared: build exited {code}: {stderr[-300:]}")
            return
        cues = _json(out, "cues.json")
        slugs = [s["media"]["slug"] for s in cues["screens"] if s.get("media")] \
            if "screens" in cues else \
            [c["media"]["slug"] for c in cues["cues"] if c.get("media")]
        for want in ("pic", "pic--lib", "only", "win"):
            if want not in slugs:
                err(errors, f"shared: cues.json has no media slug {want!r}: {slugs}")
        if (out / "_media" / "pic.png").read_bytes() != red:
            err(errors, "shared: the deck slide `pic` is not the deck's own file")
        if (out / "_media" / "pic--lib.png").read_bytes() != blue:
            err(errors, "shared: the section's `pic` is not the shared _media/pic.png")
        man = {e["slug"]: e["media"] for e in _json(out, "media-manifest.json")["referenced"]}
        if man.get("pic", {}).get("source") != "cards" or man.get("pic--lib", {}).get("source") != "library":
            err(errors, f"shared: manifest sources for the clash: "
                        f"{man.get('pic', {}).get('source')!r} / {man.get('pic--lib', {}).get('source')!r}")
        if man.get("pic", {}).get("file") == man.get("pic--lib", {}).get("file"):
            err(errors, "shared: pic and pic--lib share one published file name")
        doc = (out / "document" / "index.html").read_text(encoding="utf-8")
        if "pic.jpg" not in doc or "pic--lib.jpg" not in doc:
            err(errors, "shared: the document view does not carry both pictures")
        if (out / "_media" / "doc" / "pic.jpg").read_bytes() == (out / "_media" / "doc" / "pic--lib.jpg").read_bytes():
            err(errors, "shared: pic and pic--lib have the same handout image")
        # output names stay the slug when nothing clashes
        if (out / "_media" / "only.png").read_bytes() != only:
            err(errors, "shared: `only` (_media/only/only.png, no entry) is not published as only.png")
        if any(p.name.startswith("only--") or p.name.startswith("win--") for p in (out / "_media").iterdir()):
            err(errors, "shared: a section slug with no deck clash was renamed")
        # entry wins over a file named for the slug, and supplies the metadata
        if (out / "_media" / "win.png").read_bytes() != entry_file:
            err(errors, "shared: the library entry's file did not beat _media/win.png")
        if man.get("win", {}).get("alt") != "Entry alt for win" or man["win"].get("credit") != "Entry credit":
            err(errors, f"shared: a section shot does not carry its library entry's metadata: {man.get('win')}")

        # --- a shared pool ignores the deck's card of its name ------------
        _, r = _resolver(talk)
        pool_virtuals = [v for v in r.shared if v.startswith("ryan-pool")]
        if pool_virtuals != ["ryan-pool--lib--01"]:
            err(errors, f"shared pool: section pool uses are {pool_virtuals}, wanted ['ryan-pool--lib--01']")
        else:
            ref = r.resolve("ryan-pool--lib--01")
            if not ref.found or Path(ref.file).parent.name != "poolfolder":
                err(errors, f"shared pool: section use of ryan-pool took {ref.file!r}, not the pool folder")
        deck_ref = r.resolve("ryan-pool")
        if not deck_ref.found or Path(deck_ref.file).read_bytes() != green:
            err(errors, "shared pool: the deck's own slide of that slug lost its deck card")
        # ...and with the deck card absent the pool slug is not renamed
        (deck / "media" / "cards.yaml").write_text("[]\n", encoding="utf-8")
        (deck / "media" / "pool-deck.png").unlink()
        _write(talk, HEAD.format(extra="") + "<!-- include: ../sections/s.section.md -->\n")
        _, r2 = _resolver(talk)
        if "ryan-pool--01" not in r2.shared:
            err(errors, f"shared pool: with no deck card the use should be ryan-pool--01: {sorted(r2.shared)}")

        # --- name-matched file, no entry; ambiguity -----------------------
        _write(talk, HEAD.format(extra="") + """<!-- shot: only -->
# A slide of a shared file

Words.
""")
        _, r3 = _resolver(talk)
        ref = r3.resolve("only")
        if not ref.found or ref.source != "library" or Path(ref.file).name != "only.png":
            err(errors, f"name match: deck slide `only` -> {ref.found} {ref.source} {ref.file}")
        _write(talk, HEAD.format(extra="") + """<!-- shot: amb -->
# Two files, one slug

Words.
""")
        picks = []
        for _ in range(2):
            _, ra = _resolver(talk)
            ref = ra.resolve("amb")
            picks.append(ref.file)
            if not ref.found or len(ra.shared_issues) != 1:
                err(errors, f"ambiguous: found={ref.found} issues={ra.shared_issues}")
        if len(set(picks)) != 1 or Path(picks[0]).name != "amb.webp":
            err(errors, f"ambiguous: the pick is not fixed (flat file, then MEDIA_EXTS order): {picks}")
        rep = check_mod.check_file(talk)
        if not any(f.check == 50 and f.severity == "warning" for f in rep.findings):
            err(errors, "ambiguous: check.py reports no check 50 warning")
        if "check 50" not in _build(talk, tmp / "out-amb")[1]:
            err(errors, "ambiguous: build.py prints no check 50 warning")
        # an entry's file or a flat file alone never warns
        _write(talk, HEAD.format(extra="") + "<!-- shot: win -->\n# W\n\nWords.\n")
        if _resolver(talk)[1].shared_issues:
            err(errors, "ambiguous: an entry that wins over a name match still warned")

        # --- shelf: unresolved is fatal; an ordinary include is not -------
        secdir = decks / "shelf"
        _write(secdir / "ghost.section.md", """---
quick:
  title: "Ghost"
  keywords: [ghost]
---
<!-- shot: no-such-media -->
### Nothing to show

Words.
""")
        _write(talk, HEAD.format(extra="quick_sections: ../shelf\n") + """<!-- shot -->
# Opening

Words.
""")
        code, _, stderr = _build(talk, tmp / "out-shelf")
        if code == 0 or "ghost.section.md" not in stderr or "check 48" not in stderr \
                or "no-such-media" not in stderr:
            err(errors, f"shelf: build code {code}, stderr {stderr[:300]!r}")
        rep = check_mod.check_file(talk)
        fatal = [f for f in rep.findings if f.check == 48 and f.severity == "fatal"]
        if not fatal or "ghost.section.md" not in fatal[0].message or rep.exit_code != 1:
            err(errors, f"shelf: check.py: exit {rep.exit_code}, findings {[f.render() for f in rep.findings]}")
        # fixing the media fixes the build
        _png(shared / "no-such-media.png", (7, 7, 7))
        code, _, stderr = _build(talk, tmp / "out-shelf2")
        if code != 0:
            err(errors, f"shelf: a resolvable shelf did not build: {stderr[:200]!r}")
        (shared / "no-such-media.png").unlink()
        # the same section, included in the talk: a placeholder and a warning
        _write(talk, HEAD.format(extra="") + "<!-- include: ../shelf/ghost.section.md -->\n")
        code, stdout, _ = _build(talk, tmp / "out-inc")
        man = _json(tmp / "out-inc", "media-manifest.json")["referenced"]
        if code != 0 or [e["media"]["found"] for e in man] != [False]:
            err(errors, f"include: unresolved section media should build as a placeholder (code {code})")
        rep = check_mod.check_file(talk)
        if rep.exit_code != 0 or not any(f.check == 11 and f.severity == "warning" for f in rep.findings):
            err(errors, f"include: expected exit 0 and a check 11 warning: {[f.render() for f in rep.findings]}")

        # --- --quick-sections with a directory outside the deck's parent --
        elsewhere = tmp / "elsewhere"
        _write(elsewhere / "sections" / "far.section.md", """---
quick:
  title: "Far"
  keywords: [far]
---
<!-- shot: far-pic -->
### Far

Words.
""")
        _png(shared / "far-pic.png", (50, 60, 70))            # beside the DECK: found
        _write(talk, HEAD.format(extra="") + "<!-- shot -->\n# Opening\n\nWords.\n")
        code, _, stderr = _build(talk, tmp / "out-far", "--quick-sections", str(elsewhere / "sections"))
        if code != 0:
            err(errors, f"outside dir: shared media beside the deck was not used: {stderr[:200]!r}")
        (shared / "far-pic.png").unlink()
        _png(elsewhere / "_media" / "far-pic.png", (50, 60, 70))   # beside the section dir: ignored
        _png(elsewhere / "sections" / "_media" / "far-pic.png", (50, 60, 70))
        code, _, stderr = _build(talk, tmp / "out-far2", "--quick-sections", str(elsewhere / "sections"))
        if code == 0 or "far.section.md" not in stderr:
            err(errors, f"outside dir: a _media beside the section directory was used (code {code})")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
