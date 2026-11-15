"""timing.py — the deck clock (spec: Timing).

Three provenance tiers, ordered by truth: **measured > authored > estimated**.

- `estimated` — arithmetic only: script word count / `wpm` * 60, floored per
  screen kind (a black beat, a beat screen, a credits read; a video file's
  real duration is a hard floor).  Emitted as `est_seconds` on every cue in
  `cues.json`.
- `authored` — a hand override in the deck-local `timing.yaml` sidecar
  (`animatic.timing.v1`): cue id -> {seconds, provenance}.
- `measured` — real timing from a recording or a test read: the alignment
  tooling (not built yet) would write the same sidecar with
  `provenance: measured`.  Recognized here, never produced here.

This module is the sidecar reader plus the arithmetic and nothing else.  The
screen-shaped half of the estimate — which words a cue speaks, which kind it
is, whether its media file is a video — belongs to the parse model, so it
lives in render.py (`cue_estimate`); every caller (render, check 19) goes
through that one function, and no estimate is ever computed twice.

`timing.yaml` carries deliberate overrides and real measurements only: the
estimate is never echoed back into it (regenerable, deterministic — that is
what `cues.json` is for).

The clock is advisory: the estimate is crude by design, so a divergence from
the declared `dur` is reported (check 19, never a warning or an error) and the
build never fails on it.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

SCHEMA = "animatic.timing.v1"
FILENAME = "timing.yaml"

# Speech rate.  A placeholder constant, not sacred: public speaking runs about
# 130-150 wpm.  Tunable per deck via timing.yaml `settings.wpm`.
DEFAULT_WPM = 150.0

# Floor values (seconds) — built-in defaults, tuned after first use.  They are
# deliberately not spec'd: the spec names the screen kinds, not the numbers.
FLOOR_BLACK = 2.0        # a black beat: deliberate silence, nothing to read
FLOOR_BEAT = 3.0         # a beat screen: a visual moment with no words
FLOOR_CREDITS = 8.0      # a credits read (end roll), longer than a beat

# Effective total vs declared `dur`: report past this relative divergence.
DIVERGENCE = 0.30

# Provenance tiers, in truth order (most true first).
TIERS = ("measured", "authored", "estimated")

# Words, for the estimate: a token must start alphanumeric (a bare dash or a
# stray punctuation mark is not a word).
_WORD_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9'\u2019-]*")

# `dur` parsing.  Accepted: "~75 min", "75", "1h30", "1 hour 15 min",
# "01:15:00", "90s".  A bare number is read as minutes.
_DUR_UNIT_SECONDS = {
    "h": 3600.0, "hr": 3600.0, "hrs": 3600.0, "hour": 3600.0, "hours": 3600.0,
    "m": 60.0, "min": 60.0, "mins": 60.0, "minute": 60.0, "minutes": 60.0,
    "s": 1.0, "sec": 1.0, "secs": 1.0, "second": 1.0, "seconds": 1.0,
}
_NEXT_UNIT = {"h": "m", "m": "s", "s": "s"}
_DUR_PAIR_RE = re.compile(r"(\d+(?:\.\d+)?)\s*([a-z]*)")
_DUR_CLOCK_RE = re.compile(r"\d+(?:\.\d+)?")

_PROBE_CACHE: dict = {}


@dataclass
class Entry:
    """One deliberate timing.yaml value: seconds + where it came from."""

    seconds: float
    provenance: str              # 'authored' | 'measured'


@dataclass
class Timing:
    """A deck's timing sidecar, loaded.  Absent sidecar = empty (all tiers
    fall through to the estimate)."""

    wpm: float = DEFAULT_WPM
    cues: dict = field(default_factory=dict)      # cue id -> Entry
    path: Optional[Path] = None
    problems: list = field(default_factory=list)  # malformed sidecar rows

    def entry(self, cue_id: str) -> Optional[Entry]:
        return self.cues.get(cue_id)

    def effective(self, cue_id: str, est: float) -> tuple[float, str]:
        """The cue's effective seconds and the tier that decided them."""
        e = self.cues.get(cue_id)
        if e is None:
            return effective(est)
        if e.provenance == "measured":
            return effective(est, measured=e.seconds)
        return effective(est, authored=e.seconds)


def effective(est: float, *, authored: Optional[float] = None,
              measured: Optional[float] = None) -> tuple[float, str]:
    """Per-cue override order: measured > authored > estimated (spec: Timing)."""
    if measured is not None:
        return float(measured), "measured"
    if authored is not None:
        return float(authored), "authored"
    return float(est), "estimated"


def word_count(text: str) -> int:
    """Words in a cue's script (feeds the estimate)."""
    return len(_WORD_RE.findall(text or ""))


def parse_dur(value) -> Optional[float]:
    """A frontmatter `dur` in seconds, or None when it is not a duration.

    `dur` is free text and optional (spec: Frontmatter — recommended,
    unenforced): a value this cannot read simply means check 19 has nothing
    to compare against, never an error.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value) * 60.0 if value > 0 else None
    if not isinstance(value, str):
        return None
    s = value.strip().lstrip("~≈").strip().lower()
    if not s:
        return None
    if ":" in s:
        parts = [p.strip() for p in s.split(":")]
        if not 1 <= len(parts) <= 3:
            return None
        if not all(_DUR_CLOCK_RE.fullmatch(p) for p in parts):
            return None
        total = 0.0
        for i, part in enumerate(reversed(parts)):
            total += float(part) * (60.0 ** i)
        return total if total > 0 else None
    pairs = _DUR_PAIR_RE.findall(s)
    if not pairs:
        return None
    total = 0.0
    unit = None
    for num, raw_unit in pairs:
        if raw_unit:
            if raw_unit not in _DUR_UNIT_SECONDS:
                return None
            unit = raw_unit
        elif unit is not None:
            unit = _NEXT_UNIT.get(unit, unit)     # "1h30" -> 1 h + 30 min
        else:
            unit = "m"                            # a bare number is minutes
        total += float(num) * _DUR_UNIT_SECONDS[unit]
    return total if total > 0 else None


def floor_for(kind: str, *, words: int, video_seconds: Optional[float] = None,
              credits_read: bool = False, beat: bool = False) -> float:
    """The floor this screen kind imposes (spec: Timing — floors are built-in
    defaults).  A video file's real duration is the hard floor."""
    if kind == "black":
        floor = FLOOR_BLACK
    elif credits_read:
        floor = FLOOR_CREDITS
    elif beat or words == 0:
        floor = FLOOR_BEAT
    else:
        floor = 0.0
    if video_seconds is not None:
        floor = max(floor, float(video_seconds))
    return floor


def estimate_seconds(words: int, kind: str, *,
                     video_seconds: Optional[float] = None,
                     wpm: float = DEFAULT_WPM,
                     credits_read: bool = False,
                     beat: bool = False,
                     timer_seconds: Optional[int] = None,
                     timer_armed: bool = False) -> float:
    """The `estimated` tier for one cue: max(computed, floor), rounded to
    milliseconds so the artifact is byte-stable across runs.

    A countdown timer counts in full.  A plain timer starts on arrival, so the
    words are spoken while it runs: the longer of the two.  A revealed timer
    (`timer_armed`) starts on a next-press after the words: the two add.  A
    video's real duration is still a floor."""
    computed = (float(words) / wpm) * 60.0 if words > 0 and wpm > 0 else 0.0
    if timer_seconds:
        computed = (computed + timer_seconds if timer_armed
                    else max(computed, float(timer_seconds)))
        if words == 0:
            return round(max(computed, float(video_seconds or 0.0)), 3)
    floor = floor_for(kind, words=words, video_seconds=video_seconds,
                      credits_read=credits_read, beat=beat)
    return round(max(computed, floor), 3)


def estimate_span_parent(base: float, timer_seconds: int, inner: float, *,
                         armed: bool = False) -> float:
    """The `estimated` tier for a screen whose countdown is continued below it
    (`[timer]`, spec: Timer screens, "Continued timers").

    `base` is the screen's own estimate without the timer (words, floors, video)
    and `inner` the estimated seconds of the screens in its span, which are spent
    while the countdown runs.  The span as a whole lasts the countdown, or the
    talk inside it if that runs longer.  A plain timer runs while this screen's
    own words are spoken, so the screen takes max(base, timer - inner); a
    revealed one starts after them: base + max(timer - inner, 0)."""
    left = float(timer_seconds) - inner
    return round(base + max(left, 0.0) if armed else max(base, left), 3)


def probe_video_seconds(path) -> Optional[float]:
    """A media file's real duration via ffprobe, or None.

    None is not an error: no ffprobe, no file, an unreadable container, or a
    stream with no duration all mean "no hard floor", and the estimate stands
    on its own.  Cached per (path, size, mtime) so a build probes each file
    once and stays fast.
    """
    if shutil.which("ffprobe") is None:
        return None
    p = Path(path)
    try:
        st = p.stat()
    except OSError:
        return None
    key = (str(p), st.st_size, int(st.st_mtime))
    if key in _PROBE_CACHE:
        return _PROBE_CACHE[key]
    value: Optional[float] = None
    try:
        proc = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(p)],
            capture_output=True, text=True, timeout=15, check=False)
        if proc.returncode == 0:
            raw = proc.stdout.strip().splitlines()
            if raw:
                seconds = float(raw[0])
                if seconds > 0:
                    value = round(seconds, 3)
    except (OSError, ValueError, subprocess.SubprocessError):
        value = None
    _PROBE_CACHE[key] = value
    return value


def probe_video_size(path) -> Optional[tuple]:
    """A video's (width, height) in pixels via ffprobe, or None.

    Same contract as `probe_video_seconds`: no ffprobe, no file or an unreadable
    container is "unknown", never an error, and the caller falls back to
    treating the video as the whole frame. Cached per (path, size, mtime)."""
    if shutil.which("ffprobe") is None:
        return None
    p = Path(path)
    try:
        st = p.stat()
    except OSError:
        return None
    key = ("size", str(p), st.st_size, int(st.st_mtime))
    if key in _PROBE_CACHE:
        return _PROBE_CACHE[key]
    value = None
    try:
        proc = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height", "-of", "csv=p=0:s=x", str(p)],
            capture_output=True, text=True, timeout=15, check=False)
        if proc.returncode == 0 and "x" in proc.stdout:
            w, h = proc.stdout.strip().splitlines()[0].split("x")[:2]
            if int(w) > 0 and int(h) > 0:
                value = (int(w), int(h))
    except (OSError, ValueError, subprocess.SubprocessError):
        value = None
    _PROBE_CACHE[key] = value
    return value


def load(deck_dir) -> Timing:
    """Read `<deck_dir>/timing.yaml` when present.  Never raises: malformed
    rows land in `problems` (surfaced by check 19 as reports) and are skipped,
    so a broken sidecar can never break a build."""
    path = Path(deck_dir) / FILENAME
    tt = Timing()
    if not path.is_file():
        return tt
    tt.path = path
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        tt.problems.append(f"timing.yaml is unreadable ({exc}) — no timing "
                           f"overrides applied (spec: Timing)")
        return tt
    if raw is None:
        return tt                                  # empty sidecar: no overrides
    if not isinstance(raw, dict):
        tt.problems.append("timing.yaml must be a mapping of schema/settings/"
                           "cues (spec: Timing)")
        return tt
    schema = raw.get("schema")
    if schema is not None and schema != SCHEMA:
        tt.problems.append(f"timing.yaml schema is {schema!r}, expected "
                           f"{SCHEMA!r} — entries read anyway (spec: Timing)")
    settings = raw.get("settings")
    if settings is not None and not isinstance(settings, dict):
        tt.problems.append("timing.yaml settings must be a mapping "
                           "(spec: Timing)")
    elif isinstance(settings, dict) and settings.get("wpm") is not None:
        wpm = settings.get("wpm")
        if isinstance(wpm, bool) or not isinstance(wpm, (int, float)) \
                or wpm <= 0:
            tt.problems.append(f"timing.yaml settings.wpm is {wpm!r}, not a "
                               f"positive number — using {DEFAULT_WPM:g} "
                               f"(spec: Timing)")
        else:
            tt.wpm = float(wpm)
    cues = raw.get("cues")
    if cues is None:
        return tt
    if not isinstance(cues, dict):
        tt.problems.append("timing.yaml cues must be a mapping of cue id -> "
                           "{seconds, provenance} (spec: Timing)")
        return tt
    for cue_id, entry in cues.items():
        cid = str(cue_id)
        if not isinstance(entry, dict):
            tt.problems.append(f"timing.yaml {cid}: entry must be a mapping of "
                               f"seconds/provenance (spec: Timing)")
            continue
        seconds = entry.get("seconds")
        if isinstance(seconds, bool) or not isinstance(seconds, (int, float)) \
                or seconds <= 0:
            tt.problems.append(f"timing.yaml {cid}: seconds {seconds!r} is not "
                               f"a positive number — entry ignored "
                               f"(spec: Timing)")
            continue
        provenance = str(entry.get("provenance", "")).strip()
        if provenance == "estimated":
            tt.problems.append(f"timing.yaml {cid}: provenance 'estimated' — "
                               f"the estimate is never written to the sidecar; "
                               f"entry ignored (spec: Timing)")
            continue
        if provenance not in TIERS:
            tt.problems.append(f"timing.yaml {cid}: provenance {provenance!r} "
                               f"is not one of {'/'.join(TIERS)} — entry "
                               f"ignored (spec: Timing)")
            continue
        tt.cues[cid] = Entry(seconds=float(seconds), provenance=provenance)
    return tt
