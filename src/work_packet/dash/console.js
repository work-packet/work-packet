// Console drawer (docs/console.md): slash commands and the agent, scoped to this page.
// ` (backquote) or the Console button opens it; Esc closes; ↑/↓ history; Tab completes.
// The page's conversation is kept on the server (/console/conv); replies stream on
// /console/ws/<id>. Everything is rendered with textContent: nothing here is HTML.
(function () {
  "use strict";
  var box = document.getElementById("console");
  if (!box) return;
  var out = box.querySelector(".con-out");
  var input = box.querySelector("input");
  var state = box.querySelector(".con-state");
  var stop = box.querySelector(".con-stop");
  var KEY = "wpk.console.";
  var cmds = null;
  var hist = [];
  var at = 0;
  var conv = null;        // the conversation's id
  var sock = null;
  var lastT = 0;
  var seen = {};

  function load(k, d) { try { return JSON.parse(localStorage.getItem(KEY + k)) || d; } catch (e) { return d; } }
  function save(k, v) { try { localStorage.setItem(KEY + k, JSON.stringify(v)); } catch (e) { /* none */ } }
  hist = load("hist", []);
  at = hist.length;

  function setOpen(on) {
    box.hidden = !on;
    document.body.classList.toggle("con-open", on);
    save("open", on);
    if (on) { input.focus(); out.scrollTop = out.scrollHeight; }
  }
  document.querySelectorAll("[data-console]").forEach(function (b) {
    b.addEventListener("click", function () { setOpen(box.hidden); });
  });
  document.addEventListener("keydown", function (ev) {
    var t = ev.target, typing = t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.isContentEditable);
    if (ev.key === "`" && !typing && !ev.ctrlKey && !ev.metaKey && !ev.altKey) {
      ev.preventDefault(); setOpen(true);
    } else if (ev.key === "Escape" && t === input) {
      setOpen(false);
    }
  });

  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }
  function link(text, href) {
    if (!href || href.charAt(0) !== "/" || href.charAt(1) === "/") return el("span", null, text);
    var a = el("a", null, text); a.href = href; return a;
  }
  function put(node) {
    var stick = out.scrollHeight - out.scrollTop - out.clientHeight < 40;
    out.appendChild(node);
    if (stick || !box.hidden) out.scrollTop = out.scrollHeight;
  }

  // -- what a conversation holds -------------------------------------------------
  function card(line, r, how) {
    var c = el("div", "con-card " + (r.ok ? "ok" : "bad"));
    c.appendChild(el("div", "con-in", line + (how ? "  · " + how : "")));
    var head = el("div", "con-head");
    head.appendChild(r.href ? link(r.text, r.href) : el("span", null, r.text));
    c.appendChild(head);
    var lines = r.lines || [], into = c;
    if (how && lines.length > 3) {         // the agent's: folded, the head says enough
      into = el("details");
      into.appendChild(el("summary", "con-line", lines.length + " more lines"));
      c.appendChild(into);
    }
    lines.forEach(function (l) {
      var d = el("div", "con-line");
      d.appendChild(l.href ? link(l.text, l.href) : el("span", null, l.text));
      into.appendChild(d);
    });
    put(c);
  }
  // A proposal (C3): a slash command the agent wrote on a line of its own. The read-only
  // ones ran at once on the server; the others wait for Run or Dismiss.
  var props = {};         // "<say id>:<i>" -> its row
  function mark(ref, how) {
    var row = props[ref];
    if (!row || row.dataset.done) return;
    row.dataset.done = how;
    row.querySelectorAll("button").forEach(function (b) { b.remove(); });
    row.appendChild(el("span", "con-done", how));
  }
  function say(ev) {
    var box2 = el("div", "con-say");
    var at = {};
    (ev.props || []).forEach(function (p) { at[p.at] = p; });
    var text = [];
    function flush() {
      if (text.length) { box2.appendChild(el("span", null, text.join("\n") + "\n")); text = []; }
    }
    ev.text.split("\n").forEach(function (ln, i) {
      var p = at[i];
      if (!p) { text.push(ln); return; }
      flush();
      var ref = ev.id + ":" + p.i;
      var row = el("div", "con-prop");
      row.appendChild(el("code", null, p.line));
      if (!p.auto) {
        var run = el("button", "con-run", "Run");
        run.type = "button";
        run.title = "Run this command, as if you typed it";
        run.addEventListener("click", function () { mark(ref, "ran"); send(p.line, {ref: ref}); });
        var no = el("button", "con-no", "Dismiss");
        no.type = "button";
        no.addEventListener("click", function () { mark(ref, "dismissed"); send("", {decline: ref}); });
        row.appendChild(run); row.appendChild(no);
      }
      props[ref] = row;
      box2.appendChild(row);
    });
    flush();
    put(box2);
  }
  function event(ev) {
    if (ev.k === "busy") { busy(ev.on); return; }
    var key = ev.t + ":" + ev.k + ":" + (ev.text || ev.line || ev.what || ev.ref || "").length;
    if (seen[key]) return;
    seen[key] = true;
    if (ev.t > lastT) lastT = ev.t;
    if (ev.k === "cmd") {
      card(ev.line, ev.out || {}, ev.auto ? "ran at once" : null);
      if (ev.ref) mark(ev.ref, ev.auto ? "ran at once" : "ran");
    }
    else if (ev.k === "decline") mark(ev.ref, "dismissed");
    else if (ev.k === "ask") put(el("div", "con-in con-ask", ev.text));
    else if (ev.k === "say") say(ev);
    else if (ev.k === "tool") put(el("div", "con-tool", "· " + ev.name + " " + (ev.what || "")));
    else if (ev.k === "note") put(el("div", "con-tool", ev.text));
    else if (ev.k === "end") {
      var t = (ev.ok ? "" : (ev.error || "failed") + " · ") + "$" + (ev.cost || 0).toFixed(3) + " so far";
      put(el("div", "con-end" + (ev.ok ? "" : " bad"), t));
    }
  }
  function busy(on) {
    state.textContent = on ? "thinking…" : "";
    stop.hidden = !on;
  }

  function connect() {
    if (sock) { sock.onclose = null; sock.close(); sock = null; }
    if (!conv) return;
    var id = conv;
    var url = (location.protocol === "https:" ? "wss:" : "ws:") + "//" + location.host +
      "/console/ws/" + encodeURIComponent(id) + "?since=" + lastT;
    var s = new WebSocket(url);
    sock = s;
    s.onopen = function () { s.send(JSON.stringify({token: box.dataset.csrf})); };
    s.onmessage = function (m) {
      try { event(JSON.parse(m.data)); } catch (e) { /* not ours */ }
    };
    s.onclose = function (c) {
      if (sock !== s) return;
      sock = null; busy(false);
      if (c.code !== 1008 && conv === id) setTimeout(function () { if (conv === id && !sock) connect(); }, 3000);
    };
  }

  function open(then) {
    fetch("/console/conv?path=" + encodeURIComponent(location.pathname), {credentials: "same-origin"})
      .then(function (r) { return r.json(); })
      .then(function (r) {
        out.textContent = ""; seen = {}; lastT = 0; props = {};
        conv = r.conv ? r.conv.id : null;
        box.querySelector(".con-model").textContent = r.conv ? r.conv.model : "";
        (r.events || []).forEach(event);
        busy(!!r.busy);
        connect();
        if (then) then();
      }).catch(function () { /* the drawer still runs commands */ });
  }

  function send(line, extra) {
    if (!extra) {
      hist = hist.filter(function (h) { return h !== line; }).concat([line]).slice(-100);
      save("hist", hist); at = hist.length;
    }
    var body = {line: line, path: location.pathname};
    if (extra) { body.ref = extra.ref; body.decline = extra.decline; }
    fetch("/console/cmd", {
      method: "POST", credentials: "same-origin",
      headers: {"content-type": "application/json", "x-csrf-token": box.dataset.csrf},
      body: JSON.stringify(body)
    }).then(function (r) {
      if (!r.ok) throw new Error("HTTP " + r.status);
      return r.json();
    }).then(function (r) {
      if (r.cmd === "new" || (r.cmd === "sessions" && r.conv && r.conv !== conv)) {
        open();               // the new one's transcript, this command included
        return;
      }
      if (r.conv && r.conv !== conv) { conv = r.conv; connect(); }
      if (r.model) box.querySelector(".con-model").textContent = r.model;
      if (r.declined) { /* marked already */ }
      else if (r.t && r.conv) event({k: "cmd", t: r.t, line: line, out: r, ref: body.ref});
      else if (!r.asked) card(line, r);
      if (r.go && r.href) location.href = r.href;
      else if (r.ok && r.cmd && changes(r.cmd)) setTimeout(function () { location.reload(); }, 900);
    }).catch(function (e) { card(line, {ok: false, text: String(e)}); });
  }
  function changes(name) {
    return (cmds || []).some(function (c) { return c.name === name && c.changes; });
  }
  stop.addEventListener("click", function () { send("/cancel"); });

  function commands(then) {
    if (cmds) return then(cmds);
    fetch("/console/commands", {credentials: "same-origin"}).then(function (r) { return r.json(); })
      .then(function (c) { cmds = c; then(c); }).catch(function () { /* no completion */ });
  }
  commands(function () {});

  input.addEventListener("keydown", function (ev) {
    if (ev.key === "Enter") {
      ev.preventDefault();
      var line = input.value.trim();
      if (!line) return;
      input.value = "";
      send(line);
    } else if (ev.key === "ArrowUp") {
      if (at > 0) { at--; input.value = hist[at]; ev.preventDefault(); }
    } else if (ev.key === "ArrowDown") {
      if (at < hist.length) { at++; input.value = hist[at] || ""; ev.preventDefault(); }
    } else if (ev.key === "Tab") {
      var v = input.value;
      if (v.charAt(0) !== "/" || v.indexOf(" ") >= 0) return;
      ev.preventDefault();
      commands(function (c) {
        var hit = c.filter(function (x) { return ("/" + x.name).indexOf(v) === 0; });
        if (hit.length === 1) input.value = "/" + hit[0].name + " ";
        else if (hit.length > 1) card(v, {ok: true, text: "matches",
          lines: hit.map(function (x) { return {text: "/" + x.name + " " + x.usage}; })});
      });
    }
  });

  try { localStorage.removeItem(KEY + "cards"); } catch (e) { /* none */ }  // C1 kept cards here
  open();
  if (load("open", false)) setOpen(true);
})();
