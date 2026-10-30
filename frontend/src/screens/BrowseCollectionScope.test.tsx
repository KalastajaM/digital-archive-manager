/** A search scoped to one collection shows that collection (its header and details) above
 * the files, and a file that comes from a child collection says which. */
import { cleanup, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import type { CollectionRow, Member, SearchHit } from "../api/client";
import { type Call, deferred, mockFetch, renderWithProviders } from "../test-utils";
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

function Where() {
  const loc = useLocation();
  return <p data-testid="where">{loc.pathname + loc.search}</p>;
}

function setup(url: string, extra: Parameters<typeof mockFetch>[0] = {}) {
  const calls = mockFetch({
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
    ...extra,
  });
  renderWithProviders(
    <MemoryRouter initialEntries={[url]}>
      <Routes>
        <Route
          path="/browse"
          element={
            <>
              <Browse />
              <Where />
            </>
          }
        />
      </Routes>
    </MemoryRouter>,
  );
  return calls;
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

  it("the keys act once, on Browse's file: the collection's own keys stay off", async () => {
    const calls = setup("/browse?tree=collections&q=collection:Legal");
    const user = userEvent.setup();
    await user.click(await within(pane()).findByText("deed.pdf"));
    (document.activeElement as HTMLElement | null)?.blur();
    await user.keyboard("{Meta>}{Backspace}{/Meta}");
    await user.keyboard(" ");
    await waitFor(() => expect(calls.some((c: Call) => c.url.startsWith("/api/quarantine"))).toBe(true));
    const trashed = calls.filter((c: Call) => c.url.startsWith("/api/quarantine")).map((c) => (c.body as { drive_ids: string[] }).drive_ids);
    expect(trashed.every((ids) => !ids.includes("a"))).toBe(true); // a.pdf: the collection's first file
    expect(screen.queryByRole("dialog", { name: /will\.pdf/ })).toBeNull();
  });

  it("a rename in the block keeps the collection on screen: the address follows the new name", async () => {
    let name = "Legal";
    setup("/browse?tree=collections&q=collection:Legal", {
      "GET /api/collections": () => ({ body: ALL.map((c) => (c.id === 1 ? { ...c, name, path: [name] } : c)) }),
      "GET /api/collections/1": () => ({ body: { ...LEGAL, name, path: [name] } }),
      "POST /api/collections/1/rename/preview": { body: [] },
      "PATCH /api/collections/1": (call) => {
        name = (call.body as { name: string }).name;
        return { body: { collection: { ...LEGAL, name, path: [name] }, batch: null, problems: [], ongoing_status: null } };
      },
    });
    const user = userEvent.setup();
    await user.click(await within(pane()).findByRole("button", { name: "Rename Legal" }));
    const input = within(pane()).getByRole("textbox", { name: "Collection name" });
    await user.clear(input);
    await user.type(input, "Family law{Enter}");
    await waitFor(() => expect(screen.getByTestId("where").textContent).toContain("collection%3A%22Family+law%22"));
    expect(await within(pane()).findByText("Wills and deeds")).toBeInTheDocument();
    expect(within(pane()).queryByText(/No collection named/)).toBeNull();
  });

  it("never says the collection is missing while the collections are still loading", async () => {
    const list = deferred<{ body: unknown }>();
    setup("/browse?tree=collections&q=collection:Legal", { "GET /api/collections": () => list.promise });
    await within(pane()).findByText("deed.pdf");
    expect(within(pane()).queryByText(/No collection named/)).toBeNull();
    list.resolve({ body: ALL });
    expect(await within(pane()).findByText("Wills and deeds")).toBeInTheDocument();
  });

  it("puts the collection's name and its actions in the pane's bar, instead of the folder path", async () => {
    setup("/browse?tree=collections&q=collection:Legal");
    await within(pane()).findByText("Wills and deeds");
    const bar = pane().querySelector(".pane-bar") as HTMLElement;
    expect(await within(bar).findByRole("button", { name: "Rename Legal" })).toBeInTheDocument();
    expect(within(bar).getByRole("button", { name: "Hide details" })).toBeInTheDocument();
    expect(within(bar).queryByRole("navigation", { name: /path|Breadcrumb|Folder/i })).toBeNull();
    expect(within(bar).queryByText("Archive")).toBeNull();
  });
});

