// The scheduler's forms (sched.html, packets.html): ask first (data-confirm),
// the All packets bulk bar's "tick all shown", and the Overview's "select all".
(function () {
  document.addEventListener("submit", function (e) {
    var f = e.target;
    if (f.dataset && f.dataset.confirm && !window.confirm(f.dataset.confirm)) e.preventDefault();
  });
  document.addEventListener("change", function (e) {
    var t = e.target;
    if (!t.matches || !t.matches("input[data-pick-all]")) return;
    if (t.dataset.pickAll === "form") {                 // the Overview's finished rows
      t.form.querySelectorAll("input[name=project]").forEach(function (b) { b.checked = t.checked; });
      return;
    }
    document.querySelectorAll("#pk tbody tr").forEach(function (tr) {
      var box = tr.querySelector("input[name=pick]");
      if (box && !tr.hidden) box.checked = t.checked;
    });
  });
})();
