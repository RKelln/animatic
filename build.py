"""build.py — animatic builder spike (E2).

One talkfile in, three views out:
    out/present/index.html      own-pager deck (VO in speaker notes)
    out/present/presenter.html  speaker UI for the second window ('s')
    out/document/index.html     static HTML handout (VO as prose; print CSS for PDF)

...and three generated sidecars:
    out/cues.json               ordered slide id -> script text (future controller)
    out/nav.json                cue id -> source line range, movement, kind
    out/media-manifest.json     slug resolution audit

Usage:
    python3 build.py TALKFILE [--out OUTDIR]
    python3 build.py TALKFILE --watch    # rebuild on every save
    python3 build.py --corpus [ROOT]     # corpus check (register 21, T11)

Example (specimen):
    python3 build.py ~/talks/decks/L01-opening-talk/talk.md

--corpus without ROOT uses the corpus.yaml content roots; with ROOT it scans
that directory (per-deck pass/fail + cross-deck slug collisions + tag drift
and coverage reports).  The builder itself is never used in corpus mode —
the corpus check parses and checks every deck read-only and never writes
into a content root.

The specimen talkfile and its media dir are READ-ONLY inputs: this builder
never writes outside OUTDIR.  Deterministic output; out/ is gitignored.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

import yaml

import render
import talkparse
from mediaresolve import MediaResolver, expand_pools
from render import (cited_sources, render_cues, render_document, render_manifest, render_nav,
                    render_present, render_presenter)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("talkfile", nargs="?", help="path to the talkfile "
                    "(markdown); omit when --corpus is used")
    ap.add_argument("--out", default="out", help="output directory (default: out/)")
    ap.add_argument("--corpus", nargs="?", const="__config__", metavar="ROOT",
                    help="corpus mode (check 21): with ROOT, scan that "
                         "directory; without, use the corpus.yaml content "
                         "roots.  Exclusive with TALKFILE.")
    ap.add_argument("--handout-figures", default=None, metavar="WIDTH",
                    help="handout figure width: capped (default), full, or n%% "
                         "(overrides frontmatter handout-figures)")
    ap.add_argument("--no-handout-pools", action="store_true",
                    help="leave pool-card pictures (random art from a folder) "
                         "out of the handout; slides keep them "
                         "(frontmatter: handout-pools: off)")
    ap.add_argument("--no-handout-placeholders", action="store_true",
                    help="leave the grey box for a card with no picture yet "
                         "out of the handout "
                         "(frontmatter: handout-placeholders: off)")
    ap.add_argument("--keep", action="store_true",
                    help="do not wipe the output directory first")
    ap.add_argument("--theme", default=None,
                    help="override the talkfile's theme: frontmatter "
                         "(e.g. --theme lecture) for style comparisons")
    ap.add_argument("--media-remap", default=None, metavar="YAML",
                    help="slug -> file stand-in map for unproduced media "
                         "(see remaps/l01-standins.yaml); real art always "
                         "beats a stand-in")
    ap.add_argument("--link-media", action="store_true",
                    help="symlink media into OUT/_media instead of copying it: "
                         "for throwaway and test builds (no disk cost), not "
                         "for a folder you will move or share")
    ap.add_argument("--watch", action="store_true",
                    help="stay running and rebuild whenever the talkfile, a "
                         "file beside it, its media/ dir or the remap changes; "
                         "open pages reload themselves after each build")
    ap.add_argument("--lease", default=None, metavar="PATH",
                    help="with --watch: stop once PATH's mtime is older than "
                         "--lease-timeout. A watcher must not outlive the "
                         "process that started it (pull-deck.sh heartbeats this)")
    ap.add_argument("--lease-timeout", type=float, default=60.0, metavar="SECS",
                    help="how stale the --lease heartbeat may get (default 60)")
    args = ap.parse_args(argv)

    if args.lease and not args.watch:
        ap.error("--lease only means something with --watch")

    if args.corpus is not None:
        if args.talkfile:
            ap.error("--corpus is exclusive with TALKFILE")
        import check
        root = None if args.corpus == "__config__" else args.corpus
        return check.corpus_main(root)

    if not args.talkfile:
        ap.error("a TALKFILE is required (or use --corpus [ROOT])")
    talk_path = Path(args.talkfile).expanduser().resolve()
    if not talk_path.is_file():
        print(f"error: talkfile not found: {talk_path}", file=sys.stderr)
        return 2
    if args.watch:
        return watch(talk_path, args)
    return build(talk_path, args)


def build(talk_path: Path, args) -> int:
    talk = talkparse.build_talk(talk_path)
    if args.theme:
        talk.meta["theme"] = args.theme
    resolver = MediaResolver(talk_dir=talk_path.parent, meta=talk.meta)
    resolver.link_media = bool(getattr(args, "link_media", False))
    expand_pools(talk, resolver)
    if args.media_remap:
        remap_path = Path(args.media_remap).expanduser().resolve()
        if not remap_path.is_file():
            print(f"error: media-remap file not found: {remap_path}",
                  file=sys.stderr)
            return 2
        raw = yaml.safe_load(remap_path.read_text(encoding="utf-8")) or {}
        base = remap_path.parent
        resolver.remap = {}
        for k, v in raw.items():
            if not isinstance(v, str):
                continue
            p = Path(v) if Path(v).is_absolute() else base / v
            resolver.remap[str(k)] = p.resolve()
        gone = [k for k, p in resolver.remap.items() if not p.is_file()]
        for k in gone:
            del resolver.remap[k]
        if gone:
            print(f"warn      : media-remap file(s) missing, ignored: "
                  f"{', '.join(gone)}")

    out = Path(args.out).expanduser().resolve()
    if out.exists():
        if not args.keep:
            shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)

    media_refs = referenced_media(talk, resolver)
    resolver.validate_steps()
    resolver.publish(out, [r.slug for r in media_refs])
    for _slug, msg in resolver.playback_issues:
        print(f"warn      : check 29: {msg}")
    for _slug, msg in resolver.steps_issues:
        print(f"warn      : check 33: {msg}")
    for _slug, msg in resolver.pool_issues:
        print(f"warn      : check 41: {msg}")
    for scr, _line, msg in render.step_count_notes(talk, resolver):
        print(f"warn      : check 34: {render.deck_slug(talk)}-{scr.idx:03d}: {msg}")
    for scr, _line, msg in render.next_mark_notes(talk, resolver):
        print(f"warn      : check 40: {render.deck_slug(talk)}-{scr.idx:03d}: {msg}")

    cites = talk.meta.get("cites")
    if isinstance(cites, dict):
        bare = [c["id"] for c in cited_sources(talk) if not str(cites.get(c["id"], "")).strip()]
        if bare:
            print(f"warn      : handout Sources omits {len(bare)} cited id(s) "
                  f"with no `cites:` entry: {', '.join(bare)}")

    present = render_present(talk, resolver, out / "present")
    presenter = render_presenter(talk, resolver, out / "present")
    document = render_document(talk, resolver, out / "document", figures=args.handout_figures,
                               pools=False if args.no_handout_pools else None,
                               placeholders=False if args.no_handout_placeholders else None)
    cues = render_cues(talk, resolver, out)
    nav = render_nav(talk, out)
    manifest = render_manifest(talk, resolver, out)

    print(f"talk      : {talk.source}")
    print(f"title     : {talk.meta.get('title', '')}")
    print(f"movements : {len(talk.movements)} "
          f"({', '.join(str(m.index) for m in talk.movements)})")
    for virtual, fname, line in resolver.pool_log:
        print(f"pool      : {virtual} <- {fname or 'NO FILE'} (line {line})")
    print(f"screens   : {len(talk.screens)} (cues); "
          f"opening={sum(1 for s in talk.screens if s.movement == 0)}")
    roles = {r: 0 for r in ("stat", "lower", "credits")}
    for s in talk.screens:
        for b in s.blocks:
            if b.kind in roles:
                roles[b.kind] += 1
    empty_script = 0
    said_lists = 0
    for s in talk.screens:
        has_script = any((b.kind == "vo" and b.text.strip()) or b.spoken
                         for b in s.blocks)
        if not has_script:
            empty_script += 1
        said_lists += sum(1 for b in s.blocks if b.kind == "list" and b.spoken)
    print(f"roles     : stat={roles['stat']} lower={roles['lower']} "
          f"credits={roles['credits']} (payloads)")
    print(f"lists     : {said_lists} list(s) read aloud (spoken voice-over "
          f"before them — spec: Text, Spoken lists)")
    print(f"beats     : {empty_script} screen(s) carry no script (card/media "
          f"beat with no VO — see cues.json)")
    found = [r for r in media_refs if r.found]
    missing = [r for r in media_refs if not r.found]
    print(f"media     : {len(media_refs)} referenced slugs; "
          f"found={len(found)} placeholder={len(missing)}")
    for scr in talk.screens:
        sref = render.screen_steps(scr, resolver)
        if sref is not None:
            print(f"steps     : {sref.slug}: {len(sref.steps)} steps "
                  f"(handout: {render.handout_label(sref)}) [{render.deck_slug(talk)}-{scr.idx:03d}]")
    if talk.warnings:
        print("warnings  :")
        for w in talk.warnings:
            print(f"  - {w}")
    print(f"written   : {present}")
    print(f"           : {presenter}")
    print(f"           : {document}")
    print(f"           : {cues}")
    print(f"           : {nav}")
    print(f"           : {manifest}")
    return 0


def watched_files(talk_path: Path, args) -> dict:
    """mtime/size snapshot of every input a rebuild would read: the talkfile
    and its siblings (cards.yaml, timing.yaml, style.md ...), everything under
    media/, and the remap file.  Polled, not inotify: stdlib only, and a stat
    of ~1k files every half second is cheap."""
    paths = [p for p in talk_path.parent.iterdir() if p.is_file()]
    media = talk_path.parent / "media"
    if media.is_dir():
        paths += [p for p in media.rglob("*") if p.is_file()]
    if args.media_remap:
        paths.append(Path(args.media_remap).expanduser().resolve())
    try:                                  # files pulled in by `include:`
        paths += talkparse.build_talk(talk_path).includes
    except Exception:                     # a half-saved talkfile: watch the rest
        pass
    snap = {}
    for p in paths:
        try:
            st = p.stat()
        except OSError:
            continue
        snap[p] = (st.st_mtime_ns, st.st_size)
    return snap


# Injected only under --watch, so plain builds keep their exact bytes.  The
# page re-adds a <script> for ../_watch.js every second (a script tag, not
# fetch, so it works from file:// as well as a localhost server) and reloads
# when the stamp in it changes.  The hash (#N) survives the reload, so the deck
# stays on its slide; the presenter re-syncs through its ready handshake.
RELOAD_SNIPPET = """<script>/* animatic --watch: auto-reload */
(function () {
  var seen = null;
  window.__animaticWatch = function (stamp) {
    if (seen === null) seen = stamp;
    else if (stamp !== seen) location.reload();
  };
  function poll() {
    var s = document.createElement("script");
    s.src = "../_watch.js?" + Date.now();
    s.onload = s.onerror = function () { s.remove(); };
    document.head.appendChild(s);
  }
  poll();
  setInterval(poll, 1000);
})();
</script>
"""


def inject_reload(out: Path, stamp: str) -> None:
    """Add RELOAD_SNIPPET to every page in OUTDIR, then write the stamp.  The
    stamp goes last, so an open page only reloads once the build is whole."""
    for page in sorted(out.glob("*/*.html")):
        html = page.read_text(encoding="utf-8")
        i = html.rfind("</body>")
        if i < 0:
            continue
        page.write_text(html[:i] + RELOAD_SNIPPET + html[i:], encoding="utf-8")
    (out / "_watch.js").write_text(
        f"window.__animaticWatch && window.__animaticWatch({stamp!r});\n",
        encoding="utf-8")


def watch(talk_path: Path, args, interval: float = 0.5) -> int:
    """Rebuild on every change until Ctrl-C.  A failed build prints its
    traceback and waits for the next save; it never ends the watch."""
    import time
    import traceback

    # A lease is a heartbeat someone else writes; when it stops moving, whoever
    # asked for this build is gone (ctrl-c cannot reach us from another machine,
    # and a SIGKILLed puller leaves no chance to say goodbye). So the watcher
    # stops itself: the alternative is a build nobody is watching, still
    # stamping _watch.js into a deck that might get carried to a venue.
    lease = Path(args.lease).expanduser() if args.lease else None
    started = time.monotonic()

    def lease_stale() -> bool:
        if lease is None:
            return False
        try:
            age = time.time() - lease.stat().st_mtime
        except OSError:            # no beat yet: give the starter one window
            return (time.monotonic() - started) > args.lease_timeout
        return age > args.lease_timeout

    def run(changed):
        stamp = time.strftime("%H:%M:%S")
        if changed:
            names = ", ".join(sorted(p.name for p in changed)[:5])
            more = f" (+{len(changed) - 5})" if len(changed) > 5 else ""
            print(f"\n[{stamp}] changed: {names}{more}")
        t0 = time.monotonic()
        # build() empties OUTDIR first, so a browser reload mid-build would
        # 404.  Build beside it and swap the finished tree in with a rename.
        final = Path(args.out).expanduser().resolve()
        stage = None
        if not args.keep:
            stage = final.with_name(f".{final.name}.building")
            shutil.rmtree(stage, ignore_errors=True)
            args.out = str(stage)
        try:
            rc = build(talk_path, args)
            if rc == 0:
                inject_reload(stage or final, f"{time.time_ns()}")
                if stage is not None:
                    old = final.with_name(f".{final.name}.old")
                    shutil.rmtree(old, ignore_errors=True)
                    if final.exists():
                        final.rename(old)
                    stage.rename(final)
                    shutil.rmtree(old, ignore_errors=True)
        except Exception:
            traceback.print_exc()
            rc = 1
        finally:
            args.out = str(final)
        status = "ok" if rc == 0 else f"FAILED (exit {rc})"
        print(f"[{time.strftime('%H:%M:%S')}] build {status} in "
              f"{time.monotonic() - t0:.1f}s; watching {talk_path.parent} "
              f"(Ctrl-C to stop)", flush=True)

    snap = watched_files(talk_path, args)
    run(None)
    try:
        while True:
            if lease_stale():
                print(f"\nlease stale ({args.lease_timeout:g}s without a "
                      f"heartbeat): nothing is pulling this build. Stopping.")
                return 0
            time.sleep(interval)
            now = watched_files(talk_path, args)
            if now == snap:
                continue
            # editors save in several writes (temp file, rename); wait until
            # the tree holds still for one interval before building
            while True:
                time.sleep(interval)
                later = watched_files(talk_path, args)
                if later == now:
                    break
                now = later
            changed = {p for p in now.keys() | snap.keys()
                       if now.get(p) != snap.get(p)}
            snap = now
            run(changed)
    except KeyboardInterrupt:
        print("\nwatch stopped")
        return 0


def referenced_media(talk: talkparse.Talk, resolver: MediaResolver):
    seen = []
    slugs = set()
    for s in talk.screens:
        for shot in s.shots:
            if shot.is_media and shot.slug not in slugs:
                slugs.add(shot.slug)
                seen.append(resolver.resolve(shot.slug))
    return seen


if __name__ == "__main__":
    sys.exit(main())
