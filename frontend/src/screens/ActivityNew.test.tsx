/** Activity and Maintenance in the New look: the "Filters N" button that folds the filters
 * in a narrow screen, who made each change as a chip, and Maintenance's text buttons.
 * Classic renders none of it. */
import { cleanup, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import type { BatchSummary, JournalEntry } from "../api/client";
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

  it("has neither in Classic", async () => {
    api();
    activity();
    await screen.findByRole("article", { name: "Batch b1" });
    expect(screen.queryByRole("button", { name: /^Filters/ })).not.toBeInTheDocument();
    expect(screen.queryByText("You")).not.toBeInTheDocument();
    expect(screen.getByText("command line")).toBeInTheDocument();
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
});
