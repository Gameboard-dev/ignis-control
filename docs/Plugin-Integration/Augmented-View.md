# Augmented View: the desktop's model server from Ignis

Ignis Control lets Augmented View in a browser use the model server that desktop Obsidian runs on the PC.

The plugin itself is documented in
[its README](https://github.com/Gameboard-dev/obsidian-augmented-view#readme). This page covers the route through Ignis.

## Why

[Augmented View](https://github.com/Gameboard-dev/obsidian-augmented-view) marks key phrases with a model server.
Desktop Obsidian starts that server on `127.0.0.1:8790` (the plugin's **Port** setting). In a browser through Ignis,
the plugin cannot start a server, and the page cannot reach `127.0.0.1` on the PC. The relay passes the plugin's
requests to the server desktop Obsidian already runs.

## How it flows

Two routes reach the same server. Both allow the same four requests.

### Same-origin relay (current)

```
Augmented View in a tab ── /relay/augmented-view/<path> ──> Cloudflare Access ──> Ignis server (sandbox)
  ──> \\.\pipe\ignis-control-ignis-relay ──> launcher ──> http://127.0.0.1:<port>/<path>
```

The plugin uses this route when it runs in Ignis and its **Server address** is empty. It streams answers as they
come.

### Forwarder (older)

```
Augmented View in a tab ── http://127.0.0.1:18790/<path> ──> Ignis's proxy (PROXY_ALLOW_PRIVATE_HOSTS=127.0.0.1)
  ──> node.exe relay/augmented-view-forwarder.js (sandbox, 127.0.0.1:18790)
  ──> \\.\pipe\ignis-control-ignis-augmented-view ──> launcher ──> http://127.0.0.1:<port>/<path>
```

The plugin uses this route when its **Server address** is `http://127.0.0.1:18790`. Ignis's proxy passes an answer on
only when it is complete, so this route does not stream. The launcher always runs the forwarder; it appears as the
process `augmented-view` in the status.

`<port>`, on both routes, is `IGNIS_AUGMENTED_VIEW_PORT` from the launcher's environment or `<root>\ignis\.env`,
default 8790 (the server's own default). It is never read from the plugin's `data.json`: that file is in the vault,
which the browser can write, so a port taken from it could send the relayed requests to any other service on the PC.
If you change the plugin's **Port** on desktop, set `IGNIS_AUGMENTED_VIEW_PORT` to the same value; no restart is
needed, as it is read at every request. A value outside 1024–65535, or equal to 8080 or 18790, is replaced by 8790; a value that
is another relayed service's port is refused with 403
([configuration.md](../configuration.md#ports-of-the-relayed-services)).

## Scope

| Allowed | Refused (403, and `relay: refused …` in `ignis.log`) |
| --- | --- |
| `GET /health` | Everything else, including: |
| `GET /stats` (the server's read-only GPU and memory readings) | `POST /shutdown`, which would stop the server desktop Obsidian uses |
| `POST /emphasis` | `GET /docs` |
| `POST /claims` | Any path containing `..` or `//` |

- The relay never starts or stops the server. Start it from desktop Obsidian.
- One request per connection.
- On the same-origin relay, the request headers passed are `accept`, `accept-language`, `content-type`,
  `content-length`, `last-event-id`, `cache-control` and `user-agent`. No cookies and no Access token.
- On both routes, the launcher replaces `Host` and `Connection` and removes `Origin`.

## Set-up on the PC

1. Install Ignis Control ([installation.md](../installation.md)). The relay and the forwarder start with the launcher;
   nothing else is needed on the Ignis side.
2. In desktop Obsidian, start Augmented View's server and keep desktop Obsidian running while the browser uses it.

## Set-up in the plugin

In the browser, in Augmented View's settings, under the settings kept on this device only:

| Setting | Same-origin relay | Forwarder |
| --- | --- | --- |
| **Server address** | empty | `http://127.0.0.1:18790` |
| **Paragraphs per request** | the plugin's default | 16 (smaller requests show sooner, because the proxy does not stream) |

Both settings are kept in the browser's own storage, not in the vault's `data.json`, so desktop Obsidian keeps using
its own server.

## Status, logs and failures

| Where | What |
| --- | --- |
| Plugin panel, **Augmented View relay** | Counts of passed, refused and unavailable requests (for every relay service), and the last one |
| Plugin panel, process `augmented-view` | The forwarder's state |
| `<root>\ignis\ignis.log` | `relay: \\.\pipe\ignis-control-ignis-augmented-view -> 127.0.0.1:<port> (…)` at start; `relay: refused …` per refusal |

| Answer | Reason | Fix |
| --- | --- | --- |
| 502 `nothing answers on port <port> …` (same-origin relay) | The server is not running on the PC | Start it in desktop Obsidian |
| 502 `Augmented View server not reachable: …` (forwarder) | The launcher's relay or the server is not running | Start the server; check the launcher |
| 403 `… is not relayed` | The request is not one of the four | Expected |
