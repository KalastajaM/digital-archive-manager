/** A collection in the New look, laid out as drawn: the header (parent line, name, state pill,
 * counts, buttons), the sections in order (Summary, Needs attention, Files by group, Notes and
 * Checklist), the side panel with its buttons under the preview, the "File details" button
 * that opens the panel over the list when the page is narrow, and Show folder and Export in
 * the ... menu. Classic renders none of it. */
import { cleanup, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import type { Collection } from "../api/client";
import { mockFetch, renderWithProviders } from "../test-utils";
import Collections from "./Collections";

const SAUNA: Collection = {
  id: 7,
  name: "Sauna",
  state: "open",
  created: 1_760_000_000,
  closed_at: null,
  publish: { ongoing: false },
  ongoing_rel: null,
  members: [
    { drive_id: "f1", path: "40. House/Sauna/quote.pdf", is_dir: false, missing: false, quarantined: false, is_link: false, group_id: null, connected: true, marks: [] },
  ],
  ongoing_status: null,
  summary: "",
  groups: [],
  parent_id: null,
  path: ["Sauna"],
  kind: null,
  position: 0,
};

function setup() {
  mockFetch({
    "GET /api/collections": { body: [{ ...SAUNA, files: 1, open_checks: 0 }] },
    "GET /api/collections/7": { body: SAUNA },
    "GET /api/notes/collection/7": { body: { text: "" } },
    "GET /api/checklist/collection/7": { body: [] },
    "GET /api/files/f1/links": { body: { items: [], collections: [], note: "" } },
  });
  const user = userEvent.setup();
  renderWithProviders(
    <MemoryRouter initialEntries={["/collections/7"]}>
      <Routes>
        <Route path="/collections/:id?" element={<Collections today="2026-10-19" />} />
      </Routes>
    </MemoryRouter>,
  );
  return { user };
}

beforeEach(() => localStorage.clear());
afterEach(() => {
  cleanup();
  delete document.documentElement.dataset.style;
});

describe("a collection in New", () => {
  it("opens the file details over the list from a button and closes them again", async () => {
    document.documentElement.dataset.style = "new";
    const { user } = setup();
    const details = await screen.findByRole("button", { name: "File details" });
    expect(details).toHaveAttribute("aria-expanded", "false");
    const cols = document.querySelector(".collection-cols") as HTMLElement;
    expect(cols.dataset.details).toBeUndefined();
    await user.click(details);
    expect(cols.dataset.details).toBe("open");
    expect(details).toHaveAttribute("aria-expanded", "true");
    await user.click(document.querySelector(".details-scrim") as HTMLElement);
    expect(cols.dataset.details).toBeUndefined();
  });

  it("puts Show folder and Export as buttons in the header, and in the ... menu too", async () => {
    document.documentElement.dataset.style = "new";
    const { user } = setup();
    await screen.findByRole("button", { name: "File details" });
    expect(document.querySelectorAll(".collection-head .hdr-wide")).toHaveLength(2);
    expect(screen.getByRole("button", { name: "Show folder" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Export…" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add files" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "More actions" }));
    expect(await screen.findByRole("menuitem", { name: "Show folder" })).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: "Export…" })).toBeInTheDocument();
  });

  it("draws the header as the board does: the parent line, the name, a state pill and the counts", async () => {
    document.documentElement.dataset.style = "new";
    const { user } = setup();
    await screen.findByRole("button", { name: "File details" });
    const head = document.querySelector(".collection-head") as HTMLElement;
    expect(head).toHaveTextContent("Collection · no parent ·");
    expect(within(head).getByRole("button", { name: "Rename Sauna" })).toBeInTheDocument();
    expect(head.querySelector(".collection-state")).toHaveTextContent("Open");
    expect(head.querySelector(".collection-head-count")).toHaveTextContent("1 file");
    await user.click(within(head).getByRole("button", { name: "Put inside another collection…" }));
    expect(await screen.findByRole("dialog", { name: /Move Sauna to/ })).toBeInTheDocument();
  });

  it("orders the page as the board does and keeps New group in the Files by group heading", async () => {
    document.documentElement.dataset.style = "new";
    setup();
    const files = await screen.findByRole("heading", { name: "Files by group" });
    const heads = [...document.querySelectorAll(".collection-body h2")].map((h) => h.textContent);
    expect(heads.indexOf("Summary")).toBeGreaterThanOrEqual(0);
    expect(heads.indexOf("Summary")).toBeLessThan(heads.indexOf("Files by group"));
    expect(within(files.parentElement as HTMLElement).getByRole("button", { name: "New group" })).toBeInTheDocument();
    // not repeated in the header
    expect(within(document.querySelector(".collection-head") as HTMLElement).queryByRole("button", { name: "New group" })).toBeNull();
    expect(screen.getAllByRole("button", { name: "New group" })).toHaveLength(1);
  });

  it("shows the summary as text with Edit and Summarize, and Edit opens the field", async () => {
    document.documentElement.dataset.style = "new";
    const { user } = setup();
    const edit = await screen.findByRole("button", { name: "Edit" });
    expect(screen.getByText("No summary yet.")).toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: "Summary" })).not.toBeInTheDocument();
    await user.click(edit);
    expect(await screen.findByRole("textbox", { name: "Summary" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Done" })).toBeInTheDocument();
  });

  it("puts the selected file's buttons under its preview: Open, Show in folder, Note on this file, Remove", async () => {
    document.documentElement.dataset.style = "new";
    setup();
    const group = await screen.findByRole("group", { name: "This file" });
    for (const name of ["Open", "Show in folder", "Note on this file", "Remove from collection"]) {
      expect(within(group).getByRole("button", { name })).toBeInTheDocument();
    }
    // the rest of the file's actions follow as the icon row, no longer in the page header
    expect(document.querySelector(".collection-head .file-action-bar")).toBeNull();
    expect(document.querySelector(".collection-inspector .file-action-bar")).not.toBeNull();
    expect(screen.queryByRole("button", { name: /Remove quote.pdf from the collection/ })).not.toBeInTheDocument();
  });

  it("Add files opens a finder that puts the chosen file in the collection", async () => {
    document.documentElement.dataset.style = "new";
    const { user } = setup();
    await user.click(await screen.findByRole("button", { name: "Add files" }));
    const sheet = await screen.findByRole("dialog", { name: "Add files to Sauna" });
    expect(within(sheet).getByLabelText("Find a file")).toBeInTheDocument();
    await user.click(within(sheet).getByRole("button", { name: "Done" }));
    expect(screen.queryByRole("dialog", { name: "Add files to Sauna" })).not.toBeInTheDocument();
  });

  it("renders none of it in Classic", async () => {
    setup();
    await screen.findByRole("button", { name: "More actions" });
    expect(screen.queryByRole("button", { name: "File details" })).not.toBeInTheDocument();
    expect(document.querySelector(".hdr-wide")).toBeNull();
    expect(document.querySelector(".collection-head")).toBeNull();
    expect(document.querySelector(".inspector-foot")).toBeNull();
    expect(screen.queryByRole("heading", { name: "Files by group" })).not.toBeInTheDocument();
  });
});
