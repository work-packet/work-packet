// The browser shell (docs/dash-tasks.md §5): xterm.js on a WebSocket to a pty the
// server owns. Sessions outlive the page; a reload reattaches and replays.
(function () {
  "use strict";
  var pane = document.getElementById("shellpane");
  if (!pane || !window.Terminal) return;
  var project = pane.getAttribute("data-project");
  var csrf = pane.getAttribute("data-csrf");
  var sids = (pane.getAttribute("data-sids") || "").split(",").filter(Boolean);
  var tabs = document.getElementById("shelltabs");
  var key = "wpk.shell." + project;
  var enc = new TextEncoder();

  var term = null, fit = null;
  // The terminal is made on first use: no shell starts until you ask for one.
  function ensureTerm() {
    if (term) return;
    document.getElementById("shellidle").hidden = true;
    var box = document.getElementById("term");
    box.hidden = false;
    term = new window.Terminal({ cursorBlink: true, fontSize: 13, scrollback: 5000,
      fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace" });
    fit = new window.FitAddon.FitAddon();
    term.loadAddon(fit);
    term.open(box);
    fit.fit();
    term.onData(function (d) { if (ws && ws.readyState === 1 && cur) ws.send(enc.encode(d)); });
    term.onResize(function (sz) { send({ resize: [sz.cols, sz.rows] }); });
  }

  var ws = null, cur = null, pending = null, retries = 0;

  function remember(sid) {
    try { if (sid) sessionStorage.setItem(key, sid); else sessionStorage.removeItem(key); }
    catch (e) { /* storage blocked: fine */ }
  }
  function remembered() {
    try { return sessionStorage.getItem(key); } catch (e) { return null; }
  }
  function send(obj) {
    if (ws && ws.readyState === 1) ws.send(JSON.stringify(obj));
  }
  function drawTabs() {
    tabs.textContent = "";
    sids.forEach(function (sid, i) {
      var b = document.createElement("button");
      b.type = "button"; b.className = "go" + (sid === cur ? " on" : "");
      b.textContent = "shell " + (i + 1);
      b.addEventListener("click", function () { if (sid !== cur) connect(sid); });
      tabs.appendChild(b);
      if (sid === cur) {
        var x = document.createElement("button");
        x.type = "button"; x.className = "go"; x.textContent = "close";
        x.title = "end this shell (SIGHUP)";
        x.addEventListener("click", function () { send({ close: true }); });
        tabs.appendChild(x);
      }
    });
    if (!sids.length) {
      var s = document.createElement("span");
      s.className = "muted"; s.style.fontSize = "12px";
      s.textContent = "No shell open.";
      tabs.appendChild(s);
    }
  }

  var recheckTimer = null;
  function recheck() {
    clearTimeout(recheckTimer);
    recheckTimer = setTimeout(function () {
      fetch(location.pathname, { credentials: "same-origin" }).then(function (r) { return r.text(); })
        .then(function (html) {
          var doc = new DOMParser().parseFromString(html, "text/html");
          var fresh = doc.querySelector("aside.checks"), old = document.querySelector("aside.checks");
          if (fresh && old) { old.innerHTML = fresh.innerHTML; bindTypeIt(old); }
        }).catch(function () {});
    }, 300);
  }

  function note(text, color) {
    term.write("\r\n\x1b[" + (color || "2") + "m" + text + "\x1b[0m\r\n");
  }

  function connect(sid, quiet) {
    ensureTerm();
    if (ws) { ws.onclose = null; ws.close(); }
    term.reset();
    cur = sid === "new" ? null : sid;
    var opened = false;
    term.write("\x1b[2m" + (sid === "new" ? "Starting a shell" : "Reattaching") + "…\x1b[0m");
    var url = (location.protocol === "https:" ? "wss://" : "ws://") + location.host +
      "/p/" + encodeURIComponent(project) + "/shell/" + encodeURIComponent(sid);
    var sock = new WebSocket(url);
    ws = sock;
    sock.binaryType = "arraybuffer";
    sock.onopen = function () {
      sock.send(JSON.stringify({ token: csrf }));
    };
    sock.onmessage = function (ev) {
      if (typeof ev.data !== "string") { term.write(new Uint8Array(ev.data)); return; }
      var m; try { m = JSON.parse(ev.data); } catch (e) { return; }
      if (m.sid) {
        opened = true; term.reset();   // the replay of its output follows
        retries = 0; cur = m.sid; remember(cur);
        if (sids.indexOf(cur) < 0) sids.push(cur);
        drawTabs();
        fit.fit(); send({ resize: [term.cols, term.rows] });
        if (pending !== null) { send({ input: pending }); pending = null; }
        if (!quiet) term.focus();   // a reattach on load does not take the keyboard
      } else if (m.recheck) {
        recheck();
      } else if (m.exit !== undefined) {
        term.write("\r\n\x1b[2m[shell exited " + m.exit + "]\x1b[0m\r\n");
        sids = sids.filter(function (s) { return s !== cur; }); remember(null); cur = null;
        drawTabs(); recheck();
      } else if (m.taken) {
        term.write("\r\n\x1b[2m[opened in another window]\x1b[0m\r\n");
        sock.onclose = null;
      } else if (m.gone) {
        sids = sids.filter(function (s) { return s !== sid; }); remember(null); cur = null;
        drawTabs();
      } else if (m.error) {
        opened = true; note(m.error, "31");
      }
    };
    sock.onclose = function (ev) {
      if (ws !== sock) return;
      if (ev.code === 1008) {
        note("The server refused the shell (its token changed?): reload the page.", "31");
        return;
      }
      if (!opened) {                    // never got as far as a session: say so
        note("Could not open a shell: the connection closed (code " + ev.code + "). " +
             "The wpk dash log says why; + shell tries again.", "31");
        return;
      }
      if (!cur || retries >= 5) {
        if (cur) note("[disconnected: + shell, or reload to reattach]");
        return;
      }
      retries += 1;                     // a dropped connection: the shell is still there
      setTimeout(function () { if (ws === sock) connect(cur, true); }, 1000 * retries);
    };
  }

  window.addEventListener("resize", function () { if (fit) fit.fit(); });

  document.getElementById("newshell").addEventListener("click", function () { connect("new"); });
  document.getElementById("openshell").addEventListener("click", function () { connect("new"); });

  function bindTypeIt(root) {
    root.querySelectorAll("button[data-typeit]").forEach(function (b) {
      b.addEventListener("click", function () {
        var text = b.getAttribute("data-typeit");
        if (ws && ws.readyState === 1 && cur) { send({ input: text }); term.focus(); }
        else { pending = text; connect(cur || "new"); }
        pane.scrollIntoView({ block: "nearest" });
      });
    });
  }
  bindTypeIt(document);

  drawTabs();
  var want = remembered();
  if (want && sids.indexOf(want) >= 0) connect(want, true);
  else if (sids.length) connect(sids[0], true);
  // else: no shell until "Open shell", "+ shell" or "Type it"
})();
