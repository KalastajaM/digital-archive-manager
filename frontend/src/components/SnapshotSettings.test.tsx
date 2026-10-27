import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { navigation } from "../api/client";
import { mockFetch, renderWithProviders } from "../test-utils";
import { SnapshotSettings } from "./SnapshotSettings";

const snap = (name: string, extra: Record<string, unknown> = {}) => ({
  name,
  created_at: "2026-10-20T10:00:00",
  size: 2048,
  kind: "manual",
  imported: false,
  revision: "0042",
  app_version: "1",
  archive_root: "/archive",
  other_folder: false,
  problem: null,
  ...extra,
});
const list = (snapshots: unknown[], can_restore = true) => ({ folder: "/data/snapshots", snapshots, can_restore });

afterEach(() => vi.restoreAllMocks());

describe("SnapshotSettings", () => {
  it("lists the snapshots with their marks and an Export link", async () => {
    mockFetch({ "GET /api/snapshots": { body: list([snap("a.zip"), snap("b.zip", { kind: "before-restore", imported: true })]) } });
    renderWithProviders(<SnapshotSettings />);
    const rows = within(await screen.findByRole("list", { name: "Snapshots" })).getAllByRole("listitem");
    expect(rows).toHaveLength(2);
    expect(rows[1]).toHaveTextContent("taken before a restore · imported");
    expect(within(rows[0]).getByRole("link", { name: "Export" })).toHaveAttribute("href", "/api/snapshots/a.zip/download");
  });

  it("says so when there are none, and takes a snapshot on click", async () => {
    const user = userEvent.setup();
    let now: unknown[] = [];
    const calls = mockFetch({
      "GET /api/snapshots": () => ({ body: list(now) }),
      "POST /api/snapshots": () => {
        now = [snap("new.zip")];
        return { body: snap("new.zip") };
      },
    });
    renderWithProviders(<SnapshotSettings />);
    expect(await screen.findByText("No snapshots yet.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Take snapshot" }));
    expect(await screen.findByText("Snapshot taken: new.zip.")).toBeInTheDocument();
    expect(calls.some((c) => c.method === "POST" && c.url === "/api/snapshots")).toBe(true);
    expect(await screen.findByRole("list", { name: "Snapshots" })).toBeInTheDocument();
  });

  it("shows a failure to take a snapshot and to load the list", async () => {
    const user = userEvent.setup();
    mockFetch({
      "GET /api/snapshots": { status: 409, body: { error: "database is locked" } },
      "POST /api/snapshots": { status: 409, body: { error: "disk full" } },
    });
    renderWithProviders(<SnapshotSettings />);
    expect(await screen.findByText(/Could not load the snapshots: database is locked/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Take snapshot" }));
    expect(await screen.findByText(/Could not take a snapshot: disk full/)).toBeInTheDocument();
  });

  it("asks before restoring, can restore without a snapshot, then leaves the page", async () => {
    const user = userEvent.setup();
    const leave = vi.spyOn(navigation, "leave").mockImplementation(() => {});
    const calls = mockFetch({
      "GET /api/snapshots": { body: list([snap("a.zip")]) },
      "POST /api/snapshots/a.zip/restore": { body: { restored: "a.zip", safety_snapshot: null, replaced_folder: "", kept_folders: true } },
    });
    renderWithProviders(<SnapshotSettings />);
    await user.click(await screen.findByRole("button", { name: "Restore…" }));
    expect(screen.getByText("Take a snapshot of the current state first?")).toBeInTheDocument();
    expect(calls.some((c) => c.url.endsWith("/restore"))).toBe(false);
    await user.click(screen.getByRole("button", { name: "Restore without snapshot" }));
    await waitFor(() => expect(leave).toHaveBeenCalledTimes(1));
    expect(calls.find((c) => c.url.endsWith("/restore"))?.body).toEqual({ snapshot_current: false, other_folder_ok: false });
  });

  it("a snapshot of another archive folder needs a tick, and a failed restore says why", async () => {
    const user = userEvent.setup();
    mockFetch({
      "GET /api/snapshots": { body: list([snap("o.zip", { other_folder: true, archive_root: "/elsewhere" })]) },
      "POST /api/snapshots/o.zip/restore": { status: 409, body: { error: "a restore is running" } },
    });
    renderWithProviders(<SnapshotSettings />);
    await user.click(await screen.findByRole("button", { name: "Restore…" }));
    const restore = screen.getByRole("button", { name: "Take snapshot and restore" });
    expect(restore).toBeDisabled();
    await user.click(screen.getByRole("checkbox"));
    await user.click(restore);
    expect(await screen.findByText(/Could not restore: a restore is running/)).toBeInTheDocument();
  });

  it("Restore is off where the window cannot restore", async () => {
    mockFetch({ "GET /api/snapshots": { body: list([snap("a.zip")], false) } });
    renderWithProviders(<SnapshotSettings />);
    expect(await screen.findByRole("button", { name: "Restore…" })).toBeDisabled();
    expect(screen.getByText(/This window cannot restore a snapshot. Start dam/)).toBeInTheDocument();
  });
});
