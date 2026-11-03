# The relay

The relay lets an Obsidian plugin running in a browser through Ignis reach a service on the PC that hosts Ignis. The
sandbox cannot connect to the PC's services, and a browser page cannot reach `127.0.0.1` on another machine. The relay
is the one route between them, and it passes only listed requests.

## Contents

1. [Request path](#request-path)
2. [Ignis server rules (patch 0006)](#ignis-server-rules-patch-0006)
3. [Launcher rules](#launcher-rules)
4. [Services](#services)
5. [Answers and errors](#answers-and-errors)
6. [Using the relay from a plugin](#using-the-relay-from-a-plugin)
7. [Adding a service](#adding-a-service)
8. [The older Augmented View route](#the-older-augmented-view-route)

## Request path

```
plugin in a browser tab
  │ fetch("/relay/<service>/<path>")            same origin: covered by the Cloudflare Access session
  ▼
Cloudflare Access ──> tunnel ──> cloudflared ──> Ignis server (sandbox)
  │ apps/ignis-server/server/routes/local-relay.js (patch 0006): checks origin and service name, filters headers
  ▼
\\.\pipe\ignis-control-ignis-relay                  admits only the ignis-control.ignis container
  │
  ▼
launcher (outside the sandbox): checks the request against the service's allowlist
  │
  ├─ augmented-view ──> http://127.0.0.1:<port>/<path>
  └─ latex          ──> the launcher's own build, after the Access token is verified
```

The request body and the answer are streamed in both directions, server-sent events included.

## Ignis server rules (patch 0006)

The route is mounted at `/relay` before Ignis's body parsers and compression, so it streams.

| Check | Rule | Result if it fails |
| --- | --- | --- |
| Service name | The first path segment matches `^[a-z][a-z0-9-]{0,31}$` | 404 `no such relay service` |
| Origin | No `Origin` header (a same-origin `GET`, or not a browser), or an `Origin` whose host equals the request's `Host`, or an `Origin` listed in `WS_ORIGINS` | 403 `the relay serves only this page`, and a `relay: refused` line in the log |
| Relay switched on | `IGNIS_LOCAL_RELAY` is set | 503 `the relay is off: the launcher did not set IGNIS_LOCAL_RELAY` |
| Pipe served | The launcher answers on the pipe | 502 `the relay is not running (…): is the launcher up?` |

**Request headers passed to the launcher.** Only these: `accept`, `accept-language`, `content-type`,
`content-length`, `last-event-id`, `cache-control`, `user-agent`. For the service `latex` only, also
`cf-access-jwt-assertion`. For the service `quarry` only, also `authorization`: Quarry's own service token
(`Bearer <token>`), which Quarry's service checks on every request since 2026-10-30. Everything else stays in Ignis:
cookies (including `CF_Authorization`), `Authorization` for every other service, the Access token for every other
service, and forwarding headers. `Host` is set to `relay` and `Connection` to
`close`.

**Answer headers.** All headers from the launcher are passed back except `Connection`. Headers are sent at once, so
an event stream starts without delay.

**Cancellation.** When the browser closes the request (an `EventSource` closed, a page left), the request through the
pipe is ended too.

## Launcher rules

| Check | Rule | Result if it fails |
| --- | --- | --- |
| Known service | `augmented-view` or `latex` | 403 `no relayed service '<name>'` |
| Path form | The path (without the query) contains neither `..` nor `//` | 403 |
| Allowlist | The method and path are listed for the service ([Services](#services)) | 403, and `relay: refused <method> <path>: <why>` in the log |
| Service running | A connection to `127.0.0.1:<port>` succeeds within 5 s | 502 `nothing answers on port <port> for <path> (is the service running in desktop Obsidian?)` |

**Headers.** The launcher removes `Connection`, `Host` and `Origin`, and adds `Host: 127.0.0.1:<port>` and
`Connection: close`. The Ignis server has already checked the origin; removing it lets the service's own origin check
accept the request. The request body is passed on unchanged.

**Counting.** Each passed, refused or unavailable request is counted in `status.json` under `relay`.

## Services

Paths are relative to `/relay/<service>`: `GET /health` for `augmented-view` is `GET /relay/augmented-view/health`.

| Service | Destination | Allowed requests | Refused requests |
| --- | --- | --- | --- |
| `augmented-view` | `127.0.0.1:<port>`; `IGNIS_AUGMENTED_VIEW_PORT` from the launcher's environment or `ignis\.env`, default 8790 (never the vault's `data.json`) | `GET /health`, `GET /stats`, `POST /emphasis`, `POST /claims` | Everything else, including `POST /shutdown` and `GET /docs` |
| `quarry` | `127.0.0.1:<port>`; `IGNIS_QUARRY_PORT` from the launcher's environment or `ignis\.env`, default 8766 (never the vault's `data.json`) | The library, search, themes, citation trees, exclusions and credibility, indexing, and the review's reading and task-control tools ([the list](Plugin-Integration/Quarry.md#scope)); `POST /queue` without its `vault` and `config_dir` fields | Everything else, including the settings, keys, `POST /shutdown` and every assistant tool that writes |
| `latex` | The launcher's build | `GET /status`, `POST /compile`, each with a valid Cloudflare Access token | Everything else under `/relay/latex/` (404); any request without a valid token (403) |

Per-service detail:

- `augmented-view`: [Plugin-Integration/Augmented-View.md](Plugin-Integration/Augmented-View.md).
- `latex`: [Plugin-Integration/LaTeX.md](Plugin-Integration/LaTeX.md).
- `quarry`: [Plugin-Integration/Quarry.md](Plugin-Integration/Quarry.md).

A service's port never comes from the vault: the browser can write every file in it, so a port read from there could
point the relay at any service on the PC. Each port comes from the launcher's own settings (its environment or
`ignis\.env`). A port is used only if it is in 1024–65535 and is neither 8080 nor 18790; otherwise the default is
used. A request is then refused (403) if its service's port is also another known service's: another relayed
service's, Ignis's (8080) or the forwarder's (18790). If two relayed services are set to the same port, both are
refused until one is corrected.

## Answers and errors

| Status | From | Meaning |
| --- | --- | --- |
| Service's own | The service | Passed through unchanged |
| 403 | Ignis server | Another site's `Origin` |
| 403 | Launcher | Unknown service, path not allowed, `..` or `//` in the path, or (for `latex`) no valid Access token |
| 404 | Ignis server | Invalid service name |
| 404 | Launcher | Not a `latex` build request |
| 409 | Launcher | `latex`: a build is running, or Obsidian is open on the PC |
| 502 | Ignis server | The launcher is not serving the pipe |
| 502 | Launcher | The service is not running on the PC |
| 503 | Ignis server | `IGNIS_LOCAL_RELAY` is not set |
| 503 | Launcher | `latex`: TinyTeX or `main.tex` missing |

Errors from the relay itself are JSON: `{"error": "<reason>"}`.

## Using the relay from a plugin

1. **Detect Ignis.** The patched Ignis sets `window.__ignis` to an object (`{version, build}`) and adds the class
   `is-ignis` to `<html>`. Desktop Obsidian has neither.
2. **Build the address from the page's own origin.** `` `${location.origin}/relay/<service>/<path>` ``, or the relative
   path `/relay/<service>/<path>`. Do not use a stored address: the vault's `data.json` is shared with desktop
   Obsidian, which reaches the service directly.
3. **Send same-origin requests.** `fetch(url, { credentials: "same-origin" })`. `EventSource` works for event
   streams. No CORS set-up is needed.
4. **Handle refusals.** Expect 403 for requests the launcher does not list, and 502 when the service is not running
   on the PC. Show the `error` field.
5. **Do not start or stop the service.** A browser cannot start a program on the PC, and `shutdown` requests are
   refused.

## Adding a service

Services are defined in the launcher, outside the sandbox, so a page in the browser cannot add one. To add one, edit
`ignis_native.py`:

1. Write a function that returns the service's port, from `config("<NAME>")` (the launcher's environment or
   `ignis\.env`), never from a file in the vault or in `ignis\data` (the sandbox can write both). Pass it through `checked_port`, and add a fixed port the service must
   never be confused with to `OTHER_PORTS`.
2. Write an allowlist: a set of `(method, path)` pairs, or a function `(method, path) -> bool`.
3. Add an entry to `SERVICES`: `"<name>": (port_function, allows_function)`. Requests and answers pass through
   unchanged apart from the headers listed above.
4. Restart the launcher. The log's `relay:` line at start lists every service and its port.

The Ignis server needs no change: it passes any valid service name to the pipe.

## The older Augmented View route

Before the same-origin relay existed, Augmented View reached its server through Ignis's own proxy. The route still
runs:

```
Augmented View in a tab ── fetch http://127.0.0.1:18790 ──> Ignis's proxy (PROXY_ALLOW_PRIVATE_HOSTS=127.0.0.1)
  ──> relay/augmented-view-forwarder.js (sandbox, 127.0.0.1:18790)
  ──> \\.\pipe\ignis-control-ignis-augmented-view ──> launcher ──> 127.0.0.1:<port>
```

It allows the same four requests as the `augmented-view` service. Ignis's proxy passes an answer on only when it is
complete, so this route does not stream. Details:
[Plugin-Integration/Augmented-View.md](Plugin-Integration/Augmented-View.md).
