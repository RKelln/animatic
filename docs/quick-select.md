# Quick select: answering questions from the presenter window

**Status: implemented, 2026-11-05 (v1 scope). Where the build differs from the draft, the
text below says what was built and "As built" at the end gives the reasons.**

During Q&A someone asks about a topic the talk doesn't cover. The presenter
presses `/` in the presenter window, types "agents", picks a result, and the
slide appears on the projector. Esc returns to exactly where they were.

Quick select does two things:

1. Jumps to **any slide in the deck**.
2. Jumps to **hidden slides**: sections built into the deck that the talk never
   reaches in normal paging. This is the "shelf".

It needs no AI, server or network at show time, and works from `file://` and
from localhost.

## Authoring

A talk opts in with one frontmatter line. The path is relative to the talkfile:

```yaml
quick_sections: ../_sections
```

A section joins the shelf by declaring a `quick:` block in its own frontmatter:

```yaml
quick:
  title: What's an agent?
  keywords: [agents, agentic, hermes, claude code, opencode, tools]
```

- Sections with no `quick:` block stay off the shelf. Credits and take-home
  should not be search results.
- A section the talk already includes is not shelved a second time. Search finds
  the copy in the talk.
- `quick:` on a section that a talk simply includes has no effect beyond adding
  its title and keywords to search.
- `python3 build.py <talk> --quick-sections <dir>` overrides the frontmatter, so
  a deck can be trial-built without editing its talkfile.

Shelf order is by filename, so builds stay deterministic. A deck without
`quick_sections` has an empty shelf: its visible output and every non-script build
product (document view, handout, `cues.json`, `nav.json`, `media-manifest.json`, media)
are unchanged. Only the inline scripts and the presenter page's markup and cue index
differ, because every deck now runs the same scripts.

## What the build does

Shelf sections are lexed like includes, then appended **after the deck's last
real screen**. Existing slide numbers and `#N` links don't move.

| Output | Shelf screens |
|---|---|
| `present/index.html` | Present, with `data-quick="<section path>"` |
| `presenter.html` cue index | Present, with `quick: true` |
| `cues.json` | Present, with `quick: true` and `live_only: true`, so a video render skips them |
| `nav.json` | Present, with `include` and `quick: true` |
| document view, handout, web export | Absent, through the existing `live_only` route |
| timing totals, check 19 | Excluded: a shelf does not lengthen a talk |
| `media-manifest.json`, `_media` | Present, so the media is on the machine |

**Citations must not leak.** An included section's `cites:` and `sources:` join
the talk's (`talkparse.py`, `build_talk`), and the handout is public. A shelf
section's `cites:` must resolve for its own screens but must not print in the
handout unless the talk cites them too.

**`--watch`** follows shelf files as it does includes. A newly added section file
needs a fresh build.

## Pager rules

The deck gains `mainCount`, the number of non-shelf screens. All the existing
navigation stays inside it.

- `next()` stops at the last main screen. `End` goes there too.
- The counter and the presenter's "N of M" use `mainCount`. On a shelf screen the
  presenter shows the section title rather than a number.
- On a shelf screen, next and prev move within **that section** and stop at its
  edges. They never run into a neighbouring section or back into the talk.
- A `#N` hash can name a shelf screen, so a reload stays put, but the return
  position does not survive a reload.
- `warmAround()` must not warm across the main/shelf boundary, or between shelf
  sections. Otherwise every deck pre-loads videos it may never show, on the last
  slide and at each jump.

### Jumping and returning

`window.animatic` gains `jump(i)` and `returnFromJump()`:

- The first jump saves `{index, step}`. Later jumps keep that saved position, so
  several questions in a row still return to one place.
- A jump lands fully revealed: every list item shown, using the same rule `prev()`
  uses when backing into a slide. A revealed timer waits for its own press.
- Return restores the saved step exactly, then clears the saved position.
- Going to a normal slide with the normal keys doesn't clear it, so the presenter
  can step around after a jump and still return.
- Esc, in this order: close the search, then close the notes panel, then return.

## The search box

Presenter window only in v1, because in a one-screen room a search box would be on
the projector.

- `/` opens it. Its handler runs first and swallows every key while open, so
  typing `s`, `t`, `p`, `f` or `0` can't close the window, restart the clock or
  touch a timer.
- Empty query: lists all shelf sections by title, so it doubles as a menu.
- Up, Down and Enter choose. Enter jumps and closes the box. Esc closes it.
- Each result shows its title, or the first line of its text, plus a label: the
  section name, or the movement and slide number.
- The selected result shows a preview. The presenter asks the deck for a clone
  with a new `animatic-preview-request` message and the deck replies through the
  existing preview path. It doesn't navigate, a video is a still, and a `type:
  live` screen gets the existing no-preview label.
- A status line appears while away: `Quick: What's an agent? · Esc returns to 23`.
  The projector shows no such thing.

### Index and ranking

The build adds search text to the cue index already in `presenter.html`: title,
screen text and spoken script, plus section title and keywords for shelf screens.
Stage notes stay out, as they aren't what the audience is asking about.

Case-insensitive, every typed word must match as a prefix. Scores, highest first:

1. Section title or keyword: one row, jumping to the section's first screen
2. Slide title or screen text
3. Spoken script

Shelf rows win ties, because they were written to answer questions. Show at most
12 rows (the empty-query menu lists every shelf section, uncapped, since a menu with a
hidden entry is no menu). There's no fuzzy matching or synonym table in v1: `keywords:` is the way
to teach it a word.

## Interaction with later work

A separate proposal publishes the room's position to participants' agents as the
presenter advances. Jumps must not count as advancing, so `jump()` and
`returnFromJump()` fire a distinguishable change: `animatic.moveKind()` is `"jump"`,
`"return"` or `"nav"` while the change listeners run, `animatic.jumped()` says whether a
position is saved, and the presenter's `animatic-state` carries `jumped`, `returnTo` and
`move`. No further work for that feature here.

## Checks and tests

- **Register check 48 (fatal):** `quick_sections` names a missing directory, or a
  `quick:` block has no `title`, or `keywords` isn't a list. Registered in `check.py`
  (the draft said 40; 40 was already the `[next]` marks check).
- **Golden suite:** existing expected output must not change. Run the corpus check
  before and after, as "nothing that parses today may change meaning" requires.
- **`tests/properties/quick_props.py`:** shelf placement and ordering, dedupe
  against includes, absence from document view and handout, timing unaffected,
  cites not leaking, cue index mirroring `cues.json`, deterministic bytes.
- **Browser test, modelled on `tests/browser_reveal_timer.py`:** next stops at the
  last main slide, section edges hold, jump and return restore the exact step,
  several jumps return to the first position, typing in the search touches nothing,
  shelf videos don't warm until jumped to.
- **`tools/presenter-probe`:** the search box fits at 1280x800 and 1920x1080 (the probe
  now opens the search over a deck with a shelf and measures the panel, the input, the
  results and the 16:9 preview at each size).
- **Docs:** README and `docs/presenter-view.md` keys table, plus the format spec for
  the two new frontmatter fields.

## Out of scope for v1

- Search in the deck window for one-screen rooms
- Slides from other decks: promote the slide to a section instead
- LLM topic tags, embeddings or typo tolerance
- Editing talkfiles or sections: `quick:` blocks and `quick_sections` lines are
  content, written and committed by Ryan's content sessions

## Known costs

- Every deck carries its shelf's media. A long shelf video grows all of them, so
  prefer stills on the shelf.
- A section edit means rebuilding each deck. Decks are rebuilt before presenting
  anyway, and `build.py --corpus` covers all of them.
- Returning to a video slide would reload that video from its start, because warming
  releases slides left behind. Confirmed in the browser test (an 8 s clip, headless
  Chromium: unpinned, it came back at 0.00 s with its buffer dropped; a video that is
  not local would also re-buffer), so the saved slide is pinned: while a jump is out,
  `warmAround()` does not release it, and it resumes where it was (0.83 s, buffer
  intact, in the same test).

## As built

What differs from the draft above, and why.

- **Check 48, not 40.** 40 is the `[next]` marks check.
- **One set of scripts, and what that changes.** The quick-select logic is in the shared
  `PAGER_JS`, `PRESENTER_JS`, `LIVE_JS`, `DEBUG_JS`, `MEDIA_JS` and `PRESENTER_UI_JS`, so
  every deck runs it; a deck with no `quick_sections` is a deck with an empty shelf
  (`mainCount` equals the slide count and no slide has `data-quick`). Guarantee: visible
  output and non-script build products are unchanged. Checked by rebuilding 14 real and
  example decks before and after: `present/index.html` differs only inside its `<script>`
  elements, `present/presenter.html` differs only in its script, its search markup, its
  added style block and its cue index (which now carries search text), and the document
  view, `cues.json`, `nav.json`, `media-manifest.json` and media are byte-identical.
  The golden suite's expected files did not change.
- **`state.jumped` became `animatic.jumped()` / `moveKind()`** plus the `jumped`,
  `returnTo` and `move` fields in the presenter message (see Interaction with later work).
  The deck has no `state` object.
- **Counts.** `animatic.count()` is the talk's screen count (`mainCount`); `total()` adds
  the shelf and `bounds(i)` gives the `[lo, hi]` region of a slide. The deck counter and
  the presenter's "n / m" use `count()`. On a shelf slide the deck's counter and progress
  bar keep showing the talk's place (the saved slide when a jump is out, else the last
  slide), and the presenter shows the section title. The debug dump reports `screens`
  (the talk) and `shelf` apart. `Home` and `End` go to the first and last screen of the
  region you are in (the talk, or the shelf section), so they never cross either.
- **Esc in the deck window** also returns, after the notes panel and only when no other
  panel (hookup, debug, media) is open, so the one-screen room can return too.
- **Hookup panel.** A shelf slide is labelled "shelf" and its `go` button is a jump, so
  Esc can still return.
- **Where a shelf screen shows up.** `nav.json` entries carry `"quick": true` and the
  document entry's reason is `"shelf"` (not `"live-only"`). `cues.json` lists shelf cues in
  no movement. Shelf screens take the talk's last movement number in the model.
- **Dedupe is by resolved file path.** A `--quick-sections` directory holding a *copy* of
  a section the talk includes is a different file and is shelved too; the real
  `quick_sections: ../_sections` is the same files and dedupes.
- **Citations.** A shelf section's `cites:` / `sources:` live in `Talk.shelf_registry`
  (per section; `Talk.shelf_cite()` resolves a shelf screen's own id, then the talk's) and
  its `[^id]` refs in `Talk.shelf_footnote_ids`. Neither joins `meta` or `footnote_ids`,
  which is what the handout's Sources list and `deck.sources` are built from. An
  unresolvable shelf footnote warns as check 28 at parse time. The handout PDF
  (`tools/handout-pdf.py`) and the web export (`tools/web-export.py`) build the same
  document view and were run on the fixture: no shelf text or citation appears.
- **`quick:` on a plain include.** Only read in a deck that has opted in; a malformed one
  in a deck without `quick_sections` still parses exactly as before.
- **Search labels.** A section row's label is "shelf" (or "section" for an include the
  talk carries); a screen's label is its section title, or "Movement n · slide m"
  ("Opening" before the first movement).
- **v1 limits kept.** Search is in the presenter window only. The 12-row cap and the
  ranking are exactly as above; there is no browser test for "more than 12 matches"
  because the fixture is small (it asserts at most 12).
