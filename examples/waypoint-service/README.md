# Waypoint service: an example receiver

A small service and hook that make the deck's waypoint feature useful in a workshop.
When the presenter reaches a marked slide, the deck publishes one word (`build`,
`break`). Each time a participant sends a message, a hook on their machine reads that
word and, if it is new, adds a fixed note to what their coding agent sees. Someone who
has fallen behind hears about it from their own agent, without asking anyone.

The deck's half is in the main repo (`docs/waypoints.md`). This folder is the other two
parts: a service to hold the word, and a hook to read it. Both are examples to adapt,
not a product. It was written for a library workshop series and is reduced here to the
parts anyone could reuse.

```
deck (marked slide) -- POST word + token --> service (this folder, server.py)
participant's machine (hook on each message) -- GET --> service
    +- hook looks the word up in a local file --> a fixed note for the agent
```

| File | What it is |
|---|---|
| `server.py` | The service. Standard library only. Its docstring lists the design rules. |
| `hook/waypoint.sh.in` | The hook script, a template. It also runs on macOS (bash 3.2, BSD tools). |
| `hook/waypoints.txt` | One `word \| note` line per word: the only text that can reach an agent. |
| `hook/claude-settings.json` | The hook registration for Claude Code (`UserPromptSubmit`). |
| `check-waypoints.py` | Checks a talkfile's `waypoint=word` flags against `waypoints.txt`, both ways. |
| `waypoint.service`, `Caddyfile.snippet` | A systemd unit and a Caddy route, to adapt. |
| `test_waypoint.py` | Local checks: starts the service, runs the real hook against it. No network. |

## The service

| Request | Result |
|---|---|
| `GET /waypoint/<event>` | `200` and the word, or `404` if none. `Cache-Control: no-store`. No authentication. `X-Waypoint-Age` is the whole seconds since the word was written, counted on the server. |
| `POST /waypoint/<event>` | `Authorization: Bearer <token>`, the word as a plain-text body. Written atomically; the last write wins. |
| `OPTIONS /waypoint/<event>` | The preflight for a deck opened from `file://` or localhost. |

An event is a short name (`workshop-3`), letters, digits and hyphens. A word is
lowercase letters, digits and hyphens, 1 to 24 characters. Anything else is `400`; a
body over 1 KB is `413`. Run it locally:

```sh
export WAYPOINT_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
python3 server.py serve --data ./data
curl -X POST -H "Authorization: Bearer $WAYPOINT_TOKEN" -d build http://127.0.0.1:8472/waypoint/demo
curl -i http://127.0.0.1:8472/waypoint/demo
```

**Remote text never reaches an agent.** The service stores a word and nothing else. The
hook looks the word up in a file on the participant's own machine and prints only that
line's fixed text. A stolen token, or a compromised service, can pick among the notes you
wrote, and nothing else. A word with no line is ignored.

**Nothing about a participant is kept.** A `GET` carries the event name and, as any
request does, the participant's IP address. The service keeps no addresses and logs only
the method, the path and the status.

**A leftover word is ignored.** The hook drops a word older than three hours (`max_age`
in `waypoint.sh.in`), so a test from the night before cannot tell a room where it is.
Still end your setup by opening the deck at screen 1, which publishes `start`.

## The token

One secret, used by the presenter's deck to write. It never goes in a repo or a
participant's files. Reads need no token, so nothing on participants' machines is secret.
The server refuses to start with a token under 20 characters, and starts read-only
(POST is `503`) with none.

The deck's build reads it from the environment, and it goes into `present/index.html` and
nowhere else:

```sh
ANIMATIC_WAYPOINT_TOKEN="$(cat ~/.config/waypoint/token)" python3 build.py talk.md
```

Rotate by making a new one and restarting the service; decks built with the old token
can no longer publish, which is the point.

## The hook

1. Write `waypoints.txt`: a `start` line with an empty note, then one line per word the
   talk marks.
2. Check the talk and the list agree (a word in one but not the other fails silently in
   the room):

   ```sh
   python3 check-waypoints.py talk.md hook/waypoints.txt
   ```

3. Render the script and put it with the list in the participant's project:

   ```sh
   sed -e "s#__URL__#https://example.org/waypoint/workshop-3#" -e "s#__EVENT__#workshop-3#" \
       hook/waypoint.sh.in > .facilitator/waypoint.sh
   cp hook/waypoints.txt .facilitator/
   ```

4. Register it in the project's `.claude/settings.json` (see `hook/claude-settings.json`).
   A Claude Code hook runs only after the folder is trusted.

The hook always exits 0, so it can never get between a person and their agent. If the
service is unreachable it uses the last word it saw.

On a shared or managed machine: a first test must confirm the hook fires, that `curl`
works from a hook (an agent's own `curl` may be denied), and that `$TMPDIR` is writable,
since the hook keeps its "last word seen" file there.

## Deploying

For a service the room can reach, run `server.py` behind TLS. A minimal path:

1. Copy `server.py` to the host, make a data folder (mode 700), and a `token.env` file
   (mode 600) with one line, `WAYPOINT_TOKEN=...`.
2. Adapt `waypoint.service` and enable it. The service listens on `127.0.0.1:8472`.
3. Put a reverse proxy in front (`Caddyfile.snippet`) that does TLS and caps the request
   body at 1 KB. Keep the data folder out of any web root.
4. Point the talkfile at it: `waypoints: { url: https://example.org/waypoint/workshop-3 }`.

Removing it: disable the unit, delete the unit file and the data folder, remove the proxy
route.

## Test it

```sh
python3 test_waypoint.py
```
