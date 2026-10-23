// Sets <html data-theme> before the first paint, so a chosen Light or Dark never flashes
// the other one. A plain script (not inline: the CSP allows only 'self'); src/appearance.ts
// has the same rule and keeps it up to date after load.
(function () {
  var choice = "auto";
  try {
    choice = localStorage.getItem("dam.appearance") || "auto";
  } catch (e) {}
  var dark = choice === "dark" || (choice !== "light" && matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.dataset.theme = dark ? "dark" : "light";
  var meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.content = dark ? "#1e1e20" : "#fbfbfd";
})();
