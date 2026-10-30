// A studio chart in its frame (docs/studio-plan.md S2.4). Vega-Lite through
// vega-embed with vega-interpreter (the frame's CSP has no unsafe-eval), in the
// studio's theme; selections (brush, click) become "Ask about these rows",
// which the board answers with the rows themselves; the spec panel writes mark,
// encodings and title back into the spec. Text goes in with textContent only.
import { embed, expressionInterpreter } from "/static/vendor/vega/vega.js";

const root = document.getElementById("ch");
const base = root.dataset.base, path = root.dataset.path, csrf = root.dataset.csrf;
const msg = document.getElementById("ch-msg");
const spec = JSON.parse(document.getElementById("ch-spec").textContent);
const themes = JSON.parse(document.getElementById("ch-theme").textContent);
const dark = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
let selection = null;

function post(url, body) {
  return fetch(base + url, {method: "POST", credentials: "same-origin",
    headers: {"content-type": "application/json", "x-csrf-token": csrf},
    body: JSON.stringify(body)})
    .then((r) => r.json().then((j) => [r.status, j]));
}

// The selection params, wherever they are in the spec: {name: "interval" | "point"}.
function selections(s, out) {
  if (Array.isArray(s)) { s.forEach((x) => selections(x, out)); return out; }
  if (s && typeof s === "object") {
    (s.params || []).forEach((p) => {
      if (p && p.select) out[p.name] = typeof p.select === "string" ? p.select : p.select.type;
    });
    Object.keys(s).forEach((k) => { if (k !== "params" && k !== "data") selections(s[k], out); });
  }
  return out;
}

function clean(v) {        // Vega's selection value, less its own bookkeeping
  const out = {};
  Object.keys(v || {}).forEach((k) => {
    if (!/^(vl|_vg)/.test(k) && Array.isArray(v[k]) && v[k].length) out[k] = v[k];
  });
  return out;
}

function showSel() {
  const box = document.getElementById("ch-sel");
  const keys = selection ? Object.keys(selection).filter((k) => k !== "kind") : [];
  box.hidden = !keys.length;
  document.getElementById("ch-sel-what").textContent = keys.map((k) => {
    const v = selection[k];
    return selection.kind === "point" ? k + " in " + v.join(", ")
      : k + " " + v.map((x) => typeof x === "number" ? +x.toFixed(3) : x).join("–");
  }).join("; ");
}

function ask() {
  const q = document.getElementById("ch-q");
  if (!selection) return;
  msg.textContent = "asking…";
  post("/select", {path: path, selection: selection, text: q.value}).then(([st, j]) => {
    msg.textContent = st === 200 ? "asked: the answer is in the conversation" : (j.error || "error " + st);
    if (st === 200) q.value = "";
  }).catch((e) => { msg.textContent = String(e); });
}
document.getElementById("ch-ask").onclick = ask;
document.getElementById("ch-q").addEventListener("keydown", (ev) => {
  if (ev.key === "Enter") { ev.preventDefault(); ask(); }
});

const view = Object.assign({}, spec);
if (view.mark && view.width === undefined) view.width = "container";
view.config = Object.assign({}, themes[dark ? "dark" : "light"], spec.config || {});

embed("#chart", view, {ast: true, expr: expressionInterpreter, renderer: "svg", actions: false})
  .then((res) => {
    const sels = selections(spec, {});
    Object.keys(sels).forEach((name) => {
      res.view.addSignalListener(name, (n, v) => {
        const c = clean(v);
        selection = Object.keys(c).length ? Object.assign({kind: sels[name]}, c) : null;
        showSel();
      });
    });
    if (!Object.keys(sels).length) {
      msg.textContent = "No selection in this chart: add a param with select (interval or point) to ask about rows.";
    }
    window.__studioReady = true;
  })
  .catch((e) => { msg.textContent = "Vega: " + e; window.__studioReady = true; });

// -- the spec panel ------------------------------------------------------------------
const panel = document.getElementById("ch-panel");
if (panel && root.dataset.source) {
  fetch(base + "/table?limit=1&path=" + encodeURIComponent(root.dataset.source),
        {credentials: "same-origin"})
    .then((r) => r.json()).then((j) => {
      (j.columns || []).forEach((c) => {
        panel.querySelectorAll('select[data-k="field"]').forEach((s) => {
          if ([...s.options].some((o) => o.value === c.name)) return;
          const o = document.createElement("option");
          o.value = c.name; o.textContent = c.name + " (" + c.type.toLowerCase() + ")";
          s.appendChild(o);
        });
      });
    }).catch(() => {});
  document.getElementById("ch-save").onclick = () => {
    const out = {mark: document.getElementById("ch-mark").value,
                 title: document.getElementById("ch-title").value};
    ["x", "y", "color"].forEach((ch) => {
      out[ch] = {};
      panel.querySelectorAll('[data-ch="' + ch + '"]').forEach((s) => { out[ch][s.dataset.k] = s.value; });
    });
    const m = document.getElementById("ch-save-msg");
    m.textContent = "saving…";
    post("/chart", {path: path, panel: out}).then(([st, j]) => {
      if (st === 200) location.reload(); else m.textContent = j.error || "error " + st;
    }).catch((e) => { m.textContent = String(e); });
  };
}
