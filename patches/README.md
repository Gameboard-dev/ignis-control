# Patches to Ignis

Six patches to [Ignis](https://github.com/Nystik-gh/ignis) by Nystik. Ignis Control's launcher and plugin depend on
them.

- **Base:** release tag `v0.8.18+obsidian.1.14.4` (commit `d65e2f3`). Apply them in order.
- **Licence:** GNU Affero General Public License, version 3 or later, as Ignis is ([LICENSE](LICENSE), copied
  unchanged from Ignis). The rest of this repository is under the MIT licence.
- **Fork:** the same changes, one commit each, are on the `main` branch of
  [Gameboard-dev/ignis](https://github.com/Gameboard-dev/ignis). Its
  [fork documentation](https://github.com/Gameboard-dev/ignis/tree/main/docs/fork) describes each patch in detail:
  what it changes, why, the files touched, configuration, and behaviour when not configured.

| Patch | What it does | Configuration |
| --- | --- | --- |
| `0001-local-plugins-guard.patch` | Keeps the plugins listed in `.obsidian/ignis-disabled-plugins.json` off in Ignis while desktop runs them; follows desktop's plugin switches in open tabs; stores Ignis's layout as `workspace-ignis.json` | The vault file `.obsidian/ignis-disabled-plugins.json` |
| `0002-listen-host.patch` | `HOST` sets the address the server listens on | `HOST` (unset: every interface, as upstream) |
| `0003-diagnostics.patch` | Logs failed requests with their reason and file; browser tabs report errors (with the plugin on the stack), plugin load times, stalls, memory and crashes to the server's log | `LOG_REQUESTS=errors`, `NO_COLOR`, the vault file `.obsidian/ignis-diagnostics.json` |
| `0004-mobile.patch` | Asks the browser to keep the site's storage, so Obsidian's metadata index survives; keeps `.obsidian` files in the browser between visits while they are unchanged on the server | The server setting `persistentCacheBytes` (default 100 MB, 0 turns it off) |
| `0005-startup.patch` | Builds Ignis's two browser bundles minified; writes readable copies to `packages/*/reference/`, which the server does not serve; adds the class `is-ignis` to the page | none |
| `0006-relay.patch` | The same-origin relay `/relay/<service>/…`: streams requests through the named pipe named in `IGNIS_LOCAL_RELAY` to the launcher | `IGNIS_LOCAL_RELAY` (unset: every relay request gets 503) |

Patch 0003 also changes `local-plugins-guard.js`, which patch 0001 adds, so apply 0001 before 0003.

## Applying them

```
git clone https://github.com/Nystik-gh/ignis.git app
cd app
git checkout v0.8.18+obsidian.1.14.4
git apply ../patches/0001-local-plugins-guard.patch
git apply ../patches/0002-listen-host.patch
git apply ../patches/0003-diagnostics.patch
git apply ../patches/0004-mobile.patch
git apply ../patches/0005-startup.patch
git apply ../patches/0006-relay.patch
npm ci
npm run build
```

Replace `../patches/` with the path of this folder. Then continue with
[docs/installation.md](../docs/installation.md#4-the-obsidian-app-files).

For a newer Ignis release, apply the patches the same way and fix by hand any hunk that no longer applies
([docs/installation.md, "Upgrading"](../docs/installation.md#13-upgrading)).
