// Sets <html data-theme> before the first paint, so a chosen Light or Dark never flashes the
// other one, and <html data-style="new">, which the redesign's styles are scoped to. A plain
// script (not inline: the CSP allows only 'self'); src/appearance.ts has the same rules and
// keeps them up to date after load.
(function () {
  var choice = "auto";
  try {
    choice = localStorage.getItem("dam.appearance") || "auto";
  } catch (e) {}
  var dark = choice === "dark" || (choice !== "light" && matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.dataset.theme = dark ? "dark" : "light";
  document.documentElement.dataset.style = "new";
  var meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.content = dark ? "#1a1917" : "#ffffff";
})();
