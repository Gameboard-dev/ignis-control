# Troubleshooting

Start with the plugin's panel (**Settings → Ignis Control → Status**): the dot, each process's state and last exit,
and the **Log** pane (choose a source: the launcher, Ignis, the browser tabs, cloudflared, the relay, vault access,
LaTeX). The full log is `<root>\ignis\ignis.log`. Cloudflare-side problems are also covered in
[cloudflare.md](cloudflare.md#12-when-something-is-wrong).

## The launcher and the status

| Symptom | Cause | Fix |
| --- | --- | --- |
| Hollow dot `○`, "not running" | The launcher is not running, or `status.json` is older than 10 s | Select **Start**. If it does not start, run `python <root>\ignis\ignis_native.py run` in a terminal and read the error |
| **Start** says "the Ignis folder is not known on this device" | No `location.json` yet and no **Ignis folder** set | Run the launcher once by hand, or set **This panel → Ignis folder** |
| **Start** says "no python.exe set on this device" | **Python** is empty, not absolute, not `python.exe`/`pythonw.exe`, or missing | Set **This panel → Python** to the full path of `python.exe` |
| `run` prints `Ignis is already running` | Another launcher holds the mutex `Local\ignis-control-ignis-native` | End the other `pythonw.exe … ignis_native.py run` process, or use it |
| The launcher stops with `IGNIS_CONTAINER_PREFIX=… is not a valid name` | The prefix has a character other than letters, digits, `.` and `-`, or is longer than 40 | Fix it in `.env` ([configuration.md](configuration.md#names-in-windows)) |
| After an upgrade from 0.3.x: amber dot "no token stored", or `EPERM` everywhere | The new launcher uses the default prefix, so a new sandbox without grants or token | Set `IGNIS_CONTAINER_PREFIX` to the old prefix ([installation.md](installation.md#from-version-03)), or run `setup` and `set-token` |
| The launcher exits at once with a `FileNotFoundError` for `.obsidian-version` | `obsidian-app\.obsidian-version` is missing | Write it ([installation.md](installation.md#4-the-obsidian-app-files)) |
| Red dot, `ignis` in `restarting` or `failed to start` | Ignis exits at start | Read the `[ignis]` lines before `ignis exited with code`. Common causes: `app\` not built (`npm run build`), missing grants (`setup`, then `check`) |
| Amber dot, "running, no tunnel (no token stored)" | No token in Credential Manager | `python <root>\ignis\ignis_native.py set-token`, then restart |
| Amber dot, "tunnel connecting" for more than a minute | cloudflared cannot reach Cloudflare | See [The tunnel](#the-tunnel) |

## The tunnel

| Symptom | Cause | Fix |
| --- | --- | --- |
| No `Registered tunnel connection` lines in the log | UDP 7844 outbound blocked; `cloudflared.exe` missing from `ignis\runtime`; wrong token | Allow UDP 7844 outbound over IPv4; check the file; run `set-token` again |
| cloudflared's start-up connectivity pre-check reports QUIC and TCP as failing | The pre-check does not work inside the sandbox | Ignore it when `Registered tunnel connection … protocol=quic` lines follow |
| A certificate error in `[ignis]` lines (plugin requests through Ignis's proxy) | An antivirus re-signs HTTPS and Node does not trust its certificate | Export the certificate to `<root>\ignis\runtime\extra-ca.pem` and restart ([installation.md](installation.md#https-scanning-antivirus)) |
| Frequent reconnects: many `Retrying connection`, `Connection terminated` and `Failed to dial a quic connection … timeout: no recent network activity` lines | QUIC (UDP) is dropped or disturbed on the way to Cloudflare. If the same minutes also show `Failed to refresh DNS local resolver … i/o timeout` or `unreachable host`, the PC's network itself was down (sleep, Wi-Fi, a VPN reconnecting), and no protocol helps | Try `IGNIS_TUNNEL_PROTOCOL=http2` in `.env` and restart the launcher; the log should then show `Registered tunnel connection … protocol=http2`. Behind HTTPS-scanning antivirus, first exclude `cloudflared.exe` (or `*.argotunnel.com`) from the scanning, or the tunnel will not connect at all over HTTP/2; `auto` lets cloudflared fall back to HTTP/2 only when QUIC fails |
| With `http2`, no `Registered tunnel connection` and certificate errors (`x509`, `certificate signed by unknown authority`) in `[cloudflared]` lines | Antivirus re-signs the TLS connection to Cloudflare's edge | Exclude `cloudflared.exe` from the antivirus's HTTPS scanning, or go back to `quic` (remove the line and restart) |
| `Failed to refresh DNS local resolver … i/o timeout` now and then | cloudflared re-resolves its edge address periodically and the DNS query timed out | Harmless on its own: the established connections are kept. Many of them together mean the network was unavailable |
| The tunnel drops while a VPN or the Cloudflare One Client runs | They can block the tunnel or show a Gateway block page | Try with them off |

## The site

| Symptom | Cause | Fix |
| --- | --- | --- |
| Ignis opens without the Access login page | The Access application does not cover the hostname | Stop the launcher at once. Fix the application's public hostname ([cloudflare.md](cloudflare.md#6-the-access-application)) |
| 502 or "Bad gateway" | The route's service URL is not `http://127.0.0.1:8080`, or Ignis is not running | Fix the route; check the `ignis` process |
| The page loads but stays "connecting" | `IGNIS_HOSTNAME` is not exactly the public hostname, so the WebSocket origin is refused | Fix `.env` and restart the launcher |
| **Public address → Check** is not healthy | The tunnel or the route is down | A healthy answer is HTTP 200 to 399 (the Access login page) |
| An insecure-connection warning, saving problems, an empty vault list | Ignis's own browser-side issues | [Ignis troubleshooting](https://ignis.thiefling.com/docs/troubleshooting/) |

## Files Ignis cannot open

| Symptom | Cause | Fix |
| --- | --- | --- |
| `GET 500 /api/fs/readFile?… -- EPERM: operation not permitted` in the log; notes that never index; a slow tab | Files moved into the vault kept their old access list | The launcher repairs them within 300 s (or at once with the access watcher). By hand: `python <root>\ignis\ignis_native.py repair` |
| Most of the vault unreadable at once (for example, a vault restored from the Recycle Bin) | Every restored file kept its old access list | `icacls <vault>\* /reset /T` in a terminal, then `check` |
| `EPERM` for a file outside the vault | A grant is missing | `setup` again, run its administrator commands, then `check` |
| `check` prints `FAIL` for a probe expected `denied` | A folder is readable to the container | Remove the rule or the group that grants it, then `check` |
| **Vault access** in the panel shows files Ignis cannot open | The repair failed for them | Read the `access:` lines in the log for the paths |

## Plugins in the browser

| Symptom | Cause | Fix |
| --- | --- | --- |
| A plugin should not run in Ignis | Two-way sync plugins, plugins that need desktop features | Add it under **Plugin exclusions**. It applies when a tab next loads |
| An excluded plugin still runs in an open tab | The list is read when a tab loads | Reload the tab |
| A plugin switched on in Ignis is not on in desktop Obsidian | Desktop Obsidian reads `community-plugins.json` only at start | Restart desktop Obsidian |
| A plugin fails in Ignis | It needs desktop-only features (a program, a socket, a native module) | [Plugin compatibility](https://ignis.thiefling.com/docs/using/plugin-compatibility/), [issue #9](https://github.com/Nystik-gh/ignis/issues/9) |

### Reading the tab reports

With **Browser tabs → Diagnostics** on, each tab reports to `ignis.log` as `client <session>` (patch 0003):

| Report | Contents |
| --- | --- |
| `new page on …` | The device: system, browser, memory, screen size |
| `ERROR uncaught [plugin <id>]: …` | An error, with the plugin whose code was on the stack. No plugin named means Obsidian or Ignis |
| `plugin` | Each plugin's load time, or why it failed |
| `boot` | When the app object, the layout and the metadata index were ready |
| `stall` | The page frozen for over 300 ms, and the plugins whose scripts ran |
| `memory` | JS heap: every 15 s for the first 2 minutes, then every minute, and at once above 60 % of the limit |
| `crash` | Reported by the next page on the same device: the previous page ended without closing |

To follow one tab: `Select-String 'client <session>' <root>\ignis\ignis.log`.

## The relay

| Symptom | Cause | Fix |
| --- | --- | --- |
| 403 `the relay serves only this page` | The request came from another site | Requests must come from the Ignis page itself |
| 403 `… is not relayed` | The request is not on the service's allowlist | Expected for refused requests ([relay.md](relay.md#services)) |
| 502 `nothing answers on port …` | The service is not running on the PC | Start it in desktop Obsidian |
| 502 `the relay is not running` | The launcher is not serving the pipe | Restart the launcher |
| 503 `the relay is off` | Ignis was started without `IGNIS_LOCAL_RELAY` | Start Ignis through the launcher, not by hand |

LaTeX build failures: [Plugin-Integration/LaTeX.md](Plugin-Integration/LaTeX.md#status-logs-and-failures).
