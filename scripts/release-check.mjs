// Checks a release before it is published: the version agrees everywhere, the release has exactly the plugin's three
// files, and none of them holds a path of the computer that built it, an email address, eval, a shell, browser
// storage, or CSS the community directory's lint rejects.
//
//   node scripts/release-check.mjs [--tag x.y.z] [--dir FOLDER]
//
//   --tag   the release's tag (default: manifest.json's version); must equal manifest.json's version
//   --dir   the folder holding main.js, manifest.json and styles.css (default: the repository's root)
//
// Extra words that must not appear (your own name, email, folder or account names) go one per line in the git-ignored
// file .release-scan.local, or in the RELEASE_SCAN_TERMS environment variable (separated by "|"), never in this file,
// which is public. Exits with 1 and says why when a check fails.
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const args = process.argv.slice(2);
const opt = (name) => {
  const i = args.indexOf(name);
  return i >= 0 ? args[i + 1] : undefined;
};
const fail = [];
const read = (p) => fs.readFileSync(p, "utf8");

const manifest = JSON.parse(read(path.join(root, "manifest.json")));
const versions = JSON.parse(read(path.join(root, "versions.json")));
const tag = opt("--tag") ?? manifest.version;
const dir = path.resolve(opt("--dir") ?? root);

if (!/^\d+\.\d+\.\d+$/.test(tag)) fail.push(`the tag ${tag} is not x.y.z (no "v")`);
if (manifest.version !== tag) fail.push(`manifest.json says ${manifest.version}, the tag is ${tag}`);
if (versions[tag] !== manifest.minAppVersion) fail.push(`versions.json has no "${tag}": "${manifest.minAppVersion}"`);
if (!fs.existsSync(path.join(root, ".github", "release-notes", `${tag}.md`))) fail.push(`no .github/release-notes/${tag}.md`);
if (manifest.id !== "ignis-control") fail.push(`the id is ${manifest.id}, not ignis-control`);
if (/obsidian/i.test(manifest.id) || /obsidian/i.test(manifest.name)) fail.push("the id or name contains 'obsidian'");
if (manifest.description.length > 250) fail.push(`the description is ${manifest.description.length} characters (at most 250)`);
if (/obsidian/i.test(manifest.description)) fail.push("the description mentions Obsidian");
if (!manifest.description.endsWith(".")) fail.push("the description does not end with a period");
if (manifest.isDesktopOnly !== true) fail.push("isDesktopOnly is not true (the plugin uses Node's fs and child_process)");

const files = ["main.js", "manifest.json", "styles.css"];
for (const f of files) if (!fs.existsSync(path.join(dir, f))) fail.push(`${f} is missing in ${dir}`);

const terms = [];
const local = path.join(root, ".release-scan.local");
if (fs.existsSync(local)) terms.push(...read(local).split(/\r?\n/).map((l) => l.trim()).filter((l) => l && !l.startsWith("#")));
if (process.env.RELEASE_SCAN_TERMS) terms.push(...process.env.RELEASE_SCAN_TERMS.split("|").map((t) => t.trim()).filter(Boolean));

// Addresses that may appear: GitHub's no-reply form, and the examples the code uses.
const allowedEmail = /@(users\.noreply\.github\.com|example\.(com|org|net|invalid))$/i;
for (const f of files) {
  const p = path.join(dir, f);
  if (!fs.existsSync(p)) continue;
  const text = read(p);
  const userPath = /[A-Za-z]:\\\\?Users\\\\?(?!me\b|you\b|x\b|<you>)[A-Za-z0-9._-]+|\/(home|Users)\/(?!me\b|you\b|runner\b)[A-Za-z0-9._-]+/.exec(text);
  if (userPath) fail.push(`${f} holds a user folder path: ${userPath[0]}`);
  for (const m of text.matchAll(/[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}/g)) {
    if (!allowedEmail.test(m[0])) fail.push(`${f} holds an email address: ${m[0]}`);
  }
  if (/sourceMappingURL=data:/.test(text)) fail.push(`${f} has an inline source map`);
  if (/\beval\(|new Function\(/.test(text)) fail.push(`${f} uses eval or new Function`);
  if (/shell:\s*true/.test(text)) fail.push(`${f} starts a process through a shell`);
  if (f === "main.js" && /\b(window\.localStorage|sessionStorage)\b|[^.\w]localStorage\b/.test(text)) fail.push("main.js uses browser storage (use App.loadLocalStorage / saveLocalStorage)");
  if (f === "main.js" && /\b(execSync|execFileSync|spawnSync)\(|[^.\w]exec\(/.test(text)) fail.push("main.js runs a command line (exec/execSync)");
  if (f === "main.js" && /\.innerHTML\b|\.outerHTML\b|insertAdjacentHTML/.test(text)) fail.push("main.js sets HTML from text");
  if (f === "styles.css") {
    const css = text.replace(/\/\*[\s\S]*?\*\//g, ""); // the rules, without comments
    if (/!important|:has\(/.test(css)) fail.push("styles.css uses !important or :has");
    if (/\btext-decoration|box-decoration-break|(^|[\s;{])(column|row)-gap\s*:/m.test(css)) fail.push("styles.css uses text-decoration, box-decoration-break, column-gap or row-gap (the directory's CSS lint)");
  }
  for (const t of terms) if (text.toLowerCase().includes(t.toLowerCase())) fail.push(`${f} holds a word from the scan list (${t.length} characters)`);
}

if (fail.length) {
  console.error("release-check: NOT ready\n- " + fail.join("\n- "));
  process.exit(1);
}
console.log(`release-check: ${manifest.name} ${tag} is ready (${files.join(", ")} in ${path.relative(root, dir) || "."}; ${terms.length} extra scan term(s)).`);
