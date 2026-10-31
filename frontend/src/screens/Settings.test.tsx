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
    "GET /api/archives": { body: { archives: [{ id: "main", name: "Home", color: "#3b6fd4", current: true, extra_folders: [] }], can_switch: true } },
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
      "/settings/folders",
      "/settings/indexing",
      "/settings/countries",
      "/settings/senders",
      "/settings/snapshots",
      "/settings/appearance",
    ]);
  });

  it("Indexing sets how fast page 1 of PDFs with a text layer is read, and the background reading", async () => {
    const calls = mockFetch({
      "GET /api/archives": { body: { archives: [{ id: "main", name: "Home", color: "#3b6fd4", current: true }], can_switch: true } },
      "GET /api/status": {
        body: {
          files: 1,
          page1: { read: 1, total: 2, backfill: true, blocked: [], text_per_min: 300, scans_per_min: 30, text_left: 1, scans_left: 0 },
          identifiers: { read: 1200, total: 10452 },
        },
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
    expect(await screen.findByText(/^Business IDs, IBANs and domains read from 1\D200 of 10\D452 documents\.$/)).toBeInTheDocument();
    const section = await screen.findByRole("region", { name: "Indexing" });
    const speed = await within(section).findByRole("combobox", { name: "Page 1 reading speed" });
    expect(speed).toHaveValue("300");
    await user.selectOptions(speed, "600");
    expect(calls.find((c) => c.method === "PUT" && c.url === "/api/settings/page1-speed")?.body).toEqual({ reads_per_minute: 600 });
    await user.click(within(section).getByRole("checkbox", { name: /Read page 1 of older documents/ }));
    expect(calls.find((c) => c.method === "PUT" && c.url === "/api/settings/page1-backfill")?.body).toEqual({ enabled: false });
  });

  it("Snapshots lists the snapshots, takes one, and offers each for export", async () => {
    const calls = mockFetch({
      "GET /api/archives": { body: archivesBody },
      "GET /api/snapshots": { body: snapshotsBody },
      "POST /api/snapshots": { body: { ...snapshotsBody.snapshots[0], name: "dam-snapshot-20261026-130000.zip" } },
    });
    const user = renderSnapshots();
    const section = await screen.findByRole("region", { name: "Snapshots" });
    const rows = await within(section).findAllByRole("listitem");
    expect(rows).toHaveLength(3);
    expect(within(rows[0]).getByRole("link", { name: "Export" })).toHaveAttribute(
      "href",
      "/api/snapshots/dam-snapshot-20261026-120000.zip/download",
    );
    expect(within(rows[1]).getByText(/imported/)).toBeInTheDocument();
    expect(within(rows[1]).getByText(/Of another archive folder: \/old\/Archive/)).toBeInTheDocument();
    expect(within(rows[2]).getByText(/newer or different version/)).toBeInTheDocument();
    const blocked = within(rows[2]).getByRole("button", { name: "Restore…" });
    expect(blocked).toBeDisabled();
    expect(blocked.parentElement).toHaveAttribute("data-tip", expect.stringMatching(/newer or different version/));
    expect(within(rows[0]).getByRole("link", { name: "Export" })).toHaveAttribute("data-tip", expect.stringMatching(/same as copying it/));
    await user.click(within(section).getByRole("button", { name: "Take snapshot" }));
    expect(await within(section).findByText(/Snapshot taken: dam-snapshot-20261026-130000.zip/)).toBeInTheDocument();
    expect(calls.filter((c) => c.method === "POST" && c.url === "/api/snapshots")).toHaveLength(1);
  });

  it("Import sends the picked file as it is", async () => {
    const calls = mockFetch({
      "GET /api/archives": { body: archivesBody },
      "GET /api/snapshots": { body: snapshotsBody },
      "POST /api/snapshots/import": { body: snapshotsBody.snapshots[1] },
    });
    const user = renderSnapshots();
    const section = await screen.findByRole("region", { name: "Snapshots" });
    const file = new File(["PK"], "dam-snapshot-20261020-090000.zip", { type: "application/zip" });
    await user.upload(within(section).getByLabelText("Snapshot file to import"), file);
    expect(await within(section).findByText(/Imported the snapshot from/)).toBeInTheDocument();
    const sent = calls.find((c) => c.url === "/api/snapshots/import");
    expect(sent?.method).toBe("POST");
  });

  it.each([
    ["Take snapshot and restore", true],
    ["Restore without snapshot", false],
  ])("Restore asks whether to take a snapshot first: %s", async (choice, snapshotCurrent) => {
    const leave = vi.spyOn(navigation, "leave").mockImplementation(() => {});
    const name = snapshotsBody.snapshots[0].name;
    const calls = mockFetch({
      "GET /api/archives": { body: archivesBody },
      "GET /api/snapshots": { body: snapshotsBody },
      [`POST /api/snapshots/${name}/restore`]: {
        body: { restored: name, safety_snapshot: null, replaced_folder: "/d/snapshots/replaced-x", kept_folders: false },
      },
    });
    const user = renderSnapshots();
    const section = await screen.findByRole("region", { name: "Snapshots" });
    const [first] = await within(section).findAllByRole("listitem");
    await user.click(within(first).getByRole("button", { name: "Restore…" }));
    const sheet = await screen.findByRole("dialog", { name: "Restore snapshot" });
    expect(within(sheet).getByText("Take a snapshot of the current state first?")).toBeInTheDocument();
    expect(within(sheet).queryByRole("checkbox")).toBeNull();
    expect(calls.filter((c) => c.url.endsWith("/restore"))).toHaveLength(0); // nothing before the answer
    await user.click(within(sheet).getByRole("button", { name: choice }));
    await vi.waitFor(() => expect(leave).toHaveBeenCalled());
    expect(calls.find((c) => c.url === `/api/snapshots/${name}/restore`)?.body).toEqual({
      snapshot_current: snapshotCurrent,
      other_folder_ok: false,
    });
    leave.mockRestore();
  });

  it("a snapshot of another archive folder is restored only once that is confirmed", async () => {
    const leave = vi.spyOn(navigation, "leave").mockImplementation(() => {});
    const name = snapshotsBody.snapshots[1].name;
    const calls = mockFetch({
      "GET /api/archives": { body: archivesBody },
      "GET /api/snapshots": { body: snapshotsBody },
      [`POST /api/snapshots/${name}/restore`]: {
        body: { restored: name, safety_snapshot: null, replaced_folder: "/d/snapshots/replaced-x", kept_folders: true },
      },
    });
    const user = renderSnapshots();
    const section = await screen.findByRole("region", { name: "Snapshots" });
    const rows = await within(section).findAllByRole("listitem");
    await user.click(within(rows[1]).getByRole("button", { name: "Restore…" }));
    const sheet = await screen.findByRole("dialog", { name: "Restore snapshot" });
    const restore = within(sheet).getByRole("button", { name: "Take snapshot and restore" });
    expect(restore).toBeDisabled();
    expect(within(sheet).getByRole("button", { name: "Restore without snapshot" })).toBeDisabled();
    await user.click(within(sheet).getByRole("checkbox", { name: /another archive folder/ }));
    await user.click(restore);
    await vi.waitFor(() => expect(leave).toHaveBeenCalled());
    expect(calls.find((c) => c.url === `/api/snapshots/${name}/restore`)?.body).toEqual({
      snapshot_current: true,
      other_folder_ok: true,
    });
    leave.mockRestore();
  });

  it("Archive folders lists the folders of this archive", async () => {
    mockFetch({
      "GET /api/archives": { body: { archives: [{ id: "main", name: "Home", color: "#3b6fd4", current: true }], can_switch: true } },
      "GET /api/archive-folders": { body: { folders: [{ label: null, path: "/Archive", attached: true, connected: true, files: 5 }] } },
    });
    renderWithProviders(
      <MemoryRouter initialEntries={["/settings/folders"]}>
        <Routes>
          <Route path="/settings/:section?" element={<Settings />} />
        </Routes>
      </MemoryRouter>,
    );
    const section = await screen.findByRole("region", { name: "Archive folders" });
    expect(await within(section).findByText("Main folder")).toBeInTheDocument();
  });

  it("an unknown section opens the first", async () => {
    setup("/settings/nonsense");
    expect(await screen.findByRole("region", { name: "Filing codes" })).toBeInTheDocument();
  });

  it("Reset layout forgets the pane widths and Today's cards for every archive, and Undo brings them back", async () => {
    localStorage.setItem("dam.browse.listwidth", "60");
    localStorage.setItem("dam.inbox.panelwidth.other", "500");
    localStorage.setItem("dam.today.layout.v1", '{"order":["a"],"collapsed":{}}');
    localStorage.setItem("dam.browse.split", "1"); // one pane or two is not a width: it stays
    const user = setup("/settings/appearance");
    const appearance = await screen.findByRole("region", { name: "Appearance" });
    expect(within(appearance).getByText(/remembered in this browser, per screen/)).toBeInTheDocument();
    await user.click(within(appearance).getByRole("button", { name: "Reset layout" }));
    expect(localStorage.getItem("dam.browse.listwidth")).toBeNull();
    expect(localStorage.getItem("dam.inbox.panelwidth.other")).toBeNull();
    expect(localStorage.getItem("dam.today.layout.v1")).toBeNull();
    expect(localStorage.getItem("dam.browse.split")).toBe("1");
    expect(await screen.findByText(/Layout reset/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Undo" }));
    expect(localStorage.getItem("dam.browse.listwidth")).toBe("60");
    expect(localStorage.getItem("dam.inbox.panelwidth.other")).toBe("500");
    expect(localStorage.getItem("dam.today.layout.v1")).toBe('{"order":["a"],"collapsed":{}}');
  });

  it("Reset layout says so when there is nothing to reset", async () => {
    const user = setup("/settings/appearance");
    const appearance = await screen.findByRole("region", { name: "Appearance" });
    await user.click(within(appearance).getByRole("button", { name: "Reset layout" }));
    expect(await screen.findByText(/Nothing to reset/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Undo" })).not.toBeInTheDocument();
  });
});

const archivesBody = { archives: [{ id: "main", name: "Home", color: "#3b6fd4", current: true }], can_switch: true };

const snapshot = {
  size: 2048,
  kind: "manual",
  imported: false,
  revision: "0034",
  app_version: "0.1.0",
  archive_root: "/a",
  other_folder: false,
  problem: null,
};

const snapshotsBody = {
  folder: "/d/snapshots",
  can_restore: true,
  snapshots: [
    { ...snapshot, name: "dam-snapshot-20261026-120000.zip", created_at: "2026-10-26T12:00:00+02:00" },
    {
      ...snapshot,
      name: "dam-snapshot-20261020-090000-imported.zip",
      created_at: "2026-10-20T09:00:00+02:00",
      imported: true,
      archive_root: "/old/Archive",
      other_folder: true,
    },
    {
      ...snapshot,
      name: "dam-snapshot-20261001-090000.zip",
      created_at: "2026-10-01T09:00:00+02:00",
      revision: "9999",
      problem: "The snapshot was made by a newer or different version of dam.",
    },
  ],
};

function renderSnapshots() {
  renderWithProviders(
    <MemoryRouter initialEntries={["/settings/snapshots"]}>
      <Routes>
        <Route path="/settings/:section?" element={<Settings />} />
      </Routes>
    </MemoryRouter>,
  );
  return userEvent.setup();
}

describe("Settings Appearance", () => {
  it("arranges Theme, Layout and Archive colour as separate groups under a title that says where it is kept", async () => {
    setup("/settings/appearance");
    const section = await screen.findByRole("region", { name: "Appearance" });
    expect(within(section).getByText("Kept in this browser, the same for every archive.")).toBeInTheDocument();
    const groups = [...section.querySelectorAll("fieldset > legend")].map((l) => l.textContent);
    expect(groups).toEqual(["Theme", "Layout", "Archive colour"]);
    expect(within(section).getByText("Auto follows your computer's setting.")).toBeInTheDocument();
    expect(within(section).getByRole("button", { name: "Reset layout" })).toBeInTheDocument();
  });

  it("takes the theme from radios, applied at once", async () => {
    const user = setup("/settings/appearance");
    const section = await screen.findByRole("region", { name: "Appearance" });
    const theme = within(section).getByRole("radiogroup", { name: "Appearance" });
    expect(within(theme).getByRole("radio", { name: "Auto" })).toBeChecked();
    await user.click(within(theme).getByRole("radio", { name: "Dark" }));
    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(localStorage.getItem(APPEARANCE_KEY)).toBe("dark");
    expect(within(theme).getByRole("radio", { name: "Dark" })).toBeChecked();
  });

  it("opens Manage archives from the note on the archive colour", async () => {
    const user = setup("/settings/appearance");
    const section = await screen.findByRole("region", { name: "Appearance" });
    expect(within(section).getByText(/Every archive except Main gets a coloured band/)).toBeInTheDocument();
    await user.click(within(section).getByRole("button", { name: "Manage archives" }));
    expect(await screen.findByRole("dialog", { name: "Manage archives" })).toBeInTheDocument();
  });
});
