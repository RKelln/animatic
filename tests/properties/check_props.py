"""Property checks over the check suite itself (register-driven).

Every fixture is run through check.check_file (the T11 per-deck seam) with
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

import check as check_mod

from .common import err


def check(fx, errors: list) -> None:
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
