# Plugin integration

Obsidian plugins that work with Ignis Control. Each one runs in the browser through Ignis and reaches something on
the PC through the relay ([relay.md](../relay.md)).

| Plugin | Relay service | What it gets from the PC | Page |
| --- | --- | --- | --- |
| [LaTeX](https://github.com/Gameboard-dev/latex) | `latex` | A sandboxed LuaLaTeX build of `LaTeX/compiled/main.tex` | [LaTeX.md](LaTeX.md) |
| [Augmented View](https://github.com/Gameboard-dev/obsidian-augmented-view) | `augmented-view` | The model server that desktop Obsidian runs | [Augmented-View.md](Augmented-View.md) |

Each page has the same sections: why the integration exists, how a request flows, its scope, set-up on the PC and in
the plugin, and status, logs and failures.
