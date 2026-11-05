# Waypoints: telling participants' agents where the room is

**Status: design draft, 2026-11-05. Nothing here is built yet.**

When the talk reaches a marked slide, the deck publishes one word. Each time a
participant sends a message, a small hook on their machine reads that word and,
if it's new, adds a fixed note to what their agent sees. A person who is behind
hears about it from their own agent, without having to tell anyone.

```
deck (marked slide) ── POST word + token ──> tpl-waypoint service (behind Caddy)
                                                      │
machine (person sends a message) ── GET ──────────────┘
    └─ hook looks the word up in the seed files ──> note added to agent's context
```

Three parts: an animatic feature, a small service, and a hook in the seed files.

**Deliberately left out of this version:**

- **Waking an idle agent.** The agent stays quiet until a person types. "When someone
  is stuck" below covers that gap with a typed "help" instead. An `asyncRewake` poller
  can be added later without changing anything here, once it has been tested.
- **Communication back to Ryan.** The only route is the agent offering to wave
  him over.
- **Free-form messages.** Remote text never reaches an agent (see Security).

## 1. Animatic: marking and publishing

### Authoring

```yaml
waypoints:
  url: https://ryankelln.com/tpl_2026/waypoint/W11
```

```markdown
<!-- waypoint: expanding -->
```

- The directive goes on its own line and applies to the next screen.
- A word is lowercase letters, digits and hyphens, up to 24 characters, and can be
  used once per talk.
- It must be in the talkfile itself. In a `*.section.md` it would fire in every
  talk that includes that section.
- The first screen should carry `start`, so a run never begins on the previous
  run's last word.
- `cues.json` and `nav.json` gain a `waypoint` field on marked screens. Document
  view and handout don't show it. Decks without waypoints build byte-identically.
- Register check 49 (48 is quick select's): bad word, duplicate, directive inside a
  section, nothing following the directive, or directives with no `waypoints.url`.

### Token

The token comes from `ANIMATIC_WAYPOINT_TOKEN` at build time, and goes only into
`present/index.html`. A build without it is inert: nothing is published and no
status appears, so ordinary and rehearsal builds can't touch a live room. Web
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

### Implementation notes for section 1 (animatic, built 2026-11-05)

Built as specified. What the code does, and where it goes beyond or away from the text above:

- **Parsing.** The directive is lexed as its own block and then folded into the block after it
  (`talkparse._attach_waypoints`), so it can sit between a heading and the shot that heading
  titles without changing how either reads. `Screen.waypoint` carries the word.
- **Check 49 (free; 48 is quick select's)** is enforced in `talkparse.py` and registered in
  `check.py --register`. Beyond the listed cases it is also fatal when: the directive is split
  over several lines; two directives are in a row; text that joins an already open screen
  follows the directive (it marks the *next screen*, so there is none); or `waypoints:` is
  present with no `http(s)://` `url`, marks or not. A directive in a section is fatal whether the
  section is included or shelved, so no shelf screen can carry one.
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
  after a newer one, rarely, and `w` corrects it. Build without the token under `--watch`: each
  reload on screen 1 publishes `start` again. Chromium sent the preflight the spec predicted
  (`OPTIONS` with `Access-Control-Request-Headers: authorization`) from `file://` (`Origin: null`)
  and from `http://127.0.0.1`; the service must answer it for both (section 2 already says so).
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
  presenter scripts the state and the key).
- **Tests:** `tests/properties/waypoint_props.py` (in `tests/run.py`) and
  `tests/browser_waypoint.py`, over `tests/fixtures/waypoints/`. The timeout can only be seen in
  real time, because headless Chromium's virtual time stands still while a fetch is pending.
- **Not verified:** the real service (it does not exist yet, and nothing was sent to a real host);
  a browser other than Chromium; Safari's handling of a `file://` page POSTing to `https://`
  (it should behave as Chromium does, given the service answers the preflight, but it is untested).

## 2. The service

A sibling of the take-home drop, deployed the same way: `waypoint/server.py` in the
TPL repo, standard-library Python, a systemd unit running as `deploy` on
`127.0.0.1:8472`, and a Caddy route. It's about 190 lines. **Deployed 2026-11-05**;
setup and rollback are in `waypoint/README.md`.

| Request | Behaviour |
|---|---|
| `GET /tpl_2026/waypoint/W11` | `200` with the word, `404` if none, `Cache-Control: no-store`, no authentication |
| `POST /tpl_2026/waypoint/W11` | Bearer token required, plain-text word in the body, written atomically |
| `OPTIONS` | Preflight for `file://` and localhost decks (`Authorization`, `POST`) |

Other answers: `401` bad or no token, `405` other methods, `411` no length, `413` over 1 KB, `503` no
token configured. There is no delete route. The site-wide Caddy header supplies
`Access-Control-Allow-Origin`, once; a second copy would make browsers reject the response.

- The event must match `^[A-Z][0-9]{2}$` and the word the rule above. Anything else
  is `400`. Caddy caps the request body at 1 KB.
- The token lives in a systemd `EnvironmentFile`, is compared in constant time, and
  never appears in a repo.
- Words live in the service's own `data/` folder rather than `/var/www/tpl_2026`, so
  no payload publish can overwrite or delete them.
- It stores no IP addresses, logs or participant data.

**Caddy change, on the server shared with Ryan's other sites:** one new `handle`
block beside `@takehome`, and one `not path` line in `@payload`, so the matchers stay
disjoint. The site's global `Access-Control-Allow-Origin: *` can stay here, since
the token protects writes.

## 3. The machine side

An event opts in by having a `waypoints.txt` in its seed set.

**`.facilitator/waypoints.txt`, one line per word:**

```
start | 
key-choice | [Workshop note] Ryan has moved the room to The key choice. If this person isn't there yet, say so in one line and offer to finish the current step, or to wave Ryan over. Then deal with their message.
expanding | [Workshop note] Ryan has moved the room to Expanding. If this person isn't there yet, say so in one line and offer to finish the current step, or to wave Ryan over. Then deal with their message.
```

An empty message records the word and adds no note.

**The hook script.** For the W11 pilot it lives in `seed_src/assets/waypoint.sh.in`, with `__EVENT__`
filled in by W11's `assemble.py`, not in `payload/kit/`, because a kit change marks every event's
payload stale. This is the design sketch; the shipped version also skips the blank line for an
empty note and guards the word's length:

```bash
#!/bin/bash
# UserPromptSubmit hook. Prints the room's waypoint, plus a note if it's new. Always exits 0.
export LC_ALL=C
dir="$(cd "$(dirname "$0")" && pwd)"
seen="${TMPDIR:-/tmp}/tpl-waypoint-__EVENT__"
word="$(curl -fsS --max-time 1 "https://ryankelln.com/tpl_2026/waypoint/__EVENT__" 2>/dev/null)" \
  || word="$(cat "$seen" 2>/dev/null)"   # offline: use the last word seen
case "$word" in ""|*[!a-z0-9-]*) exit 0 ;; esac
line="$(awk -F ' *[|] *' -v w="$word" '$1==w {print; exit}' "$dir/waypoints.txt" 2>/dev/null)"
[ -n "$line" ] || exit 0
if [ "$word" != "$(cat "$seen" 2>/dev/null)" ]; then
  printf '%s\n' "$word" > "$seen" 2>/dev/null
  printf '%s\n' "${line#*|}" | sed 's/^ *//'
fi
printf 'Room waypoint: %s\n' "$word"
exit 0
```

The `Room waypoint:` line goes with every message, so the agent always knows where
the room is, which is what the "help" rule relies on. The longer note goes only when
the word changes.

**The event's `claude-settings.json` gains:**

```json
"hooks": {
  "UserPromptSubmit": [{ "hooks": [{
    "type": "command",
    "command": "bash \"$CLAUDE_PROJECT_DIR/.facilitator/waypoint.sh\"",
    "timeout": 3
  }]}]
}
```

**`flow.md` gains one short paragraph**, and the event's "How the phases are called"
table stays. Ryan still calls each phase out loud, because the note only reaches
someone when they next send a message. The agent should treat a note and a spoken
call as the same event.

### macOS points

- `/bin/bash` is 3.2, and `awk` and `sed` are the BSD versions. The script above uses
  no bash 4 features or GNU-only flags.
- The seen file must stay outside `~/workshop`: the installer refuses to replace a
  folder holding a file its receipt doesn't list, so a test prompt in the setup hour
  would block a reinstall. `$TMPDIR` avoids that, and Deep Freeze clears it.
- The `Bash(curl:*)` deny in workshop settings restricts Claude's Bash tool. It
  shouldn't affect a hook, but confirm this in the first test.
- A hook runs only after the folder is trusted, which the setup hour already does.

## When someone is stuck

Ryan's observation from the workshops: people often miss that the agent has asked
them something. They ask for a thing, expect it done, get a block of text ending in
a question or a confirmation, and sit there without answering. They rarely say so.

The waypoint hook can't reach them, because it needs a message. These parts do.

### Say "help"

Tell the room at the start, on a slide and out loud: **lost or not sure what to do?
Type "help".**

No skill or fetch is needed. `help` is an ordinary message, so the hook has already
given the agent the room's waypoint, and workshop settings deny the agent `curl` and
`WebFetch` anyway. Avoid teaching `/help`, which is Claude Code's built-in command.

**Add to each event's instructions:**

```markdown
## If the person says "help", "I'm lost", "what do I do?" or similar

Reply in at most three short lines:
1. Where the room is, from the latest "Room waypoint" line.
2. Where they are: look at their files. If you were waiting on an answer from them,
   say so and ask that one question again.
3. The one next thing to do, as something they can reply to, such as "Say yes and
   I'll finish this step so you can catch up." Offer to wave Ryan over if they prefer.
```

### Make the waiting obvious

**Add to each event's "How to help" section:**

```markdown
- Keep replies short. When you need something from the person, stop there and make
  it the last line, on its own, in this form:

  **Your turn:** Should the shop's name go at the top? Say yes or no.

  Ask one thing at a time, and never bury a question mid-reply. Don't ask for
  confirmation you don't need: if it's a safe next step, do it and say what you did.
```

**And one line to teach on the first slide:** "When it stops, it's waiting for you.
Read the last line." It names the broken expectation directly: the AI doesn't always
just do the thing, and stopping is normal rather than a failure.

### Future: an idle overview for Ryan (not in this version)

A view showing how long each machine has been idle, and whether someone seems to be
in trouble. An audible alert is ruled out: too disruptive in a workshop.

Likely shape, to design when it's picked up:

- Hooks post the machine number and a fixed status to the service: `Notification`
  (`idle_prompt` after about 60 seconds, and permission prompts), `UserPromptSubmit`
  and `Stop`.
- The presenter window shows one row per machine, with a time since last activity.
- Status comes from a fixed list and never includes chat text or names.
- "In trouble" is a question for then: plain idle and waiting-on-permission signals
  first, then possibly an agent-set flag from the fixed list.
- This is a new outbound data flow, so it needs IT's sign-off and should be disclosed
  to the room.

## Security and privacy

- **Remote text never reaches an agent.** The word must match a line in a seed file
  and only that line's fixed text is used. A stolen token or a compromised service
  can pick among messages Ryan wrote, and nothing else. A word not on the list is
  ignored without being marked as seen.
- **Nothing about a participant leaves the machine.** A `GET` carries the event name
  and, as any request does, the library's IP address. No chat text or machine number.
- **IT:** this needs a line in the data flow note. It is an outbound read-only request
  to the domain the machines already use for the installer and take-home.

## Failure behaviour

| Failure | What happens |
|---|---|
| Bad wifi or slow DNS on a machine | Up to 1 second's delay, no note. The next message picks it up. |
| Service down | The same, and the deck's status shows `✗`. |
| Laptop offline | `✗` in the presenter window. Press `w` once it's back. |
| Deck reloaded mid-talk | No publish, because the hash is set. The high-water mark resets, so re-reaching a word re-sends it, which machines ignore. |
| Pressed past a waypoint by mistake | Agents may get one early note. Go back and press `w`. |
| Previous run's word still published | Replaced by `start` when the deck opens. Open it before the room's first messages. |

## Tests

1. **Spike first, on the Mini:** do hooks from the workshop folder's settings fire and
   add context in **both** the CLI and the desktop **Code tab**? W06, W11 and W13 use
   the Code tab. If it doesn't work there, the pilot has to change, so this comes
   before the other work. **CLI passed 2026-11-05** (v2.1.278): the hook fired, the
   agent saw its text, and the hook's `curl` worked while the agent's own was denied
   by `Bash(curl:*)`. **Code tab passed 2026-11-05**: the agent repeated the hook's text
   exactly. Tested on the Mini's Claude Pro account, not a Team seat. **The real script passed
   on the Mini 2026-11-05** in the CLI (bash 3.2, BSD awk, 0.05 s normally, about 1 s with an
   unreachable host); log in W11's `test_runs/`. A deck on `file://` published `start` and
   `key-choice` to the live service.
2. `scripts/test_waypoint.py`: service validation, auth, atomic write, plus the hook
   script against a local service: new word, repeat, unknown word, bad characters,
   service down, empty message.
3. Animatic: golden suite unchanged, `tests/properties/waypoint_props.py`, and a
   browser test for publish rules, especially no publish on `prev()`, hash or `jump()`.
4. `scripts/check_waypoints.py <talk.md> <waypoints.txt>`: each word in the talk has a line
   in `waypoints.txt`, and the reverse, and the first directive is `start`. A mismatch fails silently in the room, so this
   check is what catches it.
5. A live check through the public URL with a test event, as
   `scripts/check_takehome_live.py` does for take-home.

## Rollout

1. Mini spike.
2. Service, Caddy route and hook script. Deploying to the shared server needs Ryan's
   go-ahead, as does the note to IT.
3. Animatic feature. It builds on quick select's pager changes, so it follows that
   merge.
4. **Pilot: W11.2, Nov 25.** Its flow already has a clear phase table: start,
   key-choice, expanding, sharing.
5. If it helps: W13.2 (Nov 26), W06.2 (Nov 30), W09.2 (Dec 7).
6. Decide about the poller from what the pilot shows. If people who've gone quiet are
   still getting lost, test `asyncRewake`.
