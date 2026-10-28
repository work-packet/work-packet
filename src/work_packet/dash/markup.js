// Marking up a rendered Markdown file (docs/doc-markup.md). Select text for a
// comment, insertion, deletion or replacement; click an item to accept or reject
// it. Each edit is a POST that writes CriticMarkup into the file; then a reload.
(function () {
  "use strict";
  var doc = document.getElementById("mk-doc");
  if (!doc) return;
  var IGNORE = /[\s*_`~\[\]|\\<>]/g;          // as markup.IGNORE on the server
  var writable = !!doc.dataset.writable;
  var pop = document.createElement("div");
  pop.className = "mkpop";
  pop.setAttribute("role", "dialog");
  document.body.appendChild(pop);
  var editing = false, pending = null;

  function norm(s) { return s.replace(IGNORE, ""); }

  function el(tag, attrs, text) {
    var n = document.createElement(tag);
    for (var k in attrs || {}) n.setAttribute(k, attrs[k]);
    if (text != null) n.textContent = text;
    return n;
  }

  function hide() { pop.style.display = "none"; editing = false; pending = null;
    var on = doc.querySelector(".cm-on"); if (on) on.classList.remove("cm-on"); }

  function place(rect) {
    pop.style.display = "block";
    var w = pop.offsetWidth, x = rect.left + window.scrollX;
    x = Math.max(8, Math.min(x, window.scrollX + document.documentElement.clientWidth - w - 8));
    pop.style.left = x + "px";
    pop.style.top = (rect.bottom + window.scrollY + 6) + "px";
  }

  function error(msg) {
    var e = pop.querySelector(".err") || pop.appendChild(el("div", {"class": "err"}));
    e.textContent = msg;
  }

  function post(body, done) {
    body.path = doc.dataset.path;
    body.wpid = doc.dataset.wpid || null;
    body.sha = doc.dataset.sha;
    fetch(doc.dataset.post, {method: "POST", credentials: "same-origin",
      headers: {"content-type": "application/json", "x-csrf-token": doc.dataset.csrf},
      body: JSON.stringify(body)})
      .then(function (r) { return r.json().then(function (j) { return [r.status, j]; }); })
      .then(function (a) {
        var st = a[0], j = a[1];
        if (st === 200) return done ? done(j) : location.reload();
        error(j.error || ("error " + st));
        if (j.stale) {
          var b = pop.appendChild(el("button", {"class": "mini", type: "button"}, "Reload"));
          b.onclick = function () { location.reload(); };
        }
      })
      .catch(function (e) { error(String(e)); });
  }

  function button(row, label, fn, primary) {
    var b = el("button", {"class": primary ? "go primary" : "mini", type: "button"}, label);
    b.onclick = fn;
    row.appendChild(b);
    return b;
  }

  // --- a selection ----------------------------------------------------------------

  function selection() {
    var s = window.getSelection();
    if (!s || s.rangeCount === 0 || s.isCollapsed) return null;
    var r = s.getRangeAt(0);
    if (!doc.contains(r.commonAncestorContainer)) return null;
    var text = r.toString();
    if (!norm(text)) return null;
    var node = function (n) { return (n.nodeType === 1 ? n : n.parentNode).closest("[data-src]"); };
    var a = node(r.startContainer), b = node(r.endContainer);
    var block = a === b ? a : null;
    var at = 0;
    if (block) {
      var pre = document.createRange();
      pre.setStart(block, 0);
      pre.setEnd(r.startContainer, r.startOffset);
      at = norm(pre.toString()).length;
    }
    return {range: r, text: text, block: block, at: at};
  }

  function offerSelection(sel) {
    hide();
    pop.textContent = "";
    if (!sel.block) {
      pop.appendChild(el("div", {"class": "err"}, "Select within one paragraph, item or cell."));
      return place(sel.range.getBoundingClientRect());
    }
    pending = {lines: sel.block.dataset.src, sel: sel.text, at: sel.at};
    var row = pop.appendChild(el("div", {"class": "row"}));
    button(row, "Comment", function () { ask("comment", "Comment"); }, true);
    button(row, "Insert after", function () { ask("insert", "Text to insert after it"); });
    button(row, "Replace", function () { ask("replace", "Replace it with"); });
    button(row, "Delete", function () { send("delete", ""); });
    place(sel.range.getBoundingClientRect());
  }

  function ask(op, what) {
    editing = true;
    var keep = pending;
    pop.textContent = "";
    pop.appendChild(el("div", {"class": "what"}, what + ":"));
    var ta = pop.appendChild(el("textarea", {"aria-label": what}));
    var row = pop.appendChild(el("div", {"class": "row"}));
    var go = function () { pending = keep; send(op, ta.value); };
    button(row, "Save", go, true);
    button(row, "Cancel", hide);
    ta.addEventListener("keydown", function (ev) {
      if (ev.key === "Enter" && (ev.ctrlKey || ev.metaKey)) { ev.preventDefault(); go(); }
      if (ev.key === "Escape") hide();
    });
    ta.focus();
  }

  function send(op, text) {
    if (!pending) return;
    if (op !== "delete" && op !== "replace" && !text.trim()) return error("Write something first.");
    post({op: op, lines: pending.lines, sel: pending.sel, at: pending.at, text: text});
  }

  // --- an item --------------------------------------------------------------------

  var LABELS = {
    ins: ["Insertion", "Accept", "Reject"], del: ["Deletion", "Accept", "Reject"],
    sub: ["Replacement", "Accept", "Reject"], mark: ["Highlight", "Remove", null],
    comment: ["Comment", "Resolve", null]
  };

  function offerItem(item) {
    hide();
    item.classList.add("cm-on");
    pop.textContent = "";
    var kind = (item.className.match(/cm-(ins|del|sub|mark|comment)/) || [])[1];
    var l = LABELS[kind];
    pop.appendChild(el("div", {"class": "what"}, l[0]));
    var row = pop.appendChild(el("div", {"class": "row"}));
    var body = {raw: item.dataset.cm, n: Number(item.dataset.n || 0)};
    button(row, l[1], function () { body.op = "accept"; post(body); }, true);
    if (l[2]) button(row, l[2], function () { body.op = "reject"; post(body); });
    place(item.getBoundingClientRect());
  }

  // --- events ---------------------------------------------------------------------

  if (writable) {
    var timer = null;
    var check = function () {
      clearTimeout(timer);
      timer = setTimeout(function () {
        if (editing) return;
        var sel = selection();
        if (sel) offerSelection(sel);
      }, 250);
    };
    doc.addEventListener("mouseup", check);
    doc.addEventListener("keyup", check);
    document.addEventListener("selectionchange", function () {
      if (!editing && "ontouchstart" in window) check();
    });
    doc.addEventListener("click", function (ev) {
      var s = window.getSelection();
      if (s && !s.isCollapsed) return;
      var item = ev.target.closest(".cm[data-cm]");
      if (item && doc.contains(item)) { ev.preventDefault(); offerItem(item); }
    });
    document.addEventListener("mousedown", function (ev) {
      if (!pop.contains(ev.target) && !editing) hide();
    });
    document.addEventListener("keydown", function (ev) { if (ev.key === "Escape") hide(); });
  }

  var askBtn = document.getElementById("mk-ask");
  if (askBtn) askBtn.onclick = function () {
    askBtn.disabled = true;
    post({op: "ask"}, function (j) { askBtn.textContent = j.msg || "Asked"; });
  };
  // post() reports into the popover; the ask button has none open, so show it there
  var _error = error;
  error = function (msg) {
    if (pop.style.display !== "block" && askBtn) { askBtn.textContent = msg; askBtn.disabled = false; return; }
    _error(msg);
  };
})();
