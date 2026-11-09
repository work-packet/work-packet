// The desktop tab (docs/desktop.md D6): noVNC on /desk/<key>/ws, plus a bar
// with the state xproxy reports (/desk/<key>/state).
import { RFB } from "/static/vendor/novnc/novnc.js";

const key = document.body.dataset.key;
const csrf = document.body.dataset.csrf;
const screen = document.getElementById("screen");
const msg = document.getElementById("msg");
const dot = document.getElementById("dot");
const statusEl = document.getElementById("status");
const appsEl = document.getElementById("apps");
const again = document.getElementById("again");
const fit = document.getElementById("fit");
const quality = document.getElementById("quality");
const clip = document.getElementById("clip");
const cliptext = document.getElementById("cliptext");

const store = {
  get(k, d) { try { return localStorage.getItem("wpk.desk." + k) ?? d; } catch { return d; } },
  set(k, v) { try { localStorage.setItem("wpk.desk." + k, v); } catch { /* private window */ } },
};
fit.value = store.get("fit", "remote");
quality.value = store.get("quality", "6");

let rfb = null;
let wanted = true;          // reconnect by itself after a drop, until the user says otherwise

function show(text) {
  msg.textContent = text;
  msg.hidden = !text;
}

function say(state, text) {
  dot.className = state;
  statusEl.textContent = text;
}

function applyFit() {
  if (!rfb) return;
  rfb.resizeSession = fit.value === "remote";
  rfb.scaleViewport = fit.value === "scale";
  rfb.clipViewport = fit.value === "none";
}

function connect() {
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  const url = `${proto}//${location.host}/desk/${key}/ws?t=${encodeURIComponent(csrf)}`;
  show("Connecting to the desktop…");
  say("warn", "connecting…");
  again.hidden = true;
  rfb = new RFB(screen, url, { wsProtocols: ["binary"], shared: true });
  rfb.background = "var(--desk)";
  rfb.qualityLevel = Number(quality.value);
  rfb.compressionLevel = 2;
  rfb.focusOnClick = true;
  applyFit();
  rfb.addEventListener("connect", () => {
    show("");
    say("ok", "connected");
    rfb.focus();
  });
  rfb.addEventListener("disconnect", (e) => {
    rfb = null;
    again.hidden = false;
    say("bad", e.detail.clean ? "disconnected" : "connection lost");
    refresh().then((st) => {
      if (!st.desktop) {
        show(st.why || "No desktop.");
      } else if (wanted && !e.detail.clean) {
        show("Connection lost; trying again…");
        setTimeout(() => { if (!rfb && wanted) connect(); }, 2000);
      } else {
        show("Disconnected.");
      }
    });
  });
  rfb.addEventListener("clipboard", (e) => {
    cliptext.value = e.detail.text;
    if (navigator.clipboard && document.hasFocus()) {
      navigator.clipboard.writeText(e.detail.text).catch(() => {});
    }
  });
}

// The Apps menu: [desktop.apps] that can start on the server's host.
const appsbtn = document.getElementById("appsbtn");
const appsmenu = document.getElementById("appsmenu");
let launchers = null;      // not yet known

function fillApps(list) {
  const key2 = JSON.stringify(list || []);
  if (key2 === JSON.stringify(launchers)) return;
  launchers = list || [];
  appsmenu.replaceChildren();
  appsbtn.disabled = false;
  if (!launchers.length) {
    const p = document.createElement("div");
    p.className = "muted";
    // No list at all: the server started before the Apps menu existed.
    p.textContent = list ? "No apps: add [desktop.apps] to config.toml"
      : "Close VS Code and open it again from the board to get the Apps menu";
    appsmenu.append(p);
    return;
  }
  for (const a of launchers) {
    const b = document.createElement("button");
    b.type = "button";
    b.textContent = a.label;
    b.addEventListener("click", () => startApp(a));
    appsmenu.append(b);
  }
}

async function startApp(a) {
  appsmenu.hidden = true;
  say(dot.className, "starting " + a.label + "…");
  try {
    const r = await fetch(`/desk/${key}/run`, {
      method: "POST", headers: { "x-csrf-token": csrf,
                                 "content-type": "application/x-www-form-urlencoded" },
      body: "app=" + encodeURIComponent(a.name) });
    const j = await r.json();
    if (!r.ok) say("warn", j.why || "could not start " + a.label);
    else setTimeout(() => say(rfb ? "ok" : dot.className, rfb ? "connected" : "connecting…"), 1500);
  } catch {
    say("warn", "could not reach the board");
  }
  if (!rfb && wanted) connect();
}

appsbtn.addEventListener("click", (e) => { e.stopPropagation(); appsmenu.hidden = !appsmenu.hidden; });
document.addEventListener("click", (e) => { if (!appsmenu.contains(e.target)) appsmenu.hidden = true; });

async function refresh() {
  try {
    const r = await fetch(`/desk/${key}/state`, { cache: "no-store" });
    const st = await r.json();
    if (st.desktop) {
      fillApps(st.launchers);
      const apps = (st.apps || []).filter((a) => a);
      appsEl.textContent = (st.display ? st.display + " · " : "") +
        (apps.length ? "windows from: " + apps.join(", ") : "no X clients") +
        (st.viewers > 1 ? ` · ${st.viewers} viewers` : "");
    } else {
      appsEl.textContent = "";
    }
    return st;
  } catch {
    return { desktop: true };
  }
}

fit.addEventListener("change", () => { store.set("fit", fit.value); applyFit(); });
quality.addEventListener("change", () => {
  store.set("quality", quality.value);
  if (rfb) rfb.qualityLevel = Number(quality.value);
});
again.addEventListener("click", () => { wanted = true; if (!rfb) connect(); });
document.getElementById("full").addEventListener("click", () => {
  if (document.fullscreenElement) document.exitFullscreen();
  else document.documentElement.requestFullscreen().catch(() => {});
});
document.getElementById("clipbtn").addEventListener("click", () => { clip.hidden = !clip.hidden; });
document.getElementById("clipclose").addEventListener("click", () => { clip.hidden = true; });
document.getElementById("clipsend").addEventListener("click", () => {
  if (rfb) rfb.clipboardPasteFrom(cliptext.value);
  clip.hidden = true;
  if (rfb) rfb.focus();
});
// Text copied on this computer goes to the desktop when the tab gets focus,
// where the browser allows reading the clipboard.
window.addEventListener("focus", () => {
  if (!rfb || !navigator.clipboard || !navigator.clipboard.readText) return;
  navigator.clipboard.readText().then((t) => {
    if (t && t !== cliptext.value) { cliptext.value = t; rfb.clipboardPasteFrom(t); }
  }).catch(() => {});
});

refresh().then((st) => {
  if (st.desktop) connect();
  else { show(st.why || "No desktop."); say("bad", "no desktop"); again.hidden = false; }
});
setInterval(refresh, 5000);
