"""The launcher's relay rules and request handling (ignis/ignis_native.py), without pipes or the sandbox.

Run:  python -I ignis/test/relay_test.py  (in a clone of ignis-control: python -I test/relay_test.py)
A fake pipe connection feeds relay_one a request; local HTTP servers stand in for the services. The launcher's own
settings (ignis/.env and the environment) are replaced by temporary ones: the real ones are never read.
"""
import http.server
import json
import os
import sys
import tempfile
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ignis_native as n  # noqa: E402


class FakeConn:
    def __init__(self, data: bytes) -> None:
        self.chunks = [data[i:i + 7] for i in range(0, len(data), 7)]  # small pieces, as a pipe may give them
        self.out = b""

    def read(self) -> bytes:
        return self.chunks.pop(0) if self.chunks else b""

    def write(self, data: bytes) -> bool:
        self.out += data
        return True

    def close(self) -> None:
        pass


seen: list[tuple[int, str, str, bytes]] = []  # (the stand-in's port, method, path, body)


class Service(http.server.BaseHTTPRequestHandler):
    def _answer(self) -> None:
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        seen.append((self.server.server_address[1], self.command, self.path, body))
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"ok": true}')

    do_GET = do_POST = _answer

    def log_message(self, *args: object) -> None:
        pass


def stand_in() -> tuple[http.server.ThreadingHTTPServer, int]:
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Service)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, server.server_address[1]


def settings(tmp: Path, env_lines: str = "") -> None:
    """Point the launcher at temporary settings: ignis/.env with `env_lines`."""
    (tmp / "ignis").mkdir(exist_ok=True)
    (tmp / "ignis" / ".env").write_text(env_lines, encoding="utf-8")
    n.IGNIS = tmp / "ignis"


def routes() -> None:
    assert n.route_local("GET", "/augmented-view/health")[0] is not None
    assert n.route_local("POST", "/augmented-view/emphasis")[0] is not None
    assert n.route_local("GET", "/augmented-view/stats?x=1")[0][1] == "/stats?x=1"  # the query string is kept
    for refused in [("POST", "/augmented-view/shutdown"), ("GET", "/augmented-view/settings"),
                    ("GET", "/augmented-view/../health"), ("GET", "/augmented-view//health"),
                    ("GET", "/augmented-view/health/../stats"), ("GET", "/augmented-view"), ("GET", "/"),
                    ("GET", "/no-such-service/health"), ("POST", "/no-such-service/emphasis"),
                    ("GET", "/Augmented-View/health"), ("POST", "/unlisted/v2/predict/text")]:
        assert n.route_local(*refused)[0] is None, refused
    assert n.route_augmented_view("POST", "/emphasis")[0] is not None and n.route_augmented_view("POST", "/shutdown")[0] is None
    assert n.checked_port("80", 8766) == 8766 and n.checked_port(8080, 1) == 1 and n.checked_port("9000", 1) == 9000


def vault_cannot_redirect(tmp: Path) -> None:
    """The vault's data.json (which the browser can write) never sets where the relay sends Augmented View's requests."""
    lure, lure_port = stand_in()  # the service an attacker would aim at
    real, real_port = stand_in()  # Augmented View's server, as the launcher's settings name it
    n.VAULT = tmp / "vault"
    plugin = n.VAULT / ".obsidian" / "plugins" / "augmented-view"
    plugin.mkdir(parents=True)
    for port in (lure_port, 8766, 5000):
        (plugin / "data.json").write_text(json.dumps({"port": port}), encoding="utf-8")
        settings(tmp)  # no IGNIS_AUGMENTED_VIEW_PORT: the server's default
        assert n.augmented_view_port() == 8790, port
        assert n.route_local("GET", "/augmented-view/health")[0][0] == 8790, port
        assert n.route_augmented_view("GET", "/health")[0][0] == 8790, port

    # end to end, through both pipes' routes: data.json names the lure, the launcher's setting the real server
    settings(tmp, f'IGNIS_AUGMENTED_VIEW_PORT="{real_port}"\n')
    for route, target in ((n.route_local, b"/augmented-view/health"), (n.route_augmented_view, b"/health")):
        conn = FakeConn(b"GET " + target + b" HTTP/1.1\r\nHost: relay\r\nConnection: close\r\n\r\n")
        n.relay_one(conn, route)  # type: ignore[arg-type]
        assert b"200" in conn.out.split(b"\r\n")[0], conn.out
        assert seen[-1][:3] == (real_port, "GET", "/health"), seen[-1]
    assert not [s for s in seen if s[0] == lure_port], "a request reached the port data.json named"
    lure.shutdown()
    real.shutdown()


def other_services_refused(tmp: Path) -> None:
    """A relayed service whose port is another known service's gets nothing, whichever setting is wrong."""
    n.OTHER_PORTS["another local service"] = 5000  # a fixed port the relay must never send to
    try:
        settings(tmp, "IGNIS_AUGMENTED_VIEW_PORT=5000\n")
        assert n.route_local("GET", "/augmented-view/health")[0] is None
        assert n.route_augmented_view("GET", "/health")[0] is None
    finally:
        del n.OTHER_PORTS["another local service"]

    # two relayed services on one port: both refused, since neither is known to be right
    other_port = 8766
    saved = dict(n.SERVICES)
    n.SERVICES["other-service"] = (lambda: other_port, lambda m, p: (m, p) == ("GET", "/health"))
    try:
        settings(tmp, f"IGNIS_AUGMENTED_VIEW_PORT={other_port}\n")
        assert n.route_local("GET", "/augmented-view/health")[0] is None
        assert n.route_augmented_view("GET", "/health")[0] is None
        assert n.route_local("GET", "/other-service/health")[0] is None
        settings(tmp, "")  # apart again: each reaches its own port
        assert n.route_local("GET", "/augmented-view/health")[0][0] == 8790
        assert n.route_local("GET", "/other-service/health")[0][0] == other_port
    finally:
        n.SERVICES.clear()
        n.SERVICES.update(saved)
    assert n.route_local("GET", "/other-service/health")[0] is None

    settings(tmp, "IGNIS_AUGMENTED_VIEW_PORT=8080\n")  # Ignis's own port is never taken: the default instead
    assert n.augmented_view_port() == 8790
    settings(tmp, "IGNIS_AUGMENTED_VIEW_PORT=9100\n")
    assert n.route_local("GET", "/augmented-view/health")[0][0] == 9100
    os.environ["IGNIS_AUGMENTED_VIEW_PORT"] = "9200"  # the environment comes before ignis/.env
    settings(tmp, "IGNIS_AUGMENTED_VIEW_PORT=9300\n")
    assert n.augmented_view_port() == 9200
    del os.environ["IGNIS_AUGMENTED_VIEW_PORT"]


def dotenv_and_access(tmp: Path) -> None:
    """ignis/.env values may be quoted; the Access team may be its bare name or its domain."""
    assert n.unquoted('"a b"') == "a b" and n.unquoted("'x'") == "x" and n.unquoted('"x\'') == '"x\''
    assert n.unquoted('"') == '"' and n.unquoted("plain") == "plain" and n.unquoted('""') == ""
    for value in ("myteam", "myteam.cloudflareaccess.com", "https://myteam.cloudflareaccess.com/", "MyTeam"):
        assert n.access_team(value) == "myteam.cloudflareaccess.com", value
    for value in ("", "evil.com", "a.b.cloudflareaccess.com", "my team", "x/y", "myteam.cloudflareaccess.com.evil.com"):
        assert n.access_team(value) == "", value
    settings(tmp, '# a comment\nIGNIS_ACCESS_TEAM="myteam"\nIGNIS_ACCESS_AUD=\'abc123\'\n'
                  'IGNIS_ACCESS_EMAILS="A@example.com, b@example.com"\n')
    assert n.dotenv()["IGNIS_ACCESS_AUD"] == "abc123"
    assert n.access_config() == ("myteam.cloudflareaccess.com", "abc123", {"a@example.com", "b@example.com"})
    settings(tmp, "IGNIS_ACCESS_TEAM=https://myteam.cloudflareaccess.com/\nIGNIS_ACCESS_AUD=abc\nIGNIS_ACCESS_EMAILS=a@x.org\n")
    assert n.access_config() == ("myteam.cloudflareaccess.com", "abc", {"a@x.org"})
    settings(tmp, "IGNIS_ACCESS_TEAM=evil.com\nIGNIS_ACCESS_AUD=abc\nIGNIS_ACCESS_EMAILS=a@x.org\n")
    assert n.access_config() is None


def request_body(tmp: Path) -> None:
    """A request with a body through relay_one to a stand-in service: path and body arrive unchanged; refusals get 403
    and reach no service."""
    server, port = stand_in()
    settings(tmp, f"IGNIS_AUGMENTED_VIEW_PORT={port}\n")
    body = b'{"text": "a sentence", "n": 3}'
    request = (b"POST /augmented-view/emphasis?x=1 HTTP/1.1\r\nHost: relay\r\nContent-Type: application/json\r\n"
               b"Origin: https://allowed.example\r\nContent-Length: " + str(len(body)).encode() +
               b"\r\nConnection: close\r\n\r\n" + body)
    conn = FakeConn(request)
    n.relay_one(conn, n.route_local)  # type: ignore[arg-type]
    assert b"200" in conn.out.split(b"\r\n")[0] and conn.out.endswith(b'{"ok": true}'), conn.out
    assert seen[-1] == (port, "POST", "/emphasis?x=1", body), seen[-1]

    before = len(seen)
    for target in (b"/augmented-view/shutdown", b"/no-such-service/settings"):
        conn = FakeConn(b"POST " + target + b" HTTP/1.1\r\nContent-Length: 2\r\n\r\n{}")
        n.relay_one(conn, n.route_local)  # type: ignore[arg-type]
        assert conn.out.startswith(b"HTTP/1.1 403"), (target, conn.out)
    conn = FakeConn(b"not http\r\n\r\n")
    n.relay_one(conn, n.route_local)  # type: ignore[arg-type]
    assert conn.out.startswith(b"HTTP/1.1 403"), conn.out
    assert len(seen) == before, "a refused request reached the service"
    server.shutdown()


def ignored(lines: list[str], path: str) -> bool:
    """gitignore's rule for the launcher's anchored patterns: a path is ignored by the last line that matches it or one
    of its parent folders (`*` does not cross `/`); `!` watches it again."""
    import fnmatch
    import re
    parts = path.split("/")
    result = False
    for line in lines:
        negate = line.startswith("!")
        pattern = line.lstrip("!").lstrip("/")
        rx = re.compile(fnmatch.translate(pattern).replace(".*", "[^/]*"))
        if any(rx.match("/".join(parts[:k])) for k in range(1, len(parts) + 1)):
            result = not negate
    return result


def ignored_paths() -> None:
    """Ignis watches the four LaTeX files a browser must hear about, and nothing else of the build folder (an unwatched
    main.shown.pdf kept its old time in every tab, and the old PDF was shown even after a reload)."""
    lines = n.IGNORED_PATHS.split(",")
    assert "/LaTeX/compiled" not in lines, lines
    for name in n.LATEX_WATCHED:
        assert not ignored(lines, f"LaTeX/compiled/{name}"), name
    for path in ("LaTeX/compiled/main.aux", "LaTeX/compiled/2-chapter.tex", "LaTeX/compiled/latex-sync.log",
                 "LaTeX/compiled/tc/1-chapter-0.pdf", "LaTeX/compiled/code/listing.rs", "LaTeX/compiled/sub/main.pdf"):
        assert ignored(lines, path), path
    for path in ("LaTeX/compiled", "LaTeX/2-chapter.md", "notes/a.md", ".obsidian/plugins/some-plugin/data.json"):
        assert not ignored(lines, path), path
    # the same through Ignis's own matcher (packages/server-core/src/watcher.js), when its checkout (app/, SETUP.md)
    # and Node are here
    import shutil
    import subprocess
    here = Path(__file__).resolve().parents[1]
    watcher = here / "app" / "packages" / "server-core" / "src" / "watcher.js"
    node = next((str(p) for p in (here / "runtime" / "node.exe",) if p.is_file()), None) or shutil.which("node")
    if not (watcher.is_file() and node):
        print("relay: Ignis's own matcher not checked (no app checkout or no Node)")
        return
    script = ("const w = require(process.argv[1]); w.configure({ ignoredPaths: process.argv[2].split(',') });"
              "console.log(JSON.stringify(process.argv.slice(3).map((p) => w.isIgnoredPath(p))));")
    paths = [f"LaTeX/compiled/{name}" for name in n.LATEX_WATCHED] + ["LaTeX/compiled", "LaTeX/compiled/main.aux",
                                                                      "LaTeX/compiled/tc/x.pdf", "LaTeX/a.md"]
    out = subprocess.run([node, "-e", script, str(watcher), n.IGNORED_PATHS, *paths], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    got = json.loads(out.stdout)
    assert got == [ignored(lines, p) for p in paths], dict(zip(paths, got))


def names() -> None:
    """Every Windows name comes from one checked prefix; a hostile prefix stops the launcher instead of being used."""
    assert n.NAME == f"{n.PREFIX}.ignis" and n.LATEX_CONTAINER == f"{n.PREFIX}.latex"
    assert n.TOKEN_TARGET == f"{n.PREFIX}.ignis/cloudflared-tunnel-token"
    assert n.LOCAL_RELAY_PIPE == "\\\\.\\pipe\\" + n.PREFIX + "-ignis-relay"
    assert n.PIPE == "\\\\.\\pipe\\" + n.PREFIX + "-ignis-augmented-view"
    for good in ("ignis-control", "legacy", "a.b-c", "x" * 40):
        assert n.container_prefix(good) == good
    for bad in ("", "-x", ".x", "a b", "a&b", "a'b", 'a"b', "a\\b", "a/b", "é", "x" * 41):
        try:
            n.container_prefix(bad)
        except SystemExit:
            continue
        raise AssertionError(f"accepted {bad!r}")


def powershell_values() -> None:
    """Values reach PowerShell as environment variables only: quotes and separators in them run nothing."""
    import contextlib
    import io
    hostile = "a'; Write-Output INJECTED; '\" & echo INJECTED2 $(Write-Output INJECTED3)"
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = n.powershell("Write-Output $env:IGNIS_TEST_VALUE", IGNIS_TEST_VALUE=hostile)
    assert code == 0 and out.getvalue().strip() == hostile, out.getvalue()


def tunnel() -> None:
    """IGNIS_TUNNEL_PROTOCOL: quic by default, http2 or auto when set, anything else refused; always one argument."""
    assert n.tunnel_protocol(None) == ("quic", "") and n.tunnel_protocol("") == ("quic", "")
    for value, want in (("quic", "quic"), ("http2", "http2"), ("auto", "auto"), (" HTTP2 ", "http2")):
        assert n.tunnel_protocol(value) == (want, ""), value
    for bad in ("h2", "http2 --loglevel debug", "quic;calc", "tcp", "--protocol", "http2\nquic"):
        proto, why = n.tunnel_protocol(bad)
        assert proto == "" and "IGNIS_TUNNEL_PROTOCOL" in why, bad
    args = n.cloudflared_args("http2")
    assert args[args.index("--protocol") + 1] == "http2" and args.count("--protocol") == 1
    assert args[1:] == ["tunnel", "--no-autoupdate", "--protocol", "http2", "--edge-ip-version", "4", "run"]
    try:
        n.cloudflared_args("http2 --loglevel debug")
    except AssertionError:
        pass
    else:
        raise AssertionError("cloudflared_args took an unchecked protocol")


def main() -> None:
    n.log = lambda *a, **k: None  # type: ignore[assignment]
    os.environ.pop("IGNIS_AUGMENTED_VIEW_PORT", None)
    for name in ("IGNIS_ACCESS_TEAM", "IGNIS_ACCESS_AUD", "IGNIS_ACCESS_EMAILS"):
        os.environ.pop(name, None)
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        settings(tmp)
        names()
        powershell_values()
        tunnel()
        routes()
        ignored_paths()
        vault_cannot_redirect(tmp)
        other_services_refused(tmp)
        dotenv_and_access(tmp)
        request_body(tmp)
    print("relay: all checks passed")


if __name__ == "__main__":
    main()
