// Refresh by swapping <main> in place, so scroll position and open <details> survive.
// Text selected in the page also pauses it, so you can copy from a log.
(function () {
  var btn = document.getElementById("live"), on = true;
  try { on = localStorage.getItem("wpk-live") !== "off"; } catch (e) {}
  function show() { btn.textContent = on ? "live" : "paused"; btn.style.opacity = on ? 1 : .6; }
  btn.onclick = function () { on = !on; try { localStorage.setItem("wpk-live", on ? "on" : "off"); } catch (e) {} show(); };
  show();
  // A form being filled in is never swapped out from under you.
  document.addEventListener("input", function (e) { if (e.target.form) e.target.form.dataset.dirty = "1"; });
  function busy() {
    var a = document.activeElement, sel = window.getSelection && window.getSelection();
    if (sel && !sel.isCollapsed && document.getElementById("main").contains(sel.anchorNode)) return true;
    return !!document.querySelector("#main form[data-dirty]") ||
      !!(a && a.form && document.getElementById("main").contains(a));
  }
  setInterval(function () {
    if (!on || document.hidden || busy()) return;
    fetch(location.href, {cache: "no-store"}).then(function (r) { return r.text(); }).then(function (html) {
      var doc = new DOMParser().parseFromString(html, "text/html");
      var next = doc.getElementById("main"); if (!next) return;
      var open = {};
      document.querySelectorAll("#main details[id]").forEach(function (d) { open[d.id] = d.open; });
      document.dispatchEvent(new Event("wpk:beforeswap"));    // pane.js keeps the scroll panes' place
      document.getElementById("main").innerHTML = next.innerHTML;
      document.querySelectorAll("#main details[id]").forEach(function (d) { if (d.id in open) d.open = open[d.id]; });
      document.dispatchEvent(new Event("wpk:swap"));
      document.title = doc.title;
    }).catch(function () {});
  }, +btn.dataset.refreshMs || 10000);
})();
