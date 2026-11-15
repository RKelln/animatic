# Features

Optional features of the talkfile and the present view. The grammar itself is in [format-spec-v1.md](format-spec-v1.md).

## Includes

`<!-- include: path [live] -->` on its own line splices another file's screens in at
that point, so a standard piece (a privacy slide, an about-me, credits) is
written once and used by every talk. The path is relative to the including file;
absolute paths are refused. Name included files `*.section.md` (the corpus check
treats `*.talk.md` as decks).

- Each file is lexed on its own. Every screen from an included file points at the
  directive's line in the talk (warnings, `nav.json` ranges), and `nav.json` adds
  `"include": "<path as written>"` to those screens.
- `live` marks every screen inside as live-only (see the `live` shot flag in
  "What the handout does"). A `continue` shot after the include does not inherit it.
- Includes nest to 3 deep. A missing file, a cycle, an absolute path, an unknown flag
  or a `## Movement` heading inside the section is a fatal error with its line (check 22).
- An included file's frontmatter `cites:` / `sources:` join the talk's; the talk wins.
- A section's media comes only from the shared `_media/` (a library entry, or a file named
  `<slug>.<ext>` / `<slug>/<slug>.<ext>`), never the including deck's `cards.yaml` or
  `media/`, so a section looks the same in every deck. A slug with no shared media is a
  placeholder and the usual warnings. If the deck has its own card or file of that slug, the
  section's copy is published as `<slug>--lib` beside it (`docs/media-pipeline.md`).
- `--watch` follows included files. Properties: `tests/properties/include_props.py`.

## Quick select

During Q&A someone asks about a topic the talk does not cover. In the presenter window
press `/`, type "agents", pick a result with Up / Down / Enter, and that slide appears on
the projector. `Esc` returns to exactly where the talk was (same slide, same reveal step).
Full design: `docs/quick-select.md`.

- A talk opts in with one frontmatter line, `quick_sections: ../_sections` (relative to
  the talkfile). A section joins the **shelf** by declaring `quick:` in its own
  frontmatter: `title:` (required) and `keywords:` (a list). A section with no `quick:`
  block stays off the shelf. A section the talk already includes is not shelved twice;
  its title and keywords still reach the search.
- Shelf sections are built into the deck **after the last real screen**, so slide numbers
  and `#N` links do not move. Paging never leaves the talk, and on the shelf it never
  leaves the section; only a jump crosses. They are in the present view, the presenter
  window, `cues.json` (`quick: true`, `live_only: true`), `nav.json` and the media
  manifest, and **not** in the document view, the handout or the web export. The shelf
  does not count toward timing (check 19). A shelf section's `cites:` / `sources:` serve
  its own screens only and never reach the handout.
- `python3 build.py <talk> --quick-sections DIR` trial-builds a deck with a shelf from
  DIR without editing the talkfile (it overrides the frontmatter line; DIR is relative to
  the working directory). `--watch` follows shelf files; a newly added section file needs
  a fresh build.
- A deck with no `quick_sections` has an empty shelf: its slides, document view, handout and `cues.json` / `nav.json` / `media-manifest.json` are unchanged (only the inline scripts and the presenter page differ).
- Check 48 (fatal): `quick_sections` names a missing directory, a `quick:` block has no
  `title` or a `keywords` that is not a list, or a shelf screen's media does not resolve
  from the shared `_media/` (no placeholder: nobody pages to a hidden slide; the error
  names the section file). `--quick-sections DIR` reads sections from DIR but media from
  the `_media/` beside the deck, not one beside DIR.
- Properties: `tests/properties/quick_props.py`; the browser test is
  `tests/browser_quick_select.py`.

## Waypoints

When the talk reaches a marked slide the deck publishes one word, so participants'
agents can tell them where the room is. Full design: `docs/waypoints.md` (the service and
the machine-side hook are other repos; this is the deck's half).

- Mark a slide with `waypoint=expanding` in its shot (`<!-- shot: waypoint=expanding -->`, or
  alongside other tokens: `<!-- shot: reveal=timer live waypoint=expanding -->`), and give the talk `waypoints: { url: https://example.com/event/waypoint/demo }` in its
  frontmatter. A word is lowercase letters, digits and hyphens, up to 24, used once. Put
  `start` on the first screen. It belongs in the talkfile, never in a section.
- `ANIMATIC_WAYPOINT_TOKEN=... python3 build.py <talk>` builds a deck that publishes. The
  token goes into `present/index.html` and nowhere else, and is never printed. Without it
  the build is **inert**: nothing is sent and there is no status line or `w` key, so a
  rehearsal build cannot touch a live room.
- A publishing deck POSTs the bare word with `Authorization: Bearer <token>` (async, 3 s
  timeout, one retry, never blocks paging) when `next()` arrives at a marked slide later
  than the last word sent, and on load at screen 1 with no `#` in the address (`start`).
  Never on prev, a hash change, a quick-select jump or return, or a `next()` pressed while
  a jump is out. It works from `file://` and localhost.
- The presenter window shows `Waypoint: expanding ✓ 7:04pm` or `✗ not sent, w to retry`.
  `w` (deck or presenter window) re-sends the latest word at or before the current slide,
  which is also how to correct a mistake: go back, press `w`.
- `cues.json` and `nav.json` gain a `waypoint` field on marked screens; nothing else in a
  deck changes. Check 49 (fatal): a bad word, a duplicate, a waypoint inside a section's shot, one
  on a shot that opens no screen, the old standalone `<!-- waypoint: ... -->` line, or waypoints without a valid `waypoints.url`.
- Properties: `tests/properties/waypoint_props.py`; the browser test is
  `tests/browser_waypoint.py`.
