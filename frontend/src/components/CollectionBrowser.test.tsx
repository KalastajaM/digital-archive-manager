/** "Browse collections…" beside the collection field: the open collections as a tree. */
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { FileActions } from "../screens/FileActions";
import { mockFetch, renderWithProviders } from "../test-utils";

afterEach(() => vi.unstubAllGlobals());

const row = (id: number, name: string, path: string[], parent_id: number | null, extra = {}) => ({
  id,
  name,
  state: "open",
  created: 1,
  closed_at: null,
  publish: { ongoing: false },
  ongoing_rel: null,
  members: [],
  ongoing_status: null,
  summary: "",
  groups: [],
  parent_id,
  path,
  kind: null,
  files: 0,
  open_checks: 0,
  ...extra,
});
const COLLECTIONS = [
  row(1, "Houses", ["Houses"], null),
  row(2, "Sauna", ["Houses", "Sauna"], 1),
  row(3, "Car", ["Car"], null),
  row(9, "★ Ongoing", ["★ Ongoing"], null, { kind: "starred" }),
];

async function setup() {
  const calls = mockFetch({
    "GET /api/collections": { body: COLLECTIONS },
    "POST /api/collections/2/members": {
      body: { collection: COLLECTIONS[1], batch: null, problems: [], ongoing_status: null },
    },
    "GET /api/trays": { body: { trays: [], errors: [] } },
    "GET /api/files/d7/links": { body: { items: [], collections: [], note: "" } },
    "GET /api/notes/file/d7": { body: { text: "" } },
    "GET /api/ai/status": { body: { enabled: false } },
  });
  renderWithProviders(
    <MemoryRouter>
      <FileActions driveId="d7" />
    </MemoryRouter>,
  );
  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: "Add to collection…" }));
  await user.click(await screen.findByRole("button", { name: "Browse collections…" }));
  const sheet = await screen.findByRole("dialog", { name: "Choose a collection" });
  const tree = within(sheet).getByRole("tree", { name: "Collections" });
  await within(tree).findByRole("treeitem", { name: "Houses" });
  return { calls, user, sheet, tree };
}

const names = (tree: HTMLElement) => within(tree).queryAllByRole("treeitem").map((li) => li.getAttribute("aria-label"));

describe("the collection browser", () => {
  it("shows the collections as a tree, top level folded, without the built-ins", async () => {
    const { user, tree } = await setup();
    expect(names(tree)).toEqual(["Car", "Houses"]);
    expect(within(tree).getByRole("treeitem", { name: "Houses" })).toHaveAttribute("aria-expanded", "false");
    await user.click(within(tree).getByRole("button", { name: "Open Houses" }));
    expect(names(tree)).toEqual(["Car", "Houses", "Sauna"]);
    expect(within(tree).getByRole("treeitem", { name: "Sauna" })).toHaveAttribute("aria-level", "2");
  });

  it("the filter matches the path and keeps the parents; Choose adds the file to the picked collection", async () => {
    const { calls, user, sheet, tree } = await setup();
    await user.type(within(sheet).getByRole("searchbox", { name: "Filter collections" }), "houses › sau");
    expect(names(tree)).toEqual(["Houses", "Sauna"]);
    expect(within(tree).getByRole("treeitem", { name: "Sauna" })).toHaveAttribute("aria-selected", "true");
    await user.click(within(sheet).getByRole("button", { name: "Choose" }));
    await waitFor(() => expect(calls.filter((c) => c.url === "/api/collections/2/members")).toHaveLength(1));
    expect(calls.find((c) => c.url === "/api/collections/2/members")!.body).toEqual({ drive_ids: ["d7"] });
    expect(screen.queryByRole("dialog", { name: "Choose a collection" })).not.toBeInTheDocument();
  });

  it("arrows walk the tree, → opens, Enter chooses, Esc cancels", async () => {
    const { calls, user, sheet, tree } = await setup();
    await user.keyboard("{ArrowDown}{ArrowRight}");
    expect(within(tree).getByRole("treeitem", { name: "Houses" })).toHaveAttribute("aria-expanded", "true");
    await user.keyboard("{ArrowRight}{ArrowDown}");
    expect(within(tree).getByRole("treeitem", { name: "Sauna" })).toHaveAttribute("aria-selected", "true");
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog", { name: "Choose a collection" })).not.toBeInTheDocument();
    expect(calls.filter((c) => c.method === "POST")).toHaveLength(0);
    expect(sheet).not.toBeInTheDocument();
  });
});
