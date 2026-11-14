# Waypoints: telling participants' agents where the room is

When the talk reaches a marked slide, the deck publishes one word to a small web
service. A hook on each participant's machine can read that word and, if it is new,
add a fixed note to what their coding agent sees. A person who has fallen behind
hears about it from their own agent, without having to ask anyone.

```
deck (marked slide) -- POST word + token --> your waypoint service
participant's machine (hook on each message) -- GET --> service
    +- hook looks the word up in a local file --> a fixed note for the agent
```

This repo holds the deck's half. The service and the hook are yours to run; the
contract they must meet is below. Waypoints are optional: a deck with none is
unchanged.

**Deliberately not included:** waking an idle agent, messages from the room back to
the presenter, and free-form remote text. Remote text never reaches an agent (see
Security).


## The deck: marking and publishing

### Authoring

```yaml
waypoints:
  url: https://example.org/waypoint/demo
```

```markdown
<!-- shot: waypoint=expanding -->
<!-- shot: reveal=timer live waypoint=expanding -->   (with other shot tokens)
```

- `waypoint=word` is a flag in the screen's shot, so it marks the screen that shot opens.
  Every screen starts with a shot, so there is always a place to put it.
- A word is lowercase letters, digits and hyphens, up to 24 characters, and can be
  used once per talk.
- It must be in the talkfile itself. In a `*.section.md` it would fire in every
  talk that includes that section.
- The first screen should carry `start`, so a run never begins on the previous
  run's last word.
- `cues.json` and `nav.json` gain a `waypoint` field on marked screens. Document
  view and handout don't show it. Decks without waypoints keep the same slides and data; only the
  scripts in their present pages change.
- Register check 49 (48 is quick select's): bad word, duplicate, a waypoint in a section's
  shot, one on a shot that opens no screen, the removed standalone `<!-- waypoint: ... -->`
  line, or waypoints with no `waypoints.url`.

### Token

The token comes from `ANIMATIC_WAYPOINT_TOKEN` at build time, and goes only into
`present/index.html`. A build without it is inert: nothing is published and no
status appears, so ordinary and rehearsal builds can't touch a live room. An inert build also **refuses to replace** an output that already publishes (it finds the publisher in the existing `present/index.html`), including a `--watch` rebuild, which keeps the keyed deck and prints `build FAILED (exit 2)`. `--allow-inert` replaces it on purpose. (This guards against a token-less rebuild silently replacing the keyed deck you then carry to the venue.) Web
export ships no present view, so the token can't reach a public page.

### When the deck publishes

- **On `next()` arriving at a marked screen**, if it is later in the talk than the
  last word published.
- **On load**, only when the deck opens at screen 1 with no hash, which is what
  publishes `start`.
- **Never** on `prev()`, a hash change, or quick select's `jump()` and
  `returnFromJump()`. Publishing belongs in the `next()` path rather than in
  `render()`, which all of those share.
- Publishing never blocks paging: asynchronous, a 3-second timeout, one retry.

### Presenter window

A status line shows `Waypoint: expanding ✓ 7:04pm`, or `✗ not sent, w to retry`.

`w` re-sends the latest word at or before the current slide. That is also how to
correct a mistake: go back to the right place and press `w`.

### Implementation notes

What the code does, beyond the text above:

- **Parsing.** `waypoint=word` is a known shot flag. `_parse_shot` stores it on the `Shot` (not in
  `flags`), `talkparse._attach_waypoints` validates the word and tags the shot's block, and the
  assembler hands it to the screen that shot opens. `Screen.waypoint` carries the word. (Until
  2026-11-06 it was a standalone `<!-- waypoint: word -->` line above the shot; that line is now a
  fatal that says where the word goes.)
- **Check 49 (free; 48 is quick select's)** is enforced in `talkparse.py` and registered in
  `check.py --register`. Beyond the listed cases it is also fatal when: the shot carrying the word
  opens no new screen, or `waypoints:` is present with no `http(s)://` `url`, marks or not. A
  waypoint in a section's shot is fatal whether the section is included or shelved, so no shelf
  screen can carry one.
- **Outputs.** `cues.json` and `nav.json` gain `waypoint` on marked screens only, token or not.
  The word is in no other output (document view, handout, web export, presenter page).
  The token and the words reach `present/index.html` through one `<script>` block that exists
  only in a build with `ANIMATIC_WAYPOINT_TOKEN` set and at least one mark; the build log says
  whether publishing is on and never prints the token. The environment is read in `build.py`
  and handed to `render_present(waypoint_token=...)`, so the renderer has no hidden input and
  a test or tool that calls it directly builds an inert page. The value is trimmed; blank is none.
- **Pager hook.** `animatic.addOnNext(fn)` fires after `next()` arrives on a new slide, and
  nowhere else (`prev`, `go`, hash changes, `jump`, `returnFromJump` and a step within a slide
  never reach it). Publishing lives in the `next()` path, not in `render()`. `advance`
  videos and swipes call `next()`, so they advance the talk too.
- **High-water mark.** It is the slide index of the last word *sent*, not the highest ever
  reached, because the text says "later than the last word published": after `w` re-sends an
  earlier word, the next real advance onto a later mark publishes again. It is set when a send
  starts, so a failed send does not make the same screen publish twice by itself; `w` is the retry.
- **A `next()` while a jump is out publishes nothing**, even onto a later mark. The talk has not
  advanced, the presenter is answering a question. After Esc, advancing publishes as normal.
- **`w` on a shelf screen** uses the slide a jump will return to. With no word at or before the
  current slide it does nothing, and the line says `none yet`.
- **Transport.** `fetch` POST, `mode: cors`, `credentials: omit`, `Content-Type: text/plain`,
  body the bare word, `Authorization: Bearer <token>`. Any non-2xx answer (a 401 too) counts as a
  failure. 3 s timeout per attempt through an `AbortController`, one retry after 500 ms, so a dead
  service shows `✗` after about 6.5 s. A newer publish aborts an older one still in flight, so a
  slow old response cannot change the status. A request already sent can still reach the service
  after a newer one, rarely, and `w` corrects it. Built with the token under `--watch`, each
  reload on screen 1 publishes `start` again. A second `--watch` on the same `--out` stops the first, so a
  watcher started without the token is replaced by one with it (README, Build). Chromium sent the preflight the spec predicted
  (`OPTIONS` with `Access-Control-Request-Headers: authorization`) from `file://` (`Origin: null`)
  and from `http://127.0.0.1`; the service must answer it for both (see "The service contract").
- **Presenter.** The deck posts the state in `animatic-state` (`waypoint`: `{enabled, word,
  status, at}`, `null` in an inert build) and the presenter posts `animatic-waypoint-resend` on
  `w`. The line has three more states than the text lists: `… sending` while a request is out,
  `none yet`, and the ✓/✗ ones. The element is in `presenter.html` only in a build with the token,
  and reuses the quick-select status line's class, so no CSS changed. `w` is unused elsewhere in
  both windows and the quick search, which swallows every key while open, swallows it. The deck
  window also handles `w`, since the deck is the one that publishes.
- **Not enforced:** that the first screen carries `start`. It is advice, and a talk with no
  `start` simply publishes nothing on load.
- **Unchanged by the feature** in a deck without marks: slide markup, CSS, document view,
  handout, `cues.json`, `nav.json`, `media-manifest.json`, and `tests/expected`. Checked on six
  real decks against the previous build: those files are byte-identical, and the present and
  presenter pages differ only inside their `<script>` elements (the pager gained the hook, the


## The service contract

Any small HTTP service will do. The deck needs this, at the URL given in
`waypoints.url`:

| Request | Behaviour |
|---|---|
| `GET <url>` | `200` with the current word as plain text, `404` if none, `Cache-Control: no-store`, no authentication |
| `POST <url>` | Bearer token required; plain-text word in the body; write it atomically |
| `OPTIONS <url>` | CORS preflight for decks opened from `file://` and `localhost` (`Authorization`, `POST`) |

Answer `401` for a bad or missing token, `405` for other methods, `413` for a body over
1 KB, and `400` for a word that is not lowercase letters, digits and hyphens. Send
`Access-Control-Allow-Origin` exactly once (a second copy makes browsers reject the
response). Keep the token out of any repo (an environment file works), compare it in
constant time, and store nothing about the participants.

## The participant side

A machine-side hook is outside this repo, but the idea is simple. A file of
`word | note` lines ships with the exercise files. On each message the hook fetches
the current word (with a 1-second timeout, falling back to the last word seen), looks
it up, and if the word is new prints that line's fixed note. It should also print a
`Room waypoint: <word>` line every time, so the agent always knows where the room is.
Only text the author wrote ever reaches the agent.

## Security and privacy

- **Remote text never reaches an agent.** The word must match a line in a local file
  and only that line's fixed text is used. A stolen token or a compromised service can
  choose among messages the author wrote, and nothing else. A word not in the file is
  ignored.
- **Nothing about a participant leaves the machine.** A `GET` carries the event name
  and, as any request does, the network's IP address. No chat text, no names.
- The token goes only into `present/index.html` of a build made with it, never into
  the document view, handout or web export.

## Failure behaviour

| Failure | What happens |
|---|---|
| Slow network on a participant machine | Up to 1 second's delay, no note. The next message picks it up. |
| Service down | The same, and the deck's status shows `✗`. |
| Presenter laptop offline | `✗` in the presenter window. Press `w` once it is back. |
| Deck reloaded mid-talk | The high-water mark resets, so re-reaching a word re-sends it; machines ignore repeats. |
| Pressed past a waypoint by mistake | Agents may get one early note. Go back and press `w`. |
| Previous run's word still published | Replaced by `start` when the deck opens. Open it before the room's first messages. |

## Tests

`tests/properties/waypoint_props.py` (in `tests/run.py`) and `tests/browser_waypoint.py`,
over `tests/fixtures/waypoints/`. The timeout can only be seen in real time, because
headless Chromium's virtual time stands still while a fetch is pending. Not verified:
browsers other than Chromium; Safari's handling of a `file://` page POSTing to `https://`.
