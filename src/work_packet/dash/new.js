// New task: the model box offers the chosen harness's models.
(function () {
  "use strict";
  var h = document.getElementById("harness"), m = document.getElementById("model");
  if (!h || !m) return;
  h.addEventListener("change", function () {
    m.setAttribute("list", "models-" + h.value);
    var dl = document.getElementById("models-" + h.value);
    var ok = !m.value || (dl && [].some.call(dl.options, function (o) { return o.value === m.value; }));
    if (!ok) m.value = "";
  });
})();
