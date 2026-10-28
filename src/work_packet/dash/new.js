// New task: the model box offers the chosen harness's models; repo and issue
// fields search the forges as you type (docs/starters-v1.md).
(function () {
  "use strict";
  var h = document.getElementById("harness"), m = document.getElementById("model");
  if (h && m) {
    h.addEventListener("change", function () {
      m.setAttribute("list", "models-" + h.value);
      var dl = document.getElementById("models-" + h.value);
      var ok = !m.value || (dl && [].some.call(dl.options, function (o) { return o.value === m.value; }));
      if (!ok) m.value = "";
    });
  }
  var form = document.getElementById("new-form");
  if (!form) return;
  var starter = form.getAttribute("data-starter");
  [].forEach.call(form.querySelectorAll("[data-search]"), function (inp) {
    var key = inp.getAttribute("data-search"), dl = document.getElementById("dl-" + key);
    var timer = null, last = null;
    function run() {
      var q = new URLSearchParams();
      [].forEach.call(form.elements, function (el) {
        if (el.name && el.name !== "csrf" && el.type !== "submit") q.set(el.name, el.value);
      });
      q.set("starter", starter); q.set("field", key); q.set("q", inp.value);
      var s = q.toString();
      if (s === last) return;
      last = s;
      fetch("/new/search?" + s, {credentials: "same-origin"}).then(function (r) { return r.json(); })
        .then(function (d) {
          dl.innerHTML = "";
          (d.choices || []).forEach(function (c) {
            if (!c.value) return;
            var o = document.createElement("option");
            o.value = c.value; o.label = c.label + (c.detail ? "  " + c.detail : "");
            dl.appendChild(o);
          });
        }).catch(function () {});
    }
    inp.addEventListener("input", function () { clearTimeout(timer); timer = setTimeout(run, 300); });
    inp.addEventListener("focus", run);
  });
})();
