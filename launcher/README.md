# ignis-launcher

A Rust program that keeps the vault's files open to Ignis's sandbox. It is the first part of a native replacement for
`ignis_native.py`. **Windows only. Tested on Windows 11 Pro.**

## The vault access repair

Ignis runs in the AppContainer `ignis-control.ignis`, which can open only what carries its access rule. Entries created in
the vault inherit the rule from the vault's folder. An entry moved in from elsewhere keeps the access list it had,
and Ignis cannot open it. Without this program, `ignis_native.py` scans the whole vault every 300 s. This program
watches for changes instead.

```
ignis-launcher access check  --vault <folder> --sid <S-1-15-2-…>   report entries that lack the rule
ignis-launcher access repair --vault <folder> --sid <S-1-15-2-…>   make each one inherit again, once
ignis-launcher access watch  --vault <folder> --sid <S-1-15-2-…>   one full scan, then each entry as it arrives
                             [--exit-with-stdin]                   (ReadDirectoryChangesW: created, moved or renamed
                                                                    in, or its access list changed)
```

Each command prints one JSON line per scan or repair, with the fields `event` (`check`, `scan`, `rescan`,
`repaired`), `entries`, `repaired`, `failed`, and the first paths. With `--exit-with-stdin`, `watch` ends when its
standard input closes.

## Use by the Python launcher

1. Build it: `cargo build --release` in this folder.
2. Copy `target\release\ignis-launcher.exe` to `<root>\ignis\`, beside `ignis_native.py`, or set
   `IGNIS_LAUNCHER_EXE` to its full path. When the file exists, `ignis_native.py` runs it as
   `ignis-launcher.exe access watch --vault <vault> --sid <SID> --exit-with-stdin`.
3. The launcher shows the program's lines in `ignis.log` (`access: …`) and under **Vault access** in Ignis Control's
   status.
4. If the program stops, the launcher restarts it. After five failures in a row, each within 60 s of starting, the
   launcher returns to its own scans every 300 s.

## Links are never followed

- The scan skips symbolic links and junctions and does not enter them.
- The repair opens each entry without following links (`FILE_FLAG_OPEN_REPARSE_POINT`), refuses it if it is a link,
  and changes the access list through that handle. An entry swapped for a link between the scan and the repair cannot
  redirect the change to a folder outside the vault.
- Nothing is run and no command line is built.

## Tests

`cargo test --release` (in `tests/access.rs`), with SYSTEM standing in for the sandbox's SID:

- a file whose inherited rules were removed is repaired;
- a junction to a protected folder outside the vault is neither entered nor changed;
- `watch` repairs a file moved in while it runs.

## Planned parts

The AppContainer and its grants, the supervised processes (Ignis, cloudflared), the relays, the status file and the
logon shortcut, with the same checks as `ignis_native.py check`.
