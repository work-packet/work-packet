// Opening in VS Code: follow a vscode:// link once (docs/vscode-plan.md §3).
// The board cannot tell for sure whether this browser runs on the board's machine
// (a forwarded port looks like localhost), so the link you click is remembered
// here and followed next time.
(function () {
  "use strict";
  var KEY = "wpk-ide-link", pick = null;
  try { pick = window.localStorage.getItem(KEY); } catch (e) { /* private window */ }
  var links = document.querySelectorAll("a.ide-link");
  var go = document.getElementById("ide-go");
  [].forEach.call(links, function (a) {
    a.addEventListener("click", function () {
      try { window.localStorage.setItem(KEY, a.getAttribute("data-kind")); } catch (e) { /* */ }
    });
    if (pick && a.getAttribute("data-kind") === pick) go = a;
  });
  if (go && /^vscode:/.test(go.getAttribute("href"))) window.location.href = go.getAttribute("href");
})();
