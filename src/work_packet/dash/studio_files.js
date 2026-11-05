// The studio's file tree and editor tabs (docs/studio-v2.md §3-§4, V1). The
// tree comes from /studio/tree: the Packet section (the card, the plan, the
// inputs, steps and children, as wp: paths) and the folder, a directory at a
// time. Opening a file pins it (studio.js draws the tabs); a text file's tab is
// an editor (studio_edit.js, CodeMirror; a textarea if it is not built) that
// saves with the sha it read, and a save the file moved under shows a merge.
// Text goes in with textContent only.
(function () {
  "use strict";
  var S = window.wpkStudio;
  var box = document.getElementById("st-files");
  if (!S || !box) return;
  var treeEl = document.getElementById("st-tree");
  var hiddenEl = document.getElementById("st-hidden");
  var open = {"Packet": true, "Plan": true, "Files": true};   // expanded groups and dirs
  var dirs = {};            // folder dir -> its listing
  var data = null;          // the last /tree
  var cardFile = null;      // the card's name in the folder: its changes come as that path
  var fresh = {};           // path -> who changed it since you last opened it
  var eds = {};             // path -> editor tab state (kept across redraws)
  var cm = null;            // the CodeMirror module, once loaded (false: not built)

  function el(tag, cls, t) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (t != null) e.textContent = t;
    return e;
  }
  function q(p) { return encodeURIComponent(p); }
  function alias(path) { return path === cardFile ? "wp:card" : path; }

  // -- the tree -----------------------------------------------------------------
  function load() {
    var h = hiddenEl && hiddenEl.checked ? "&hidden=1" : "";
    S.getJSON("/tree?x=1" + h).then(function (r) {
      if (r[0] !== 200) { treeEl.textContent = r[1].error || "error"; return; }
      data = r[1];
      cardFile = null;
      (data.packet || []).forEach(function (n) { if (n.path === "wp:card") cardFile = n.file; });
      var want = Object.keys(dirs);
      dirs = {};
      Promise.all(want.filter(function (d) { return open["d:" + d]; }).map(loadDir)).then(draw);
    });
  }
  function loadDir(d) {
    var h = hiddenEl && hiddenEl.checked ? "&hidden=1" : "";
    return S.getJSON("/tree?dir=" + q(d) + h).then(function (r) {
      dirs[d] = r[0] === 200 ? r[1].files : [];
    });
  }
  var timer = null;
  function reload() { clearTimeout(timer); timer = setTimeout(load, 400); }

  function row(label, depth, cls) {
    var r = el("div", "ft-row" + (cls ? " " + cls : ""));
    r.style.paddingLeft = (4 + depth * 12) + "px";
    r.appendChild(el("span", "ft-name", label));
    return r;
  }
  function badges(r, n) {
    if (n.access === "read" && !n.dir) r.appendChild(el("span", "ft-ro", "ro"));
    if (n.open) r.appendChild(el("span", "ft-count", String(n.open)));
    var e = eds[n.path];
    if (e && e.dirty) r.appendChild(el("span", "ft-dirty", "●"));
    else if (fresh[n.path]) {
      var b = el("span", "ft-fresh", "●");
      b.title = "changed by " + fresh[n.path];
      r.appendChild(b);
    }
  }
  function node(n, depth, ul) {
    if (n.group || n.dir) {
      var key = n.group ? "g:" + (n.wpid || "") + (n.path || "") + n.name + depth : "d:" + n.path;
      if (n.group && open[n.name] && open[key] === undefined && depth < 2) open[key] = true;
      var r = row((open[key] ? "▾ " : "▸ ") + n.name + (n.dir ? "/" : ""), depth,
        n.group ? "ft-group" : "ft-dir");
      if (n.hidden) r.classList.add("ft-hidden");
      if (n.group && n.access === "read") r.appendChild(el("span", "ft-ro", "ro"));
      r.onclick = function () {
        open[key] = !open[key];
        if (open[key] && n.dir && !n.children && !dirs[n.path]) loadDir(n.path).then(draw);
        else draw();
      };
      ul.appendChild(r);
      if (!open[key]) return;
      var kids = n.children || dirs[n.path];
      if (!kids) { ul.appendChild(row("…", depth + 1, "ft-muted")); return; }
      if (!kids.length) ul.appendChild(row("(empty)", depth + 1, "ft-muted"));
      kids.forEach(function (k) { node(k, depth + 1, ul); });
      return;
    }
    var f = row(n.name, depth, "ft-file");
    f.title = n.path + (n.access === "read" ? " (read-only)" : "");
    if (S.isOpen(n.path)) f.classList.add("on");
    badges(f, n);
    f.onclick = function () { delete fresh[n.path]; S.pin(n.path); };
    ul.appendChild(f);
  }
  function draw() {
    if (!data) return;
    treeEl.textContent = "";
    var pk = el("div", "ft-sec");
    node({group: true, name: "Packet", children: data.packet}, 0, pk);
    pk.firstChild.classList.add("ft-packet");
    treeEl.appendChild(pk);
    var fs = el("div", "ft-sec");
    node({group: true, name: "Files", children: data.files}, 0, fs);
    treeEl.appendChild(fs);
  }
  if (hiddenEl) hiddenEl.onchange = load;
  var newBtn = document.getElementById("st-new");
  if (newBtn) newBtn.onclick = function () {
    var p = prompt("New file (a path in the folder, or wp:state/… for the plan):", "wp:state/notes/");
    if (!p || /\/$/.test(p)) return;
    S.post("/fs", {path: p, text: "", create: true}).then(function (r) {
      if (r[0] !== 200) { S.say(r[1].error || "error", true); return; }
      load();
      S.pin(p);
    });
  };

  // -- editor tabs ----------------------------------------------------------------
  function loadCM() {
    if (cm !== null) return Promise.resolve(cm);
    return import("/static/studio_edit.js").then(function (m) { cm = m; return m; },
      function () { cm = false; return false; });
  }
  function plain(parent, o) {        // the editor when CodeMirror is not built
    var t = el("textarea", "ft-plain");
    t.value = o.text || "";
    t.readOnly = !!o.readOnly;
    t.spellcheck = false;
    t.oninput = function () { if (o.onChange) o.onChange(); };
    t.onkeydown = function (ev) {
      if ((ev.ctrlKey || ev.metaKey) && ev.key === "s") { ev.preventDefault(); if (o.onSave) o.onSave(); }
    };
    parent.appendChild(t);
    return {getText: function () { return t.value; }, setText: function (v) { t.value = v; },
      focus: function () { t.focus(); }, destroy: function () { t.remove(); }};
  }
  function plainMerge(parent, o) {
    var w = el("div", "ft-merge-plain");
    var a = el("textarea"), b = el("textarea");
    a.value = o.mine; b.value = o.theirs; b.readOnly = true;
    w.appendChild(a); w.appendChild(b);
    parent.appendChild(w);
    return {getText: function () { return a.value; }, destroy: function () { w.remove(); }};
  }

  function editorTab(a) {
    var e = eds[a.path];
    if (e) { if (e.dirty === false && e.stale) refreshTab(a.path); return e.node; }
    e = eds[a.path] = {path: a.path, node: el("div", "ft-ed"), dirty: false, sha: null, ed: null};
    var bar = el("div", "ft-bar");
    e.label = el("span", "ft-state", "loading…");
    e.save = el("button", "mini", "Save");
    e.save.type = "button";
    e.save.disabled = true;
    e.save.onclick = function () { save(e); };
    var rl = el("button", "mini", "Reload");
    rl.type = "button";
    rl.onclick = function () {
      if (e.dirty && !confirm("Drop your changes to " + a.path + "?")) return;
      refreshTab(a.path, true);
    };
    var raw = el("a", "mini", "Raw");
    raw.href = S.base + "/file?path=" + q(a.path);
    raw.target = "_blank";
    bar.appendChild(el("code", null, a.path));
    bar.appendChild(e.label);
    bar.appendChild(el("span", "sp"));
    [e.save, rl, raw].forEach(function (x) { bar.appendChild(x); });
    e.body = el("div", "ft-body");
    e.node.appendChild(bar);
    e.node.appendChild(e.body);
    S.getJSON("/fs?path=" + q(a.path)).then(function (r) {
      if (r[0] !== 200) { e.label.textContent = r[1].error || "error"; return; }
      var f = r[1];
      if (f.text == null) {
        e.label.textContent = f.why === "large" ? "too large to edit here" : "not a text file";
        e.body.appendChild(el("div", "st-empty", (f.size || 0) + " bytes. Open it with Raw, or in VS Code."));
        return;
      }
      e.sha = f.sha;
      e.ro = f.access !== "edit";
      return loadCM().then(function (m) {
        var o = {text: f.text, name: f.name, readOnly: e.ro,
          onChange: function () { mark(e, true); }, onSave: function () { save(e); }};
        e.ed = m ? m.makeEditor(e.body, o) : plain(e.body, o);
        mark(e, false);
      });
    });
    return e.node;
  }

  function mark(e, dirty, msg) {
    e.dirty = dirty;
    e.save.disabled = !dirty || e.ro;
    e.label.textContent = msg || (e.ro ? "read-only" : dirty ? "● unsaved" : "saved");
    e.label.className = "ft-state" + (dirty ? " dirty" : "");
    S.tabsChanged();
    draw();
  }

  function save(e, force) {
    if (!e.ed || e.ro || e.saving) return;
    e.saving = true;
    var text = e.ed.getText();
    S.post("/fs", {path: e.path, text: text, sha: e.sha, create: !e.sha}).then(function (r) {
      e.saving = false;
      if (r[0] === 200) { e.sha = r[1].sha; e.stale = false; mark(e, e.ed.getText() !== text); return; }
      if (r[0] === 409 && r[1].stale) { merge(e, text, r[1]); return; }
      mark(e, true, r[1].error || ("error " + r[0]));
    }).catch(function (err) { e.saving = false; mark(e, true, String(err)); });
  }

  // The file changed under you: your text and the file's side by side. Save
  // writes your side over what the file holds now; Take theirs drops yours.
  function merge(e, mine, now) {
    if (now.text == null) {            // deleted under you: saving makes it again
      e.sha = null;
      mark(e, true, "deleted outside; Save makes it again");
      return;
    }
    var panel = el("div", "ft-merge");
    var head = el("div", "ft-bar");
    head.appendChild(el("strong", null, "Changed since you opened it."));
    head.appendChild(el("span", "muted", " Left: yours (edit it; arrows take a change from the right). Right: the file now."));
    head.appendChild(el("span", "sp"));
    var keep = el("button", "mini primary", "Save mine"), take = el("button", "mini", "Take theirs"),
      cancel = el("button", "mini", "Cancel");
    [keep, take, cancel].forEach(function (b) { b.type = "button"; head.appendChild(b); });
    var body = el("div", "ft-body");
    panel.appendChild(head);
    panel.appendChild(body);
    e.node.appendChild(panel);
    e.body.hidden = true;
    var mv = cm ? cm.makeMerge(body, {mine: mine, theirs: now.text, name: e.path}) :
      plainMerge(body, {mine: mine, theirs: now.text});
    function done() { mv.destroy(); panel.remove(); e.body.hidden = false; }
    keep.onclick = function () {
      var t = mv.getText();
      done();
      e.ed.setText(t);
      e.sha = now.sha;
      save(e);
    };
    take.onclick = function () { done(); e.ed.setText(now.text); e.sha = now.sha; mark(e, false); };
    cancel.onclick = function () { done(); mark(e, true, "● unsaved (the file changed outside)"); };
  }

  function refreshTab(path, force) {
    var e = eds[path];
    if (!e || !e.ed) return;
    if (e.dirty && !force) {
      e.stale = true;
      mark(e, true, "● unsaved; the file changed outside (Save shows both)");
      return;
    }
    S.getJSON("/fs?path=" + q(path)).then(function (r) {
      if (r[0] !== 200 || r[1].text == null) return;
      if (r[1].sha === e.sha && !force) return;
      e.ed.setText(r[1].text);
      e.sha = r[1].sha;
      e.stale = false;
      mark(e, false);
    });
  }

  // A Markdown tab: the rendered document (with its comments) or its source.
  var mdMode = {};
  function documentTab(a, rendered) {
    var w = el("div", "ft-doc");
    var bar = el("div", "ft-seg");
    var bR = el("button", "mini", "Rendered"), bS = el("button", "mini", "Source");
    [bR, bS].forEach(function (b) { b.type = "button"; bar.appendChild(b); });
    var slot = el("div", "ft-slot");
    w.appendChild(bar);
    w.appendChild(slot);
    function show() {
      var src = mdMode[a.path] === "source";
      bR.classList.toggle("on", !src);
      bS.classList.toggle("on", src);
      slot.textContent = "";
      slot.appendChild(src ? editorTab(a) : rendered());
    }
    bR.onclick = function () { mdMode[a.path] = "rendered"; show(); };
    bS.onclick = function () { mdMode[a.path] = "source"; show(); };
    if (eds[a.path] && eds[a.path].dirty) mdMode[a.path] = "source";
    show();
    return w;
  }

  window.wpkFiles = {
    editor: editorTab,
    document: documentTab,
    dirty: function (path) { return !!(eds[path] && eds[path].dirty); },
    drop: function (path) {
      var e = eds[path];
      if (e && e.ed) e.ed.destroy();
      delete eds[path];
      draw();
    },
    // A change from the watcher ({path, change, by}).
    changed: function (ev) {
      var p = alias(ev.path);
      if (ev.by !== "you") fresh[p] = ev.by;
      if (ev.change !== "modified") reload();
      else draw();
      if (eds[p] && ev.by !== "you") refreshTab(p);
      if (ev.from && eds[alias(ev.from)]) refreshTab(alias(ev.from));
    },
    redraw: draw,
  };

  window.addEventListener("beforeunload", function (ev) {
    if (Object.keys(eds).some(function (p) { return eds[p].dirty; })) {
      ev.preventDefault();
      ev.returnValue = "";
    }
  });
  load();
})();
