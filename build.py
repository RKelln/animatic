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
    python3 build.py --corpus [ROOT]     # corpus check

Example (specimen):
    python3 build.py examples/roles-demo/talk.md

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
import os
import shutil
import sys
from pathlib import Path

import yaml

import exercises
import render
import talkparse
from mediaresolve import UNCREDITED, MediaResolver, expand_pools, shelf_media_errors, uncredited_shared
from render import (cited_sources, render_cues, render_document, render_manifest, render_nav,
                    render_present, render_presenter)


def parser() -> argparse.ArgumentParser:
    """The command line.  A function so tests can ask what a flag
    defaults to without building a deck."""
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
    ap.add_argument("--home-page", action="store_true",
                    help="document view for the home page: exercise (`do`) screens print in place "
                         "(tools/web-export.py --home)")
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
                         "(a YAML file of slug: path); real art always "
                         "beats a stand-in")
    ap.add_argument("--link-media", action="store_true",
                    help="symlink media into OUT/_media instead of copying it: "
                         "for throwaway and test builds (no disk cost), not "
                         "for a folder you will move or share")
    ap.add_argument("--quick-sections", default=None, metavar="DIR",
                    help="quick select: shelve the sections in DIR that declare "
                         "a `quick:` block, overriding the talkfile's "
                         "`quick_sections:` line (relative to the working "
                         "directory); for trial builds without editing a talk")
    ap.add_argument("--allow-inert", action="store_true",
                    help="let a build without a waypoint token replace an "
                         "output that publishes waypoints (refused by default: it "
                         "would silently turn a live-room deck inert)")
    ap.add_argument("--inert", action="store_true",
                    help="publish no waypoints whatever the token sources say: a "
                         "deck safe to hand out (implies --allow-inert)")
    ap.add_argument("--watch", action="store_true",
                    help="stay running and rebuild whenever the talkfile, a "
                         "file beside it, its media/ dir or the remap changes; "
                         "one line per rebuild (--verbose for the full summary, "
                         "--reload to have open pages refresh themselves)")
    ap.add_argument("--reload", dest="reload", action="store_true", default=True,
                    help="with --watch (the default): open pages reload themselves "
                         "after each build")
    ap.add_argument("--no-reload", dest="reload", action="store_false",
                    help="with --watch: inject no reload snippet; refresh the page "
                         "yourself when you want to see the change")
    ap.add_argument("-q", "--quiet", action="store_true",
                    help="print problems and the one-line result, never the "
                         "build summary")
    ap.add_argument("-v", "--verbose", action="store_true",
                    help="with --watch: repeat the full summary on every rebuild "
                         "(default: the summary once, then one line each time)")
    ap.add_argument("--lease", default=None, metavar="PATH",
                    help="with --watch: stop once PATH's mtime is older than "
                         "--lease-timeout. A watcher must not outlive the "
                         "process that started it (pull-deck.sh heartbeats this)")
    ap.add_argument("--lease-timeout", type=float, default=60.0, metavar="SECS",
                    help="how stale the --lease heartbeat may get (default 60)")
    return ap


def main(argv=None) -> int:
    ap = parser()
    args = ap.parse_args(argv)

    if args.lease and not args.watch:
        ap.error("--lease only means something with --watch")

    global SUMMARY, DETAIL
    SUMMARY = not args.quiet
    DETAIL = args.verbose

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


TOKEN_FILE_ENV = "ANIMATIC_WAYPOINT_TOKEN_FILE"
TOKEN_FILE = "~/.config/animatic/waypoint-token"


def waypoint_token() -> tuple:
    """(token, where it came from); ("", "") when there is none.

    ANIMATIC_WAYPOINT_TOKEN wins.  Otherwise the machine's key file
    (`~/.config/animatic/waypoint-token`, or the path in
    ANIMATIC_WAYPOINT_TOKEN_FILE).  The file is why the secret is not typed into
    every build command and never travels inside the ssh command that starts a
    remote `--watch`.  Trimmed; blank is none.  Never print what this returns:
    the caller may print the source, which is not a secret.
    """
    env = os.environ.get("ANIMATIC_WAYPOINT_TOKEN", "").strip()
    if env:
        return env, "ANIMATIC_WAYPOINT_TOKEN"
    path = Path(os.environ.get(TOKEN_FILE_ENV, "").strip() or TOKEN_FILE).expanduser()
    try:
        token = path.read_text(encoding="utf-8").strip()
    except OSError:
        return "", ""
    if not token:
        return "", ""
    try:
        if path.stat().st_mode & 0o077:
            print(f"warn      : {path} is readable by group or others; "
                  f"chmod 600 {path}", file=sys.stderr)
    except OSError:
        pass
    return token, str(path)


def publishes_waypoints(present_index: Path) -> bool:
    """True if this built present page carries the waypoint publisher (a build
    with the token has the Authorization header in it; an inert one has not)."""
    try:
        return b"Bearer " in present_index.read_bytes()
    except OSError:
        return False


# The build summary is the essay: helpful once, noise on every save.  --quiet
# turns it off, and a watcher prints it for the first build only unless
# --verbose.  Warnings and errors never go through here: they always print.
SUMMARY = True
DETAIL = False          # --verbose: the per-slot, per-screen, per-file lists


def say(*parts, **kw) -> None:
    if SUMMARY:
        print(*parts, **kw)


def tilde(path) -> str:
    """A path a person reads: ~ for home, since every deck lives under one."""
    text = str(path)
    home = str(Path.home())
    return "~" + text[len(home):] if text.startswith(home) else text


def build(talk_path: Path, args) -> int:
    warns: list[str] = []   # collected, then printed together in the report
    talk = talkparse.build_talk(talk_path,
                                quick_sections=getattr(args, "quick_sections", None))
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
            warns.append(f"media-remap file(s) missing, ignored: {', '.join(gone)}")

    shelf_errors = shelf_media_errors(talk, resolver)
    if shelf_errors:
        for line, msg in shelf_errors:
            print(f"error     : {talk.source}:{line}: {msg}", file=sys.stderr)
        return 1

    # A build without the token must not silently replace one that has it: the
    # deck carried to the venue would stop publishing and say nothing.  A
    # watcher builds beside the output and swaps it in, so it names the folder
    # it will replace in args.replaces.  --inert is the deliberate version.
    if getattr(args, "inert", False):
        wp_token, wp_source = "", ""
    else:
        wp_token, wp_source = waypoint_token()
    if not wp_token and not (getattr(args, "allow_inert", False)
                             or getattr(args, "inert", False)):
        prior = Path(getattr(args, "replaces", None) or args.out).expanduser().resolve() / "present" / "index.html"
        if publishes_waypoints(prior):
            print(f"error: {prior.parent.parent} holds a deck that publishes waypoints, "
                  f"and this build has no waypoint token, so it would replace it "
                  f"with one that publishes nothing.  Set ANIMATIC_WAYPOINT_TOKEN "
                  f"or put the token in {TOKEN_FILE} (chmod 600), or pass "
                  f"--allow-inert to replace it on purpose.", file=sys.stderr)
            return 2

    out = Path(args.out).expanduser().resolve()
    if out.exists():
        if not args.keep:
            shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)

    media_refs = referenced_media(talk, resolver)
    resolver.validate_steps()
    resolver.publish(out, [r.slug for r in media_refs])
    for _slug, msg in resolver.playback_issues:
        warns.append(f"check 29: {msg}")
    for _slug, msg in resolver.steps_issues:
        warns.append(f"check 33: {msg}")
    for _slug, msg in resolver.pool_issues:
        warns.append(f"check 41: {msg}")
    for msg in dict.fromkeys(m for _slug, m in resolver.shared_issues):
        warns.append(f"check 50: {msg}")
    for label in uncredited_shared(talk, resolver):
        warns.append(f"check 51: {UNCREDITED.format(label)}")
    for scr, _line, msg in render.step_count_notes(talk, resolver):
        warns.append(f"check 34: {render.deck_slug(talk)}-{scr.idx:03d}: {msg}")
    for scr, _line, msg in render.next_mark_notes(talk, resolver):
        warns.append(f"check 40: {render.deck_slug(talk)}-{scr.idx:03d}: {msg}")

    cites = talk.meta.get("cites")
    if isinstance(cites, dict):
        bare = [c["id"] for c in cited_sources(talk) if not str(cites.get(c["id"], "")).strip()]
        if bare:
            warns.append(f"handout Sources omits {len(bare)} cited id(s) "
                         f"with no `cites:` entry: {', '.join(bare)}")

    elif cited_sources(talk) and str(talk.meta.get("handout-sources", "")).strip().lower() != "working":
        warns.append(f"handout prints no Sources list: {len(cited_sources(talk))} "
                     f"cited id(s) but no `cites:` map (working receipts never print; "
                     f"`handout-sources: working` for a draft copy)")

    # waypoints (docs/waypoints.md): the token goes into present/index.html only,
    # and a build without one publishes nothing.  It is never printed.
    present = render_present(talk, resolver, out / "present",
                             waypoint_token=wp_token)
    presenter = render_presenter(talk, resolver, out / "present",
                                 waypoints_live=bool(wp_token))
    document = render_document(talk, resolver, out / "document", figures=args.handout_figures,
                               pools=False if args.no_handout_pools else None,
                               placeholders=False if args.no_handout_placeholders else None,
                               home=args.home_page,
                               omit=(exercises.skipped_screens(talk)
                                     if args.home_page else None))
    cues = render_cues(talk, resolver, out)
    nav = render_nav(talk, out)
    manifest = render_manifest(talk, resolver, out)

    say("")
    say(f"deck      : {tilde(talk.source)}")
    say(f"title     : {talk.meta.get('title', '')}")
    say(f"shape     : {len(talk.movements)} movements, {len(talk.main_screens)} screens "
          f"({sum(1 for s in talk.main_screens if s.movement == 0)} opening)")
    if talk.shelf_screens:
        say(f"shelf     : {len(talk.shelf_screens)} quick-select screens in "
              f"{len({s.section[0] for s in talk.shelf_screens})} sections "
              f"(after the talk; not in the handout)")
    if resolver.pool_log:
        pool = f"{len(resolver.pool_log)} slot(s)"
        if DETAIL:
            for virtual, fname, line in resolver.pool_log:
                say(f"pool      : {virtual} <- {fname or 'NO FILE'} (line {line})")
        else:
            say(f"pool      : {pool} filled from the deck's media library (-v lists them)")
    wp_marked = [s for s in talk.screens if s.waypoint]
    if wp_marked:
        if wp_token:
            wp_state = f"publishing ON in present/index.html (token from {tilde(wp_source)})"
        elif getattr(args, "inert", False):
            wp_state = "inert (--inert: this build never publishes)"
        else:
            wp_state = ("inert (no waypoint token: set ANIMATIC_WAYPOINT_TOKEN "
                        f"or write {TOKEN_FILE})")
        say(f"waypoints : {len(wp_marked)} marked; {wp_state}")
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
    say(f"roles     : stat={roles['stat']} lower={roles['lower']} "
          f"credits={roles['credits']} (payloads)")
    found = [r for r in media_refs if r.found]
    missing = [r for r in media_refs if not r.found]
    media_line = (f"{len(media_refs)} referenced slugs, all found" if not missing
                  else f"{len(media_refs)} referenced slugs, {len(found)} found, "
                       f"{len(missing)} placeholder")
    say(f"media     : {media_line}")
    say(f"voice     : {said_lists} list(s) read aloud; {empty_script} screen(s) "
          f"carry no script (card/media beat with no VO — see cues.json)")
    steppers = [(scr, render.screen_steps(scr, resolver)) for scr in talk.screens]
    steppers = [(scr, ref) for scr, ref in steppers if ref is not None]
    if steppers:
        if DETAIL:
            for scr, ref in steppers:
                say(f"steps     : {ref.slug}: {len(ref.steps)} steps "
                      f"(handout: {render.handout_label(ref)}) "
                      f"[{render.deck_slug(talk)}-{scr.idx:03d}]")
        else:
            total = sum(len(ref.steps) for _, ref in steppers)
            say(f"steps     : {len(steppers)} stepper screen(s), {total} step(s) "
                  f"(-v names them)")
    for w in warns + list(talk.warnings):
        print(f"warn      : {w}")   # warnings are never quiet: they are problems
    final = Path(args.replaces).expanduser() if getattr(args, "replaces", None) \
        else Path(args.out).expanduser()
    if DETAIL:
        for path in (present, presenter, document, cues, nav, manifest):
            say(f"written   : {tilde(path)}")
    else:
        say(f"written   : {tilde(final)}/ — present/ document/ presenter.html "
              f"cues.json nav.json media-manifest.json")
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
        t_ = talkparse.build_talk(talk_path, quick_sections=getattr(
            args, "quick_sections", None))
        paths += t_.includes + t_.shelf_files
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


def stamp_watch(out: Path, stamp: str) -> None:
    """Record a build stamp in `_watch.js`.  Written on every watch build, with
    or without the reload snippet, because that file is also how `animatic pack`
    and the transport scripts tell a watch build from a plain one."""
    (out / "_watch.js").write_text(
        f"window.__animaticWatch && window.__animaticWatch({stamp!r});\n",
        encoding="utf-8")


def inject_reload(out: Path, stamp: str) -> None:
    """Add RELOAD_SNIPPET to every page in OUTDIR, then write the stamp.  The
    stamp goes last, so an open page only reloads once the build is whole."""
    for page in sorted(out.glob("*/*.html")):
        html = page.read_text(encoding="utf-8")
        i = html.rfind("</body>")
        if i < 0:
            continue
        page.write_text(html[:i] + RELOAD_SNIPPET + html[i:], encoding="utf-8")
    stamp_watch(out, stamp)


def _is_watcher(pid: int) -> bool:
    """True if `pid` is a live `build.py ... --watch` (not a recycled pid)."""
    try:
        cmd = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
    except OSError:
        return False
    return any(c.endswith(b"build.py") for c in cmd) and b"--watch" in cmd


def take_over_watch(pidfile: Path) -> None:
    """One watcher per --out: two fight over the same staging folder, and one
    started without ANIMATIC_WAYPOINT_TOKEN would keep rebuilding an inert deck
    over a good one.  The newest watcher wins: stop the old one, then record
    ourselves.  Only the pid in the file is touched, and only if it is still a
    build.py --watch."""
    import signal
    import time
    try:
        old = int(pidfile.read_text().strip())
    except (OSError, ValueError):
        old = 0
    if old and old != os.getpid() and _is_watcher(old):
        print(f"replacing the watcher already running for this --out (pid {old})")
        try:
            os.kill(old, signal.SIGTERM)
        except OSError:
            pass
        for _ in range(40):
            if not _is_watcher(old):
                break
            time.sleep(0.1)
        else:
            print(f"warning: pid {old} did not stop; two watchers may fight", file=sys.stderr)
    pidfile.write_text(f"{os.getpid()}\n")


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

    import atexit
    import signal
    out_final = Path(args.out).expanduser().resolve()
    pidfile = out_final.with_name(f".{out_final.name}.watch.pid")
    take_over_watch(pidfile)

    def _forget():
        try:
            if pidfile.read_text().strip() == str(os.getpid()):
                pidfile.unlink()
        except OSError:
            pass
    atexit.register(_forget)
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))

    def lease_stale() -> bool:
        if lease is None:
            return False
        try:
            age = time.time() - lease.stat().st_mtime
        except OSError:            # no beat yet: give the starter one window
            return (time.monotonic() - started) > args.lease_timeout
        return age > args.lease_timeout

    first = [True]

    def run(changed):
        # The first build earns the summary; later ones are the one-line result
        # unless --verbose.  --quiet silences it every time.
        global SUMMARY, DETAIL
        SUMMARY = not args.quiet and (first[0] or args.verbose)
        DETAIL = args.verbose
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
        args.replaces = str(final)
        try:
            rc = build(talk_path, args)
            if rc == 0:
                stamp = f"{time.time_ns()}"
                if getattr(args, "reload", True):
                    inject_reload(stage or final, stamp)
                else:
                    stamp_watch(stage or final, stamp)
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
        took = time.monotonic() - t0
        # The first build says what is being watched; later ones are a heartbeat,
        # so they do not repeat the path on every save.
        where = (f"; watching {tilde(talk_path.parent)} (Ctrl-C to stop)"
                 if first[0] else "")
        print(f"[{time.strftime('%H:%M:%S')}] build {status} in {took:.1f}s{where}",
              flush=True)
        first[0] = False

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
