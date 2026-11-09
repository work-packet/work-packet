# Vendored JavaScript for the dash

The dash's pages need xterm.js (the browser shell and the studio's agent
terminal), CodeMirror (the studio's editor), Vega-Lite, Mermaid and
Excalidraw. The board's CSP is `script-src 'self'` and a tailnet may have no
internet, so they are bundled and served from the package
(docs/studio-v2.md §7).

**The bundles are build output, not committed:**
`src/work_packet/dash/vendor/` is gitignored.

## Build

```sh
ivpm update                  # installs package.json here into packages/node
node tools/vendor/build.mjs  # or: node tools/vendor/build.mjs codemirror
```

`ivpm.yaml` (`default-dev`) imports this `package.json` with the
`package.json` source, so `ivpm update` installs the packages into
`packages/node/node_modules` (and links `./node_modules` to it). No
`npm ci` by hand. `build.mjs` finds them in `$WPK_NODE_MODULES`, else
`packages/node/node_modules`, else `tools/vendor/node_modules` (a plain
`npm install` here, without ivpm).

It writes `dash/vendor/<lib>/` and `dash/vendor/manifest.json` (every file
with its sha256 and size, the versions, the size budget):

- ESM bundles by esbuild for `vega`, `draw`, `codemirror` and `novnc`
  (`novnc` for es2022: noVNC uses top-level await);
- `term`: xterm.js and its fit addon copied as they are built (UMD,
  loaded by a plain `<script>`).

The dash serves only what the manifest lists, at `/static/vendor/<path>`.
It reads the manifest once, so restart a running dash after a build.
Without a build, the dash still runs: chart pages say the JavaScript is not
built (`vendored.NOT_BUILT`), the shell is not offered, and
`tests/test_studio_vendor.py` skips.

To upgrade: change the versions in `package.json` (direct dependencies are
pinned exactly), `ivpm update`, rebuild, run the tests (and the `live`
ones: `WPK_LIVE=1 pytest -m live tests/test_studio_*`), and update the
table below.

Transitive versions come from ivpm's `packages/node/package-lock.json`,
which is not committed, so two builds a month apart can differ in a
dependency's dependency. How releases get reproducible bundles is open
(docs/studio-v2.md §11).

## What is in it

| Bundle | Entry | Packages | Licence |
|---|---|---|---|
| `vega/vega.js` | `entries/vega.js` | vega 6.4.0, vega-lite 6.5.0, vega-embed 7.3.0, vega-interpreter 2.3.2 | BSD-3-Clause |
| `draw/mermaid.js` | `entries/mermaid.js` | mermaid 11.17.2 | MIT |
| `draw/excalidraw.js`, `draw/excalidraw.css`, `draw/fonts/` | `entries/excalidraw.js` | @excalidraw/excalidraw 0.18.1, react 18.3.1, react-dom 18.3.1 | MIT |
| `draw/mermaid-to-excalidraw.js` | `entries/mermaid-to-excalidraw.js` | @excalidraw/mermaid-to-excalidraw 2.2.2 | MIT |
| `codemirror/codemirror.js` | `entries/codemirror.js` | codemirror 6.0.2, @codemirror/state 6.7.6, view 6.43.15, language 6.13.1, lang-markdown 6.5.2, lang-python 6.2.1, lang-json 6.0.2, lang-yaml 6.1.3, legacy-modes 6.5.5 (shell, TOML, Verilog/SV, C/C++, diff, CMake), merge 6.12.3 | MIT |
| `novnc/novnc.js` | `entries/novnc.js` | @novnc/novnc 1.7.0 (the desktop tab, docs/desktop.md) | MPL-2.0 (`novnc/LICENSE.txt`) |
| `term/xterm.js`, `term/xterm.css`, `term/addon-fit.js` | copied | @xterm/xterm 6.0.0, @xterm/addon-fit 0.11.0 | MIT (`term/LICENSE.txt`) |

Third-party licence comments are collected in `*.LEGAL.txt` next to each
bundle.

Choices made:

- **Mermaid 11, not 12**: mermaid-to-excalidraw 2.2.2 (the version Excalidraw
  0.18.1 uses) imports Mermaid 11's internals. One Mermaid serves both.
- **React 18**: Excalidraw 0.18's radix-ui dependencies declare React ≤ 18.
- **Mermaid and Excalidraw are built together** (`draw/`) so they share
  chunks; built apart, Mermaid was in the tree twice (3.4 MB more).
- **No CJK font**: Excalidraw's Xiaolai font is ~13 MB in 209 files; left
  out (`SKIP_FONTS`), the browser falls back to a system font.
- **No CDN fonts**: Excalidraw appends `https://esm.sh/...` as the last
  source of every font; the `no-cdn-fonts` esbuild plugin in `build.mjs`
  drops it (it fails the build if Excalidraw's code changes shape), so the
  fonts come only from `EXCALIDRAW_ASSET_PATH` (set it to
  `/static/vendor/draw/`) and the CSP logs nothing.
- **Vega under the CSP**: Vega compiles expressions with `new Function`,
  which `script-src 'self'` refuses. Pass `{ast: true, expr:
  expressionInterpreter}` to `embed()` (both exported by `vega.js`).

## Sizes and budget

Built 2026-10-31 (budget in `build.mjs`, `BUDGET`; the build and
`vendored.check()` warn above it):

| Library | Size | Budget |
|---|---|---|
| vega | 0.84 MB (2 files) | 1.5 MB |
| draw | 8.93 MB (219 files: 7.61 MB chunks, 0.88 MB entries and CSS, 0.44 MB fonts) | 10 MB |
| codemirror | 0.74 MB (1 file) | 0.8 MB |
| novnc | 0.19 MB (2 files) | 0.4 MB |
| term | 0.50 MB (4 files) | 0.6 MB |

A page loads only what it uses: a chart page `vega.js` (0.84 MB); Mermaid
loads a diagram type's chunk on first use; the sketch editor loads
Excalidraw and its chunks, and Mermaid only when converting.
