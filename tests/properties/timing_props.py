"""Property + unit checks over the timing clock (spec: Timing, check 19).

Two layers:

- **Artifact invariants**, over every fixture: each cue in cues.json carries a
  positive-float `est_seconds` that is at least the pure word-count time at the
  deck's speech rate, and the build never writes timing into `timing.yaml` (the
  sidecar holds deliberate values only; the estimate is regenerable and stays
  in cues.json).
- **The clock's behaviour**, on the fixtures that exist for it: check 19
  reports on a deck whose declared `dur` is far from the effective total
  (`timing-drift`) and stays silent when `dur` is inside the threshold
  (`timing-demo`); an authored override beats the estimate; a measured value
  beats both.  Plus direct unit assertions on `timing.py` (dur parsing, floors,
  the video hard floor, precedence, sidecar validation) — the parts a golden
  cannot pin.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

import yaml

import check as check_mod
import render
import talkparse
import timing

from .common import err

# Fixtures that exist for the clock (see tests/README.md).
DRIFT_FIXTURE = "timing-drift.talk.md"     # dur far from the estimate: reports
SILENT_FIXTURE = "timing-demo"             # dur inside the threshold: silent

EPS = 5e-4          # half a millisecond: the estimate rounds to 3 decimals


def check(fx, errors: list) -> None:
    _artifact_invariants(fx, errors)
    _units(errors)
    _fixture_clock(fx, errors)
    _check19_fixtures(fx, errors)


# ---------------------------------------------------------------------------
# Artifact invariants (every fixture)
# ---------------------------------------------------------------------------


def _artifact_invariants(fx, errors: list) -> None:
    cues = fx.cues()
    tt = timing.load(fx.deck_dir)
    wpm = tt.wpm
    for cue in cues.get("cues", []):
        cid = cue.get("id")
        est = cue.get("est_seconds")
        if est is None:
            err(errors, f"{fx.talkfile.name}: cue {cid} has no est_seconds "
                        f"(spec: Timing — every cue carries the estimate)")
            continue
        if isinstance(est, bool) or not isinstance(est, float):
            err(errors, f"{fx.talkfile.name}: cue {cid} est_seconds {est!r} is "
                        f"not a float")
            continue
        if not est > 0:
            err(errors, f"{fx.talkfile.name}: cue {cid} est_seconds {est!r} "
                        f"is not positive")
        if est != round(est, 3):
            err(errors, f"{fx.talkfile.name}: cue {cid} est_seconds {est!r} is "
                        f"not rounded to milliseconds (determinism)")
        words = timing.word_count(cue.get("script") or "")
        computed = (words / wpm) * 60.0
        if est + EPS < computed:
            err(errors, f"{fx.talkfile.name}: cue {cid} est_seconds {est} is "
                        f"below the pure read time {computed:.3f} "
                        f"({words} words at {wpm:g} wpm)")
        if cue.get("kind") == "black" and est + EPS < timing.FLOOR_BLACK:
            err(errors, f"{fx.talkfile.name}: cue {cid} black beat est_seconds "
                        f"{est} is below the black floor "
                        f"{timing.FLOOR_BLACK}")

    # The negative test: the build never writes the estimate into the sidecar.
    if (fx.out / timing.FILENAME).exists():
        err(errors, f"{fx.talkfile.name}: build wrote {timing.FILENAME} into "
                    f"the output — the estimate lives in cues.json, never in "
                    f"the sidecar (spec: Timing)")
    sidecar = fx.deck_dir / timing.FILENAME
    if sidecar.is_file():
        text = sidecar.read_text(encoding="utf-8")
        if "est_seconds" in text:
            err(errors, f"{sidecar}: timing.yaml carries the estimate — it "
                        f"holds authored/measured entries only (spec: Timing)")
        raw = yaml.safe_load(text) or {}
        extra = set(raw) - {"schema", "settings", "cues"}
        if extra:
            err(errors, f"{sidecar}: unexpected top-level keys {sorted(extra)}")
        entries = raw.get("cues") or {}
        if not isinstance(entries, dict):
            err(errors, f"{sidecar}: cues must be a mapping")
        else:
            for cid, entry in entries.items():
                if not isinstance(entry, dict):
                    err(errors, f"{sidecar}: {cid} is not a mapping")
                    continue
                keys = set(entry)
                if keys - {"seconds", "provenance"}:
                    err(errors, f"{sidecar}: {cid} carries keys beyond "
                                f"seconds/provenance: {sorted(keys)}")
                if entry.get("provenance") not in ("authored", "measured"):
                    err(errors, f"{sidecar}: {cid} provenance "
                                f"{entry.get('provenance')!r} is not "
                                f"authored/measured (never the estimate)")
        if timing.load(fx.deck_dir).problems:
            err(errors, f"{sidecar}: timing.yaml does not load cleanly: "
                        f"{timing.load(fx.deck_dir).problems}")


# ---------------------------------------------------------------------------
# Fixture-driven clock behaviour
# ---------------------------------------------------------------------------


def _fixture_clock(fx, errors: list) -> None:
    """The override story, on the fixture written for it."""
    if SILENT_FIXTURE not in str(fx.talkfile):
        return
    deck_dir = fx.deck_dir
    tt = timing.load(deck_dir)
    if tt.path is None or not tt.cues:
        err(errors, f"{deck_dir}: timing.yaml did not load any entries")
        return
    if tt.wpm == timing.DEFAULT_WPM:
        err(errors, f"{deck_dir}: fixture timing.yaml sets no non-default wpm — "
                    f"settings.wpm is untested end to end")
    talk = talkparse.build_talk(fx.talkfile)
    resolver = _resolver(talk)
    est = {f"{fx.slug}-{s.idx:03d}": render.cue_estimate(s, resolver, tt.wpm)
           for s in talk.screens}
    artifact = {c["id"]: c["est_seconds"] for c in fx.cues()["cues"]}
    for cid, value in est.items():
        if artifact.get(cid) != value:
            err(errors, f"cue {cid}: cues.json est_seconds {artifact.get(cid)!r} "
                        f"!= recomputed {value!r}")

    tiers = {}
    eff_total = 0.0
    est_total = 0.0
    for cid, value in est.items():
        seconds, tier = tt.effective(cid, value)
        tiers[cid] = tier
        eff_total += seconds
        est_total += value
    # an authored entry wins over the estimate for its cue ...
    authored = "authored" in tiers.values()
    measured = "measured" in tiers.values()
    if not (authored and measured):
        err(errors, f"{deck_dir}: fixture exercises "
                    f"{'authored' if authored else 'no authored'} and "
                    f"{'measured' if measured else 'no measured'} tiers — the "
                    f"override order is not covered")

    dur = timing.parse_dur(fx.meta.get("dur"))
    if dur is None:
        err(errors, f"{deck_dir}: fixture dur {fx.meta.get('dur')!r} is not "
                    f"parseable — it pins the silent case")
        return
    eff_div = abs(eff_total - dur) / dur
    if eff_div > timing.DIVERGENCE:
        err(errors, f"{deck_dir}: effective total {eff_total:.3f} vs dur "
                    f"{dur:.0f} diverges {eff_div:.0%} — the silent fixture "
                    f"must sit inside the {timing.DIVERGENCE:.0%} threshold")
    if abs(est_total - eff_total) < EPS:
        err(errors, f"{deck_dir}: overrides do not change the effective total "
                    f"({eff_total:.3f}) — the sidecar is not applied")


def _resolver(talk):
    import warnings

    from mediaresolve import MediaResolver
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return MediaResolver(talk_dir=Path(talk.source).parent, meta=talk.meta)


def _check19_fixtures(fx, errors: list) -> None:
    """check 19 fires on the divergent deck and stays silent on the matching
    one — and neither is a failure."""
    drift = DRIFT_FIXTURE in str(fx.talkfile)
    silent = SILENT_FIXTURE in str(fx.talkfile)
    if not (drift or silent):
        return
    report = check_mod.check_file(fx.talkfile, strict=False,
                                 cues_path=fx.out / "cues.json")
    found = [f for f in report.findings if f.check == 19]
    if report.exit_code != 0:
        err(errors, f"{fx.talkfile.name}: check 19 case exits "
                    f"{report.exit_code} — a timing report never fails a deck")
    if drift:
        if not found:
            err(errors, f"{fx.talkfile.name}: check 19 stayed silent on a "
                        f"deliberately divergent dur")
        for f in found:
            if f.severity != "report":
                err(errors, f"{fx.talkfile.name}: check 19 produced a "
                            f"{f.severity} — the clock reports, never warns "
                            f"or errors (spec: Timing)")
    if silent and found:
        err(errors, f"{fx.talkfile.name}: check 19 fired inside the "
                    f"{timing.DIVERGENCE:.0%} threshold: "
                    f"{[f.message for f in found]}")


# ---------------------------------------------------------------------------
# Unit assertions (timing.py — the parts no golden can pin)
# ---------------------------------------------------------------------------


def _units(errors: list) -> None:
    _unit_words(errors)
    _unit_dur(errors)
    _unit_floors(errors)
    _unit_precedence(errors)
    _unit_sidecar(errors)
    _unit_video(errors)


def _unit_words(errors: list) -> None:
    cases = [("", 0), ("one two three", 3), ("  ", 0), ("a-b c's", 2),
             ("- -- ,", 0), ("159 data centres.", 3)]
    for text, want in cases:
        got = timing.word_count(text)
        if got != want:
            err(errors, f"word_count({text!r}) = {got}, want {want}")


def _unit_dur(errors: list) -> None:
    cases = [
        ("~75 min", 4500.0), ("75", 4500.0), (75, 4500.0), ("~2 min", 120.0),
        ("1h30", 5400.0), ("90m", 5400.0), ("01:15:00", 4500.0), ("2:30", 150.0),
        ("1 day", None), ("an hour", None), ("", None), (None, None),
        ("0", None), (True, None), ([12], None),
    ]
    for value, want in cases:
        got = timing.parse_dur(value)
        if got != want:
            err(errors, f"parse_dur({value!r}) = {got!r}, want {want!r}")


def _unit_floors(errors: list) -> None:
    # a black beat floors at the black constant, never the beat constant
    black = timing.estimate_seconds(0, "black")
    if black != timing.FLOOR_BLACK or black == timing.FLOOR_BEAT:
        err(errors, f"black beat estimate {black}, want {timing.FLOOR_BLACK}")
    # a wordless screen is a beat
    beat = timing.estimate_seconds(0, "card")
    if beat != timing.FLOOR_BEAT:
        err(errors, f"wordless card estimate {beat}, want {timing.FLOOR_BEAT}")
    # an explicit (Beat.) note lifts a thin script to the beat floor
    noted = timing.estimate_seconds(2, "card", beat=True)
    if noted != timing.FLOOR_BEAT:
        err(errors, f"(Beat.) estimate {noted}, want {timing.FLOOR_BEAT}")
    # a credits read floors longer than a beat
    credits = timing.estimate_seconds(0, "credits", credits_read=True)
    if credits != timing.FLOOR_CREDITS:
        err(errors, f"credits read estimate {credits}, want "
                    f"{timing.FLOOR_CREDITS}")
    # words beat the floor when they take longer
    spoken = timing.estimate_seconds(150, "card", wpm=150.0)
    if spoken != 60.0:
        err(errors, f"150 words at 150 wpm = {spoken}, want 60.0")
    # a video's real duration is the hard floor
    video = timing.estimate_seconds(150, "media", video_seconds=120.0)
    if video != 120.0:
        err(errors, f"video floor: {video}, want 120.0")
    short_video = timing.estimate_seconds(300, "media", video_seconds=10.0)
    if short_video != 120.0:
        err(errors, f"computed time should win over a short video: "
                    f"{short_video}, want 120.0")
    # the speech rate is honoured
    fast = timing.estimate_seconds(150, "card", wpm=300.0)
    if fast != 30.0:
        err(errors, f"150 words at 300 wpm = {fast}, want 30.0")


def _unit_precedence(errors: list) -> None:
    if timing.effective(5.0) != (5.0, "estimated"):
        err(errors, f"effective(est) = {timing.effective(5.0)}")
    if timing.effective(5.0, authored=7.0) != (7.0, "authored"):
        err(errors, f"an authored override must beat the estimate")
    if timing.effective(5.0, authored=7.0, measured=6.5) != (6.5, "measured"):
        err(errors, f"a measured value must beat an authored override")
    if timing.effective(5.0, measured=6.5) != (6.5, "measured"):
        err(errors, f"a measured value must beat the estimate")


def _unit_sidecar(errors: list) -> None:
    with tempfile.TemporaryDirectory(prefix="animatic-timing-") as tmp:
        d = Path(tmp)
        # absent sidecar: defaults, no problems
        empty = timing.load(d)
        if empty.path is not None or empty.cues or empty.problems:
            err(errors, "a missing timing.yaml must load as empty defaults")
        if empty.wpm != timing.DEFAULT_WPM:
            err(errors, f"missing timing.yaml wpm {empty.wpm}")
        # a good sidecar
        (d / timing.FILENAME).write_text(
            "schema: animatic.timing.v1\n"
            "settings: {wpm: 160}\n"
            "cues:\n"
            "  deck-001: {seconds: 9.5, provenance: authored}\n"
            "  deck-002: {seconds: 4.0, provenance: measured}\n",
            encoding="utf-8")
        good = timing.load(d)
        if good.problems:
            err(errors, f"a well-formed timing.yaml reported problems: "
                        f"{good.problems}")
        if good.wpm != 160.0:
            err(errors, f"settings.wpm not read: {good.wpm}")
        if good.entry("deck-001") is None or \
                good.effective("deck-001", 3.0) != (9.5, "authored"):
            err(errors, "authored entry did not win over the estimate")
        if good.effective("deck-002", 3.0) != (4.0, "measured"):
            err(errors, "measured entry did not win over the estimate")
        if good.effective("deck-003", 3.0) != (3.0, "estimated"):
            err(errors, "an unlisted cue must fall through to the estimate")
        # a malformed sidecar reports and skips, never raises
        (d / timing.FILENAME).write_text(
            "schema: animatic.timing.v9\n"
            "settings: {wpm: -3}\n"
            "cues:\n"
            "  deck-001: {seconds: 9.5, provenance: estimated}\n"
            "  deck-002: {seconds: nope, provenance: authored}\n"
            "  deck-003: {seconds: 4.0, provenance: guessed}\n"
            "  deck-004: 12\n"
            "  deck-005: {seconds: 5.0, provenance: authored}\n",
            encoding="utf-8")
        bad = timing.load(d)
        if len(bad.problems) < 6:
            err(errors, f"malformed timing.yaml reported {len(bad.problems)} "
                        f"problems, want one per defect: {bad.problems}")
        if bad.wpm != timing.DEFAULT_WPM:
            err(errors, f"a bad wpm must fall back to "
                        f"{timing.DEFAULT_WPM:g}: {bad.wpm}")
        if set(bad.cues) != {"deck-005"}:
            err(errors, f"only the valid entry may survive: {sorted(bad.cues)}")


def _unit_video(errors: list) -> None:
    """ffprobe's real duration as the hard floor, against a generated file."""
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        return                                  # no ffmpeg here: nothing to pin
    with tempfile.TemporaryDirectory(prefix="animatic-timing-") as tmp:
        clip = Path(tmp) / "clip.mp4"
        try:
            subprocess.run(
                ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                 "color=c=black:s=64x64:d=1.5", "-pix_fmt", "yuv420p",
                 str(clip)], check=True, timeout=120,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except (OSError, subprocess.SubprocessError) as exc:
            err(errors, f"could not generate a test video: {exc}")
            return
        probed = timing.probe_video_seconds(clip)
        if probed is None or not 1.0 <= probed <= 2.5:
            err(errors, f"probe_video_seconds on a 1.5 s clip = {probed!r}")
        floored = timing.estimate_seconds(3, "media", video_seconds=probed)
        if floored != probed:
            err(errors, f"a video's duration must be the hard floor: "
                        f"{floored} vs {probed}")
        missing = timing.probe_video_seconds(Path(tmp) / "nope.mp4")
        if missing is not None:
            err(errors, f"probing a missing file returned {missing!r}, want None")
        # the cache must not change the value
        if timing.probe_video_seconds(clip) != probed:
            err(errors, "the probe cache changed the duration between calls")
