// The board page (board.html): dragging a card onto a board in the side tab
// (docs/boards.md), and forms that ask first (data-confirm).
(function () {
  var h = document.documentElement;
  document.addEventListener("submit", function (e) {
    var f = e.target;
    if (f.dataset && f.dataset.confirm && !window.confirm(f.dataset.confirm)) e.preventDefault();
  });

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
