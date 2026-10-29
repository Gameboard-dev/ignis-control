// Stop's check that a process id is the launcher before it is killed (main.js, checkLauncherProcess).
// Run: node test/stop_test.js   (Windows; uses the real tasklist.exe; kills only the Python process it starts itself)

const assert = require("assert");
const Module = require("module");
const { spawn } = require("child_process");

// main.js requires Obsidian's module, which exists only inside Obsidian: a stand-in with what main.js reads at load
const load = Module._load;
Module._load = function (request, ...rest) {
  if (request === "obsidian") {
    const Base = class {};
    return { Plugin: Base, PluginSettingTab: Base, Setting: Base, Modal: Base, Notice: Base,
      Platform: { isDesktopApp: true }, requestUrl: () => null };
  }
  return load.call(this, request, ...rest);
};
const { isLauncherImage, imageFromTasklist, tasklistPath, checkLauncherProcess } = require("../main.js").forTests;

async function main() {
  // the parser and the names
  const csv = '"python.exe","1234","Console","1","12,000 K"\r\n"node.exe","56","Console","1","1 K"\r\n';
  assert.strictEqual(imageFromTasklist(csv, 1234), "python.exe");
  assert.strictEqual(imageFromTasklist(csv, 56), "node.exe");
  assert.strictEqual(imageFromTasklist(csv, 123), "", "a prefix of another id is not that id");
  assert.strictEqual(imageFromTasklist("INFO: No tasks are running which match the specified criteria.", 7), "");
  for (const ok of ["python.exe", "pythonw.exe", "PythonW.EXE"]) assert.ok(isLauncherImage(ok), ok);
  for (const bad of ["node.exe", "Obsidian.exe", "python.exe.exe", "notpython.exe", "", "python"]) assert.ok(!isLauncherImage(bad), bad);
  assert.ok(/[\\/]System32[\\/]tasklist\.exe$/i.test(tasklistPath()), tasklistPath());

  if (process.platform !== "win32") {
    console.log("stop: parser checked; process checks need Windows");
    return;
  }
  // invalid ids are refused before anything runs
  for (const bad of [0, -1, 1.5, NaN, "1234", null, undefined]) assert.ok(await checkLauncherProcess(bad), String(bad));
  // this Node process is not the launcher
  const self = await checkLauncherProcess(process.pid);
  assert.ok(self && /node\.exe/i.test(self), self);
  // a process id nobody has
  assert.ok(/no longer exists/.test(await checkLauncherProcess(4294967)));
  // a Python process is accepted (a stand-in for the launcher, ended here)
  const py = spawn("python", ["-c", "import time; time.sleep(30)"], { stdio: "ignore", windowsHide: true });
  const started = await new Promise((r) => { py.once("spawn", () => r(true)); py.once("error", () => r(false)); });
  if (started) {
    try {
      assert.strictEqual(await checkLauncherProcess(py.pid), null);
    } finally {
      py.kill();
    }
  } else {
    console.log("stop: no python on PATH; the accepted case was not run");
  }
  console.log("stop: all checks passed");
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
