# Licences

[← README](../README.md)

## Ignis

[Ignis](https://github.com/Nystik-gh/ignis) ("Ignis - Obsidian server bridge") is the work of its author, Nystik,
Copyright (C) 2026 Nystik, and is free software under the
[GNU Affero General Public License, version 3 or later](https://www.gnu.org/licenses/agpl-3.0.html). Its documentation
is at [ignis.thiefling.com/docs](https://ignis.thiefling.com/docs/). Ignis Control is an unofficial companion to it,
written by someone else and not affiliated with or endorsed by Ignis's author (or by Obsidian). Everything Ignis does
(serving the vault and Obsidian to a browser, its proxy, its settings) is Ignis's own work; Ignis Control adds a
launcher, a sandbox, the relay and a control panel around it, and six patches to it.

## This repository

| Files | Licence |
| --- | --- |
| The plugin (`main.js`, `manifest.json`, `styles.css`), the launcher (`ignis_native.py`), the forwarder (`relay/`), the access watcher (`launcher/`), the tests and the documentation | [MIT](../LICENSE) |
| The patches to Ignis (`patches/*.patch`) | GNU Affero General Public License, version 3 or later ([patches/LICENSE](../patches/LICENSE), copied unchanged from Ignis) |

**How the patches relate to the rest.** The patches change Ignis's source code, which is under the AGPL, so they are
under the AGPL too. They are applied to your own copy of Ignis when you build it ([installation.md](installation.md#3-build-the-patched-ignis));
the plugin and the launcher contain no Ignis code. The launcher only starts the patched Ignis as a separate program and
talks to it through environment variables, a named pipe and HTTP. The same patches, one commit each, are published as
source on the fork [Gameboard-dev/ignis](https://github.com/Gameboard-dev/ignis), which keeps upstream's licence.

**If you run a modified Ignis for others.** The AGPL asks that users who interact with a modified Ignis over a network
can get its source. The patched source is public (the fork, and `patches/` here); if you change it further and let
other people use your server, publish your changes too.

## Programs Ignis Control runs or builds on

None of these is distributed with Ignis Control: you download each one yourself from its own publisher, under its own
licence.

| Program | Licence | Where |
| --- | --- | --- |
| Ignis | AGPL 3.0 or later | [Nystik-gh/ignis](https://github.com/Nystik-gh/ignis) |
| Obsidian's app files (served by Ignis) | Obsidian's own terms | [obsidian.md](https://obsidian.md/license), [releases](https://github.com/obsidianmd/obsidian-releases/releases) |
| cloudflared | Apache 2.0 | [cloudflare/cloudflared](https://github.com/cloudflare/cloudflared) |
| Node.js | MIT, with bundled third-party licences | [nodejs.org](https://nodejs.org/) |
| Python | Python Software Foundation License | [python.org](https://www.python.org/) |
| pywin32 | Python Software Foundation License | [mhammond/pywin32](https://github.com/mhammond/pywin32) |
| psutil | BSD 3-Clause | [giampaolo/psutil](https://github.com/giampaolo/psutil) |
| Pygments (optional) | BSD 2-Clause | [pygments.org](https://pygments.org/) |
| TinyTeX and TeX Live packages (optional) | TinyTeX: GPL 2; TeX Live: the licence of each package | [yihui.org/tinytex](https://yihui.org/tinytex/) |
| The access watcher's Rust crates (`serde_json`, `windows-sys`) | MIT or Apache 2.0 | [crates.io](https://crates.io/) |

Ignis serves Obsidian's own app files to your browser. Obsidian is free for personal use; check
[Obsidian's licence](https://obsidian.md/license) for other uses, such as commercial use.
