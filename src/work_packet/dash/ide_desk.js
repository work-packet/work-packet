// Web VS Code: the way to the packet's desktop (docs/desktop.md §6). The board
// puts this in the workbench page when [desktop] is on. It asks
// /desk/<key>/state every few seconds; while the server has a display, a small
// "Desktop" link sits above the status bar, and when a program opens a window
// that nobody is viewing, a toast says so. Opening a tab needs your click
// (pop-up blockers), so nothing opens by itself.
(function () {
  "use strict";
  var m = /^\/ide\/([0-9a-f]{12})\//.exec(location.pathname);
  if (!m) {
    return;
  }
  var key = m[1];
  var desk = "/desk/" + key + "/";
  var pill = null;
  var toast = null;
  var seen = {};            // apps already announced, until they go away

  function el(tag, css, text) {
    var e = document.createElement(tag);
    for (var k in css) {
      e.style[k] = css[k];
    }
    if (text) {
      e.textContent = text;
    }
    return e;
  }

  var BOX = {position: "fixed", zIndex: "100000", font: "12px system-ui, sans-serif",
             borderRadius: "4px", boxShadow: "0 2px 8px rgba(0,0,0,.35)"};

  function link(text) {
    var a = el("a", {color: "inherit", textDecoration: "none", cursor: "pointer"}, text);
    a.href = desk;
    a.target = "wpk-desk-" + key;
    a.rel = "noopener";
    return a;
  }

  function showPill(st) {
    if (!pill) {
      pill = el("div", Object.assign({}, BOX, {right: "14px", bottom: "30px", padding: "3px 9px",
                                               background: "#3a3f4b", color: "#e3e6ec",
                                               opacity: "0.85"}));
      pill.title = "The packet's desktop: windows of GUI programs started here";
      pill.appendChild(link(""));
      document.body.appendChild(pill);
    }
    var n = (st.apps || []).length;
    pill.firstChild.textContent = "Desktop" + (n ? " \u00b7 " + n + " app" + (n > 1 ? "s" : "") : "");
  }

  function showToast(apps) {
    if (toast) {
      toast.remove();
    }
    toast = el("div", Object.assign({}, BOX, {right: "14px", bottom: "60px", padding: "10px 12px",
                                              background: "#1f6feb", color: "#fff", maxWidth: "320px"}));
    var what = apps.length > 1 ? " opened windows. " : " opened a window. ";
    toast.appendChild(el("span", {}, apps.join(", ") + what));
    var a = link("View desktop");
    a.style.fontWeight = "600";
    a.style.textDecoration = "underline";
    a.addEventListener("click", function () { toast.remove(); toast = null; });
    toast.appendChild(a);
    var x = el("span", {marginLeft: "10px", cursor: "pointer", opacity: "0.8"}, "✕");
    x.addEventListener("click", function () { toast.remove(); toast = null; });
    toast.appendChild(x);
    document.body.appendChild(toast);
    setTimeout(function () { if (toast) { toast.remove(); toast = null; } }, 20000);
  }

  function poll() {
    fetch("/desk/" + key + "/state", {cache: "no-store", credentials: "same-origin"})
      .then(function (r) { return r.json(); })
      .then(function (st) {
        if (!st.desktop) {
          if (pill) { pill.remove(); pill = null; }
          return;
        }
        showPill(st);
        var apps = st.apps || [];
        var fresh = apps.filter(function (a) { return !seen[a]; });
        var now = {};
        apps.forEach(function (a) { now[a] = true; });
        seen = now;
        if (fresh.length && !st.viewers) {
          showToast(fresh);
        }
      })
      .catch(function () { /* the board is away: try again */ });
  }
  function start() {
    poll();
    setInterval(poll, 4000);
  }
  if (document.body) {
    start();
  } else {
    document.addEventListener("DOMContentLoaded", start);
  }
})();
