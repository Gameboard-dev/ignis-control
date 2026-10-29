# Ignis Control

Run [Ignis](https://ignis.thiefling.com/docs/) on a Windows PC inside a sandbox, publish it through a Cloudflare
Tunnel behind Cloudflare Access, and control it from Obsidian.

**Windows only. Tested on Windows 11 Pro.**

> **Unofficial.** [Ignis](https://github.com/Nystik-gh/ignis) is a separate project by its own author, Nystik
> ([documentation](https://ignis.thiefling.com/docs/)). Ignis Control is an unofficial companion written by someone
> else: it is not part of Ignis, and it is not affiliated with or endorsed by Ignis's author or by Obsidian. Problems
> with Ignis Control belong in [this repository's issues](https://github.com/Gameboard-dev/ignis-control/issues), not
> Ignis's. Ignis Control is not listed in Obsidian's community plugins; it is installed by hand or with BRAT.

Ignis serves an Obsidian vault as a web page: any browser, on any device, opens the vault in the real Obsidian app with
its plugins. Ignis has no login of its own. Ignis Control runs it on your PC in a Windows sandbox, puts Cloudflare's
login in front of it, and gives you a status bar indicator and a control panel in Obsidian. It is for a person who
keeps a vault on a Windows PC and wants to open it from a phone or another computer without opening a port on the PC.

## Disclosures

Ignis Control is not in Obsidian's community plugins, but it follows what
[Obsidian's developer policies](https://docs.obsidian.md/community-directory/developer-policies) ask listed plugins to
disclose, so you know what you install. In short (the full account is [docs/disclosures.md](docs/disclosures.md)):

- **Desktop only, Windows only.** The plugin starts and stops a separate program on your PC, the launcher
  (`ignis_native.py`, a Python script you install yourself). It runs nothing else, and never downloads or installs
  anything.
- **Network use.** The plugin makes one request of its own, when you press **Check**: to your Ignis site's public
  address, to see whether it answers. Inside Ignis it talks only to the Ignis page it runs in. The launcher, outside
  Obsidian, runs Cloudflare's tunnel connector (`cloudflared`), which carries your vault's pages between Cloudflare and
  your PC.
- **An account is needed:** a Cloudflare account and a domain on Cloudflare, whose free plans are sufficient. Ignis
  Control itself is free and needs no account or payment.
- **Files outside the vault.** The plugin reads the launcher's status file, log and location file, and writes Ignis's
  server settings file, all in the Ignis installation folder or `%LOCALAPPDATA%\Ignis Control\`.
- **No telemetry, no ads.** Nothing about you or your use is collected or sent anywhere.
- **Open source:** MIT; the patches to Ignis are under Ignis's own licence, the AGPL 3.0 or later.

## What it is

| Part | Files | What it does |
| --- | --- | --- |
| Obsidian plugin | `main.js`, `manifest.json`, `styles.css` | Status bar indicator, start, stop and restart, live status and log, Ignis's server options, plugin exclusions and tab diagnostics. Also loads inside Ignis, where it changes the server's options from any device |
| Launcher | `ignis_native.py` (Python) | Runs Ignis and cloudflared in a Windows AppContainer, restarts them when they exit, writes the status file, serves the relay, runs the LaTeX build |
| Forwarder | `relay/augmented-view-forwarder.js` | Runs inside the sandbox and passes Augmented View's requests to the launcher (older route) |
| Access watcher (optional) | `launcher/` (Rust) | Restores the sandbox's access rule on files moved into the vault, as they arrive |
| Patches | `patches/` | Six changes to Ignis 0.8.18 that the launcher and the plugin depend on |

## Features

- **Sandbox.** Ignis and cloudflared run in an AppContainer that can change only the vault and Ignis's data folder,
  and read only Ignis's own folders. `ignis_native.py check` proves it with probes run inside the container.
- **No open ports.** Ignis listens on `127.0.0.1` inside the sandbox; cloudflared connects out to Cloudflare. Nothing
  connects in.
- **Login first.** Cloudflare Access (a one-time PIN sent by e-mail) stands in front of the public address.
- **The tunnel token stays in Credential Manager.** It is never written to a file, a command line or the log.
- **Status and control.** A status bar dot (green, amber, red, hollow), a process table, the live log, start, stop,
  restart, the sandbox check and a check of the public address.
- **From any device.** Inside Ignis, the same panel changes Ignis's server options, the plugins kept off in Ignis,
  and the tab diagnostics.
- **Relay.** Plugins in the browser reach a listed service on the PC through `/relay/<service>/` on the page's own
  address: Augmented View's model server, and the LaTeX build. Each passes only listed requests.
- **Remote LaTeX build.** The [LaTeX](https://github.com/Gameboard-dev/latex) plugin in a browser can ask the PC to
  compile its document in a second sandbox with no network.

## Requirements

| Requirement | Notes |
| --- | --- |
| Windows 11 | AppContainer, Credential Manager and named pipes are Windows features |
| Obsidian 1.8.7 or later, desktop | The plugin |
| Python 3.9 or later, with `pywin32` and `psutil` | Runs the launcher. `pygments` is optional (code listings in the LaTeX build) |
| Node.js and npm, Git | Build Ignis. Its `node.exe` is copied into the installation |
| `cloudflared.exe` | The tunnel connector, from [Cloudflare's releases](https://github.com/cloudflare/cloudflared/releases) |
| The patched Ignis 0.8.18 (`v0.8.18+obsidian.1.14.4`) | From [Gameboard-dev/ignis](https://github.com/Gameboard-dev/ignis), or upstream with `patches/` applied |
| Obsidian 1.14.4 app files | The version that Ignis release is pinned to |
| A Cloudflare account and a domain on Cloudflare | The free plans are sufficient |
| Optional: Rust | Builds the access watcher in `launcher/` |
| Optional: TinyTeX | Only for the remote LaTeX build |

## Install

- **The plugin:** copy `main.js`, `manifest.json` and `styles.css` from a
  [release](https://github.com/Gameboard-dev/ignis-control/releases) into `<vault>\.obsidian\plugins\ignis-control\`,
  or add `Gameboard-dev/ignis-control` in the [BRAT](https://github.com/TfTHacker/obsidian42-brat) plugin, which
  installs and updates plugins from GitHub releases. It is not in Obsidian's community plugins.
- **The launcher:** clone this repository, or download the release's **Source code (zip)**; the launcher and its files
  are plain source. It is installed by hand, once, as [docs/installation.md](docs/installation.md) describes.

## Quick start

1. Install the prerequisites, build the patched Ignis and lay out the installation folder:
   [docs/installation.md](docs/installation.md).
2. Run `python <root>\ignis\ignis_native.py setup` and the administrator commands it prints.
3. Set up the Cloudflare account, domain, Access application and tunnel: [docs/cloudflare.md](docs/cloudflare.md).
4. Store the tunnel token with `python <root>\ignis\ignis_native.py set-token` and write `<root>\ignis\.env`:
   [docs/configuration.md](docs/configuration.md).
5. Install the plugin and enable it in desktop Obsidian.
6. Run `python <root>\ignis\ignis_native.py check`. The last line must read `all as expected`.
7. Select **Start** in the plugin's panel, wait for the green dot, and open `https://vault.example.com`.
8. Optional: `python <root>\ignis\ignis_native.py install-startup` starts the launcher at logon.

## Documentation

| Page | What it covers |
| --- | --- |
| [Installation](docs/installation.md) | Getting the files, prerequisites, folder layout, building Ignis, the plugin, first run, `check`, the logon shortcut, upgrading |
| [Cloudflare](docs/cloudflare.md) | Domain, Zero Trust organisation, one-time PIN, the Access application, the tunnel, DNS, checks, hardening |
| [Configuration](docs/configuration.md) | Every `.env` key, environment variable, server option, plugin setting and name in Windows, with defaults |
| [Architecture](docs/architecture.md) | Processes, the AppContainer and its rights, the named pipes, the status file, the log |
| [Relay](docs/relay.md) | The relay: request path, origin and header rules, the services and their allowed requests |
| [Plugin integration](docs/Plugin-Integration/README.md) | Obsidian plugins that use Ignis Control: LaTeX, Augmented View |
| [Security](docs/security.md) | Threat model, what is protected and how, what is not protected |
| [Troubleshooting](docs/troubleshooting.md) | Symptoms, causes and fixes |
| [Building and testing](docs/building.md) | The plugin (no build step), the access watcher, the tests, the patches |
| [Disclosures](docs/disclosures.md) | What the plugin and the launcher run, connect to and read, under Obsidian's developer policies |
| [Licences](docs/licences.md) | This repository's licences, Ignis's, and the programs it runs |
| [patches/README.md](patches/README.md) | The six Ignis patches and how to apply them |
| [launcher/README.md](launcher/README.md) | The Rust access watcher |

<a name="with-the-latex-plugin-remote-markdown-to-latex-compilation"></a>

## Plugin integrations

| Plugin | What Ignis Control provides | Page |
| --- | --- | --- |
| [LaTeX](https://github.com/Gameboard-dev/latex) | Remote Markdown-to-LaTeX compilation on the PC when the vault is open in a browser | [LaTeX.md](docs/Plugin-Integration/LaTeX.md) |
| [Augmented View](https://github.com/Gameboard-dev/obsidian-augmented-view) | Access to the model server that desktop Obsidian runs | [Augmented-View.md](docs/Plugin-Integration/Augmented-View.md) |

## Which Ignis

Ignis Control requires the patched Ignis 0.8.18, release tag `v0.8.18+obsidian.1.14.4`. The launcher sets `HOST` and
`IGNIS_LOCAL_RELAY`, which only the patched server reads, and the plugin exclusions, tab diagnostics and the **Kept
plugin and settings files** option also come from the patches. Use either the fork
[Gameboard-dev/ignis](https://github.com/Gameboard-dev/ignis) (branch `main`: upstream's history with the six patches
as commits) or upstream [Nystik-gh/ignis](https://github.com/Nystik-gh/ignis) at that tag with the files in
[`patches/`](patches/README.md) applied in order.

## Security in brief

Every request passes Cloudflare Access before it reaches Ignis; Ignis cannot read or change anything on the PC beyond
the vault and its own folders; the relay passes only listed requests; secrets stay on the PC. **Not protected:**
anyone who passes Access can read and change every file in the vault, including plugin code that desktop Obsidian
loads, so admit only yourself. The launcher itself runs with your rights. Details: [docs/security.md](docs/security.md).

## Licence

Ignis is the work of Nystik, under the GNU Affero General Public License 3.0 or later
([Nystik-gh/ignis](https://github.com/Nystik-gh/ignis)). The plugin, the launcher (`ignis_native.py`, `launcher/`) and the forwarder (`relay/`) are under the
[MIT licence](LICENSE). The files in `patches/` modify Ignis and are under the GNU Affero General Public License 3.0
or later, as Ignis is ([patches/LICENSE](patches/LICENSE)). More: [docs/licences.md](docs/licences.md).
