"""Run Ignis (Obsidian in a browser, https://ignis.thiefling.com) natively on Windows, inside an AppContainer.

Why native: Windows reports file changes to Ignis directly (chokidar on ReadDirectoryChangesW) and the vault is read at
full disk speed. In Docker under WSL, edits made by Windows programs never reached Ignis without a bridge. Why an AppContainer: Ignis has no login of its own and is published through a
Cloudflare Tunnel, so the process is fenced in. An AppContainer is Windows' app sandbox: its process may open only what
an access rule grants to its own SID (deny by default, unlike a second user account, which can read whatever
"Users" or "Authenticated Users" may). Both the user's rights and the container's must allow an access.
https://learn.microsoft.com/en-us/windows/win32/secauthz/appcontainer-isolation

What the container is granted (`setup` writes the rules; `check` proves them):
  read + run   ignis/app (Ignis, built from its pinned release plus the patches in patches/), ignis/runtime (its own
               node.exe and, if present, an extra root certificate), ignis/obsidian-app (Obsidian's app files),
               ignis/vaults (the junction)
  modify       ignis/data (Ignis's state) and the vault (VAULT: IGNIS_VAULT, else <root>/vault)
  attributes   C:\\, C:\\Users and every folder on the way down to ignis/ and to the vault: that folder only, no
               listing (Node reads each folder's attributes on the way down to a file)
  network      internetClient only: connections out (cloudflared to Cloudflare; plugins' requests through Ignis's
               proxy). Nothing outside the container can connect in (Windows drops connections into an AppContainer,
               tested 2026-10-23, even with a loopback exemption and a firewall rule), and the container cannot reach
               this PC's own services (without a loopback exemption, a local service refused it). So
               cloudflared runs in the same container, where loopback works, and Ignis listens on 127.0.0.1 only
               (HOST, patches/0002-listen-host.patch). On this PC too, Ignis is reached through the tunnel.
               One deliberate way out: the relays (named pipes to the launcher, which passes only listed requests to
               the services listed in SERVICES; "the Augmented View relay" and "the same-origin relay" below).
Everything else (the rest of the profile, <root> and its other folders, other drives) is denied.

<root> is the folder that holds ignis/ (this script is ignis/ignis_native.py). The launcher's settings (IGNIS_VAULT,
IGNIS_AUGMENTED_VIEW_PORT, ...) come from the environment, else from ignis/.env, never from the vault: the sandbox
cannot read or write either.

Usage (a Python with pywin32 and psutil):
  python ignis/ignis_native.py setup            create the container, grant the folders (no admin needed)
  python ignis/ignis_native.py set-token        store the Cloudflare tunnel token in Credential Manager
  python ignis/ignis_native.py check            run probes inside the container: allowed vs denied paths, and
                                                 list vault files that lack the container's rule
  python ignis/ignis_native.py repair           make such files inherit the vault's rules again (`run` does this
                                                 by itself every 5 minutes)
  python ignis/ignis_native.py run              run Ignis in the foreground, restarting it if it exits
  python ignis/ignis_native.py install-startup  run it at logon (a shortcut in the Startup folder)
  python ignis/ignis_native.py exempt|unexempt  administrator: a loopback exemption + firewall rule, and
                                                          undoing them (tried 2026-10-23; not used, see network above)
Log: ignis/ignis.log. Installation, configuration, upgrades and the tunnel: docs/ in the Ignis Control repository
(https://github.com/Gameboard-dev/ignis-control).
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import subprocess
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)  # console programs started from pythonw open no window
import sys
import threading
import time
from ctypes import wintypes
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

ROOT = Path(__file__).resolve().parents[1]  # ignis/ignis_native.py -> the folder that holds ignis/
IGNIS = ROOT / "ignis"
APP = IGNIS / "app"
RUNTIME = IGNIS / "runtime"
NODE = RUNTIME / "node.exe"
CLOUDFLARED = RUNTIME / "cloudflared.exe"  # cloudflared-windows-amd64.exe from cloudflared's releases, renamed
OBSIDIAN_APP = IGNIS / "obsidian-app"
DATA = IGNIS / "data"
VAULTS = IGNIS / "vaults"  # Ignis's VAULT_ROOT: one junction per vault


def dotenv() -> dict[str, str]:
    """ignis/.env (KEY=value lines; git-ignored). The tunnel token is not kept here (see TOKEN_TARGET)."""
    try:
        lines = (IGNIS / ".env").read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}
    pairs = (l.split("=", 1) for l in lines if "=" in l and not l.lstrip().startswith("#"))
    return {k.strip(): unquoted(v.strip()) for k, v in pairs}


def unquoted(value: str) -> str:
    """A .env value without one pair of matching surrounding quotes ("..." or '...'), as most .env readers take it."""
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def config(name: str, default: str = "") -> str:
    """A launcher setting: the environment variable, else its line in ignis/.env, else `default`. Settings come only
    from here, never from the vault or ignis/data: the sandbox (and so anyone in the browser) can write those."""
    return os.environ.get(name) or dotenv().get(name) or default


# The vault: IGNIS_VAULT, else <root>/vault (may be a symbolic link; the junction and the access rule use the real
# folder). `require_vault` stops the commands that need it, naming the setting, when the folder does not exist.
VAULT = Path(config("IGNIS_VAULT", str(ROOT / "vault"))).resolve()
LOG = IGNIS / "ignis.log"
# An extra root certificate for Node (NODE_EXTRA_CA_CERTS), used only if the file exists: for antivirus software that
# re-signs TLS, export its root certificate as PEM to this file (IGNIS_EXTRA_CA_CERT names another).
CA_CERT = Path(config("IGNIS_EXTRA_CA_CERT", str(RUNTIME / "extra-ca.pem")))
# Programs of Windows itself, by full path (never a PATH lookup: a folder early on PATH could hold a program of the
# same name)
SYSTEM32 = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
POWERSHELL = SYSTEM32 / "WindowsPowerShell" / "v1.0" / "powershell.exe"


def container_prefix(value: str) -> str:
    """IGNIS_CONTAINER_PREFIX checked: letters, digits, '.' and '-', starting with a letter or digit, at most 40
    characters (an AppContainer name may have 64). Anything else stops the launcher with the reason."""
    ok = 0 < len(value) <= 40 and value[0].isascii() and value[0].isalnum() and all(
        c.isascii() and (c.isalnum() or c in ".-") for c in value)
    if not ok:
        sys.exit(f"IGNIS_CONTAINER_PREFIX={value!r} is not a valid name: use letters, digits, '.' and '-' only "
                 f"(at most 40 characters), in {IGNIS / '.env'} or the environment")
    return value


# The names this installation uses in Windows, all from one prefix (IGNIS_CONTAINER_PREFIX, default "ignis-control"):
# the two AppContainers, the tunnel token's Credential Manager entry, the relay's named pipes and the launcher's
# mutex. The AppContainer's SID is derived from its name, so a new prefix means a new container (and new access rules,
# granted by `setup`) and a token stored again (`set-token`). An installation set up under another prefix keeps it by
# setting IGNIS_CONTAINER_PREFIX to that prefix: status.json's "container" field is "<prefix>.ignis".
PREFIX = container_prefix(config("IGNIS_CONTAINER_PREFIX", "ignis-control"))
NAME = f"{PREFIX}.ignis"  # Ignis's AppContainer
PORT = 8080
# Folders Ignis does not watch (gitignore patterns, comma-separated; IGNIS_IGNORED_PATHS replaces the default): the
# LaTeX plugin's build folder, rewritten on every build (ignored folders are not watched but are still listed in the
# tree each tab downloads). Add folders that change constantly, such as a sync plugin's cache, with the setting.
# The LaTeX build folder's contents are ignored except four files a browser must hear about: an ignored file keeps, in
# every tab, the size and time it had when Ignis listed the vault, so Obsidian would ask for the PDF at the same
# address after each build and show the old one, even after a reload. main.pdf and main.shown.pdf (the PDF and the copy
# the LaTeX plugin's pane shows), main.synctex.gz (sync scrolling) and latex-status.json (what the PC's build did, for
# the plugin's status bar) are watched: a few events per build. `*` rather than the folder keeps the folder itself
# watched, and each `!` line watches one file again (LATEX_WATCHED).
LATEX_WATCHED = ("main.pdf", "main.shown.pdf", "main.synctex.gz", "latex-status.json")
IGNORED_PATHS = config("IGNIS_IGNORED_PATHS", ",".join([
    "/LaTeX/compiled/*", *(f"!/LaTeX/compiled/{name}" for name in LATEX_WATCHED)]))
# Capability SIDs: internetClient only (outgoing: plugins' requests through Ignis's proxy, cloudflared to Cloudflare)
CAPABILITIES = ("S-1-15-3-1",)

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
advapi = ctypes.WinDLL("advapi32", use_last_error=True)
userenv = ctypes.WinDLL("userenv")
ole32 = ctypes.WinDLL("ole32")


def log(message: str) -> None:
    try:
        with open(LOG, "a", encoding="utf-8", newline="\n") as f:
            f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} {message}\n")
    except OSError:
        pass


def trim_log(keep: int = 5000) -> None:
    try:
        lines = LOG.read_text(encoding="utf-8").splitlines(keepends=True)
    except OSError:
        return
    if len(lines) > 2 * keep:
        LOG.write_text("".join(lines[-keep:]), encoding="utf-8", newline="\n")


# --- the container ---

_SID: tuple[ctypes.c_void_p, str] | None = None
_SID_LOCK = threading.Lock()


def container_sid() -> tuple[ctypes.c_void_p, str]:
    """Create the AppContainer profile (or find it) and return its SID, as a pointer and as a string. Looked up once and
    shared: concurrent CreateAppContainerProfile calls from the supervising threads failed with E_UNEXPECTED
    (0x8000ffff, logged 2026-10-24), which is likely what kept the tunnel down on 2026-10-23."""
    global _SID
    with _SID_LOCK:
        if _SID is None:
            _SID = _lookup_container_sid()
        return _SID


def _lookup_container_sid(name: str = NAME, title: str = "Ignis",
                          about: str = "Ignis server for the vault") -> tuple[ctypes.c_void_p, str]:
    psid = ctypes.c_void_p()
    hr = userenv.CreateAppContainerProfile(name, title, about, None, 0, ctypes.byref(psid))
    if hr == -2147024713:  # HRESULT_FROM_WIN32(ERROR_ALREADY_EXISTS)
        hr = userenv.DeriveAppContainerSidFromAppContainerName(name, ctypes.byref(psid))
    if hr != 0:
        raise OSError(f"AppContainer profile: HRESULT {hr & 0xFFFFFFFF:#010x}")
    s = wintypes.LPWSTR()
    if not advapi.ConvertSidToStringSidW(psid, ctypes.byref(s)):
        raise ctypes.WinError(ctypes.get_last_error())
    text = s.value or ""
    k32.LocalFree(s)
    return psid, text


def container_folder(sid: str) -> Path:
    """%LOCALAPPDATA%\\Packages\\<name>\\AC: the one profile folder the container may write (its TEMP goes here)."""
    p = wintypes.LPWSTR()
    hr = userenv.GetAppContainerFolderPath(sid, ctypes.byref(p))
    if hr != 0:
        raise OSError(f"GetAppContainerFolderPath: HRESULT {hr & 0xFFFFFFFF:#010x}")
    folder = Path(p.value or "")
    ole32.CoTaskMemFree(p)
    return folder


def grant(path: Path, sid: str, rights: str, inherit: bool = True, quiet: bool = False) -> bool:
    """One access rule for the container (by default inherited by everything under a folder; icacls propagates it)."""
    flags = "(OI)(CI)" if inherit and path.is_dir() else ""
    r = subprocess.run([str(SYSTEM32 / "icacls.exe"), str(path), "/grant", f"*{sid}:{flags}({rights})", "/C"],
                       capture_output=True, text=True, creationflags=NO_WINDOW)
    ok = r.returncode == 0 and "Failed processing 0 files" in r.stdout  # with /C, icacls exits 0 even when refused
    if ok or not quiet:
        print(f"  {rights:2} {path}" + ("" if ok else f"  FAILED: {(r.stdout + r.stderr).strip()[-300:]}"))
    return ok


def setup() -> int:
    _, sid = container_sid()
    print(f"AppContainer {NAME}: {sid}")
    for d in (DATA, VAULTS):
        d.mkdir(exist_ok=True)
    link = VAULTS / VAULT.name
    if not link.exists():
        # A junction made through the Windows API (CPython's _winapi.CreateJunction), not cmd's mklink: no command
        # line is parsed, so a folder name with & or quotes cannot run anything
        import _winapi
        _winapi.CreateJunction(str(VAULT), str(link))
    print(f"  junction {link} -> {VAULT}")
    print("granting:")
    for p in (APP, RUNTIME, OBSIDIAN_APP, VAULTS, FORWARDER.parent):
        grant(p, sid, "RX")
    grant(DATA, sid, "M")
    grant(VAULT, sid, "M")
    # Node (its module loader, and Ignis's confinement check, fs.realpathSync) reads the attributes of every folder on
    # the way down from C:\. RA on just those folders, not inherited: no listing, no contents, only their own
    # timestamps and flags. The ones owned by the system (C:\, C:\Users) need an administrator.
    print("read attributes only, this folder only (the path down to the granted folders):")
    admin = [a for a in sorted({a for p in (APP, VAULT) for a in p.parents}, key=lambda a: len(a.parts))
             if not grant(a, sid, "RA", inherit=False, quiet=True)]
    if admin:
        print("\nOnce, in an administrator PowerShell:")
        for a in admin:
            print(f"  icacls '{a}' /grant '*{sid}:(RA)'")
    return 0


# --- the vault's grant drifting ---
# The vault's rule is inherited by what is created in it, but a file moved in keeps the access list it had: on
# 2026-10-25 the vault was restored from the Recycle Bin and 13,136 of 14,692 files came back without the container's
# rule. Ignis then got EPERM for them (GET /api/fs/readFile 500), Obsidian re-read them on every load and could never
# index them. The launcher looks for such files every ACCESS_EVERY seconds (1.7 s for 24,000 entries) and makes each
# inherit from its folder again, as `icacls <file> /reset` would.

ACCESS_EVERY = 300.0
ACCESS: dict[str, Any] = {"checked_at": 0.0, "entries": 0, "lacking": 0, "repaired_total": 0, "repaired_last": [], "errors": 0}


FILE_ATTRIBUTE_REPARSE_POINT = 0x400


def is_link(path: str) -> bool:
    """A symbolic link, junction or other reparse point (never followed, entered or changed by the repair: a link in
    the vault to a folder elsewhere must not get that folder's access list replaced)."""
    try:
        return bool(os.lstat(path).st_file_attributes & FILE_ATTRIBUTE_REPARSE_POINT)
    except OSError:
        return True  # gone or unreadable: leave it alone


def lacking_grant(sid: str) -> tuple[int, list[str]]:
    """(entries looked at, paths whose access list has no rule for the container). Links are skipped and not walked
    into (os.walk would enter a junction)."""
    import win32security
    want = win32security.ConvertStringSidToSid(sid)
    entries, lacking = 0, []
    for folder, dirs, files in os.walk(VAULT):
        dirs[:] = [d for d in dirs if not is_link(os.path.join(folder, d))]
        for name in dirs + files:
            p = os.path.join(folder, name)
            if name in files and is_link(p):
                continue
            entries += 1
            try:
                dacl = win32security.GetNamedSecurityInfo(
                    p, win32security.SE_FILE_OBJECT, win32security.DACL_SECURITY_INFORMATION).GetSecurityDescriptorDacl()
            except win32security.error:
                continue  # gone since it was listed
            if dacl is not None and not any(dacl.GetAce(i)[2] == want for i in range(dacl.GetAceCount())):
                lacking.append(p)
    return entries, lacking


def reinherit(path: str) -> bool:
    """Replace a file's or folder's access list with what it inherits from its folder: an empty, unprotected list,
    which Windows fills with the inherited rules. Done through a handle opened without following links
    (FILE_FLAG_OPEN_REPARSE_POINT), and refused if the object is itself a link, so a file swapped for a link between
    the scan and this call cannot redirect the change (tested 2026-10-27)."""
    import ntsecuritycon
    import pywintypes
    import win32file
    import win32security
    try:
        h = win32file.CreateFile(
            path, ntsecuritycon.WRITE_DAC | ntsecuritycon.READ_CONTROL, 7, None, win32file.OPEN_EXISTING,
            win32file.FILE_FLAG_BACKUP_SEMANTICS | win32file.FILE_FLAG_OPEN_REPARSE_POINT, None)
    except pywintypes.error:
        return False
    try:
        if win32file.GetFileInformationByHandle(h)[0] & FILE_ATTRIBUTE_REPARSE_POINT:
            log(f"access: {path} is a link; not changed")
            return False
        win32security.SetSecurityInfo(
            h, win32security.SE_FILE_OBJECT,
            win32security.DACL_SECURITY_INFORMATION | win32security.UNPROTECTED_DACL_SECURITY_INFORMATION,
            None, None, win32security.ACL(), None)
        return True
    except pywintypes.error:
        return False
    finally:
        h.Close()


def repair_access(sid: str, quiet: bool = False) -> list[str]:
    """Find what the container cannot open in the vault and make it inherit again; returns the repaired paths."""
    entries, lacking = lacking_grant(sid)
    repaired = [p for p in lacking if reinherit(p)]
    with STATUS_LOCK:
        ACCESS.update(checked_at=time.time(), entries=entries, lacking=len(lacking) - len(repaired),
                      repaired_total=int(ACCESS["repaired_total"]) + len(repaired),
                      repaired_last=[os.path.relpath(p, VAULT) for p in repaired[:20]],
                      errors=len(lacking) - len(repaired))
    if repaired and not quiet:
        log(f"access: {len(repaired)} item(s) in the vault lacked the container's rule, now inherit it again"
            f" (first: {', '.join(os.path.relpath(p, VAULT) for p in repaired[:5])})")
    if len(lacking) > len(repaired):
        log(f"access: {len(lacking) - len(repaired)} item(s) could not be repaired (first: {lacking[0]})")
    return repaired


# The Rust access watcher (launcher/ in the Ignis Control repository, `cargo build --release` there): one full
# scan, then each item as Windows reports it arriving (ReadDirectoryChangesW), instead of a scan every ACCESS_EVERY
# seconds. Without the program the scans go on as before. IGNIS_LAUNCHER_EXE names the program; by default it is
# ignis-launcher.exe beside this script.
ACCESS_EXE = Path(config("IGNIS_LAUNCHER_EXE", str(IGNIS / "ignis-launcher.exe")))


def watch_access(sid: str) -> None:
    if ACCESS_EXE.is_file():
        watch_access_events(sid)
    while True:
        try:
            repair_access(sid)
        except Exception as e:  # never end the thread
            log(f"access: check failed: {e!r}")
        time.sleep(ACCESS_EVERY)


def watch_access_events(sid: str) -> None:
    """Run `ignis-launcher access watch` and keep ACCESS from its JSON lines; restarted if it stops (backing off), and
    left for the scans after five failures in a row."""
    failures = 0
    while failures < 5:
        started = time.time()
        try:
            # stdin stays open while the launcher runs: when it ends, the watcher ends too (--exit-with-stdin)
            p = subprocess.Popen([str(ACCESS_EXE), "access", "watch", "--vault", str(VAULT), "--sid", sid, "--exit-with-stdin"],
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
                                 creationflags=subprocess.CREATE_NO_WINDOW)
        except OSError as e:
            log(f"access: cannot start {ACCESS_EXE.name} ({e}); scanning every {ACCESS_EVERY:.0f} s instead")
            return
        log(f"access: watching the vault for items lacking the sandbox's rule ({ACCESS_EXE.name}, pid {p.pid})")
        assert p.stdout is not None
        for line in p.stdout:
            try:
                r = json.loads(line)
            except ValueError:
                continue
            repaired, failed = int(r.get("repaired", 0)), int(r.get("failed", 0))
            with STATUS_LOCK:
                if r.get("event") in ("scan", "rescan"):
                    ACCESS.update(entries=int(r.get("entries", 0)))
                ACCESS.update(checked_at=time.time(), lacking=failed, errors=failed,
                              repaired_total=int(ACCESS["repaired_total"]) + repaired)
                if repaired:
                    ACCESS["repaired_last"] = list(r.get("repaired_first", []))
            if repaired:
                log(f"access: {repaired} item(s) in the vault lacked the container's rule, now inherit it again"
                    f" (first: {', '.join(r.get('repaired_first', [])[:5])})")
            if failed:
                log(f"access: {failed} item(s) could not be repaired (first: {'; '.join(r.get('failed_first', []))})")
        p.wait()
        why = (p.stderr.read() if p.stderr else "").strip()
        failures = failures + 1 if time.time() - started < 60 else 1
        log(f"access: {ACCESS_EXE.name} stopped (exit {p.returncode}{': ' + why if why else ''}); "
            + ("restarting" if failures < 5 else f"scanning every {ACCESS_EVERY:.0f} s instead"))
        time.sleep(min(60, 2 ** failures))


def repair() -> int:
    _, sid = container_sid()
    entries, lacking = lacking_grant(sid)
    print(f"{entries} entries in {VAULT}; {len(lacking)} lack the container's rule")
    fixed = [p for p in lacking if reinherit(p)]
    for p in lacking:
        print(f"  {'repaired' if p in fixed else 'FAILED  '} {p}")
    return 0 if len(fixed) == len(lacking) else 1


def exempt() -> int:
    """Administrator: let this PC's processes reach the container on loopback (Windows drops that traffic otherwise).
    The same list CheckNetIsolation.exe LoopbackExempt edits; the ones already on it are kept.
    https://learn.microsoft.com/en-us/windows/win32/api/netfw/nf-netfw-networkisolationsetappcontainerconfig"""
    psid, sid = container_sid()
    fw = ctypes.WinDLL("FirewallAPI")
    count, current = wintypes.DWORD(), ctypes.POINTER(SID_AND_ATTRIBUTES)()
    r = fw.NetworkIsolationGetAppContainerConfig(ctypes.byref(count), ctypes.byref(current))
    if r != 0:
        print(f"reading the exemption list failed: error {r}")
        return 1
    sids = [current[i].Sid for i in range(count.value)]
    as_text = []
    for s in sids:
        t = wintypes.LPWSTR()
        advapi.ConvertSidToStringSidW(ctypes.c_void_p(s), ctypes.byref(t))
        as_text.append(t.value)
    if sid in as_text:
        print(f"already exempt: {sid}")
    else:
        items = (SID_AND_ATTRIBUTES * (len(sids) + 1))(*[SID_AND_ATTRIBUTES(s, 0) for s in sids],
                                                         SID_AND_ATTRIBUTES(psid, 0))
        r = fw.NetworkIsolationSetAppContainerConfig(len(items), items)
        print(f"exempted {sid}" if r == 0 else f"failed: error {r} (5 = run it from an administrator shell)")
        if r != 0:
            return 1
    # Windows Firewall filters an AppContainer's inbound traffic, loopback included (tested 2026-10-23: the handshake
    # was dropped until this rule existed). The rule admits this PC only: 127.0.0.1 to 127.0.0.1, TCP PORT.
    ps = ("if (-not (Get-NetFirewallRule -DisplayName $env:IGNIS_FW_RULE -ErrorAction SilentlyContinue)) { "
          "New-NetFirewallRule -DisplayName $env:IGNIS_FW_RULE -Direction Inbound -Action Allow -Protocol TCP "
          "-LocalPort $env:IGNIS_FW_PORT -LocalAddress 127.0.0.1 -RemoteAddress 127.0.0.1 -Package $env:IGNIS_FW_SID "
          "| Out-Null; 'firewall rule added: ' + $env:IGNIS_FW_RULE } "
          "else { 'firewall rule already there: ' + $env:IGNIS_FW_RULE }")
    return powershell(ps, IGNIS_FW_RULE=firewall_rule(), IGNIS_FW_PORT=str(PORT), IGNIS_FW_SID=sid)


def firewall_rule() -> str:
    return f"Ignis (AppContainer {NAME}): this PC only"


def powershell(command: str, **values: str) -> int:
    """Run a FIXED PowerShell command (Windows PowerShell, by its full path); the data it needs arrives as environment
    variables ($env:NAME), never as text inside the command, so no value can change what the command does."""
    r = subprocess.run([str(POWERSHELL), "-NoProfile", "-NonInteractive", "-Command", command],
                       env={**os.environ, **values}, capture_output=True, text=True, creationflags=NO_WINDOW)
    print((r.stdout + r.stderr).strip())
    return r.returncode


def unexempt() -> int:
    """Administrator: undo `exempt` (the loopback exemption and the firewall rule). The exemption also let the
    container connect out to every service on this PC's loopback (tested 2026-10-23: local services answered it), so
    it is not used: cloudflared runs inside the container instead."""
    _, sid = container_sid()
    fw = ctypes.WinDLL("FirewallAPI")
    count, current = wintypes.DWORD(), ctypes.POINTER(SID_AND_ATTRIBUTES)()
    if fw.NetworkIsolationGetAppContainerConfig(ctypes.byref(count), ctypes.byref(current)) != 0:
        print("reading the exemption list failed")
        return 1
    keep = []
    for i in range(count.value):
        t = wintypes.LPWSTR()
        advapi.ConvertSidToStringSidW(ctypes.c_void_p(current[i].Sid), ctypes.byref(t))
        if t.value != sid:
            keep.append(current[i].Sid)
    if len(keep) == count.value:
        print("not exempt")
    else:
        items = (SID_AND_ATTRIBUTES * max(len(keep), 1))(*[SID_AND_ATTRIBUTES(s, 0) for s in keep])
        r = fw.NetworkIsolationSetAppContainerConfig(len(keep), items)
        print(f"exemption removed: {sid}" if r == 0 else f"failed: error {r} (5 = run it from an administrator shell)")
        if r != 0:
            return 1
    ps = ("$r = Get-NetFirewallRule -DisplayName $env:IGNIS_FW_RULE -ErrorAction SilentlyContinue; "
          "if ($r) { $r | Remove-NetFirewallRule; 'firewall rule removed: ' + $env:IGNIS_FW_RULE } "
          "else { 'no firewall rule' }")
    return powershell(ps, IGNIS_FW_RULE=firewall_rule())


# --- starting a process in it ---

class SID_AND_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("Sid", ctypes.c_void_p), ("Attributes", wintypes.DWORD)]


class SECURITY_CAPABILITIES(ctypes.Structure):
    _fields_ = [("AppContainerSid", ctypes.c_void_p), ("Capabilities", ctypes.POINTER(SID_AND_ATTRIBUTES)),
                ("CapabilityCount", wintypes.DWORD), ("Reserved", wintypes.DWORD)]


class STARTUPINFOW(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD), ("lpReserved", wintypes.LPWSTR), ("lpDesktop", wintypes.LPWSTR),
                ("lpTitle", wintypes.LPWSTR), ("dwX", wintypes.DWORD), ("dwY", wintypes.DWORD),
                ("dwXSize", wintypes.DWORD), ("dwYSize", wintypes.DWORD), ("dwXCountChars", wintypes.DWORD),
                ("dwYCountChars", wintypes.DWORD), ("dwFillAttribute", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                ("wShowWindow", wintypes.WORD), ("cbReserved2", wintypes.WORD), ("lpReserved2", ctypes.c_void_p),
                ("hStdInput", wintypes.HANDLE), ("hStdOutput", wintypes.HANDLE), ("hStdError", wintypes.HANDLE)]


class STARTUPINFOEXW(ctypes.Structure):
    _fields_ = [("StartupInfo", STARTUPINFOW), ("lpAttributeList", ctypes.c_void_p)]


class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [("hProcess", wintypes.HANDLE), ("hThread", wintypes.HANDLE),
                ("dwProcessId", wintypes.DWORD), ("dwThreadId", wintypes.DWORD)]


class SECURITY_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("nLength", wintypes.DWORD), ("lpSecurityDescriptor", ctypes.c_void_p),
                ("bInheritHandle", wintypes.BOOL)]


class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD)]


class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION), ("IoInfo", ctypes.c_uint64 * 6),
                ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]


k32.CreatePipe.argtypes = [ctypes.POINTER(wintypes.HANDLE), ctypes.POINTER(wintypes.HANDLE),
                           ctypes.POINTER(SECURITY_ATTRIBUTES), wintypes.DWORD]
k32.CreateFileW.restype = wintypes.HANDLE
k32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(SECURITY_ATTRIBUTES),
                            wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
k32.SetHandleInformation.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD]
k32.InitializeProcThreadAttributeList.argtypes = [ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD,
                                                  ctypes.POINTER(ctypes.c_size_t)]
k32.UpdateProcThreadAttribute.argtypes = [ctypes.c_void_p, wintypes.DWORD, ctypes.c_size_t, ctypes.c_void_p,
                                          ctypes.c_size_t, ctypes.c_void_p, ctypes.c_void_p]
k32.CreateProcessW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, ctypes.c_void_p, ctypes.c_void_p, wintypes.BOOL,
                               wintypes.DWORD, ctypes.c_void_p, wintypes.LPCWSTR, ctypes.c_void_p,
                               ctypes.POINTER(PROCESS_INFORMATION)]
k32.CreateJobObjectW.restype = wintypes.HANDLE
k32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
k32.ResumeThread.argtypes = [wintypes.HANDLE]
k32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
k32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
k32.CloseHandle.argtypes = [wintypes.HANDLE]
k32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]


def kill_on_close_job() -> wintypes.HANDLE:
    """A job whose processes all end when the launcher does, so Ignis never outlives it."""
    job = k32.CreateJobObjectW(None, None)
    info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
    info.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not k32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)):
        raise ctypes.WinError(ctypes.get_last_error())
    return wintypes.HANDLE(job)


class Sandboxed:
    """A process started inside the AppContainer, its output read from a pipe."""

    def __init__(self, args: list[str], env: dict[str, str], cwd: Path, job: wintypes.HANDLE,
                 container: Optional[tuple[ctypes.c_void_p, str]] = None, capabilities: tuple[str, ...] = CAPABILITIES,
                 mitigation: int = 0) -> None:
        psid, _ = container or container_sid()
        caps = (SID_AND_ATTRIBUTES * max(len(capabilities), 1))()
        for i, text in enumerate(capabilities):
            cap = ctypes.c_void_p()
            if not advapi.ConvertStringSidToSidW(text, ctypes.byref(cap)):
                raise ctypes.WinError(ctypes.get_last_error())
            caps[i] = SID_AND_ATTRIBUTES(cap, 4)  # SE_GROUP_ENABLED
        sc = SECURITY_CAPABILITIES(psid, caps if capabilities else None, len(capabilities), 0)

        sa = SECURITY_ATTRIBUTES(ctypes.sizeof(SECURITY_ATTRIBUTES), None, True)
        read, write = wintypes.HANDLE(), wintypes.HANDLE()
        if not k32.CreatePipe(ctypes.byref(read), ctypes.byref(write), ctypes.byref(sa), 0):
            raise ctypes.WinError(ctypes.get_last_error())
        k32.SetHandleInformation(read, 1, 0)  # the launcher's end stays out of the child
        nul = wintypes.HANDLE(k32.CreateFileW("NUL", 0x80000000, 3, ctypes.byref(sa), 3, 0, None))
        # Only these two handles are inherited (PROC_THREAD_ATTRIBUTE_HANDLE_LIST), nothing else the launcher holds
        handles = (wintypes.HANDLE * 2)(write, nul)

        listed = [(0x00020009, ctypes.byref(sc), ctypes.sizeof(sc)),  # SECURITY_CAPABILITIES
                  (0x00020002, handles, ctypes.sizeof(handles))]  # HANDLE_LIST
        policy = ctypes.c_uint64(mitigation)
        if mitigation:
            listed.append((0x00020007, ctypes.byref(policy), ctypes.sizeof(policy)))  # MITIGATION_POLICY
        size = ctypes.c_size_t()
        k32.InitializeProcThreadAttributeList(None, len(listed), 0, ctypes.byref(size))
        attrs = ctypes.create_string_buffer(size.value)
        if not k32.InitializeProcThreadAttributeList(attrs, len(listed), 0, ctypes.byref(size)):
            raise ctypes.WinError(ctypes.get_last_error())
        for attr, value, n in listed:
            if not k32.UpdateProcThreadAttribute(attrs, 0, attr, value, n, None, None):
                raise ctypes.WinError(ctypes.get_last_error())

        si = STARTUPINFOEXW()
        si.StartupInfo.cb = ctypes.sizeof(STARTUPINFOEXW)
        si.StartupInfo.dwFlags = 0x100  # STARTF_USESTDHANDLES
        si.StartupInfo.hStdInput, si.StartupInfo.hStdOutput, si.StartupInfo.hStdError = nul, write, write
        si.lpAttributeList = ctypes.cast(attrs, ctypes.c_void_p)
        block = "".join(f"{k}={v}\0" for k, v in sorted(env.items(), key=lambda kv: kv[0].upper())) + "\0"
        cmdline = ctypes.create_unicode_buffer(subprocess.list2cmdline(args))
        pi = PROCESS_INFORMATION()
        flags = 0x80000 | 0x400 | 0x08000000 | 0x4  # EXTENDED_STARTUPINFO, UNICODE_ENVIRONMENT, NO_WINDOW, SUSPENDED
        if not k32.CreateProcessW(args[0], cmdline, None, None, True, flags, ctypes.create_unicode_buffer(block),
                                  str(cwd), ctypes.byref(si), ctypes.byref(pi)):
            raise ctypes.WinError(ctypes.get_last_error())
        k32.CloseHandle(write)
        k32.CloseHandle(nul)
        if not k32.AssignProcessToJobObject(job, pi.hProcess):
            raise ctypes.WinError(ctypes.get_last_error())
        k32.ResumeThread(pi.hThread)
        k32.CloseHandle(pi.hThread)
        self.process, self.pid = pi.hProcess, pi.dwProcessId
        import msvcrt
        self.output = os.fdopen(msvcrt.open_osfhandle(read.value or 0, os.O_RDONLY), "rb")

    def wait(self) -> int:
        k32.WaitForSingleObject(self.process, 0xFFFFFFFF)
        code = wintypes.DWORD()
        k32.GetExitCodeProcess(self.process, ctypes.byref(code))
        k32.CloseHandle(self.process)
        return code.value


def ignis_env(sid: str) -> dict[str, str]:
    folder = container_folder(sid)
    temp = folder / "Temp"
    temp.mkdir(exist_ok=True)
    return {
        # Ignis's settings: https://ignis.thiefling.com/docs/server/environment/
        "PORT": str(PORT),
        "HOST": "127.0.0.1",  # patches/0002-listen-host.patch
        "VAULT_ROOT": str(VAULTS),
        "DATA_ROOT": str(DATA),
        "OBSIDIAN_ASSETS_PATH": str(OBSIDIAN_APP),
        "IGNIS_OBSIDIAN_PIN": (OBSIDIAN_APP / ".obsidian-version").read_text(encoding="utf-8").strip(),
        "IGNORED_PATHS": IGNORED_PATHS,
        # Ignis's proxy may reach 127.0.0.1, which inside the container is only Ignis, cloudflared and the
        # Augmented View forwarder (the container cannot reach this PC's loopback)
        "PROXY_ALLOW_PRIVATE_HOSTS": "127.0.0.1",
        # The WebSocket origin allowlist: this PC, plus the tunnel's hostname once ignis/.env names it
        "WS_ORIGINS": ",".join([f"https://{h}" for h in tunnel_hosts()] + [f"http://localhost:{PORT}"]),
        # The request log: failures with their reason, partial batch-reads and slow requests only; no colour codes
        # (patches/0003-diagnostics.patch). Browser tabs' own reports appear as "client <session> ..." lines.
        "LOG_REQUESTS": "errors",
        "NO_COLOR": "1",
        # the same-origin relay's pipe (patches/0006-relay.patch)
        "IGNIS_LOCAL_RELAY": LOCAL_RELAY_PIPE,
        **({"NODE_EXTRA_CA_CERTS": str(CA_CERT)} if CA_CERT.is_file() else {}),
        "NODE_ENV": "production",
        # What Windows programs expect; profile paths point at the container's own folder
        "SystemRoot": os.environ.get("SystemRoot", r"C:\Windows"),
        "PATH": str(RUNTIME),
        "TEMP": str(temp), "TMP": str(temp),
        "USERPROFILE": str(folder), "LOCALAPPDATA": str(folder), "APPDATA": str(folder),
    }


def tunnel_hosts() -> list[str]:
    host = dotenv().get("IGNIS_HOSTNAME", "")
    return [host] if host and host != "vault.example.com" else []


# The tunnel token lives in Windows Credential Manager (a generic credential, encrypted by Windows for this user on
# this machine; Control Panel -> Credential Manager -> Windows Credentials), not in a file. `set-token` stores it;
# the launcher reads it only to start cloudflared, which gets it as TUNNEL_TOKEN in its environment.
TOKEN_TARGET = f"{NAME}/cloudflared-tunnel-token"


# The tunnel's transport (cloudflared's --protocol): IGNIS_TUNNEL_PROTOCOL, default quic.
#   quic   UDP to Cloudflare's edge on port 7844 (the default, and what earlier versions always used)
#   http2  TLS over TCP on port 7844: for networks that block or disturb UDP. Antivirus that re-signs TLS (HTTPS
#          scanning) breaks it: cloudflared then rejects the edge's certificate, unless cloudflared.exe or
#          *.argotunnel.com is excluded from that scanning
#   auto   cloudflared's own choice: QUIC, falling back to HTTP/2 when QUIC fails
TUNNEL_PROTOCOLS = ("quic", "http2", "auto")


def tunnel_protocol(value: Optional[str]) -> tuple[str, str]:
    """(the protocol, "") from IGNIS_TUNNEL_PROTOCOL (empty: quic), or ("", why) when it is not one of
    TUNNEL_PROTOCOLS; the launcher then does not start."""
    v = (value or "quic").strip().lower()
    if v in TUNNEL_PROTOCOLS:
        return v, ""
    return "", (f"IGNIS_TUNNEL_PROTOCOL={value!r} is not a tunnel protocol: use one of {', '.join(TUNNEL_PROTOCOLS)} "
                f"(in {IGNIS / '.env'} or the environment); the launcher does not start")


def cloudflared_args(protocol: str) -> list[str]:
    """cloudflared's command line, as an argument list (no shell); `protocol` from tunnel_protocol."""
    assert protocol in TUNNEL_PROTOCOLS
    return [str(CLOUDFLARED), "tunnel", "--no-autoupdate", "--protocol", protocol, "--edge-ip-version", "4", "run"]


def tunnel_token() -> str:
    import pywintypes
    import win32cred
    try:
        cred = win32cred.CredRead(TOKEN_TARGET, win32cred.CRED_TYPE_GENERIC)
    except pywintypes.error:
        return ""
    blob = cred["CredentialBlob"]
    return (blob.decode("utf-16-le") if isinstance(blob, bytes) else str(blob)).strip()


def set_token() -> int:
    """Store the tunnel token (typed or pasted at a hidden prompt) in Credential Manager; an empty answer removes it."""
    import getpass
    import pywintypes
    import win32cred
    token = getpass.getpass("Tunnel token (input hidden; Enter alone removes the stored one): ").strip()
    if not token:
        try:
            win32cred.CredDelete(TOKEN_TARGET, win32cred.CRED_TYPE_GENERIC)
            print(f"removed {TOKEN_TARGET}")
        except pywintypes.error:
            print("nothing stored")
        return 0
    win32cred.CredWrite({"Type": win32cred.CRED_TYPE_GENERIC, "TargetName": TOKEN_TARGET, "UserName": "cloudflared",
                         "CredentialBlob": token, "Persist": win32cred.CRED_PERSIST_LOCAL_MACHINE,
                         "Comment": "Cloudflare Tunnel token for Ignis (ignis/ignis_native.py)"}, 0)
    print(f"stored in Credential Manager as {TOKEN_TARGET} ({len(token)} characters); restart the launcher to use it")
    return 0


# --- the Augmented View relay ---
# Augmented View (the Obsidian plugin) ranks phrases with a model server that desktop Obsidian starts on
# 127.0.0.1:<port>. In Ignis the plugin asks for http://127.0.0.1:RELAY_PORT instead (its "Server address" setting,
# set in Ignis: Settings > Augmented View > This device); Ignis's proxy reaches that inside the container
# (PROXY_ALLOW_PRIVATE_HOSTS=127.0.0.1), where ignis/relay/augmented-view-forwarder.js passes each request through a named
# pipe to `relay` below, outside the sandbox, which forwards it to the desktop server. The sandbox cannot reach this
# PC's loopback, and the pipe admits only the container, so this is its one way to a local service; the relay passes
# only the requests in AUGMENTED_VIEW_ALLOWED (never /shutdown, which would stop the server desktop Obsidian is using;
# /stats is the server's read-only GPU and memory readings).
RELAY_PORT = 18790
PIPE = rf"\\.\pipe\{PREFIX}-ignis-augmented-view"
FORWARDER = IGNIS / "relay" / "augmented-view-forwarder.js"
AUGMENTED_VIEW_ALLOWED = {("GET", "/health"), ("GET", "/stats"), ("POST", "/emphasis"), ("POST", "/claims")}
AUGMENTED_VIEW_DEFAULT_PORT = 8790  # the Augmented View server's own default (its --port)


def augmented_view_port() -> int:
    """The port desktop's Augmented View server listens on: IGNIS_AUGMENTED_VIEW_PORT from the launcher's own settings
    (the environment or ignis/.env), else the server's default. Never the plugin's data.json: it is in the vault, which
    the browser can write, so a port read from it could point the relay at any other service on this PC."""
    return checked_port(config("IGNIS_AUGMENTED_VIEW_PORT"), AUGMENTED_VIEW_DEFAULT_PORT)


# Quarry (Gameboard-dev/Quarry): its service on this PC, which desktop Obsidian starts. In the browser Quarry asks
# /relay/quarry/<path> with the service's own token (Authorization: Bearer, which patches/0006-relay.patch passes to
# this service only). The token is the service's lock; this list is the relay's: what a browser may do with the library
# (search, the library and its credibility, exclusions, themes, citation trees, the review's progress and task
# controls, starting or cancelling indexing). Refused: the settings (they hold paths), keys, the GPU hold, stopping the
# service, archiving, and every assistant tool that writes or retrieves (docs/ignis.md in Quarry's repository).
QUARRY_DEFAULT_PORT = 8766  # the service's own default (Settings, Service, Port)
QUARRY_GET = {"/health", "/stats", "/events", "/library", "/exclusions", "/duplicates", "/credibility", "/citekeys",
              "/bib", "/preprints", "/queue", "/stale", "/models", "/skills", "/hardware/recommend", "/zotero/ping",
              "/zotero/check", "/themes", "/themes/"}
QUARRY_POST = {"/search", "/similar", "/connections", "/citation-tree", "/exclusions", "/credibility/override", "/queue",
               "/queue/cancel", "/themes/rebuild", "/themes/cancel"}
# the assistant's tools the review pane uses that only read, or pause, resume or stop a task in the review's ledger
QUARRY_TOOLS = {"review_open", "review_progress", "list_tasks", "task_control", "retrieval_status"}


def quarry_port() -> int:
    """The port of Quarry's service: IGNIS_QUARRY_PORT from the launcher's own settings (the environment or
    ignis/.env), else the service's default; never the vault's data.json, for the reason augmented_view_port gives."""
    return checked_port(config("IGNIS_QUARRY_PORT"), QUARRY_DEFAULT_PORT)


def quarry_allows(method: str, path: str) -> bool:
    """Whether a browser may make this request of Quarry's service (QUARRY_GET, QUARRY_POST, QUARRY_TOOLS; a theme by
    its number)."""
    if method == "GET":
        return path in QUARRY_GET or (path.startswith("/themes/") and path[len("/themes/"):].isdigit()
                                      and path[len("/themes/"):].isascii())
    if method == "POST":
        tool = path[len("/assistant/"):] if path.startswith("/assistant/") else None
        return path in QUARRY_POST or tool in QUARRY_TOOLS
    return False


def quarry_queue(body: Any) -> Any:
    """POST /queue's body without `vault` and `config_dir`: a request from the browser may start a task, never point
    the service at another folder (the vault every new note and every assistant tool writes to)."""
    if not isinstance(body, dict):
        raise ValueError("the body is not a JSON object")
    return {k: v for k, v in body.items() if k not in ("vault", "config_dir")}


def checked_port(value: Any, default: int) -> int:
    """A port from a settings file, or the default when it is not one a service of ours would use."""
    try:
        port = int(value)
    except (TypeError, ValueError):
        return default
    return port if 1024 <= port <= 65535 and port not in (PORT, RELAY_PORT) else default


# --- the LaTeX build, asked for from the browser ---
# When the vault is edited in Ignis and Obsidian is not open on this PC (which would build it itself), the LaTeX plugin
# in the browser asks <page origin>/relay/latex/compile. The build is ONE fixed command (latexmk with LuaLaTeX, biber
# and makeglossaries; no latexmkrc, no shell escape; nothing from the request is passed on), run in an AppContainer of
# its own (LATEX_CONTAINER) that may read TinyTeX and read and write the vault's LaTeX/compiled folder, and nothing
# else: no other part of the vault, none of the user's files, no network. TeX resolves every folder on a path, which an
# AppContainer cannot do above its own folders, so TinyTeX, the build folder and the container's folder are reached
# through drive letters made for the build (subst) and removed after it. The steps are LuaLaTeX, biber, makeglossaries
# and LuaLaTeX twice; biber alone runs outside the container (its executable cannot start in one), after main.bcf's
# data sources are checked to be .bib files of the build folder, with no configuration file. A request must carry a valid Cloudflare Access
# token (Cf-Access-Jwt-Assertion, signed by the team's key, for this application's AUD, unexpired, from an allowed
# e-mail address): without the three settings in ignis/.env, or without a token (a request made on this PC), nothing
# is built. One build at a time; one that runs past LATEX_LIMIT seconds is stopped.

LATEX_CONTAINER = f"{PREFIX}.latex"
LATEX_LIMIT = 600.0
LATEX_DIR = VAULT / "LaTeX" / "compiled"  # the LaTeX plugin's default notes folder, LaTeX, and its output folder
LATEX_LOG = ".ignis-build.log"
# TinyTeX's own default location, else IGNIS_TINYTEX
TINYTEX = Path(config("IGNIS_TINYTEX", str(Path(os.environ.get("APPDATA", str(Path.home()))) / "TinyTeX")))
LATEX: dict[str, Any] = {"running": False, "last": None}
_LATEX_LOCK = threading.Lock()
_LATEX_SID: Optional[tuple[ctypes.c_void_p, str]] = None


def latex_sid() -> tuple[ctypes.c_void_p, str]:
    global _LATEX_SID
    with _SID_LOCK:
        if _LATEX_SID is None:
            _LATEX_SID = _lookup_container_sid(LATEX_CONTAINER, "Ignis LaTeX build", "Builds the vault's LaTeX document")
        return _LATEX_SID


def latex_ready() -> Optional[str]:
    """Why a build cannot run, or None: TinyTeX present, the build folder inside the vault, the access rules in place."""
    if not all((TINYTEX / "bin" / "windows" / exe).is_file() for exe in ("lualatex.exe", "biber.exe", "makeglossaries.exe")):
        return f"no TinyTeX at {TINYTEX}"
    folder = LATEX_DIR.resolve()
    if VAULT not in folder.parents or not (folder / "main.tex").is_file():
        return "the build folder is not the vault's LaTeX/compiled, or it has no main.tex"
    return None


def latex_setup() -> None:
    """The build container's two access rules (idempotent): read TinyTeX, read and write LaTeX/compiled."""
    _, sid = latex_sid()
    grant(TINYTEX, sid, "RX", quiet=True)
    grant(LATEX_DIR, sid, "M", quiet=True)


def access_config() -> Optional[tuple[str, str, set[str]]]:
    """Cloudflare Access: the team's domain, the application's AUD tag and the e-mail addresses allowed to build."""
    e = dotenv()
    team = access_team(e.get("IGNIS_ACCESS_TEAM", ""))
    aud = e.get("IGNIS_ACCESS_AUD", "").strip()
    emails = {m.strip().lower() for m in e.get("IGNIS_ACCESS_EMAILS", "").split(",") if m.strip()}
    if not team or not aud or not emails:
        return None
    return team, aud, emails


def access_team(value: str) -> str:
    """The team's domain from IGNIS_ACCESS_TEAM, given as the bare team name ("myteam") or its domain
    ("myteam.cloudflareaccess.com", with or without https:// and a trailing slash); "" when it is neither."""
    team = value.strip().lower().removeprefix("https://").strip("/")
    if "." not in team:
        team += ".cloudflareaccess.com"
    name, _, domain = team.partition(".")
    ok = domain == "cloudflareaccess.com" and name and all(c.isascii() and (c.isalnum() or c == "-") for c in name)
    return team if ok else ""


_CERTS: dict[str, Any] = {"at": 0.0, "team": "", "keys": {}}


def access_keys(team: str) -> dict[str, tuple[int, int]]:
    """The team's signing keys (RSA n, e by key id), from Cloudflare, kept for an hour."""
    import base64
    import urllib.request
    if _CERTS["team"] == team and time.time() - _CERTS["at"] < 3600 and _CERTS["keys"]:
        return _CERTS["keys"]
    with urllib.request.urlopen(f"https://{team}/cdn-cgi/access/certs", timeout=10) as r:
        data = json.loads(r.read())
    b = lambda t: int.from_bytes(base64.urlsafe_b64decode(t + "=" * (-len(t) % 4)), "big")
    keys = {k["kid"]: (b(k["n"]), b(k["e"])) for k in data.get("keys", []) if k.get("kty") == "RSA"}
    _CERTS.update(at=time.time(), team=team, keys=keys)
    return keys


def access_email(token: str) -> str:
    """The e-mail address of a valid Cloudflare Access token for this application, or ValueError saying why not.
    RS256 is checked here (PKCS#1 v1.5 over SHA-256, the RSA operation in Python's integers; no package needed)."""
    import base64
    import hashlib
    import hmac
    cfg = access_config()
    if cfg is None:
        raise ValueError("Cloudflare Access is not set up for builds: IGNIS_ACCESS_TEAM, IGNIS_ACCESS_AUD and IGNIS_ACCESS_EMAILS in ignis/.env")
    team, aud, emails = cfg
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("no Cloudflare Access token (a build is asked for only through the tunnel)")
    d = lambda t: base64.urlsafe_b64decode(t + "=" * (-len(t) % 4))
    head, claims, sig = json.loads(d(parts[0])), json.loads(d(parts[1])), d(parts[2])
    if head.get("alg") != "RS256":
        raise ValueError("token not signed with RS256")
    key = access_keys(team).get(head.get("kid", ""))
    if key is None:
        _CERTS["at"] = 0.0  # a rotated key: fetched again next time
        raise ValueError("token signed with an unknown key")
    n, e = key
    k = (n.bit_length() + 7) // 8
    if len(sig) != k:
        raise ValueError("bad signature length")
    em = pow(int.from_bytes(sig, "big"), e, n).to_bytes(k, "big")
    digest_info = bytes.fromhex("3031300d060960864801650304020105000420") + hashlib.sha256(f"{parts[0]}.{parts[1]}".encode()).digest()
    expected = b"\x00\x01" + b"\xff" * (k - len(digest_info) - 3) + b"\x00" + digest_info
    if not hmac.compare_digest(em, expected):
        raise ValueError("bad signature")
    now = time.time()
    auds = claims.get("aud", [])
    auds = [auds] if isinstance(auds, str) else auds
    if aud not in auds:
        raise ValueError("token for another application")
    if claims.get("iss") != f"https://{team}":
        raise ValueError("token from another team")
    if not (float(claims.get("exp", 0)) > now and float(claims.get("nbf", claims.get("iat", now))) <= now + 60):
        raise ValueError("token expired or not yet valid")
    email = str(claims.get("email", "")).lower()
    if email not in emails:
        raise ValueError("this account may not build")
    return email


def desktop_obsidian_open() -> bool:
    """Whether Obsidian runs on this PC (its LaTeX plugin then builds the document itself)."""
    r = subprocess.run([str(SYSTEM32 / "tasklist.exe"), "/FI", "IMAGENAME eq Obsidian.exe", "/NH", "/FO", "CSV"], capture_output=True, text=True, creationflags=NO_WINDOW)
    return "obsidian.exe" in r.stdout.lower()


def free_letters(n: int) -> list[str]:
    """Drive letters not in use, from the end of the alphabet."""
    used = {d[0].upper() for d in os.listdrives()} if hasattr(os, "listdrives") else {chr(c) for c in range(65, 91) if os.path.exists(f"{chr(c)}:\\")}
    free = [c for c in "ZYXWVUTSRQPONM" if c not in used]
    if len(free) < n:
        raise OSError("no free drive letters for the build")
    return [f"{c}:" for c in free[:n]]


def bcf_sources(folder: Path) -> list[str]:
    """The data sources main.bcf names, if each is a plain .bib file name in the build folder (no path, no URL, no
    other kind); else ValueError. biber reads exactly these, outside the sandbox."""
    import xml.etree.ElementTree as ET
    root = ET.parse(folder / "main.bcf").getroot()
    out = []
    for el in root.iter():
        if not el.tag.endswith("datasource"):
            continue
        name = (el.text or "").strip()
        if el.get("type", "file") != "file" or el.get("datatype", "bibtex") != "bibtex":
            raise ValueError(f"main.bcf asks for a data source of another kind: {el.get('type')}/{el.get('datatype')}")
        if not name.lower().endswith(".bib") or any(c in name for c in "/\\:") or ".." in name or not (folder / name).is_file():
            raise ValueError(f"main.bcf names a data source outside the build folder or not a .bib file: {name!r}")
        out.append(name)
    return out


def highlight_code(build: Path) -> bytes:
    """The code listings highlighted, as latexmkrc and the plugin's highlight command do on the desktop (a browser
    cannot run Pygments, and this build reads no latexmkrc): each code/<name>.<ext> whose code/<name>.tex is missing
    or older becomes a Pygments LaTeX Verbatim block, and code/pygments-style.tex holds the 'default' style's colours.
    In this process, through Pygments' own API: no program is started and the code is only read, never run. Returns a
    line for the build's transcript."""
    code = build / "code"
    if not code.is_dir():
        return b""
    try:
        from pygments import highlight
        from pygments.formatters import LatexFormatter
        from pygments.lexers import get_lexer_for_filename
        from pygments.util import ClassNotFound
    except ImportError:
        return b"\n===== highlighting: Pygments is not installed for the launcher's Python; listings left as they were\n"
    done, skipped = [], []
    formatter = LatexFormatter(style="default")
    for src in sorted(p for p in code.iterdir() if p.is_file() and p.suffix and p.suffix.lower() != ".tex"):
        out = src.with_suffix(".tex")
        if out.exists() and out.stat().st_mtime >= src.stat().st_mtime:
            continue
        try:
            lexer = get_lexer_for_filename(src.name)
        except ClassNotFound:
            skipped.append(src.name)
            continue
        out.write_text(highlight(src.read_text(encoding="utf-8", errors="replace"), lexer, formatter), encoding="utf-8")
        done.append(src.name)
    (code / "pygments-style.tex").write_text(formatter.get_style_defs(), encoding="utf-8")
    line = f"\n===== highlighting: {len(done)} listing(s) highlighted" + (f"; no lexer for {', '.join(skipped)}" if skipped else "") + "\n"
    return line.encode()


def latex_build(email: str) -> None:
    """One build: LuaLaTeX, biber, makeglossaries, LuaLaTeX twice; its output to LaTeX/compiled/.ignis-build.log, its
    result in LATEX["last"]. Every step but biber runs in the LaTeX container."""
    t0 = time.time()
    deadline = t0 + LATEX_LIMIT
    result: dict[str, Any] = {"by": email, "started": datetime.now().isoformat(timespec="seconds")}
    letters: list[str] = []
    transcript: list[bytes] = []
    try:
        latex_setup()
        container = latex_sid()
        folder = container_folder(container[1])
        (folder / "Temp").mkdir(exist_ok=True)
        build = LATEX_DIR.resolve()
        letters = free_letters(3)
        tex, work, own = letters
        for letter, target in ((tex, TINYTEX), (work, build), (own, folder)):
            subprocess.run([str(SYSTEM32 / "subst.exe"), letter, str(target)], check=True, capture_output=True, creationflags=NO_WINDOW)
        env = {"SystemRoot": os.environ.get("SystemRoot", r"C:\Windows"), "WINDIR": os.environ.get("WINDIR", r"C:\Windows"),
               "SystemDrive": os.environ.get("SystemDrive", "C:"), "PATHEXT": ".COM;.EXE;.BAT;.CMD", "PATH": f"{tex}\\bin\\windows",
               "TEMP": f"{own}\\Temp", "TMP": f"{own}\\Temp", "USERPROFILE": f"{own}\\", "HOME": f"{own}\\", "APPDATA": f"{own}\\",
               "LOCALAPPDATA": f"{own}\\", "USERNAME": "latexbuild", "TEXMFVAR": f"{own}\\texmf-var", "TEXMFCONFIG": f"{own}\\texmf-config",
               "TEXMFHOME": f"{own}\\texmf-home"}

        def sandboxed(label: str, args: list[str]) -> int:
            if time.time() > deadline:
                raise TimeoutError(f"the build ran past {LATEX_LIMIT:.0f} s")
            job = kill_on_close_job()
            p = Sandboxed(args, env, Path(f"{work}\\"), job, container=container, capabilities=())
            timer = threading.Timer(max(deadline - time.time(), 1.0), lambda: k32.TerminateJobObject(job, 1))
            timer.start()
            out = p.output.read()
            code = p.wait()
            timer.cancel()
            k32.CloseHandle(job)
            transcript.append(f"\n===== {label}: exit {code}\n".encode() + out)
            return code

        transcript.append(highlight_code(build))
        lualatex = [f"{tex}\\bin\\windows\\lualatex.exe", "--no-shell-escape", "--interaction=nonstopmode", "--file-line-error", "--synctex=1", "main.tex"]
        sandboxed("lualatex", lualatex)
        if (build / "main.bcf").is_file():
            bcf_sources(build)  # refuses before biber runs
            # outside the sandbox (see above): fixed arguments, no configuration file, the build folder only
            r = subprocess.run([str(TINYTEX / "bin" / "windows" / "biber.exe"), "--noconf", "--input-directory", str(build),
                                "--output-directory", str(build), "main"], cwd=str(folder), capture_output=True,
                               timeout=max(deadline - time.time(), 1.0), creationflags=NO_WINDOW)
            transcript.append(f"\n===== biber: exit {r.returncode}\n".encode() + r.stdout + r.stderr)
        if (build / "main.glo").is_file() or (build / "main.acn").is_file():
            sandboxed("makeglossaries", [f"{tex}\\bin\\windows\\makeglossaries.exe", "main"])
        sandboxed("lualatex (2)", lualatex)
        code = sandboxed("lualatex (3)", lualatex)
        log_text = (build / "main.log").read_text("utf-8", "replace") if (build / "main.log").is_file() else ""
        errors = [l for l in log_text.splitlines() if l.startswith("!") or (".tex:" in l and "rror" in l)][:20]
        undefined = sum(1 for l in log_text.splitlines() if "undefined on input line" in l)
        result.update(ok=code == 0 and not errors, exit=code, errors=errors, undefined=undefined)
    except Exception as e:  # noqa: BLE001: the reason goes to the browser and the log
        result.update(ok=False, exit=None, errors=[f"the build could not run: {e}"])
    finally:
        for letter in letters:
            subprocess.run([str(SYSTEM32 / "subst.exe"), letter, "/d"], capture_output=True, creationflags=NO_WINDOW)
        try:
            (LATEX_DIR / LATEX_LOG).write_bytes(b"".join(transcript))
        except OSError:
            pass
        result["seconds"] = round(time.time() - t0, 1)
        log(f"latex build for {email}: {'ok' if result.get('ok') else 'failed'} in {result['seconds']} s")
        with _LATEX_LOCK:
            LATEX.update(running=False, last=result)


def latex_relay(conn: "PipeConnection", method: str, own: str, headers: list[str]) -> None:
    """GET /latex/status, POST /latex/compile: each with a valid Cloudflare Access token, else refused."""
    def answer(status: str, body: dict[str, Any]) -> None:
        data = json.dumps(body).encode()
        conn.write(f"HTTP/1.1 {status}\r\nContent-Type: application/json\r\nContent-Length: {len(data)}\r\nConnection: close\r\n\r\n".encode() + data)
        conn.close()

    token = next((h.split(":", 1)[1].strip() for h in headers if h.lower().startswith("cf-access-jwt-assertion:")), "")
    try:
        email = access_email(token)
    except Exception as e:  # noqa: BLE001
        log(f"relay: latex refused ({e})")
        return answer("403 Forbidden", {"error": str(e)})
    if method == "GET" and own == "/status":
        with _LATEX_LOCK:
            state = dict(LATEX)
        return answer("200 OK", {**state, "available": latex_ready() is None, "why": latex_ready(), "desktop_open": desktop_obsidian_open()})
    if method == "POST" and own == "/compile":
        why = latex_ready()
        if why:
            return answer("503 Service Unavailable", {"error": why})
        if desktop_obsidian_open():
            return answer("409 Conflict", {"error": "Obsidian is open on the PC: its LaTeX plugin builds the document itself"})
        with _LATEX_LOCK:
            if LATEX["running"]:
                return answer("409 Conflict", {"error": "a build is running"})
            LATEX["running"] = True
        threading.Thread(target=latex_build, args=(email,), daemon=True).start()
        return answer("202 Accepted", {"started": True})
    return answer("404 Not Found", {"error": f"{method} /latex{own} is not a build request"})


# --- the same-origin relay (patches/0006-relay.patch) ---
# A plugin in the browser asks <page origin>/relay/<service>/<path>; Ignis's server streams it through LOCAL_RELAY_PIPE
# (its name passed in IGNIS_LOCAL_RELAY) to `relay` below, which passes only the requests in that service's list to
# the service's port on this PC. Everything else is refused, including any request that would change a service's
# settings or stop it. `/relay/latex/...` is not forwarded: the launcher answers it itself (latex_relay above).
LOCAL_RELAY_PIPE = rf"\\.\pipe\{PREFIX}-ignis-relay"


# service -> (its port, which requests pass)
SERVICES: dict[str, tuple[Callable[[], int], Callable[[str, str], bool]]] = {
    "augmented-view": (augmented_view_port, lambda m, p: (m, p) in AUGMENTED_VIEW_ALLOWED),
    "quarry": (quarry_port, quarry_allows),
}
# (service, method, path) -> the JSON body as the service receives it: a request whose body must be read before it
# passes (at most BODY_LIMIT bytes, with a Content-Length), so that a field the browser must not set is taken out
BODY_FILTERS: dict[tuple[str, str, str], Callable[[Any], Any]] = {
    ("quarry", "POST", "/queue"): quarry_queue,
}
BODY_LIMIT = 1 << 20
# Other services on this PC that no relayed service's requests may be sent to (the relayed services' own ports are
# checked against each other as well): Ignis itself and the forwarder in the sandbox.
OTHER_PORTS = {"Ignis": PORT, "the Augmented View forwarder": RELAY_PORT}


def destination(service: str) -> tuple[Optional[int], str]:
    """The port a relayed service's requests go to, or None and why: refused when the port is another known
    service's (a mistaken or altered setting must not send one service's allowed requests to another)."""
    entry = SERVICES.get(service)
    if entry is None:
        return None, f"no relayed service {service!r}"
    port = entry[0]()
    others = {**OTHER_PORTS, **{name: other() for name, (other, _) in SERVICES.items() if name != service}}
    clash = next((name for name, p in others.items() if p == port), None)
    if clash is not None:
        return None, (f"{service}'s port {port} is also {clash}'s: nothing is relayed to it (check "
                      f"IGNIS_AUGMENTED_VIEW_PORT in ignis/.env and the services' own port settings)")
    return port, ""


def route_augmented_view(method: str, path: str) -> tuple[Optional[tuple[int, str]], str]:
    """The old pipe (augmented-view-forwarder.js): paths are Augmented View's own."""
    if (method, path.split("?")[0]) not in AUGMENTED_VIEW_ALLOWED:
        return None, f"{method} {path.split('?')[0]} is not relayed"
    port, why = destination("augmented-view")
    if port is None:
        return None, why
    return (port, path), ""


def route_local(method: str, path: str) -> tuple[Optional[tuple[int, str]], str]:
    """The same-origin relay's pipe: /<service>/<the service's own path>."""
    service, _, rest = path.lstrip("/").partition("/")
    entry = SERVICES.get(service)
    if entry is None:
        return None, f"no relayed service {service!r}"
    _, allows = entry
    own = "/" + rest
    bare = own.split("?")[0]
    if ".." in bare or "//" in bare or not allows(method, bare):
        return None, f"{method} /{service}{bare} is not relayed"
    port, why = destination(service)
    if port is None:
        return None, why
    return (port, own), ""


class PipeConnection:
    """One client of the relay's pipe, read and written with overlapped I/O (so both directions can run at once)."""

    def __init__(self, handle: object) -> None:
        import win32event
        self.h = handle
        self.read_event = win32event.CreateEvent(None, True, False, None)
        self.write_event = win32event.CreateEvent(None, True, False, None)

    def read(self) -> bytes:
        import pywintypes
        import win32file
        ov = pywintypes.OVERLAPPED()
        ov.hEvent = self.read_event
        buf = win32file.AllocateReadBuffer(65536)
        try:
            win32file.ReadFile(self.h, buf, ov)
            n = win32file.GetOverlappedResult(self.h, ov, True)
        except pywintypes.error:
            return b""  # the client has gone
        return bytes(buf[:n])

    def write(self, data: bytes) -> bool:
        import pywintypes
        import win32file
        ov = pywintypes.OVERLAPPED()
        ov.hEvent = self.write_event
        try:
            win32file.WriteFile(self.h, data, ov)
            win32file.GetOverlappedResult(self.h, ov, True)
            return True
        except pywintypes.error:
            return False

    def close(self) -> None:
        import pywintypes
        import win32file
        import win32pipe
        try:
            win32file.FlushFileBuffers(self.h)
            win32pipe.DisconnectNamedPipe(self.h)
        except pywintypes.error:
            pass
        self.h.Close()  # type: ignore[attr-defined]


def http_error(status: str, message: str) -> bytes:
    body = json.dumps({"error": message}).encode()
    return (f"HTTP/1.1 {status}\r\nContent-Type: application/json\r\nContent-Length: {len(body)}\r\n"
            "Connection: close\r\n\r\n").encode() + body


Route = Callable[[str, str], tuple[Optional[tuple[int, str]], str]]


def filtered_body(conn: PipeConnection, headers: list[str], rest: bytes, body_filter: Callable[[Any], Any]) -> tuple[Optional[bytes], str]:
    """The whole request body (its Content-Length, at most BODY_LIMIT; no chunked encoding), read as JSON and put
    through `body_filter`; or None and why."""
    lengths = [h.split(":", 1)[1].strip() for h in headers if h.lower().startswith("content-length:")]
    if any(h.lower().startswith("transfer-encoding:") for h in headers) or len(lengths) != 1 or not lengths[0].isdigit():
        return None, "this request needs a single Content-Length (no chunked body)"
    length = int(lengths[0])
    if length > BODY_LIMIT:
        return None, f"the body is larger than {BODY_LIMIT} bytes"
    body = rest
    while len(body) < length:
        chunk = conn.read()
        if not chunk:
            return None, "the body ended early"
        body += chunk
    try:
        out = body_filter(json.loads(body[:length].decode("utf-8")))
    except (ValueError, UnicodeDecodeError) as e:
        return None, f"the body is not JSON for this request ({e})"
    return json.dumps(out).encode("utf-8"), ""


def relay_one(conn: PipeConnection, route: Route = route_augmented_view) -> None:
    """One request: `route` says whether it passes and to which port and path; the request goes to that service on
    this PC and the answer streams back."""
    import socket
    head = b""
    while b"\r\n\r\n" not in head and len(head) < 65536:
        chunk = conn.read()
        if not chunk:
            conn.close()
            return
        head += chunk
    lines, _, rest = head.partition(b"\r\n\r\n")
    request_line, *headers = lines.decode("latin-1").split("\r\n")
    parts = request_line.split(" ")
    method, target = (parts[0], parts[1]) if len(parts) == 3 else ("", "")
    path = target.split("?")[0]
    if route is route_local and target.startswith("/latex/"):
        latex_relay(conn, method, path[len("/latex"):], headers)
        return
    where, why = route(method, target) if method else (None, "not an HTTP request")
    if where is None:
        log(f"relay: refused {method} {path}: {why}")
        relay_counted("refused", f"{method} {path}")
        conn.write(http_error("403 Forbidden", why))
        conn.close()
        return
    port, own = where
    service = target.lstrip("/").partition("/")[0] if route is route_local else ""
    body_filter = BODY_FILTERS.get((service, method, own.split("?")[0]))
    if body_filter is not None:
        filtered, why = filtered_body(conn, headers, rest, body_filter)
        if filtered is None:
            log(f"relay: refused {method} {path}: {why}")
            relay_counted("refused", f"{method} {path}")
            conn.write(http_error("400 Bad Request", why))
            conn.close()
            return
        headers = [h for h in headers if not h.lower().startswith("content-length:")] + [f"Content-Length: {len(filtered)}"]
        rest = filtered
    request_line = f"{method} {own} HTTP/1.1"
    # One request per connection: the server closes after answering, which ends both directions
    # the Origin was checked by Ignis's server (WS_ORIGINS) before the request reached the pipe; it is dropped, so the
    # services' own check (requests naming a foreign web origin are refused) lets the relay's requests through
    headers = [h for h in headers if not h.lower().startswith(("connection:", "host:", "origin:"))] + [f"Host: 127.0.0.1:{port}", "Connection: close"]
    try:
        sock = socket.create_connection(("127.0.0.1", port), timeout=5)
    except OSError:
        relay_counted("unavailable", f"{method} {path}")
        conn.write(http_error("502 Bad Gateway", f"nothing answers on port {port} for {path} (is the service running in desktop Obsidian?)"))
        conn.close()
        return
    sock.settimeout(None)
    relay_counted("passed", f"{method} {path}")

    def upload() -> None:  # the rest of the request body, if any (none left when a filter read it all)
        while body_filter is None and (chunk := conn.read()):
            try:
                sock.sendall(chunk)
            except OSError:
                return

    try:
        sock.sendall("\r\n".join([request_line, *headers]).encode("latin-1") + b"\r\n\r\n" + rest)
        threading.Thread(target=upload, daemon=True).start()
        while data := sock.recv(65536):
            if not conn.write(data):
                break
    except OSError:
        pass
    finally:
        sock.close()
        conn.close()


def relay(sid: str, pipe: str = PIPE, route: Route = route_augmented_view) -> None:
    """Serve `pipe` to the container only, one thread per connection, each request checked by `route`."""
    import pywintypes
    import win32event
    import win32file
    import win32pipe
    import win32security
    # SYSTEM and the owner: everything; the container: read and write. The low integrity label lets the container
    # (which runs at low integrity) write to the pipe; without it Windows' no-write-up rule would refuse it.
    sd = win32security.ConvertStringSecurityDescriptorToSecurityDescriptor(
        f"D:P(A;;GA;;;SY)(A;;GA;;;OW)(A;;GRGW;;;{sid})S:(ML;;NW;;;LW)", win32security.SDDL_REVISION_1)
    sa = pywintypes.SECURITY_ATTRIBUTES()
    sa.SECURITY_DESCRIPTOR = sd
    if pipe == PIPE:
        log(f"relay: {pipe} -> 127.0.0.1:{augmented_view_port()} ({', '.join(f'{m} {p}' for m, p in sorted(AUGMENTED_VIEW_ALLOWED))})")
    else:
        log(f"relay: {pipe} -> " + "; ".join(f"/relay/{name} -> 127.0.0.1:{port()}" for name, (port, _) in SERVICES.items()))
    while True:
        h = win32pipe.CreateNamedPipe(
            pipe, win32pipe.PIPE_ACCESS_DUPLEX | win32file.FILE_FLAG_OVERLAPPED,
            win32pipe.PIPE_TYPE_BYTE | win32pipe.PIPE_READMODE_BYTE | win32pipe.PIPE_WAIT | 0x8,  # 0x8: REJECT_REMOTE_CLIENTS
            win32pipe.PIPE_UNLIMITED_INSTANCES, 65536, 65536, 0, sa)
        ov = pywintypes.OVERLAPPED()
        ov.hEvent = win32event.CreateEvent(None, True, False, None)
        rc = win32pipe.ConnectNamedPipe(h, ov)
        if rc == 997:  # ERROR_IO_PENDING: wait for a client
            win32event.WaitForSingleObject(ov.hEvent, win32event.INFINITE)
        threading.Thread(target=relay_one, args=(PipeConnection(h), route), daemon=True).start()


# --- live status (read by the Ignis Control plugin) ---
# Every STATUS_EVERY seconds the launcher writes STATUS_FILE: its own pid and start, each process it supervises (pid,
# state, restarts, last exit, CPU and memory), the tunnel's live connections (from cloudflared's "Registered" and
# "terminated" lines), the relay's counts, and the settings in force. A file older than a few seconds means the
# launcher is not running.
STATUS_FILE = IGNIS / "status.json"
STATUS_EVERY = 2.0
STARTED = time.time()
PROCS: dict[str, dict[str, Any]] = {}  # name -> pid, state, started, restarts, last_exit, last_exit_at, last_line
TUNNEL: dict[str, str] = {}  # cloudflared connIndex -> edge location
TUNNEL_IN_USE = {"protocol": ""}  # the protocol cloudflared was started with (status.json)
RELAY_COUNTS: dict[str, Any] = {"passed": 0, "refused": 0, "unavailable": 0, "last": "", "last_at": 0.0}
STATUS_LOCK = threading.Lock()


def observe(name: str, line: str) -> None:
    """Keep the status in step with a process's output."""
    import re
    with STATUS_LOCK:
        PROCS[name]["last_line"] = line[-200:]
        if name != "cloudflared":
            return
        if m := re.search(r"Registered tunnel connection connIndex=(\d+).*?location=(\S+)", line):
            TUNNEL[m.group(1)] = m.group(2)
        elif m := re.search(r"(?:Connection terminated|Unregistered tunnel connection).*?connIndex=(\d+)", line):
            TUNNEL.pop(m.group(1), None)


def relay_counted(kind: str, request: str) -> None:
    with STATUS_LOCK:
        RELAY_COUNTS[kind] = int(RELAY_COUNTS[kind]) + 1
        RELAY_COUNTS["last"], RELAY_COUNTS["last_at"] = f"{kind}: {request}", time.time()


def server_settings() -> dict[str, Any]:
    try:
        settings: dict[str, Any] = json.loads((DATA / "server-settings.json").read_text(encoding="utf-8"))
        return settings
    except (OSError, ValueError):
        return {}


def write_status() -> None:
    """Write STATUS_FILE every STATUS_EVERY seconds (atomically: a reader never sees half a file)."""
    import psutil
    handles: dict[int, psutil.Process] = {}
    me = psutil.Process()
    while True:
        procs: dict[str, Any] = {}
        with STATUS_LOCK:
            snapshot = {name: dict(p) for name, p in PROCS.items()}
            tunnel = dict(TUNNEL)
            relay_counts = dict(RELAY_COUNTS)
            access = dict(ACCESS)
        for name, p in snapshot.items():
            pid = p.get("pid")
            if p.get("state") == "running" and pid:
                try:
                    h = handles.setdefault(pid, psutil.Process(pid))
                    p["cpu_percent"] = round(h.cpu_percent(), 1)  # since the previous reading
                    p["memory_mb"] = round(h.memory_info().rss / 1048576, 1)
                except psutil.Error:
                    pass
            procs[name] = p
        status = {
            "updated": time.time(),
            "launcher": {"pid": os.getpid(), "started": STARTED, "memory_mb": round(me.memory_info().rss / 1048576, 1)},
            "processes": procs,
            "tunnel": {"connections": len(tunnel), "edges": sorted(tunnel.values()), "protocol": TUNNEL_IN_USE["protocol"]},
            "relay": relay_counts,
            "access": access,
            "url": f"https://{tunnel_hosts()[0]}" if tunnel_hosts() else "",
            "settings": server_settings(),
            "log": str(LOG),
            "container": NAME,
        }
        tmp = STATUS_FILE.with_suffix(".tmp")
        try:
            tmp.write_text(json.dumps(status, indent=1), encoding="utf-8")
            os.replace(tmp, STATUS_FILE)
        except OSError:
            pass
        time.sleep(STATUS_EVERY)


def supervise(name: str, args: list[str], env: dict[str, str], cwd: Path, job: wintypes.HANDLE) -> None:
    """Run one process in the container, copy its output to the log, restart it when it exits (backing off to 5
    minutes while it keeps failing)."""
    backoff = 2.0
    with STATUS_LOCK:
        PROCS[name] = {"state": "starting", "pid": None, "started": None, "restarts": 0, "last_exit": None,
                       "last_exit_at": None, "last_line": ""}
    while True:
        started = time.time()
        try:
            p = Sandboxed(args, env, cwd, job)
            log(f"started {name} in AppContainer {NAME} (pid {p.pid})")
            with STATUS_LOCK:
                PROCS[name].update(state="running", pid=p.pid, started=started)
            for line in p.output:
                text = line.decode("utf-8", "replace").rstrip()
                log(f"  [{name}] " + text)
                observe(name, text)
            code = p.wait()
            log(f"{name} exited with code {code}")
            with STATUS_LOCK:
                PROCS[name].update(state="restarting", pid=None, last_exit=code, last_exit_at=time.time())
                if name == "cloudflared":
                    TUNNEL.clear()
        except Exception as e:  # a failed start must not end the thread silently (2026-10-23: the tunnel never came up)
            log(f"{name} could not be started: {e!r}; retrying")
            with STATUS_LOCK:
                PROCS[name].update(state="failed to start", pid=None, last_exit=repr(e), last_exit_at=time.time())
        with STATUS_LOCK:
            PROCS[name]["restarts"] += 1
        backoff = 2.0 if time.time() - started > 60 else min(backoff * 2, 300)
        time.sleep(backoff)


# Where this installation is, for the Ignis Control plugin on this PC: per user and outside the vault, so no folder or
# program path travels in the vault's shared plugin settings (which any device, or the browser, can write). Rewritten
# at every start, so it follows the folder if it moves.
LOCATION_FILE = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "Ignis Control" / "location.json"


def write_location() -> None:
    # python.exe (Ignis Control starts pythonw.exe beside it, which opens no window), whichever of the two runs this
    python = Path(sys.executable).with_name("python.exe")
    data = {"ignis_dir": str(IGNIS), "python": str(python if python.exists() else Path(sys.executable)), "written": time.time()}
    try:
        LOCATION_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = LOCATION_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, LOCATION_FILE)
    except OSError as e:
        log(f"could not write {LOCATION_FILE} (Ignis Control finds the Ignis folder there): {e}")


def run() -> int:
    import win32api
    import win32event
    import winerror
    mutex = win32event.CreateMutex(None, False, f"Local\\{PREFIX}-ignis-native")  # held for the launcher's lifetime
    if win32api.GetLastError() == winerror.ERROR_ALREADY_EXISTS:
        print("Ignis is already running")
        return 1
    trim_log()
    write_location()
    job = kill_on_close_job()
    _, sid = container_sid()
    env = ignis_env(sid)
    workers = [threading.Thread(target=supervise, daemon=True, args=(
        "ignis", [str(NODE), str(APP / "apps" / "ignis-server" / "server" / "index.js")], env, APP, job))]
    if dotenv().get("TUNNEL_TOKEN"):
        log("ignis/.env has a TUNNEL_TOKEN line: it is ignored; store the token with `set-token` and delete the line")
    token = tunnel_token()
    protocol, why = tunnel_protocol(config("IGNIS_TUNNEL_PROTOCOL"))
    if why:
        log(why)
        print(why, file=sys.stderr)
        return 1
    if token:
        # The tunnel connector runs in the same container: its connection to Ignis stays inside it, and it dials out
        # to Cloudflare. IPv4: IPv6 attempts timed out on the network it was tested on.
        # https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/configure-tunnels/run-parameters/
        log(f"cloudflared: protocol {protocol} (IGNIS_TUNNEL_PROTOCOL)")
        TUNNEL_IN_USE["protocol"] = protocol
        workers.append(threading.Thread(target=supervise, daemon=True, args=(
            "cloudflared", cloudflared_args(protocol), {**env, "TUNNEL_TOKEN": token}, RUNTIME, job)))
    else:
        log(f"no tunnel token in Credential Manager ({TOKEN_TARGET}): the tunnel is not started")
    # Augmented View: the relay outside the sandbox and the forwarder inside it (see "the Augmented View relay" above)
    workers.append(threading.Thread(target=relay, args=(sid,), daemon=True))
    workers.append(threading.Thread(target=relay, args=(sid, LOCAL_RELAY_PIPE, route_local), daemon=True))
    workers.append(threading.Thread(target=supervise, daemon=True, args=(
        "augmented-view", [str(NODE), str(FORWARDER), str(RELAY_PORT), PIPE], env, FORWARDER.parent, job)))
    workers.append(threading.Thread(target=watch_access, args=(sid,), daemon=True))  # files moved into the vault
    workers.append(threading.Thread(target=write_status, daemon=True))  # for the Ignis Control plugin
    for w in workers:
        w.start()
    for w in workers:
        w.join()
    assert mutex
    return 0


# --- proving the fence ---

PROBE = r"""
const fs = require("fs");
for (const [p, expect] of JSON.parse(process.argv[1])) {
  let got;
  try { fs.statSync(p).isDirectory() ? fs.readdirSync(p) : fs.readFileSync(p); got = "readable"; }
  catch (e) { got = e.code; }
  console.log(JSON.stringify([p, expect, got]));
}
"""


def probe_paths(planted: Path) -> list[tuple[str, str]]:
    """What `check` tries inside the container, built from this PC's environment: what Ignis needs (readable) and what
    it must not reach (denied). A denied probe proves something only when the path exists, so missing ones are left
    out. The folders on the way down to the vault and to ignis/ hold the container's attributes-only rule (a listing
    rule added there shows names, never contents), so in those a file is probed instead of the folder."""
    env = os.environ.get
    on_the_way = {*VAULT.parents, *IGNIS.resolve().parents}

    def first_file(folder: Path) -> Optional[Path]:
        try:
            return next((f for f in sorted(folder.iterdir()) if f.is_file() and not is_link(str(f))), None)
        except OSError:
            return None

    def folder_or_file(folder: Path) -> Optional[Path]:
        return first_file(folder) if folder.resolve() in on_the_way else folder

    drives = []
    for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":  # other fixed disks (not removable or network ones, which may hang)
        root = Path(f"{letter}:\\")
        if k32.GetDriveTypeW(str(root)) == 3 and root not in on_the_way:
            drives.append(root)
    denied: list[Optional[Path]] = [
        planted,  # a file `check` writes in the user's temporary folder (in the profile, outside the vault)
        IGNIS / ".env",  # the launcher's own settings (the relay's ports come from here)
        IGNIS / Path(__file__).name,  # the launcher itself
        first_file(ROOT),  # a file beside ignis/
        folder_or_file(Path.home() / "Documents"),
        folder_or_file(VAULT.parent),  # the folder that holds the vault
        Path.home() / ".ssh",
        *(Path(v) for v in (env("APPDATA"), env("LOCALAPPDATA"), env("ProgramData")) if v),
        Path(env("PUBLIC", "")) / "Documents" if env("PUBLIC") else None,  # every user may read it; the sandbox may not
        *drives,
    ]
    readable = [VAULT, VAULTS / VAULT.name, DATA, APP / "package.json"]
    return ([(str(p), "readable") for p in readable]
            + [(str(p), "denied") for p in dict.fromkeys(denied) if p is not None and p.exists()])


def check() -> int:
    _, sid = container_sid()
    import tempfile
    fd, name = tempfile.mkstemp(prefix="ignis-check-", suffix=".txt")
    os.write(fd, b"a file outside the vault that the container must not read\n")
    os.close(fd)
    try:
        probes = probe_paths(Path(name))
        job = kill_on_close_job()
        p = Sandboxed([str(NODE), "-e", PROBE, json.dumps(probes)], ignis_env(sid), RUNTIME, job)
        out = p.output.read().decode("utf-8", "replace")
        p.wait()
    finally:
        os.remove(name)
    ok = True
    for line in out.splitlines():
        try:
            path, expect, got = json.loads(line)
        except ValueError:
            print(line)
            ok = False
            continue
        good = (got == "readable") == (expect == "readable")
        ok &= good
        print(f"  {'ok  ' if good else 'FAIL'} {expect:8} -> {got:9} {path}")
    entries, lacking = lacking_grant(sid)  # the vault's files the container cannot open (a file moved in)
    ok &= not lacking
    print(f"  {'ok  ' if not lacking else 'FAIL'} vault grant: {len(lacking)} of {entries} entries lack the container's rule"
          + (f" (first: {lacking[0]}); `repair` fixes them" if lacking else ""))
    print("all as expected" if ok else "SOME PROBES DID NOT MATCH")
    return 0 if ok else 1


def install_startup() -> int:
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    startup = Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
    link = startup / "Ignis Control.lnk"
    # A fixed command; the paths reach it only as environment variables (a quote in a folder name cannot end a string
    # and run what follows)
    ps = ("$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:IGNIS_LNK); $s.TargetPath = $env:IGNIS_TARGET; "
          "$s.Arguments = $env:IGNIS_ARGS; $s.WorkingDirectory = $env:IGNIS_WORKDIR; $s.WindowStyle = 7; $s.Save()")
    code = powershell(ps, IGNIS_LNK=str(link), IGNIS_TARGET=str(pythonw),
                      IGNIS_ARGS=subprocess.list2cmdline([str(Path(__file__).resolve()), "run"]), IGNIS_WORKDIR=str(ROOT))
    print(f"created {link}" if code == 0 else f"could not create {link} (PowerShell exit code {code})")
    return code


def require_vault() -> None:
    """Stop, naming the setting, when the vault folder does not exist (nothing is created or granted in its place)."""
    if not VAULT.is_dir():
        message = (f"the vault folder {VAULT} does not exist: set IGNIS_VAULT to your vault's folder, as a line "
                   f"IGNIS_VAULT=<folder> in {IGNIS / '.env'} or in the environment")
        log(message)
        sys.exit(message)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for c in ("setup", "exempt", "unexempt", "check", "repair", "set-token", "run", "install-startup"):
        sub.add_parser(c)
    args = ap.parse_args()
    if args.cmd in ("setup", "check", "repair", "run"):
        require_vault()
    return {"setup": setup, "exempt": exempt, "unexempt": unexempt, "check": check, "repair": repair, "set-token": set_token, "run": run, "install-startup": install_startup}[args.cmd]()


if __name__ == "__main__":
    sys.exit(main())
