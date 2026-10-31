/** Browse's trees open a row's right-click menu from the keyboard too (Shift+F10 on the
 * focused row), and a nested row's menu is its own, not its parent's. */
import { cleanup, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it } from "vitest";
import type { ScopeState } from "../browseScope";
import { useContextMenuKeys } from "../contextMenus";
import { mockFetch, renderWithProviders } from "../test-utils";
import { CollectionTree } from "./BrowseCollectionTree";
import { TagTree } from "./BrowseTagTree";

const NONE: ScopeState = { collections: [], tags: [], starred: false, important: false };
const coll = (id: number, name: string, parent_id: number | null = null) => ({
  id,
  name,
  state: "open",
  parent_id,
  path: [name],
  kind: null,
  position: id,
  members: [],
  files: 0,
  open_checks: 0,
  groups: [],
  ongoing_status: null,
});

function Keys() {
  useContextMenuKeys();
  return null;
}

afterEach(cleanup);

describe("Browse's trees from the keyboard", () => {
  it("Shift+F10 on a collection opens its menu; a child's right-click is the child's", async () => {
    mockFetch({ "GET /api/collections": { body: [coll(1, "Car"), coll(2, "Tyres", 1)] } });
    renderWithProviders(
      <MemoryRouter>
        <Keys />
        <CollectionTree active={NONE} onPick={() => {}} />
      </MemoryRouter>,
    );
    const user = userEvent.setup();
    (await screen.findByRole("treeitem", { name: "Car" })).focus();
    await user.keyboard("{Shift>}{F10}{/Shift}");
    expect(await screen.findByRole("menu", { name: "Order of Car" })).toBeInTheDocument();
    await user.keyboard("{Escape}");
    await user.pointer({ keys: "[MouseRight]", target: screen.getByText("Tyres") });
    expect(await screen.findByRole("menu", { name: "Order of Tyres" })).toBeInTheDocument();
  });

  it("Shift+F10 on a tag opens its menu, with rules between its groups of entries", async () => {
    mockFetch({
      "GET /api/tags/all": { body: { tags: [{ name: "medical", files: 2, pinned: false, group_id: 1 }], groups: [{ id: 1, name: "Health" }] } },
    });
    renderWithProviders(<><Keys /><TagTree active={NONE} onPick={() => {}} /></>);
    const user = userEvent.setup();
    (await screen.findByRole("treeitem", { name: "medical, 2 files" })).focus();
    await user.keyboard("{Shift>}{F10}{/Shift}");
    const menu = await screen.findByRole("menu", { name: "Actions for medical" });
    expect(menu.querySelectorAll('[role="separator"]').length).toBeGreaterThan(0);
  });
});
