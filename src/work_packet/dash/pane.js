// Scroll panes that follow their end, as a CI log does, and the log's buttons.
// A pane is any element with class "pane" and an id; data-follow="no" starts
// it at the top. live.js fires wpk:beforeswap and wpk:swap around a refresh.
(function () {
  var NEAR = 40, saved = {};
  function panes() { return document.querySelectorAll(".pane[id]"); }
  function atEnd(p) { return p.scrollHeight - p.scrollTop - p.clientHeight < NEAR; }
  document.addEventListener("wpk:beforeswap", function () {
    saved = {};
    panes().forEach(function (p) { saved[p.id] = {top: p.scrollTop, end: atEnd(p)}; });
  });
  document.addEventListener("wpk:swap", function () {
    panes().forEach(function (p) {
      var s = saved[p.id];
      if (!s) { if (p.dataset.follow !== "no") p.scrollTop = p.scrollHeight; }
      else p.scrollTop = s.end ? p.scrollHeight : s.top;
    });
  });
  function start() {
    var m = /^#(L\d+)$/.exec(location.hash), t = m && document.getElementById(m[1]);
    if (t) {
      var d = t.closest("details"); if (d) d.open = true;
      t.scrollIntoView({block: "center"});
      return;
    }
    panes().forEach(function (p) { if (p.dataset.follow !== "no") p.scrollTop = p.scrollHeight; });
  }
  document.addEventListener("click", function (e) {
    var b = e.target.closest("[data-expand], [data-copy]");
    if (!b) return;
    if (b.dataset.copy) {
      var src = document.getElementById(b.dataset.copy);
      if (src && navigator.clipboard) navigator.clipboard.writeText(src.textContent);
      return;
    }
    var open = b.dataset.expand === "all";
    document.querySelectorAll(b.dataset.target + " details").forEach(function (d) { d.open = open; });
  });
  start();
})();
