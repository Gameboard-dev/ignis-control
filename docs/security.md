# Security

What Ignis Control protects, how, and what it does not protect.

## Threat model

Ignis gives full read and write access to a vault to anyone who can open its page. It has no login. Ignis Control
publishes it on the internet, so it assumes:

| Assumption | Consequence |
| --- | --- |
| Anyone on the internet can send requests to `vault.example.com` | Cloudflare Access must admit only listed people |
| A person who passes Access is the vault's owner | Ignis Control does not restrict what such a person does inside the vault |
| Ignis, its dependencies or a plugin in the browser may be compromised | The server process is fenced so that it cannot read or change anything on the PC outside the vault and its own folders |
| A page in the browser may send any request to the relay | The launcher, outside the sandbox, passes only listed requests |
| Files in the vault may be written by the browser | The launcher takes no program path, service port or other setting from the vault (or from `ignis\data`, which the sandbox can also write) |

## What is protected, and how

| Asset | Threat | Protection |
| --- | --- | --- |
| The vault | Access by strangers | Cloudflare Access with one-time PIN to listed e-mail addresses, in front of the whole hostname ([cloudflare.md](cloudflare.md#6-the-access-application)) |
| The PC's other files | A compromised Ignis process reading or changing them | The AppContainer `ignis-control.ignis` denies everything not granted ([architecture.md](architecture.md#rights-of-ignis-controlignis)); `check` proves it |
| The PC's network services | A compromised Ignis process connecting to them | The container has no loopback exemption, so it cannot connect to the PC's services. The only route is the relay's named pipes |
| The PC from the LAN | Direct connections to Ignis | Ignis listens on `127.0.0.1` inside the container, and Windows drops connections into an AppContainer |
| The PC from the internet | Open ports | None. cloudflared opens the tunnel outbound |
| Desktop services | Requests that change settings, reveal keys or stop the service | Per-service allowlists in the launcher ([relay.md](relay.md#services)) |
| Other services on the PC | The relay redirected to them by a changed port setting | Ports come from the launcher's environment or `ignis\.env` (`IGNIS_AUGMENTED_VIEW_PORT`, default 8790), never from the vault's `data.json`; a port that is another known service's is refused ([relay.md](relay.md#services)) |
| The relay | Use by another website | The Ignis server refuses an `Origin` that is neither this host nor in `WS_ORIGINS` |
| Cookies and Access tokens | Leaking to desktop services | The Ignis server forwards only seven listed headers; the Access token goes only to `latex` |
| The tunnel token | Theft from a file or the log | Kept in Credential Manager ([below](#the-tunnel-token)) |
| The LaTeX build | Running a command chosen by the request | A fixed command sequence; nothing from the request reaches a command line ([Plugin-Integration/LaTeX.md](Plugin-Integration/LaTeX.md)) |
| Other programs on the PC | **Stop** killing a program that is not the launcher (a stale or altered `status.json`) | The plugin asks Windows which program has the id and stops only `python.exe` or `pythonw.exe` |
| Program paths on desktop | The browser choosing the program desktop Obsidian runs | The `ignis\` folder and the Python path are kept per device, outside the vault ([configuration.md](configuration.md#plugin-settings)) |
| Commands the launcher and the plugin run | A folder or file name with quotes, `&` or `;` changing a command | Every program is started with an argument list, never through a shell; Windows' own tools by full path from `%SystemRoot%\System32`; the few PowerShell commands are fixed text, with their values passed as environment variables (tested with hostile values in `test/relay_test.py`) |
| Files moved into the vault | Breaking the access rule | The launcher repairs entries without following links ([architecture.md](architecture.md#the-vaults-access-rule)) |

## What is not protected

- **The vault, from anyone who passes Access.** That person can read, change and delete every file in the vault.
- **Desktop Obsidian, from plugin code changed through Ignis.** The vault's `.obsidian\plugins\` folder is inside the
  vault, so a person who passes Access can change the code of a plugin. Desktop Obsidian on the PC loads that code
  with your rights. Treat access to the vault as equal to running code on the PC, and admit only yourself.
- **Windows' own folders.** `C:\Windows` and `Program Files` stay readable to every AppContainer (`ALL APPLICATION
  PACKAGES`).
- **The launcher.** `ignis_native.py` runs with your rights, not sandboxed. It starts the sandboxed processes and
  handles every relay request. A flaw in it is not contained.
- **biber.** In the LaTeX build, biber runs outside the sandbox, with your rights, because its executable cannot start
  in an AppContainer. Its inputs are checked first.
- **Cloudflare.** Cloudflare terminates TLS and can see the traffic. Your Cloudflare login controls who can open the
  vault: protect it with two-factor authentication.

## Cloudflare Access

- Access is a Cloudflare Zero Trust application covering the whole hostname, with one Allow policy that includes
  only listed e-mail addresses, and the One-time PIN identity provider. Set-up and hardening:
  [cloudflare.md](cloudflare.md#6-the-access-application).
- Deny is the default: a person who matches no Allow policy is refused.
- Do not add Bypass or Service Auth policies. Bypass turns Access off for what it matches. Service Auth admits a
  service token instead of a person.
- After login, Cloudflare adds a signed JSON Web Token to every request, in the header `Cf-Access-Jwt-Assertion` and
  the cookie `CF_Authorization`. The Ignis server forwards the header only to `latex`, and the cookie to no service.

### How the LaTeX build verifies the token

At every `/relay/latex/` request, the launcher:

1. reads `IGNIS_ACCESS_TEAM`, `IGNIS_ACCESS_AUD` and `IGNIS_ACCESS_EMAILS` from `.env`;
2. fetches the team's signing keys from `https://<team>.cloudflareaccess.com/cdn-cgi/access/certs` (cached for
   3,600 s; fetched again when the token names an unknown key);
3. checks the RS256 signature (PKCS#1 v1.5 over SHA-256, computed in Python without extra packages);
4. checks that `aud` contains the AUD tag;
5. checks that `iss` is `https://<team>.cloudflareaccess.com`;
6. checks that `exp` is in the future and that `nbf` (or `iat`) is no more than 60 s in the future;
7. checks that `email`, in lower case, is in `IGNIS_ACCESS_EMAILS`.

Any failure gives 403 with the reason, and `relay: latex refused (<reason>)` in the log. A service token has no
e-mail address and is always refused. A request made on the PC itself has no token and is always refused.

## The tunnel token

- Stored by `ignis_native.py set-token` as a Windows generic credential, target
  `ignis-control.ignis/cloudflared-tunnel-token`, user name `cloudflared`, persisted for your account on this PC.
  Windows encrypts it for your account.
- Viewable in **Control Panel → Credential Manager → Windows Credentials**.
- `set-token` reads it at a hidden prompt. Pressing Enter alone removes it.
- The launcher reads it only to start cloudflared, which receives it as `TUNNEL_TOKEN` in its environment. It is never
  written to a file, a command line or the log. A `TUNNEL_TOKEN` line in `.env` is ignored.
- Rotate it in the Cloudflare dashboard if it may have leaked ([cloudflare.md](cloudflare.md#11-keeping-it-safe)).

## Files that hold secrets or state

| File | Contains | Protection |
| --- | --- | --- |
| `<root>\ignis\.env` | Hostname, team domain, AUD tag, allowed addresses, the vault's folder, Augmented View's port | Git-ignored; outside the vault; not readable or writable by the sandbox (`check` probes it) |
| `<root>\ignis\status.json` | Process ids, counts, the public URL | Git-ignored; outside the vault |
| `<root>\ignis\ignis.log` | Requests that failed, tab reports, relay decisions | Git-ignored; outside the vault. The plugin hides token-like lines in its live log |
| `<root>\ignis\runtime\extra-ca.pem` | A public root certificate | Git-ignored (`*.pem`) |

## The sandbox probes

`ignis_native.py check` is the test of the fence. It starts `node.exe` inside `ignis-control.ignis` with the same
environment as Ignis, tries to read each probe path (list a folder, or read a file), and compares the result with the
expectation. The denied probes are built on each PC from its environment (`%USERPROFILE%`, `%APPDATA%`,
`%LOCALAPPDATA%`, `%ProgramData%`, `%PUBLIC%`, the fixed disks), and a file `check` writes in `%TEMP%` for the run, so
they prove the same denials on any PC. It also checks every vault entry for the container's rule. The probe list and
the expected results are in [installation.md](installation.md#10-check-the-sandbox).

Run it after installation, after each upgrade, and after any change to folders or permissions. Every line must read
`ok`, and the last line `all as expected`.
