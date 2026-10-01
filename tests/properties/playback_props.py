"""Video playback property checks (register 29; card `playback:`).

Builds a throwaway deck under /tmp from generated clips, because the
behaviour lives in real video files: the committed fixtures stay media-free.

- `loop` (and no key at all) keeps the cinematic `loop` attribute;
- `once` drops `loop`, carries data-playback="once", and the manifest says so;
- `pingpong` publishes `_media/<slug>-pingpong.mp4`, about twice the source's
  length (less the two dropped seam frames), and it still loops;
- an unknown value and a playback on an image card each raise check 29 and
  change nothing in the build;
- the pingpong cache makes a rebuild byte-identical (determinism);
- the frames come out in exactly the right order across chunk boundaries:
  each source frame has its own brightness, so the baked file is read back
  frame by frame (a chunk joined out of order, or a doubled seam frame, fails);
- with no ffmpeg the screen falls back to looping the original, and says why;
- `sound: true` drops `muted` and marks data-sound (only there), the manifest
  says so, and a non-boolean or a sound on an image card raises check 29;
- the `advance` shot flag drops `loop`, plays once and carries data-advance
  (only there), and on an image it raises check 31;
- shot flags override the card for their screen (2026-09-28): `playback=once`
  and `playback=loop` beat the card's playback, `playback=advance` is the same
  as `advance`, `sound` / `sound=false` / `silent` beat the card's sound (in the
  handout too), `playback=pingpong` is refused (check 25), `sound` on an image raises
  check 31, and a playback or sound on a continue shot warns.

Needs ffmpeg + ffprobe; without them the module pins nothing, like
timing_props' video unit.
"""

from __future__ import annotations

import io
import json
import os
import re
import shutil
import subprocess
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

import build as build_mod
import check as check_mod
import mediaresolve

from .common import err

TALK = """\
---
type: Talk
format-version: 1.0
slug: playback-demo
title: "Playback demo"
theme: lecture
---

<!-- shot: clip-loop -->

A looping clip.

<!-- shot: clip-once -->

A clip that plays once and holds.

<!-- shot: clip-pingpong -->

A clip that goes there and back.

<!-- shot: clip-default -->

A clip with no playback key.

<!-- shot: clip-typo -->

A clip whose playback value is misspelled.

<!-- shot: still-once -->

A still that asks to play once.

<!-- shot: clip-sound -->

A clip that plays once, with its audio.

<!-- shot: clip-sound-typo -->

A clip whose sound value is not a boolean.

<!-- shot: still-sound -->

A still that asks for sound.

<!-- shot: clip-advance advance -->

A looping clip that moves the deck on when it ends.

<!-- shot: still-advance advance -->

A still that asks to advance.

<!-- shot: clip-shot-once playback=once -->

A looping card that this screen plays once.

<!-- shot: continue sound -->

A continue shot that asks for sound it cannot change.

<!-- shot: clip-shot-loop playback=loop -->

A play-once card that this screen loops.

<!-- shot: clip-shot-advance playback=advance -->

The alias for advance.

<!-- shot: clip-shot-sound sound -->

A muted card that this screen plays with sound.

<!-- shot: clip-shot-mute sound=false -->

A sound card that this screen mutes.

<!-- shot: clip-shot-silent silent -->

A sound card that this screen mutes with the silent alias.

<!-- shot: clip-shot-pingpong playback=pingpong -->

A shot asking for pingpong, which only a card can bake.

<!-- shot: still-shot-sound sound -->

A still whose shot asks for sound.

"""

CARDS = """\
- slug: clip-loop
  type: video
  status: file
  playback: loop
  file: media/clip.mp4
- slug: clip-once
  type: video
  status: file
  playback: once
  file: media/clip.mp4
- slug: clip-pingpong
  type: video
  status: file
  playback: pingpong
  file: media/clip.mp4
- slug: clip-default
  type: video
  status: file
  file: media/clip.mp4
- slug: clip-typo
  type: video
  status: file
  playback: ponce
  file: media/clip.mp4
- slug: still-once
  type: image
  status: file
  playback: once
  file: media/still.png
- slug: clip-sound
  type: video
  status: file
  playback: once
  sound: true
  file: media/clip.mp4
- slug: clip-sound-typo
  type: video
  status: file
  sound: "yes"
  file: media/clip.mp4
- slug: still-sound
  type: image
  status: file
  sound: true
  file: media/still.png
- slug: clip-advance
  type: video
  status: file
  file: media/clip.mp4
- slug: still-advance
  type: image
  status: file
  file: media/still.png
- slug: clip-shot-once
  type: video
  status: file
  playback: loop
  file: media/clip.mp4
- slug: clip-shot-loop
  type: video
  status: file
  playback: once
  file: media/clip.mp4
- slug: clip-shot-advance
  type: video
  status: file
  file: media/clip.mp4
- slug: clip-shot-sound
  type: video
  status: file
  file: media/clip.mp4
- slug: clip-shot-mute
  type: video
  status: file
  sound: true
  file: media/clip.mp4
- slug: clip-shot-silent
  type: video
  status: file
  sound: true
  file: media/clip.mp4
- slug: clip-shot-pingpong
  type: video
  status: file
  file: media/clip.mp4
- slug: still-shot-sound
  type: image
  status: file
  file: media/still.png
"""

# each frame N of the test clip is a flat grey at LUMA0 + LUMA_STEP * N, so the
# baked file can be read back and its frame order checked exactly
CLIP_FRAMES, LUMA0, LUMA_STEP = 72, 20, 2


def _frame_lumas(path: Path) -> list:
    # extractplanes takes the luma plane as stored; converting to `gray`
    # would rescale limited range to full and shift every value
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-vf", "extractplanes=y",
                          "-f", "rawvideo", "-"], capture_output=True, check=True,
                         timeout=120).stdout
    size = 64 * 64
    return [sum(raw[i:i + size]) / size for i in range(0, len(raw), size)]


VIDEO_TAG_RE = re.compile(r'<video[^>]*class="[^"]*media-video[^"]*"[^>]*>')


def _build(talkfile: Path, out: Path) -> str:
    buf = io.StringIO()
    with redirect_stdout(buf):
        build_mod.main([str(talkfile), "--out", str(out)])
    return buf.getvalue()


def _tree_bytes(root: Path) -> dict:
    return {str(p.relative_to(root)): p.read_bytes()
            for p in sorted(root.rglob("*")) if p.is_file()}


def _check_fit(errors: list) -> None:
    """`fit` values mean what they say; contain is the default (2026-09-28)."""
    from render import media_fit
    cases = [({}, "contain"), ({"fit": "contain"}, "contain"),
             ({"fit": "cover"}, "cover"), ({"fit": "hero"}, "contain"),
             ({"kb": "in"}, "cover"), ({"kb": "out", "fit": "contain"}, "contain")]
    for flags, want in cases:
        got = media_fit(flags)
        if got != want:
            err(errors, f"fit: media_fit({flags}) = {got!r}, want {want!r}")


def check(errors: list) -> None:
    _check_fit(errors)
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        return                                  # no ffmpeg here: nothing to pin
    tmp = Path(tempfile.mkdtemp(prefix="animatic-playback-"))
    old_cache = os.environ.get("XDG_CACHE_HOME")
    os.environ["XDG_CACHE_HOME"] = str(tmp / "cache")   # never touch the real cache
    try:
        deck = tmp / "deck"
        (deck / "media").mkdir(parents=True)
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
             f"nullsrc=s=64x64:r=24:d={CLIP_FRAMES / 24},"
             f"geq=lum='{LUMA0}+{LUMA_STEP}*N':cb=128:cr=128,format=yuv420p",
             "-c:v", "libx264", "-crf", "0", str(deck / "media" / "clip.mp4")],
            check=True, timeout=120)
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=gray:s=64x64",
             "-frames:v", "1", str(deck / "media" / "still.png")],
            check=True, timeout=120)
        (deck / "talk.md").write_text(TALK, encoding="utf-8")
        (deck / "media" / "cards.yaml").write_text(CARDS, encoding="utf-8")

        out_a, out_b = tmp / "out-a", tmp / "out-b"
        log = _build(deck / "talk.md", out_a)
        present = (out_a / "present" / "index.html").read_text(encoding="utf-8")
        tags = {}
        for tag in VIDEO_TAG_RE.findall(present):
            m = re.search(r'src="[^"]*_media/([^"/]+)"', tag)
            if m:
                tags[m.group(1)] = tag

        def tag_for(name):
            t = tags.get(name)
            if t is None:
                err(errors, f"playback: no present video for {name} (have {sorted(tags)})")
                return ""
            return t

        # every slide video: the pager plays and warms it, so no bare autoplay
        # and no eager preload (a served deck fetched every video at load and
        # starved its images; 2026-09-28)
        for name, t in sorted(tags.items()):
            if re.search(r"\sautoplay\b", t) or "data-autoplay" not in t:
                err(errors, f"playback: {name} must carry data-autoplay, not autoplay: {t}")
            if 'preload="none"' not in t:
                err(errors, f"playback: {name} must be preload=\"none\": {t}")

        for name in ("clip-loop.mp4", "clip-default.mp4", "clip-typo.mp4",
                     "clip-shot-loop.mp4", "clip-shot-pingpong.mp4"):
            t = tag_for(name)
            if t and (not re.search(r"\sloop\b", t) or "data-playback" in t):
                err(errors, f"playback: {name} should loop plainly: {t}")
        for name in ("clip-once.mp4", "clip-shot-once.mp4"):
            t = tag_for(name)
            if t and (re.search(r"\sloop\b", t) or 'data-playback="once"' not in t):
                err(errors, f"playback: once must drop loop and mark itself: {t}")
        t = tag_for("clip-once.mp4")
        if t and (re.search(r"\sloop\b", t) or 'data-playback="once"' not in t):
            err(errors, f"playback: once must drop loop and mark itself: {t}")
        # sound: only clip-sound (card) and clip-shot-sound (shot) are
        # unmuted; clip-shot-mute's card sound is muted by its shot
        for name, t in sorted(tags.items()):
            loud = name in ("clip-sound.mp4", "clip-shot-sound.mp4")
            if loud != ("data-sound" in t) or loud == bool(re.search(r"\smuted\b", t)):
                err(errors, f"playback: {name} sound={loud} but tag is {t}")
        t = tag_for("clip-sound.mp4")
        if t and (re.search(r"\sloop\b", t) or 'data-playback="once"' not in t):
            err(errors, f"playback: sound must not change once: {t}")
        for name, t in sorted(tags.items()):
            adv = name in ("clip-advance.mp4", "clip-shot-advance.mp4")
            if adv != ("data-advance" in t):
                err(errors, f"playback: data-advance belongs on the advance clips only: {t}")
        # playback=advance is the same flag as advance: identical tags
        t = tag_for("clip-advance.mp4")
        if t and (re.search(r"\sloop\b", t) or 'data-playback="once"' not in t):
            err(errors, f"playback: advance must play once, not loop: {t}")
        t2 = tag_for("clip-shot-advance.mp4")
        if t and t2 and t.replace("clip-advance", "X") != t2.replace("clip-shot-advance", "X"):
            err(errors, f"playback: playback=advance differs from advance: {t} vs {t2}")
        # the handout carries no video: each clip is its small JPEG still
        # (2026-09-30), so playback / sound / advance have nothing to set
        document = (out_a / "document" / "index.html").read_text(encoding="utf-8")
        if VIDEO_TAG_RE.search(document):
            err(errors, "playback: the handout must not carry a <video> element")
        for name in ("clip-shot-once", "clip-shot-loop", "clip-shot-sound",
                     "clip-shot-mute", "clip-shot-silent"):
            if f'src="../_media/doc/{name}.jpg"' not in document:
                err(errors, f"playback: handout has no still for {name}")
            elif not (out_a / "_media" / "doc" / f"{name}.jpg").is_file():
                err(errors, f"playback: handout still for {name} missing on disk")
        if "video[data-advance]" not in present:
            err(errors, "playback: pager lacks the advance-on-ended handler")
        if "NotAllowedError" not in present:
            err(errors, "playback: pager lacks the muted fallback for a refused sound play")
        t = tag_for("clip-pingpong-pingpong.mp4")
        if t and not re.search(r"\sloop\b", t):
            err(errors, f"playback: the baked pingpong must loop: {t}")

        # the baked file, frame by frame: 1..n-1 forward, then n-2..0 back
        # (the first frame of each leg is dropped, so no seam repeats a frame)
        baked = out_a / "_media" / "clip-pingpong-pingpong.mp4"
        if not baked.is_file():
            err(errors, "playback: no baked pingpong file was published")
        else:
            n = CLIP_FRAMES
            want_order = list(range(1, n)) + list(range(n - 2, -1, -1))
            got = [round((v - LUMA0) / LUMA_STEP) for v in _frame_lumas(baked)]
            if got != want_order:
                bad = next((i for i, (g, w) in enumerate(zip(got, want_order)) if g != w),
                           min(len(got), len(want_order)))
                err(errors, f"playback: pingpong frame order wrong: {len(got)} frames "
                            f"(want {len(want_order)}), first mismatch at output frame "
                            f"{bad}: got {got[bad:bad + 4]}, want {want_order[bad:bad + 4]}")

        manifest = json.loads((out_a / "media-manifest.json").read_text(encoding="utf-8"))
        by_slug = {r["slug"]: r["media"] for r in manifest["referenced"]}
        # the manifest audits the card, not the screen: shot flags never show
        want = {"clip-once": "once", "clip-pingpong": "pingpong", "clip-sound": "once",
                "clip-shot-loop": "once"}
        for slug, media in by_slug.items():
            if media.get("playback") != want.get(slug):
                err(errors, f"playback: manifest {slug} playback="
                            f"{media.get('playback')!r}, want {want.get(slug)!r}")
            if media.get("sound") != (True if slug in ("clip-sound", "clip-shot-mute", "clip-shot-silent") else None):
                err(errors, f"playback: manifest {slug} sound={media.get('sound')!r}")

        # check 29: exactly the two typos and the two image cards, at build and at check
        for needle in ("'clip-typo' has playback: 'ponce'", "'still-once' has playback: once but type: image",
                       "'clip-sound-typo' has sound: 'yes'", "'still-sound' has sound: true but type: image"):
            if needle not in log:
                err(errors, f"playback: build log lacks check 29 for {needle!r}")
        report = check_mod.check_file(str(deck / "talk.md"))
        c29 = [f for f in report.findings if f.check == 29]
        if len(c29) != 4:
            err(errors, f"playback: check 29 found {len(c29)} issues, want 4: "
                        f"{[f.message for f in c29]}")
        c31 = [f for f in report.findings if f.check == 31]
        c31_msgs = sorted(f.message for f in c31)
        if (len(c31) != 2 or not c31_msgs[0].startswith("advance on 'still-advance'")
                or not c31_msgs[1].startswith("sound on 'still-shot-sound'")):
            err(errors, f"playback: check 31 should flag still-advance and "
                        f"still-shot-sound only: {c31_msgs}")
        # playback=pingpong on a shot is refused (check 25); the clip still loops
        c25 = [f.message for f in report.findings if f.check == 25]
        if not any("playback=pingpong" in m and "card-only" in m for m in c25):
            err(errors, f"playback: check 25 lacks the refused shot pingpong: {c25}")
        # a sound on a continue shot cannot change the head's video: it warns
        if not any("'sound=true' on a continue shot" in f.message for f in report.findings):
            err(errors, f"playback: no warning for sound on a continue shot: "
                        f"{[f.message for f in report.findings]}")

        # determinism: the cached pingpong makes a rebuild byte-identical
        _build(deck / "talk.md", out_b)
        a, b = _tree_bytes(out_a), _tree_bytes(out_b)
        if a != b:
            diff = sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k))
            err(errors, f"playback: rebuild differs in {diff[:5]}")

        # the fallback: with no ffmpeg the original loops, and the build says why
        real_which = mediaresolve.shutil.which
        mediaresolve.shutil.which = lambda cmd, *a, **k: None if cmd == "ffmpeg" else real_which(cmd, *a, **k)
        try:
            log_c = _build(deck / "talk.md", tmp / "out-c")
        finally:
            mediaresolve.shutil.which = real_which
        present_c = (tmp / "out-c" / "present" / "index.html").read_text(encoding="utf-8")
        fell_back = [t for t in VIDEO_TAG_RE.findall(present_c) if "_media/clip-pingpong.mp4" in t]
        if not fell_back or not re.search(r"\sloop\b", fell_back[0]):
            err(errors, f"playback: an unbakeable pingpong must loop the original: {fell_back}")
        if (tmp / "out-c" / "_media" / "clip-pingpong-pingpong.mp4").exists():
            err(errors, "playback: an unbakeable pingpong still published a baked file")
        if "'clip-pingpong' asks for playback: pingpong but ffmpeg is not installed" not in log_c:
            err(errors, "playback: the build log does not say why the pingpong fell back")
        manifest_c = json.loads((tmp / "out-c" / "media-manifest.json").read_text(encoding="utf-8"))
        pp = [r["media"] for r in manifest_c["referenced"] if r["slug"] == "clip-pingpong"]
        if not pp or "playback" in pp[0]:
            err(errors, f"playback: a fallen-back pingpong must record as loop: {pp}")
    except Exception as exc:  # noqa: BLE001 — suite must not die
        err(errors, f"playback: suite error: {type(exc).__name__}: {exc}")
    finally:
        if old_cache is None:
            os.environ.pop("XDG_CACHE_HOME", None)
        else:
            os.environ["XDG_CACHE_HOME"] = old_cache
        shutil.rmtree(tmp, ignore_errors=True)
