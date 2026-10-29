# Installation

This page installs Ignis Control on a Windows PC: the prerequisites, the installation folder, the patched Ignis, the
plugin, the first run, the sandbox check, the logon shortcut, and upgrades.

The Cloudflare side (domain, Access, tunnel) is in [cloudflare.md](cloudflare.md). Every setting is listed in
[configuration.md](configuration.md).

## Placeholders

| Placeholder | Meaning |
| --- | --- |
| `<root>` | The folder that holds `ignis\`. The launcher is `<root>\ignis\ignis_native.py` |
| `<vault>` | The vault's folder |
| `<vault name>` | The last part of `<vault>` |
| `<repo>` | A clone of this repository, or the release's source archive unpacked ([Getting the files](#getting-the-files)) |
| `vault.example.com` | The public hostname |

## Getting the files

Ignis Control has two parts, obtained separately:

- **The Obsidian plugin** (`main.js`, `manifest.json`, `styles.css`): the assets of each
  [release](https://github.com/Gameboard-dev/ignis-control/releases), copied by hand, or installed with the
  [BRAT](https://github.com/TfTHacker/obsidian42-brat) plugin (`Gameboard-dev/ignis-control`). Ignis Control is not in
  Obsidian's community plugins.
- **The launcher and its files** (`ignis_native.py`, `relay\`, `patches\`, and the optional access watcher's source in
  `launcher\`): a clone of this repository, or the **Source code (zip)** archive attached to the same release, unpacked.
  They are plain source files: there is no installer and no binary to download, and neither the plugin nor the launcher
  downloads anything by itself. Use the launcher from the same release as the plugin.

```powershell
git clone https://github.com/Gameboard-dev/ignis-control.git <repo>
git -C <repo> checkout <version>
```

## Contents

1. [Prerequisites](#1-prerequisites)
2. [The installation folder](#2-the-installation-folder)
3. [Build the patched Ignis](#3-build-the-patched-ignis)
4. [The Obsidian app files](#4-the-obsidian-app-files)
5. [The vault](#5-the-vault)
6. [Create the sandbox](#6-create-the-sandbox)
7. [Cloudflare, the token and `.env`](#7-cloudflare-the-token-and-env)
8. [Install the plugin](#8-install-the-plugin)
9. [First run](#9-first-run)
10. [Check the sandbox](#10-check-the-sandbox)
11. [Start at logon](#11-start-at-logon)
12. [Optional: the access watcher](#12-optional-the-access-watcher)
13. [Upgrading](#13-upgrading)

## 1. Prerequisites

| What | Why | How |
| --- | --- | --- |
| Windows 11 | AppContainer, Credential Manager, named pipes | Tested on Windows 11 Pro |
| Python 3.9 or later | Runs the launcher | [python.org](https://www.python.org/downloads/windows/) |
| `pywin32`, `psutil` | Win32 calls, Credential Manager, the status file | `python -m pip install pywin32 psutil` |
| `pygments` (optional) | Highlights code listings in the LaTeX build. Without it, listings are left unchanged | `python -m pip install pygments` |
| Node.js and npm | Builds Ignis; `node.exe` runs it | [nodejs.org](https://nodejs.org/en/download). Tested with v24.21.0 |
| Git | Clones Ignis | [git-scm.com](https://git-scm.com/download/win) |
| `cloudflared.exe` | The tunnel connector | See [cloudflared](#cloudflared) below |
| TinyTeX (optional) | Only for the remote LaTeX build | See [TinyTeX](#tinytex) below |
| Antivirus root certificate (only with HTTPS scanning) | Lets Ignis's Node trust connections the antivirus re-signs | See [HTTPS-scanning antivirus](#https-scanning-antivirus) below |
| Rust (optional) | Builds the access watcher in `launcher/` | [rustup.rs](https://rustup.rs/) |

### cloudflared

1. Download `cloudflared-windows-amd64.exe` from
   [cloudflared's releases](https://github.com/cloudflare/cloudflared/releases).
2. Save it as `<root>\ignis\runtime\cloudflared.exe`. If you installed the MSI instead, copy `cloudflared.exe` from
   `C:\Program Files (x86)\cloudflared\` to that path.
3. Do not install cloudflared as a Windows service, and do not run the install command the Cloudflare dashboard
   shows. A service runs outside the sandbox. The launcher starts cloudflared itself, inside the sandbox.
4. If a service is already installed, remove it in an administrator terminal:
   `"C:\Program Files (x86)\cloudflared\cloudflared.exe" service uninstall`.

cloudflared does not update itself on Windows. To update it, replace `<root>\ignis\runtime\cloudflared.exe` and
restart the launcher.

The launcher runs cloudflared with `--protocol quic --edge-ip-version 4`. The PC must be allowed to connect out on
UDP port 7844 over IPv4
([firewall requirements](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/configure-tunnels/tunnel-with-firewall/)).

### TinyTeX

Only needed for the remote LaTeX build ([Plugin-Integration/LaTeX.md](Plugin-Integration/LaTeX.md)).

1. Install TinyTeX with the Windows instructions at [yihui.org/tinytex](https://yihui.org/tinytex/). It installs to
   `%APPDATA%\TinyTeX`, where the launcher looks for it; set `IGNIS_TINYTEX` if it is elsewhere.
2. Install the two extra packages: `tlmgr install biber glossaries`.
3. Install every other package the document uses: `tlmgr install <name>`.

The build requires `lualatex.exe`, `biber.exe` and `makeglossaries.exe` in TinyTeX's `bin\windows\` folder.

### HTTPS-scanning antivirus

Antivirus products that scan HTTPS re-sign connections with their own root certificate. The launcher handles this in two
ways:

- cloudflared always uses QUIC. Over HTTP/2 it rejects a re-signed certificate.
- Ignis's Node does not read Windows' certificate store. If the file `<root>\ignis\runtime\extra-ca.pem` exists,
  the launcher passes it to Node as `NODE_EXTRA_CA_CERTS` (`IGNIS_EXTRA_CA_CERT` names another file; keep it in
  `runtime\`, which the sandbox can read).

To create the file:

1. Run `certmgr.msc`.
2. Open **Trusted Root Certification Authorities → Certificates**.
3. Right-click the antivirus's certificate, then **All Tasks → Export**.
4. Choose **Base-64 encoded X.509 (.CER)**.
5. Save it as `<root>\ignis\runtime\extra-ca.pem`.

## 2. The installation folder

Everything lives in `<root>\ignis\`. The launcher finds every path relative to its own location, so it must be at
`<root>\ignis\ignis_native.py`.

| Path | Source | Contents |
| --- | --- | --- |
| `ignis_native.py` | `<repo>\ignis_native.py` | The launcher |
| `relay\augmented-view-forwarder.js` | `<repo>\relay\augmented-view-forwarder.js` | The Augmented View forwarder |
| `app\` | Step 3 | The patched Ignis, built |
| `runtime\node.exe` | `C:\Program Files\nodejs\node.exe` | Ignis's Node. The sandbox cannot read `Program Files\nodejs` |
| `runtime\cloudflared.exe` | Step 1 | The tunnel connector |
| `runtime\extra-ca.pem` | Step 1 (optional) | An extra root certificate for Node |
| `obsidian-app\` | Step 4 | Obsidian's app files and `.obsidian-version` |
| `vaults\<vault name>` | Created by `setup` | A junction to `<vault>`. Ignis's `VAULT_ROOT` is `vaults\` |
| `data\` | Created by `setup` | Ignis's state, including `server-settings.json` |
| `.env` | Step 7 | Hostname and Access settings. Never commit it |
| `ignis.log` | Written by the launcher | The log |
| `status.json` | Written by the launcher | Live status, every 2 s |
| `ignis-launcher.exe` | Step 12 (optional) | The access watcher |

Create the folder and copy the two files from this repository:

```powershell
New-Item -ItemType Directory -Force <root>\ignis\relay, <root>\ignis\runtime
Copy-Item <repo>\ignis_native.py <root>\ignis\
Copy-Item <repo>\relay\augmented-view-forwarder.js <root>\ignis\relay\
Copy-Item 'C:\Program Files\nodejs\node.exe' <root>\ignis\runtime\
```

## 3. Build the patched Ignis

Option A, the fork (the patches are already applied):

```powershell
git clone https://github.com/Gameboard-dev/ignis.git <root>\ignis\app
cd <root>\ignis\app
npm ci
npm run build
```

Option B, upstream with this repository's patches:

```powershell
git clone https://github.com/Nystik-gh/ignis.git <root>\ignis\app
cd <root>\ignis\app
git checkout v0.8.18+obsidian.1.14.4
git apply <repo>\patches\0001-local-plugins-guard.patch
git apply <repo>\patches\0002-listen-host.patch
git apply <repo>\patches\0003-diagnostics.patch
git apply <repo>\patches\0004-mobile.patch
git apply <repo>\patches\0005-startup.patch
git apply <repo>\patches\0006-relay.patch
npm ci
npm run build
```

`npm run build` writes the served bundles to `packages\*\dist\` and readable copies to `packages\*\reference\`
(patch 0005).

## 4. The Obsidian app files

Ignis serves Obsidian's own app files, which are not in its repository. Ignis 0.8.18 is pinned to Obsidian 1.14.4.

1. Download `obsidian-1.14.4.asar.gz` from
   `https://github.com/obsidianmd/obsidian-releases/releases/download/v1.14.4/obsidian-1.14.4.asar.gz`.
2. Decompress it with Node:

   ```powershell
   node -e "const fs=require('fs');fs.writeFileSync('obsidian.asar',require('zlib').gunzipSync(fs.readFileSync('obsidian-1.14.4.asar.gz')))"
   ```

3. Extract it into an empty folder: `npx @electron/asar extract obsidian.asar <root>\ignis\obsidian-app`.
4. Write the version: `Set-Content -NoNewline <root>\ignis\obsidian-app\.obsidian-version 1.14.4`.

The launcher reads `.obsidian-version` at every start and passes it to Ignis as `IGNIS_OBSIDIAN_PIN`. Without the
file the launcher stops with an error. This is what Ignis's own container image does
([entrypoint.sh](https://github.com/Nystik-gh/ignis/blob/main/apps/ignis-server/scripts/entrypoint.sh)).

## 5. The vault

Set `IGNIS_VAULT` to the vault's folder, as a line in `<root>\ignis\.env`:

```
IGNIS_VAULT=C:\Users\<you>\Documents\<vault>
```

or as a **user** environment variable (open a new terminal afterwards):

```powershell
[Environment]::SetEnvironmentVariable('IGNIS_VAULT', '<vault>', 'User')
```

Without `IGNIS_VAULT`, the launcher uses `<root>\vault`; if that folder does not exist, `setup`, `check`, `repair`
and `run` stop with an error naming `IGNIS_VAULT` ([configuration.md](configuration.md#environment-variables)). A
symbolic link is resolved to its target.

## 6. Create the sandbox

```powershell
python <root>\ignis\ignis_native.py setup
```

`setup` is safe to repeat. It:

1. creates the AppContainer `ignis-control.ignis` (or finds it) and prints its SID (the name's prefix is
   `IGNIS_CONTAINER_PREFIX`, [configuration.md](configuration.md#names-in-windows));
2. creates `ignis\data\` and `ignis\vaults\`, and the junction `ignis\vaults\<vault name>` → `<vault>`;
3. grants the container read and execute on `ignis\app`, `ignis\runtime`, `ignis\obsidian-app`, `ignis\vaults` and
   `ignis\relay`, and modify on `ignis\data` and `<vault>`;
4. grants read-attributes, on that folder only, on every folder above `ignis\app` and above `<vault>`.

Folders owned by the system (`C:\`, `C:\Users`) need an administrator. `setup` prints the commands it could not run,
under `Once, in an administrator PowerShell:`, in this form:

```
icacls 'C:\' /grant '*S-1-15-2-…:(RA)'
```

Run each printed command once in an administrator PowerShell. The exact rights are listed in
[architecture.md](architecture.md#the-appcontainer).

## 7. Cloudflare, the token and `.env`

1. Follow [cloudflare.md](cloudflare.md) to create the Access application and the tunnel.
2. Store the tunnel token: `python <root>\ignis\ignis_native.py set-token`. Paste the token at the hidden prompt.
3. Create `<root>\ignis\.env` with at least `IGNIS_HOSTNAME=vault.example.com` (your real hostname). The keys are in
   [configuration.md](configuration.md#the-env-file).

## 8. Install the plugin

The plugin has no build step.

1. Create `<vault>\.obsidian\plugins\ignis-control\`.
2. Copy `main.js`, `manifest.json` and `styles.css` from the release (or from `<repo>`) into it.
3. In desktop Obsidian, open **Settings → Community plugins** and enable **Ignis Control**.

The plugin also loads in Ignis, where it shows the browser panel (server settings, plugin exclusions, diagnostics).
To keep it out of Ignis, add `ignis-control` to the plugin exclusions.

Add two-way sync plugins to the exclusions (**Settings → Ignis Control → Plugin exclusions**). A second sync engine in
a browser tab would sync the same files again.

## 9. First run

The plugin needs two paths on each device: the `ignis\` folder and a `python.exe`. Both come from
`%LOCALAPPDATA%\Ignis Control\location.json`, which the launcher writes at every start. Choose one:

- **Start the launcher once by hand.** Run `python <root>\ignis\ignis_native.py run` in a terminal. The plugin then
  finds both paths. Close the terminal to stop the launcher.
- **Set the paths in the plugin.** Open **Settings → Ignis Control → This panel** and set **Ignis folder**
  (`<root>\ignis`) and **Python** (the full path to `python.exe` with `pywin32` and `psutil`).

Then select **Start** under **Controls**. The plugin starts `pythonw.exe` from the same folder as **Python** (or
`python.exe` if there is no `pythonw.exe`) with `ignis_native.py run`, without a window.

The status bar dot turns green when Ignis runs and the tunnel has at least one connection. Open
`https://vault.example.com`. Cloudflare Access asks for your e-mail address, then for the code it sends.

## 10. Check the sandbox

```powershell
python <root>\ignis\ignis_native.py check
```

The plugin's **Sandbox check → Run** runs the same command and shows its output. `check` starts `node.exe` inside the
container, tries to read each probe path, and compares the result with the expected one. Then it lists vault entries
that lack the container's access rule. The last line is `all as expected` or `SOME PROBES DID NOT MATCH`; the exit
code is 0 or 1.

| Probe | Expected |
| --- | --- |
| `<vault>` | readable |
| `<root>\ignis\vaults\<vault name>` | readable |
| `<root>\ignis\data` | readable |
| `<root>\ignis\app\package.json` | readable |
| A file `check` writes in `%TEMP%` for the run (in your profile, outside the vault), deleted afterwards | denied |
| `<root>\ignis\.env` (the launcher's settings) | denied |
| `<root>\ignis\ignis_native.py` (the launcher) | denied |
| The first file directly in `<root>` | denied |
| `%USERPROFILE%\Documents` | denied |
| The folder that holds `<vault>` | denied |
| `%USERPROFILE%\.ssh` | denied |
| `%APPDATA%`, `%LOCALAPPDATA%`, `%ProgramData%` | denied |
| `%PUBLIC%\Documents` (every user may read it; the sandbox may not) | denied |
| The root of every other fixed disk (`D:\`, …) | denied |

The denied probes are built from this PC's environment when `check` runs, and a path that does not exist is left
out (it would prove nothing). A folder on the way down to the vault or to `ignis\` (often `Documents` and the folder
that holds the vault) carries the container's attributes-only rule, and may carry a listing rule if you added one;
for such a folder `check` probes the first file in it instead of listing it. Windows' own folders (`C:\Windows`,
`Program Files`) are readable to every AppContainer, so they are not probed. A vault entry without the container's
rule fails the check; `python <root>\ignis\ignis_native.py repair` fixes it.

Run `check` after installation, after every upgrade, and after any change to folders or permissions.

## 11. Start at logon

```powershell
python <root>\ignis\ignis_native.py install-startup
```

This creates `%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\Ignis Control.lnk`. The shortcut runs
`pythonw.exe` (beside the Python that ran the command) with `"<root>\ignis\ignis_native.py" run`, in `<root>`,
minimised. Delete the shortcut to stop starting at logon.

## 12. Optional: the access watcher

A file moved into the vault keeps its old access list, and the sandbox cannot open it. Without the watcher, the
launcher scans the whole vault every 300 s and repairs such entries. With the watcher, it repairs each entry as
Windows reports it.

1. Build it: `cargo build --release` in `<repo>\launcher\` ([building.md](building.md#the-access-watcher)).
2. Copy `<repo>\launcher\target\release\ignis-launcher.exe` to `<root>\ignis\`, or set `IGNIS_LAUNCHER_EXE` (in
   `.env`) to its full path.
3. Restart the launcher. `ignis.log` shows `access: watching the vault for items lacking the sandbox's rule`.

Details: [launcher/README.md](../launcher/README.md).

## 13. Upgrading

### Ignis

1. Read the new release's tag. It names the Obsidian version it is pinned to: `v<ignis>+obsidian.<x.y.z>`.
2. Update the fork, or re-apply the patches:
   - Fork: `git -C <root>\ignis\app pull --ff-only`. When the fork's `main` has been rebased onto a newer upstream
     release, this fails; then run `git -C <root>\ignis\app fetch` and
     `git -C <root>\ignis\app reset --hard origin/main`.
   - Upstream: `git checkout <new tag>`, then `git apply` the six patches in order. If a hunk fails, fix it by hand;
     the patches touch `packages/shim/src/init.js`, `packages/shim/src/loader.js`,
     `apps/ignis-server/server/index.js`, `apps/ignis-server/server/routes/fs.js` and
     `packages/server-core/src/errors.js`, among others ([patches/README.md](../patches/README.md)).
3. In `<root>\ignis\app`: `npm ci`, `npm run build`, `npm run lint`.
4. If the Obsidian version changed, repeat [step 4](#4-the-obsidian-app-files) with the new version, into an emptied
   `obsidian-app\`.
5. Run `python <root>\ignis\ignis_native.py setup`. It grants the new files. Run any administrator commands it
   prints.
6. Run `python <root>\ignis\ignis_native.py check`.
7. Restart the launcher (**Restart** in the plugin).

### Node.js or cloudflared

1. Copy the new `node.exe` or `cloudflared.exe` into `<root>\ignis\runtime\`.
2. Run `setup` and `check`.
3. Restart the launcher.

### Ignis Control

1. Read the release notes. Stop the launcher (**Stop** in the plugin).
2. Copy the new `ignis_native.py` and `relay\augmented-view-forwarder.js` into `<root>\ignis\`. Rebuild and copy
   `ignis-launcher.exe` if you use the access watcher.
3. Update the plugin (copy the new `main.js`, `manifest.json` and `styles.css` into
   `<vault>\.obsidian\plugins\ignis-control\`, or let BRAT update it), and reload it in desktop Obsidian.
4. Start the launcher, then run `check`.

### From version 0.3

Version 0.4.0 gave the installation's names in Windows a neutral, configurable prefix and moved some defaults. An
installation set up with 0.3.x keeps working after these steps; do them before starting the new launcher:

1. **Keep the sandbox and the stored token.** Open `<root>\ignis\status.json` (written by the old launcher) and read
   its `container` field, `<prefix>.ignis`. Unless it is `ignis-control.ignis`, add `IGNIS_CONTAINER_PREFIX=<prefix>`
   to `<root>\ignis\.env`. Without this line the new launcher uses a new sandbox, which needs `setup`, the
   administrator commands it prints, and `set-token` again.
2. **The logon shortcut.** Delete the old shortcut in `%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\`
   (the one whose target is `ignis_native.py`), then run `install-startup`, which makes `Ignis Control.lnk`.
3. **The extra root certificate**, if you use one: rename the `.pem` file in `runtime\` to `extra-ca.pem`, or set
   `IGNIS_EXTRA_CA_CERT` to it.
4. **The access watcher**, if you use it: copy `ignis-launcher.exe` to `<root>\ignis\`, or set `IGNIS_LAUNCHER_EXE`.
5. **Ignored paths.** The default `IGNIS_IGNORED_PATHS` is now the LaTeX build folder only. If you relied on other
   folders being ignored, list them in `IGNIS_IGNORED_PATHS` after the default value
   ([configuration.md](configuration.md#environment-variables)).
6. **The plugin's paths.** The launcher now records itself in `%LOCALAPPDATA%\Ignis Control\location.json`; the new
   launcher writes it at its first start. Until then, set **This panel → Ignis folder** and **Python** in the plugin if
   the status stays hollow.
