# Disclosures and compliance

[← README](../README.md)

Ignis Control is not listed in Obsidian's community plugins, and it is an unofficial companion to
[Ignis](https://github.com/Nystik-gh/ignis), not affiliated with or endorsed by Ignis's author or by Obsidian. It still
follows Obsidian's [Developer policies](https://docs.obsidian.md/community-directory/developer-policies) and
[Plugin guidelines](https://docs.obsidian.md/Plugins/Releasing/Plugin+guidelines), so that anyone installing it by
hand knows what it does. This page goes through what those policies ask a plugin to disclose, and what they forbid,
and says plainly what Ignis Control does about each and why. It covers the plugin and the launcher it controls,
because the plugin is only useful with the launcher.

- [In short](#in-short)
- [Payment](#payment)
- [Accounts](#accounts)
- [Network use](#network-use)
- [Programs the plugin and the launcher run](#programs-the-plugin-and-the-launcher-run)
- [Files outside the vault](#files-outside-the-vault)
- [No self-installation or self-updating](#no-self-installation-or-self-updating)
- [Telemetry](#telemetry)
- [Ads](#ads)
- [Source code and licences](#source-code-and-licences)
- [Desktop only](#desktop-only)
- [The plugin guidelines](#the-plugin-guidelines)

## In short

Ignis Control is free and open source, shows no ads and collects nothing about you. The plugin is a control panel for
a separate program, the **launcher** (`ignis_native.py`), which you install yourself on a Windows PC and which runs
[Ignis](https://ignis.thiefling.com/docs/) (Obsidian served to web browsers) in a Windows sandbox, published through a
Cloudflare Tunnel behind Cloudflare Access. The plugin starts and stops the launcher and reads its status; it never
downloads or installs anything. Using it needs a Cloudflare account and a domain on Cloudflare; the free plans are
sufficient.

## Payment

None. The plugin and the launcher are free, and every feature works without paying anyone. Cloudflare's Tunnel and
Access are used on Cloudflare's free plan (Zero Trust Free, up to 50 users). A domain name costs whatever your
registrar charges; Ignis Control does not sell or require any particular one.

## Accounts

- **Ignis Control:** none. No sign-in, no API key, no licence key.
- **Cloudflare:** an account is needed to create the tunnel, the DNS record and the Access application that asks for
  a login before anyone reaches the vault ([cloudflare.md](cloudflare.md)). The account and its settings are yours;
  Ignis Control never signs in to it and never calls Cloudflare's API.
- **Signing in to the site:** Cloudflare Access sends a one-time PIN to the e-mail addresses you allow. Those
  addresses are in your Access policy, and (optionally, for the LaTeX build) in the launcher's `.env` on your PC.

## Network use

**The plugin, in desktop Obsidian**, makes one network request of its own, and only when you press
**Controls → Public address → Check**: an HTTPS `GET` to your site's public address (`https://<your hostname>`, read
from the launcher's status file), through Obsidian's `requestUrl`, to report whether the address answers. It sends
nothing else. The links under **Resources** and the **Guide** and **Site** buttons open pages in your web browser when
you select them; the plugin does not fetch them.

**The plugin, inside Ignis** (a browser tab showing your vault), talks only to the Ignis server that served the page,
on the page's own address: it reads and changes Ignis's server options through `/api/settings`, and reads and writes
two small files in the vault's `.obsidian` folder through Obsidian's own file API. It also asks the browser how much
storage the site uses (`navigator.storage.estimate()`), which is a local question, not a network request.

**The launcher**, which you run outside Obsidian, uses the network as follows. Each use is part of what you set it up
to do:

| Who | Connects to | What goes through | Why |
| --- | --- | --- | --- |
| cloudflared (in the sandbox) | Cloudflare's edge, outbound, QUIC on UDP port 7844 | Every page, file and request between a browser and your Ignis server, after Cloudflare Access has admitted the browser | The tunnel publishes Ignis without opening a port on your PC. Cloudflare terminates TLS, so Cloudflare can see this traffic ([security.md](security.md#what-is-not-protected)) |
| Ignis (in the sandbox) | The addresses Obsidian plugins in the browser ask Ignis's proxy for | Those plugins' own requests | Ignis's proxy stands in for desktop Obsidian's network access; this is Ignis's behaviour, not Ignis Control's |
| The launcher | `https://<team>.cloudflareaccess.com/cdn-cgi/access/certs` | Nothing is sent; Cloudflare's public signing keys are fetched (at most once an hour) | Only when the LaTeX build is set up and a build request arrives: to check the request's Cloudflare Access token before building |
| The launcher's relay | `127.0.0.1:<port>` on your own PC | Only the listed requests of a relayed service (Augmented View's model server) | Lets that plugin, in a browser, use the server desktop Obsidian runs ([relay.md](relay.md)) |

The tunnel token (the secret that lets cloudflared connect as your tunnel) is kept in Windows Credential Manager and
handed to cloudflared in its environment; it is never written to a file, a command line or the log.

Nothing in Ignis Control checks for updates, downloads code, or contacts any server of the author's.

## Programs the plugin and the launcher run

**The plugin** runs two programs, both in desktop Obsidian on Windows only, both with an argument list (Node's
`child_process.spawn` and `execFile`, never a shell, so no command line is parsed):

| When | Program | Arguments |
| --- | --- | --- |
| **Start**, **Restart**, **Apply and restart** | `pythonw.exe` beside the Python you set (or `python.exe` if there is none) | `<Ignis folder>\ignis_native.py run` |
| **Sandbox check → Run** | The Python you set | `<Ignis folder>\ignis_native.py check` |

The Python path and the Ignis folder are kept on each device (Obsidian's local storage) or read from the launcher's
`location.json` in `%LOCALAPPDATA%`, never from the vault's `data.json`: the vault can be changed from the browser,
and a path stored there could choose the program desktop Obsidian runs. The plugin accepts only an absolute path whose
file name is `python.exe` or `pythonw.exe`. **Stop** ends the launcher's process (its id is in the launcher's status
file, which is outside the vault). Before killing it, the plugin checks that the status file is fresh and asks
Windows (`tasklist.exe` by its full path, with an argument list) which program has that id: only `python.exe` or
`pythonw.exe` is stopped, and any other program is refused with a message. Windows then ends everything the launcher
started, through its job object. Inside Ignis, the plugin cannot start or stop anything.

**The launcher** runs, outside the sandbox and with your rights, each with an argument list and Windows' own tools by
their full path in `%SystemRoot%\System32`:

| Program | When | Why |
| --- | --- | --- |
| `node.exe` (the copy in `ignis\runtime\`), in the sandbox | Always | The Ignis server, and the Augmented View forwarder |
| `cloudflared.exe` (the copy in `ignis\runtime\`), in the sandbox | When a tunnel token is stored | The tunnel, run with `--no-autoupdate` |
| `icacls.exe` | `setup`; each LaTeX build | Grant the sandbox its access rules |
| `subst.exe`, `tasklist.exe` | Each LaTeX build | Temporary drive letters for TeX; whether desktop Obsidian is running |
| `lualatex.exe`, `makeglossaries.exe` (TinyTeX), in a second sandbox with no network | Each LaTeX build | The build |
| `biber.exe` (TinyTeX) | Each LaTeX build that needs it | Bibliography; it cannot start in a sandbox, so its inputs are checked first |
| Windows PowerShell | Only the commands `install-startup`, `exempt`, `unexempt` | Make the logon shortcut; add or remove a firewall rule. A fixed command each, with the values passed as environment variables |
| `ignis-launcher.exe` (optional, built by you from `launcher/`) | If present | Watches the vault and restores the sandbox's access rule on files moved in |

## Files outside the vault

**The plugin** reads and writes these, in desktop Obsidian only:

| File | Access | Why |
| --- | --- | --- |
| `%LOCALAPPDATA%\Ignis Control\location.json` | Read | Where the launcher is installed and which Python runs it, written by the launcher, so no path travels in the vault |
| `<Ignis folder>\status.json` | Read, every 2 s by default | The launcher's live status, for the status bar dot and the panel |
| `<Ignis folder>\ignis.log` | Read with Node's `fs`: its last 256 KB, then what is added, once a second, only while the plugin's settings tab is open | The **Log** pane. Tokens, Cloudflare team names, AUD tags, e-mail addresses, the site's hostname and other secret-looking values are hidden before a line is kept or shown |
| `<vault>\LaTeX\compiled\.ignis-build.log` | Read the same way, only when **Last LaTeX build's transcript** is chosen in the **Log** pane | The transcript the launcher writes for a LaTeX build through Ignis |
| `<Ignis folder>\data\server-settings.json` | Read; written on **Apply and restart** | Ignis's server options |

The **Log** pane's **Copy** button writes the lines shown (already redacted) to the clipboard when you select it;
the plugin never reads the clipboard. Its choices (source, follow, wrap) are kept on each device in Obsidian's local
storage.

Inside the vault it writes `.obsidian/ignis-disabled-plugins.json`, `.obsidian/ignis-diagnostics.json` and its own
`data.json`.

**The launcher** uses, outside the vault: its installation folder (`<root>\ignis\`: Ignis, its runtime, Ignis's data,
`.env`, `status.json`, `ignis.log`); `%LOCALAPPDATA%\Ignis Control\location.json`; the sandboxes' profile folders that
Windows makes in `%LOCALAPPDATA%\Packages\<prefix>.ignis\` and `<prefix>.latex\`; one Windows Credential Manager entry,
`<prefix>.ignis/cloudflared-tunnel-token`, holding the tunnel token; TinyTeX (read, for the LaTeX build); and, if you
run `install-startup`, one shortcut in your Startup folder. `setup` adds access rules for the sandbox to the vault, to
the installation's folders, and a read-attributes rule to each folder on the way down to them
([architecture.md](architecture.md#the-appcontainer)).

## No self-installation or self-updating

The policies forbid plugins that install or update themselves or their dependencies. Ignis Control never downloads,
installs or updates anything:

- you install the launcher, Ignis, Node.js, cloudflared and (optionally) TinyTeX yourself, by the steps in
  [installation.md](installation.md);
- the plugin only starts the launcher you installed, and the launcher only starts the programs you put in place;
- cloudflared runs with `--no-autoupdate`;
- upgrades are manual steps you take ([installation.md](installation.md#13-upgrading)).

## Telemetry

None, client-side or server-side. Nothing about you or your use is collected or sent anywhere. The status, the log and
the browser tabs' optional diagnostics stay on your PC, in the launcher's own files.

## Ads

None, static or dynamic.

## Source code and licences

Open source. The plugin, the launcher, the forwarder and the access watcher are under the MIT licence
([LICENSE](../LICENSE)). The six patches to Ignis in `patches/` modify Ignis, which is under the GNU Affero General
Public License 3.0 or later, so they are under that licence too ([patches/LICENSE](../patches/LICENSE)); they are not
part of the plugin. The plugin's code is plain, unminified JavaScript (`main.js`), not obfuscated. Details and the
licences of the programs it runs: [licences.md](licences.md).

## Desktop only

`isDesktopOnly` is `true`. In desktop Obsidian the plugin uses Node's `fs`, `path` and `child_process`, which exist
only there. Everything it controls (the AppContainer, Credential Manager, the named pipes) is a Windows feature, so on
macOS and Linux it shows a note and does nothing else. Inside Ignis (a browser) it uses no Node module: it changes
Ignis's server options and the vault's two settings files only.

## The plugin guidelines

| Guideline | How Ignis Control meets it |
|---|---|
| No obfuscation | `main.js` is the source itself, readable and commented |
| Security | No `innerHTML`, `outerHTML` or `insertAdjacentHTML`: text is set with `setText`/`textContent` and the DOM API. No `eval` or `new Function`. Programs are started with argument lists, never through a shell, and never from a path stored in the vault |
| Command ids | Without the plugin id (`open-panel`, `start`, `stop`, `restart`, `open-site`); no default hotkeys |
| Settings | Headings with `setHeading`, in sentence case, without the word "settings" |
| Resources | The status bar click handler is registered with `registerDomEvent` and the refresh timer with `registerInterval`, so both end when the plugin unloads |
| `this.app` | The plugin uses its own `app`, never the global one |
| Styles | All in `styles.css`, scoped to the plugin's classes; Obsidian's CSS variables; no `!important` |
| Licence and attribution | MIT; the Ignis patches keep Ignis's AGPL ([licences.md](licences.md)) |

Two of Obsidian's interfaces the plugin uses are not in Obsidian's public API: `app.setting` (to open its own settings
tab when the status bar item is selected) and `app.plugins` (to list the installed plugins for **Plugin exclusions**,
and, inside Ignis only, to switch an excluded plugin off in the open tab at once). Both are read-only uses or act only
on what you choose in the panel.
