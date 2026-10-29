/** Browse's collection tree: Important and Starred first, then the open collections as
 * they nest; a click picks one, the picked one is current, and a long name stays in its row. */
import { cleanup, fireEvent, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { CollectionRow } from "../api/client";
import type { ScopeState } from "../browseScope";
import css from "../styles-new.css?raw";
import { mockFetch, renderWithProviders } from "../test-utils";
import { CollectionTree } from "./BrowseCollectionTree";

const coll = (id: number, name: string, parent_id: number | null = null): CollectionRow => ({
  id,
  name,
  state: "open",
  created: 1,
  closed_at: null,
  publish: { ongoing: true },
  ongoing_rel: null,
  members: [],
  ongoing_status: null,
  summary: "",
  groups: [],
  parent_id,
  path: [name],
  kind: null,
  position: id,
  files: 0,
  open_checks: 0,
});

const NONE: ScopeState = { collections: [], tags: [], starred: false, important: false };

function setup(collections: CollectionRow[], active: ScopeState = NONE) {
  mockFetch({ "GET /api/collections": { body: collections } });
  const onPick = vi.fn();
  renderWithProviders(<CollectionTree active={active} onPick={onPick} />);
  return { onPick, user: userEvent.setup() };
}

const names = () => screen.getAllByRole("treeitem").map((li) => li.querySelector(".tree-name")?.textContent);

afterEach(cleanup);

describe("CollectionTree", () => {
  it("lists Important and Starred first, then the open collections nested", async () => {
    setup([coll(1, "Legal"), coll(2, "Michiel", 1), coll(3, "Car")]);
    await screen.findByText("Michiel");
    expect(names()).toEqual(["Important", "Starred", "Legal", "Michiel", "Car"]);
    const level = (name: string) => Number(screen.getByText(name).closest('[role="treeitem"]')?.getAttribute("aria-level"));
    expect(level("Michiel")).toBe(level("Legal") + 1);
  });

  it("a click picks, and the picked row is current", async () => {
    const { onPick, user } = setup([coll(3, "Car")], { ...NONE, collections: ["Car"] });
    await user.click(await screen.findByText("Car"));
    expect(onPick).toHaveBeenCalledWith({ kind: "collection", name: "Car" }, false);
    expect(screen.getByText("Car").closest('[role="treeitem"]')).toHaveAttribute("aria-current", "true");
    await user.click(screen.getByText("Starred"));
    expect(onPick).toHaveBeenCalledWith({ kind: "starred" }, false);
  });

  it("a child of a closed collection shows at the top", async () => {
    setup([coll(4, "Orphan", 99)]);
    const row = (await screen.findByText("Orphan")).closest('[role="treeitem"]');
    expect(row).toHaveAttribute("aria-level", "1");
  });

  it("a long name ends in an ellipsis with the full name on hover", async () => {
    const long = "A very long collection name ".repeat(5).trim();
    setup([coll(5, long)]);
    const name = await screen.findByText(long);
    expect(name).toHaveClass("tree-name");
    expect(name).toHaveAttribute("title", long);
    expect(css).toMatch(/\.tree-name\s*{[^}]*text-overflow:\s*ellipsis/);
  });

  it("no open collections says so", async () => {
    setup([]);
    expect(await screen.findByText("No open collections")).toBeInTheDocument();
    expect(within(screen.getByRole("navigation", { name: "Collections" })).getByText("Important")).toBeInTheDocument();
  });

  it("stays in the Tab order when the focused collection is folded away", async () => {
    const { user } = setup([coll(1, "Legal"), coll(2, "Michiel", 1)]);
    await user.click(await screen.findByText("Michiel"));
    const legal = screen.getByText("Legal").closest('[role="treeitem"]') as HTMLElement;
    fireEvent.click(legal.querySelector(".tree-chevron") as HTMLElement); // a click that leaves the focus where it was
    expect(screen.queryByText("Michiel")).not.toBeInTheDocument();
    expect(screen.getAllByRole("treeitem").filter((li) => li.tabIndex === 0)).toHaveLength(1);
  });
});

