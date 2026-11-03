// The log pane's parts (main.js): following a file through growth, cut lines, truncation and replacement; which source
// a line of ignis.log belongs to; what is hidden; the line cap. Run: node test/log_test.js (no Obsidian, no launcher).

const assert = require("assert");
const fs = require("fs");
const os = require("os");
const path = require("path");
const Module = require("module");

const load = Module._load;
Module._load = function (request, ...rest) {
  if (request === "obsidian") {
    const Base = class {};
    return { Plugin: Base, PluginSettingTab: Base, Setting: Base, Modal: Base, Notice: Base,
      Platform: { isDesktopApp: true }, requestUrl: () => null, setIcon: () => undefined };
  }
  return load.call(this, request, ...rest);
};
const { lineSource, lineLevel, redactLine, siteHost, LogTail, pushCapped, LOG_MAX_LINES } = require("../main.js").forTests;

async function tail() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "ignis-log-test-"));
  const file = path.join(dir, "ignis.log");
  try {
    const t = new LogTail(fs.promises, file, 16, 64);
    assert.deepStrictEqual(await t.poll(), { lines: [], missing: true, restarted: false, skipped: 0 });

    fs.writeFileSync(file, "old line one\nold line two\nlast\n");
    let r = await t.poll(); // only the end (16 bytes): its cut first line is dropped
    assert.deepStrictEqual(r.lines, ["last"], JSON.stringify(r));

    fs.appendFileSync(file, "new a\nhalf");
    r = await t.poll();
    assert.deepStrictEqual(r.lines, ["new a"]);
    fs.appendFileSync(file, " done\r\n");
    r = await t.poll();
    assert.deepStrictEqual(r.lines, ["half done"], "a line written in two parts comes out whole");
    assert.deepStrictEqual((await t.poll()).lines, []);

    fs.writeFileSync(file, "after truncation\n"); // shorter than what was read: start again
    r = await t.poll();
    assert.ok(r.restarted);
    assert.deepStrictEqual(r.lines, ["after truncation"]);

    fs.renameSync(file, file + ".1"); // rotation: a new file in its place, of any length
    fs.writeFileSync(file, "rotated one\nrotated two and more text to be longer than before\n");
    r = await t.poll();
    if (process.platform !== "win32" || r.restarted) {
      assert.ok(r.restarted, "a replaced file is read from its start");
      assert.deepStrictEqual(r.lines, ["rotated one", "rotated two and more text to be longer than before"]);
    }

    fs.appendFileSync(file, `${"x".repeat(200)}\nend of burst\n`); // more than maxBytes at once: the start is skipped
    r = await t.poll();
    assert.ok(r.skipped > 0, JSON.stringify(r));
    assert.deepStrictEqual(r.lines, ["end of burst"]);
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
}

function sources() {
  const cases = [
    ["2026-10-29 22:13:01 started ignis in AppContainer x.ignis (pid 4)", "launcher"],
    ["2026-10-29 22:13:01   [ignis] GET 500 /api/fs/readFile -- EPERM", "ignis"],
    ["2026-10-29 22:13:01   [ignis] client 7kemmk boot ready", "tabs"],
    ["2026-10-29 22:13:01   [cloudflared] Registered tunnel connection connIndex=0", "cloudflared"],
    ["2026-10-29 22:13:01   [augmented-view] forwarding", "relay"],
    ["2026-10-29 22:13:01 relay: refused POST /x/shutdown: not relayed", "relay"],
    ["2026-10-29 22:13:01 relay: latex refused (token expired)", "latex"],
    ["2026-10-29 22:13:01 latex build for <e-mail>: ok in 31 s", "latex"],
    ["2026-10-29 22:13:01 access: 3 item(s) in the vault lacked the container's rule", "access"],
  ];
  for (const [line, want] of cases) assert.strictEqual(lineSource(line), want, line);
  assert.strictEqual(lineLevel("ignis exited with code 1"), "error");
  assert.strictEqual(lineLevel("cloudflared could not be started"), "error");
  assert.strictEqual(lineLevel("ignis exited with code 0"), "info");
  assert.strictEqual(lineLevel("  [cloudflared] 2026-10-29T22:13:01Z WRN Connection terminated error=\"x\""), "warn");
  assert.strictEqual(lineLevel("  [cloudflared] 2026-10-29T22:13:01Z INF Retrying connection in up to 2s error=\"x\""), "info");
  assert.strictEqual(lineLevel("  [cloudflared] 2026-10-29T22:13:01Z ERR Failed to dial a quic connection"), "error");
}

function redaction() {
  const jwt = "eyJhbGciOiJSUzI1NiIsImtpZCI6IjEyMyJ9.eyJlbWFpbCI6ImFAYi5jIn0.c2lnbmF0dXJlX2hlcmVfbG9uZw";
  const cases = [
    [`token ${jwt} seen`, (o) => !o.includes("eyJ") && o.includes("<token>")],
    ["TUNNEL_TOKEN=abcdefghijklmnopqrstuvwxyz0123", (o) => o === "TUNNEL_TOKEN=<hidden>"],
    ["Cf-Access-Jwt-Assertion: abc.def.ghi", (o) => o === "Cf-Access-Jwt-Assertion: <hidden>"],
    ["cookie: CF_Authorization=secretvalue; other=1", (o) => o === "cookie: <hidden>"],
    // Quarry's service token, which the relay passes on to Quarry (patches/0006-relay.patch)
    [`Authorization: Bearer ${"0f".repeat(32)}`, (o) => o === "Authorization: <hidden>"],
    ["issuer https://myteam-4f8a.cloudflareaccess.com/cdn-cgi", (o) => o === "issuer https://<team>.cloudflareaccess.com/cdn-cgi"],
    [`aud ${"a1b2c3d4".repeat(8)} ok`, (o) => o === "aud <hex> ok"],
    ["password: hunter2hunter2", (o) => o === "password: <hidden>"],
    ["latex build for someone@example.org: ok", (o) => o === "latex build for <e-mail>: ok"],
    [`key ${"Ab3+".repeat(12)}== end`, (o) => o === "key <long value> end"],
    ["\x1b[31mred\x1b[0m text", (o) => o === "red text"],
    ["GET 200 /api/fs/readFile?path=notes/a.md 12 ms", (o) => o === "GET 200 /api/fs/readFile?path=notes/a.md 12 ms"],
    ["tunnelID=0e5b7a2c-1111-4c22-9333-0123456789ab connIndex=0", (o) => o.includes("tunnelID=0e5b7a2c-1111")],
  ];
  for (const [line, ok] of cases) {
    const out = redactLine(line);
    assert.ok(ok(out), `${JSON.stringify(line)} -> ${JSON.stringify(out)}`);
  }
  // the site's own hostname, from the status file's url
  const site = siteHost({ url: "https://vault.example.net" });
  assert.strictEqual(site, "vault.example.net");
  assert.strictEqual(redactLine("WS_ORIGINS=https://vault.example.net,http://localhost:8080", site),
    "WS_ORIGINS=https://<site>,http://localhost:8080");
  assert.strictEqual(siteHost({ url: "not a url" }), "");
  assert.strictEqual(siteHost(null), "");
}

function cap() {
  const list = [];
  pushCapped(list, Array.from({ length: LOG_MAX_LINES + 5 }, (_, i) => i), LOG_MAX_LINES);
  assert.strictEqual(list.length, LOG_MAX_LINES);
  assert.strictEqual(list[0], 5);
  assert.strictEqual(LOG_MAX_LINES, 2000);
}

(async () => {
  await tail();
  sources();
  redaction();
  cap();
  console.log("log: all checks passed");
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
