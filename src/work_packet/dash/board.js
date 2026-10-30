// The board page (board.html): dragging a card onto a board in the side tab
// (docs/boards.md), cards that unfold and stay so, and forms that ask first (data-confirm).
(function () {
  var h = document.documentElement;
  document.addEventListener("submit", function (e) {
    var f = e.target;
    if (f.dataset && f.dataset.confirm && !window.confirm(f.dataset.confirm)) e.preventDefault();
  });

  // Cards are compact <details>; which are open is remembered per browser. live.js
  // keeps them open across its swaps; this puts them back on a fresh load.
  var KEY = "wpk-cards-open", opened = {};
  try { opened = JSON.parse(localStorage.getItem(KEY) || "{}") || {}; } catch (e) {}
  function save() { try { localStorage.setItem(KEY, JSON.stringify(opened)); } catch (e) {} }
  function cards() { return document.querySelectorAll("details.card[data-project]"); }
  function label() {
    var b = document.getElementById("cards-all"); if (!b) return;
    var all = cards(), n = 0;
    all.forEach(function (d) { if (d.open) n++; });
    b.textContent = all.length && n === all.length ? "Fold all" : "Expand all";
  }
  function restore() {
    cards().forEach(function (d) { if (opened[d.dataset.project]) d.open = true; });
    label();
  }
  document.addEventListener("toggle", function (e) {
    var d = e.target;
    if (!d.matches || !d.matches("details.card[data-project]")) return;
    if (d.open) opened[d.dataset.project] = 1; else delete opened[d.dataset.project];
    save(); label();
  }, true);
  // A click on an open card's body folds it, unless it hit a link, a button or a form,
  // or was the end of selecting text.
  document.addEventListener("click", function (e) {
    var d = e.target.closest && e.target.closest("details.card[open] > .body");
    if (!d || e.target.closest("a, button, form, input, select, textarea, label")) return;
    var sel = window.getSelection && window.getSelection();
    if (sel && !sel.isCollapsed) return;
    d.parentNode.open = false;
  });
  document.addEventListener("click", function (e) {
    if (!e.target.closest || !e.target.closest("#cards-all")) return;
    var all = cards(), open = false;
    all.forEach(function (d) { if (!d.open) open = true; });
    all.forEach(function (d) { d.open = open; });
  });
  document.addEventListener("wpk:swap", restore);
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", restore); else restore();

  // Drag a card onto a board in the side tab. live.js leaves the page alone meanwhile.
  var dragged = null;
  function target(e) { return e.target.closest && e.target.closest(".side [data-board]"); }
  function clear() { document.querySelectorAll(".side .drop").forEach(function (x) { x.classList.remove("drop"); }); }
  document.addEventListener("dragstart", function (e) {
    var c = e.target.closest && e.target.closest(".card[data-project]");
    if (!c) return;
    dragged = c.dataset.project;
    c.classList.add("dragging"); h.classList.add("wpk-dragging");
    e.dataTransfer.effectAllowed = "move";
    e.dataTransfer.setData("text/plain", dragged);
  });
  document.addEventListener("dragend", function (e) {
    dragged = null; clear(); h.classList.remove("wpk-dragging");
    document.querySelectorAll(".card.dragging").forEach(function (x) { x.classList.remove("dragging"); });
  });
  document.addEventListener("dragover", function (e) {
    var t = dragged && target(e);
    if (!t) return;
    e.preventDefault(); e.dataTransfer.dropEffect = "move";
    if (!t.classList.contains("drop")) { clear(); t.classList.add("drop"); }
  });
  document.addEventListener("dragleave", function (e) {
    var t = target(e);
    if (t && !t.contains(e.relatedTarget)) t.classList.remove("drop");
  });
  document.addEventListener("drop", function (e) {
    var t = dragged && target(e), side = document.querySelector(".side");
    if (!t || !side) return;
    e.preventDefault();
    var body = new URLSearchParams({board: t.dataset.board, back: location.pathname});
    fetch("/p/" + encodeURIComponent(dragged) + "/board", {method: "POST", body: body,
      headers: {"X-CSRF-Token": side.dataset.csrf}}).then(function (r) {
      location.href = r.url;
    }).catch(function () { location.reload(); });
  });
})();
