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
  library is still the one beside the DECK, never one beside DIR;
- the `--lib` name holds wherever a shot goes: a `continue` screen, a stepped
  card and its frames, a video and its pingpong, the document view, and
  `--no-handout-pools`; a picture with no alt falls back to the slug as written;
- a library entry is the card of a deck slide that has none; a missing `file:` is
  check 50; no credit is check 51; a deck's stand-in never fills a section's `--lib`.
"""

from __future__ import annotations

import io
import json
import shutil
import subprocess
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
        _check_lib_names(errors, tmp / "lib")
        _check_entries(errors, tmp / "entries")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _check_lib_names(errors: list, root: Path) -> None:
    decks = root / "decks"
    deck, shared = decks / "deck", decks / "_media"
    deck_pic = _png(deck / "media" / "pic.png", (200, 0, 0))
    lib_pic = _png(shared / "pic.png", (0, 0, 200))
    _png(deck / "media" / "stepped.png", (200, 0, 0))
    _png(deck / "media" / "f1.png", (200, 0, 0))               # the deck's frame of that name
    f1 = _png(shared / "f1.png", (0, 90, 0))
    f2 = _png(shared / "f2.png", (0, 120, 0))
    _png(deck / "media" / "art.png", (200, 0, 0))
    _png(shared / "artfolder" / "a1.png", (10, 10, 10))
    _png(shared / "artfolder" / "a2.png", (240, 240, 240))
    _write(shared / "library.yaml", """
- slug: stepped
  type: image
  status: file
  credit: Someone
  steps: [f1, f2]
- slug: art
  type: image
  status: have
  credit: Someone
  pool: ../_media/artfolder
""")
    _write(decks / "sections" / "s.section.md", """---
timing:
  minutes: 1
---
<!-- shot: pic -->
### Section pic

Words.

<!-- shot: continue -->
### Carried on

Words.

<!-- shot: stepped -->
### Stepped

Words.

<!-- shot: art -->
### Pool

Words.
""")
    deck_slides = "<!-- shot: pic -->\n# Deck pic\n\nWords.\n\n<!-- shot: stepped -->\n### Deck stepped\n\nWords.\n\n<!-- shot: art -->\n### Deck art\n\nWords.\n\n"
    talk = deck / "talk.md"
    _write(talk, HEAD.format(extra="") + deck_slides + "<!-- include: ../sections/s.section.md -->\n")
    out = root / "out"
    code, _, stderr = _build(talk, out)
    if code != 0:
        err(errors, f"--lib names: build exited {code}: {stderr[-300:]}")
        return
    cues = [c for c in _json(out, "cues.json")["cues"] if c.get("media")]
    slugs = [c["media"]["slug"] for c in cues]
    if slugs.count("pic--lib") != 2:
        err(errors, f"--lib names: a continue screen should carry pic--lib on: {slugs}")
    if (out / "_media" / "pic--lib.png").read_bytes() != lib_pic or (out / "_media" / "pic.png").read_bytes() != deck_pic:
        err(errors, "--lib names: pic and pic--lib did not keep their own files")
    stepped = next((c["media"] for c in cues if c["media"]["slug"] == "stepped--lib"), None)
    if not stepped or len(stepped.get("steps") or []) != 2:
        err(errors, f"--lib names: the section's stepped card lost its frames: {stepped}")
    else:
        got = [(out / "_media" / Path(s).name).read_bytes() if (out / "_media" / Path(s).name).is_file()
               else next((out / "_media").glob(f"{s}.*")).read_bytes() for s in stepped["steps"]]
        if got != [f1, f2]:
            err(errors, f"--lib names: frames {stepped['steps']} are not the shared files")
    page = (out / "present" / "index.html").read_text(encoding="utf-8")
    doc = (out / "document" / "index.html").read_text(encoding="utf-8")
    for name, text in (("deck", page), ("document", doc)):
        if 'alt="pic--lib"' in text:
            err(errors, f"--lib names: the {name} view shows pic--lib as alt text")
    if 'alt="pic"' not in doc:
        err(errors, "--lib names: a picture with no alt should fall back to `pic`")
    if not any(s.startswith("art--lib--") for s in slugs):
        err(errors, f"--lib names: the section's pool use has no --lib name: {slugs}")
    # --no-handout-pools drops a section's `art--lib--01` as it drops a deck's pool pick
    out2 = root / "out-nopools"
    code, _, stderr = _build(talk, out2, "--no-handout-pools")
    doc2 = (out2 / "document" / "index.html").read_text(encoding="utf-8")
    if code != 0 or "art--lib--" in doc2:
        err(errors, f"--lib names: --no-handout-pools kept a section's pool pick (code {code})")

    # a deck's stand-in stays the deck's; a stand-in named for the --lib slug is used
    standin = _png(root / "standin.png", (77, 77, 77))
    _write(deck / "talk.md", HEAD.format(extra="") + "<!-- shot: gone -->\n# Deck\n\nWords.\n\n"
           "<!-- include: ../sections/gone.section.md -->\n")
    _write(decks / "sections" / "gone.section.md", "<!-- shot: gone -->\n### Section\n\nWords.\n")
    _png(deck / "media" / "gone.png", (1, 1, 1))
    remap = root / "remap.yaml"
    _write(remap, f"gone: {root / 'standin.png'}\n")
    out3 = root / "out-remap"
    _build(talk, out3, "--media-remap", str(remap))
    man = {e["slug"]: e["media"] for e in _json(out3, "media-manifest.json")["referenced"]}
    if man.get("gone--lib", {}).get("found"):
        err(errors, f"--lib names: the deck's stand-in filled the section's gone--lib: {man.get('gone--lib')}")
    _write(remap, f"gone--lib: {root / 'standin.png'}\n")
    out4 = root / "out-remap2"
    _build(talk, out4, "--media-remap", str(remap))
    if not next((out4 / "_media").glob("gone--lib.*"), None) \
            or next((out4 / "_media").glob("gone--lib.*")).read_bytes() != standin:
        err(errors, "--lib names: a stand-in named gone--lib was not used")

    # video and its pingpong
    if not shutil.which("ffmpeg"):
        return
    clip = shared / "vid.mp4"
    (deck / "media" / "vid.mp4").parent.mkdir(parents=True, exist_ok=True)
    made = subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=s=160x90:r=24:d=1",
                           "-pix_fmt", "yuv420p", "-c:v", "libx264", str(clip)], capture_output=True, timeout=120)
    if made.returncode != 0:
        return
    shutil.copy(clip, deck / "media" / "vid.mp4")
    _write(shared / "library.yaml", """
- slug: vid
  type: video
  status: file
  credit: Someone
  playback: pingpong
""")
    _write(decks / "sections" / "v.section.md", "<!-- shot: vid -->\n### Clip\n\nWords.\n")
    _write(talk, HEAD.format(extra="") + "<!-- shot: vid -->\n# Deck clip\n\nWords.\n\n"
           "<!-- include: ../sections/v.section.md -->\n")
    out5 = root / "out-video"
    code, _, stderr = _build(talk, out5)
    if code != 0:
        err(errors, f"--lib names: video build exited {code}: {stderr[-300:]}")
        return
    media = out5 / "_media"
    if not (media / "vid--lib-pingpong.mp4").is_file():
        err(errors, f"--lib names: no vid--lib-pingpong.mp4: {sorted(p.name for p in media.iterdir())}")
    if not (media / "vid.mp4").is_file():
        err(errors, "--lib names: the deck's own loop clip was not published as vid.mp4")
    if not list((media / "doc").glob("vid--lib.*")):
        err(errors, "--lib names: the section's clip has no handout still of its own")


def _check_entries(errors: list, root: Path) -> None:
    decks = root / "decks"
    deck, shared = decks / "deck", decks / "_media"
    _png(shared / "plain.png", (9, 9, 9))
    _png(shared / "fine.png", (8, 8, 8))
    _png(shared / "broken.png", (7, 7, 7))
    _png(shared / "owned.png", (6, 6, 6))
    _png(shared / "twice.png", (5, 5, 5))
    _png(shared / "twice.webp", (4, 4, 4))
    _write(shared / "library.yaml", """
- slug: fine
  status: file
  alt: Library alt
  credit: Library credit
  licence: CC BY
- slug: broken
  status: file
  file: nowhere/broken.png
  credit: Library credit
- slug: noted
  status: file
  file: fine.png
  alt: Library alt
  credit: Library credit
  note: The entry's note
- slug: twice
  status: file
  file: nowhere/twice.png
  credit: Library credit
- slug: owned
  status: file
  alt: Library alt
  credit: Library credit
""")
    _write(deck / "media" / "cards.yaml", """
- slug: owned
  status: to-find
  alt: The deck's alt
  credit: The deck's credit
""")
    talk = deck / "talk.md"
    _write(talk, HEAD.format(extra="") + "".join(
        f"<!-- shot: {s} -->\n### {s}\n\nWords.\n\n" for s in ("plain", "fine", "broken", "owned", "noted", "twice")))
    _, r = _resolver(talk)
    fine = r.resolve("fine")
    if (fine.alt, fine.credit) != ("Library alt", "Library credit"):
        err(errors, f"entries: a slide with no card did not take the entry's words: {fine.alt!r} {fine.credit!r}")
    owned = r.resolve("owned")
    if (owned.alt, owned.credit) != ("The deck's alt", "The deck's credit"):
        err(errors, f"entries: a deck's card lost its words to the entry: {owned.alt!r} {owned.credit!r}")
    if r.resolve("noted").note != "The entry's note":
        err(errors, f"entries: a slide with no card lost the entry's note: {r.resolve('noted').note!r}")
    if not r.resolve("broken").found:
        err(errors, "entries: a missing file: should fall through to the file named for the slug")
    rep = check_mod.check_file(talk)
    w50 = [f.message for f in rep.findings if f.check == 50]
    w51 = [f.message for f in rep.findings if f.check == 51]
    for want in ("nowhere/broken.png", "nowhere/twice.png", "'twice' matches 2 files"):
        if not any(want in m for m in w50):
            err(errors, f"entries: check 50 should say {want!r}: {w50}")
    if len(w50) != 3:
        err(errors, f"entries: check 50 should give 3 warnings: {w50}")
    if len(w51) != 1 or "'plain'" not in w51[0]:
        err(errors, f"entries: check 51 should name only the uncredited file: {w51}")
    stdout = _build(talk, root / "out")[1]
    if "check 50" not in stdout or "check 51" not in stdout:
        err(errors, "entries: build.py does not print checks 50 and 51")
