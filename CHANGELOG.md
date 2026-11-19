# Changelog

## Unreleased

- `layout=cols` spaces its two columns by their text: each column is as wide as
  its longest item, and the room left over goes evenly before, between and after
  them, so short items sit together in the middle instead of at the left of two
  half-slide columns. Specimen screens for long items and for check marks in
  columns.
- Bulleted lists on slides have no marker by default: items are set apart by
  space, and sub-points get a quiet dash. `bullets=` on a shot (or `bullets:` in
  the frontmatter, for the deck) picks one: `dot` (the old round bullet), `check`
  (a box: things to do; prints as a box to tick in the handout), `arrow` and
  `dash`, in the accent colour. Print keeps a bullet for bare and dot lists.
  Numbered lists, reveal steps, columns, notes and the agent export are
  unchanged. The source marker (`-`, `*`, `+`) still means nothing, since
  formatters rewrite it. Specimen screens for each marker in both decks.
- A slide whose text shrinks to fit now keeps it off the frame's edge: the fitter
  used to stop once nothing scrolled, which on a centred slide left the title
  against the top edge and the last line against the bottom. Text may now use
  at most half of the slide's padding (hero and code slides keep all of it, as
  before). A specimen deck for the rest of the features
  (`examples/specimens/plain/`) and `tests/browser_specimens.py`, a clip check
  over every specimen deck in both themes at four window sizes (or over the decks
  you name, in their own theme). Over the applied-AI decks it found 398 slide
  sizes clipped or on the edge before this change and 166 after.
  `tools/check-fit.py` is gone: the clip check covers it, and its "slightly
  tall" list had stopped fitting at the themes' current sizes.
- `fit=hero` styling fixes, found with a new specimen deck
  (`examples/specimens/hero/`, one hero screen per combination of features) and
  `tools/contact-sheet.py`, which renders every slide of a deck into one
  thumbnail sheet for review (`--theme`, `--only`, `--size`, `--frames`; a red
  frame marks a slide clipped at the fit floor). Fixed: a type-in quote
  (`` > `text` ``) lost its left padding under the lecture theme; hero lists
  hung their bullets into the slide margin (the indent is now in em); a short
  code span in a hero list or quote stays on one line (`--strict` no longer
  parts from its command) unless that would shrink the block; duo and split
  hero text ran to the slide's top and bottom edge; a hero title that leaves its
  block under 1.5x steps down to a heading, and a hero quote that is not short
  gets a wider column.
- The log is one grid: rows, the `starting` notice for big transfers and the
  header are built from the same format string, so the file column always lines
  up — `starting` sits in the time slot and the size in the size column. The
  header prints with the first row, after the build's report, instead of
  floating above it. A 206 row shows what went over the wire, not a
  "sent of total" that only a hand-made range request ever produced.
- The build report and the request log are readable again: one summary line per
  fact instead of an essay (pool slots, step lists and the six written paths are
  `-v`), paths shown with `~`, warnings gathered into one block above `written`,
  and the log is time / status / size / file / took with no `(no range)` column
  and no stdlib "code 404, message File not found" echo under every 404 row.
- The deck server no longer logs the reload poll: a watched page asks for
  `_watch.js` once a second, and those lines were burying the requests that
  matter. The poll still happens; the log just says so once, in its header.
- `--no-reload` turns the watch build's page refresh off, for when a reload
  would lose your place. Reload is otherwise what `--watch` does.
- `-q/--quiet` and `-v/--verbose` on `build` (and through `serve`): the summary
  prints once, then one line per rebuild; `-v` keeps the essay every time, `-q`
  keeps only problems.
- `animatic serve DECK --watch` builds, serves and rebuilds in one process, so
  keeping a deck live over the network is one command and one terminal. The
  server runs in a thread beside build.py's watcher; `--bind tailscale` binds the
  box's tailnet address so a laptop knows what to open, and the banner now prints
  URLs against the address actually bound (it used to say localhost while
  listening elsewhere).
- The waypoint token can come from a machine key file
  (`~/.config/animatic/waypoint-token`, or `ANIMATIC_WAYPOINT_TOKEN_FILE`) instead
  of only the environment, and `animatic token` stores it without echoing it and
  writes mode 0600. The env var still wins. The file is what makes a `--watch`
  started over ssh (pull-deck.sh) publish: it inherits no environment.
- `--inert` builds with the waypoint publisher left out whatever the token sources
  say — a deck safe to hand out. The handout PDF and web export use it, and
  `animatic pack --inert` seals such a copy; a normal pack records `waypoints` in
  `BUILD.json` and warns when the folder carries the token.
- `animatic` is now the one door: `build`, `check`, `serve`, `decks` and `pack`
  subcommands. `animatic-check` is folded into `animatic check` (`--register`,
  `--strict`, `--corpus` and the new `--json` all still work). A deck argument
  may be a talkfile or a folder holding one, and is the current directory when
  omitted; the output folder defaults to `out-<slug>`.
- `animatic pack` seals a release artifact: a plain build (never a watch build),
  a check, and a path-free `BUILD.json` with the hash of every file. It is
  deterministic, so `animatic pack --verify --out DIR` re-checks a carried copy
  on any machine without a source tree, and refuses one that carries
  `_watch.js`.
- `animatic decks [--json]` answers what the content roots hold, with the folder
  each deck builds into — the fact `tools/find-talkfile.py` and pull-deck had
  each been deriving for themselves.
- `serve-deck.py` (and `animatic serve`) warns when bound to a non-loopback
  address: `getDisplayMedia` needs a secure context, so a LAN bind silently
  disables browser window capture.
- `corpus.yaml` is no longer tracked — it names machine-local content roots.
  `corpus.example.yaml` is the template; with no `corpus.yaml` the corpus check
  scans the repo's `examples/` and says so, and relative roots now resolve
  against the repo root rather than the current directory.

## 0.1.0 — first public release

- The builder: one talkfile to a present view, presenter window, document view,
  `cues.json`, `nav.json` and `media-manifest.json`.
- Handout PDF, web export, home-page and agent export, timing report.
- Check suite (`animatic-check`, `--register`, `--strict`, corpus mode).
- Includes, quick select, waypoints, live capture screens, timers and reveals.
- Golden and property test suite, plus browser tests.
