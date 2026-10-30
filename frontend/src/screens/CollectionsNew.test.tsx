/** A collection in the New look, laid out as drawn: the header (parent line, name, state pill,
 * counts, buttons), the sections in order (Summary, Needs attention, Files by group, Notes and
 * Checklist), the side panel with its buttons under the preview, the "File details" button
 * that opens the panel over the list when the page is narrow, and Show folder and Export in
 * the ... menu. Classic renders none of it. */
import { cleanup, screen, waitFor, within } from "@testing-library/react";
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

function setup(c: Collection = SAUNA) {
  const calls = mockFetch({
    "PATCH /api/collections/7/summary": { body: { collection: { ...c, summary: "Sauna build, phase 2" }, batch: null, problems: [], ongoing_status: null } },
    "GET /api/collections": { body: [{ ...c, files: 1, open_checks: 0 }] },
    "GET /api/collections/7": { body: c },
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
  return { user, calls };
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

  it("orders the page as the board does; an ordinary collection lists its Files, with no groups", async () => {
    document.documentElement.dataset.style = "new";
    setup();
    await screen.findByRole("heading", { name: "Files" });
    // the summary is the file panel's summary box, above the files
    const body = document.querySelector(".collection-body") as HTMLElement;
    const summary = within(body).getByRole("heading", { name: "Summary" });
    expect(summary.closest(".summary-box")).not.toBeNull();
    expect(summary.compareDocumentPosition(within(body).getByRole("heading", { name: "Files" })) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    // only Important has groups: other collections nest instead
    expect(screen.queryByRole("button", { name: "New group" })).toBeNull();
  });

  it("keeps New group in Important's Files by group heading, once", async () => {
    document.documentElement.dataset.style = "new";
    setup({ ...SAUNA, name: "Important", kind: "important" });
    const files = await screen.findByRole("heading", { name: "Files by group" });
    expect(within(files.parentElement as HTMLElement).getByRole("button", { name: "New group" })).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "New group" })).toHaveLength(1);
  });

  it("edits the summary in place: a click on it opens the field, leaving it saves, Esc puts it back", async () => {
    document.documentElement.dataset.style = "new";
    const { user, calls } = setup();
    const empty = await screen.findByRole("button", { name: "What is this collection about? Where does it stand?" });
    expect(screen.queryByRole("button", { name: "Edit" })).toBeNull();
    expect(screen.queryByRole("textbox", { name: "Summary" })).toBeNull();
    await user.click(empty);
    const field = await screen.findByRole("textbox", { name: "Summary" });
    await user.type(field, "Sauna build, phase 2");
    await user.tab();
    await waitFor(() => expect(calls.some((c) => c.method === "PATCH")).toBe(true));
    expect(calls.find((c) => c.method === "PATCH")?.body).toEqual({ summary: "Sauna build, phase 2" });
    const text = await screen.findByRole("button", { name: "Sauna build, phase 2" });
    await user.click(text);
    await user.type(await screen.findByRole("textbox", { name: "Summary" }), " more");
    await user.keyboard("{Escape}");
    expect(await screen.findByRole("button", { name: "Sauna build, phase 2" })).toBeInTheDocument();
    expect(calls.filter((c) => c.method === "PATCH")).toHaveLength(1);
  });

  it("shows the selected file in the one file panel: the icon row, then Group", async () => {
    document.documentElement.dataset.style = "new";
    setup();
    const panel = await screen.findByRole("complementary", { name: "Selected file" });
    const look = await within(panel).findByRole("group", { name: "Look at it" });
    for (const name of ["Open", "Show in folder", "Relatives", "Ask AI"]) {
      expect(within(look).getByRole("button", { name })).toBeInTheDocument();
    }
    const filing = within(panel).getByRole("group", { name: "File it" });
    for (const name of ["From…", "For…", "Put in tray", "Star", "Mark Important", "Back to inbox", "Move to To Delete"]) {
      expect(within(filing).getByRole("button", { name })).toBeInTheDocument();
    }
    // Remove from collection is an icon of the second row (a membership action, undone from its toast)
    expect(within(filing).getByRole("button", { name: /Remove quote.pdf from the collection/ })).toBeInTheDocument();
    // Show in folder is an icon of the row; no text links repeat it or the note
    expect(within(panel).getAllByRole("button", { name: "Show in folder" })).toHaveLength(1);
    expect(within(panel).queryByRole("button", { name: "Note on this file" })).toBeNull();
    // the blocks come in the skeleton's order
    const blocks = [...panel.querySelectorAll("[data-block]")].map((b) => (b as HTMLElement).dataset.block);
    const order = ["header", "actions", "tags", "collections", "group", "summary", "relatives", "preview", "notes"];
    expect(blocks.filter((b) => order.includes(b!))).toEqual(order.filter((b) => blocks.includes(b)));
    // no longer in the page's header or a foot under the preview
    expect(document.querySelector(".collection-head .file-action-bar")).toBeNull();
    expect(document.querySelector(".inspector-foot")).toBeNull();
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
