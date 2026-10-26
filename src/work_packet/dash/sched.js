// The scheduler's forms (sched.html, packets.html): ask first (data-confirm),
// and the All packets bulk bar's "tick all shown".
(function () {
  document.addEventListener("submit", function (e) {
    var f = e.target;
    if (f.dataset && f.dataset.confirm && !window.confirm(f.dataset.confirm)) e.preventDefault();
  });
  document.addEventListener("change", function (e) {
    var t = e.target;
    if (!t.matches || !t.matches("input[data-pick-all]")) return;
    document.querySelectorAll("#pk tbody tr").forEach(function (tr) {
      var box = tr.querySelector("input[name=pick]");
      if (box && !tr.hidden) box.checked = t.checked;
    });
  });
})();
