#!/usr/bin/env python3
"""Browser test for waypoints (docs/waypoints.md, section 1): drive the built deck
in headless Chromium against a throwaway HTTP server that records every request,
the CORS preflight included.  Nothing here touches a real server: the deck's
`waypoints.url` is rewritten to 127.0.0.1 in a scratch copy of the fixture.

    python3 tests/browser_waypoint.py            # exit 0 pass, 1 fail, 77 no chromium

Builds tests/fixtures/waypoints (marked screens: 1 start, 4 key-choice,
6 expanding, 8 sharing; a shelf after the talk) into a scratch dir inside the repo
(a snap chromium cannot read /tmp) with ANIMATIC_WAYPOINT_TOKEN set, appends a driver to a copy of
the present page and reads the driver's JSON log out of the DOM.

Runs:

  1. rules (file://, origin null): `start` goes out on load with no hash and
     nothing else does; next() onto a marked screen publishes it; prev, a hash
     change, jump() and returnFromJump() never do; a next() pressed while a jump is
     out never does; going back and forward over a word that was published does
     not re-send it; `w` re-sends the latest word at or before the slide and
     the high-water mark follows it, so the next real advance publishes again.
     The server sees a preflight (Authorization is not a safelisted header), then
     a POST with `Authorization: Bearer <token>`, a text/plain body that is the
     word alone, and Origin: null.
  2. a reload mid-talk (hash set) and an opening on `#1` publish nothing.
  3. failure, in virtual time: a 500 is retried once and then reported, paging
     is never blocked, `w` re-sends once the service is back, a 500 then a 200
     ends well.
  4. failure, in real time: a server that never answers within 3 s is given up on
     after one retry.
  5. the presenter window (http, so the popup can be scripted): the status line,
     `w` in the presenter, and the quick search swallowing `w`.
  6. an inert build (no token): no module, no fetch, no status line, `w` does
     nothing, and the server never hears from it.

Needs chromium; without it the test exits 77.
"""

from __future__ import annotations

import functools
import html as htmllib
import http.server
import json
import os
import re
import shutil
import socketserver
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
FIXTURE = REPO / "tests" / "fixtures" / "waypoints"
TOKEN = "TESTTOKEN-q7Zk3-not-a-real-secret"
WPATH = "/event/waypoint/W99"


# ---------------------------------------------------------------------------
# the throwaway service: records everything, answers by mode
# ---------------------------------------------------------------------------

class Recorder:
    def __init__(self):
        self.log: list = []
        self.mode = "ok"
        self.count = 0
        self.result = None      # a driver in a real-time run posts its log here
        self.lock = threading.Lock()


def make_handler(rec: Recorder):
    class H(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):
            pass

        def _send(self, code, body=b"", extra=None):
            try:
                self.send_response(code)
                self.send_header("Access-Control-Allow-Origin", "*")
                for k, v in (extra or {}).items():
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except OSError:        # the browser gave up on this request
                pass

        def do_OPTIONS(self):
            with rec.lock:
                rec.log.append({"method": "OPTIONS", "path": self.path,
                                "origin": self.headers.get("Origin"),
                                "acrm": self.headers.get("Access-Control-Request-Method"),
                                "acrh": self.headers.get("Access-Control-Request-Headers")})
            self._send(204, b"", {
                "Access-Control-Allow-Methods": "POST, GET, OPTIONS",
                "Access-Control-Allow-Headers": "authorization, content-type",
                "Access-Control-Max-Age": "0"})

        def do_GET(self):
            u = urllib.parse.urlparse(self.path)
            if u.path == "/__log":
                with rec.lock:
                    body = json.dumps(rec.log).encode()
                self._send(200, body, {"Content-Type": "application/json"})
            elif u.path == "/__set":
                with rec.lock:
                    rec.mode = urllib.parse.parse_qs(u.query)["mode"][0]
                    rec.count = 0
                self._send(200, b"ok")
            elif u.path == "/__reset":
                with rec.lock:
                    rec.log.clear()
                    rec.mode, rec.count = "ok", 0
                self._send(200, b"ok")
            else:
                self._send(404)

        def do_POST(self):
            n = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(n).decode("utf-8", "replace")
            if self.path == "/__result":
                rec.result = body
                self._send(200, b"ok")
                return
            with rec.lock:
                rec.count += 1
                mode, count = rec.mode, rec.count
                rec.log.append({"method": "POST", "path": self.path, "body": body,
                                "auth": self.headers.get("Authorization"),
                                "ctype": self.headers.get("Content-Type"),
                                "origin": self.headers.get("Origin")})
            if self.headers.get("Authorization") != f"Bearer {TOKEN}":
                self._send(401)
            elif mode == "fail" or (mode == "once" and count == 1):
                self._send(500)
            elif mode == "slow":
                time.sleep(4.5)
                try:
                    self._send(200)
                except OSError:
                    pass
            else:
                self._send(200, b"ok")

    return H


def start_service():
    rec = Recorder()

    class S(socketserver.ThreadingMixIn, http.server.HTTPServer):
        daemon_threads = True

    srv = S(("127.0.0.1", 0), make_handler(rec))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, rec


# ---------------------------------------------------------------------------
# drivers
# ---------------------------------------------------------------------------

def common(port: int) -> str:
    return r"""
var A = window.animatic, log = [];
var SVC = "http://127.0.0.1:%d";
function ok(label, cond, detail) { log.push({label: label, ok: !!cond, detail: detail === undefined ? null : String(detail)}); }
function key(k) { document.dispatchEvent(new KeyboardEvent("keydown", {key: k, bubbles: true})); }
function wait(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }
function svc(path) { return fetch(SVC + path).then(function (r) { return r.text(); }); }
function posts() {
  return svc("/__log").then(function (t) { return JSON.parse(t).filter(function (e) { return e.method === "POST"; }); });
}
function words() { return posts().then(function (p) { return p.map(function (e) { return e.body; }); }); }
function finish() {
  var pre = document.createElement("pre");
  pre.id = "driver-log";
  pre.textContent = JSON.stringify(log);
  document.body.appendChild(pre);
}
// press next until the deck is on slide i (list steps count as presses)
function nextTo(i) { var g = 0; while (A.current() < i && g++ < 20) key("ArrowRight"); }
""" % port


def rules_driver(port: int) -> str:
    return "<script>\n(function () {\n" + common(port) + r"""
  (async function () {
    try {
      await wait(500);
      ok("opened at screen 1 with no hash", A.current() === 0 && location.hash === "", location.hash);
      ok("the module is there", !!A.waypoint);
      var w = await words();
      ok("on load, `start` is published", JSON.stringify(w) === '["start"]', JSON.stringify(w));
      ok("the status is ok", A.waypoint.state().status === "ok" && A.waypoint.state().word === "start", JSON.stringify(A.waypoint.state()));

      // next onto unmarked screens: nothing
      key("ArrowRight"); await wait(250);
      w = await words();
      ok("next onto an unmarked screen publishes nothing", w.length === 1, JSON.stringify(w));
      nextTo(3); await wait(400);
      w = await words();
      ok("next onto a marked screen publishes its word", A.current() === 3 && JSON.stringify(w) === '["start","key-choice"]', A.current() + " " + JSON.stringify(w));

      // prev and forward again over a word already published
      key("ArrowLeft"); await wait(200);
      w = await words();
      ok("prev publishes nothing", A.current() === 2 && w.length === 2, JSON.stringify(w));
      key("ArrowRight"); await wait(300);
      w = await words();
      ok("next back onto a published word does not re-send it (not later than the last word)", A.current() === 3 && w.length === 2, JSON.stringify(w));

      // a hash change onto a later marked screen
      location.hash = "#6"; await wait(300);
      w = await words();
      ok("a hash change onto a marked screen publishes nothing", A.current() === 5 && w.length === 2, A.current() + " " + JSON.stringify(w));
      key("ArrowLeft"); key("ArrowLeft"); await wait(200);
      ok("back at the key choice by prev", A.current() === 3, A.current());
      w = await words();
      ok("and prev still publishes nothing", w.length === 2, JSON.stringify(w));

      // jump and return
      A.jump(5); await wait(250);
      w = await words();
      ok("jump() onto a marked screen publishes nothing", A.current() === 5 && A.jumped() && w.length === 2, JSON.stringify(w));
      key("Escape"); await wait(250);
      w = await words();
      ok("returnFromJump() publishes nothing", A.current() === 3 && !A.jumped() && w.length === 2, JSON.stringify(w));
      A.jump(4); key("ArrowRight"); await wait(300);
      w = await words();
      ok("a next() onto a later marked screen while a jump is out publishes nothing",
         A.current() === 5 && A.jumped() && w.length === 2, A.current() + " " + JSON.stringify(w));
      key("Escape"); await wait(200);
      ok("returned again", A.current() === 3 && !A.jumped(), A.current());

      // the real advance
      key("ArrowRight"); key("ArrowRight"); await wait(400);
      w = await words();
      ok("next() onto the next marked screen publishes it",
         A.current() === 5 && JSON.stringify(w) === '["start","key-choice","expanding"]', A.current() + " " + JSON.stringify(w));

      // back over it and forward: not re-sent
      key("ArrowLeft"); key("ArrowLeft"); key("ArrowLeft"); await wait(150);
      ok("three back to the key choice", A.current() === 2 || A.current() === 3, A.current());
      nextTo(5); await wait(400);
      w = await words();
      ok("going back and forward over a published word does not re-send it", A.current() === 5 && w.length === 3, JSON.stringify(w));

      // w: the correction route
      A.go(3); await wait(100);
      key("w"); await wait(400);
      w = await words();
      ok("w on a marked screen re-sends that screen's word", w.length === 4 && w[3] === "key-choice", JSON.stringify(w));
      A.go(4); key("w"); await wait(400);
      w = await words();
      ok("w on an unmarked screen sends the latest word before it", w.length === 5 && w[4] === "key-choice", JSON.stringify(w));
      nextTo(5); await wait(400);
      w = await words();
      ok("after a correction the next real advance publishes again (the mark follows the last word sent)",
         w.length === 6 && w[5] === "expanding", JSON.stringify(w));
      A.go(0); key("w"); await wait(400);
      w = await words();
      ok("w on screen 1 sends start", w.length === 7 && w[6] === "start", JSON.stringify(w));
      // one mark at a time: a newer publish aborts an older one, so pressing through
      // several marks in one tick makes the count a race
      nextTo(3); await wait(400); nextTo(5); await wait(400); nextTo(7); await wait(400);
      w = await words();
      ok("next onto the last marked screen publishes it", A.current() === 7 && w[w.length - 1] === "sharing" && w.length === 10,
         A.current() + " " + JSON.stringify(w));
      var n9 = w.length;
      key("ArrowRight"); key("ArrowRight"); key("End"); key("Home"); await wait(300);
      w = await words();
      ok("the last screen, End and Home publish nothing", w.length === n9, JSON.stringify(w));
      A.go(0); key("w"); await wait(300);
      A.jump(9); key("w"); await wait(400);
      w = await words();
      ok("w on a shelf screen uses the slide a jump will return to (screen 1: start)",
         w.length === n9 + 2 && w[w.length - 1] === "start", JSON.stringify(w.slice(n9)));

      // the wire: preflight, then a POST with the token and the bare word
      var all = JSON.parse(await svc("/__log"));
      var pf = all.filter(function (e) { return e.method === "OPTIONS"; });
      ok("the browser sent a preflight", pf.length > 0 && pf.every(function (e) { return /authorization/i.test(e.acrh || "") && e.acrm === "POST"; }),
         JSON.stringify(pf[0]));
      ok("the first request was the preflight", all[0].method === "OPTIONS", all[0].method);
      var ps = all.filter(function (e) { return e.method === "POST"; });
      ok("every POST carries the bearer token", ps.every(function (e) { return e.auth === "Bearer %TOKEN%"; }), ps[0].auth);
      ok("every POST is text/plain with the bare word", ps.every(function (e) { return /^text\/plain/.test(e.ctype) && /^[a-z0-9-]{1,24}$/.test(e.body); }),
         ps[0].ctype + " " + ps[0].body);
      ok("every POST goes to the talk's url", ps.every(function (e) { return e.path === "%WPATH%"; }), ps[0].path);
      ok("from a file:// page the origin is null", location.protocol !== "file:" || ps.every(function (e) { return e.origin === "null"; }), ps[0].origin);
    } catch (e) { log.push({label: "driver error", ok: false, detail: String(e && e.stack || e)}); }
    finish();
  })();
})();
</script>
""".replace("%TOKEN%", TOKEN).replace("%WPATH%", WPATH)


def hash_driver(port: int) -> str:
    return "<script>\n(function () {\n" + common(port) + r"""
  (async function () {
    try {
      await wait(600);
      ok("opened with a hash", location.hash !== "", location.hash);
      var w = await words();
      ok("a deck opened on a hash publishes nothing on load", w.length === 0, JSON.stringify(w));
      nextTo(3); await wait(500);
      w = await words();
      ok("the first real advance after a reload publishes (the mark starts again)", JSON.stringify(w) === '["key-choice"]', JSON.stringify(w));
    } catch (e) { log.push({label: "driver error", ok: false, detail: String(e && e.stack || e)}); }
    finish();
  })();
})();
</script>
"""


def fail_driver(port: int) -> str:
    return "<script>\n(function () {\n" + common(port) + r"""
  var t0 = Date.now();
  (async function () {
    try {
      // /__set mode=fail was applied by the harness before this page loaded: `start` meets a 500
      await wait(2000);
      var w = await words();
      ok("a 500 is retried once, then given up", JSON.stringify(w) === '["start","start"]', JSON.stringify(w));
      var st = A.waypoint.state();
      ok("the state says failed", st.status === "fail" && st.word === "start", JSON.stringify(st));

      var t1 = performance.now();
      key("ArrowRight"); key("ArrowRight");
      ok("paging is not blocked by a failed publish", A.current() === 1 || A.current() === 2, A.current());
      nextTo(3);
      ok("and a failing publish does not hold the pager", A.current() === 3 && performance.now() - t1 < 100, performance.now() - t1);
      await wait(2000);
      w = await words();
      ok("the marked screen tried, and retried", w.length === 4 && w[2] === "key-choice" && w[3] === "key-choice", JSON.stringify(w));

      await svc("/__set?mode=ok");
      key("w"); await wait(400);
      w = await words();
      st = A.waypoint.state();
      ok("w re-sends the latest word once the service is back", w.length === 5 && w[4] === "key-choice" && st.status === "ok" && st.word === "key-choice", JSON.stringify(w) + JSON.stringify(st));

      // a 500 then a 200: the retry succeeds
      await svc("/__set?mode=once");
      nextTo(5); await wait(1500);
      w = await words();
      st = A.waypoint.state();
      ok("a failure then a success ends well (two POSTs)", w.length === 7 && w[5] === "expanding" && w[6] === "expanding" && st.status === "ok", JSON.stringify(w.slice(5)) + st.status);

      // never blocks, even while a request is out
      await svc("/__set?mode=ok");
    } catch (e) { log.push({label: "driver error", ok: false, detail: String(e && e.stack || e)}); }
    finish();
  })();
})();
</script>
"""


def slow_driver(port: int) -> str:
    return "<script>\n(function () {\n" + common(port) + r"""
  (async function () {
    try {
      // the service answers after 4.5 s, longer than the 3 s timeout, every time
      var t0 = Date.now();
      await wait(300);
      var st = A.waypoint.state();
      ok("a publish in flight says so", st.status === "pending" && st.word === "start", JSON.stringify(st));
      var t1 = performance.now();
      key("ArrowRight"); key("ArrowRight");
      ok("paging is immediate while a request is out", A.current() === 1 || A.current() === 2, A.current());
      ok("and it takes no time", performance.now() - t1 < 100, performance.now() - t1);
      // timeout at 3 s, retry at 3.5 s, second timeout at 6.5 s
      await wait(2400);
      st = A.waypoint.state();
      ok("still trying at 2.7 s", st.status === "pending", JSON.stringify(st));
      await wait(1500);
      var w = await words();
      st = A.waypoint.state();
      ok("a request that does not answer in 3 s is retried once (two POSTs at 4.2 s)", w.length === 2 && st.status === "pending", JSON.stringify(w) + st.status);
      await wait(3200);
      st = A.waypoint.state();
      w = await words();
      ok("after the second timeout it is reported failed, with no third try", st.status === "fail" && w.length === 2, JSON.stringify(w) + JSON.stringify(st));
      var secs = (Date.now() - t0) / 1000;
      ok("it took about 6.5 s (3 + 0.5 + 3)", secs > 6.0 && secs < 8.5, secs);
    } catch (e) { log.push({label: "driver error", ok: false, detail: String(e && e.stack || e)}); }
    finish();
    try { await fetch(SVC + "/__result", {method: "POST", body: JSON.stringify(log)}); } catch (e) {}
  })();
})();
</script>
"""


def popup_driver(port: int) -> str:
    return "<script>\n(function () {\n" + common(port) + r"""
  var sent = [];
  window.addEventListener("message", function (e) { if (e.data && e.data.type) sent.push(e.data.type); });
  function resends() { return sent.filter(function (t) { return t === "animatic-waypoint-resend"; }).length; }
  (async function () {
    try {
      await wait(400);
      key("s");
      await wait(1200);
      var P = window.open("", "animatic-presenter");
      ok("the presenter window opened", !!P && P.document.title.indexOf("presenter") > 0);
      var D = P.document;
      function pkey(k, target) {
        (target || D.activeElement || D.body).dispatchEvent(new P.KeyboardEvent("keydown", {key: k, bubbles: true, cancelable: true}));
      }
      function q(id) { return D.getElementById(id); }
      await wait(400);
      var line = q("presenter-waypoint");
      ok("the presenter has a waypoint line", !!line);
      ok("it shows the word and a tick with a time", line && !line.hidden && /^Waypoint: start ✓ \d{1,2}:\d{2}(am|pm)$/.test(line.textContent), line && line.textContent);

      key("ArrowRight"); nextTo(3); await wait(500);
      ok("after an advance onto a marked screen the line names that word", /^Waypoint: key-choice ✓ /.test(line.textContent), line.textContent);

      // w in the presenter window
      var n0 = (await words()).length;
      pkey("w", D.body); await wait(500);
      var w = await words();
      ok("w in the presenter asks the deck to re-send", resends() === 1 && w.length === n0 + 1 && w[w.length - 1] === "key-choice", resends() + " " + JSON.stringify(w));

      // failure and retry through the presenter's w
      await svc("/__set?mode=fail");
      pkey("w", D.body); await wait(1600);
      ok("a failure shows ✗ and the key to press", /^Waypoint: key-choice ✗ not sent, w to retry$/.test(line.textContent), line.textContent);
      await svc("/__set?mode=ok");
      pkey("w", D.body); await wait(500);
      ok("w again, with the service back, shows the tick", /^Waypoint: key-choice ✓ /.test(line.textContent), line.textContent);

      // the quick search swallows w
      var nBefore = (await words()).length, rBefore = resends();
      pkey("/", D.body); await wait(150);
      ok("the search is open", q("quick").hidden === false);
      var inp = q("quick-input");
      pkey("w", inp); pkey("W", inp); await wait(500);
      ok("w typed in the search sends nothing to the deck", resends() === rBefore, resends());
      ok("and the deck published nothing", (await words()).length === nBefore);
      pkey("Escape", inp); await wait(150);
      ok("the search closed", q("quick").hidden === true);
      ok("the window is still open and the line is unchanged", !P.closed && /✓/.test(line.textContent), line.textContent);

      // a jump is not a publish, and the line does not change for it
      var nJ = (await words()).length;
      pkey("/", D.body);
      inp.value = "agent"; inp.dispatchEvent(new P.Event("input", {bubbles: true}));
      pkey("Enter", inp); await wait(500);
      ok("a quick-select jump from the presenter publishes nothing", A.jumped() && (await words()).length === nJ, A.current());
      pkey("w", D.body); await wait(500);
      w = await words();
      ok("w on a shelf screen sends the word for the slide a jump returns to", w.length === nJ + 1 && w[w.length - 1] === "key-choice", JSON.stringify(w.slice(nJ)));
      pkey("Escape", D.body); await wait(300);
      ok("Esc returns and publishes nothing", !A.jumped() && (await words()).length === nJ + 1);
    } catch (e) { log.push({label: "driver error", ok: false, detail: String(e && e.stack || e)}); }
    finish();
  })();
})();
</script>
"""


def inert_driver(port: int) -> str:
    return "<script>\n(function () {\n" + common(port) + r"""
  var sent = [];
  window.addEventListener("message", function (e) { if (e.data && e.data.type) sent.push(e.data.type); });
  var fetches = 0, realFetch = window.fetch;
  window.fetch = function () { fetches++; return realFetch.apply(this, arguments); };
  (async function () {
    try {
      await wait(400);
      ok("no waypoint module in an inert build", A.waypoint === undefined && A.addOnNext !== undefined);
      key("w");
      for (var i = 0; i < 10; i++) key("ArrowRight");
      key("End"); key("w"); key("Home"); key("w");
      A.jump(9); key("w"); A.returnFromJump();
      await wait(400);
      ok("no fetch was made by the deck", fetches === 0, fetches);
      ok("no token module text in the page", document.documentElement.outerHTML.indexOf("Bea" + "rer") < 0);
      key("s"); await wait(1200);
      var P = window.open("", "animatic-presenter");
      var D = P.document;
      ok("the presenter has no waypoint line at all", D.getElementById("presenter-waypoint") === null);
      D.body.dispatchEvent(new P.KeyboardEvent("keydown", {key: "w", bubbles: true, cancelable: true}));
      await wait(300);
      ok("w in the presenter posts nothing", sent.indexOf("animatic-waypoint-resend") < 0, sent.join(","));
      ok("the status text has no trace of a waypoint", !/Waypoint/.test(D.body.innerText));
    } catch (e) { log.push({label: "driver error", ok: false, detail: String(e && e.stack || e)}); }
    finish();
  })();
})();
</script>
"""


# ---------------------------------------------------------------------------
# plumbing
# ---------------------------------------------------------------------------

def chromium_path() -> str | None:
    return (shutil.which("chromium-browser") or shutil.which("chromium")
            or shutil.which("google-chrome"))


def build_scratch(tmp: Path, port: int, token: str | None) -> Path:
    deck = tmp / "deck"
    shutil.copytree(FIXTURE, deck)
    talk = deck / "talk.md"
    talk.write_text(re.sub(r"url: \S+ }", f"url: http://127.0.0.1:{port}{WPATH} }}",
                           talk.read_text(encoding="utf-8")), encoding="utf-8")
    out = tmp / "out"
    env = dict(os.environ)
    env.pop("ANIMATIC_WAYPOINT_TOKEN", None)
    if token:
        env["ANIMATIC_WAYPOINT_TOKEN"] = token
    r = subprocess.run([sys.executable, str(REPO / "build.py"), str(talk), "--out", str(out)],
                       check=True, capture_output=True, text=True, env=env)
    if token and token in r.stdout + r.stderr:
        raise SystemExit("FAIL: the build log printed the token")
    return out


def run_page(chromium: str, url: str, budget: int | None = 15000, real_ms: int | None = None) -> list:
    args = [chromium, "--headless", "--disable-gpu", "--no-sandbox", "--disable-popup-blocking",
            "--autoplay-policy=no-user-gesture-required"]
    if real_ms:
        args.append(f"--timeout={real_ms}")
    elif budget:
        args.append(f"--virtual-time-budget={budget}")
    proc = subprocess.run(args + ["--dump-dom", url], capture_output=True, text=True, timeout=180)
    m = re.search(r'<pre id="driver-log">(.*?)</pre>', proc.stdout, re.DOTALL)
    if not m:
        print("FAIL: the driver log never appeared\n", proc.stderr[-800:])
        return [{"label": "driver log missing", "ok": False, "detail": ""}]
    return json.loads(htmllib.unescape(m.group(1)))


def run_page_real(chromium: str, url: str, rec: Recorder, limit: float = 40.0) -> list:
    """Real time: virtual time stands still while a fetch is pending, so a 3 s
    timeout can only be seen on a real clock.  The driver posts its log back to
    the recorder; chromium is killed once it has."""
    prof = tempfile.mkdtemp(prefix="waypoint-profile-", dir=REPO)
    rec.result = None
    proc = subprocess.Popen(
        [chromium, "--headless", "--disable-gpu", "--no-sandbox", f"--user-data-dir={prof}",
         url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        t0 = time.time()
        while rec.result is None and time.time() - t0 < limit:
            time.sleep(0.2)
    finally:
        proc.kill()
        proc.wait()
        shutil.rmtree(prof, ignore_errors=True)
    if rec.result is None:
        print("FAIL: the real-time driver never reported")
        return [{"label": "driver log missing", "ok": False, "detail": ""}]
    return json.loads(rec.result)


def report(name: str, log: list) -> int:
    bad = 0
    for e in log:
        if not e["ok"]:
            bad += 1
            print(f"  FAIL  {name}: {e['label']}  [{e['detail']}]")
    print(f"{'ok  ' if not bad else 'FAIL'}  {name}: {len(log)} checks")
    return bad


def serve_dir(root: Path):
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass
    srv = socketserver.TCPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=str(root)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def main() -> int:
    chromium = chromium_path()
    if not chromium:
        print("skip: no chromium")
        return 77
    tmp = Path(tempfile.mkdtemp(prefix="waypoint-scratch-", dir=REPO))
    svc, rec = start_service()
    page_srv = None
    port = svc.server_address[1]
    bad = 0
    try:
        out = build_scratch(tmp, port, TOKEN)
        page = (out / "present" / "index.html").read_text(encoding="utf-8")
        for name, driver in (("rules", rules_driver), ("hash", hash_driver), ("fail", fail_driver),
                             ("slow", slow_driver), ("popup", popup_driver)):
            (out / "present" / f"{name}.html").write_text(
                page.replace("</body>", driver(port) + "</body>"), encoding="utf-8")

        def fresh(mode="ok"):
            with rec.lock:
                rec.log.clear()
                rec.mode, rec.count = mode, 0

        fresh()
        bad += report("rules (file://)", run_page(chromium, f"file://{out / 'present' / 'rules.html'}"))
        fresh()
        log = run_page(chromium, f"file://{out / 'present' / 'hash.html'}#3")
        bad += report("opened on a hash (file://)", log)
        fresh()
        log = run_page(chromium, f"file://{out / 'present' / 'hash.html'}#1")
        bad += report("opened on #1 (file://)", log)
        fresh("fail")
        bad += report("failure and retry (file://)", run_page(chromium, f"file://{out / 'present' / 'fail.html'}"))
        fresh("slow")
        bad += report("timeout, real time (file://)",
                      run_page_real(chromium, f"file://{out / 'present' / 'slow.html'}", rec))
        fresh()
        page_srv = serve_dir(tmp)
        pport = page_srv.server_address[1]
        bad += report("presenter window (http)", run_page(chromium, f"http://127.0.0.1:{pport}/out/present/popup.html"))
        # localhost origin: the same deck over http sends Origin: http://127.0.0.1:<port>
        with rec.lock:
            origins = {e["origin"] for e in rec.log if e["method"] == "POST"}
        if origins != {f"http://127.0.0.1:{pport}"}:
            bad += 1
            print(f"  FAIL  localhost deck's origin was {origins}")
        else:
            print("ok    a localhost deck's POSTs carry its own origin and pass the preflight")

        # an inert build: no token
        tmp2 = tmp / "inert"
        tmp2.mkdir()
        out2 = build_scratch(tmp2, port, None)
        page2 = (out2 / "present" / "index.html").read_text(encoding="utf-8")
        (out2 / "present" / "inert.html").write_text(
            page2.replace("</body>", inert_driver(port) + "</body>"), encoding="utf-8")
        fresh()
        bad += report("inert build (http)", run_page(chromium, f"http://127.0.0.1:{pport}/inert/out/present/inert.html"))
        with rec.lock:
            heard = list(rec.log)
        if heard:
            bad += 1
            print(f"  FAIL  an inert deck contacted the service: {heard}")
        else:
            print("ok    an inert deck never contacted the service (no POST, no preflight)")
        return 1 if bad else 0
    finally:
        svc.shutdown()
        if page_srv:
            page_srv.shutdown()
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
