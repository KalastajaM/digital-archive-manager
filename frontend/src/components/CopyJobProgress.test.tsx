import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { type Call, mockFetch, renderWithProviders } from "../test-utils";
import { CopyJobProgress, startedCopyJob } from "./CopyJobProgress";

const job = (over: Record<string, unknown> = {}) => ({
  job_id: "j1",
  state: "running",
  version: 3,
  done: 3,
  total: 10,
  bytes_done: 3 * 1024 * 1024,
  bytes_total: 10 * 1024 * 1024,
  current: "d.pdf",
  elapsed_s: 4,
  error: null,
  result: null,
  ...over,
});
const batch = { batch_id: "b1", dry_run: false, done: [], failed: null, error: null, index_error: null, stopped: false, job_id: null };
const posts = (calls: Call[], url: string) => calls.filter((c) => c.method === "POST" && c.url === url);

describe("Move across disks progress", () => {
  it("shows files, bytes and the file being copied, and Stop asks the server", async () => {
    const calls = mockFetch({
      "GET /api/browse/move/jobs/latest": { body: null },
      "GET /api/browse/move/jobs/j1": { body: job() },
      "POST /api/browse/move/jobs/j1/stop": { body: job({ state: "stopped" }) },
    });
    renderWithProviders(<CopyJobProgress />);
    act(() => startedCopyJob("j1"));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("3 of 10 files (3,0 MB of 10 MB)")).toBeInTheDocument();
    expect(within(dialog).getByText("Copying d.pdf")).toBeInTheDocument();
    await userEvent.setup().click(within(dialog).getByRole("button", { name: "Stop" }));
    await waitFor(() => expect(posts(calls, "/api/browse/move/jobs/j1/stop")).toHaveLength(1));
  });

  it("picks up a move still running after a reload, and keeps a line when closed", async () => {
    mockFetch({
      "GET /api/browse/move/jobs/latest": { body: job() },
      "GET /api/browse/move/jobs/j1": { body: job() },
    });
    renderWithProviders(<CopyJobProgress />);
    const dialog = await screen.findByRole("dialog");
    await userEvent.setup().click(within(dialog).getByRole("button", { name: "Hide" }));
    expect(await screen.findByRole("button", { name: "Moving across disks: 3 of 10 files" })).toBeInTheDocument();
  });

  it("ends with a toast that offers Undo", async () => {
    mockFetch({
      "GET /api/browse/move/jobs/latest": { body: null },
      "GET /api/browse/move/jobs/j1": { body: job({ state: "done", done: 10, result: batch }) },
    });
    renderWithProviders(<CopyJobProgress />);
    act(() => startedCopyJob("j1"));
    expect(await screen.findByText("Moved 10 files across disks")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Undo" })).toBeInTheDocument();
  });

  it("a folder move ends with the server's own words", async () => {
    mockFetch({
      "GET /api/browse/move/jobs/latest": { body: null },
      "GET /api/browse/move/jobs/j1": {
        body: job({ state: "done", done: 2, result: { ...batch, message: "Moved folder 2009 (2 files) to 'Old years'" } }),
      },
    });
    renderWithProviders(<CopyJobProgress />);
    act(() => startedCopyJob("j1"));
    expect(await screen.findByText("Moved folder 2009 (2 files) to 'Old years'")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Undo" })).toBeInTheDocument();
  });

  it("a stopped move says how far it got", async () => {
    mockFetch({
      "GET /api/browse/move/jobs/latest": { body: null },
      "GET /api/browse/move/jobs/j1": {
        body: job({ state: "stopped", result: { ...batch, stopped: true, error: "Stopped: 3 of 10 files moved." } }),
      },
    });
    renderWithProviders(<CopyJobProgress />);
    act(() => startedCopyJob("j1"));
    expect(await screen.findByText("Stopped: 3 of 10 files moved.")).toBeInTheDocument();
  });
});
