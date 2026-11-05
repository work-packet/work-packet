// New task: the model box offers the chosen harness's models; repo and issue
// fields search the forges as you type (docs/starters-v1.md).
(function () {
  "use strict";
  var h = document.getElementById("harness"), m = document.getElementById("model");
  if (h && m) {
    h.addEventListener("change", function () {
      m.setAttribute("list", "models-" + h.value);
      var dl = document.getElementById("models-" + h.value);
      var ok = !m.value || (dl && [].some.call(dl.options, function (o) { return o.value === m.value; }));
      if (!ok) m.value = "";
    });
  }
  var form = document.getElementById("new-form");
  if (!form) return;
  var starter = form.getAttribute("data-starter");
  [].forEach.call(form.querySelectorAll("[data-search]"), function (inp) {
    var key = inp.getAttribute("data-search"), dl = document.getElementById("dl-" + key);
    var timer = null, last = null;
    function run() {
      var q = new URLSearchParams();
      [].forEach.call(form.elements, function (el) {
        if (el.name && el.name !== "csrf" && el.type !== "submit") q.set(el.name, el.value);
      });
      q.set("starter", starter); q.set("field", key); q.set("q", inp.value);
      var s = q.toString();
      if (s === last) return;
      last = s;
      fetch("/new/search?" + s, {credentials: "same-origin"}).then(function (r) { return r.json(); })
        .then(function (d) {
          dl.innerHTML = "";
          (d.choices || []).forEach(function (c) {
            if (!c.value) return;
            var o = document.createElement("option");
            o.value = c.value; o.label = c.label + (c.detail ? "  " + c.detail : "");
            dl.appendChild(o);
          });
        }).catch(function () {});
    }
    inp.addEventListener("input", function () { clearTimeout(timer); timer = setTimeout(run, 300); });
    inp.addEventListener("focus", run);
  });
})();

// Create, in the background (dash-create-progress-design.md): the preview form's
// Create starts a job, and a panel shows its steps, the clone's progress, the
// dependencies as IVPM fetches them, and the output; on success, the page
// Create would have sent you to. /new?job=<id> picks a job up again.
(function () {
  "use strict";
  var panel = document.getElementById("new-job");
  if (!panel) return;
  var form = document.getElementById("create-form");
  var $ = function (sel) { return panel.querySelector(sel); };
  var MAX_LINES = 2000;
  var st, sock, jid, lastN, tries, timer, skew, dirty = false;

  function reset() {
    st = {steps: [], byId: {}, pk: {}, tasks: {}, git: {}, nlines: 0, undo: false, done: null};
    lastN = 0; tries = 0; skew = null;
    $(".nj-steps").innerHTML = ""; $(".nj-log").textContent = ""; $(".nj-activity").textContent = "";
    var e = $(".nj-error"); e.hidden = true; e.textContent = "";
  }

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }
  function secs(s) {
    if (s == null) return "";
    s = Math.max(0, s);
    if (s < 60) return s.toFixed(1) + "s";
    var m = Math.floor(s / 60), r = Math.floor(s % 60);
    return m + ":" + (r < 10 ? "0" : "") + r;
  }
  function now() { return Date.now() / 1000 - (skew || 0); }
  var ICON = {run: "●", ok: "✓", fail: "✗", skip: "–", pending: "○"};

  function bar(pct) {
    var b = el("span", "bar"), i = el("i");
    i.style.width = Math.max(0, Math.min(100, pct)) + "%";
    b.appendChild(i);
    return b;
  }

  function apply(ev) {
    if (ev.n) lastN = ev.n;
    if (ev.t) { var d = Date.now() / 1000 - ev.t; skew = skew == null ? d : Math.min(skew, d); }
    var sid = ev.step;
    switch (ev.k) {
      case "step":
        var s = st.byId[ev.id];
        if (!s) { s = st.byId[ev.id] = {id: ev.id}; st.steps.push(s); }
        if (ev.label) s.label = ev.label;
        s.state = ev.state;
        if (ev.state === "run") s.t0 = ev.t;
        if (ev.secs != null) s.secs = ev.secs;
        if (ev.note) s.note = ev.note;
        break;
      case "pkg":
        if (ev.name === "[clone]") break;            // the clone step itself
        (st.pk[sid] = st.pk[sid] || {})[ev.name] = ev;
        break;
      case "task":
        (st.tasks[sid] = st.tasks[sid] || {})[ev.name] = ev;
        break;
      case "git":
        st.git[sid + "|" + (ev.pkg && ev.pkg !== "[clone]" ? ev.pkg : "")] = ev;
        break;
      case "line":
        st.nlines++;
        var log = $(".nj-log");
        log.appendChild(document.createTextNode(ev.text + "\n"));
        while (log.childNodes.length > MAX_LINES) log.removeChild(log.firstChild);
        if (ev.text.trim()) st.activity = ev.text;
        break;
      case "diag":
        if (ev.severity === "note") st.activity = ev.msg;
        break;
      case "note":
        st.activity = ev.text;
        break;
      case "undo":
        st.undo = true;
        break;
      case "done":
        st.done = ev;
        break;
    }
    dirty = true;
  }

  function render() {
    if (!dirty && !(st && !st.done)) return;
    dirty = false;
    var ol = $(".nj-steps");
    ol.innerHTML = "";
    var start = null;
    st.steps.forEach(function (s) {
      if (s.t0 != null && (start == null || s.t0 < start)) start = s.t0;
      var li = el("li", "nj-step " + s.state);
      li.appendChild(el("span", "ic", ICON[s.state] || "·"));
      var lab = el("span", "lab", s.label || s.id);
      var g = st.git[s.id + "|"];
      if (s.state === "run" && g) {
        lab.appendChild(el("span", "muted", "  " + g.phase + " " + g.pct + "%"));
        lab.appendChild(bar(g.pct));
      }
      var pk = st.pk[s.id] || {}, names = Object.keys(pk);
      if (names.length) {
        var done = names.filter(function (n) { return pk[n].state === "ok"; }).length;
        var bad = names.filter(function (n) { return pk[n].state === "fail"; }).length;
        lab.appendChild(el("span", "muted", "  " + done + " done / " + names.length + " started" +
                           (bad ? ", " + bad + " failed" : "")));
      }
      if (s.note && s.state !== "run" && s.state !== "fail") lab.appendChild(el("span", "muted", "  " + s.note));
      li.appendChild(lab);
      li.appendChild(el("span", "t", s.state === "run" && s.t0 != null ? secs(now() - s.t0) : secs(s.secs)));
      var sub = el("div", "nj-sub");
      names.forEach(function (n) {
        var p = pk[n], row = el("div", "nj-pk " + p.state);
        row.appendChild(el("span", "", ICON[p.state] || "·"));
        row.appendChild(el("span", "", n));
        var act = el("span", "act meta");
        var gp = st.git[s.id + "|" + n];
        if (p.state === "run" && gp) { act.textContent = gp.phase + " " + gp.pct + "%"; act.appendChild(bar(gp.pct)); }
        else if (p.state === "fail") { act.textContent = p.error || "failed"; act.title = act.textContent; }
        else if (p.type) act.textContent = p.type;
        row.appendChild(act);
        row.appendChild(el("span", "meta", p.secs != null ? secs(p.secs) : ""));
        sub.appendChild(row);
      });
      var tk = st.tasks[s.id] || {};
      Object.keys(tk).forEach(function (n) {
        var t = tk[n], row = el("div", "nj-pk " + t.state);
        row.appendChild(el("span", "", ICON[t.state] || "·"));
        row.appendChild(el("span", "", n));
        var act = el("span", "act meta", t.state === "fail" ? (t.msg || "failed")
          : (t.at != null && t.total ? t.at + "/" + t.total + " " : "") + (t.msg || ""));
        if (t.state === "run" && t.at != null && t.total) act.appendChild(bar(100 * t.at / t.total));
        row.appendChild(act);
        row.appendChild(el("span", "meta", t.secs != null ? secs(t.secs) : ""));
        sub.appendChild(row);
      });
      if (sub.childNodes.length) li.appendChild(sub);
      ol.appendChild(li);
    });
    $(".nj-clock").textContent = start != null ? secs((st.done ? st.done.t : now()) - start) : "";
    $(".nj-activity").textContent = st.done ? "" : (st.activity || "starting…");
    $(".nj-nlines").textContent = st.nlines ? "(" + st.nlines + " lines)" : "";
    if (st.done) finish(st.done);
  }

  function finish(d) {
    clearInterval(timer);
    if (d.ok) {
      $(".nj-title").textContent = "Created " + (d.name || "");
      $(".nj-activity").textContent = "opening it…";
      setTimeout(function () { location.replace(d.url); }, 700);
      return;
    }
    $(".nj-title").textContent = "Not created";
    var e = $(".nj-error");
    e.textContent = d.error + (st.undo ? "\n\nThe clone was removed; nothing was left behind." : "");
    e.hidden = false;
    $(".nj-raw").open = true;
    enable(true);
  }

  function enable(on) {
    if (!form) return;
    [].forEach.call(form.elements, function (x) { x.disabled = !on; });
  }

  function connect() {
    var url = (location.protocol === "https:" ? "wss:" : "ws:") + "//" + location.host +
      "/new/job/" + encodeURIComponent(jid) + "/ws?since=" + lastN;
    sock = new WebSocket(url);
    sock.onopen = function () { tries = 0; sock.send(JSON.stringify({token: panel.dataset.csrf})); };
    sock.onmessage = function (m) { try { apply(JSON.parse(m.data)); } catch (x) {} };
    sock.onclose = function () {
      if (st.done) return;
      if (++tries > 30) {
        finish({ok: false, error: "Lost touch with the server; the packet may still be made. " +
                "See the log, or the board."});
        return;
      }
      setTimeout(connect, Math.min(5000, 500 * tries));
    };
  }

  function watch(id) {
    jid = id;
    reset();
    panel.hidden = false;
    panel.scrollIntoView({block: "nearest"});
    $(".nj-loglink").href = "/new/job/" + encodeURIComponent(id) + "/log";
    clearInterval(timer);
    timer = setInterval(render, 250);
    connect();
  }

  if (form) {
    form.addEventListener("submit", function (e) {
      var b = e.submitter;
      if (b && b.value !== "create") return;
      if (!window.fetch || !window.WebSocket) return;     // the plain post still works
      e.preventDefault();
      var body = new URLSearchParams(new FormData(form));
      body.set("action", "create");
      enable(false);
      fetch("/new", {method: "POST", body: body, credentials: "same-origin",
                     headers: {"accept": "application/json", "x-csrf-token": panel.dataset.csrf}})
        .then(function (r) { return r.json().then(function (d) { return [r.ok, d]; }); })
        .then(function (rd) {
          if (!rd[0] || !rd[1].job) throw new Error(rd[1].error || "the server refused");
          $(".nj-title").textContent = "Creating " + (form.elements.name ? form.elements.name.value : "");
          var q = new URLSearchParams(location.search);
          q.set("job", rd[1].job);
          history.replaceState(null, "", "/new?" + q.toString());
          watch(rd[1].job);
        })
        .catch(function (x) {
          reset();
          panel.hidden = false;
          $(".nj-title").textContent = "Not created";
          var er = $(".nj-error"); er.textContent = x.message; er.hidden = false;
          enable(true);
        });
    });
  }
  if (panel.dataset.job) watch(panel.dataset.job);
})();
