/** The Inbox in the New look: a second divider (the filing panel's width) and, for a narrow
 * window, an "Inbox N" button that opens the folded list. Classic has neither. */
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import type { InboxEntry } from "../api/client";
import { mockFetch, renderWithProviders } from "../test-utils";
import Inbox from "./Inbox";

function entry(id: string, name: string): InboxEntry {
  return {
    record: {
      drive_id: id,
      path: `##. Organize/${name}`,
      name,
      ext: "pdf",
      is_dir: false,
      is_link: false,
      link_target: null,
      size: 1000,
      mtime: 1_760_000_000,
      sha256: null,
      doc_date: null,
      index_state: "indexed",
      retry_at: null,
      attempts: 0,
      missing: false,
      last_seen: null,
      parked_at: null,
      connected: true,
      marks: [],
    },
    suggestion: {
      name,
      folder: null,
      tags: [],
      fields: { dates: [], amounts: [], iban: null, reference: null },
      doc_date: null,
      sources: [],
      name_source: "scan",
      folder_source: null,
      tag_sources: {},
      tray: null,
      tray_source: null,
      collections: [],
      collection_sources: {},
      codes: [],
      conflict: false,
      star: null,
      important: null,
      marks_unclear: false,
      waiting_for_page1: false,
      people_found: [],
      areas: [],
      person_line: null,
    },
    text_excerpt: "",
    prefill: {},
    tray_guess: null,
    open_trays: [],
    fields: [],
    fields_edited: false,
  };
}

const ENTRIES = [entry("d1", "scan001.pdf"), entry("d2", "scan002.pdf")];

function setup(look: "new" | "classic") {
  if (look === "new") document.documentElement.dataset.style = "new";
  mockFetch({
    "GET /api/inbox": { body: ENTRIES },
    "GET /api/folders": { body: [] },
    "GET /api/trays": { body: { trays: [], errors: [] } },
    "GET /api/collections": { body: [] },
  });
  renderWithProviders(
    <MemoryRouter>
      <Inbox />
    </MemoryRouter>,
  );
  return userEvent.setup();
}

beforeEach(() => localStorage.clear());
afterEach(() => {
  cleanup();
  delete document.documentElement.dataset.style;
});

describe("Inbox in the New look", () => {
  it("has a divider for the filing panel next to the list's, remembered and reset by a double-click", async () => {
    setup("new");
    await screen.findByLabelText("Name");
    const panel = screen.getByRole("separator", { name: "Resize the filing panel" });
    expect(panel).toHaveAttribute("aria-valuenow", "360");
    expect(panel).toHaveClass("splitter-end");
    expect(screen.getByRole("separator", { name: "Resize the list" })).toHaveAttribute("aria-valuenow", "280");
    fireEvent.keyDown(panel, { key: "ArrowLeft" }); // the divider moves left: the panel grows
    expect(panel).toHaveAttribute("aria-valuenow", "376");
    expect(Object.values(localStorage).length).toBeGreaterThan(0);
    fireEvent.doubleClick(panel);
    expect(panel).toHaveAttribute("aria-valuenow", "360");
  });

  it("folds the list behind an Inbox N button: it opens, takes the focus, and Esc closes it", async () => {
    const user = setup("new");
    const button = await screen.findByRole("button", { name: "Inbox 2" });
    const list = screen.getByRole("navigation", { name: "Inbox" });
    expect(button).toHaveAttribute("aria-expanded", "false");
    expect(button).toHaveAttribute("aria-controls", list.id);
    await user.click(button);
    expect(button).toHaveAttribute("aria-expanded", "true");
    expect(list.closest(".inbox")).toHaveAttribute("data-queue", "open");
    await waitFor(() => expect(document.activeElement).toHaveAttribute("data-inbox-entry"));
    await user.keyboard("{Escape}");
    expect(button).toHaveAttribute("aria-expanded", "false");
    expect(list.closest(".inbox")).not.toHaveAttribute("data-queue");
    expect(button).toHaveFocus();
  });

  it("closes the folded list when a file is picked in it", async () => {
    const user = setup("new");
    const button = await screen.findByRole("button", { name: "Inbox 2" });
    await user.click(button);
    await user.click(screen.getByRole("button", { name: /scan002\.pdf/ }));
    // the card is made again for the other file, with its own button
    await waitFor(() => expect(screen.getByLabelText("Name")).toHaveValue("scan002.pdf"));
    expect(screen.getByRole("button", { name: "Inbox 2" })).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByRole("navigation", { name: "Inbox" }).closest(".inbox")).not.toHaveAttribute("data-queue");
    expect(screen.getByRole("button", { name: "Inbox 2" })).toHaveFocus();
  });
});

describe("Inbox in Classic", () => {
  it("has no filing panel divider and no Inbox N button", async () => {
    setup("classic");
    await screen.findByLabelText("Name");
    expect(screen.queryByRole("separator", { name: "Resize the filing panel" })).toBeNull();
    expect(screen.queryByRole("button", { name: /^Inbox \d/ })).toBeNull();
    expect(screen.getByRole("separator", { name: "Resize the list" })).toBeInTheDocument();
  });
});
