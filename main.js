// Ignis Control: live status and controls for the Ignis server on this PC, in desktop Obsidian.
// Windows only; tested on Windows 11 Pro.
//
// Ignis (Obsidian in a browser, https://ignis.thiefling.com) runs here in a Windows AppContainer, started and watched by
// ignis/ignis_native.py (the "launcher"), with cloudflared in the same sandbox publishing it through a
// Cloudflare Tunnel. Design and set-up: README.md and docs/ in this repository.
//
// Where the information comes from: the launcher writes ignis/status.json every 2 s (its pid, each process it
// supervises with state, restarts, last exit, CPU and memory, the tunnel's live connections, the relay's counts, the
// server settings). This plugin reads that file, and the tail of ignis/ignis.log; it never talks to the sandbox (nothing
// outside the sandbox can connect in). A status file older than STALE_SECONDS means the launcher is not running.
//
// Windows only, because everything it controls is: the AppContainer, the launcher, Credential Manager, the named-pipe
// relay.
//
// Two modes. In desktop Obsidian it starts and stops the launcher (child_process) and reads files outside the vault.
// In Ignis itself (a browser tab, on any device, through the tunnel) it has no Node: there it shows and changes what a
// tab can reach, so Ignis can be adjusted remotely: the server settings through Ignis's own /api/settings (validated
// and applied by the server, no restart), which plugins load in Ignis (.obsidian/ignis-disabled-plugins.json, read by
// the local plugins guard, patches/0001) and the tabs' diagnostics. Nothing in it can start a program from a
// browser.
//
// The Ignis folder and the Python that runs the launcher are per device, never in the vault's data.json (the vault is
// shared with every device and the browser, which could otherwise choose the program desktop Obsidian runs): they come
// from %LOCALAPPDATA%\Ignis Control\location.json, which the launcher writes at every start, or from this device's
// own settings (Obsidian's local storage).
//
// What it runs, which network requests it makes and which files outside the vault it reads: docs/disclosures.md.

const { Plugin, PluginSettingTab, Setting, Modal, Notice, Platform, requestUrl, setIcon } = require("obsidian");

const IN_IGNIS = typeof window !== "undefined" && typeof window.__ignis === "object" && window.__ignis !== null;
const DESKTOP = !IN_IGNIS && Platform.isDesktopApp;
// Node's modules exist only in desktop Obsidian (Ignis has stand-ins over the vault, which must not be used here)
const fs = DESKTOP ? require("fs") : null;
const path = DESKTOP ? require("path") : null;
const { spawn, execFile } = DESKTOP ? require("child_process") : {};

const WINDOWS = DESKTOP && process.platform === "win32";
const PLATFORM_NOTE = "Windows only; tested on Windows 11 Pro.";

// Shared through the vault: only what is the same on every device
const DEFAULTS = { refreshSeconds: 2 };
// Per device (Obsidian's local storage), never in data.json; empty: from the launcher's location.json
const DEVICE_KEYS = ["ignisDir", "python", "launcher"];
const STALE_SECONDS = 10;
const DISABLED_FILE = "ignis-disabled-plugins.json"; // in .obsidian

// Ignis's own server settings (ignis/data/server-settings.json; read by Ignis when it starts, so a change needs a
// restart). Defaults and meanings: https://ignis.thiefling.com/docs/using/settings/
const MB = 1024 * 1024;
const SERVER_SLIDERS = [
  { key: "contentCacheBytes", name: "Content cache", unit: "MB", scale: MB, min: 25, max: 500, step: 25, def: 50,
    desc: "Note contents kept in each browser tab's memory. Ignis prefetches up to about three quarters of it (at most 100 MB) on every load: larger loads faster, but uses more memory and mobile data per visit." },
  { key: "persistentCacheBytes", name: "Kept plugin and settings files", unit: "MB", scale: MB, min: 0, max: 500, step: 25, def: 100,
    desc: "Each browser keeps the vault's .obsidian files (plugins' code, styles, settings) between visits, so a phone does not download them at every start (about 32 MB here). A kept file is used only while it is unchanged on this PC. Least recently used files go first above this size; 0 keeps none and empties it. Patched Ignis (patch 0004)." },
  { key: "inputCacheBytes", name: "Input cache", unit: "MB", scale: MB, min: 50, max: 1000, step: 50, def: 200,
    desc: "Files picked in file dialogs (for example by the Importer plugin), kept for the plugin to read." },
  { key: "writeCoalesceMs", name: "Write coalesce window", unit: "ms", scale: 1, min: 0, max: 5000, step: 100, def: 0,
    desc: "Groups rapid saves into one write. Off (0) suits a local disk." },
  { key: "maxBodyBytes", name: "Maximum request size", unit: "MB", scale: MB, min: 10, max: 500, step: 10, def: 50,
    desc: "The largest single upload or save the server accepts." },
];

// Ignis's documentation, for the Guide button (a web page: nothing local is opened).
// Ignis Control's own files on GitHub (the repository holds the plugin, its set-up guide and the launcher).
const REPO = "https://github.com/Gameboard-dev/ignis-control/blob/main/";
const GUIDE_URL = REPO + "README.md#documentation";

// Resources: [heading, [[name, description, web address]]].
const RESOURCES = [
  ["This installation", [
    ["Documentation", "Installation, Cloudflare, configuration, architecture, the relay, security and troubleshooting.", REPO + "README.md#documentation"],
    ["Launcher", "ignis_native.py: starts and watches Ignis, cloudflared and the relay, and repairs the vault's access rules; its docstring explains the sandbox.", REPO + "ignis_native.py"],
  ]],
  ["Downloads", [
    ["Ignis", "Source releases; each tag names the Obsidian version it is pinned to.", "https://github.com/Nystik-gh/ignis/releases"],
    ["Obsidian app files", "obsidian-x.y.z.asar.gz for the version Ignis is pinned to.", "https://github.com/obsidianmd/obsidian-releases/releases"],
    ["Node.js", "Copy the new node.exe into ignis/runtime.", "https://nodejs.org/en/download"],
    ["cloudflared", "Copy the new cloudflared.exe into ignis/runtime.", "https://github.com/cloudflare/cloudflared/releases"],
  ]],
  ["Documentation", [
    ["Ignis", "Deployment, settings, plugin compatibility.", "https://ignis.thiefling.com/docs/"],
    ["Ignis environment variables", "Every setting the server reads at start.", "https://ignis.thiefling.com/docs/server/environment/"],
    ["Ignis troubleshooting", "Insecure-connection warnings, saving, plugins, vault list.", "https://ignis.thiefling.com/docs/troubleshooting/"],
    ["Plugin compatibility", "Community reports per plugin (Ignis issue #9).", "https://github.com/Nystik-gh/ignis/issues/9"],
    ["Cloudflare Tunnel", "Connectors, routes and run parameters.", "https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/"],
    ["Cloudflare Access", "Self-hosted applications and their login policies.", "https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/self-hosted-public-app/"],
    ["Windows AppContainer", "The sandbox the server runs in.", "https://learn.microsoft.com/en-us/windows/win32/secauthz/appcontainer-isolation"],
  ]],
  ["Dashboards", [
    ["Cloudflare", "Tunnels, routes and DNS.", "https://dash.cloudflare.com/"],
    ["Cloudflare Zero Trust", "Access applications, Gateway policies and logs.", "https://one.dash.cloudflare.com/"],
  ]],
];

const GUIDE = [
  ["Status indicator", "Green: running, tunnel connected. Amber: running, but the tunnel is down or connecting (or no tunnel token is stored). Red: the Ignis server itself is down. Hollow: the launcher is not running. Select it to open this panel."],
  ["Starting and stopping", "The launcher can start at logon (the Startup shortcut \"Ignis Control\", made by its install-startup command). Stopping it stops Ignis, cloudflared and the relay together. After a restart, wait for green."],
  ["Opening the vault", "Use the public address on any device, this PC included: nothing outside the sandbox can connect to Ignis directly. Cloudflare Access asks for a one-time PIN sent to your email first."],
  ["Plugins in the browser", "The same as desktop, except those in Plugin exclusions (.obsidian/ignis-disabled-plugins.json). Switching a plugin on or off on desktop is followed live in open Ignis tabs."],
  ["From a phone", "This panel works in Ignis too: open Settings → Ignis Control in the browser to change the server's settings, which plugins load in Ignis, and the tabs' diagnostics."],
  ["Augmented View", "In the browser it uses desktop Obsidian's model server through the relay, so start that server in desktop Obsidian."],
  ["When the site is unreachable", "Check the tunnel and the processes' last exit here, then the log. A VPN client, or the Cloudflare One Client, running on this PC can block the tunnel. A Cloudflare Gateway block page comes from a Zero Trust policy, not from this server."],
  ["After changes to the sandbox", "After upgrades or changes to folders or permissions, run the sandbox check: every line should read ok."],
];

module.exports = class IgnisControl extends Plugin {
  async onload() {
    const saved = (await this.loadData()) || {};
    this.settings = Object.assign({}, DEFAULTS, saved);
    for (const k of DEVICE_KEYS) delete this.settings[k];
    this.device = this.loadDevice(saved);
    this.addSettingTab(new IgnisTab(this.app, this));
    this.bar = this.addStatusBarItem();
    this.bar.addClass("ignis-control-bar");
    if (IN_IGNIS) {
      // in a browser tab: this page came through the tunnel, so the server and the tunnel are up
      this.bar.setText("Ignis ●");
      this.bar.setAttr("data-level", "ok");
      this.bar.setAttr("aria-label", `Ignis ${window.__ignis.version ?? ""}: connected (settings: select)`);
      this.bar.addClass("mod-clickable");
      this.registerDomEvent(this.bar, "click", () => this.openPanel());
      this.addCommand({ id: "open-panel", name: "Show the server's options", callback: () => this.openPanel() });
      return;
    }
    if (!WINDOWS) {
      this.bar.setText("Ignis: Windows only");
      return; // nothing it controls exists elsewhere
    }
    this.status = null; // the last status.json, parsed
    this.health = { level: "off", symbol: "○", text: "reading status" };
    this.urlCheck = null;

    this.bar.addClass("mod-clickable");
    this.registerDomEvent(this.bar, "click", () => this.openPanel());
    this.addCommand({ id: "open-panel", name: "Show status and controls", callback: () => this.openPanel() });
    this.addCommand({ id: "start", name: "Start the server", callback: () => this.start() });
    this.addCommand({ id: "stop", name: "Stop the server", callback: () => this.stop() });
    this.addCommand({ id: "restart", name: "Restart the server", callback: () => this.restart() });
    this.addCommand({ id: "open-site", name: "Open the site in the browser", callback: () => this.openSite() });

    await this.refresh();
    this.schedule();
  }

  schedule() {
    if (this.timer) window.clearInterval(this.timer);
    this.timer = window.setInterval(() => this.refresh(), this.settings.refreshSeconds * 1000);
    this.registerInterval(this.timer);
  }

  // --- this device's paths ---

  // The launcher's location.json (desktop only); {} when there is none yet
  readLocation() {
    if (!DESKTOP) return {};
    try {
      const base = process.env.LOCALAPPDATA || path.join(require("os").homedir(), "AppData", "Local");
      const loc = JSON.parse(fs.readFileSync(path.join(base, "Ignis Control", "location.json"), "utf8"));
      // only the two strings it is read for (the file is the launcher's, but nothing else is taken from it)
      return { ignis_dir: typeof loc?.ignis_dir === "string" ? loc.ignis_dir : "", python: typeof loc?.python === "string" ? loc.python : "" };
    } catch {
      return {};
    }
  }

  // This device's paths: its own settings, else the launcher's location.json. Values an older version kept in the
  // vault's data.json move to this device once, and data.json is written without them.
  loadDevice(saved) {
    const own = {};
    for (const k of DEVICE_KEYS) own[k] = this.app.loadLocalStorage(`ignis-control-${k}`) || "";
    if (DESKTOP && DEVICE_KEYS.some((k) => saved[k] !== undefined)) {
      for (const k of DEVICE_KEYS) if (!own[k] && typeof saved[k] === "string") this.app.saveLocalStorage(`ignis-control-${k}`, (own[k] = saved[k].trim()) || null);
      this.saveSettings();
    }
    this.own = own;
    const loc = this.readLocation();
    return { ignisDir: own.ignisDir || loc.ignis_dir || "", python: own.python || loc.python || "", launcher: own.launcher };
  }

  setDevice(key, value) {
    this.app.saveLocalStorage(`ignis-control-${key}`, value || null);
    this.device = this.loadDevice({});
  }

  file(name) {
    return path.join(this.device.ignisDir, name);
  }

  launcherPath() {
    return this.device.launcher || this.file("ignis_native.py");
  }

  // --- what a browser tab reaches ---

  // Ignis's server settings (same origin, behind Cloudflare Access): GET, or POST changes (validated, saved and
  // applied by the server; the cache sizes reach a tab when it next loads)
  async apiSettings(changes) {
    const r = await fetch("/api/settings", changes ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(changes) } : {});
    const body = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(body.error || `HTTP ${r.status}`);
    return body;
  }

  // The plugins kept off in Ignis (.obsidian/ignis-disabled-plugins.json; the same file from desktop and browser)
  async disabledInIgnis() {
    try {
      const ids = JSON.parse(await this.app.vault.adapter.read(`${this.app.vault.configDir}/${DISABLED_FILE}`));
      return Array.isArray(ids) ? ids.filter((x) => typeof x === "string") : [];
    } catch {
      return [];
    }
  }

  async setDisabledInIgnis(ids) {
    const file = `${this.app.vault.configDir}/${DISABLED_FILE}`;
    let crlf = false;
    try { crlf = (await this.app.vault.adapter.read(file)).includes("\r\n"); } catch { /* new file */ }
    const text = JSON.stringify([...new Set(ids)], null, 2) + "\n";
    await this.app.vault.adapter.write(file, crlf ? text.replace(/\n/g, "\r\n") : text);
  }

  // --- reading the state ---

  async refresh() {
    try {
      this.status = this.device.ignisDir ? JSON.parse(await fs.promises.readFile(this.file("status.json"), "utf8")) : null;
    } catch {
      this.status = null;
    }
    this.health = this.assess(this.status);
    this.bar.setText(`Ignis ${this.health.symbol}`);
    this.bar.setAttr("aria-label", `Ignis: ${this.health.text}`);
    this.bar.setAttr("data-level", this.health.level);
    this.onRefresh?.();
  }

  launcherAlive(s) {
    if (!s || !s.launcher) return false;
    try {
      process.kill(s.launcher.pid, 0); // throws if there is no such process
      return Date.now() / 1000 - s.updated < STALE_SECONDS;
    } catch {
      return false;
    }
  }

  assess(s) {
    if (!this.launcherAlive(s)) return { level: "off", symbol: "○", text: "not running" };
    const p = s.processes || {};
    if (p.ignis?.state !== "running") return { level: "bad", symbol: "●", text: `server ${p.ignis?.state ?? "not started"}` };
    if (!p.cloudflared) return { level: "warn", symbol: "●", text: "running, no tunnel (no token stored)" };
    if (p.cloudflared.state !== "running") return { level: "warn", symbol: "●", text: `running, tunnel ${p.cloudflared.state}` };
    if (!s.tunnel?.connections) return { level: "warn", symbol: "●", text: "running, tunnel connecting" };
    const n = s.tunnel.connections;
    return { level: "ok", symbol: "●", text: `running, tunnel connected (${n} connection${n === 1 ? "" : "s"})` };
  }

  // The files the log pane can follow (desktop only; both outside or at the edge of the vault, read with Node's fs):
  // the launcher's ignis.log in the Ignis folder (from location.json or this device's setting), and the transcript the
  // launcher writes for the last LaTeX build through Ignis, in the vault's LaTeX/compiled folder.
  logFiles() {
    const base = this.app.vault.adapter?.getBasePath?.();
    return {
      main: this.device.ignisDir ? this.file("ignis.log") : "",
      build: base ? path.join(base, "LaTeX", "compiled", ".ignis-build.log") : "",
    };
  }

  // --- controls ---

  // Python and the Ignis folder as this device knows them, or why they cannot be used
  runnable() {
    const { python, ignisDir } = this.device;
    if (!ignisDir || !fs.existsSync(this.launcherPath())) return `the Ignis folder is not known on this device: start the launcher once by hand (it records where it is), or set the folder below`;
    if (!python || !path.isAbsolute(python) || !/^pythonw?\.exe$/i.test(path.basename(python)) || !fs.existsSync(python)) return `no python.exe set on this device: set it below`;
    return null;
  }

  start() {
    if (this.launcherAlive(this.status)) return new Notice("Ignis is already running.");
    const why = this.runnable();
    if (why) return new Notice(`Ignis: cannot start: ${why}.`);
    const pythonw = path.join(path.dirname(this.device.python), "pythonw.exe");
    const exe = fs.existsSync(pythonw) ? pythonw : this.device.python;
    const child = spawn(exe, [this.launcherPath(), "run"], {
      cwd: path.dirname(this.device.ignisDir), detached: true, stdio: "ignore", windowsHide: true,
    });
    child.on("error", (e) => new Notice(`Ignis: could not start the launcher: ${e.message}`));
    child.unref();
    new Notice("Ignis: starting. The indicator turns green once the tunnel connects.");
    window.setTimeout(() => this.refresh(), 3000);
  }

  // Ends the launcher; true when it was asked to end. The process id comes from status.json, so before anything is
  // killed, Windows is asked which program has that id: only python.exe or pythonw.exe (the launcher) is stopped.
  async stop() {
    const s = this.status;
    if (!this.launcherAlive(s)) {
      new Notice("Ignis is not running.");
      return false;
    }
    const pid = s.launcher.pid;
    const why = await checkLauncherProcess(pid);
    if (why) {
      new Notice(`Ignis: not stopped: ${why}.`, 10000);
      return false;
    }
    try {
      process.kill(pid); // the launcher's job object ends Ignis, cloudflared and the forwarder with it
      new Notice("Ignis: stopped.");
    } catch (e) {
      new Notice(`Ignis: could not stop the launcher (process ${pid}): ${e.message}`);
      return false;
    } finally {
      window.setTimeout(() => this.refresh(), 500);
    }
    return true;
  }

  async restart() {
    const s = this.status;
    if (this.launcherAlive(s)) {
      if (!(await this.stop())) return; // not the launcher, or it could not be stopped: start nothing
      for (let i = 0; i < 40; i++) { // up to 10 s for the launcher to exit
        await sleep(250);
        try { process.kill(s.launcher.pid, 0); } catch { break; }
      }
    }
    this.start();
  }

  openSite() {
    const url = this.status?.url;
    if (url) window.open(url);
    else new Notice("Ignis: no public address yet (IGNIS_HOSTNAME in ignis/.env).");
  }



  // `ignis_native.py check`, run with an argument array (no shell parses anything); its output is shown in a modal
  sandboxCheck() {
    const why = this.runnable();
    if (why) return new Notice(`Ignis: cannot run the check: ${why}.`);
    const modal = new TextModal(this.app, "Sandbox check", "Running probes inside the sandbox…");
    modal.open();
    execFile(this.device.python, [this.launcherPath(), "check"], { windowsHide: true, timeout: 120000 },
      (err, stdout, stderr) => modal.setText((stdout || "") + (stderr || "") + (err && !stdout ? `\n${err.message}` : "")));
  }

  async checkUrl() {
    const url = this.status?.url;
    if (!url) return new Notice("Ignis: no public address yet.");
    const t0 = performance.now();
    try {
      const r = await requestUrl({ url, method: "GET", throw: false }); // follows the redirect to the Access login
      // healthy: the Access login page (or the site itself) answered
      const ok = r.status >= 200 && r.status < 400;
      this.urlCheck = { ok, text: `HTTP ${r.status} in ${Math.round(performance.now() - t0)} ms`, at: Date.now() / 1000 };
    } catch (e) {
      this.urlCheck = { ok: false, text: `unreachable (${e.message})`, at: Date.now() / 1000 };
    }
    this.onRefresh?.();
  }

  // --- server settings ---

  async readServerSettings() {
    try {
      return JSON.parse(await fs.promises.readFile(this.file(path.join("data", "server-settings.json")), "utf8"));
    } catch {
      return {};
    }
  }

  async writeServerSettings(changes) {
    const current = await this.readServerSettings();
    const file = this.file(path.join("data", "server-settings.json"));
    await fs.promises.writeFile(file, JSON.stringify(Object.assign(current, changes), null, 2) + "\n", "utf8");
  }

  openPanel() {
    this.app.setting.open();
    this.app.setting.openTabById(this.manifest.id);
  }

  async saveSettings() {
    await this.saveData(this.settings);
  }
};

class IgnisTab extends PluginSettingTab {
  constructor(app, plugin) {
    super(app, plugin);
    this.plugin = plugin;
  }

  hide() {
    this.plugin.onRefresh = null;
    this.logPane?.unmount(); // the pane reads the logs only while this tab is open
    this.logPane = null;
  }

  async display() {
    const el = this.containerEl;
    this.logPane?.unmount();
    this.logPane = null;
    el.empty();
    el.removeClass("setting-contents-layout");
    const nav = el.createEl("nav", { cls: "setting-contents" });
    await this.sections(el);
    this.contents(el, nav);
  }

  // The tab's contents: a link to every section heading, beside the sections and in view as they scroll where the
  // window is wide (styles.css), above them where it is not. The same layout as the author's other plugins' tabs.
  contents(el, nav) {
    if (!nav.isConnected) return; // drawn again meanwhile
    const heads = Array.from(el.querySelectorAll(".setting-item-heading"));
    if (heads.length < 3) {
      nav.remove();
      return;
    }
    nav.createDiv({ cls: "setting-contents-title", text: "Contents" });
    const links = nav.createDiv("setting-contents-links");
    heads.forEach((head, i) => {
      const a = links.createEl("a", { text: head.querySelector(".setting-item-name")?.textContent ?? "", href: "#" });
      a.addEventListener("click", (e) => {
        e.preventDefault();
        head.scrollIntoView({ behavior: "smooth", block: "start" });
      });
      if (i + 1 < heads.length) links.createSpan({ cls: "setting-contents-sep", text: " · " });
    });
    el.addClass("setting-contents-layout");
  }

  async sections(el) {
    el.addClass("ignis-control");
    el.createDiv({ cls: "ignis-platform", text: PLATFORM_NOTE });
    if (IN_IGNIS) {
      await this.webStatusSection(el);
      await this.webServerSettingsSection(el);
      await this.pluginsSection(el);
      await this.tabsSection(el);
      this.guideSection(el);
      return;
    }
    if (!WINDOWS) {
      el.createEl("p", { text: "This system is not Windows, so there is nothing to control: the sandbox, the launcher and the tunnel set-up are Windows features. In Ignis (in a browser) this panel shows the server's settings." });
      return;
    }

    this.statusSection(el);
    this.logSection(el);
    this.controlsSection(el);
    await this.serverSettingsSection(el);
    await this.pluginsSection(el);
    await this.tabsSection(el);
    this.panelSection(el);
    this.resourcesSection(el);
    this.guideSection(el);
  }

  // --- in Ignis (a browser tab) ---

  async webStatusSection(el) {
    new Setting(el).setHeading().setName("This tab");
    const facts = el.createDiv("ignis-facts");
    const fact = (k, v) => {
      facts.createDiv({ cls: "ignis-fact-key", text: k });
      return facts.createDiv({ cls: "ignis-fact-value", text: v });
    };
    fact("Server", `Ignis ${window.__ignis.version ?? ""}${window.__ignis.build ? ` (${window.__ignis.build})` : ""}, connected through the tunnel`);
    const storage = fact("Kept in this browser", "…");
    try {
      const [{ usage, quota }, kept] = await Promise.all([navigator.storage.estimate(), navigator.storage.persisted?.() ?? false]);
      storage.setText(`${Math.round(usage / MB)} MB of ${Math.round(quota / MB)} MB; ${kept ? "kept (the browser will not clear it on its own)" : "may be cleared by the browser when space runs low"}`);
    } catch {
      storage.setText("unknown");
    }
    el.createEl("p", { cls: "ignis-down", text: "Starting, stopping and the log are in desktop Obsidian's Ignis Control: a browser tab cannot start programs on the PC." });
  }

  async webServerSettingsSection(el) {
    const plugin = this.plugin;
    new Setting(el).setHeading().setName("Server")
      .setDesc("Ignis's own options. Saved and applied by the server straight away (no restart). The cache sizes reach a tab when it next loads.");
    let current;
    try {
      current = await plugin.apiSettings();
    } catch (e) {
      el.createEl("p", { cls: "ignis-down", text: `Could not read the server's settings: ${e.message}` });
      return;
    }
    const pending = {};
    for (const sl of SERVER_SLIDERS) {
      const value = current[sl.key] != null ? Math.round(current[sl.key] / sl.scale) : sl.def;
      const setting = new Setting(el).setName(sl.name).setDesc(sl.desc);
      const shown = setting.controlEl.createSpan({ cls: "ignis-value", text: `${value} ${sl.unit}` });
      let slider;
      setting.addSlider((s) => {
        slider = s;
        s.setLimits(sl.min, sl.max, sl.step).setValue(value).onChange((v) => {
          pending[sl.key] = v * sl.scale;
          shown.setText(`${v} ${sl.unit}${v === value ? "" : " (not applied)"}`);
        });
      });
      setting.addExtraButton((b) => b.setIcon("rotate-ccw").setTooltip(`Restore Ignis's default (${sl.def} ${sl.unit})`).onClick(() => slider.setValue(sl.def)));
    }
    new Setting(el).setName("Apply")
      .setDesc("Sends the changed values to the server, which checks and saves them (ignis/data/server-settings.json).")
      .addButton((b) => b.setButtonText("Apply").setCta().onClick(async () => {
        if (!Object.keys(pending).length) return new Notice("No settings changed.");
        try {
          await plugin.apiSettings(pending);
          new Notice("Ignis: settings saved. Reload a tab for the cache sizes to apply to it.");
        } catch (e) {
          new Notice(`Ignis: the server refused the settings: ${e.message}`);
        }
        this.display();
      }));
  }

  // --- in both ---

  // Which installed plugins load in Ignis: the plugins guard (patches/0001) leaves those in
  // ignis-disabled-plugins.json out of Ignis's plugin list, while desktop keeps running them.
  async pluginsSection(el) {
    const plugin = this.plugin;
    const plugins = this.app.plugins;
    new Setting(el).setHeading().setName("Plugin exclusions")
      .setDesc("Plugins excluded from loading in Ignis, on every device, while desktop Obsidian keeps running them. Taken up when a tab next loads; in this tab now, too, when you are in Ignis. A plugin switched off in Community plugins stays off everywhere.");
    const manifests = () => Object.values(plugins.manifests || {}).sort((a, b) => a.name.localeCompare(b.name));
    const onDesktop = (id, off) => plugins.enabledPlugins?.has(id) || off.has(id);
    // this tab follows at once (without saving community-plugins.json, which desktop owns)
    const follow = async (m, load, off) => {
      if (IN_IGNIS && m.id !== plugin.manifest.id && onDesktop(m.id, off)) {
        try {
          load ? await plugins.enablePlugin(m.id) : await plugins.disablePlugin(m.id);
        } catch (e) {
          new Notice(`Ignis: ${m.name}: ${e.message}`);
        }
      }
      new Notice(`Ignis: ${m.name} ${load ? "loads in" : "is kept out of"} Ignis from the next time a tab loads${IN_IGNIS ? " (and in this tab now)" : ""}.`);
    };

    // a search box: type part of a plugin's name, pick it, and it is excluded
    const add = new Setting(el).setName("Exclude a plugin").setDesc("Search the installed plugins by name.");
    const list = el.createDiv("ignis-exclusions");
    const box = add.controlEl.createDiv("ignis-plugin-search");
    const input = box.createEl("input", { type: "search", placeholder: "Plugin name…" });
    const hits = box.createDiv("ignis-plugin-hits");
    const showHits = async () => {
      const q = input.value.trim().toLowerCase();
      hits.empty();
      if (!q) return;
      const off = new Set(await plugin.disabledInIgnis());
      for (const m of manifests().filter((m) => !off.has(m.id) && (m.name.toLowerCase().includes(q) || m.id.includes(q))).slice(0, 8)) {
        const hit = hits.createDiv({ cls: "ignis-plugin-hit", text: m.name });
        hit.addEventListener("click", async () => {
          await plugin.setDisabledInIgnis([...(await plugin.disabledInIgnis()), m.id]);
          input.value = "";
          hits.empty();
          await follow(m, false, off);
          await drawList();
        });
      }
      if (!hits.childElementCount) hits.createDiv({ cls: "ignis-plugin-none", text: "No other plugin matches." });
    };
    input.addEventListener("input", showHits);

    // the excluded plugins, each with Remove
    const drawList = async () => {
      list.empty();
      const off = new Set(await plugin.disabledInIgnis());
      const excluded = manifests().filter((m) => off.has(m.id));
      if (!excluded.length) {
        list.createDiv({ cls: "setting-item-description", text: "No plugin is excluded: every plugin desktop runs also loads in Ignis." });
        return;
      }
      for (const m of excluded) {
        const row = new Setting(list).setName(m.name).setClass("ignis-plugin");
        row.setDesc(m.id === plugin.manifest.id ? "This panel. Excluded, these settings can be changed only from desktop Obsidian." : (onDesktop(m.id, off) ? "" : "Switched off in Community plugins."));
        row.addButton((b) => b.setButtonText("Remove").onClick(async () => {
          const ids = await plugin.disabledInIgnis();
          await plugin.setDisabledInIgnis(ids.filter((x) => x !== m.id));
          await follow(m, true, off);
          await drawList();
        }));
      }
    };
    await drawList();
  }

  // Built once; every refresh only updates text in place, so nothing jumps or blinks
  statusSection(el) {
    const plugin = this.plugin;
    new Setting(el).setHeading().setName("Status");
    const box = el.createDiv("ignis-status");

    const head = box.createDiv("ignis-headline");
    const dot = head.createSpan({ cls: "ignis-dot", text: "●" });
    const headText = head.createSpan();
    const link = head.createEl("a", { cls: "ignis-url" });

    const down = box.createEl("p", { cls: "ignis-down", text: "The launcher is not running, so the server and the tunnel are down. Start it under Controls; it also starts at logon." });

    const table = box.createEl("table", { cls: "ignis-table" });
    const hr = table.createEl("thead").createEl("tr");
    for (const h of ["Process", "State", "PID", "Up", "CPU", "Memory", "Restarts", "Last exit"]) hr.createEl("th", { text: h });
    const tbody = table.createEl("tbody");

    const facts = box.createDiv("ignis-facts");

    let drawing = false;
    const draw = async () => {
      if (drawing) return;
      drawing = true;
      try {
        const s = plugin.status;
        const alive = plugin.launcherAlive(s);

        dot.className = `ignis-dot ignis-${plugin.health.level}`;
        headText.setText(` ${plugin.health.text}`);
        link.toggle(!!s?.url);
        if (s?.url && link.getAttr("href") !== s.url) {
          link.setAttr("href", s.url);
          link.setText(s.url);
        }
        down.toggle(!alive);
        table.toggle(alive);
        facts.toggle(alive);

        if (alive) {
          const rows = document.createDocumentFragment();
          const row = (name, p) => {
            const tr = rows.createEl("tr");
            for (const v of [name, p.state ?? "running", p.pid ?? "–", p.started ? age(p.started) : "–",
              p.cpu_percent != null ? `${p.cpu_percent}%` : "–", p.memory_mb != null ? `${p.memory_mb} MB` : "–",
              p.restarts ?? "–", p.last_exit != null ? `${p.last_exit}, ${age(p.last_exit_at)} ago` : "–"]) tr.createEl("td", { text: String(v) });
          };
          row("launcher", { pid: s.launcher.pid, started: s.launcher.started, memory_mb: s.launcher.memory_mb });
          for (const [name, p] of Object.entries(s.processes || {})) row(name, p);
          tbody.replaceChildren(rows);

          const r = s.relay;
          const cache = s.settings?.contentCacheBytes;
          const items = [
            ["Tunnel", `${s.tunnel.connections} connection${s.tunnel.connections === 1 ? "" : "s"}${s.tunnel.edges.length ? ` (${s.tunnel.edges.join(", ")})` : ""}, QUIC over IPv4`],
            ["Augmented View relay", `${r.passed} passed, ${r.refused} refused, ${r.unavailable} while desktop's server was stopped${r.last ? `; last ${age(r.last_at)} ago` : ""}`],
            ["Vault access", !s.access?.checked_at ? "not checked yet"
              : `${s.access.lacking ? `${s.access.lacking} file(s) Ignis cannot open; ` : "every file open to Ignis; "}`
                + `${s.access.repaired_total} repaired since the launcher started; checked ${age(s.access.checked_at)} ago`],
            ["Content cache", `${cache ? Math.round(cache / MB) : 50} MB`],
            ["Public address", plugin.urlCheck ? `${plugin.urlCheck.text}, checked ${age(plugin.urlCheck.at)} ago` : "not checked yet"],
            ["Status file", `written ${age(s.updated)} ago`],
          ];
          const grid = document.createDocumentFragment();
          for (const [k, v] of items) {
            grid.createDiv({ cls: "ignis-fact-key", text: k });
            grid.createDiv({ cls: "ignis-fact-value", text: v });
          }
          facts.replaceChildren(grid);
        }
      } finally {
        drawing = false;
      }
    };
    plugin.onRefresh = draw;
    draw();
  }

  // The launcher's logs, as they grow (read only while this tab is open)
  logSection(el) {
    new Setting(el).setHeading().setName("Log")
      .setDesc("The launcher's log, with the output of Ignis, cloudflared and the relay, as it grows. Tokens, Cloudflare team names, AUD tags, e-mail addresses and other secret-looking values are hidden. Read only while this tab is open.");
    this.logPane = new LogPane(this.plugin);
    this.logPane.mount(el);
  }

  controlsSection(el) {
    const plugin = this.plugin;
    new Setting(el).setHeading().setName("Controls");
    new Setting(el).setName("Launcher")
      .setDesc("The launcher runs Ignis, cloudflared and the relay. Stopping it stops all three.")
      .addButton((b) => b.setButtonText("Start").setCta().onClick(() => plugin.start()))
      .addButton((b) => b.setButtonText("Restart").onClick(() => plugin.restart()))
      .addButton((b) => b.setButtonText("Stop").setWarning().onClick(() => plugin.stop()));
    new Setting(el).setName("Open")
      .setDesc("The site in your browser, or Ignis's documentation on the web. The launcher's logs are under Log.")
      .addButton((b) => b.setButtonText("Site").onClick(() => plugin.openSite()))
      .addButton((b) => b.setButtonText("Guide").onClick(() => window.open(GUIDE_URL)));
    new Setting(el).setName("Sandbox check")
      .setDesc("Runs probes inside the sandbox: the vault and the server's own folders must be readable, everything else denied.")
      .addButton((b) => b.setButtonText("Run").onClick(() => plugin.sandboxCheck()));
    const check = new Setting(el).setName("Public address")
      .setDesc("Asks Cloudflare for the site from this PC. A healthy answer is the Access login page.");
    const result = check.descEl.createDiv({ cls: "ignis-check-result" });
    const show = () => {
      const c = plugin.urlCheck;
      result.setText(c ? `${c.ok ? "Healthy" : "Not healthy"}: ${c.text}, checked ${age(c.at)} ago` : "");
      result.toggleClass("mod-success", !!c?.ok);
      result.toggleClass("mod-warning", !!c && !c.ok);
    };
    show();
    check.addButton((b) => b.setButtonText("Check").onClick(async () => {
      b.setDisabled(true);
      result.setText("Checking…");
      await plugin.checkUrl();
      b.setDisabled(false);
      show();
      new Notice(`Ignis: public address ${result.getText().toLowerCase()}`);
    }));
  }

  async serverSettingsSection(el) {
    const plugin = this.plugin;
    new Setting(el).setHeading().setName("Server")
      .setDesc("Ignis's own options. Ignis reads them when it starts, so they take effect after a restart. Open tabs reconnect on their own.");
    const current = await plugin.readServerSettings();
    const pending = {};
    for (const sl of SERVER_SLIDERS) {
      const value = current[sl.key] != null ? Math.round(current[sl.key] / sl.scale) : sl.def;
      const setting = new Setting(el).setName(sl.name).setDesc(sl.desc);
      const shown = setting.controlEl.createSpan({ cls: "ignis-value", text: `${value} ${sl.unit}` });
      let slider;
      setting.addSlider((s) => {
        slider = s;
        s.setLimits(sl.min, sl.max, sl.step).setValue(value).onChange((v) => {
          pending[sl.key] = v * sl.scale;
          shown.setText(`${v} ${sl.unit}${v === value ? "" : " (not applied)"}`);
        });
      });
      setting.addExtraButton((b) => b.setIcon("rotate-ccw").setTooltip(`Restore Ignis's default (${sl.def} ${sl.unit})`).onClick(() => slider.setValue(sl.def)));
    }
    new Setting(el).setName("Apply")
      .setDesc("Saves the changed values to ignis/data/server-settings.json and restarts the server (the launcher, Ignis, cloudflared and the relay). With nothing changed it only restarts, which also loads a new launcher.")
      .addButton((b) => b.setButtonText("Apply and restart").setCta().onClick(async () => {
        if (Object.keys(pending).length) await plugin.writeServerSettings(pending);
        else new Notice("Ignis: no settings changed; restarting the server.");
        await plugin.restart();
        this.display();
      }));
  }

  // Ignis's browser tabs read .obsidian/ignis-diagnostics.json when they load (patches/0003-diagnostics.patch)
  async tabsSection(el) {
    const adapter = this.app.vault.adapter;
    const file = `${this.app.vault.configDir}/ignis-diagnostics.json`;
    let enabled = true; // no file: on
    try {
      enabled = JSON.parse(await adapter.read(file)).enabled !== false;
    } catch {
      // not written yet
    }
    new Setting(el).setHeading().setName("Browser tabs");
    new Setting(el).setName("Diagnostics")
      .setDesc("Each Ignis tab reports to ignis.log: errors with the plugin that caused them, each plugin's load time, start-up milestones, freezes, memory (JS heap, each plugin's WebAssembly memory, the note cache) and, after a crash, what the crashed page last reported. On by default; takes effect when a tab is next loaded. The server's own request errors are always logged.")
      .addToggle((t) => t.setValue(enabled).onChange(async (v) => {
        await adapter.write(file, JSON.stringify({ enabled: v }, null, 2) + "\n");
        new Notice(`Ignis: tab diagnostics ${v ? "on" : "off"} from the next time a tab loads.`);
      }));
  }

  panelSection(el) {
    const plugin = this.plugin;
    new Setting(el).setHeading().setName("This panel");
    const refresh = new Setting(el).setName("Refresh interval")
      .setDesc("How often the indicator and this panel re-read the status. The launcher writes it every 2 seconds.");
    const shown = refresh.controlEl.createSpan({ cls: "ignis-value", text: `${plugin.settings.refreshSeconds} s` });
    refresh.addSlider((s) => s.setLimits(1, 30, 1).setValue(plugin.settings.refreshSeconds).onChange(async (v) => {
      shown.setText(`${v} s`);
      plugin.settings.refreshSeconds = v;
      await plugin.saveSettings();
      plugin.schedule();
    }));
    const loc = plugin.readLocation();
    for (const [key, name, desc, found] of [
      ["ignisDir", "Ignis folder", "The installation's ignis/ folder (beside ignis_native.py): status.json, ignis.log and data/.", loc.ignis_dir],
      ["python", "Python", "A python.exe with pywin32 and psutil (all the launcher needs). pythonw.exe beside it starts the launcher without a window.", loc.python],
      ["launcher", "Launcher script", "Empty: ignis_native.py in the Ignis folder. Set it only if the launcher lives elsewhere.", ""],
    ]) {
      const where = found ? ` Empty: what the launcher recorded, ${found}.` : " Empty: what the launcher records when it starts.";
      new Setting(el).setName(name).setDesc(`${desc} This device only.${key === "launcher" ? "" : where}`)
        .addText((t) => t.setPlaceholder(found || "").setValue(plugin.own[key] || "").onChange((v) => plugin.setDevice(key, v.trim())));
    }
  }

  resourcesSection(el) {
    const plugin = this.plugin;
    new Setting(el).setHeading().setName("Resources");
    for (const [group, items] of RESOURCES) {
      el.createDiv({ cls: "ignis-group", text: group });
      for (const [name, desc, target] of items) {

        new Setting(el).setName(name).setDesc(desc).setClass("ignis-resource")
          .addExtraButton((b) => b.setIcon("external-link")
            .setTooltip(target)
            .onClick(() => window.open(target)));
      }
    }
  }

  guideSection(el) {
    new Setting(el).setHeading().setName("Guide");
    for (const [name, desc] of GUIDE) new Setting(el).setName(name).setDesc(desc).setClass("ignis-guide");
  }
}

class TextModal extends Modal {
  constructor(app, title, text) {
    super(app);
    this.titleEl.setText(title);
    this.pre = this.contentEl.createEl("pre", { cls: "ignis-log", text });
  }
  setText(text) {
    this.pre.setText(text);
  }
}

function age(epochSeconds) {
  if (!epochSeconds) return "–";
  const s = Math.max(0, Math.round(Date.now() / 1000 - epochSeconds));
  if (s < 90) return `${s} s`;
  if (s < 5400) return `${Math.round(s / 60)} min`;
  if (s < 172800) return `${(s / 3600).toFixed(1)} h`;
  return `${Math.round(s / 86400)} d`;
}

function sleep(ms) {
  return new Promise((r) => window.setTimeout(r, ms));
}

// --- is this process id the launcher? (before Stop kills it) ---

// The launcher runs under Python; any other program with that id (a stale or altered status.json) is left alone.
const LAUNCHER_IMAGES = ["python.exe", "pythonw.exe"];

function isLauncherImage(name) {
  return LAUNCHER_IMAGES.includes(String(name).toLowerCase());
}

// The image name `tasklist /FO CSV /NH` reports for `pid` ("name","pid",...), or "" when no line is that process
function imageFromTasklist(csv, pid) {
  for (const line of String(csv).split(/\r?\n/)) {
    const m = /^"([^"]*)","(\d+)"/.exec(line.trim());
    if (m && Number(m[2]) === pid) return m[1];
  }
  return "";
}

// Windows' tasklist.exe by its full path (never a PATH lookup), started with an argument array: no shell
function tasklistPath() {
  return path.join(process.env.SystemRoot || "C:\\Windows", "System32", "tasklist.exe");
}

// Why `pid` must not be stopped as the launcher, or null when it is python.exe or pythonw.exe. (Windows offers no
// shell-free way from here to read a process's full path, so the image name is what is checked.)
function checkLauncherProcess(pid) {
  if (!Number.isInteger(pid) || pid <= 0) return Promise.resolve(`the status file names no valid process id (${pid})`);
  return new Promise((resolve) => {
    execFile(tasklistPath(), ["/FI", `PID eq ${pid}`, "/FO", "CSV", "/NH"], { windowsHide: true, timeout: 15000 },
      (err, stdout) => {
        if (err) return resolve(`could not check process ${pid} (${err.message})`);
        const image = imageFromTasklist(stdout, pid);
        if (!image) return resolve(`process ${pid} no longer exists`);
        resolve(isLauncherImage(image) ? null
          : `process ${pid} is ${image}, not the launcher (python.exe or pythonw.exe); the status file may be stale`);
      });
  });
}

// --- the log pane (settings tab, desktop): the launcher's logs as they grow ---

const LOG_MAX_LINES = 2000; // kept per source, and shown at most
const LOG_POLL_MS = 1000;

// The pane's sources. ignis.log holds everything the launcher supervises: its own lines, and each sandboxed process's
// output prefixed "  [name] " (Ignis's server, cloudflared, the Augmented View forwarder); "build" is a file of its own.
const LOG_SOURCES = [
  ["all", "Everything (ignis.log)"],
  ["launcher", "The launcher"],
  ["ignis", "Ignis server"],
  ["tabs", "Browser tabs' reports"],
  ["cloudflared", "cloudflared (the tunnel)"],
  ["relay", "The relay"],
  ["access", "Vault access repair"],
  ["latex", "LaTeX builds"],
  ["build", "Last LaTeX build's transcript"],
];

// Which source a line of ignis.log belongs to
function lineSource(line) {
  const body = String(line).replace(/^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d /, "");
  if (/^\s*\[ignis\] client /.test(body)) return "tabs";
  if (/^\s*\[ignis\] /.test(body)) return "ignis";
  if (/^\s*\[cloudflared\] /.test(body)) return "cloudflared";
  if (/^relay: latex|^latex build /.test(body)) return "latex";
  if (/^\s*\[augmented-view\] |^relay: /.test(body)) return "relay";
  if (/^access: /.test(body)) return "access";
  return "launcher";
}

function lineLevel(line) {
  // cloudflared names its own level (INF, WRN, ERR, FTL): that decides, whatever words the message holds
  const own = /\s(DBG|INF|WRN|ERR|FTL)\s/.exec(line);
  if (own) return own[1] === "ERR" || own[1] === "FTL" ? "error" : own[1] === "WRN" ? "warn" : "info";
  if (/\b(error|failed|fail|refused|denied|EPERM|ENOENT|exited with code [1-9]|could not)\b/i.test(line)) return "error";
  if (/\b(warn|warning|restarting|retrying|timed out|unavailable)\b/i.test(line)) return "warn";
  return "info";
}

// Values hidden before a line is kept: what could let someone into the tunnel, the site or an account, or identify
// the Access set-up, and long strings that look like keys
const REDACTIONS = [
  [/\x1b\[[0-9;]*m/g, ""], // colour codes
  [/eyJ[A-Za-z0-9_-]{8,}(?:\.[A-Za-z0-9_-]+){0,2}/g, "<token>"], // JSON Web Tokens: Access, the tunnel token
  [/\b((?:cf-access-jwt-assertion|cf_authorization|authorization|proxy-authorization|cookie|set-cookie)\s*[:=]\s*).*$/gi, "$1<hidden>"],
  [/\b((?:tunnel[_-]?token|token|secret|password|passwd|api[_-]?key|client[_-]?(?:id|secret)|aud|audience)\s*[=:]\s*)["']?[^\s"',;&]+/gi, "$1<hidden>"],
  [/\b[a-z0-9-]+\.cloudflareaccess\.com\b/gi, "<team>.cloudflareaccess.com"], // the Zero Trust team
  [/\b[0-9a-f]{32,}\b/gi, "<hex>"], // AUD tags (64 hex digits), keys
  [/[A-Za-z0-9+_-]{40,}={0,2}/g, "<long value>"], // base64-like keys
  [/[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}/g, "<e-mail>"],
];

// `site`: the public hostname (from the status file), hidden too, so a copied log does not name the site
function redactLine(line, site = "") {
  let out = String(line);
  for (const [rx, to] of REDACTIONS) out = out.replace(rx, to);
  if (site && site.length >= 4) out = out.split(site).join("<site>");
  return out;
}

// The site's hostname from the status file's url ("https://host"), or ""
function siteHost(status) {
  try {
    return status?.url ? new URL(status.url).hostname : "";
  } catch {
    return "";
  }
}

// Follows a growing log file: the end of it at first, then what is added. A file that shrank, or was replaced (a new
// inode), is read again from its start (rotation, truncation, the build transcript rewritten per build). A file that
// grew by more than maxBytes since the last poll is read from maxBytes before its end, and the skip is reported.
class LogTail {
  constructor(fsp, file, initialBytes = 256 * 1024, maxBytes = 1024 * 1024) {
    this.fsp = fsp;
    this.file = file;
    this.initialBytes = initialBytes;
    this.maxBytes = maxBytes;
    this.offset = -1;
    this.ino = 0;
    this.rest = "";
    this.dropNext = false;
  }

  async poll() {
    let st;
    try {
      st = await this.fsp.stat(this.file);
    } catch {
      return { lines: [], missing: true, restarted: false, skipped: 0 };
    }
    const ino = Number(st.ino) || 0;
    let restarted = false;
    let dropFirst = false; // reading from the middle of the file: its first line is cut
    if (this.offset < 0) {
      this.offset = Math.max(0, st.size - this.initialBytes);
      dropFirst = this.offset > 0;
      this.ino = ino;
    } else if (st.size < this.offset || (ino && this.ino && ino !== this.ino)) {
      this.offset = 0;
      this.ino = ino;
      this.rest = "";
      this.dropNext = false;
      restarted = true;
    }
    let skipped = 0;
    if (st.size - this.offset > this.maxBytes) {
      skipped = st.size - this.maxBytes - this.offset;
      this.offset = st.size - this.maxBytes;
      this.rest = "";
      dropFirst = true;
    }
    const length = st.size - this.offset;
    if (length <= 0) return { lines: [], missing: false, restarted, skipped };
    const buf = Buffer.alloc(length);
    let got = 0;
    const fh = await this.fsp.open(this.file, "r");
    try {
      while (got < length) {
        const { bytesRead } = await fh.read(buf, got, length - got, this.offset + got);
        if (bytesRead <= 0) break;
        got += bytesRead;
      }
    } finally {
      await fh.close();
    }
    this.offset += got;
    const parts = (this.rest + buf.toString("utf8", 0, got)).split(/\r?\n/);
    this.rest = parts.pop() ?? ""; // a line still being written
    if (dropFirst || this.dropNext) {
      this.dropNext = parts.length === 0; // the cut line has not ended yet: drop it when it does
      parts.shift();
    }
    if (this.rest.length > 64 * 1024) this.rest = this.rest.slice(-64 * 1024);
    return { lines: parts.filter((l) => l.trim()), missing: false, restarted, skipped };
  }
}

// Keeps at most `max` items, dropping the oldest
function pushCapped(list, items, max) {
  list.push(...items);
  if (list.length > max) list.splice(0, list.length - max);
}

// The pane itself: source, follow, wrap, filter, copy; polling only while it is mounted (the settings tab is open)
class LogPane {
  constructor(plugin) {
    this.plugin = plugin;
    this.app = plugin.app;
    this.timer = null;
    this.tails = {};
    this.lines = {}; // source -> redacted lines (each source capped)
    this.polling = false;
  }

  local(key, fallback) {
    const v = this.app.loadLocalStorage(`ignis-control-log-${key}`);
    return v === null || v === undefined ? fallback : v;
  }

  mount(parent) {
    const files = this.plugin.logFiles();
    this.files = files;
    this.source = LOG_SOURCES.some(([v]) => v === this.local("source", "all")) ? this.local("source", "all") : "all";
    this.follow = this.local("follow", "1") === "1";
    this.wrap = this.local("wrap", "1") === "1";
    this.filter = "";

    const wrap = parent.createDiv({ cls: "ignis-logpane" });
    const bar = wrap.createDiv({ cls: "ignis-logbar" });

    const select = bar.createEl("select", { cls: "dropdown", attr: { "aria-label": "Which log to show" } });
    for (const [value, label] of LOG_SOURCES) select.createEl("option", { value, text: label });
    select.value = this.source;
    select.addEventListener("change", () => {
      this.source = select.value;
      this.app.saveLocalStorage("ignis-control-log-source", this.source);
      this.renderAll();
    });

    const filter = bar.createEl("input", { type: "search", cls: "ignis-logfilter", attr: { placeholder: "Filter…", "aria-label": "Show only lines containing" } });
    filter.addEventListener("input", () => {
      this.filter = filter.value.trim().toLowerCase();
      this.renderAll();
    });

    const toggle = (label, on, change) => {
      const l = bar.createEl("label", { cls: "ignis-logopt" });
      const cb = l.createEl("input", { type: "checkbox" });
      cb.checked = on;
      l.appendText(` ${label}`);
      cb.addEventListener("change", () => change(cb.checked));
    };
    toggle("Follow new lines", this.follow, (on) => {
      this.follow = on;
      this.app.saveLocalStorage("ignis-control-log-follow", on ? "1" : "0");
      if (on) this.scrollToEnd(true);
    });
    toggle("Wrap lines", this.wrap, (on) => {
      this.wrap = on;
      this.app.saveLocalStorage("ignis-control-log-wrap", on ? "1" : "0");
      this.applyWrap();
      this.scrollToEnd();
    });

    const copy = bar.createEl("button", { cls: "clickable-icon", attr: { "aria-label": "Copy the lines shown" } });
    setIcon(copy, "copy");
    copy.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(this.shown().join("\n"));
        new Notice("Ignis: log copied (secret-looking values are hidden). Check it for paths before sharing it.");
      } catch (e) {
        new Notice(`Ignis: could not copy the log (${e.message}).`);
      }
    });

    this.box = wrap.createDiv({ cls: "ignis-logview", attr: { tabindex: "0", role: "log", "aria-live": "off" } });
    this.where = wrap.createDiv({ cls: "ignis-logsource" });
    this.applyWrap();
    this.renderAll();

    const tick = () => this.poll();
    this.timer = window.setInterval(tick, LOG_POLL_MS);
    this.plugin.registerInterval(this.timer); // also cleared if the plugin unloads with the tab open
    tick();
  }

  unmount() {
    if (this.timer !== null) window.clearInterval(this.timer);
    this.timer = null;
  }

  fileFor(source) {
    return source === "build" ? this.files.build : this.files.main;
  }

  async poll() {
    if (this.polling || this.timer === null) return;
    this.polling = true;
    try {
      for (const key of ["main", "build"]) {
        const file = this.files[key];
        if (!file) continue;
        if (key === "build" && this.source !== "build" && !this.tails.build) continue; // read only once asked for
        const tail = (this.tails[key] ??= new LogTail(fs.promises, file));
        const r = await tail.poll();
        const added = [];
        if (r.restarted) added.push(`(${path.basename(file)} started again from its beginning: it was replaced or emptied)`);
        if (r.skipped) added.push(`(${r.skipped} bytes skipped: the log grew faster than the pane reads it)`);
        const site = siteHost(this.plugin.status);
        added.push(...r.lines.map((l) => redactLine(l, site)));
        if (key === "build") {
          if (r.restarted) this.lines.build = [];
          this.add("build", added);
        } else {
          this.add("all", added);
          const by = {};
          for (const l of added) (by[lineSource(l)] ??= []).push(l);
          for (const [s, ls] of Object.entries(by)) this.add(s, ls);
        }
        tail.missing = r.missing;
      }
      this.showWhere();
    } catch (e) {
      this.where?.setText(`Could not read the log: ${e.message}`);
    } finally {
      this.polling = false;
    }
  }

  add(source, lines) {
    if (!lines.length) return;
    pushCapped((this.lines[source] ??= []), lines, LOG_MAX_LINES);
    if (source !== this.source) return;
    const shown = lines.filter((l) => this.matches(l));
    if (!shown.length) return;
    this.box.querySelector(".ignis-logempty")?.remove();
    for (const l of shown) this.lineEl(l);
    while (this.box.childElementCount > LOG_MAX_LINES) this.box.firstElementChild?.remove();
    this.scrollToEnd();
  }

  matches(line) {
    return !this.filter || line.toLowerCase().includes(this.filter);
  }

  shown() {
    return (this.lines[this.source] ?? []).filter((l) => this.matches(l)).slice(-LOG_MAX_LINES);
  }

  lineEl(line) {
    this.box.createDiv({ cls: `ignis-logline is-${lineLevel(line)}`, text: line });
  }

  renderAll() {
    if (!this.box) return;
    if (this.source === "build" && !this.tails.build) this.poll();
    this.box.empty();
    const lines = this.shown();
    for (const l of lines) this.lineEl(l);
    if (!lines.length) this.box.createDiv({ cls: "ignis-logempty", text: this.filter ? "No line matches the filter." : "No lines yet." });
    this.showWhere();
    this.scrollToEnd(true);
  }

  showWhere() {
    const file = this.fileFor(this.source);
    if (!file) {
      this.where.setText(this.source === "build" ? "The vault's folder is not known." : "The Ignis folder is not known on this device: set it under This panel.");
      return;
    }
    const tail = this.tails[this.source === "build" ? "build" : "main"];
    const n = (this.lines[this.source] ?? []).length;
    this.where.setText(tail?.missing ? `${file}: not there yet` : `${file} (${n} line${n === 1 ? "" : "s"} kept, at most ${LOG_MAX_LINES})`);
  }

  applyWrap() {
    this.box.toggleClass("is-wrap", this.wrap);
    this.box.toggleClass("is-nowrap", !this.wrap);
  }

  scrollToEnd(force = false) {
    if (this.box && (force || this.follow)) this.box.scrollTop = this.box.scrollHeight;
  }
}

// for the tests in test/ (plain Node, with Obsidian's module stubbed)
module.exports.forTests = { isLauncherImage, imageFromTasklist, tasklistPath, checkLauncherProcess,
  lineSource, lineLevel, redactLine, siteHost, LogTail, pushCapped, LOG_MAX_LINES };
