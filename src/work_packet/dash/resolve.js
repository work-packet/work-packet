// Question resolution in the browser (docs/question-ux-plan.md §2): a Claude session
// on a pty the server owns, started with the packet's questions and the resolve mode.
// xterm loads on first use. While a session is open the page holds its live refresh
// (data-live-hold, live.js), and the session outlives a reload: it reattaches.
(function () {
  "use strict";
  var enc = new TextEncoder();
  var loading = null;

  function load() {                     // xterm and its fit addon, once
    if (window.Terminal && window.FitAddon) return Promise.resolve();
    if (loading) return loading;
    var css = document.createElement("link");
    css.rel = "stylesheet"; css.href = "/static/vendor/term/xterm.css";
    document.head.appendChild(css);
    function script(src) {
      return new Promise(function (ok, bad) {
        var s = document.createElement("script");
        s.src = src; s.onload = ok; s.onerror = bad;
        document.head.appendChild(s);
      });
    }
    loading = script("/static/vendor/term/xterm.js").then(function () {
      return script("/static/vendor/term/addon-fit.js");
    });
    return loading;
  }

  function key(wpid) { return "wpk.resolve." + wpid; }
  function remember(wpid, sid) {
    try { if (sid) sessionStorage.setItem(key(wpid), sid); else sessionStorage.removeItem(key(wpid)); }
    catch (e) { /* storage blocked: fine */ }
  }
  function remembered(wpid) {
    try { return sessionStorage.getItem(key(wpid)); } catch (e) { return null; }
  }

  function start(pane, sid) {
    if (pane._resolve) return;
    var wpid = pane.getAttribute("data-wpid");
    var box = pane.querySelector(".term");
    var status = pane.querySelector(".resolve-status");
    pane._resolve = true;
    pane.setAttribute("data-live-hold", "1");
    pane.querySelector(".resolve-start").hidden = true;
    pane.querySelector(".resolve-end").hidden = false;
    status.textContent = sid === "new" ? "Starting…" : "Reattaching…";
    load().then(function () {
      box.hidden = false;
      var term = new window.Terminal({ cursorBlink: true, fontSize: 13, scrollback: 5000,
        fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace" });
      var fit = new window.FitAddon.FitAddon();
      term.loadAddon(fit);
      term.open(box);
      fit.fit();
      var cur = null, retries = 0, ws = null, ended = false;
      function send(o) { if (ws && ws.readyState === 1) ws.send(JSON.stringify(o)); }
      term.onData(function (d) { if (ws && ws.readyState === 1 && cur) ws.send(enc.encode(d)); });
      term.onResize(function (sz) { send({ resize: [sz.cols, sz.rows] }); });
      window.addEventListener("resize", function () { fit.fit(); });
      function finish(text) {
        ended = true; cur = null; remember(wpid, null);
        pane.removeAttribute("data-live-hold");
        pane.querySelector(".resolve-end").hidden = true;
        status.textContent = text;
        pane.querySelector(".resolve-done").hidden = false;
      }
      function connect(s) {
        var url = (location.protocol === "https:" ? "wss://" : "ws://") + location.host + "/p/" +
          encodeURIComponent(pane.getAttribute("data-project")) + "/shell/" + encodeURIComponent(s);
        var sock = new WebSocket(url);
        ws = sock; sock.binaryType = "arraybuffer";
        sock.onopen = function () {
          var hello = { token: pane.getAttribute("data-csrf") };
          if (s === "new") hello.resolve = wpid;
          sock.send(JSON.stringify(hello));
        };
        sock.onmessage = function (ev) {
          if (typeof ev.data !== "string") { term.write(new Uint8Array(ev.data)); return; }
          var m; try { m = JSON.parse(ev.data); } catch (e) { return; }
          if (m.sid) {
            term.reset(); retries = 0; cur = m.sid; remember(wpid, cur);
            status.textContent = "Session open. It keeps running if you leave the page (30 min idle).";
            fit.fit(); send({ resize: [term.cols, term.rows] }); term.focus();
          } else if (m.exit !== undefined) {
            finish("The session ended. Reload to see where the packet stands.");
          } else if (m.taken) {
            sock.onclose = null; status.textContent = "Opened in another window.";
          } else if (m.gone) {
            finish("That session is gone.");
            pane.querySelector(".resolve-start").hidden = false; pane._resolve = false;
            box.hidden = true; term.dispose();
          } else if (m.error) {
            finish(m.error);
          }
        };
        sock.onclose = function (ev) {
          if (ws !== sock || ended) return;
          if (ev.code === 1008) { finish("The server refused it (its token changed?): reload the page."); return; }
          if (!cur) { finish("Could not start it (code " + ev.code + "); the wpk dash log says why."); return; }
          if (retries >= 5) { status.textContent = "Disconnected: reload to reattach."; return; }
          retries += 1;                 // a dropped connection: the session is still there
          setTimeout(function () { if (ws === sock) connect(cur); }, 1000 * retries);
        };
      }
      pane.querySelector(".resolve-end").onclick = function () {
        if (cur) send({ close: true });
      };
      connect(sid);
    }).catch(function () {
      pane._resolve = false; pane.removeAttribute("data-live-hold");
      status.textContent = "Could not load the terminal.";
      pane.querySelector(".resolve-start").hidden = false;
    });
  }

  document.addEventListener("click", function (ev) {
    var b = ev.target.closest && ev.target.closest(".resolve-start");
    if (b) start(b.closest(".resolvepane"), "new");
    var r = ev.target.closest && ev.target.closest(".resolve-reload");
    if (r) location.reload();
  });
  function reattach() {
    document.querySelectorAll(".resolvepane").forEach(function (pane) {
      var sid = remembered(pane.getAttribute("data-wpid"));
      if (sid && !pane._resolve) start(pane, sid);
    });
  }
  document.addEventListener("wpk:swap", reattach);
  reattach();
})();
