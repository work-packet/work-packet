// Build the dash's vendored JavaScript (docs/studio-v2.md §7).
//
//   ivpm update                 # installs tools/vendor/package.json into packages/node
//   node tools/vendor/build.mjs # or: node tools/vendor/build.mjs codemirror
//
// The packages are found in $WPK_NODE_MODULES, else packages/node/node_modules
// (ivpm), else tools/vendor/node_modules (a plain `npm ci` here). The output
// is build output, not committed.
//
// Writes ESM bundles to src/work_packet/dash/vendor/<lib>/ and
// src/work_packet/dash/vendor/manifest.json ({path: {sha256, size}}), which the
// dash serves from (only the files it lists). Checks the sizes against
// BUDGET (bytes per library) and warns above them; README.md lists them.

import { build } from "esbuild";
import { createHash } from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const OUT = path.resolve(HERE, "../../src/work_packet/dash/vendor");
const NODE_MODULES = [process.env.WPK_NODE_MODULES,
  path.resolve(HERE, "../../packages/node/node_modules"),
  path.join(HERE, "node_modules")].find(d => d && fs.existsSync(d));
if (!NODE_MODULES) {
  console.error("build.mjs: no node_modules: run `ivpm update` (or `npm ci` in tools/vendor)");
  process.exit(1);
}
// <lib>: its entries. "draw" builds Mermaid and Excalidraw together so they
// share chunks: mermaid-to-excalidraw imports Mermaid's internals.
const LIBS = {
  vega: ["vega"],
  draw: ["mermaid", "excalidraw", "mermaid-to-excalidraw"],
  codemirror: ["codemirror"],
  term: [],   // xterm.js: copied as built (UMD, loaded by a plain <script>)
};
export const BUDGET = { vega: 1_500_000, draw: 10_000_000, codemirror: 800_000, term: 600_000 };
// term: [from (under node_modules), to (under vendor/term/)]
const TERM = [["@xterm/xterm/lib/xterm.js", "xterm.js"], ["@xterm/xterm/css/xterm.css", "xterm.css"],
  ["@xterm/addon-fit/lib/addon-fit.js", "addon-fit.js"], ["@xterm/xterm/LICENSE", "LICENSE.txt"]];
// Excalidraw's CJK font (Xiaolai, ~13 MB in 209 files) is left out: the
// browser falls back to a system font for those characters.
const SKIP_FONTS = new Set(["Xiaolai"]);

// Excalidraw adds https://esm.sh/... as the last source of every font, after
// EXCALIDRAW_ASSET_PATH. The board's CSP refuses it (and a tailnet may have no
// internet), so each font load logged a violation: drop the fallback.
const noCdnFonts = {
  name: "no-cdn-fonts",
  setup(b) {
    b.onLoad({ filter: /@excalidraw[\\/]excalidraw[\\/]dist[\\/]prod[\\/].*\.js$/ }, async (args) => {
      let src = await fs.promises.readFile(args.path, "utf8");
      const rx = /return (\w+)\.push\(new URL\((\w+),(\w+)\.ASSETS_FALLBACK_URL\)\),\1/;
      if (src.includes("ASSETS_FALLBACK_URL)") ) {
        if (!rx.test(src)) throw new Error("no-cdn-fonts: the fallback code changed in " + args.path);
        src = src.replace(rx, "return $1");
      }
      return { contents: src, loader: "js" };
    });
  },
};

function rm(dir) {
  fs.rmSync(dir, { recursive: true, force: true });
}

function copyDir(src, dst, skip = new Set()) {
  fs.mkdirSync(dst, { recursive: true });
  for (const e of fs.readdirSync(src, { withFileTypes: true })) {
    if (skip.has(e.name)) continue;
    const s = path.join(src, e.name), d = path.join(dst, e.name);
    if (e.isDirectory()) copyDir(s, d);
    else fs.copyFileSync(s, d);
  }
}

function walk(dir, out = []) {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, e.name);
    if (e.isDirectory()) walk(p, out);
    else out.push(p);
  }
  return out;
}

async function bundle(lib) {
  const outdir = path.join(OUT, lib);
  rm(outdir);
  if (lib === "term") {
    fs.mkdirSync(outdir, { recursive: true });
    for (const [from, to] of TERM) fs.copyFileSync(path.join(NODE_MODULES, from), path.join(outdir, to));
    return;
  }
  await build({
    entryPoints: Object.fromEntries(LIBS[lib].map(e => [e, path.join(HERE, "entries", e + ".js")])),
    outdir, bundle: true, format: "esm", splitting: true, minify: true,
    target: "es2020", platform: "browser", legalComments: "linked",
    chunkNames: "chunks/[name]-[hash]", assetNames: "assets/[name]-[hash]",
    loader: { ".woff2": "file", ".ttf": "file", ".png": "file", ".svg": "file" },
    define: { "process.env.NODE_ENV": '"production"', "process.env.IS_PREACT": '"false"' },
    logLevel: "warning", plugins: [noCdnFonts], nodePaths: [NODE_MODULES],
  });
  if (lib === "draw") {
    const dist = path.join(NODE_MODULES, "@excalidraw/excalidraw/dist/prod");
    fs.copyFileSync(path.join(dist, "index.css"), path.join(outdir, "excalidraw.css"));
    copyDir(path.join(dist, "fonts"), path.join(outdir, "fonts"), SKIP_FONTS);
  }
}

function manifest() {
  const files = {};
  const sizes = {};
  for (const lib of Object.keys(LIBS)) {
    if (!fs.existsSync(path.join(OUT, lib))) continue;
    for (const p of walk(path.join(OUT, lib)).sort()) {
      const rel = path.relative(OUT, p).split(path.sep).join("/");
      const buf = fs.readFileSync(p);
      files[rel] = { sha256: createHash("sha256").update(buf).digest("hex"), size: buf.length };
      sizes[lib] = (sizes[lib] || 0) + buf.length;
    }
  }
  const versions = {};
  const pkg = JSON.parse(fs.readFileSync(path.join(HERE, "package.json"), "utf8"));
  for (const name of Object.keys(pkg.dependencies)) {
    versions[name] = JSON.parse(fs.readFileSync(
      path.join(NODE_MODULES, name, "package.json"), "utf8")).version;
  }
  fs.writeFileSync(path.join(OUT, "manifest.json"),
    JSON.stringify({ versions, budget: BUDGET, files }, null, 1) + "\n");
  return sizes;
}

const only = process.argv.slice(2);
for (const lib of Object.keys(LIBS)) {
  if (only.length && !only.includes(lib)) continue;
  await bundle(lib);
}
const sizes = manifest();
for (const lib of Object.keys(LIBS)) {
  const n = sizes[lib] || 0;
  const over = n > BUDGET[lib] ? "  ABOVE BUDGET " + BUDGET[lib] : "";
  console.log(`${lib.padEnd(11)} ${(n / 1e6).toFixed(2)} MB${over}`);
}
