// Write openapi.json from the backend's schema without touching the real archive:
// `dam openapi` runs on a throwaway data dir whose settings point at an empty folder.
import { spawnSync } from "node:child_process";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const tmp = mkdtempSync(join(tmpdir(), "dam-openapi-"));
try {
  const archive = join(tmp, "archive");
  mkdirSync(archive);
  mkdirSync(join(tmp, "data", "config"), { recursive: true });
  writeFileSync(
    join(tmp, "data", "config", "settings.yaml"),
    `archive_root: ${JSON.stringify(archive)}\n`,
  );
  const r = spawnSync(
    "uv",
    ["--directory", "../backend", "run", "dam", "--data-dir", join(tmp, "data"), "openapi"],
    // the schema passed 1 MB, spawnSync's default output limit (it then kills the child)
    { encoding: "utf8", stdio: ["ignore", "pipe", "inherit"], maxBuffer: 64 * 1024 * 1024 },
  );
  if (r.status !== 0) {
    console.error(`dam openapi failed (exit ${r.status ?? r.signal})`);
    process.exit(1);
  }
  JSON.parse(r.stdout); // fail loudly on anything but JSON
  writeFileSync("openapi.json", r.stdout);
} finally {
  rmSync(tmp, { recursive: true, force: true });
}
