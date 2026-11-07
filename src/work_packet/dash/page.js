// Small behaviours of the packet page and the Desk, as a file: the board's CSP
// (script-src 'self') runs no inline script.
(function () {
  "use strict";
  function ready(fn) {
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", fn);
    else fn();
  }
  ready(function () {
    // Just made, to work on yourself (docs/collaboration.md W1): open it, once.
    var f = document.getElementById("autoopen");
    if (f) {
      history.replaceState(null, "", location.pathname + location.hash);
      setTimeout(function () { f.submit(); }, 300);
    }
    // The packet overview: old anchors moved to tabs (docs/packet-page.md §2.5).
    if (document.querySelector("[data-old-anchors]")) {
      var to = {"#tokens": "/cost", "#context": "/cost#context", "#settings": "/settings",
                "#sched": "/settings#sched"};
      var h = location.hash, base = location.pathname.replace(/\/$/, "");
      if (to[h]) location.replace(base + to[h]);
      if (h === "#vscode") { var d = document.getElementById("vscode"); if (d) d.open = true; }
    }
    // The Desk: you are here, so "since you were last here" counts from your next visit.
    var v = document.querySelector("[data-visit]");
    if (v && window.fetch) {
      fetch("/attention/visit", {method: "POST", credentials: "same-origin",
                                 headers: {"x-csrf-token": v.dataset.csrf || ""}}).catch(function () {});
    }
    // Checkpoint: draft it from the packet's latest session (docs/session-checkpoint.md §4.2).
    var b = document.getElementById("cp-draft"), msg = document.getElementById("cp-msg");
    if (b && b.dataset.url) {
      b.addEventListener("click", function () {
        b.disabled = true; msg.textContent = " drafting…";
        var csrf = b.form.querySelector("[name=csrf]").value;
        fetch(b.dataset.url, {method: "POST", headers: {"x-csrf-token": csrf}})
          .then(function (r) { return r.json(); })
          .then(function (d) {
            if (d.error) { msg.textContent = " " + d.error; return; }
            document.getElementById("cp-status").value = d.status || "";
            document.getElementById("cp-next").value = d.next || "";
            document.getElementById("cp-body").value = d.body || "";
            msg.textContent = " drafted: check it, then Record";
          })
          .catch(function () { msg.textContent = " could not draft"; })
          .finally(function () { b.disabled = false; });
      });
    }
  });
})();
