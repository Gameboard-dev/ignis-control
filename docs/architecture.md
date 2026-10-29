# Architecture

How the parts of Ignis Control fit together: the processes, the sandbox and its rights, the named pipes, the status
file and the log.

## Overview

```
 any browser
     │ https
     ▼
 Cloudflare edge ── Cloudflare Access (one-time PIN) ──┐
                                                       │ tunnel: QUIC over IPv4, opened outbound by cloudflared
 ┌──────────────── AppContainer "ignis-control.ignis" ─▼────────────────────────────────────────────┐
 │                                                                                                  │
 │  cloudflared ── http://127.0.0.1:8080 ──> node.exe (Ignis server, patched)                       │
 │                                              │  /relay/<service>/...                             │
 │  node.exe augmented-view-forwarder.js        │                                                   │
 │  (127.0.0.1:18790)                           │                                                   │
 │        │                                     │                                                   │
 └────────┼─────────────────────────────────────┼───────────────────────────────────────────────────┘
          │ \\.\pipe\ignis-control-ignis-       │ \\.\pipe\ignis-control-ignis-relay
          │   augmented-view                    │
          ▼                                     ▼
 ┌──────────────── launcher: pythonw.exe ignis_native.py run (your rights, not sandboxed) ──────────┐
 │  relay: allowlist per service ── 127.0.0.1:<port> ──> Augmented View server                      │
 │                               ── LaTeX build ──> AppContainer "ignis-control.latex" (no network) │
 │  status.json every 2 s, ignis.log, vault access repair                                           │
 └──────────────────────────────────────────────────────────────────────────────────────────────────┘
          ▲ reads status.json and ignis.log; starts and stops the launcher
 desktop Obsidian + Ignis Control plugin

 desktop Obsidian, sync tools ──write──> <vault> <──read/write── Ignis server (same files, Windows change events)
```

## Why native and not Docker

Ignis is distributed as a Docker image. A Linux container under WSL is not told about changes Windows programs make
to a Windows folder, so edits from desktop Obsidian would not reach Ignis. Running Ignis natively, Windows reports
every file change to Ignis directly (chokidar on `ReadDirectoryChangesW`), and the vault is read at full disk speed.

## Processes

The launcher, `ignis_native.py run`, starts and supervises everything. It holds the mutex
`Local\ignis-control-ignis-native`, so only one launcher runs at a time.

The names on this page (`ignis-control.ignis`, `ignis-control.latex`, the pipes and the mutex) are the defaults. All of
them start with the prefix `IGNIS_CONTAINER_PREFIX` (default `ignis-control`;
[configuration.md](configuration.md#names-in-windows)).

**Programs the launcher starts outside the sandbox.** Each is started with an argument list (no shell parses a
command line) and, for Windows' own tools, by its full path in `%SystemRoot%\System32`: `icacls.exe` (`setup` and
the LaTeX build's grants), `subst.exe` and `tasklist.exe` (the LaTeX build), Windows PowerShell (only `exempt`,
`unexempt` and `install-startup`, each a fixed command whose values arrive as environment variables), biber (the
LaTeX build) and the optional access watcher.

| Process | Name in status | Runs as | Command |
| --- | --- | --- | --- |
| Launcher | `launcher` | You | `pythonw.exe <root>\ignis\ignis_native.py run` |
| Ignis server | `ignis` | AppContainer `ignis-control.ignis` | `runtime\node.exe app\apps\ignis-server\server\index.js` |
| cloudflared | `cloudflared` | AppContainer `ignis-control.ignis` | `runtime\cloudflared.exe tunnel --no-autoupdate --protocol quic --edge-ip-version 4 run` |
| Augmented View forwarder | `augmented-view` | AppContainer `ignis-control.ignis` | `runtime\node.exe relay\augmented-view-forwarder.js 18790 \\.\pipe\ignis-control-ignis-augmented-view` |
| Access watcher (optional) | none (shown under **Vault access**) | You | `ignis-launcher.exe access watch --vault <vault> --sid <SID> --exit-with-stdin` |
| LaTeX build steps (on request) | none | AppContainer `ignis-control.latex` (biber: you) | See [Plugin-Integration/LaTeX.md](Plugin-Integration/LaTeX.md) |

cloudflared starts only when a tunnel token is stored.

**Supervision.** Each sandboxed process runs in a thread of the launcher, which copies its output to `ignis.log` and
restarts it when it exits. The wait before a restart starts at 2 s and doubles on each quick exit, up to 300 s. It
returns to 2 s after a run longer than 60 s. A process that fails to start is retried the same way.

**Kill on close.** All sandboxed processes belong to one Windows job object with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`.
When the launcher ends, for any reason, Windows ends every process in the job.

**Handles.** A sandboxed process inherits exactly two handles: the write end of its output pipe and `NUL` (as
standard input). It inherits nothing else the launcher holds.

## The AppContainer

An [AppContainer](https://learn.microsoft.com/en-us/windows/win32/secauthz/appcontainer-isolation) process can open
only objects whose access list grants its container SID (derived from the name `ignis-control.ignis`). Windows checks
both your rights and the container's. A second user account would not give this: it can read everything the groups
"Users" and "Authenticated Users" can, which includes other drives and folders created directly under `C:\`.

### Rights of `ignis-control.ignis`

`setup` writes these rules with `icacls`.

| Right | `icacls` | Path | Inherited by contents |
| --- | --- | --- | --- |
| Read and execute | `RX` | `ignis\app`, `ignis\runtime`, `ignis\obsidian-app`, `ignis\vaults`, `ignis\relay` | Yes |
| Modify | `M` | `ignis\data`, `<vault>` | Yes |
| Read attributes | `RA` | Every folder above `ignis\app` and above `<vault>`, from `C:\` down | No (that folder only) |
| Network | capability `internetClient` (`S-1-15-3-1`) | Outbound connections | — |

The read-attributes rule lets Node resolve a path: it reads each folder's attributes on the way down to a file. It
does not allow listing a folder or reading its contents.

Everything else is denied: the rest of your profile, the rest of `<root>`, and other drives. Windows' own folders and
`Program Files` stay readable to every AppContainer through the group `ALL APPLICATION PACKAGES`.

### Network

- **Nothing outside the container can connect in.** Windows drops connections into an AppContainer, including from
  the same PC. cloudflared therefore runs in the same container, where loopback between its processes works.
- **The container cannot reach the PC's own services.** It has no loopback exemption.
- **Ignis listens on `127.0.0.1` only** (`HOST`, patch 0002).
- **Outbound connections work** (`internetClient`): cloudflared to Cloudflare, and plugin requests through Ignis's
  proxy.

The launcher has two administrator commands, `exempt` and `unexempt`, that add and remove a loopback exemption and a
firewall rule for the container. They are not part of the installation. An exemption lets the container reach every
service on the PC's loopback, so it is not used.

### Rights of `ignis-control.latex`

| Right | Path |
| --- | --- |
| Read and execute | TinyTeX (`IGNIS_TINYTEX`, default `%APPDATA%\TinyTeX`) |
| Modify | `<vault>\LaTeX\compiled` |
| Network | none (no capabilities) |

The rules are granted at the start of each build. Details: [Plugin-Integration/LaTeX.md](Plugin-Integration/LaTeX.md).

## The vault's access rule

Files created in the vault inherit the container's rule from the vault folder. A file **moved** into the vault keeps
the access list it had, and Ignis cannot open it (`EPERM`). The launcher repairs such entries: it replaces the entry's
access list with an empty, unprotected one, which Windows fills with the inherited rules (what
`icacls <file> /reset` does).

| Mode | When | How |
| --- | --- | --- |
| Access watcher | `IGNIS_LAUNCHER_EXE` (or its default path) exists | One full scan, then each entry as Windows reports it created, moved in, renamed, or its access list changed |
| Scan | No watcher, or the watcher failed 5 times in a row (each run under 60 s) | Full scan at start and every 300 s |
| By hand | `ignis_native.py repair` | One scan and repair, with a line per entry |

Links (symbolic links and junctions) are never followed, entered or changed. The repair opens each entry without
following links (`FILE_FLAG_OPEN_REPARSE_POINT`) and refuses it if it is a link, so an entry swapped for a link
between the scan and the repair cannot redirect the change outside the vault.

## The named pipes

The launcher serves two named pipes. Both have the same security descriptor:

```
D:P(A;;GA;;;SY)(A;;GA;;;OW)(A;;GRGW;;;<ignis-control.ignis SID>)S:(ML;;NW;;;LW)
```

| Part | Meaning |
| --- | --- |
| `D:P` | Protected access list: no inherited rules |
| `(A;;GA;;;SY)`, `(A;;GA;;;OW)` | SYSTEM and the owner (you): full access |
| `(A;;GRGW;;;<SID>)` | The `ignis-control.ignis` container: read and write |
| `S:(ML;;NW;;;LW)` | Low integrity label. The container runs at low integrity; without this label Windows' no-write-up rule refuses its writes |

Each pipe is created with `PIPE_REJECT_REMOTE_CLIENTS`. Named pipes are not subject to the AppContainer's network
isolation, which is why they work where loopback does not.

| Pipe | Client | Routes |
| --- | --- | --- |
| `\\.\pipe\ignis-control-ignis-relay` | The Ignis server (patch 0006) | `/<service>/<path>` for `augmented-view` and `latex` |
| `\\.\pipe\ignis-control-ignis-augmented-view` | The forwarder | Augmented View's own paths |

One request per pipe connection. The launcher reads the request head, decides, forwards or refuses, streams the
answer back, and closes. Rules: [relay.md](relay.md).

## The status file

`<root>\ignis\status.json`, written every 2 s. The launcher writes `status.tmp` first and renames it, so a reader
never sees half a file.

| Field | Contents |
| --- | --- |
| `updated` | Time written (Unix seconds) |
| `launcher` | `pid`, `started`, `memory_mb` |
| `processes` | Per process (`ignis`, `cloudflared`, `augmented-view`): `state` (`starting`, `running`, `restarting`, `failed to start`), `pid`, `started`, `restarts`, `last_exit`, `last_exit_at`, `last_line`, and while running `cpu_percent` and `memory_mb` |
| `tunnel` | `connections` (count), `edges` (Cloudflare locations), from cloudflared's `Registered tunnel connection` and `Connection terminated` lines |
| `relay` | `passed`, `refused`, `unavailable` (counts for both pipes), `last`, `last_at` |
| `access` | `checked_at`, `entries`, `lacking`, `repaired_total`, `repaired_last` (first 20), `errors` |
| `url` | `https://<IGNIS_HOSTNAME>`, or empty |
| `settings` | The contents of `ignis\data\server-settings.json` |
| `log` | The log's path |
| `container` | The AppContainer's name, `<prefix>.ignis` (default `ignis-control.ignis`) |

The plugin treats the launcher as not running when `status.json` is missing, older than 10 s, or names a launcher
`pid` that no longer exists.

### The status bar dot

| Dot | Level | Condition |
| --- | --- | --- |
| `○` hollow | off | The launcher is not running |
| `●` red | bad | The `ignis` process is not `running` |
| `●` amber | warn | No `cloudflared` process (no token stored), `cloudflared` not `running`, or 0 tunnel connections |
| `●` green | ok | Ignis running and at least one tunnel connection |

Inside Ignis the dot is always green: the page came through the tunnel.

## The log

`<root>\ignis\ignis.log`, UTF-8, one line per event, each starting `YYYY-MM-DD HH:MM:SS`.

| Line | Source |
| --- | --- |
| `started <name> in AppContainer ignis-control.ignis (pid <n>)`, `<name> exited with code <n>`, `<name> could not be started: …` | Supervision |
| `  [ignis] …`, `  [cloudflared] …`, `  [augmented-view] …` | The process's own output |
| `  [ignis] GET 500 /api/fs/readFile?… -- EPERM: …` | Failed request with reason (patch 0003) |
| `  [ignis] client <session> …` | Browser tab reports (patch 0003) |
| `relay: refused <method> <path>: <why>` | Relay refusal |
| `relay: latex refused (<why>)` | LaTeX request without a valid token |
| `latex build for <address>: ok in <n> s` or `failed in <n> s` | LaTeX build result |
| `access: …` | Vault access repair |

At each start, a log longer than 10,000 lines is cut to its last 5,000. The plugin's **Log** pane follows it
([below](#the-log-pane)).

## The plugin

The plugin never connects to the sandbox. In desktop Obsidian it reads `status.json` and the end of `ignis.log`,
writes `server-settings.json`, and starts and stops the launcher with Node's `child_process`. Inside Ignis it has no
Node: it reads and writes Ignis's `/api/settings` and two files in the vault's `.obsidian` folder. A browser tab cannot
start a program on the PC.

| Mode | Sections |
| --- | --- |
| Desktop Obsidian on Windows | Status, Log, Controls, Server, Plugin exclusions, Browser tabs, This panel, Resources, Guide |
| Inside Ignis | This tab, Server, Plugin exclusions, Browser tabs, Guide |
| Desktop Obsidian on another system | A note that the plugin controls Windows features only |

### The log pane

**Settings → Ignis Control → Log**, in desktop Obsidian on Windows.

| Part | What it does |
| --- | --- |
| Source | Everything in `ignis.log`, or only the lines of one part: the launcher, Ignis server (`[ignis]`), the browser tabs' reports (`[ignis] client …`), cloudflared (`[cloudflared]`), the relay (`relay:` and `[augmented-view]`), vault access repair (`access:`), LaTeX builds (`latex build …`, `relay: latex …`); or the last LaTeX build's transcript, `<vault>\LaTeX\compiled\.ignis-build.log` |
| Filter | Shows only the lines containing the text typed (any case) |
| Follow new lines | Keeps the newest line in view |
| Wrap lines | On: long lines wrap. Off: each line stays whole and the pane scrolls sideways |
| Copy | Writes the lines shown to the clipboard (on selection only) |
| Height | Drag the pane's lower edge |

- `ignis.log` is found in the Ignis folder (from `location.json` or **This panel → Ignis folder**); nothing is
  hard-coded.
- The pane reads only while the settings tab is open: the last 256 KB at first, then what is added, once a second,
  with Node's `fs`. A file that shrank or was replaced (log trimming at the launcher's start, a new build transcript)
  is read again from its start; a burst of more than 1 MB is skipped to its last 1 MB, and the pane says so.
- At most 2,000 lines are kept per source, and shown.
- Before a line is kept, the pane hides JSON Web Tokens (the tunnel token, Access tokens), cookie and authorization
  header values, `token=`/`secret=`/`password=`/`aud=`-style values, Cloudflare team names
  (`<team>.cloudflareaccess.com`), hex strings of 32 or more digits (AUD tags), other long key-like strings, e-mail
  addresses and the site's hostname. Lines are coloured by level (cloudflared's own `WRN`/`ERR`, otherwise words such as
  `failed` or `exited with code 1`).
- Source, follow and wrap are kept per device in Obsidian's local storage.
