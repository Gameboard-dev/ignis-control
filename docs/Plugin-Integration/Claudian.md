# Claudian: Claude Code in the browser

Ignis Control runs the Claude Code CLI on the PC, in a sandbox of its own, so that the
[Claudian](https://github.com/Nax51/obsidian-claudian) plugin works when the vault is open in a browser through
Ignis.

Claudian is a third-party plugin, by someone else, and it is **not modified**: the copy in the vault's
`.obsidian\plugins\realclaudian\` is the one desktop Obsidian and Ignis both load. What makes it work in a browser is
Ignis patch 0007 and the launcher's `claude` service, described here.

## Why

Claudian embeds the [Claude Agent SDK](https://docs.claude.com/en/api/agent-sdk/overview), which starts the Claude
Code CLI as a child process and talks to it over the process's standard input and output. A page in a browser cannot
start a process: Ignis's shim for Node's `child_process` threw for every function, so in a browser the plugin failed
as soon as it tried to run the CLI.

The launcher can start a process, and it already starts programs in Windows AppContainers for the
[LaTeX build](LaTeX.md#the-sandbox). So the CLI runs on the PC, inside a container that may change the vault and
nothing else, and the browser gets the CLI's input and output over the relay. The plugin needs no change: it still
believes it started a child process.

## How it flows

1. The plugin (or the SDK inside it) calls `child_process.spawn("/claude", [...])`.
2. Ignis's shim (patch 0007) refuses any program but the Claude Code CLI, with the same `ENOENT` Node gives for a
   program that is not installed. For the CLI it sends `POST /relay/claude/start` with the arguments only.
3. The Ignis server passes the request and its `Cf-Access-Jwt-Assertion` header through the relay's pipe. Together
   with `latex`, `claude` is one of the two services that receive this header.
4. The launcher verifies the Cloudflare Access token ([security.md](../security.md)), checks the arguments, and starts
   **its own** `claude.exe` in the `<prefix>.claude` AppContainer, with the vault as the working directory. It
   answers `{"id", "pid"}`.
5. The shim opens `GET /relay/claude/output/<id>`, a stream of server-sent events: each `data:` frame is base64 of
   what the CLI wrote, and an `exit` event carries its exit code. The shim turns those into the `data` events of
   `child.stdout` and the `close` event of the child.
6. Everything written to `child.stdin` becomes `POST /relay/claude/input/<id>`. Writes made before the CLI has
   started are kept and sent in order once it has.
7. `child.kill()` becomes `POST /relay/claude/stop/<id>`.

## Scope

**It does:**

- start the Claude Code CLI, and only that one program: the launcher finds `claude.exe` itself and never takes a
  program name, a path or a command line from the browser;
- pass on the arguments the plugin gives, as an argument array (never a command line, so nothing in an argument can
  start another program), refusing `--add-dir`, more than 400 arguments, more than 256 KiB of them together, and any
  argument holding a null character;
- run the CLI with the vault as its working directory, and with a fixed environment whose home, temporary and
  configuration folders are inside `ignis\claude\`;
- carry the CLI's output and input, and stop it on request;
- allow four sessions at once (one browser tab needs one), and stop a session whose output nothing has read for
  30 minutes.

**It does not:**

- pass on the working directory, the environment or the `stdio` option the browser asked for: the launcher chooses
  all three;
- read or write the plugin's settings, or any file outside the vault and its own folder;
- give the browser any other program. `exec`, `execFile`, `fork`, `spawnSync` and the rest still throw in a browser,
  and `spawn` of anything but the CLI reports `ENOENT`.

### The sandbox

The CLI runs in an AppContainer of its own, `<prefix>.claude`, separate from the one Ignis runs in, so Claude Code
cannot read or change Ignis's own files or state. Its access rules, made by `claude-setup`:

| Access | Path |
| --- | --- |
| modify | the vault, all of it (inherited, as Ignis's own rule is) |
| modify | `ignis\claude` — its configuration, sign-in, home and temporary folders. Deliberately **not** under `ignis\data`, every part of which is granted to the Ignis container: the sign-in kept there would be readable to Ignis, which is the thing a container of its own is meant to prevent |
| read + run | the folder holding `claude.exe` |
| read | the extra root certificate, when one is set (`IGNIS_EXTRA_CA_CERT`), that one file |
| network | `internetClient` only: connections out, so the CLI can reach the API |
| **out of reach** | the vault's `.obsidian` folder, which holds every plugin's code. Desktop Obsidian runs that code **as you, outside any sandbox**, so a session able to write there could leave code to run at the next start of Obsidian. Nothing the CLI does needs the folder. Ignis itself still reads and writes it, as it must |

Nothing else of the PC is granted: not your home folder, not your own `~/.claude`, not Ignis's folders. **Inside the
vault the CLI may read and change every note**, which is what Claudian is for; the container is what stops it going
further. Claudian's own default is to ask for no approval before each tool call ("YOLO mode"); its Safe mode asks.

**How `.obsidian` is kept out of reach, and a Windows trap.** A *deny* rule naming the container's package SID does
not work. icacls writes it, `Get-Acl` shows `Deny / FullControl` first in the list, and a process in the container
reads the file straight through anyway: what decides an AppContainer's access is whether something *allows* its
package SID, which is also why every folder with no rule at all is refused. So the folder is taken out of reach
instead -- it stops inheriting the vault's rule and the container's entry is removed from it and everything under it
(`unshare` in the launcher) -- and a deny rule is written afterwards as a statement of intent, for the day Windows
weighs one. `claude-probe` caught the deny-only version passing, and is what proves the real one holds.

**Proving it.** `python ignis\ignis_native.py claude-probe` runs thirteen short programs inside the container, as a
session runs, and reports what each could and could not reach: a note in the vault and its own sign-in (allowed);
`.obsidian`, Ignis's state and program files, your own `~/.claude`, this project's files, your Documents, your SSH
keys, another drive, and planting a junction (all refused). It judges nothing by the access lists; it reports what
Windows actually allowed.

Unlike Ignis's own Node, the CLI starts without a rule on each folder on the way down to it. If a session ever fails
to start with a permission error, that is the thing to try: `icacls '<each folder from C:\ down to the CLI>' /grant
'*<the container's SID>:(RA)'`, the SID being the one `claude-setup` prints.

## Set-up on the PC

Once:

1. Install the Claude Code CLI ([instructions](https://docs.claude.com/en/docs/claude-code)). The launcher finds
   `claude.exe` on `PATH`, in winget's package folder, in `%LOCALAPPDATA%\Programs\claude`,
   `%USERPROFILE%\.local\bin` or `%USERPROFILE%\.claude\local`. A line `IGNIS_CLAUDE_CLI=<path to claude.exe>` in
   `ignis\.env` names it instead. Only a real `.exe` is accepted: a `.cmd` would need a command interpreter.
2. `python ignis\ignis_native.py claude-setup` — makes the container and its access rules. Run it again if the CLI
   moves.
3. `python ignis\ignis_native.py claude-login` — **the sandbox signs in for itself.** This runs the CLI here, as you,
   with its configuration folder set to `ignis\claude\.claude`; type `/login`, follow the browser, then `/exit`.
   Your own `~/.claude` is not read or changed, and the sandbox cannot read it. The sign-in it writes sits outside the
   vault, so a browser cannot download it.
4. `python ignis\ignis_native.py claude-check` — proves it: runs `claude.exe --version` and then a one-line prompt in
   the container, and prints what each said.
5. The three Cloudflare Access settings in `ignis\.env` (`IGNIS_ACCESS_TEAM`, `IGNIS_ACCESS_AUD`,
   `IGNIS_ACCESS_EMAILS`), the same three the LaTeX build needs. Without them every request to `/relay/claude/` is
   refused, as is a request made on the PC rather than through the tunnel.

## Set-up in the plugin

One setting, in **Claudian's own settings** -- not Ignis Control's, which has no entry for Claudian and needs none.

**Open the vault in a browser through Ignis**, and there: Settings -> Community plugins -> **Claudian** ->
**Providers** tab -> **Claude Code** -> the **Claude Code CLI path** box.

![Claudian's Providers tab: the Claude Code panel, with the "Claude Code CLI path" box beneath
it](../images/claudian-cli-path.png)

Type `/.ignis/claude` into that box.

> **Do this in the Ignis tab, not in desktop Obsidian.** The box says "Optional CLI path **for this computer**", and
> Claudian means it: the value is stored per host, and Ignis reports its host as `localhost`. Set in the Ignis tab it
> sits beside what desktop Obsidian found for itself and changes nothing there. Set on the desktop it would override
> the desktop's own detection, and Ignis would still not have a path. The panel above the box tells you which one you
> are looking at: on the desktop it reads **Auto-detected** with the real path to `claude.exe`, and in Ignis it reads
> **Not found**, because a browser cannot see the PC's filesystem.

That path is never read and nothing lives there. It exists in the browser as a file only so that Claudian's own
check of the box passes -- it requires a path that is absolute, exists, is a file, and is executable -- and its name
is what marks the spawn as the Claude Code CLI's. The launcher chooses the real `claude.exe` itself.

Nothing else needs changing. The model, the tools, the safety mode and the rest are Claudian's own settings, shared
with the desktop through the vault.

Claudian must also be switched on in Obsidian's **Community plugins** list for either app to load it; an open Ignis
tab follows that list and switches it on within about a second.

## Status, logs and failures

### Endpoints

| Request | Answer |
| --- | --- |
| `GET /relay/claude/status` | `available`, `why`, `cli`, `container`, and `sessions` (each with `id`, `pid`, `seconds`, `exit`) |
| `POST /relay/claude/start` | 200 `{"id", "pid"}`; 400 a refused argument; 429 four sessions already; 503 not ready; 500 the CLI did not start |
| `GET /relay/claude/output/<id>` | 200 an event stream; 404 no such session; 409 something is reading it already |
| `POST /relay/claude/input/<id>` | 200 `{"written"}`; 404 no such session; 409 the CLI has stopped reading |
| `POST /relay/claude/stop/<id>` | 200 `{"stopped": true}` |
| anything else under `/relay/claude/` | 404 |
| any of them without a valid Access token | 403, and a `relay: claude refused (…)` line in the log |

### Log lines

`ignis.log` gets one line when a session starts (`claude: session <id> (pid <n>) started for <address>: <n>
arguments`), one when it ends with its exit code, one when a session is stopped because nothing was reading it, and
one for each refusal.

### Failures

| What you see | Why | What to do |
| --- | --- | --- |
| `brotliDecompressSync is not a function`, the plugin fails to load | The server has no `/api/brotli` route: it is running without patch 0007, or was not restarted after it was applied | Restart the launcher, which restarts the server |
| `spawn /claude ENOENT` in the plugin | The CLI path setting is not `/.ignis/claude`, so the shim treated it as another program | Set **Claude CLI path** to `/.ignis/claude` |
| 503 and "the sandboxed CLI has not signed in yet" | `claude-login` has not been run | Run it once on the PC |
| 503 and "the Claude Code CLI was not found" | No `claude.exe` where the launcher looks | Install it, or set `IGNIS_CLAUDE_CLI` |
| 403 for every request | No Cloudflare Access token: the three `.env` settings are missing, or the page was opened on the PC instead of through the tunnel | Set them; use the tunnel address |
| "the CLI did not start in the sandbox" | The container's rules are missing | Run `claude-setup`, then `claude-check` |
| `Not logged in · Please run /login` from `claude-check` | The container has no sign-in of its own | Run `claude-login` |
| "Ignoring extra certs from …, load failed: Operation not permitted" in the CLI's output | The CLI looked for the antivirus's own certificate, whose folder antivirus software will not let anything grant access to | A warning only. Keep a copy of the certificate somewhere the sandbox may read and name it in `IGNIS_EXTRA_CA_CERT` |
