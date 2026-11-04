"""The launcher's Claude Code service (ignis/ignis_native.py): the argument rules, the request handling, and one
real round trip through the sandbox.

Run:  python -I ignis/test/claude_test.py  (in a clone of ignis-control: python -I test/claude_test.py)

A fake pipe connection stands in for Ignis's server, as in relay_test.py. The token check is replaced, so no
Cloudflare Access token is needed; that the check is made at all is tested on its own. The last test starts the real
CLI in its container with `--version`, which needs no sign-in and no network: it is skipped when the CLI is not
installed.
"""
import base64
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ignis_native as n  # noqa: E402

failures: list[str] = []


def check(what: str, got: object, want: object) -> None:
    if got != want:
        failures.append(f"{what}: got {got!r}, wanted {want!r}")
        print(f"  FAILED {what}: got {got!r}, wanted {want!r}")
    else:
        print(f"  ok {what}")


class FakeConn:
    """Ignis's end of the pipe: the request in small pieces, the answer collected."""

    def __init__(self, body: bytes = b"") -> None:
        self.chunks = [body[i:i + 7] for i in range(0, len(body), 7)]
        self.out = b""
        self.closed = False
        self.refuse_after = None  # bytes written after which write() fails, as a browser going away

    def read(self) -> bytes:
        return self.chunks.pop(0) if self.chunks else b""

    def write(self, data: bytes) -> bool:
        if self.refuse_after is not None and len(self.out) >= self.refuse_after:
            return False
        self.out += data
        return True

    def close(self) -> None:
        self.closed = True

    def status(self) -> str:
        return self.out.split(b"\r\n", 1)[0].decode("latin-1")

    def json(self) -> dict:
        return json.loads(self.out.split(b"\r\n\r\n", 1)[1].decode("utf-8"))

    def events(self) -> tuple[bytes, str]:
        """The output stream's data frames joined, and the exit event's value."""
        data, code = b"", ""
        for line in self.out.split(b"\r\n\r\n", 1)[1].split(b"\n"):
            if line.startswith(b"data: "):
                value = line[len(b"data: "):]
                if value.isdigit():
                    code = value.decode()
                else:
                    data += base64.b64decode(value)
        return data, code


def request(method: str, path: str, body: bytes = b"", token: str = "token") -> FakeConn:
    conn = FakeConn(body)
    headers = [f"Cf-Access-Jwt-Assertion: {token}"] if token else []
    if body:
        headers.append(f"Content-Length: {len(body)}")
    n.claude_relay(conn, method, path, headers, b"")
    return conn


class FakeSession:
    """A session that starts no process: the request handling is what is under test here."""

    counter = 0

    def __init__(self, args, cli, who) -> None:
        FakeSession.counter += 1
        self.id = f"session{FakeSession.counter}"
        self.args, self.who = args, who
        self.pid = 1000 + FakeSession.counter
        self.started = self.touched = n.time.time()
        self.exit = None
        self.taken = False
        self.chunks: list[bytes] = []
        self.ready = n.threading.Event()
        self.written = b""
        self.stopped = False

    def take(self):
        chunks, self.chunks = self.chunks, []
        self.ready.clear()
        return chunks

    def write(self, data: bytes) -> None:
        self.written += data

    def stop(self) -> None:
        self.stopped = True
        self.exit = 1
        self.ready.set()


def main() -> int:
    print("the arguments a start request may carry")
    check("a plain run", n.claude_args(["--print", "hello"])[0], ["--print", "hello"])
    check("not a list", n.claude_args("--print")[0], None)
    check("not all strings", n.claude_args(["--print", 7])[0], None)
    check("too many", n.claude_args(["x"] * (n.CLAUDE_ARGS_COUNT + 1))[0], None)
    check("too long", n.claude_args(["x" * (n.CLAUDE_ARGS_LIMIT + 1)])[0], None)
    check("a null character", n.claude_args(["--print", "a\0b"])[0], None)
    check("--add-dir refused", n.claude_args(["--add-dir", "/"])[0], None)
    check("--add-dir=... refused", n.claude_args(["--add-dir=C:\\"])[0], None)
    check("a path as a value is allowed", n.claude_args(["--model", "opus"])[0], ["--model", "opus"])

    print("\nevery request needs a Cloudflare Access token")
    real_email = n.access_email
    n.access_email = lambda token: (_ for _ in ()).throw(ValueError("no token")) if token != "token" else "me@x.y"
    refused = request("GET", "/status", token="")
    check("no token is refused", refused.status(), "HTTP/1.1 403 Forbidden")
    check("and nothing else is said", "error" in refused.json(), True)

    print("\nstatus")
    answer = request("GET", "/status")
    check("answered", answer.status(), "HTTP/1.1 200 OK")
    check("names the container", answer.json()["container"], n.CLAUDE_CONTAINER)
    check("lists no sessions", answer.json()["sessions"], [])

    print("\nstarting, writing, reading and stopping (no process started)")
    real_session, real_ready = n.ClaudeSession, n.claude_ready
    n.ClaudeSession, n.claude_ready = FakeSession, lambda: None
    try:
        started = request("POST", "/start", json.dumps({"args": ["--print", "hi"]}).encode())
        check("started", started.status(), "HTTP/1.1 200 OK")
        ident = started.json()["id"]
        session = n.CLAUDE_RUNNING[ident]
        check("the arguments reached it", session.args, ["--print", "hi"])

        bad = request("POST", "/start", json.dumps({"args": ["--add-dir", "/"]}).encode())
        check("a refused argument is a bad request", bad.status(), "HTTP/1.1 400 Bad Request")

        wrote = request("POST", f"/input/{ident}", b'{"type":"user"}\n')
        check("input accepted", wrote.json()["written"], 16)
        check("input reached the CLI", session.written, b'{"type":"user"}\n')

        missing = request("POST", "/input/nosuchsession", b"x")
        check("an unknown session is not found", missing.status(), "HTTP/1.1 404 Not Found")

        session.chunks = [b'{"type":"system"}\n']
        session.exit = 0
        session.ready.set()
        streamed = request("GET", f"/output/{ident}")
        check("the output streams as events", streamed.events()[0], b'{"type":"system"}\n')
        check("and ends with the exit code", streamed.events()[1], "0")
        check("the answer is an event stream", b"text/event-stream" in streamed.out, True)

        unknown = request("DELETE", "/start")
        check("another method is not found", unknown.status(), "HTTP/1.1 404 Not Found")

        n.CLAUDE_RUNNING.clear()
        for _ in range(n.CLAUDE_AT_ONCE):
            request("POST", "/start", json.dumps({"args": []}).encode())
        full = request("POST", "/start", json.dumps({"args": []}).encode())
        check(f"more than {n.CLAUDE_AT_ONCE} at once is refused", full.status(), "HTTP/1.1 429 Too Many Requests")
        for session in list(n.CLAUDE_RUNNING.values()):
            session.stop()
        n.CLAUDE_RUNNING.clear()
    finally:
        n.ClaudeSession, n.claude_ready = real_session, real_ready

    print("\none real round trip: the CLI in its container, which needs no sign-in for --version")
    cli = n.claude_cli()
    if cli is None:
        print("  skipped: the Claude Code CLI is not installed on this computer")
    else:
        n.claude_ready = lambda: None
        try:
            started = request("POST", "/start", json.dumps({"args": ["--version"]}).encode())
            check("started in the sandbox", started.status(), "HTTP/1.1 200 OK")
            if started.status().endswith("200 OK"):
                ident = started.json()["id"]
                streamed = request("GET", f"/output/{ident}")
                said, code = streamed.events()
                print(f"  it said: {said.decode('utf-8', 'replace').strip()!r}, exit {code}")
                check("it printed its version", b"(Claude Code)" in said, True)
                check("and exited cleanly", code, "0")
        finally:
            n.claude_ready = real_ready
            for session in list(n.CLAUDE_RUNNING.values()):
                session.stop()
            n.CLAUDE_RUNNING.clear()
    n.access_email = real_email

    print(f"\n{'FAILED: ' + '; '.join(failures) if failures else 'all checks passed'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
