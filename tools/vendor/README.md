# Vendored JavaScript for the studio

The studio's viewers need Vega-Lite, Mermaid and Excalidraw in the browser.
The board's CSP is `script-src 'self'` and a tailnet may have no internet, so
they are bundled here and committed under `src/work_packet/dash/vendor/`
(decision D11 in `docs/studio-plan.md`): Node is needed only to rebuild them.

## Rebuild

```sh
cd tools/vendor
npm ci            # the versions in package-lock.json
node build.mjs    # or: node build.mjs vega   (one library)
```

`build.mjs` (esbuild) writes ESM bundles to `dash/vendor/<lib>/` and
`dash/vendor/manifest.json` (every file with its sha256 and size, the
versions, the size budget). The dash serves only what the manifest lists, at
`/static/vendor/<path>`; `tests/test_studio_vendor.py` fails if the files and
the manifest disagree (a half-done rebuild). Commit the whole of
`dash/vendor/vega/`, `dash/vendor/draw/` and the manifest together.

To upgrade: change the versions in `package.json`, `npm install`, rebuild,
run the tests (and the `live` ones: `WPK_LIVE=1 pytest -m live
tests/test_studio_*`), and update the table below.

## What is in it

| Bundle | Entry | Packages | Licence |
|---|---|---|---|
| `vega/vega.js` | `entries/vega.js` | vega 6.4.0, vega-lite 6.5.0, vega-embed 7.3.0, vega-interpreter 2.3.2 | BSD-3-Clause |
| `draw/mermaid.js` | `entries/mermaid.js` | mermaid 11.17.2 | MIT |
| `draw/excalidraw.js`, `draw/excalidraw.css`, `draw/fonts/` | `entries/excalidraw.js` | @excalidraw/excalidraw 0.18.1, react 18.3.1, react-dom 18.3.1 | MIT |
| `draw/mermaid-to-excalidraw.js` | `entries/mermaid-to-excalidraw.js` | @excalidraw/mermaid-to-excalidraw 2.2.2 | MIT |

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

Built 2026-10-30 (budget in `build.mjs`, `BUDGET`; the build and
`vendored.check()` warn above it):

| Library | Size | Budget |
|---|---|---|
| vega | 0.84 MB (2 files) | 1.5 MB |
| draw | 8.93 MB (219 files: 7.61 MB chunks, 0.88 MB entries and CSS, 0.44 MB fonts) | 10 MB |

A page loads only what it uses: a chart page `vega.js` (0.84 MB); Mermaid
loads a diagram type's chunk on first use; the sketch editor loads
Excalidraw and its chunks, and Mermaid only when converting.
