# Building and testing

[← README](../README.md)

## The plugin

The plugin has no build step: `main.js`, `manifest.json` and `styles.css` are the files Obsidian loads, as they are in
the repository. Check the script's syntax with `node --check main.js`.

A release attaches exactly these three files to a GitHub release whose tag is the version in `manifest.json` (no
leading `v`), and adds the version and its minimum Obsidian version to `versions.json`.

## The launcher

`ignis_native.py` is a Python script; it needs no build. It uses `pywin32` and `psutil`, and `pygments` for the LaTeX
build's code listings when present.

```powershell
python -m pip install pywin32 psutil pygments
```

### Tests

```powershell
python -I test/relay_test.py
node test/stop_test.js
```

The tests run the launcher's rules without named pipes or the sandbox: the relay's allowlists and refusals, that a port
is never taken from the vault, `.env` parsing and the Cloudflare Access settings, the names derived from
`IGNIS_CONTAINER_PREFIX` (and the refusal of a hostile one), that values reach PowerShell only as environment variables,
and the ignored paths. `test/stop_test.js` checks that **Stop** asks Windows which program has the launcher's process
id and refuses any program but `python.exe` or `pythonw.exe` (it starts and ends one Python process of its own). The
Python tests read no real settings: `ignis/.env` and the environment are replaced by temporary ones.
When an Ignis checkout (`app\`) and Node are beside the script, the ignored paths are also checked with Ignis's own
matcher.

`ignis_native.py check`, run on an installed PC, is the test of the sandbox itself
([installation.md](installation.md#10-check-the-sandbox)).

## The access watcher

The optional access watcher in `launcher/` is a Rust program (Windows only).

```powershell
cd launcher
cargo build --release
cargo test --release
```

The program is `launcher\target\release\ignis-launcher.exe`; copy it to `<root>\ignis\` or point
`IGNIS_LAUNCHER_EXE` at it ([installation.md](installation.md#12-optional-the-access-watcher)). While the launcher
runs it, Windows locks the file, so stop the launcher before rebuilding into the same folder, or build elsewhere with
`CARGO_TARGET_DIR`.

The tests (in `tests/access.rs`) use a temporary folder, with SYSTEM standing in for the sandbox's SID: a file whose
inherited rules were removed is repaired; a junction to a protected folder outside the vault is neither entered nor
changed; `watch` repairs a file moved in while it runs. Details: [launcher/README.md](../launcher/README.md).

## The Ignis patches

`patches/` holds six patches to Ignis 0.8.18; [patches/README.md](../patches/README.md) says what each does and how to
apply them. After applying them, Ignis's own `npm run build` and `npm run lint` build and check the patched server, and
patch 0006 adds tests for the relay route to its test suite (`npm test`, which runs vitest).
