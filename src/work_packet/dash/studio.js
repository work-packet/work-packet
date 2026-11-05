// The studio page (docs/studio-plan.md S1.5-S1.6): the canvas, the conversation
// with the studio's agent, and the close dialog. The server does the work
// (dash/studio.py); this draws what it sends. Text goes in with textContent only:
// nothing from the agent or the files is HTML here. Documents render in
// same-origin frames (/studio/frame/doc), images from /studio/file.
(function () {
  "use strict";
  var root = document.getElementById("studio");
  if (!root) return;
  var base = root.dataset.base, csrf = root.dataset.csrf;
  var out = document.getElementById("st-out");
  var tabs = document.getElementById("st-tabs");
  var tiles = document.getElementById("st-tiles");
  var text = document.getElementById("st-text");
  var send = document.getElementById("st-send");
  var stop = document.getElementById("st-stop");
  var stateEl = document.getElementById("st-state");
  var two = document.getElementById("st-two");
  var canvas = {canvas: [], layout: {mode: "tabs", open: []}};
  var lastBy = {};          // path -> who changed it last
  var lastT = 0, sock = null, retry = 1000;

  function el(tag, cls, t) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (t != null) e.textContent = t;
    return e;
  }
  function q(p) { return encodeURIComponent(p); }
  var folder = root.dataset.folder || "";
  function short(t) {        // the agent's paths, relative to the studio's folder
    return folder ? String(t).split(folder + "/").join("") : String(t);
  }
  function post(path, body) {
    return fetch(base + path, {method: "POST", credentials: "same-origin",
      headers: {"content-type": "application/json", "x-csrf-token": csrf},
      body: JSON.stringify(body || {})})
      .then(function (r) { return r.json().then(function (j) { return [r.status, j]; }); });
  }
  function say(msg, bad) {
    stateEl.textContent = msg || "";
    stateEl.style.color = bad ? "var(--FAILED)" : "";
  }

  // -- the canvas -----------------------------------------------------------------
  function kindOf(a) { return a.kind || (/\.(md|markdown)$/i.test(a.path) ? "document" : null); }

  function getJSON(url) {
    return fetch(base + url, {credentials: "same-origin"})
      .then(function (r) { return r.json().then(function (j) { return [r.status, j]; }); });
  }

  // A table (S2.3): pages from the kernel, sort by a column, filter per column,
  // column stats, and a SQL box (one SELECT; save it as a .sql to keep it).
  function tableViewer(a, small) {
    var box = el("div", "st-table" + (small ? " small" : ""));
    var s = {offset: 0, limit: small ? 5 : 100, sort: null, desc: false, filters: {},
             table: null, sql: null};
    var bar = el("div", "tb-bar"), msg = el("span", "muted tb-msg");
    var grid = el("div", "tb-grid"), stats = el("div", "tb-stats");
    stats.hidden = true;
    var sqlBox = el("div", "tb-sql");
    sqlBox.hidden = true;
    var pick = null;
    if (!small && /\.(sqlite3?|db)$/i.test(a.path)) {
      pick = el("select");
      pick.onchange = function () { s.table = pick.value; s.offset = 0; load(); };
      bar.appendChild(pick);
      getJSON("/table/tables?path=" + q(a.path)).then(function (r) {
        (r[1].tables || []).forEach(function (t) { var o = el("option", null, t); o.value = t; pick.appendChild(o); });
      });
    }
    var prev = el("button", "mini", "‹"), next = el("button", "mini", "›"), where = el("span", "muted");
    prev.type = next.type = "button";
    prev.onclick = function () { s.offset = Math.max(0, s.offset - s.limit); load(); };
    next.onclick = function () { s.offset += s.limit; load(); };
    if (!small) {
      var bStats = el("button", "mini", "Stats"), bSql = el("button", "mini", "SQL");
      bStats.type = bSql.type = "button";
      bStats.onclick = function () { stats.hidden = !stats.hidden; if (!stats.hidden) loadStats(); };
      bSql.onclick = function () { sqlBox.hidden = !sqlBox.hidden; };
      [prev, where, next, bStats, bSql].forEach(function (x) { bar.appendChild(x); });
      var ta = el("textarea"), saved = /\.sql$/i.test(a.path);
      ta.placeholder = (saved ? "SELECT …" : "SELECT … FROM '" + a.path + "'") +
        " (one SELECT over the folder's files; Ctrl+Enter runs)";
      if (saved) {             // a saved query: the box starts from its text
        fetch(base + "/file?path=" + q(a.path), {credentials: "same-origin"})
          .then(function (r) { return r.ok ? r.text() : ""; })
          .then(function (t) { if (!ta.value) ta.value = t.trim(); });
      }
      var run = el("button", "mini", "Run"), save = el("button", "mini", "Save as .sql…"), back = el("button", "mini", "Back to the file");
      run.type = save.type = back.type = "button";
      run.onclick = function () { s.sql = ta.value; s.offset = 0; s.sort = null; s.filters = {}; load(); };
      ta.addEventListener("keydown", function (ev) {
        if (ev.key === "Enter" && (ev.ctrlKey || ev.metaKey)) { ev.preventDefault(); run.onclick(); }
      });
      back.onclick = function () { s.sql = null; s.offset = 0; load(); };
      save.onclick = function () {
        var to = window.prompt("Save the query as (a .sql file in the folder):", "queries/query.sql");
        if (!to) return;
        post("/sql/save", {sql: ta.value, path: to}).then(function (r) {
          msg.textContent = r[0] === 200 ? "saved " + r[1].path + ": Pin it to keep it on the canvas" : (r[1].error || "error " + r[0]);
          if (r[0] === 200) post("/pin", {path: r[1].path}).then(took);
        });
      };
      [ta, run, save, back].forEach(function (x) { sqlBox.appendChild(x); });
    }
    bar.appendChild(msg);
    [bar, sqlBox, stats, grid].forEach(function (x) { box.appendChild(x); });

    function draw(r) {
      grid.textContent = "";
      var t = el("table"), head = el("thead"), hr = el("tr"), fr = el("tr", "tb-filter"), body = el("tbody");
      r.columns.forEach(function (c) {
        var th = el("th", null, c.name + (s.sort === c.name ? (s.desc ? " ▼" : " ▲") : ""));
        th.title = c.type + (small ? "" : " · click to sort");
        if (!small) th.onclick = function () {
          if (s.sort === c.name) s.desc = !s.desc; else { s.sort = c.name; s.desc = false; }
          s.offset = 0; load();
        };
        hr.appendChild(th);
        if (!small) {
          var td = el("td"), inp = el("input");
          inp.value = s.filters[c.name] || "";
          inp.placeholder = "filter";
          inp.addEventListener("keydown", function (ev) {
            if (ev.key !== "Enter") return;
            s.filters[c.name] = inp.value; s.offset = 0; load();
          });
          td.appendChild(inp);
          fr.appendChild(td);
        }
      });
      head.appendChild(hr);
      if (!small) head.appendChild(fr);
      r.rows.forEach(function (row) {
        var tr = el("tr");
        row.forEach(function (v) {
          var td = el("td", v === null ? "null" : (typeof v === "number" ? "num" : null), v === null ? "null" : String(v));
          tr.appendChild(td);
        });
        body.appendChild(tr);
      });
      t.appendChild(head); t.appendChild(body); grid.appendChild(t);
      var end = Math.min(r.total, r.offset + r.rows.length);
      where.textContent = r.total ? (r.offset + 1) + "–" + end + " of " + r.total : "no rows";
      prev.disabled = r.offset <= 0;
      next.disabled = end >= r.total;
      if (small && r.total > r.rows.length) grid.appendChild(el("div", "muted", r.rows.length + " of " + r.total + " rows"));
    }
    function load() {
      msg.textContent = "…";
      var p;
      if (s.sql != null) {
        p = post("/sql", {sql: s.sql, offset: s.offset, limit: s.limit, sort: s.sort, desc: s.desc, filters: s.filters});
      } else {
        var u = "/table?path=" + q(a.path) + "&offset=" + s.offset + "&limit=" + s.limit +
          (s.table ? "&table=" + q(s.table) : "") + (s.sort ? "&sort=" + q(s.sort) + (s.desc ? "&desc=1" : "") : "");
        Object.keys(s.filters).forEach(function (k) { if (s.filters[k]) u += "&f." + q(k) + "=" + q(s.filters[k]); });
        p = getJSON(u);
      }
      p.then(function (r) {
        if (r[0] !== 200) { msg.textContent = r[1].error || ("error " + r[0]); return; }
        msg.textContent = s.sql != null ? "query" : "";
        draw(r[1]);
      }).catch(function (e) { msg.textContent = String(e); });
    }
    function loadStats() {
      getJSON("/table/stats?path=" + q(a.path) + (s.table ? "&table=" + q(s.table) : "")).then(function (r) {
        stats.textContent = "";
        if (r[0] !== 200) { stats.appendChild(el("span", "muted", r[1].error || "error")); return; }
        var t = el("table"), hr = el("tr");
        ["column", "type", "nulls %", "min", "max", "distinct"].forEach(function (h) { hr.appendChild(el("th", null, h)); });
        t.appendChild(hr);
        r[1].columns.forEach(function (c) {
          var tr = el("tr");
          [c.name, c.type, c.nulls, c.min, c.max, c.distinct].forEach(function (v) {
            tr.appendChild(el("td", null, v === null || v === undefined ? "" : String(v)));
          });
          t.appendChild(tr);
        });
        stats.appendChild(t);
      });
    }
    box.reload = function () { load(); if (!stats.hidden) loadStats(); };
    load();
    return box;
  }

  function viewer(a, small) {
    var k = kindOf(a), stamp = "&t=" + (a.mtime || Date.now());
    if (k === "document" && window.wpkFiles && !small) {      // rendered or source (v2 §4)
      return window.wpkFiles.document(a, function () {
        var f = el("iframe");
        f.title = a.path;
        f.src = base + "/frame/doc?path=" + q(a.path);
        f.dataset.path = a.path;
        return f;
      });
    }
    if (k === "document" || k === "chart") {
      var f = el("iframe");
      f.title = a.path;
      f.src = base + "/frame/" + (k === "chart" ? "chart" : "doc") + "?path=" + q(a.path);
      f.dataset.path = a.path;
      return f;
    }
    if (k === "table") return tableViewer(a, small);
    if (k === "image") {
      var w = el("div", small ? null : "img"), img = el("img");
      img.alt = a.path;
      img.src = base + "/file?path=" + q(a.path) + stamp;
      img.dataset.path = a.path;
      w.appendChild(img);
      return w;
    }
    return window.wpkFiles ? window.wpkFiles.editor(a) : el("div", "st-empty", a.path);
  }

  function drawCanvas() {
    tabs.textContent = "";
    var open = canvas.layout.open || [];
    canvas.canvas.forEach(function (a) {
      var b = el("button", "st-tab" + (open.indexOf(a.path) >= 0 ? " on" : ""), tabName(a.path));
      b.type = "button";
      b.title = (a.kind || "file") + (a.missing ? " (missing)" : "");
      b.title = a.path;
      if (window.wpkFiles && window.wpkFiles.dirty(a.path)) b.appendChild(el("span", "dirty", "●"));
      else if (lastBy[a.path]) b.appendChild(el("span", "by", lastBy[a.path]));
      var x = el("span", "x", "×");
      x.title = "Close";
      x.onclick = function (ev) {
        ev.stopPropagation();
        var F = window.wpkFiles;
        if (F && F.dirty(a.path) && !confirm("Close " + a.path + " without saving?")) return;
        if (F) F.drop(a.path);
        post("/unpin", {path: a.path}).then(took);
      };
      b.appendChild(x);
      b.onclick = function () {
        var want = canvas.layout.mode === "two-up" ? open.filter(function (p) { return p !== a.path; }).slice(-1).concat([a.path]) : [a.path];
        post("/layout", {open: want}).then(took);
      };
      tabs.appendChild(b);
    });
    tiles.textContent = "";
    tiles.className = "st-tiles" + (canvas.layout.mode === "two-up" ? " two" : "");
    var shown = canvas.canvas.filter(function (a) { return open.indexOf(a.path) >= 0; });
    if (!shown.length) {
      tiles.appendChild(el("div", "st-empty", canvas.canvas.length ?
        "Pick a tab to open it." : "Open a file from the tree, or ask for something."));
      return;
    }
    shown.forEach(function (a) {
      var t = el("div", "st-tile");
      t.dataset.path = a.path;
      t.appendChild(viewer(a));
      tiles.appendChild(t);
    });
  }

  function took(a) {
    if (a[0] !== 200) { say(a[1].error || ("error " + a[0]), true); return; }
    canvas = a[1];
    drawCanvas();
    if (window.wpkFiles) window.wpkFiles.redraw();
  }

  // A tab's label: the file's name, with the plan's paths shown as such.
  function tabName(p) {
    if (p === "wp:card") return "card";
    var n = p.split("/").pop();
    return /^wp:state\//.test(p) ? "plan: " + n : /^wp:/.test(p) ? n + " (ro)" : n;
  }

  function refresh(path) {
    tiles.querySelectorAll(".st-tile").forEach(function (t) {
      if (t.dataset.path !== path) return;
      var f = t.querySelector("iframe");
      if (f) { try { f.contentWindow.location.reload(); } catch (e) { f.src = f.src; } }
      var img = t.querySelector("img");
      if (img) img.src = base + "/file?path=" + q(path) + "&t=" + Date.now();
      var tb = t.querySelector(".st-table");
      if (tb && tb.reload) tb.reload();
    });
  }

  // A data file changed: the tables and charts open on the canvas may read it
  // (a saved query, a chart's data), so they all load again.
  var DATA = /\.(csv|tsv|parquet|jsonl|ndjson|sql|db|sqlite3?)$/i;
  function refreshData(except) {
    tiles.querySelectorAll(".st-tile").forEach(function (t) {
      if (t.dataset.path === except) return;
      var k = kindOf(canvas.canvas.filter(function (a) { return a.path === t.dataset.path; })[0] || {path: ""});
      if (k === "table" || k === "chart") refresh(t.dataset.path);
    });
  }

  function loadCanvas() {
    fetch(base + "/canvas", {credentials: "same-origin"})
      .then(function (r) { return r.json().then(function (j) { return [r.status, j]; }); })
      .then(took).catch(function (e) { say(String(e), true); });
  }

  if (two) two.onchange = function () {
    post("/layout", {mode: two.checked ? "two-up" : "tabs"}).then(took);
  };

  // -- the conversation -------------------------------------------------------------
  function put(node) {
    var stick = out.scrollHeight - out.scrollTop - out.clientHeight < 60;
    out.appendChild(node);
    if (stick) out.scrollTop = out.scrollHeight;
  }

  function outputCard(ev) {
    (ev.files || []).forEach(function (f) {
      var c = el("div", "st-card");
      var row = el("div", "row");
      row.appendChild(el("strong", null, f.path));
      row.appendChild(el("span", "muted", f.change + (f.kind ? " · " + f.kind : "")));
      if (f.gone) {            // deleted since: nothing to pin or show
        row.appendChild(el("span", "muted", "· deleted since"));
        c.appendChild(row);
        put(c);
        return;
      }
      var pin = el("button", "mini", "Pin");
      pin.type = "button";
      pin.onclick = function () { post("/pin", {path: f.path}).then(took); };
      var open = el("a", "mini", "Open");
      open.href = f.kind === "document" || f.kind === "chart" ?
        base + "/frame/" + (f.kind === "chart" ? "chart" : "doc") + "?path=" + q(f.path) :
        base + "/file?path=" + q(f.path);
      open.target = "_blank";
      row.appendChild(pin);
      row.appendChild(open);
      c.appendChild(row);
      if (f.kind) c.appendChild(viewer({path: f.path, kind: f.kind}, true));
      put(c);
    });
  }

  function show(ev) {
    if (ev.t) lastT = Math.max(lastT, ev.t);
    var k = ev.k;
    if (k === "busy") {
      stop.hidden = !ev.on;
      send.disabled = !!ev.on;
      say(ev.on ? "working…" : "");
    } else if (k === "ask") {
      put(el("div", "st-ev ask", ev.text));
    } else if (k === "say") {
      put(el("div", "st-ev say", ev.text));
    } else if (k === "tool") {
      put(el("div", "st-ev tool", "· " + ev.name + " " + short(ev.what || "")));
    } else if (k === "end") {
      setTimeout(loadVersions, 1500);
      put(el("div", "st-ev end" + (ev.ok ? "" : " bad"),
        (ev.ok ? "done" : "stopped: " + (ev.error || "error")) +
        (ev.cost ? " · $" + Number(ev.cost).toFixed(3) + " so far" : "")));
    } else if (k === "output") {
      outputCard(ev);
      setTimeout(loadVersions, 800);       // the turn's version follows its card
    } else if (k === "changed") {
      lastBy[ev.path] = ev.by === "you" ? "you" : ev.by;
      if (window.wpkFiles) window.wpkFiles.changed(ev);
      if (ev.by !== "agent") put(el("div", "st-ev changed", ev.path + " " + ev.change + " by " + ev.by));
      var pinned = canvas.canvas.some(function (a) { return a.path === ev.path; });
      if (pinned) { refresh(ev.path); drawTabsOnly(); }
      if (DATA.test(ev.path)) refreshData(ev.path);
    } else if (k === "note" || k === "cmd") {
      put(el("div", "st-ev tool", ev.text || ev.line || ""));
    }
  }

  // For studio_files.js (the tree and the editor tabs).
  window.wpkStudio = {
    base: base, csrf: csrf, post: post, getJSON: getJSON, say: say,
    pin: function (path) { return post("/pin", {path: path}).then(took); },
    isOpen: function (path) { return (canvas.layout.open || []).indexOf(path) >= 0; },
    tabsChanged: function () { drawTabsOnly(); },
  };

  function drawTabsOnly() {
    tabs.querySelectorAll(".st-tab").forEach(function (b, i) {
      var a = canvas.canvas[i];
      if (!a) return;
      var dirty = window.wpkFiles && window.wpkFiles.dirty(a.path), dot = b.querySelector(".dirty");
      if (dirty && !dot) b.insertBefore(el("span", "dirty", "●"), b.querySelector(".x"));
      if (!dirty && dot) dot.remove();
      var by = b.querySelector(".by");
      if (lastBy[a.path] && !dirty) {
        if (!by) { by = el("span", "by"); b.insertBefore(by, b.querySelector(".x")); }
        by.textContent = lastBy[a.path];
      }
    });
  }

  function connect() {
    if (!root.dataset.conv) return;
    var proto = location.protocol === "https:" ? "wss://" : "ws://";
    sock = new WebSocket(proto + location.host + base + "/ws?since=" + lastT);
    sock.onopen = function () { retry = 1000; sock.send(JSON.stringify({token: csrf})); };
    sock.onmessage = function (m) { try { show(JSON.parse(m.data)); } catch (e) { /* skip */ } };
    sock.onclose = function () {
      say("reconnecting…");
      setTimeout(connect, retry);
      retry = Math.min(retry * 2, 15000);
    };
  }

  function ask() {
    var t = text.value.trim();
    if (!t) return;
    send.disabled = true;
    post("/ask", {text: t}).then(function (a) {
      if (a[0] !== 200) { send.disabled = false; say(a[1].error || ("error " + a[0]), true); return; }
      text.value = "";
    }).catch(function (e) { send.disabled = false; say(String(e), true); });
  }
  send.onclick = ask;
  text.addEventListener("keydown", function (ev) {
    if (ev.key === "Enter" && (ev.ctrlKey || ev.metaKey)) { ev.preventDefault(); ask(); }
  });
  stop.onclick = function () { post("/cancel", {}); };

  // -- versions (S3.3): the strip, view, compare, flip, restore, keep ---------------------
  var strip = document.getElementById("st-strip"), verBox = document.getElementById("st-ver");
  var vers = [], keyAt = {}, viewing = null, other = null, picking = false, flipped = false;
  var verPoll = null;

  function when(t) { var d = new Date(t * 1000); return d.toTimeString().slice(0, 5); }

  // keyAt[n][path]: the render of each file as it was at version n (the newest
  // render at or before n: a version names the renders of what it changed).
  function index() {
    keyAt = {};
    var cur = {};
    vers.forEach(function (v) {
      (v.deleted || []).forEach(function (p) { delete cur[p]; });
      v.changed.forEach(function (c) { cur[c.path] = {key: c.key, kind: c.kind, n: v.n, ready: c.ready, checks: c.checks}; });
      var snap = {};
      v.files.forEach(function (p) { if (cur[p]) snap[p] = cur[p]; else snap[p] = {key: null, kind: null, n: null}; });
      keyAt[v.n] = snap;
    });
  }

  function picture(n, path) {      // an <img> of path as it was at version n, or a note
    var a = (keyAt[n] || {})[path];
    if (!a) return el("div", "muted", "not in v" + n);
    if (a.kind === "image" || (!a.key && /\.(png|jpe?g|gif|webp|svg)$/i.test(path))) {
      var im = el("img"); im.alt = path; im.src = base + "/version/" + n + "/file?path=" + q(path); return im;
    }
    if (!a.key) return el("div", "muted", "no picture for this kind");
    if (!a.ready) return el("div", "muted", "rendering…");
    var i = el("img"); i.alt = path + " at v" + n; i.src = base + "/render/" + a.key + "/full.png"; return i;
  }

  function drawStrip() {
    strip.textContent = "";
    vers.forEach(function (v) {
      var b = el("button", "st-chip" + (viewing === v.n || other === v.n ? " on" : "") + (picking ? " pick" : ""));
      b.type = "button";
      var first = v.changed.filter(function (c) { return c.key || c.kind === "image"; })[0];
      var th = el("div", "th");
      if (first && first.kind === "image") th.style.backgroundImage = "url(" + JSON.stringify(base + "/version/" + v.n + "/file?path=" + q(first.path)) + ")";
      else if (first && first.ready) th.style.backgroundImage = "url(" + JSON.stringify(base + "/render/" + first.key + "/thumb.png") + ")";
      b.appendChild(th);
      var flags = v.changed.reduce(function (k, c) { return k + (c.checks || []).length; }, 0);
      var line = el("span", null, "v" + v.n + (v.keep ? " ★" : "") + " · " + v.by);
      if (flags) line.appendChild(el("span", "flag", " ⚑" + flags));
      b.appendChild(line);
      b.appendChild(el("span", null, when(v.at) + (v.note ? " · " + v.note : "")));
      b.title = v.changed.map(function (c) { return c.path; }).concat((v.deleted || []).map(function (p) { return p + " (deleted)"; })).join("\n");
      b.onclick = function () {
        if (picking) { picking = false; other = v.n; flipped = false; }
        else { viewing = viewing === v.n ? null : v.n; other = null; }
        drawStrip(); drawVersion();
      };
      strip.appendChild(b);
    });
    strip.scrollLeft = strip.scrollWidth;
  }

  function drawVersion() {
    if (viewing == null) { verBox.hidden = true; tiles.hidden = false; return; }
    tiles.hidden = true; verBox.hidden = false; verBox.textContent = "";
    var v = vers.filter(function (x) { return x.n === viewing; })[0];
    if (!v) { viewing = null; return drawVersion(); }
    var bar = el("div", "vbar");
    bar.appendChild(el("strong", null, "v" + v.n));
    bar.appendChild(el("span", "muted", v.by + " · " + when(v.at) + (v.note ? " · " + v.note : "")));
    function btn(t, fn, title) { var b = el("button", "mini", t); b.type = "button"; b.onclick = fn; if (title) b.title = title; bar.appendChild(b); return b; }
    btn("Back to now", function () { viewing = null; other = null; drawStrip(); drawVersion(); });
    btn(v.keep ? "Unkeep" : "Keep", function () { post("/keep", {n: v.n, keep: !v.keep}).then(loadVersions); },
        "Mark the versions worth showing first");
    btn("Restore", function () {
      if (!window.confirm("Write v" + v.n + "'s files back? (The files as they are now stay as a version.)")) return;
      post("/restore", {n: v.n}).then(function (r) {
        say(r[0] === 200 ? (r[1].version ? "restored v" + v.n + " as v" + r[1].version.n : "already v" + v.n) : (r[1].error || "error"), r[0] !== 200);
        viewing = null; other = null; loadVersions();
      });
    }, "Write this version's files back, as a new version");
    btn(other == null ? "Compare with…" : "Stop comparing", function () {
      if (other != null) { other = null; picking = false; } else { picking = true; say("pick a version in the strip to compare with"); }
      drawStrip(); drawVersion();
    });
    if (other != null) btn("Flip", function () { flipped = !flipped; drawVersion(); }, "Show one in place of the other");
    verBox.appendChild(bar);
    var paths = v.changed.map(function (c) { return c.path; });
    if (other != null) {
      var o = vers.filter(function (x) { return x.n === other; })[0];
      (o ? o.changed : []).forEach(function (c) { if (paths.indexOf(c.path) < 0) paths.push(c.path); });
    }
    paths.forEach(function (p) {
      verBox.appendChild(el("div", null, p));
      var a = (keyAt[v.n] || {})[p];
      if (a && a.checks && a.checks.length && a.n === v.n) {
        verBox.appendChild(el("div", "checks", a.checks.map(function (c) { return "⚑ " + c.check + ": " + c.what; }).join("\n")));
      }
      var cols = el("div", "cols" + (other != null && !flipped ? " two" : ""));
      if (other == null) cols.appendChild(picture(v.n, p));
      else if (flipped) { cols.appendChild(el("div", "muted", "v" + other)); cols.appendChild(picture(other, p)); }
      else {
        var l = el("div"), r = el("div");
        l.appendChild(el("div", "muted", "v" + v.n)); l.appendChild(picture(v.n, p));
        r.appendChild(el("div", "muted", "v" + other)); r.appendChild(picture(other, p));
        cols.appendChild(l); cols.appendChild(r);
      }
      verBox.appendChild(cols);
    });
    (v.deleted || []).forEach(function (p) { verBox.appendChild(el("div", "muted", p + " deleted in this version")); });
  }

  function loadVersions() {
    getJSON("/versions").then(function (r) {
      if (r[0] !== 200) return;
      vers = r[1].versions || [];
      index(); drawStrip(); drawVersion();
      var waiting = vers.some(function (v) { return v.changed.some(function (c) { return c.key && !c.ready; }); });
      clearTimeout(verPoll);
      if (waiting && r[1].renders === "on") verPoll = setTimeout(loadVersions, 3000);
    }).catch(function () {});
  }

  // -- closing ----------------------------------------------------------------------
  var dlg = document.getElementById("st-close");
  document.getElementById("st-close-open").onclick = function () {
    var box = document.getElementById("st-summary");
    box.value = "Drafting a summary…";
    if (dlg.showModal) dlg.showModal(); else dlg.setAttribute("open", "");
    fetch(base + "/draft", {credentials: "same-origin"}).then(function (r) { return r.json(); })
      .then(function (j) { box.value = j.text || ""; })
      .catch(function () { box.value = ""; });
  };
  document.getElementById("st-close-cancel").onclick = function () { dlg.close(); };

  loadCanvas();
  loadVersions();
  connect();
})();
