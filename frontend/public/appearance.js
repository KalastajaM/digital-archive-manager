// Sets <html data-theme> and <html data-style> before the first paint, so a chosen Light or
// Dark, or the New look, never flashes the other one. A plain script (not inline: the CSP
// allows only 'self'); src/appearance.ts has the same rules and keeps them up to date after load.
(function () {
  var choice = "auto";
  var look = "new";
  try {
    choice = localStorage.getItem("dam.appearance") || "auto";
    look = localStorage.getItem("dam.style") === "classic" ? "classic" : "new";
  } catch (e) {}
  var dark = choice === "dark" || (choice !== "light" && matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.dataset.theme = dark ? "dark" : "light";
  document.documentElement.dataset.style = look;
  var meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.content = look === "new" ? (dark ? "#1a1917" : "#ffffff") : dark ? "#1e1e20" : "#fbfbfd";
})();
