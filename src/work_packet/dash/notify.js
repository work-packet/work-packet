// Browser notifications from an open board tab (docs/collaboration.md §4.3, plan C6).
// Off until you turn them on in Settings (this browser only). While on, the tab
// asks the board what to push every 30 s and shows a notification for each new
// question or blocked session, only while the tab is hidden: one per item (its
// key is the notification's tag, so several tabs show it once).
(function () {
  "use strict";
  var KEY = "wpk-notify", SEEN = "wpk-notify-seen";
  function get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }
  function put(k, v) { try { localStorage.setItem(k, v); } catch (e) {} }
  function seen() { try { return JSON.parse(get(SEEN) || "{}") || {}; } catch (e) { return {}; } }

  // Settings: the switch.
  document.addEventListener("DOMContentLoaded", function () {
    var b = document.getElementById("notify-browser"), s = document.getElementById("notify-browser-state");
    if (!b) return;
    function show() {
      var on = get(KEY) === "on" && window.Notification && Notification.permission === "granted";
      s.textContent = !window.Notification ? "this browser has no notifications" :
        Notification.permission === "denied" ? "blocked by this browser: allow them in its site settings" :
        on ? "on in this browser" : "off in this browser";
      b.textContent = on ? "Turn off" : "Turn on";
    }
    b.addEventListener("click", function () {
      if (!window.Notification) return;
      if (get(KEY) === "on") { put(KEY, "off"); show(); return; }
      Notification.requestPermission().then(function (p) {
        if (p === "granted") put(KEY, "on");
        show();
      });
    });
    show();
  });

  if (!window.Notification || !window.fetch) return;
  function poll() {
    if (get(KEY) !== "on" || Notification.permission !== "granted") return;
    fetch("/attention.json", {credentials: "same-origin", cache: "no-store"})
      .then(function (r) { return r.ok ? r.json() : {items: []}; })
      .then(function (d) {
        var old = seen(), now = {};
        (d.items || []).forEach(function (it) {
          now[it.key] = 1;
          if (old[it.key] || !document.hidden) return;
          var n = new Notification(it.title, {body: it.text, tag: it.key});
          n.onclick = function () { window.focus(); location.href = it.url; n.close(); };
        });
        // Remember what is open now: shown, or seen in the open tab.
        put(SEEN, JSON.stringify(now));
      }).catch(function () {});
  }
  setInterval(poll, 30000);
  setTimeout(poll, 2000);
})();
