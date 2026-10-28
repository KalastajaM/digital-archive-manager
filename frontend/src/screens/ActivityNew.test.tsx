/** Activity and Maintenance in the New look, as the boards draw them. Activity: the header
 * (title, count, Changes / AI calls), the filter row (search, four filters, Expand all and
 * the "Filters N" button that folds them in a narrow screen), who made each change as a chip
 * and Details or Review where there is no Undo. Maintenance: a row per check with its status
 * line and one button. Classic renders none of it. */
import { cleanup, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import type { BatchSummary, JournalEntry } from "../api/client";
import { RAN_KEY } from "../components/maintenance/lastRun";
import { maintenancePolling } from "../components/maintenance/useMaintenanceJob";
import { archiveKey } from "../api/client";
import { mockFetch, renderWithProviders } from "../test-utils";
import Activity from "./Activity";
import Maintenance from "./Maintenance";

function op(batch: string, overrides: Partial<JournalEntry> = {}): JournalEntry {
  return {
    id: 1,
    batch_id: batch,
    seq: 0,
    kind: "move",
    src: "##. Organize/scan001.pdf",
    dst: "10. Financial/Banks/lasku.pdf",
    drive_id: "d1",
    size: 10,
    mtime: 1,
    is_file: true,
    state: "done",
    error: null,
    origin: "ui",
    undo_of: null,
    created: 1_760_000_000,
    finished: 1_760_000_001,
    marks: [],
    ...overrides,
  };
}
const B1: BatchSummary = { batch_id: "b1", created: 1_760_000_000, origin: "ui", ops: [op("b1")], undone: false, is_undo: false, undoable: true };
const B2: BatchSummary = { batch_id: "b2", created: 1_750_000_000, origin: "cli", ops: [op("b2", { origin: "cli" })], undone: false, is_undo: false, undoable: true };

function api() {
  mockFetch({ "GET /api/activity": { body: [B1, B2] }, "GET /api/recovery": { body: [] } });
}
const activity = (url = "/activity") =>
  renderWithProviders(
    <MemoryRouter initialEntries={[url]}>
      <Activity />
    </MemoryRouter>,
  );

beforeEach(() => localStorage.clear());
afterEach(() => {
  cleanup();
  delete document.documentElement.dataset.style;
});

describe("Activity in New", () => {
  it("has a Filters N button that counts the filters in use and opens them", async () => {
    document.documentElement.dataset.style = "new";
    api();
    const user = userEvent.setup();
    activity("/activity?kind=trash&when=today");
    const button = await screen.findByRole("button", { name: /^Filters/ });
    expect(button).toHaveTextContent("Filters 2");
    expect(button).toHaveAttribute("aria-expanded", "false");
    expect(document.querySelector(".activity")).not.toHaveAttribute("data-filters");
    await user.click(button);
    expect(button).toHaveAttribute("aria-expanded", "true");
    expect(document.querySelector(".activity")).toHaveAttribute("data-filters", "open");
    // the filters themselves are still there for the keyboard and the screen reader
    expect(screen.getByRole("combobox", { name: "Kind of change" })).toBeInTheDocument();
    await user.click(button);
    expect(document.querySelector(".activity")).not.toHaveAttribute("data-filters");
  });

  it("names who made each change in a chip", async () => {
    document.documentElement.dataset.style = "new";
    api();
    activity();
    await screen.findByRole("article", { name: "Batch b1" });
    expect(within(screen.getByRole("article", { name: "Batch b1" })).getByText("You")).toHaveClass("batch-origin");
    expect(within(screen.getByRole("article", { name: "Batch b2" })).getByText("CLI")).toHaveClass("batch-origin");
  });

  it("puts the search and Expand all in the filter row, not in the header", async () => {
    document.documentElement.dataset.style = "new";
    api();
    const user = userEvent.setup();
    activity();
    await screen.findByRole("article", { name: "Batch b1" });
    const filters = screen.getByRole("group", { name: "Filters" });
    expect(within(filters).getByRole("searchbox", { name: "Search the changes" })).toBeInTheDocument();
    const header = document.querySelector(".activity-toolbar") as HTMLElement;
    expect(within(header).queryByRole("searchbox")).toBeNull();
    expect(within(header).queryByRole("button", { name: /all$/ })).toBeNull();
    expect(header).toHaveTextContent("2 changes, undone one at a time");
    const expand = within(filters).getByRole("button", { name: "Expand all" });
    await user.click(expand);
    expect(within(filters).getByRole("button", { name: "Collapse all" })).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: /^Hide the operations/ })).toHaveLength(2);
  });

  it("names the AI view AI calls", async () => {
    document.documentElement.dataset.style = "new";
    api();
    activity();
    await screen.findByRole("article", { name: "Batch b1" });
    expect(within(screen.getByRole("group", { name: "Show" })).getByRole("button", { name: "AI calls" })).toBeInTheDocument();
  });

  it("offers Undo on a done change, Details on an undone one and Review on an interrupted one", async () => {
    document.documentElement.dataset.style = "new";
    const undone: BatchSummary = { ...B2, batch_id: "b3", undone: true, undoable: false, ops: [op("b3", { state: "undone" })] };
    const interrupted: BatchSummary = { ...B2, batch_id: "b4", undoable: false, ops: [op("b4", { state: "planned" })] };
    mockFetch({ "GET /api/activity": { body: [B1, undone, interrupted] }, "GET /api/recovery": { body: [] } });
    const user = userEvent.setup();
    activity();
    const done = await screen.findByRole("article", { name: "Batch b1" });
    expect(within(done).getByRole("button", { name: "Undo" })).toBeInTheDocument();
    const gone = screen.getByRole("article", { name: "Batch b3" });
    expect(within(gone).queryByRole("button", { name: "Undo" })).toBeNull();
    const details = within(gone).getByRole("button", { name: /^Details of/ });
    expect(details).toHaveTextContent("Details");
    expect(details).toHaveAttribute("aria-expanded", "false");
    await user.click(details);
    expect(details).toHaveAttribute("aria-expanded", "true");
    const stopped = screen.getByRole("article", { name: "Batch b4" });
    expect(within(stopped).getByRole("button", { name: /^Review/ })).toHaveTextContent("Review");
    expect(within(stopped).getByText("Run recovery first")).toBeInTheDocument();
  });

  it("has neither in Classic", async () => {
    api();
    activity();
    await screen.findByRole("article", { name: "Batch b1" });
    expect(screen.queryByRole("button", { name: /^Filters/ })).not.toBeInTheDocument();
    expect(screen.queryByText("You")).not.toBeInTheDocument();
    expect(screen.getByText("command line")).toBeInTheDocument();
    // the search stays in the header, the filter row holds the filters alone
    const header = document.querySelector(".activity-toolbar") as HTMLElement;
    expect(within(header).getByRole("searchbox")).toBeInTheDocument();
    expect(within(screen.getByRole("group", { name: "Filters" })).queryByRole("searchbox")).toBeNull();
    expect(within(screen.getByRole("group", { name: "Show" })).getByRole("button", { name: "AI" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Details of/ })).toBeNull();
  });
});

describe("Maintenance in New", () => {
  function maintenance() {
    mockFetch({ "GET /api/maintenance/jobs": { body: [] } });
    renderWithProviders(
      <MemoryRouter initialEntries={["/maintenance"]}>
        <Maintenance />
      </MemoryRouter>,
    );
  }

  it("has Collapse all and Reset all as text buttons, and a longer subtitle", async () => {
    document.documentElement.dataset.style = "new";
    maintenance();
    expect(await screen.findByRole("button", { name: "Collapse all" })).toHaveTextContent("Collapse all");
    expect(screen.getByRole("button", { name: "Reset all" })).toHaveTextContent("Reset all");
    expect(screen.getByText(/every fix is previewed and can be undone/)).toBeInTheDocument();
    await userEvent.setup().click(screen.getByRole("button", { name: "Collapse all" }));
    expect(screen.getByRole("button", { name: "Expand all" })).toBeInTheDocument();
  });

  it("keeps the icon buttons in Classic", async () => {
    maintenance();
    const collapse = await screen.findByRole("button", { name: "Collapse all" });
    expect(collapse).not.toHaveTextContent("Collapse all");
    expect(screen.queryByText(/every fix is previewed/)).not.toBeInTheDocument();
  });

  it("has no icon buttons in the header, and one status line and one button per check", async () => {
    document.documentElement.dataset.style = "new";
    maintenance();
    await screen.findByRole("button", { name: "Collapse all" });
    const rows = document.querySelectorAll(".maintenance-body > .card");
    expect(rows).toHaveLength(10);
    for (const row of rows) {
      const head = row.querySelector(".card-header") as HTMLElement;
      expect(within(head).getByText("Not checked yet")).toHaveClass("check-status");
      expect(within(head).getAllByRole("button", { name: /^Check( again)?$/ })).toHaveLength(1);
      expect(row.querySelectorAll(".check-button")).toHaveLength(1);
    }
    // Moved outside dam and Left alone after a Drive restart are rows like the others
    expect(screen.getByRole("region", { name: "Moved outside dam" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Left alone after a Drive restart" })).toBeInTheDocument();
  });

  it("says what a check found and when, and Reset all forgets both", async () => {
    document.documentElement.dataset.style = "new";
    maintenancePolling.ms = 5;
    const done = {
      job_id: "job-1",
      kind: "empty_folders",
      state: "done",
      version: 1,
      done: 1,
      total: 1,
      bytes_done: 0,
      bytes_total: 0,
      current: null,
      elapsed_s: 0.1,
      error: null,
      empty_folders: { items: [{ drive_id: "f1", path: "20. Home/Old" }], total: 1 },
    };
    const routes: Parameters<typeof mockFetch>[0] = {
      "POST /api/maintenance/jobs": { body: { ...done, state: "running" } },
      "GET /api/maintenance/jobs/job-1": { body: done },
      "GET /api/maintenance/ignored": { body: [] },
      "DELETE /api/maintenance/jobs": { status: 204 },
    };
    for (const kind of ["duplicates", "broken_links", "references", "names", "waiting", "label_clashes", "unfinished_copies", "moved", "remounted"]) {
      routes[`GET /api/maintenance/jobs/latest/${kind}`] = { body: null };
    }
    routes["GET /api/maintenance/jobs/latest/empty_folders"] = { body: null };
    mockFetch(routes);
    const user = userEvent.setup();
    renderWithProviders(
      <MemoryRouter>
        <Maintenance />
      </MemoryRouter>,
    );
    const row = await screen.findByRole("region", { name: "Empty folders" });
    await user.click(within(row).getByRole("button", { name: "Check" }));
    const status = await within(row).findByText(/^1 empty folder · today \d\d:\d\d$/);
    expect(status).toHaveAttribute("data-tone", "found");
    expect(within(row).getByRole("button", { name: "Check again" })).toBeInTheDocument();
    expect(JSON.parse(localStorage.getItem(archiveKey(RAN_KEY)) ?? "{}")).toHaveProperty("empty_folders");
    maintenancePolling.ms = 700;
    await user.click(screen.getByRole("button", { name: "Reset all" }));
    await waitFor(() => expect(localStorage.getItem(archiveKey(RAN_KEY))).toBeNull());
    expect(within(await screen.findByRole("region", { name: "Empty folders" })).getByText("Not checked yet")).toBeInTheDocument();
  });

  it("keeps the old card in Classic: the button under the text, no status line", async () => {
    maintenance();
    const row = await screen.findByRole("region", { name: "Empty folders" });
    expect(row.querySelector(".check-status")).toBeNull();
    expect(row.querySelector(".card-body .check-actions button")).not.toBeNull();
    expect(row.querySelector(".card-header")?.querySelector("button.primary")).toBeNull();
  });
});
