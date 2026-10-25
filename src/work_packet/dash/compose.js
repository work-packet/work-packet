// Compose (docs/dash-tasks.md §4): "hand off anyway" enables the button; Ctrl+S saves.
(function () {
  "use strict";
  document.querySelectorAll("input[data-enable]").forEach(function (cb) {
    var form = cb.form;
    var btn = form && form.querySelector('button[value="' + cb.getAttribute("data-enable") + '"]');
    if (!btn) return;
    cb.addEventListener("change", function () { btn.disabled = !cb.checked; });
  });
  var form = document.getElementById("compose");
  if (!form) return;
  var dirty = false;
  form.addEventListener("input", function () { dirty = true; });
  form.addEventListener("submit", function () { dirty = false; });
  window.addEventListener("beforeunload", function (ev) {
    if (dirty) { ev.preventDefault(); ev.returnValue = ""; }
  });
  document.addEventListener("keydown", function (ev) {
    if ((ev.ctrlKey || ev.metaKey) && ev.key === "s" && form.contains(document.activeElement)) {
      ev.preventDefault();
      var b = form.querySelector('button[value="save"]');
      if (b) b.click();
    }
  });
})();
