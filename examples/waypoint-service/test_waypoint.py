#!/usr/bin/env python3
"""Local checks for the waypoint example: the service, the hook and the word-list checker.

    python3 examples/waypoint-service/test_waypoint.py

The service runs as a real process on a free local port with a scratch data folder, and
the hook is the real script with its URL pointed at that port. Nothing leaves 127.0.0.1.
Exit status is 0 when every check passes.
"""
import http.client, os, shutil, socket, subprocess, sys, tempfile, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOKEN = "t" * 32
FAILS = []


def check(ok, name, detail=""):
    print(("PASS  " if ok else "FAIL  ") + name + (f"  [{detail}]" if detail and not ok else ""))
    if not ok:
        FAILS.append(name)


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def call(port, method, path, body=None, token=None):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    h = {"Authorization": f"Bearer {token}"} if token else {}
    c.request(method, path, body=body, headers=h)
    r = c.getresponse()
    return r.status, r.read().decode(), dict(r.getheaders())


def start(data, token, port):
    env = dict(os.environ, WAYPOINT_TOKEN=token)
    p = subprocess.Popen([sys.executable, str(HERE / "server.py"), "serve", "--data", str(data), "--port", str(port)],
                         env=env, stderr=subprocess.PIPE, text=True)
    for _ in range(50):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.1).close()
            return p
        except OSError:
            time.sleep(0.1)
    p.kill()
    raise SystemExit("server did not start")


def run_hook(script, tmp):
    r = subprocess.run(["bash", str(script)], env=dict(os.environ, TMPDIR=str(tmp)),
                       capture_output=True, text=True, timeout=10)
    return r.returncode, r.stdout


def main():
    work = Path(tempfile.mkdtemp(prefix="waypoint-test-"))
    server = None
    try:
        data, port = work / "data", free_port()
        server = start(data, TOKEN, port)
        P = "/waypoint/demo"
        check(call(port, "GET", P)[0] == 404, "no word yet: 404")
        check(call(port, "POST", P, "build")[0] == 401, "POST without a token: 401")
        check(call(port, "POST", P, "build", "x" * 32)[0] == 401, "POST with a wrong token: 401")
        check(call(port, "POST", P, "Not A Word", TOKEN)[0] == 400, "a bad word: 400")
        check(call(port, "POST", "/waypoint/bad_id", "build", TOKEN)[0] == 400, "a bad event name: 400")
        check(call(port, "POST", P, "x" * 2000, TOKEN)[0] == 413, "an oversize body: 413")
        s, body, _ = call(port, "POST", P, "start", TOKEN)
        check((s, body) == (200, "start"), "POST a word: 200")
        s, body, h = call(port, "GET", P)
        check(s == 200 and body == "start" and "X-Waypoint-Age" in h, "GET returns the word and its age")
        check(call(port, "PUT", P, "x", TOKEN)[0] == 405, "PUT: 405")
        check(call(port, "OPTIONS", P)[0] == 204, "OPTIONS preflight: 204")
        check(call(port, "GET", "/elsewhere/demo")[0] == 404, "outside the prefix: 404")

        # the hook, rendered against the local service
        hook = work / "hook"
        hook.mkdir()
        text = (HERE / "hook" / "waypoint.sh.in").read_text()
        text = text.replace("__URL__", f"http://127.0.0.1:{port}{P}").replace("__EVENT__", "demo")
        (hook / "waypoint.sh").write_text(text)
        shutil.copy(HERE / "hook" / "waypoints.txt", hook / "waypoints.txt")
        tmp = work / "tmp"
        tmp.mkdir()
        sh = hook / "waypoint.sh"

        call(port, "POST", P, "build", TOKEN)
        code, out = run_hook(sh, tmp)
        check(code == 0 and "[Workshop note]" in out and "Room waypoint: build" in out,
              "a new word prints its note and the status", out)
        code, out = run_hook(sh, tmp)
        check(code == 0 and "[Workshop note]" not in out and "Room waypoint: build" in out,
              "the same word prints the status only", out)
        call(port, "POST", P, "unlisted", TOKEN)
        code, out = run_hook(sh, tmp)
        check(code == 0 and out == "", "a word with no line is ignored", out)
        call(port, "POST", P, "break", TOKEN)
        os.utime(data / "demo.word", (time.time() - 4 * 3600,) * 2)
        code, out = run_hook(sh, tmp)
        check(code == 0 and out == "", "a word older than three hours is ignored", out)
        server.terminate()
        server.wait(timeout=5)
        server = None
        code, out = run_hook(sh, tmp)
        check(code == 0, "with the service down the hook still exits 0", out)

        # the word-list checker
        talk = work / "talk.md"
        talk.write_text("---\nslug: t\n---\n<!-- shot: waypoint=start -->\n# A\n\n<!-- shot: waypoint=build -->\n# B\n")
        words = work / "words.txt"
        words.write_text("start |\nbuild | a note\n")
        r = subprocess.run([sys.executable, str(HERE / "check-waypoints.py"), str(talk), str(words)],
                           capture_output=True, text=True)
        check(r.returncode == 0, "check-waypoints: a talk and list that agree pass", r.stdout)
        words.write_text("start |\n")
        r = subprocess.run([sys.executable, str(HERE / "check-waypoints.py"), str(talk), str(words)],
                           capture_output=True, text=True)
        check(r.returncode == 1 and "build" in r.stdout, "check-waypoints: a word missing from the list fails", r.stdout)
    finally:
        if server:
            server.kill()
        shutil.rmtree(work, ignore_errors=True)
    print(f"\n{'FAILED: ' + ', '.join(FAILS) if FAILS else 'all checks passed'}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
