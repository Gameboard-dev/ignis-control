# LaTeX: remote Markdown-to-LaTeX build

Ignis Control compiles the LaTeX plugin's document on the PC when the vault is open in a browser through Ignis.

The plugin itself, its conversion rules and its settings are documented in
[the LaTeX plugin's README](https://github.com/Gameboard-dev/latex#readme). This page covers the PC side.

## Why

The [LaTeX](https://github.com/Gameboard-dev/latex) plugin converts Markdown notes into a LaTeX document and compiles
it. A page in a browser cannot run TeX. When the vault is open in a browser and desktop Obsidian is closed on the PC,
nothing would compile the document after a save. In a browser through Ignis the plugin converts the notes and asks
Ignis Control to compile the PDF on the PC (it detects Ignis by itself; there is no setting to turn on).

## How it flows

1. The plugin in the browser saves the converted `.tex` files into `<vault>\LaTeX\compiled\`.
2. The plugin sends `GET /relay/latex/status`. A build is possible when `available` is `true` and `desktop_open` is
   `false`.
3. The plugin sends `POST /relay/latex/compile`.
4. The Ignis server passes the request and its `Cf-Access-Jwt-Assertion` header through the relay's pipe. The
   `latex` service is the only one that receives this header.
5. The launcher verifies the Cloudflare Access token ([security.md](../security.md#how-the-latex-build-verifies-the-token)),
   checks that TinyTeX and `main.tex` are present, that desktop Obsidian is not running, and that no build is running.
6. The launcher answers 202 `{"started": true}` and runs the build in the background.
7. The plugin sends `GET /relay/latex/status` every 3 s until `running` is `false`, then reads `last`.

## Scope

**It does:**

- build one document, `<vault>\LaTeX\compiled\main.tex`;
- run one fixed sequence:
  1. highlight code listings with Pygments, in the launcher's own process;
  2. `lualatex.exe --no-shell-escape --interaction=nonstopmode --file-line-error --synctex=1 main.tex`;
  3. `biber.exe --noconf --input-directory <build> --output-directory <build> main`, only if `main.bcf` exists;
  4. `makeglossaries.exe main`, only if `main.glo` or `main.acn` exists;
  5. the LuaLaTeX command twice more;
- run one build at a time;
- stop a build that runs longer than 600 s (the build's job object is terminated);
- accept a request only with a valid Cloudflare Access token for an address in `IGNIS_ACCESS_EMAILS`.

**It does not:**

- take a file name, an option, a command or any other input from the request;
- run latexmk or read `latexmkrc`;
- allow shell escape;
- build while desktop Obsidian runs on the PC (409; the desktop plugin builds then);
- convert notes, choose chapters or apply conversion rules. That is the LaTeX plugin's job.

### Code listings

Before the first LuaLaTeX run, for each file `code\<name>.<ext>` in the build folder (any extension except `.tex`)
whose `code\<name>.tex` is missing or older, the launcher writes a Pygments LaTeX block to `code\<name>.tex`. It also
writes `code\pygments-style.tex` with the `default` style's colours. The lexer is chosen by file name; a file with no
lexer is skipped and named in the transcript. The code is read, never run, and no program is started. Without
Pygments in the launcher's Python, listings are left unchanged and the transcript says so.

### The sandbox

Every step except biber runs in the AppContainer `ignis-control.latex`:

| Right | Path |
| --- | --- |
| Read and execute | TinyTeX (`IGNIS_TINYTEX`, default `%APPDATA%\TinyTeX`) |
| Modify | `<vault>\LaTeX\compiled` |
| Network | none |

The launcher grants these two rules at the start of each build.

TeX resolves every folder on a path, which an AppContainer cannot do above its own folders. For the length of a build,
three free drive letters (the first free ones from `Z:` down to `M:`, made with `subst` and removed afterwards)
stand for TinyTeX, the build folder and the container's own folder. The build's environment is a fixed list: `PATH`
is TinyTeX's `bin\windows`; `TEMP`, `TMP`, `HOME`, `USERPROFILE`, `APPDATA`, `LOCALAPPDATA`, `TEXMFVAR`,
`TEXMFCONFIG` and `TEXMFHOME` point into the container's folder.

**biber runs outside the sandbox**, with your rights, because its executable cannot start in an AppContainer. Before
it runs, the launcher reads every data source in `main.bcf` and stops the build unless each one is a plain `.bib`
file name (no path, no URL, no other type) that exists in the build folder. biber gets fixed arguments, `--noconf`,
and the build folder as input and output.

## Set-up on the PC

1. Install TinyTeX (by default at `%APPDATA%\TinyTeX`; elsewhere, set `IGNIS_TINYTEX`), with `biber` and
   `glossaries` and every package the document uses ([installation.md](../installation.md#tinytex)).
2. Optional: `python -m pip install pygments` for the Python that runs the launcher.
3. Find the three Cloudflare Access values ([cloudflare.md](../cloudflare.md#9-the-env-values)) and add them to
   `<root>\ignis\.env`:

   | Key | Value |
   | --- | --- |
   | `IGNIS_ACCESS_TEAM` | `<team>.cloudflareaccess.com` |
   | `IGNIS_ACCESS_AUD` | The Access application's AUD tag |
   | `IGNIS_ACCESS_EMAILS` | `you@example.com` (comma-separated for more) |

   They are read at every request. No restart is needed.
4. Make sure `<vault>\LaTeX\compiled\main.tex` exists.
5. Open `https://vault.example.com/relay/latex/status` in a logged-in browser. The answer must have
   `"available": true`.

## Set-up in the plugin

1. Nothing to turn on: in a browser through Ignis the plugin asks for builds by itself, and desktop Obsidian builds
   as usual.
2. Keep the notes folder at `LaTeX` (the plugin's default). Ignis Control builds `LaTeX/compiled/main.tex` only.
3. The document must compile with LuaLaTeX.

## While desktop Obsidian runs on the PC

The launcher then refuses to build (409), and the desktop plugin builds after every save, one made in the browser
included. The browser follows those builds through the vault, not the relay:

- The desktop plugin writes `LaTeX/compiled/latex-status.json` when a build or a preview starts and ends. The plugin in
  the browser shows it in its status bar: `building on the PC… (started 23:28)`, `built on the PC at 23:28 (preview)`,
  `build failed on the PC at 23:31 (3 errors) — see log`.
- When `main.shown.pdf` changes, the PDF pane in the browser loads the new copy by itself, and the plugin puts it at
  the note's place (sync scrolling).

Both need Ignis to watch those files: the default `IGNIS_IGNORED_PATHS` ignores the build folder's contents except
`main.pdf`, `main.shown.pdf`, `main.synctex.gz` and `latex-status.json`
([configuration.md](../configuration.md#environment-variables)). A file Ignis ignores keeps, in every tab, the size and time
it had when Ignis listed the vault: with the whole folder ignored, the browser asked for the PDF at the same address
after every build and showed the old one, even after a reload. A changed `IGNIS_IGNORED_PATHS` takes effect when Ignis
restarts.

## Status, logs and failures

### Endpoints

| Request | Answer |
| --- | --- |
| `GET /relay/latex/status` | 200 `{"running", "last", "available", "why", "desktop_open"}` |
| `POST /relay/latex/compile` | 202 `{"started": true}` |

`last` is the result of the last build since the launcher started: `by` (the e-mail address), `started`, `ok`,
`exit` (LuaLaTeX's last exit code), `errors` (up to 20 lines), `undefined` (count of undefined references), `seconds`.
A build is `ok` when the last LuaLaTeX run exits 0 and `main.log` has no error lines (lines starting `!`, or holding
`.tex:` and `rror`).

### Files and log lines

| Where | What |
| --- | --- |
| `<vault>\LaTeX\compiled\.ignis-build.log` | The transcript of the last build: each step's exit code and output. Replaced at every build |
| `<vault>\LaTeX\compiled\` | The PDF and the other build files, as a desktop build writes them |
| `<root>\ignis\ignis.log` | `latex build for <address>: ok in <n> s` (or `failed`), and `relay: latex refused (<reason>)` |
| The LaTeX plugin's log | `Ignis build: built in <n> s`, or the reason it did not build |

### Failures

| Answer | Reason | Fix |
| --- | --- | --- |
| 403 `Cloudflare Access is not set up for builds: …` | An `IGNIS_ACCESS_*` key is missing, or the team does not end in `.cloudflareaccess.com` | Fix `.env` |
| 403 `no Cloudflare Access token …` | The request did not come through the tunnel | Use the public hostname |
| 403 `token expired or not yet valid` | The Access session ended | Reload the page and log in again |
| 403 `token for another application` | `IGNIS_ACCESS_AUD` is wrong | Copy the AUD tag again |
| 403 `token from another team` | `IGNIS_ACCESS_TEAM` is wrong | Fix the team domain |
| 403 `this account may not build` | The address is not in `IGNIS_ACCESS_EMAILS`, or it is a service token | Add the address |
| 403 `token signed with an unknown key` | Cloudflare rotated its keys | Retry; the keys are fetched again |
| 503 `no TinyTeX at …` | TinyTeX or one of its three programs is missing | Install TinyTeX and `tlmgr install biber glossaries` |
| 503 `the build folder is not the vault's LaTeX/compiled, or it has no main.tex` | `main.tex` is missing, or `LaTeX\compiled` resolves outside the vault | Build once with the plugin; do not link the folder elsewhere |
| 409 `Obsidian is open on the PC: …` | Desktop Obsidian runs on the PC | Expected: the desktop plugin builds |
| 409 `a build is running` | One build at a time | Wait for it to end |
| `ok: false` after about 600 s, or with `the build ran past 600 s` | The 600 s limit stopped a step | Find the slow step in `.ignis-build.log` |
| `ok: false` with `main.bcf names a data source …` | biber would read a file that is not a `.bib` in the build folder | Keep the bibliography as a `.bib` file in `LaTeX\compiled` |
| `ok: false` with `no free drive letters for the build` | Fewer than three of `M:` to `Z:` are free | Free drive letters |
