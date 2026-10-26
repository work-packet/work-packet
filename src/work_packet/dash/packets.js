// All packets (packets.html): sort by a column, search, filter by state and board.
// The choices live here, not in the page, so a live refresh (live.js) keeps them.
(function () {
  var st = {key: null, dir: 1, q: "", state: "", board: ""};
  try { var s = JSON.parse(sessionStorage.getItem("wpk-packets") || "null"); if (s) st = s; } catch (e) {}
  function save() { try { sessionStorage.setItem("wpk-packets", JSON.stringify(st)); } catch (e) {} }
  function val(td) { return td.dataset.sort !== undefined ? td.dataset.sort : td.textContent.trim(); }
  function apply() {
    var t = document.getElementById("pk");
    var q = document.getElementById("pk-q"), s = document.getElementById("pk-state"),
        b = document.getElementById("pk-board");
    if (q) q.value = st.q; if (s) s.value = st.state; if (b) b.value = st.board;
    if (!t) return;
    var body = t.tBodies[0], rows = Array.prototype.slice.call(body.rows);
    rows.forEach(function (r, i) { if (r.dataset.i === undefined) r.dataset.i = i; });
    var ths = t.tHead.rows[0].cells, col = -1;
    for (var i = 0; i < ths.length; i++) {
      var on = ths[i].dataset.key === st.key;
      if (on) col = i;
      if (on) ths[i].setAttribute("aria-sort", st.dir > 0 ? "ascending" : "descending");
      else ths[i].removeAttribute("aria-sort");
    }
    if (col >= 0) {
      rows.sort(function (x, y) {
        var a = val(x.cells[col]), c = val(y.cells[col]), na = parseFloat(a), nc = parseFloat(c), d;
        if (a === "" || c === "") d = (a === "") - (c === "");          // blanks last
        else if (!isNaN(na) && !isNaN(nc) && String(na) === a && String(nc) === c) d = (na - nc) * st.dir;
        else d = a.localeCompare(c, undefined, {numeric: true}) * st.dir;
        return d || x.dataset.i - y.dataset.i;
      });
    } else rows.sort(function (x, y) { return x.dataset.i - y.dataset.i; });
    var words = st.q.toLowerCase().split(/\s+/).filter(Boolean), shown = 0;
    rows.forEach(function (r) {
      var text = r.textContent.toLowerCase();
      var ok = (!st.state || r.dataset.state === st.state) && (!st.board || r.dataset.board === st.board) &&
        words.every(function (w) { return text.indexOf(w) >= 0; });
      r.hidden = !ok; if (ok) shown++;
      body.appendChild(r);
    });
    // In tree order the └ marks show the hierarchy; sorted, they would mislead.
    t.classList.toggle("sorted", col >= 0);
    var n = document.getElementById("pk-count"), none = document.getElementById("pk-none");
    if (n) n.textContent = (shown === rows.length ? rows.length : shown + " of " + rows.length) +
      " packet" + (rows.length === 1 ? "" : "s");
    if (none) none.hidden = shown > 0;
  }
  document.addEventListener("click", function (e) {
    var th = e.target.closest && e.target.closest("table.pk th[data-key]");
    if (!th) return;
    var k = th.dataset.key;
    if (st.key !== k) { st.key = k; st.dir = 1; }
    else if (st.dir > 0) st.dir = -1;
    else st.key = null;                                         // a third click: tree order
    save(); apply();
  });
  document.addEventListener("input", function (e) {
    if (e.target.id === "pk-q") st.q = e.target.value;
    else if (e.target.id === "pk-state") st.state = e.target.value;
    else if (e.target.id === "pk-board") st.board = e.target.value;
    else return;
    save(); apply();
  });
  document.addEventListener("submit", function (e) { if (e.target.hasAttribute("data-filter")) e.preventDefault(); });
  document.addEventListener("DOMContentLoaded", apply);
  document.addEventListener("wpk:swap", apply);
})();
