import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { navigation } from "../api/client";
import { APPEARANCE_KEY } from "../appearance";
import { forgetKeptEdits } from "../components/codes/FilingCodes";
import { mockFetch, renderWithProviders } from "../test-utils";
import Settings from "./Settings";

function setup(path: string) {
  mockFetch({
    "GET /api/filing-codes": { body: { codes: [], problems: [], warnings: [] } },
    "GET /api/filing-codes/folders": { body: { missing: [], stray: [] } },
    "GET /api/trays": { body: { trays: [], skipped: [] } },
    "GET /api/archives": { body: { archives: [{ id: "main", name: "Home", color: "#3b6fd4", current: true }], can_switch: true } },
  });
  renderWithProviders(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/settings/:section?" element={<Settings />} />
      </Routes>
    </MemoryRouter>,
  );
  return userEvent.setup();
}

beforeEach(() => {
  forgetKeptEdits();
  localStorage.clear();
});

describe("Settings", () => {
  it("opens Filing codes first, with the sections listed by what they apply to", async () => {
    setup("/settings");
    expect(screen.getByRole("heading", { name: "Settings" })).toBeInTheDocument();
    expect(await screen.findByRole("region", { name: "Filing codes" })).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Appearance" })).toBeNull(); // one section at a time
    const nav = screen.getByRole("navigation", { name: "Settings sections" });
    expect(await within(nav).findByRole("heading", { name: "This archive · Home" })).toBeInTheDocument();
    expect(within(nav).getByRole("heading", { name: "This browser" })).toBeInTheDocument();
    expect(within(nav).getByRole("link", { name: "Filing codes" })).toHaveAttribute("aria-current", "page");
    expect(within(nav).getAllByRole("link").map((l) => l.getAttribute("href"))).toEqual([
      "/settings/filing-codes",
      "/settings/filing-rules",
      "/settings/indexing",
      "/settings/backups",
      "/settings/appearance",
    ]);
  });

  it("Indexing sets how fast page 1 of PDFs with a text layer is read, and the background reading", async () => {
    const calls = mockFetch({
      "GET /api/archives": { body: { archives: [{ id: "main", name: "Home", color: "#3b6fd4", current: true }], can_switch: true } },
      "GET /api/status": {
        body: { files: 1, page1: { read: 1, total: 2, backfill: true, blocked: [], text_per_min: 300, scans_per_min: 30, text_left: 1, scans_left: 0 } },
      },
      "PUT /api/settings/page1-speed": { body: { reads_per_minute: 600 } },
      "PUT /api/settings/page1-backfill": { body: { enabled: false } },
    });
    renderWithProviders(
      <MemoryRouter initialEntries={["/settings/indexing"]}>
        <Routes>
          <Route path="/settings/:section?" element={<Settings />} />
        </Routes>
      </MemoryRouter>,
    );
    const user = userEvent.setup();
    const section = await screen.findByRole("region", { name: "Indexing" });
    const speed = await within(section).findByRole("combobox", { name: "Page 1 reading speed" });
    expect(speed).toHaveValue("300");
    await user.selectOptions(speed, "600");
    expect(calls.find((c) => c.method === "PUT" && c.url === "/api/settings/page1-speed")?.body).toEqual({ reads_per_minute: 600 });
    await user.click(within(section).getByRole("checkbox", { name: /Read page 1 of older documents/ }));
    expect(calls.find((c) => c.method === "PUT" && c.url === "/api/settings/page1-backfill")?.body).toEqual({ enabled: false });
  });

  it("Backups lists the backups and makes one", async () => {
    const calls = mockFetch({
      "GET /api/archives": { body: { archives: [{ id: "main", name: "Home", color: "#3b6fd4", current: true }], can_switch: true } },
      "GET /api/backups": { body: backupsBody },
      "POST /api/backups": { body: { ...backupsBody.backups[0], name: "dam-backup-20261026-130000.zip" } },
    });
    const user = renderBackups();
    const section = await screen.findByRole("region", { name: "Backups" });
    const rows = await within(section).findAllByRole("listitem");
    expect(rows).toHaveLength(2);
    expect(within(rows[1]).getByText(/database version 0001/)).toBeInTheDocument();
    expect(within(rows[1]).getByText(/newer or different version/)).toBeInTheDocument();
    expect(within(rows[1]).getByRole("button", { name: "Restore…" })).toBeDisabled();
    await user.click(within(section).getByRole("button", { name: "Back up now" }));
    expect(await within(section).findByText(/Backed up as dam-backup-20261026-130000.zip/)).toBeInTheDocument();
    expect(calls.filter((c) => c.method === "POST" && c.url === "/api/backups")).toHaveLength(1);
  });

  it.each([
    ["Back up and restore", true],
    ["Restore without backup", false],
  ])("Restore asks whether to back up first: %s", async (choice, backupCurrent) => {
    const leave = vi.spyOn(navigation, "leave").mockImplementation(() => {});
    const name = backupsBody.backups[0].name;
    const calls = mockFetch({
      "GET /api/archives": { body: { archives: [{ id: "main", name: "Home", color: "#3b6fd4", current: true }], can_switch: true } },
      "GET /api/backups": { body: backupsBody },
      [`POST /api/backups/${name}/restore`]: { body: { restored: name, safety_backup: null, replaced_folder: "/d/backups/replaced-x" } },
    });
    const user = renderBackups();
    const section = await screen.findByRole("region", { name: "Backups" });
    const [first] = await within(section).findAllByRole("listitem");
    await user.click(within(first).getByRole("button", { name: "Restore…" }));
    const sheet = await screen.findByRole("dialog", { name: "Restore backup" });
    expect(within(sheet).getByText("Back up the current state first?")).toBeInTheDocument();
    expect(calls.filter((c) => c.url.endsWith("/restore"))).toHaveLength(0); // nothing before the answer
    await user.click(within(sheet).getByRole("button", { name: choice }));
    await vi.waitFor(() => expect(leave).toHaveBeenCalled());
    expect(calls.find((c) => c.url === `/api/backups/${name}/restore`)?.body).toEqual({ backup_current: backupCurrent });
    leave.mockRestore();
  });

  it("an unknown section opens the first", async () => {
    setup("/settings/nonsense");
    expect(await screen.findByRole("region", { name: "Filing codes" })).toBeInTheDocument();
  });

  it("Appearance applies the chosen theme at once and keeps it", async () => {
    const user = setup("/settings/appearance");
    const appearance = await screen.findByRole("region", { name: "Appearance" });
    expect(within(appearance).getByRole("button", { name: "Auto" })).toHaveAttribute("aria-pressed", "true");
    await user.click(within(appearance).getByRole("button", { name: "Dark" }));
    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(within(appearance).getByRole("button", { name: "Dark" })).toHaveAttribute("aria-pressed", "true");
    expect(localStorage.getItem(APPEARANCE_KEY)).toBe("dark");
    await user.click(within(appearance).getByRole("button", { name: "Light" }));
    expect(document.documentElement.dataset.theme).toBe("light");
  });
});

const backupsBody = {
  folder: "/d/backups",
  can_restore: true,
  backups: [
    {
      name: "dam-backup-20261026-120000.zip",
      created_at: "2026-10-26T12:00:00+02:00",
      size: 2048,
      kind: "manual",
      revision: "0034",
      app_version: "0.1.0",
      archive_root: "/a",
      problem: null,
    },
    {
      name: "dam-backup-20261020-090000.zip",
      created_at: "2026-10-20T09:00:00+02:00",
      size: 1024,
      kind: "manual",
      revision: "0001",
      app_version: "0.1.0",
      archive_root: "/a",
      problem: "The backup was made by a newer or different version of dam.",
    },
  ],
};

function renderBackups() {
  renderWithProviders(
    <MemoryRouter initialEntries={["/settings/backups"]}>
      <Routes>
        <Route path="/settings/:section?" element={<Settings />} />
      </Routes>
    </MemoryRouter>,
  );
  return userEvent.setup();
}
