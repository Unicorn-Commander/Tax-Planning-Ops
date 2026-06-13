/* Daylight & Paper — theme toggle (mockup demo of the real switchable theme).
   Order of precedence: ?theme= URL param > saved choice > OS preference.
   Sets <html data-theme> immediately (no flash) and injects a floating toggle.
   In the real app this is a setting in the avatar menu + a cookie, read
   server-side to avoid any flash (Stripe's lesson). */
(function () {
  var KEY = "tpo-theme";
  var param = new URLSearchParams(location.search).get("theme");
  var osDark = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
  var theme = param || localStorage.getItem(KEY) || (osDark ? "dark" : "light");
  document.documentElement.setAttribute("data-theme", theme);

  function apply(t) {
    document.documentElement.setAttribute("data-theme", t);
    try { localStorage.setItem(KEY, t); } catch (e) {}
    if (btn) btn.textContent = t === "dark" ? "☀" : "☾"; // sun / moon
  }
  var btn;
  document.addEventListener("DOMContentLoaded", function () {
    btn = document.createElement("button");
    btn.className = "theme-toggle";
    btn.setAttribute("aria-label", "Toggle dark mode");
    btn.title = "Toggle dark mode";
    btn.textContent = document.documentElement.getAttribute("data-theme") === "dark" ? "☀" : "☾";
    btn.addEventListener("click", function () {
      apply(document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark");
    });
    document.body.appendChild(btn);
  });
})();
