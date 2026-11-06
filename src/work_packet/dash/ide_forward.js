// Web VS Code: a localhost link opens through the board (port-forward plan §3.1).
// The board puts this ahead of the workbench's first script, so window.open is
// wrapped before workbench.js loads. A link to http://localhost:<port>/... goes
// to /ide/<key>/__wpk/open, which forwards it to the host where the IDE runs.
// The call stays synchronous: it keeps the click's user activation.
(function () {
  "use strict";
  var m = /^\/ide\/([0-9a-f]{12})\//.exec(location.pathname);
  if (!m) {
    return;
  }
  var open = window.open;
  var base = "/ide/" + m[1] + "/__wpk/open?u=";
  var local = /^https?:\/\/(localhost|127\.0\.0\.1|\[::1\])(:\d+)?([/?#]|$)/i;
  window.open = function (url) {
    var args = Array.prototype.slice.call(arguments);
    if (url !== undefined && url !== null && local.test(String(url))) {
      args[0] = base + encodeURIComponent(String(url));
    }
    return open.apply(window, args);
  };
})();
