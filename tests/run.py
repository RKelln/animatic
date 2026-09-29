"""tests/run.py — the animatic golden + property suite (T10).

One command, one exit code:

    python3 tests/run.py                 # build all -> diff -> assert -> exit 0/1
    python3 tests/run.py --update-goldens   # re-bless expected/ from fresh builds
    python3 tests/run.py --verbose       # echo every build's stdout
    python3 tests/run.py --only cue      # run fixtures whose relpath contains 'cue'

Layers (spec: Verification):
  - fixtures/constructs/*.talk.md   one minimal file per frozen construct
  - fixtures/decks/<deck>/talk.md   composite decks (own media dirs + cards)
  - expected/<rel>/cues.json + media-manifest.json   byte goldens
  - properties/                     structural invariants (never goldened)
  - corpus_props                    the corpus harness (check 21) over a
    synthetic /tmp tree — real content roots are never committed
  - playback_props                  card `playback:` (check 29) over a /tmp
    deck built from generated clips
  - ingest_props                    ingest.py name matching over a /tmp deck

Per fixture profile the runner: builds twice into temp dirs and requires the
trees to be byte-identical (determinism, spec: Outputs — nav.json included);
diffs cues.json + media-manifest.json against expected/ (--update-goldens
re-blesses); runs the property modules (cues, nav, manifest, timing, html
views, check suite).  HTML is never byte-diffed.

Golden discipline: a changed builder behavior shows up as a golden diff that
must be understood; --update-goldens is the escape hatch, used after the
change is intentional.  Blessed only against green T01-T09 (the current
HEAD at bless time).
"""

from __future__ import annotations

import argparse
import hashlib
import io
import shutil
import sys
import tempfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

TESTS = Path(__file__).resolve().parent
REPO = TESTS.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(TESTS))

import build as build_mod  # noqa: E402
from properties import (check_props, corpus_props, cue_props, html_props,  # noqa: E402
                        ingest_props, manifest_props, nav_props, playback_props,
                        timing_props)
from properties.common import Fixture, load_meta_source  # noqa: E402

GOLDEN_FILES = ("cues.json", "media-manifest.json")


def discover() -> list:
    """Fixture talkfiles: flat constructs plus deck dirs under fixtures/."""
    fixtures = sorted(TESTS.glob("fixtures/constructs/*.talk.md"))
    fixtures += sorted(TESTS.glob("fixtures/decks/*/talk.md"))
    return fixtures


def expected_dir_for(talkfile: Path, profile: str = "base") -> Path:
    """expected/ mirrors the fixture: constructs/<stem>/ and decks/<deck>/,
    with per-profile subdirs (e.g. decks/<deck>/standin/) when a fixture
    builds more than one way."""
    base = TESTS / "expected" / talkfile.parent.relative_to(TESTS / "fixtures")
    if talkfile.parent.name == "constructs":
        base = base / talkfile.name.removesuffix(".talk.md")
    if profile != "base":
        base = base / profile
    return base


def build_profile(talkfile: Path, out: Path, remap: Path | None,
                  verbose: bool) -> None:
    argv = [str(talkfile), "--out", str(out)]
    if remap is not None:
        argv += ["--media-remap", str(remap)]
    sink = sys.stdout if verbose else io.StringIO()
    errsink = None if verbose else io.StringIO()
    with redirect_stdout(sink), redirect_stderr(errsink or sys.stderr):
        code = build_mod.main(argv)
    if code != 0:
        raise RuntimeError(f"build {talkfile} exited {code}")


def tree_hashes(root: Path) -> dict:
    out = {}
    for p in sorted(root.rglob("*")):
        if p.is_file():
            out[str(p.relative_to(root))] = hashlib.sha256(
                p.read_bytes()).hexdigest()
    return out


def diff_goldens(fx: Fixture, errors: list, update: bool) -> None:
    import difflib

    for name in GOLDEN_FILES:
        got = fx.out / name
        want = fx.expected_dir / name
        if update:
            want.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(got, want)
            continue
        if not want.is_file():
            err(errors, f"{name}: golden missing (run --update-goldens to "
                        f"bless): {want}")
            continue
        g = got.read_bytes()
        w = want.read_bytes()
        if g != w:
            a = want.read_text(encoding="utf-8").splitlines()
            b = got.read_text(encoding="utf-8").splitlines()
            diff = "\n".join(difflib.unified_diff(
                a, b, fromfile=str(want), tofile=str(got), n=2))
            err(errors, f"{name}: golden mismatch:\n{diff[:1600]}")


def err(errors: list, msg: str) -> None:
    errors.append(msg)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--update-goldens", action="store_true",
                    help="re-bless expected/ from fresh builds")
    ap.add_argument("--verbose", action="store_true",
                    help="echo build output")
    ap.add_argument("--only", default=None, metavar="SUBSTR",
                    help="run only fixtures whose path contains SUBSTR")
    args = ap.parse_args(argv)

    fixtures = discover()
    total_profiles = 0
    failed: list[str] = []
    passed: list[str] = []
    tmp = Path(tempfile.mkdtemp(prefix="animatic-t10-"))
    try:
        for talkfile in fixtures:
            rel = str(talkfile.relative_to(TESTS / "fixtures"))
            if args.only and args.only not in rel:
                continue
            deck_dir = talkfile.parent
            remaps = deck_dir / "remaps.yaml"
            profiles = [("base", None)]
            if remaps.is_file():
                profiles.append(("standin", remaps))
            for profile, remap in profiles:
                total_profiles += 1
                label = f"{rel} [{profile}]"
                errors: list = []
                meta, source_text = load_meta_source(talkfile)
                out_a = out_b = None
                try:
                    suffix = "-standin" if profile == "standin" else ""
                    out_a = tmp / "a" / Path(rel).parent / (talkfile.stem + suffix)
                    out_b = tmp / "b" / Path(rel).parent / (talkfile.stem + suffix)
                    shutil.rmtree(out_a, ignore_errors=True)
                    shutil.rmtree(out_b, ignore_errors=True)
                    build_profile(talkfile, out_a, remap, args.verbose)
                    build_profile(talkfile, out_b, remap, args.verbose)

                    # determinism: both builds byte-identical (spec: Outputs)
                    ha, hb = tree_hashes(out_a), tree_hashes(out_b)
                    if ha != hb:
                        only_a = sorted(set(ha) - set(hb))
                        only_b = sorted(set(hb) - set(ha))
                        err(errors, "determinism: build B differs from build "
                                    f"A ({only_a[:3]} {only_b[:3]})")

                    fx = Fixture(
                        talkfile=talkfile, out=out_a,
                        expected_dir=expected_dir_for(talkfile, profile),
                        profile=profile, remap=remap,
                        meta=meta, source_text=source_text)

                    diff_goldens(fx, errors, args.update_goldens)
                    for mod in (cue_props, manifest_props, nav_props,
                                html_props, check_props, timing_props):
                        mod.check(fx, errors)
                except Exception as exc:  # noqa: BLE001 — suite must not die
                    err(errors, f"suite error: {type(exc).__name__}: {exc}")

                if errors:
                    failed.append(label)
                    print(f"FAIL  {label}")
                    for e in errors[:12]:
                        print(f"      {e}")
                    if len(errors) > 12:
                        print(f"      ... and {len(errors) - 12} more")
                else:
                    passed.append(label)
                    assert out_a is not None
                    h = hashlib.sha256(
                        (out_a / "cues.json").read_bytes()).hexdigest()[:12]
                    h2 = hashlib.sha256(
                        (out_a / "media-manifest.json").read_bytes()
                    ).hexdigest()[:12]
                    print(f"ok    {label}  cues#{h} manifest#{h2}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # corpus harness (check 21 / T11): one synthetic corpus tree under /tmp —
    # real content roots are never committed, but the harness machinery is
    # regression-covered here (discovery, verdicts, drift, banks, determinism)
    corpus_errors: list = []
    corpus_props.check(corpus_errors)
    if corpus_errors:
        failed.append("corpus-harness")
        print(f"FAIL  corpus-harness")
        for e in corpus_errors[:12]:
            print(f"      {e}")
        if len(corpus_errors) > 12:
            print(f"      ... and {len(corpus_errors) - 12} more")
    else:
        passed.append("corpus-harness")
        print("ok    corpus-harness")

    # video playback (check 29): a throwaway deck built from generated clips,
    # because once/pingpong only mean something against real video files
    playback_errors: list = []
    playback_props.check(playback_errors)
    if playback_errors:
        failed.append("playback")
        print("FAIL  playback")
        for e in playback_errors[:12]:
            print(f"      {e}")
    else:
        passed.append("playback")
        print("ok    playback")

    # ingest name matching: a throwaway deck and inbox, --no-recover only
    ingest_errors: list = []
    ingest_props.check(ingest_errors)
    if ingest_errors:
        failed.append("ingest")
        print("FAIL  ingest")
        for e in ingest_errors[:12]:
            print(f"      {e}")
    else:
        passed.append("ingest")
        print("ok    ingest")

    print()
    print(f"profiles: {total_profiles}  passed: {len(passed)}  "
          f"failed: {len(failed)}")
    if failed:
        print("FAILED:")
        for f in failed:
            print(f"  - {f}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
