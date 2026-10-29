# Cloudflare set-up for Ignis Control

This guide sets up the Cloudflare side of Ignis Control, step by step: the account, the domain, the Zero Trust
organisation, the login (Cloudflare Access), the tunnel, DNS and HTTPS, and the values the launcher reads from
`ignis\.env`. It links to Cloudflare's own documentation for each step and says exactly which options to choose.
[installation.md](installation.md) covers everything on the PC (the sandbox, building Ignis, upgrades).

Dashboard paths follow Cloudflare's documentation. If a path in the dashboard differs, the linked Cloudflare page is
the reference.

## What you end up with

```
browser ──https──> Cloudflare ──Access: e-mail code──> tunnel ──> cloudflared ──> http://127.0.0.1:8080 (Ignis)
                                                         (outbound from your PC; nothing on the PC listens publicly)
```

- Cloudflare Access stands in front of the hostname. Only your e-mail address gets in, with a one-time code.
- cloudflared, in the launcher's sandbox, dials out to Cloudflare. No port is opened on your router or PC.
- The tunnel token is kept in Windows Credential Manager, never in a file.

## Placeholders

Replace these with your own values. Never commit or share the real ones.

| Placeholder | Meaning |
| --- | --- |
| `example.com` | your domain on Cloudflare |
| `vault.example.com` | the hostname Ignis is published at (one subdomain level: `vault.example.com`, not `a.b.example.com`) |
| `<team>` | your Zero Trust team name; the team domain is `<team>.cloudflareaccess.com` |
| `you@example.com` | the e-mail address that may log in |
| `<root>` | the folder that holds `ignis\` (the launcher is `<root>\ignis\ignis_native.py`) |

## Contents

1. [On the PC first](#1-on-the-pc-first)
2. [Cloudflare account and two-factor authentication](#2-cloudflare-account-and-two-factor-authentication)
3. [A domain on Cloudflare](#3-a-domain-on-cloudflare)
4. [The Zero Trust organisation](#4-the-zero-trust-organisation)
5. [One-time PIN login](#5-one-time-pin-login)
6. [The Access application](#6-the-access-application)
7. [The tunnel](#7-the-tunnel)
8. [DNS and SSL/TLS](#8-dns-and-ssltls)
9. [The `.env` values](#9-the-env-values)
10. [Checking it works](#10-checking-it-works)
11. [Keeping it safe](#11-keeping-it-safe)
12. [When something is wrong](#12-when-something-is-wrong)

## 1. On the PC first

Complete these steps of [installation.md](installation.md) before the Cloudflare steps:

| What | Where |
| --- | --- |
| Python 3.9 or later with `pywin32` and `psutil` (needed by `set-token`) | [Prerequisites](installation.md#1-prerequisites) |
| `cloudflared.exe` saved as `<root>\ignis\runtime\cloudflared.exe`, with no Windows service installed | [cloudflared](installation.md#cloudflared) |
| Outbound UDP port 7844 over IPv4 allowed (the launcher runs cloudflared with `--protocol quic --edge-ip-version 4`) | [cloudflared](installation.md#cloudflared) |
| The antivirus root certificate, only if your antivirus scans HTTPS | [HTTPS-scanning antivirus](installation.md#https-scanning-antivirus) |
| TinyTeX, only for the LaTeX build | [TinyTeX](installation.md#tinytex) |
| The installation folder, the built Ignis and `setup` | [Steps 2–6](installation.md#2-the-installation-folder) |

Nothing on the PC needs to accept incoming connections.

## 2. Cloudflare account and two-factor authentication

1. Create a Cloudflare account. The free plan is enough for everything here. The sign-up link is on Cloudflare's
   [Get started](https://developers.cloudflare.com/cloudflare-one/setup/) page.
2. Verify your account e-mail address. (Two-factor authentication and domain registration both need it.)
3. Turn on two-factor authentication: **My Profile → Authentication**, then **Add** next to Mobile App
   Authentication or Security Key Authentication. Store the backup codes somewhere safe.
   ([Two-factor authentication](https://developers.cloudflare.com/fundamentals/user-profiles/2fa/).)

Your Cloudflare login controls who can open your vault. Protect it at least as well as the vault.

## 3. A domain on Cloudflare

You need a domain whose DNS is on Cloudflare (a "full setup"). Choose one of these:

- **A. Register a new domain with Cloudflare Registrar.** Dashboard: **Register domains**. Search, select
  **Purchase**, choose the term, enter contact details, pay. It uses Cloudflare's nameservers automatically.
  ([Register a new domain](https://developers.cloudflare.com/registrar/get-started/register-domain/).)
- **B. Use a domain you already own elsewhere.** Dashboard: **Domains → Onboard a domain**. Enter the apex domain
  (`example.com`), continue, choose the **Free** plan, review the DNS records it found, then change the domain's
  nameservers **at your registrar** to the two Cloudflare nameservers shown. Wait until the domain shows as
  **Active**. ([Onboard a domain](https://developers.cloudflare.com/fundamentals/manage-domains/add-site/).)

Pick the hostname now, for example `vault.example.com`. Use one level of subdomain: a deeper one
(`a.b.example.com`) needs a paid Advanced Certificate.

## 4. The Zero Trust organisation

Access and the tunnel live in Cloudflare Zero Trust. Create its organisation once:

1. In the [Cloudflare dashboard](https://dash.cloudflare.com/), select **Zero Trust**.
2. On the onboarding screen, choose a **team name**. Use something that does not identify you or the vault; it
   appears in the login page's address.
3. Choose the **Zero Trust Free** plan. Cloudflare asks for payment details even for the free plan, but does not
   charge.

([Create a Zero Trust organization](https://developers.cloudflare.com/cloudflare-one/setup/#2-create-a-zero-trust-organization).)

**The team domain** is `<team>.cloudflareaccess.com`. The LaTeX build needs it, or just the team name
(`IGNIS_ACCESS_TEAM`, section 9). You
can read the team name and team domain at any time under **Zero Trust → Settings**
([What is a team domain?](https://developers.cloudflare.com/cloudflare-one/faq/getting-started-faq/)).

## 5. One-time PIN login

New organisations log in with the Cloudflare identity provider (a Cloudflare account) by default. Ignis Control uses
a one-time PIN sent by e-mail instead:

1. **Zero Trust → Integrations → Identity providers**.
2. Under **Your identity providers**, select **Add new identity provider**.
3. Select **One-time PIN**.

([One-time PIN login](https://developers.cloudflare.com/cloudflare-one/integrations/identity-providers/one-time-pin/).)

## 6. The Access application

Create the Access application **before** the tunnel's route. A route without an Access application is open to
anyone on the internet.

### Create it

**Zero Trust → Access controls → Applications → Create new application → Self-hosted and private → Add public
hostname** ([Publish a self-hosted application](https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/self-hosted-public-app/)).

| Setting | Choose |
| --- | --- |
| Name (if asked) | `Ignis` (any name) |
| Public hostname | subdomain `vault`, **Domain** `example.com`, path empty (the whole site) |
| Access policies | a new policy, below |
| Identity providers | **One-time PIN** only. Clear any other (such as the Cloudflare identity provider) |
| Apply instant authentication | **on** (with one provider, users go straight to the e-mail code page) |
| Authenticate with Cloudflare One Client | off |
| Session Duration | **24 hours** or shorter (see below) |
| Additional settings | leave the defaults |

**The policy.** Under **Access policies**, create a new policy:

| Field | Value |
| --- | --- |
| Policy name | `Owner only` |
| Action | **Allow** |
| Rule | **Include** → **Emails** → `you@example.com` |

Use **Emails**, not **Emails ending in** (that would admit everyone at the same e-mail provider). Add a second
address only for someone who may read and change every note in the vault.

Select **Create** (or **Save**) to finish. ([Policies](https://developers.cloudflare.com/cloudflare-one/access-controls/policies/).)

**Session duration.** A user (and the LaTeX build's token) stays logged in for this long, then gets a new code by
e-mail. Shorter is safer; 24 hours is a reasonable upper limit for a phone. The LaTeX build accepts a request only
while the session's token is valid, so after it expires, reload the page and log in again.

### Hardening

- **Deny is the default.** Access lets in only users who match an Allow policy. You do not need a Block policy for
  "everyone else".
- **No Bypass and no Service Auth policies** on this application. Bypass turns Access off for what it matches, and
  its requests are not logged. Service Auth admits a service token instead of a person. If you once made a service
  token (for testing), delete it: **Zero Trust → Access controls → Service credentials → Service Tokens**
  ([service tokens](https://developers.cloudflare.com/cloudflare-one/access-controls/service-credentials/service-tokens/)),
  and remove any Service Auth policy that used it. The LaTeX build refuses service tokens anyway (they carry no
  e-mail address).
- **Optional: limit by country or IP.** Edit the policy and add a **Require** rule, for example **Require → Country →
  your country**. A traveller will then be locked out until the rule is changed.
- **App Launcher.** It is off by default; leave it off. In the application, **Configure → Experience settings**, keep
  **Show application in App Launcher** off
  ([App Launcher](https://developers.cloudflare.com/cloudflare-one/access-controls/access-settings/app-launcher/)).
- **Leave "Browser-based RDP, SSH or VNC" off.** Ignis is a plain web app.

### The Application Audience (AUD) tag

The LaTeX build checks that each request's Access token was issued for this application. It needs the
application's **AUD tag** (`IGNIS_ACCESS_AUD`, section 9).

**In the dashboard:**

1. **Zero Trust → Access controls → Applications**.
2. Find the application for `vault.example.com` and select **Configure** (in the row's menu).
3. Open the **Additional settings** tab.
4. Copy **Application Audience (AUD) Tag**: a long string of letters and digits.

([Get your AUD tag](https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/authorization-cookie/validating-json/#get-your-aud-tag).)
If the **Additional settings** tab does not show it, look on the application's **Overview** tab, under **Basic information**. The tag changes only
if the application is deleted and created again.

**Fallback: read it from your own login token.** If the dashboard does not show it, read the `aud` claim from the
token your browser holds after logging in. The token is a credential until it expires: do not paste it into any
website or online "JWT decoder", and do not share it.

1. Open `https://vault.example.com` and log in with the e-mail code.
2. Open the browser's developer tools (F12). Chrome or Edge: **Application → Cookies**; Firefox: **Storage →
   Cookies**. Select `https://vault.example.com`.
3. Copy the value of the cookie **`CF_Authorization`**.
4. Decode it on your own PC. In PowerShell:

   ```powershell
   $t = Read-Host 'Paste the CF_Authorization value'
   $p = $t.Split('.')[1].Replace('-', '+').Replace('_', '/')
   $p += '=' * ((4 - $p.Length % 4) % 4)
   [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($p)) | ConvertFrom-Json | Select-Object aud, iss, email
   ```

   `aud` is the AUD tag. `iss` is `https://<team>.cloudflareaccess.com`, your team domain. `email` is the address you
   logged in with.
5. Close the PowerShell window afterwards (the token was on screen).

## 7. The tunnel

A **remotely managed** tunnel: its settings live in Cloudflare, and the PC needs only its token.

### Create it and store the token

1. Dashboard: **Networking → Tunnels → Create Tunnel**
   ([Get started with Cloudflare Tunnel](https://developers.cloudflare.com/tunnel/get-started/)). If the
   dashboard has no **Networking** menu, tunnels are under **Zero Trust → Networks → Tunnels**. If asked for the connector type, choose
   **Cloudflared**.
2. Name it, for example `ignis`, and select **Create Tunnel**.
3. Under the operating system, choose **Windows** and **64-bit**. The page shows an install command. **Do not run it.**
   Copy the command into Notepad. The token is the long string at the end of the command.
4. Store the token in Credential Manager. In a terminal:

   ```
   python <root>\ignis\ignis_native.py set-token
   ```

   Paste the token at the hidden prompt and press Enter. It is stored as the generic credential
   `ignis-control.ignis/cloudflared-tunnel-token`. Run `set-token` again to replace it; press Enter alone to remove it.
5. Close Notepad **without saving**. Do not put the token in `.env`, a script or a shortcut: the launcher ignores a
   `TUNNEL_TOKEN` line in `.env` and says so in the log.
6. Start the launcher (Ignis Control's **Start**, or `python <root>\ignis\ignis_native.py run`). Within a minute the
   dashboard shows the tunnel as **Healthy**, and `ignis\ignis.log` has `Registered tunnel connection` lines. Then
   select **Continue**. (If you left the page, open the tunnel from **Networking → Tunnels**.)

If you lose the token, get it again from **Networking → Tunnels →** your tunnel **→ Add a replica** (copy the
command, do not run it) ([Tunnel tokens](https://developers.cloudflare.com/tunnel/reference/tunnel-tokens/)).

### Add the route

**Networking → Tunnels →** your tunnel **→ Routes → Add route → Published application**:

| Field | Value |
| --- | --- |
| Subdomain | `vault` |
| Domain | `example.com` |
| Path | empty |
| Service URL | `http://127.0.0.1:8080` |

Use `127.0.0.1`, not `localhost`: Ignis listens on IPv4 only, and `localhost` may resolve to IPv6. Use `http`, not
`https`: the hop from cloudflared to Ignis stays inside the sandbox on this PC. Leave **Additional application
settings** as they are. Select **Save** (or **Add route**).

### What the tunnel must not have

- **No other routes.** One published application, `vault.example.com → http://127.0.0.1:8080`. Every other address
  on the PC stays unreachable.
- **No private network.** Add no **Tunnel CIDR** or **Tunnel Hostname** route for this tunnel under **Networking →
  Routes**. Such routes would carry Cloudflare One Client (WARP) traffic into your network through this tunnel.
- **No replica elsewhere.** Run the token only through the launcher on this PC.

**Optional: Protect with Access.** cloudflared can also check the Access token itself before it passes a request on.
Edit the route, expand **Additional application settings**, and under **Access** turn on **Protect with Access** with
your team name and the AUD tag ([origin parameters](https://developers.cloudflare.com/tunnel/reference/origin-parameters/)).
This guards against an Access application deleted or mis-set by mistake. It has not been tested with Ignis Control's
sandbox; if the site stops loading after you turn it on, turn it off again and check `ignis.log`.

## 8. DNS and SSL/TLS

- **DNS.** Adding the route creates a proxied (orange-cloud) `CNAME` record, `vault → <tunnel id>.cfargotunnel.com`.
  Check it under the domain's **DNS → Records**. Leave it proxied. Do not add `A` or `AAAA` records pointing at your
  home IP address.
- **Encryption mode.** Leave **Automatic SSL/TLS** (the default) or choose **Full (strict)** on the domain's
  **SSL/TLS → Overview** page. Never **Off**. The tunnel is encrypted on its own, whatever the mode
  ([HTTPS origins with Cloudflare Tunnel](https://developers.cloudflare.com/tunnel/troubleshooting/https-origins/),
  [encryption modes](https://developers.cloudflare.com/ssl/origin-configuration/ssl-modes/)).
- **Always Use HTTPS.** Turn it on: **SSL/TLS → Edge Certificates → Always Use HTTPS**
  ([Always Use HTTPS](https://developers.cloudflare.com/ssl/edge-certificates/additional-options/always-use-https/)).
- **Nothing on the PC listens publicly.** Ignis listens on `127.0.0.1` inside the sandbox, and Windows drops
  connections into the sandbox from outside it. Do not forward any port on your router.

## 9. The `.env` values

The launcher reads `<root>\ignis\.env`: one `KEY=value` per line (a value may be wrapped in one pair of `"` or `'`
quotes, which are removed), lines starting with `#` ignored. It is
git-ignored; never commit it. Save it as UTF-8 (Notepad's default), not "UTF-8 with BOM".

| Key | What it is | Where to get it | Needed for |
| --- | --- | --- | --- |
| `IGNIS_HOSTNAME` | the public hostname, without `https://` | section 3 | everything: Ignis accepts WebSockets only from `https://<this host>` |
| `IGNIS_ACCESS_TEAM` | the team name, `<team>`, or the team domain, `<team>.cloudflareaccess.com` (a leading `https://` and a trailing `/` are allowed) | section 4 | the LaTeX build |
| `IGNIS_ACCESS_AUD` | the Access application's AUD tag | section 6 | the LaTeX build |
| `IGNIS_ACCESS_EMAILS` | who may start a build, comma-separated; compared without regard to case | your Access policy | the LaTeX build |

Example (placeholders):

```
# Ignis Control
IGNIS_HOSTNAME=vault.example.com
IGNIS_ACCESS_TEAM=<team>.cloudflareaccess.com
IGNIS_ACCESS_AUD=<the AUD tag>
IGNIS_ACCESS_EMAILS=you@example.com
```

- After changing `IGNIS_HOSTNAME`, restart the launcher. The three `IGNIS_ACCESS_*` values are read at each build
  request; no restart is needed.
- The literal value `IGNIS_HOSTNAME=vault.example.com` is treated as unset. Use your real hostname.
- `IGNIS_ACCESS_TEAM` may be the bare team name (the launcher adds `.cloudflareaccess.com`) or the full team domain;
  anything else is invalid. If any of the three is missing or wrong, every request to
  `/relay/latex/` is refused (403) and nothing is built.
- `IGNIS_ACCESS_EMAILS` should list only addresses your Access policy also allows.
- What the launcher checks on each build request: the token's RS256 signature against the team's keys (fetched from
  `https://<team>.cloudflareaccess.com/cdn-cgi/access/certs`, kept for an hour), the issuer
  (`https://<team>.cloudflareaccess.com`), the AUD tag, the expiry, and the e-mail address.
- The tunnel token is **not** in `.env` (section 7).

Every key, with defaults and when it is read: [configuration.md](configuration.md#the-env-file).

## 10. Checking it works

| Check | Expected |
| --- | --- |
| `python <root>\ignis\ignis_native.py check` | `all as expected`. This proves the sandbox, not Cloudflare; run it after set-up and after changes |
| **Networking → Tunnels** | the tunnel is **Healthy** |
| Ignis Control's status dot | green: Ignis running, tunnel connected (amber: tunnel down or no token stored) |
| Open `https://vault.example.com` in a private window | Cloudflare's page asking for your e-mail address, then for the code it sends. Not Ignis directly |
| Log in with `you@example.com` | the code arrives; Ignis opens |
| Try another address | no code arrives, or "That account does not have access" |
| Ignis Control → **Public address** → check | an HTTP 200 answer (the Access page) |
| Logged in, open `https://vault.example.com/relay/latex/status` | JSON with `available`, `why`, `running`, `last`, `desktop_open`. A 403 answer says why (`IGNIS_ACCESS_*` missing or wrong, token expired, address not allowed); `ignis.log` has the same as a `relay: latex refused (…)` line |
| **Zero Trust → Insights → Logs → Access authentication logs** | your login, allowed ([Access authentication logs](https://developers.cloudflare.com/cloudflare-one/insights/logs/dashboard-logs/access-authentication-logs/)) |

**If Ignis opens without the Access page,** the Access application does not cover the hostname. Stop the launcher at
once, then fix the application's public hostname (section 6).

## 11. Keeping it safe

- **Rotate the tunnel token** now and then, and at once if it may have leaked: **Networking → Tunnels →** your
  tunnel **→ Rotate token** (also labelled **Refresh token**), then **Add a replica**, copy the new command without
  running it, take the token, run `set-token`, and restart the launcher
  ([rotate a token](https://developers.cloudflare.com/tunnel/reference/tunnel-tokens/#rotate-a-token)). Existing
  connections with the old token stay up until they are restarted. If the token may be in someone else's hands,
  instead stop the launcher, delete the tunnel and its `CNAME` record, and make a new tunnel with the same route
  (section 7). Deleting the tunnel ends every connection made with the old token.
- **Remove old tunnels.** Delete tunnels you no longer use (**Networking → Tunnels**, select the tunnel, delete it),
  and their leftover `CNAME` records under **DNS → Records**. A deleted tunnel cannot be restored.
- **A lost or stolen device.** Revoke its sessions:
  - for this application: **Zero Trust → Access controls → Applications →** the application **→ Configure → Revoke
    existing tokens**;
  - for a user everywhere: **Zero Trust → Team & Resources → Users**, select the user, **Action → Revoke**.

  The next login needs a new e-mail code, so also secure the e-mail account itself. If the device held your e-mail,
  change that password first. ([Revoke user sessions](https://developers.cloudflare.com/cloudflare-one/access-controls/access-settings/session-management/#revoke-user-sessions).)
- **Log out** on a shared computer: open `https://vault.example.com/cdn-cgi/access/logout`.
- **Watch the sign-ins.** **Zero Trust → Insights → Logs → Access authentication logs** lists every login attempt,
  allowed or not.
- **Review now and then:** the Access policy still lists only your address; no Bypass or Service Auth policy; no
  unused service tokens; the tunnel has one route; two-factor authentication is still on.

## 12. When something is wrong

| Symptom | Likely cause |
| --- | --- |
| Ignis opens with no Access page | the Access application's hostname does not match the route. Stop the launcher; fix section 6 |
| 502 or "Bad gateway" | the route's Service URL is not `http://127.0.0.1:8080`, or Ignis is not running (`ignis.log` says which) |
| Page loads but stays "connecting" | `IGNIS_HOSTNAME` is not exactly the public hostname; fix it and restart the launcher |
| Tunnel never becomes Healthy | no token stored (`set-token`), UDP 7844 blocked outbound, or `cloudflared.exe` missing from `ignis\runtime`; see `ignis.log` |
| A Cloudflare One Client or VPN is running | they can block the tunnel or show a Gateway block page; try with them off |
| `/relay/latex/status` answers 403 | read the `error` in the answer; usually an `IGNIS_ACCESS_*` value or an expired session |

[troubleshooting.md](troubleshooting.md) covers the launcher, the sandbox and the relay.
