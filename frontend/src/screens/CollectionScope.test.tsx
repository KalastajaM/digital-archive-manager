/** A collection shown above its files in Browse (CollectionDetail's "scope" variant): the
 * header, then the details open (summary and Needs attention, note and checklist), foldable
 * to one line per collection; no member tree and no file panel (Browse has its own). */
import { cleanup, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Collection, MemberAttention } from "../api/client";
import { mockFetch, renderWithProviders } from "../test-utils";
import CollectionDetail from "./CollectionDetail";

const LEGAL: Collection = {
  id: 7,
  name: "Legal",
  state: "open",
  created: 1_760_000_000,
  closed_at: null,
  publish: { ongoing: false },
  ongoing_rel: null,
  members: [
    { drive_id: "f1", path: "40. House/will.pdf", is_dir: false, missing: false, quarantined: false, is_link: false, group_id: null, connected: true, marks: [] },
    { drive_id: "d1", path: "50. Legal/Deeds", is_dir: true, missing: false, quarantined: false, is_link: false, group_id: null, connected: true, marks: [] },
  ],
  ongoing_status: null,
  summary: "Wills and deeds for the family",
  groups: [],
  parent_id: null,
  path: ["Legal"],
  kind: null,
  position: 0,
};

const ATTENTION: MemberAttention[] = [{ drive_id: "f1", in_inbox: true, items: [] }];

function setup(c: Collection = LEGAL, onSelectFile = vi.fn()) {
  mockFetch({
    "GET /api/collections": { body: [{ ...c, files: 1, open_checks: 1 }] },
    [`GET /api/collections/${c.id}`]: { body: c },
    [`GET /api/collections/${c.id}/attention`]: { body: ATTENTION },
    [`GET /api/notes/collection/${c.id}`]: { body: { text: "Keep the originals" } },
    [`GET /api/checklist/collection/${c.id}`]: {
      body: [
        { id: 1, text: "Sign", done: true, position: 0 },
        { id: 2, text: "Notarise", done: false, position: 1 },
      ],
    },
  });
  const user = userEvent.setup();
  const view = renderWithProviders(
    <MemoryRouter>
      <CollectionDetail id={c.id} variant="scope" onSelectFile={onSelectFile} today="2026-10-30" />
    </MemoryRouter>,
  );
  return { user, onSelectFile, view };
}

beforeEach(() => {
  localStorage.clear();
  document.documentElement.dataset.style = "new";
});
afterEach(() => {
  cleanup();
  delete document.documentElement.dataset.style;
});

describe("a collection above its files (scope)", () => {
  it("shows the header and the details open, without the member tree or a file panel", async () => {
    setup();
    const summary = await screen.findByText("Wills and deeds for the family");
    const attention = screen.getByRole("region", { name: "Needs attention" });
    // layout C: the summary first, then Needs attention, both inside the details block
    expect(summary.compareDocumentPosition(attention) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(summary.closest(".collection-details")).toBe(attention.closest(".collection-details"));
    expect(screen.getByRole("button", { name: "Add files" })).toBeInTheDocument();
    expect(document.querySelector(".collection-state")).toHaveTextContent("Open");
    expect(screen.queryByRole("tree", { name: "Members" })).toBeNull();
    expect(screen.queryByRole("complementary", { name: "Selected file" })).toBeNull();
    expect(screen.queryByRole("button", { name: "File details" })).toBeNull();
  });

  it("Hide details folds the block to one line and remembers it per collection", async () => {
    const { user, view } = setup();
    await user.click(await screen.findByRole("button", { name: "Hide details" }));
    const line = document.querySelector(".collection-folded") as HTMLElement;
    expect(line).toHaveTextContent("Summary · Needs attention 1 · Checklist 1 of 2 · Note");
    expect(screen.queryByText("Wills and deeds for the family")).toBeNull();
    view.unmount();
    setup();
    expect(await screen.findByRole("button", { name: "Show details" })).toBeInTheDocument();
    await user.click(within(document.querySelector(".collection-folded") as HTMLElement).getByRole("button", { name: "Checklist 1 of 2" }));
    expect(await screen.findByText("Wills and deeds for the family")).toBeInTheDocument();
    cleanup();
    setup({ ...LEGAL, id: 8, name: "Car" });
    expect(await screen.findByRole("button", { name: "Hide details" })).toBeInTheDocument(); // another collection: open
  });

  it("a Needs attention entry selects the file in the list", async () => {
    const { user, onSelectFile } = setup();
    const strip = await screen.findByRole("region", { name: "Needs attention" });
    await user.click(within(strip).getByRole("button", { name: "will.pdf" }));
    expect(onSelectFile).toHaveBeenCalledWith("f1");
  });

  it("lists folder members as links that open the folder in Browse", async () => {
    setup();
    const folders = await screen.findByRole("navigation", { name: "Folders in this collection" });
    expect(within(folders).getByRole("link", { name: "Deeds" })).toHaveAttribute("href", "/browse?path=50.+Legal%2FDeeds");
  });

  it("Starred has no rename and no menu", async () => {
    setup({ ...LEGAL, id: 2, name: "★ Ongoing", kind: "starred" });
    await screen.findByText("Wills and deeds for the family");
    expect(screen.queryByRole("button", { name: "More actions" })).toBeNull();
    expect(screen.queryByRole("button", { name: /^Rename/ })).toBeNull();
  });

  it("a long name ends in an ellipsis with the full name on hover", async () => {
    const long = "The papers for the house sale and the move abroad in the spring of 2027";
    setup({ ...LEGAL, name: long, path: [long] });
    const name = await screen.findByRole("heading", { name: long });
    // the name is cut with an ellipsis; its hover text gives it in full
    expect(name.querySelector("[title]")?.getAttribute("title")).toContain(long);
  });
});
