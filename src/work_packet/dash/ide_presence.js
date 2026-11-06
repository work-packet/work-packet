// Web VS Code: tell the board this tab is open, and whether you can see it
// (docs/collaboration.md §4.2, §7.4). The board puts this in the workbench page;
// it posts to /ide/<key>/__wpk/vis: on load, on every visibility change, once a
// minute while open, and when the tab goes. Nothing about what you do is sent.
(function () {
  "use strict";
  var m = /^\/ide\/([0-9a-f]{12})\//.exec(location.pathname);
  if (!m) {
    return;
  }
  var url = "/ide/" + m[1] + "/__wpk/vis";
  var tab = Math.random().toString(36).slice(2, 12);
  function send(gone) {
    var body = JSON.stringify({tab: tab, visible: document.visibilityState === "visible",
                               gone: !!gone});
    if (gone && navigator.sendBeacon) {
      navigator.sendBeacon(url, new Blob([body], {type: "application/json"}));
      return;
    }
    try {
      fetch(url, {method: "POST", body: body, keepalive: true,
                  headers: {"content-type": "application/json"}}).catch(function () {});
    } catch (e) { /* the board is away: the next beat tries again */ }
  }
  send(false);
  document.addEventListener("visibilitychange", function () { send(false); });
  setInterval(function () { send(false); }, 60000);
  window.addEventListener("pagehide", function () { send(true); });
})();
