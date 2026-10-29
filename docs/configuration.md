# Configuration

Every setting Ignis Control reads, where it is kept, its default, and when a change takes effect.

## Contents

1. [The `.env` file](#the-env-file)
2. [Environment variables](#environment-variables)
3. [What the launcher passes to Ignis](#what-the-launcher-passes-to-ignis)
4. [What the launcher passes to cloudflared](#what-the-launcher-passes-to-cloudflared)
5. [Server settings](#server-settings)
6. [Plugin settings](#plugin-settings)
7. [Files in the vault](#files-in-the-vault)
8. [Ports of the relayed services](#ports-of-the-relayed-services)
9. [Fixed values](#fixed-values)
10. [Names in Windows](#names-in-windows)

## The `.env` file

The launcher reads `<root>\ignis\.env`.

- One `KEY=value` per line. Lines starting with `#` are ignored. Spaces around the key and the value are removed.
  The value may be wrapped in one pair of matching quotes (`KEY="value"` or `KEY='value'`); they are removed.
- Every launcher setting below (and under [Environment variables](#environment-variables)) is read from the
  launcher's environment first, then from this file. None is ever read from the vault.
- Save it as UTF-8 without a byte-order mark (Notepad's default "UTF-8").
- It is git-ignored. Never commit it.

| Key | Value | Default | Read | Used for |
| --- | --- | --- | --- | --- |
| `IGNIS_HOSTNAME` | The public hostname, without `https://`, for example `vault.example.com` | none | At launcher start (`WS_ORIGINS`); every 2 s (the `url` in `status.json`) | WebSocket origin allowlist; the plugin's **Site** button and public-address check |
| `IGNIS_ACCESS_TEAM` | The Zero Trust team name (`<team>`) or team domain (`<team>.cloudflareaccess.com`). A bare name gets `.cloudflareaccess.com` added; a leading `https://` and a trailing `/` are removed | none | At every `/relay/latex/` request | LaTeX build: token issuer and signing keys |
| `IGNIS_ACCESS_AUD` | The Access application's AUD tag | none | At every `/relay/latex/` request | LaTeX build: token audience |
| `IGNIS_ACCESS_EMAILS` | Addresses allowed to build, comma-separated. Compared in lower case | none | At every `/relay/latex/` request | LaTeX build: who may build |

Rules:

- `IGNIS_HOSTNAME=vault.example.com`, the literal placeholder, is treated as unset.
- Restart the launcher after changing `IGNIS_HOSTNAME`. The three `IGNIS_ACCESS_*` keys need no restart.
- `IGNIS_ACCESS_TEAM` is either the team name alone (letters, digits and `-`) or that name followed by
  `.cloudflareaccess.com`; anything else is invalid. If any of the three `IGNIS_ACCESS_*` keys is missing or invalid,
  every `/relay/latex/` request is refused with 403.
- A `TUNNEL_TOKEN` line is ignored, and the launcher writes a line to the log saying so. The token belongs in
  Credential Manager ([security.md](security.md#the-tunnel-token)).

Example:

```
IGNIS_VAULT=C:\Users\<you>\Documents\<vault>
IGNIS_HOSTNAME=vault.example.com
IGNIS_ACCESS_TEAM=<team>
IGNIS_ACCESS_AUD=<AUD tag>
IGNIS_ACCESS_EMAILS=you@example.com
```

Where each value comes from: [cloudflare.md](cloudflare.md#9-the-env-values).

## Environment variables

Read by the launcher from its own environment, else from a `NAME=value` line in `ignis\.env` (the environment wins).
A line in `.env` is the simplest; for a **user** environment variable, which the logon shortcut also sees:

```powershell
[Environment]::SetEnvironmentVariable('<NAME>', '<value>', 'User')
```

| Variable | Default | What it does |
| --- | --- | --- |
| `IGNIS_VAULT` | `<root>\vault` | The vault's folder. A symbolic link is resolved to its target. Read at launcher start. If the folder does not exist, `setup`, `check`, `repair` and `run` stop with an error naming `IGNIS_VAULT` |
| `IGNIS_AUGMENTED_VIEW_PORT` | `8790` | The port of Augmented View's server on this PC (the server's `--port`; the plugin's **Port** setting on desktop). Set it only if you changed that setting. Read at every relay request |
| `IGNIS_IGNORED_PATHS` | `/LaTeX/compiled/*,!/LaTeX/compiled/main.pdf,!/LaTeX/compiled/main.shown.pdf,!/LaTeX/compiled/main.synctex.gz,!/LaTeX/compiled/latex-status.json` | Paths Ignis does not watch, as gitignore patterns, comma-separated. Replaces the default; it is not added to it. Passed to Ignis as `IGNORED_PATHS`. Ignored files are still listed in the file tree each tab downloads, but with the size and time they had when Ignis listed the vault: a browser never learns that they changed. So the LaTeX build folder's contents are ignored except the four files a browser needs (the PDF, the copy the LaTeX plugin's pane shows, the SyncTeX file, and the plugin's `latex-status.json`); ignoring the whole folder left the old PDF on screen, even after a reload. Add folders that change constantly and that no browser needs, such as a sync plugin's cache, after the default. Read at launcher start |
| `IGNIS_CONTAINER_PREFIX` | `ignis-control` | The prefix of every name the installation uses in Windows ([Names in Windows](#names-in-windows)). Letters, digits, `.` and `-`, at most 40 characters; anything else stops the launcher with the reason. Changing it on an installation means a new sandbox: run `setup` and `set-token` again |
| `IGNIS_EXTRA_CA_CERT` | `<root>\ignis\runtime\extra-ca.pem` | An extra root certificate (PEM) for Ignis's Node, passed as `NODE_EXTRA_CA_CERTS` when the file exists ([installation.md](installation.md#https-scanning-antivirus)). The sandbox must be able to read it, so keep it in `runtime\` |
| `IGNIS_LAUNCHER_EXE` | `<root>\ignis\ignis-launcher.exe` | The Rust access watcher. If the file does not exist, the launcher scans the vault every 300 s instead |
| `IGNIS_TUNNEL_PROTOCOL` | `quic` | cloudflared's transport to Cloudflare's edge, passed as `--protocol`: `quic` (UDP 7844), `http2` (TLS over TCP 7844, for networks that block or disturb UDP) or `auto` (cloudflared's own choice: QUIC, falling back to HTTP/2). Anything else stops the launcher with the reason in `ignis.log`. `http2` fails behind antivirus that re-signs TLS unless `cloudflared.exe` or `*.argotunnel.com` is excluded from its HTTPS scanning ([troubleshooting.md](troubleshooting.md#the-tunnel)). Read at launcher start |
| `IGNIS_TINYTEX` | `%APPDATA%\TinyTeX` | The TinyTeX folder for the LaTeX build (its programs are in `bin\windows\`) |
| `APPDATA` | set by Windows | The default TinyTeX folder; the logon shortcut goes to `%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup` |
| `LOCALAPPDATA` | set by Windows | `location.json` is written to `%LOCALAPPDATA%\Ignis Control\` |
| `SystemRoot` | set by Windows | Windows' own programs (`icacls.exe`, `subst.exe`, `tasklist.exe`, Windows PowerShell) are run from `%SystemRoot%\System32` by full path |

Set `IGNIS_VAULT` explicitly unless your vault is `<root>\vault`.

## What the launcher passes to Ignis

The Ignis server (`node.exe apps\ignis-server\server\index.js`) gets only this environment. Ignis's own variables are
documented at [ignis.thiefling.com/docs/server/environment](https://ignis.thiefling.com/docs/server/environment/).

| Variable | Value | Purpose |
| --- | --- | --- |
| `PORT` | `8080` | Listening port |
| `HOST` | `127.0.0.1` | Listening address (patch 0002) |
| `VAULT_ROOT` | `<root>\ignis\vaults` | Folder of vault junctions |
| `DATA_ROOT` | `<root>\ignis\data` | Ignis's state |
| `OBSIDIAN_ASSETS_PATH` | `<root>\ignis\obsidian-app` | Obsidian's app files |
| `IGNIS_OBSIDIAN_PIN` | Contents of `obsidian-app\.obsidian-version` | Obsidian version served |
| `IGNORED_PATHS` | `IGNIS_IGNORED_PATHS` or its default | Paths not watched |
| `PROXY_ALLOW_PRIVATE_HOSTS` | `127.0.0.1` | Lets Ignis's proxy reach `127.0.0.1` inside the container (the Augmented View forwarder) |
| `WS_ORIGINS` | `https://<IGNIS_HOSTNAME>,http://localhost:8080` | WebSocket origin allowlist; also the relay's allowed origins |
| `LOG_REQUESTS` | `errors` | Log only failed, partial and slow (2,000 ms or more) requests (patch 0003) |
| `NO_COLOR` | `1` | No colour codes in the log (patch 0003) |
| `IGNIS_LOCAL_RELAY` | `\\.\pipe\ignis-control-ignis-relay` | The relay's named pipe (patch 0006) |
| `NODE_EXTRA_CA_CERTS` | `IGNIS_EXTRA_CA_CERT`, default `<root>\ignis\runtime\extra-ca.pem` | Only when that file exists |
| `NODE_ENV` | `production` | |
| `SystemRoot` | The launcher's `SystemRoot`, or `C:\Windows` | |
| `PATH` | `<root>\ignis\runtime` | |
| `TEMP`, `TMP` | `<container folder>\Temp` | |
| `USERPROFILE`, `LOCALAPPDATA`, `APPDATA` | `<container folder>` | |

`<container folder>` is `%LOCALAPPDATA%\Packages\ignis-control.ignis\AC`, the one profile folder the container may write.

## What the launcher passes to cloudflared

- Command: `<root>\ignis\runtime\cloudflared.exe tunnel --no-autoupdate --protocol <protocol> --edge-ip-version 4 run`,
  where `<protocol>` is `IGNIS_TUNNEL_PROTOCOL` (default `quic`); the log says `cloudflared: protocol <protocol>` at start,
  working folder `<root>\ignis\runtime`.
- Environment: the same as Ignis, plus `TUNNEL_TOKEN` read from Credential Manager.
- cloudflared is started only when a token is stored. Otherwise the log says
  `no tunnel token in Credential Manager (ignis-control.ignis/cloudflared-tunnel-token): the tunnel is not started`.

## Server settings

Ignis's own settings, stored in `<root>\ignis\data\server-settings.json`. The plugin shows them as sliders.

| Key | Panel name | Unit | Slider range | Step | Default | Meaning |
| --- | --- | --- | --- | --- | --- | --- |
| `contentCacheBytes` | Content cache | MB | 25–500 | 25 | 50 | Note contents kept in each tab's memory |
| `persistentCacheBytes` | Kept plugin and settings files | MB | 0–500 | 25 | 100 | `.obsidian` files each browser keeps between visits; 0 keeps none (patch 0004; the server accepts up to 2,048 MB) |
| `inputCacheBytes` | Input cache | MB | 50–1000 | 50 | 200 | Files picked in file dialogs, kept for the plugin to read |
| `writeCoalesceMs` | Write coalesce window | ms | 0–5000 | 100 | 0 | Groups rapid saves into one write |
| `maxBodyBytes` | Maximum request size | MB | 10–500 | 10 | 50 | Largest upload or save the server accepts |

How a change takes effect:

| Where | How it is saved | When it applies |
| --- | --- | --- |
| Desktop Obsidian | The plugin writes `server-settings.json`, then **Apply and restart** restarts the launcher | After the restart |
| Inside Ignis | The plugin sends `POST /api/settings`; the server validates and saves | At once; cache sizes when a tab next loads |

Meanings and other keys: [Ignis settings](https://ignis.thiefling.com/docs/using/settings/).

## Plugin settings

| Setting | Stored in | Default | Meaning |
| --- | --- | --- | --- |
| Refresh interval | The vault's `data.json` (`refreshSeconds`) | 2 s (range 1–30) | How often the dot and the panel re-read `status.json` |
| Ignis folder | This device only: Obsidian local storage `ignis-control-ignisDir` | `ignis_dir` from `location.json` | The installation's `ignis\` folder |
| Python | This device only: `ignis-control-python` | `python` from `location.json` | Absolute path to `python.exe` or `pythonw.exe` with `pywin32` and `psutil` |
| Launcher script | This device only: `ignis-control-launcher` | `<Ignis folder>\ignis_native.py` | Set only if the launcher is elsewhere |
| Log: source | This device only: `ignis-control-log-source` | Everything (`ignis.log`) | Which log, or which part of `ignis.log`, the **Log** pane shows |
| Log: Follow new lines | This device only: `ignis-control-log-follow` | On | Keep the newest line in view |
| Log: Wrap lines | This device only: `ignis-control-log-wrap` | On | Off: whole lines and a horizontal scrollbar |

The three device settings are never stored in the vault's `data.json`. The vault is shared with every device and with
the browser, and a path in it could choose the program desktop Obsidian runs.

## Files in the vault

| File | Format | Written by | Read by | Effect |
| --- | --- | --- | --- | --- |
| `.obsidian/ignis-disabled-plugins.json` | JSON array of plugin ids | **Plugin exclusions** in the panel | Each Ignis tab when it loads (patch 0001) | These plugins stay off in Ignis and keep running on desktop |
| `.obsidian/ignis-diagnostics.json` | `{"enabled": true}` or `{"enabled": false}` | **Browser tabs → Diagnostics** | Each Ignis tab when it loads (patch 0003) | Tab reports to `ignis.log`. No file means on |
| `.obsidian/workspace-ignis.json` | Obsidian workspace | Ignis (patch 0001) | Ignis | Ignis's layout, separate from desktop's `workspace.json`. Not used when the URL has `?workspace=` |

## Ports of the relayed services

The relay finds each desktop service's port at every request, never from the vault (the browser can write every file
in it, including the plugins' `data.json`).

| Service | Source | Key | Default |
| --- | --- | --- | --- |
| `augmented-view` | The launcher's environment, else `<root>\ignis\.env` | `IGNIS_AUGMENTED_VIEW_PORT` | 8790 |

A port outside 1024–65535, or equal to 8080 or 18790, is replaced by the default. A port that is also another known
service's (another relayed service, 8080 or 18790) is refused: the relay answers 403 and logs why. If you change Augmented View's **Port** on desktop, set `IGNIS_AUGMENTED_VIEW_PORT` to the same value.

## Fixed values

Constants in `ignis_native.py` and `main.js`. They have no setting.

| Value | Where | Meaning |
| --- | --- | --- |
| 8080 | Launcher | Ignis's port |
| 18790 | Launcher | The Augmented View forwarder's port inside the container |
| 2 s | Launcher | `status.json` is written every 2 s |
| 10 s | Plugin | A `status.json` older than 10 s means the launcher is not running |
| 2 s doubling to 300 s | Launcher | Restart back-off for a process that keeps exiting. Reset to 2 s after a run of more than 60 s |
| 300 s | Launcher | Vault access scan interval, without the access watcher |
| 5 | Launcher | Access watcher failures in a row before the launcher falls back to scans |
| 10,000 / 5,000 lines | Launcher | At start, a log longer than 10,000 lines is cut to its last 5,000 |
| 5 s | Launcher | Relay connect timeout to a desktop service |
| 600 s | Launcher | LaTeX build limit |
| 3,600 s | Launcher | Cloudflare Access signing keys are cached for an hour |
| 10 s | Plugin | **Restart** waits up to 10 s for the launcher to exit |
| 120 s | Plugin | **Sandbox check** timeout |

## Names in Windows

The installation's names in Windows all begin with one prefix, `IGNIS_CONTAINER_PREFIX` (default `ignis-control`).
The table shows them with the default.

| Name | What it names |
| --- | --- |
| `ignis-control.ignis` | Ignis's AppContainer. Its SID is derived from this name |
| `ignis-control.latex` | The LaTeX build's AppContainer |
| `\\.\pipe\ignis-control-ignis-relay` | The same-origin relay's named pipe |
| `\\.\pipe\ignis-control-ignis-augmented-view` | The Augmented View forwarder's named pipe |
| `ignis-control.ignis/cloudflared-tunnel-token` | The Credential Manager entry (generic credential) for the tunnel token |
| `Local\ignis-control-ignis-native` | The launcher's mutex. A second `run` prints `Ignis is already running` and exits with 1 |

A container's SID is derived from its name, so a different prefix is a different sandbox: its access rules are granted
again by `setup`, and the tunnel token is stored again with `set-token`. An installation set up by an earlier version
under another prefix keeps its sandbox and token by setting `IGNIS_CONTAINER_PREFIX` to that prefix: `status.json`'s
`container` field (written by every version) is `<prefix>.ignis` ([installation.md](installation.md#from-version-03)).

These names do not depend on the prefix:

| Name | What it names |
| --- | --- |
| `%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\Ignis Control.lnk` | The logon shortcut (`install-startup`) |
| `%LOCALAPPDATA%\Ignis Control\location.json` | Where the launcher records the `ignis\` folder and `python.exe` for the plugin |
| `%LOCALAPPDATA%\Packages\<prefix>.ignis\`, `%LOCALAPPDATA%\Packages\<prefix>.latex\` | The containers' profile folders, made by Windows |
