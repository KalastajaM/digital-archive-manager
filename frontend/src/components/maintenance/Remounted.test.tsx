/** "Left alone after a Drive restart": each root is listed with its entries; one where
 * only the device number changed offers Take over, which previews first, then applies,
 * and Undo in its message puts the old numbers back; another one says why it stays. */
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it } from "vitest";
import type { MaintenanceJob, RemountedRoot } from "../../api/client";
import { type Call, mockFetch, renderWithProviders } from "../../test-utils";
import { Remounted } from "./Remounted";
import { maintenancePolling } from "./useMaintenanceJob";

const entry = (id: number, rel: string, kind: "link" | "folder" = "link") => ({
  id,
  rel,
  kind,
  st_ino: String(100 + id),
  old_dev: "16777233",
  new_dev: "16777229",
});

const ONGOING: RemountedRoot = {
  root: "##. Ongoing",
  entries: [entry(1, "##. Ongoing/Mathildedal", "folder"), entry(2, "##. Ongoing/Pirkko.xlsx")],
  offered: true,
  reason: null,
};
const IMPORTANT: RemountedRoot = {
  root: "##. Important",
  entries: [entry(3, "##. Important/Houses")],
  offered: false,
  reason: "##. Important/Houses has a new inode number too",
};

function job(roots: RemountedRoot[]): MaintenanceJob {
  return {
    job_id: "job-remounted",
    kind: "remounted",
    state: "done",
    version: 1,
    done: 0,
    total: 0,
    bytes_done: 0,
    bytes_total: 0,
    current: null,
    elapsed_s: 0.1,
    error: null,
    remounted: { roots },
  };
}

const posts = (calls: Call[], url: string) => calls.filter((c) => c.method === "POST" && c.url === url);

function setup(extra = {}) {
  const calls = mockFetch({
    "GET /api/maintenance/jobs/latest/remounted": { body: job([ONGOING, IMPORTANT]) },
    "GET /api/maintenance/jobs/job-remounted": { body: job([]) },
    "POST /api/maintenance/remounted/readopt": (call: Call) => {
      const body = call.body as { roots: string[]; dry_run: boolean };
      return { body: { dry_run: body.dry_run, roots: [ONGOING], errors: [], undo_id: body.dry_run ? null : "u1" } };
    },
    "POST /api/maintenance/remounted/undo": { body: { dry_run: false, roots: [ONGOING], errors: [], undo_id: null } },
    ...extra,
  });
  const user = userEvent.setup();
  renderWithProviders(
    <MemoryRouter>
      <Remounted />
    </MemoryRouter>,
  );
  return { calls, user };
}

beforeEach(() => {
  maintenancePolling.ms = 5;
});

describe("Left alone after a Drive restart", () => {
  it("lists each root; only the one with just a new device number offers Take over", async () => {
    setup();
    const list = await screen.findByRole("list");
    const [ongoing, important] = within(list).getAllByRole("listitem");
    expect(ongoing).toHaveTextContent("##. Ongoing: 2 entries");
    expect(ongoing).toHaveTextContent("Only the device number changed (16777233 → 16777229).");
    expect(within(ongoing).getByRole("button", { name: "Take over…" })).toBeInTheDocument();
    expect(important).toHaveTextContent("Left alone: ##. Important/Houses has a new inode number too.");
    expect(within(important).queryByRole("button")).not.toBeInTheDocument();
  });

  it("previews, takes over, and Undo puts the old numbers back", async () => {
    const { calls, user } = setup();
    await user.click(await screen.findByRole("button", { name: "Take over…" }));
    const sheet = await screen.findByRole("dialog", { name: "Take over 2 entries?" });
    expect(within(sheet).getByText("##. Ongoing/Pirkko.xlsx")).toBeInTheDocument();
    expect(within(sheet).getByText(/Undo in the message afterwards/)).toBeInTheDocument();
    await user.click(within(sheet).getByRole("button", { name: "Take over" }));
    expect(await screen.findByText("Took over 2 entries")).toBeInTheDocument();
    expect(posts(calls, "/api/maintenance/remounted/readopt").map((c) => c.body)).toEqual([
      { roots: ["##. Ongoing"], dry_run: true },
      { roots: ["##. Ongoing"], dry_run: false },
    ]);
    await user.click(screen.getByRole("button", { name: "Undo" }));
    expect(await screen.findByText("Put back the old number of 2 entries")).toBeInTheDocument();
    expect(posts(calls, "/api/maintenance/remounted/undo").map((c) => c.body)).toEqual([{ undo_id: "u1" }]);
  });

  it("Cancel changes nothing", async () => {
    const { calls, user } = setup();
    await user.click(await screen.findByRole("button", { name: "Take over…" }));
    const sheet = await screen.findByRole("dialog");
    await user.click(within(sheet).getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(posts(calls, "/api/maintenance/remounted/readopt")).toHaveLength(1);
  });

  it("says why nothing was taken over", async () => {
    const { user } = setup({
      "POST /api/maintenance/remounted/readopt": { status: 400, body: { error: "There is nothing to take over" } },
    });
    await user.click(await screen.findByRole("button", { name: "Take over…" }));
    expect(await screen.findByText(/Not taken over: There is nothing to take over/)).toBeInTheDocument();
  });
});
