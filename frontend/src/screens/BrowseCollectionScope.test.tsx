/** A search scoped to one collection shows that collection (its header and details) above
 * the files, and a file that comes from a child collection says which. */
import { cleanup, screen, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import type { CollectionRow, Member, SearchHit } from "../api/client";
import { mockFetch, renderWithProviders } from "../test-utils";
import Browse from "./Browse";

const member = (drive_id: string): Member => ({ drive_id, path: `x/${drive_id}.pdf`, is_dir: false, missing: false, quarantined: false, is_link: false, group_id: null, connected: true, marks: [] });
const coll = (id: number, name: string, parent_id: number | null = null, members: string[] = []): CollectionRow => ({
  id,
  name,
  state: "open",
  created: 1,
  closed_at: null,
  publish: { ongoing: false },
  ongoing_rel: null,
  members: members.map(member),
  ongoing_status: null,
  summary: name === "Legal" ? "Wills and deeds" : "",
  groups: [],
  parent_id,
  path: [name],
  kind: null,
  position: id,
  files: members.length,
  open_checks: 0,
});
const hit = (id: string, name: string): SearchHit => ({ drive_id: id, path: `50. Legal/${name}`, name, snippet: name, rank: -1, size: 1, mtime: 1, connected: true, marks: [], open_items: [] });

const LEGAL = coll(1, "Legal", null, ["a"]);
const ALL = [LEGAL, coll(2, "Michiel", 1, ["b"]), coll(3, "Car")];

function setup(url: string) {
  mockFetch({
    "GET /api/browse": { body: [] },
    "GET /api/status": { body: { special_folders: { inbox: "##. Organize", ongoing: "##. Ongoing", important: "##. Important", quarantine: "##. To Delete" } } },
    "GET /api/search": { body: [hit("a", "will.pdf"), hit("b", "deed.pdf")] },
    "GET /api/activity": { body: [] },
    "GET /api/collections": { body: ALL },
    "GET /api/collections/1": { body: LEGAL },
    "GET /api/collections/1/attention": { body: [] },
    "GET /api/notes/collection/1": { body: { text: "" } },
    "GET /api/checklist/collection/1": { body: [] },
    "GET /api/tags/all": { body: { tags: [], groups: [] } },
  });
  renderWithProviders(
    <MemoryRouter initialEntries={[url]}>
      <Routes>
        <Route path="/browse" element={<Browse />} />
      </Routes>
    </MemoryRouter>,
  );
}

const pane = () => screen.getByRole("region", { name: "Browse" });

beforeEach(() => {
  localStorage.clear();
  document.documentElement.dataset.style = "new";
});
afterEach(() => {
  cleanup();
  delete document.documentElement.dataset.style;
});

describe("a collection above its files in Browse", () => {
  it("shows the collection's details above the chips, and which child a file comes from", async () => {
    setup("/browse?tree=collections&q=collection:Legal");
    const summary = await within(pane()).findByText("Wills and deeds");
    const chips = within(pane()).getByRole("list", { name: "Search filters" });
    expect(summary.compareDocumentPosition(chips) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    const deed = (await within(pane()).findByText("deed.pdf")).closest("li") as HTMLElement;
    expect(within(deed).getByText("Michiel ›")).toHaveClass("entry-via");
    const will = within(pane()).getByText("will.pdf").closest("li") as HTMLElement;
    expect(will.querySelector(".entry-via")).toBeNull(); // in Legal itself
  });

  it("says so when the collection is not there any more", async () => {
    setup("/browse?q=collection:Nope");
    expect(await within(pane()).findByText(/No collection named Nope/)).toBeInTheDocument();
  });

  it("shows nothing above a search of two collections", async () => {
    setup("/browse?q=collection:Legal%20collection:Car");
    await within(pane()).findByText("deed.pdf");
    expect(within(pane()).queryByText("Wills and deeds")).toBeNull();
    expect(within(pane()).queryByText("Michiel ›")).toBeNull();
  });
});
