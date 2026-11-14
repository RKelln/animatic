"""Web copies of a talk's videos: small H.264 MP4s a reading copy can play.

The present view plays the full-size originals from disk; a web page has to
download them, so it gets its own copy: at most 720p and 30 fps, H.264 (the one
codec every browser plays), CRF 30 at a slow preset, `+faststart` so playback
starts before the download ends, and no audio track when the card has no
`sound: true` (a muted clip need not carry one).

Encoding is slow (a two-minute 1080p clip takes about half a minute on 16
cores), so each result is cached under ~/.cache/animatic/web-video/, keyed on
the recipe, the source's bytes, and whether it keeps sound.
Rebuilding a page re-encodes only what changed, and nothing lands in a repo
until an export copies it out.

    from webvideo import web_copy
    path = web_copy(Path("clip.mp4"), sound=False)    # cached MP4, or None if ffmpeg failed

Command line: tools/web-video.py.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
from pathlib import Path

VIDEO_EXTS = (".mp4", ".mov", ".m4v", ".webm")
RECIPE = "web-v1|h264|720p|30fps|crf30|slow|aac80k"
CACHE = Path(os.environ.get("ANIMATIC_WEB_VIDEO_CACHE",
                            Path.home() / ".cache" / "animatic" / "web-video"))


def ffmpeg_args(src: Path, dst: Path, sound: bool) -> list[str]:
    """The one recipe. Change it, and bump RECIPE so the cache rebuilds."""
    vf = "scale=w='min(1280,iw)':h='min(720,ih)':force_original_aspect_ratio=decrease:force_divisible_by=2"
    args = ["ffmpeg", "-v", "error", "-y", "-i", str(src), "-map", "0:v:0",
            "-vf", vf, "-fpsmax", "30",
            "-c:v", "libx264", "-preset", "slow", "-crf", "30",
            "-profile:v", "high", "-pix_fmt", "yuv420p",
            "-x264-params", "aq-mode=3",
            "-movflags", "+faststart", "-map_metadata", "-1"]
    if sound:
        args += ["-map", "0:a:0?", "-c:a", "aac", "-b:a", "80k", "-ac", "2"]
    else:
        args += ["-an"]
    return args + [str(dst)]


def cache_key(src: Path, sound: bool) -> str:
    """The recipe, the source's bytes and the sound choice: a copy of the same
    file anywhere (a build's `_media/`) hits the same entry."""
    h = hashlib.sha256(f"{RECIPE}|{int(sound)}|".encode())
    with open(src, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()[:20]


def web_copy(src: Path, sound: bool = False, quiet: bool = False) -> Path | None:
    """The cached web copy of `src`, encoding it first if needed."""
    src = Path(src)
    if not src.is_file() or not shutil.which("ffmpeg"):
        return None
    CACHE.mkdir(parents=True, exist_ok=True)
    dst = CACHE / f"{cache_key(src, sound)}.mp4"
    if dst.is_file() and dst.stat().st_size:
        return dst
    tmp = dst.with_suffix(".part.mp4")
    if not quiet:
        print(f"encode    : {src.name} -> web copy ({'sound' if sound else 'muted'})", flush=True)
    r = subprocess.run(ffmpeg_args(src, tmp, sound))
    if r.returncode or not tmp.is_file():
        tmp.unlink(missing_ok=True)
        return None
    tmp.replace(dst)
    return dst
