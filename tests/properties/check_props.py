"""Property checks over the check suite itself (register-driven).

Every fixture is run through check.check_file (the per-deck seam) with
and without --strict and with the built cues.json, so the artifact
assertions (checks 17 + 18: no machine paths, lexical==ordinal ids) fire on
every fixture, not just on goldens:

- clean fixtures (no `test-expect`): strict exit 0 — zero warnings, zero
  fatals; infos/reports may exist (the taxonomy says they never fail), but
  the fixture set is designed so clean decks carry none.
- tolerant fixtures (`test-expect: warned`): non-strict exit 0 with at
  least one warning finding, strict exit 1, no fatal finding — the warning
  is the point of the fixture and the golden pins its exact text.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from types import SimpleNamespace

import check as check_mod

from .common import err


def check(fx, errors: list) -> None:
    _unit_genlog(errors)
    cues_path = fx.out / "cues.json"

    relaxed = check_mod.check_file(
        fx.talkfile, strict=False, cues_path=cues_path)
    strict = check_mod.check_file(
        fx.talkfile, strict=True, cues_path=cues_path)

    if relaxed.parse_error:
        err(errors, f"parse error: {relaxed.parse_error}")
    if relaxed.exit_code != 0:
        fatal = [f.render() for f in relaxed.findings
                 if f.severity == "fatal"]
        err(errors, f"non-strict check exits {relaxed.exit_code}: "
                    f"{fatal[:3] or [f.render() for f in relaxed.findings[:3]]}")

    if fx.tolerant:
        if strict.exit_code != 1:
            err(errors, f"tolerant fixture: strict check exits "
                        f"{strict.exit_code}, expected 1 (warnings escalate)")
        warns = [f for f in relaxed.findings if f.severity == "warning"]
        if not warns:
            err(errors, "tolerant fixture produced no warning findings")
        if any(f.severity == "fatal" for f in relaxed.findings):
            err(errors, "tolerant fixture carries a fatal finding")
    else:
        if strict.exit_code != 0:
            warns = [f.render() for f in strict.findings
                     if f.severity == "warning"]
            if warns:
                err(errors, f"clean fixture is not strict-clean: "
                            f"{warns[:3]}")
            else:
                err(errors, f"clean fixture exits {strict.exit_code} "
                            f"under --strict without warnings")


# ---------------------------------------------------------------------------
# Unit: checks 13/14 read every shape a real gen-log records attempts in
# ---------------------------------------------------------------------------

# Every shape a real gen-log uses: a spec header, an
# ingest.py batch, a bulk `###` block, a rename, a split, and a promote line
# (which must NOT count as a record, and must not break monotonic order).
# Two genuine drifts are planted, and they must be the only findings.
GENLOG = """\
## 2026-09-01 · spec-a · a1
intent: fixture

## 2026-09-02 · ingest · 2 file(s)
- a1 ← `raw_one.mp4` (slug ingested, matched by new)
  - fal: minimax · 5s
- a2 ← `raw_two.mp4` (slug ingested, matched by exact)

## 2026-09-03 · animatic ingest · 2 slugs / 3 takes
### old-name — 1 take(s)
- a1 ← `old_name_x.mp4` (5 MB)
### split-src — 2 take(s)
- a1 ← `split_1.mp4` (5 MB)
- a2 ← `split_2.mp4` (5 MB)

## 2026-09-04 · rename pass
- old-name-a1.<ext> -> renamed-new-a1.<ext>
- old-name-a1.<ext> -> renamed-new-a1.<ext>
- split: split-src-a1 -> new slug `split-dst`

## 2026-09-05 · promote · ingested
- a1 ← `ingested-a1.mp4` promoted to `media/ingested/ingested.mp4` (card `approved:`, status approved)

## 2026-09-06 · ghost · a1
intent: an entry whose file is gone (a genuine drift)
"""

GENLOG_FILES = ["spec-a/attempts/spec-a-a1.mp4",
                "ingested/attempts/ingested-a1.mp4", "ingested/attempts/ingested-a2.mp4",
                "renamed-new/attempts/renamed-new-a1.mp4",
                "split-src/attempts/split-src-a2.mp4",
                "split-dst/attempts/split-dst-a1.mp4",
                "unlogged/attempts/unlogged-a1.mp4"]      # a file with no entry (genuine)

_GENLOG_DONE = []


def _unit_genlog(errors: list) -> None:
    if _GENLOG_DONE:
        return                                   # once per suite run is enough
    _GENLOG_DONE.append(True)
    with tempfile.TemporaryDirectory(prefix="animatic-genlog-") as tmp:
        media = Path(tmp)
        for rel in GENLOG_FILES:
            (media / rel).parent.mkdir(parents=True, exist_ok=True)
            (media / rel).write_bytes(b"")
        (media / "gen-log.md").write_text(GENLOG, encoding="utf-8")
        report = check_mod.Report(source=str(media / "talk.md"))
        check_mod.check_13_14_attempts(None, SimpleNamespace(media_dir=media), report)
        got = sorted(f.message.split(" — ")[0] for f in report.findings)
        want = sorted(["attempt file with no gen-log entry: unlogged/attempts/unlogged-a1.mp4",
                       "gen-log entry with no attempt file on disk: ghost a1 (media/gen-log.md line 24)"])
        if got != want:
            err(errors, f"check 13/14 over every gen-log shape: got {got}, want {want}")
