// Build the studio's vendored JavaScript (docs/studio-plan.md P0.5).
//
//   cd tools/vendor && npm ci && node build.mjs
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
// <lib>: its entries. "draw" builds Mermaid and Excalidraw together so they
// share chunks: mermaid-to-excalidraw imports Mermaid's internals.
const LIBS = {
  vega: ["vega"],
  draw: ["mermaid", "excalidraw", "mermaid-to-excalidraw"],
};
export const BUDGET = { vega: 1_500_000, draw: 10_000_000 };
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
  await build({
    entryPoints: Object.fromEntries(LIBS[lib].map(e => [e, path.join(HERE, "entries", e + ".js")])),
    outdir, bundle: true, format: "esm", splitting: true, minify: true,
    target: "es2020", platform: "browser", legalComments: "linked",
    chunkNames: "chunks/[name]-[hash]", assetNames: "assets/[name]-[hash]",
    loader: { ".woff2": "file", ".ttf": "file", ".png": "file", ".svg": "file" },
    define: { "process.env.NODE_ENV": '"production"', "process.env.IS_PREACT": '"false"' },
    logLevel: "warning", plugins: [noCdnFonts],
  });
  if (lib === "draw") {
    const dist = path.join(HERE, "node_modules/@excalidraw/excalidraw/dist/prod");
    fs.copyFileSync(path.join(dist, "index.css"), path.join(outdir, "excalidraw.css"));
    copyDir(path.join(dist, "fonts"), path.join(outdir, "fonts"), SKIP_FONTS);
  }
}

function manifest() {
  const files = {};
  const sizes = {};
  for (const lib of Object.keys(LIBS)) {
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
      path.join(HERE, "node_modules", name, "package.json"), "utf8")).version;
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
