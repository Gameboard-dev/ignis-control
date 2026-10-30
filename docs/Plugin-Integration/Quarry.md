# Quarry: the desktop's service from Ignis

Ignis Control lets Quarry in a browser use the service that desktop Obsidian runs on the PC: search, the library,
themes, citation trees and the review's progress, with the models and the graphics card staying on the PC.

The plugin itself is documented in [its README](https://github.com/Gameboard-dev/Quarry#readme), and its side of this
route in [docs/ignis.md](https://github.com/Gameboard-dev/Quarry/blob/main/docs/ignis.md). This page covers the route
through Ignis.

## Why

Desktop Obsidian starts Quarry's service on `127.0.0.1:8766` (Quarry's **Port** setting). In a browser through Ignis,
the plugin cannot start a service, and the page cannot reach `127.0.0.1` on the PC. The relay passes the plugin's
requests to the service desktop Obsidian already runs.

## How it flows

```
Quarry in a tab ── /relay/quarry/<path>, Authorization: Bearer <token> ──> Cloudflare Access ──> Ignis server (sandbox)
  ──> \\.\pipe\ignis-control-ignis-relay ──> launcher ──> http://127.0.0.1:<port>/<path>
```

The plugin uses this route when it runs in Ignis and its **Service address** (kept on this device) is empty.

Two locks, each checked separately:

- **The relay's list** (below), checked by the launcher: what a browser may do at all.
- **The service's token**, checked by Quarry's service on every request. The browser cannot read it from the PC, so it
  is copied once from desktop Obsidian (Settings → Quarry → *Service token*) into the same setting in the browser,
  where it stays on that device. Ignis's server passes the `Authorization` header to `quarry` only
  (`patches/0006-relay.patch`); the launcher passes it on; the log pane hides it.

`<port>` is `IGNIS_QUARRY_PORT` from the launcher's environment or `<root>\ignis\.env`, default 8766 (the service's own
default). It is never read from Quarry's settings in the vault: the browser can write every file there, so a port
taken from it could send the relayed requests to any other service on the PC. If you change Quarry's **Port** on
desktop, set `IGNIS_QUARRY_PORT` to the same value; it is read at every request. A value outside 1024–65535, or equal
to 8080 or 18790, is replaced by 8766; a value that is another relayed service's port is refused with 403
([configuration.md](../configuration.md#ports-of-the-relayed-services)).

## Scope

| Allowed | Refused (403, and `relay: refused …` in `ignis.log`) |
| --- | --- |
| `GET /health`, `/stats`, `/events` (the progress stream) | `GET`/`POST /settings`: the settings hold folders and programs |
| `GET /library`, `/credibility`, `/citekeys`, `/bib`, `/duplicates`, `/preprints`, `/stale`, `/models`, `/skills`, `/hardware/recommend`, `/zotero/ping`, `/zotero/check` | `GET`/`POST /keys`, `POST /keys/check` |
| `POST /search`, `/similar`, `/connections`, `/citation-tree` | `POST /shutdown`, `/gpu/release`, `/queue/gpu` |
| `GET`/`POST /exclusions`, `POST /credibility/override` | `POST /archive-source`, `/zotero-web` |
| `GET /themes`, `/themes/<number>`; `POST /themes/rebuild`, `/themes/cancel` | `GET /assistant` (it names the vault's folder) |
| `GET /queue`; `POST /queue` (without `vault` and `config_dir`, below), `/queue/cancel` | Every other assistant tool, among them the ones that archive, retrieve or write |
| `POST /assistant/review_open`, `review_progress`, `list_tasks`, `task_control`, `retrieval_status` | Any other method or path, and any path containing `..` or `//` |

- **`POST /queue`** starts indexing, conversion or "Retrieve metadata". Its body may also name the vault's folder,
  which desktop Obsidian sends so that the service knows where the vault is. From the browser that field could point
  the service at another folder of the PC, the place where every new note goes, so the launcher reads this body whole
  (a single `Content-Length`, at most 1 MB, a JSON object), takes `vault` and `config_dir` out, and passes the rest.
  Any other body is refused with 400 before it reaches the service.
- The relay never starts or stops the service. Start it from desktop Obsidian, and turn off *Stop when idle* there
  for long remote use.
- One request per connection. Every other body passes unread, and answers stream.
- The request headers passed are `accept`, `accept-language`, `content-type`, `content-length`, `last-event-id`,
  `cache-control`, `user-agent` and, for this service only, `authorization`. No cookies and no Access token. The
  launcher replaces `Host` and `Connection` and removes `Origin`.

## Set-up on the PC

1. Install Ignis Control ([installation.md](../installation.md)), with the patches including the current
   `0006-relay.patch` (it passes the token).
2. In desktop Obsidian, start Quarry's service (status bar) and keep desktop Obsidian running while the browser uses
   it.
3. Copy the token from Settings → Quarry → *Service token*.

## Set-up in the plugin

In the browser, in Quarry's settings, under the settings kept on this device: paste the token into *Service token*,
and leave *Service address* empty. Both are kept in the browser's own storage, not in the vault's `data.json`.

## Status, logs and failures

| Where | What |
| --- | --- |
| Plugin panel, relay counts | Passed, refused and unavailable requests (for every relay service), and the last one |
| `<root>\ignis\ignis.log` | `relay: \\.\pipe\…-ignis-relay -> … /relay/quarry -> 127.0.0.1:<port>` at start; `relay: refused …` per refusal |

| Answer | Reason | Fix |
| --- | --- | --- |
| 502 `nothing answers on port <port> …` | The service is not running on the PC | Start it in desktop Obsidian |
| 401 from the service | No token, or not this service's token | Paste the token from desktop Obsidian; if the service's data folder was reset, copy the new one |
| 403 `… is not relayed` | The request is not on the list | Expected: do it in desktop Obsidian |
| 403 `quarry's port … is also …'s` | `IGNIS_QUARRY_PORT` equals another service's port | Set it to Quarry's **Port** |
| 400 from the relay on `POST /queue` | The body is not a single JSON object with a Content-Length | Report it: Quarry's plugin sends such a body |
