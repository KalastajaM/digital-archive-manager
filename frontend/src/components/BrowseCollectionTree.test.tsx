/** Browse's collection tree: Important and Starred first, then the open collections as
 * they nest; a click picks one, the picked one is current, and a long name stays in its row. */
import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { CollectionRow } from "../api/client";
import type { ScopeState } from "../browseScope";
import css from "../styles-new.css?raw";
import { setDragFiles, setDragSource } from "../dnd";
import { dataTransfer, deferred, mockFetch, renderWithProviders } from "../test-utils";
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

function setup(collections: CollectionRow[], active: ScopeState = NONE, routes: Parameters<typeof mockFetch>[0] = {}) {
  const calls = mockFetch({ "GET /api/collections": { body: collections }, ...routes });
  const onPick = vi.fn();
  renderWithProviders(
    <MemoryRouter>
      <CollectionTree active={active} onPick={onPick} />
    </MemoryRouter>,
  );
  return { calls, onPick, user: userEvent.setup() };
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

  it("a row shows its files, its open checks and an Ongoing problem, with the counts in its tooltip", async () => {
    const car = { ...coll(3, "Car"), files: 12, open_checks: 2, ongoing_status: "The name is taken in ##. Ongoing: using Car_2" };
    setup([car, coll(4, "Tyres", 3)]);
    const row = (await screen.findByRole("treeitem", { name: "Car" })).querySelector(".tree-row") as HTMLElement;
    expect(within(row).getByText("12")).toHaveClass("tree-count");
    expect(within(row).getByTitle("2 open checks")).toBeInTheDocument();
    expect(within(row).getByTitle("The name is taken in ##. Ongoing: using Car_2")).toBeInTheDocument();
    expect(row.querySelector(".tree-name")).toHaveAttribute("title", "Car\n12 files · 1 collection · 2 open checks");
    expect(screen.getByRole("treeitem", { name: "Car" })).toHaveAccessibleDescription(
      "12 files · 1 collection · 2 open checks. The name is taken in ##. Ongoing: using Car_2",
    );
    // an empty one shows no count
    const tyres = screen.getByRole("treeitem", { name: "Tyres" }).querySelector(".tree-row") as HTMLElement;
    expect(tyres.querySelector(".tree-count")).toBeNull();
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
    expect(name).toHaveAttribute("title", `${long}\n0 files`); // the full name, then its counts
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

  it("a file dragged from a collection onto a sibling is moved there", async () => {
    const together = coll(3, "Together", 1);
    const { calls } = setup([coll(1, "Legal"), coll(2, "Michiel", 1), together], NONE, {
      "POST /api/collections/2/members/move": { body: { collection: together, batch: null, problems: [], ongoing_status: null } },
    });
    const row = (await screen.findByText("Together")).closest(".tree-row") as HTMLElement;
    const dt = dataTransfer();
    setDragFiles({ dataTransfer: dt } as unknown as DragEvent, ["f1"], "a.pdf");
    setDragSource({ dataTransfer: dt } as unknown as DragEvent, 2);
    fireEvent.dragEnter(row, { dataTransfer: dt });
    fireEvent.drop(row, { dataTransfer: dt });
    await waitFor(() => expect(calls.filter((c) => c.method === "POST" && c.url === "/api/collections/2/members/move")).toHaveLength(1));
  });

  it("a collection's right-click menu opens it, makes one inside it, and moves it", async () => {
    const { onPick, user } = setup([coll(1, "Legal"), coll(3, "Car")]);
    const row = (await screen.findByText("Car")).closest(".tree-row") as HTMLElement;
    await user.pointer({ keys: "[MouseRight]", target: row });
    const menu = await screen.findByRole("menu");
    expect(within(menu).getAllByRole("menuitem").map((m) => m.textContent)).toEqual(["Open", "New collection inside…", "Merge into…", "Delete…", "Move up", "Move down"]);
    await user.click(within(menu).getByRole("menuitem", { name: "New collection inside…" }));
    expect(await screen.findByRole("dialog", { name: /inside Car/ })).toBeInTheDocument();
    await user.keyboard("{Escape}");
    await user.pointer({ keys: "[MouseRight]", target: row });
    await user.click(within(await screen.findByRole("menu")).getByRole("menuitem", { name: "Open" }));
    expect(onPick).toHaveBeenCalledWith({ kind: "collection", name: "Car" }, false);
  });

  it("New collection makes one at the top", async () => {
    const { user } = setup([coll(1, "Legal")]);
    await user.click(await screen.findByRole("button", { name: "New collection" }));
    expect(await screen.findByRole("dialog", { name: "New collection" })).toBeInTheDocument();
  });

  it("Show closed adds the closed collections, greyed", async () => {
    mockFetch({
      "GET /api/collections": (call) => ({
        body: call.url.includes("state=all") ? [coll(1, "Legal"), { ...coll(5, "Old"), state: "closed" }] : [coll(1, "Legal")],
      }),
    });
    const user = userEvent.setup();
    renderWithProviders(
    <MemoryRouter>
      <CollectionTree active={NONE} onPick={vi.fn()} />
    </MemoryRouter>,
  );
    await screen.findByText("Legal");
    expect(screen.queryByText("Old")).toBeNull();
    const toggle = screen.getByRole("button", { name: "Show closed" });
    expect(toggle).toHaveAttribute("aria-pressed", "false");
    await user.click(toggle);
    const old = (await screen.findByText("Old")).closest('[role="treeitem"]') as HTMLElement;
    expect(old.querySelector(".tree-row")).toHaveClass("tree-closed");
  });

  it("lists the collections by position, not by name", async () => {
    setup([{ ...coll(1, "Zed"), position: 0 }, { ...coll(2, "Alpha"), position: 1 }]);
    await screen.findByText("Alpha");
    expect(names()).toEqual(["Important", "Starred", "Zed", "Alpha"]);
  });

  it("the right-click menu moves a collection down", async () => {
    const { calls, user } = setup([coll(1, "Car"), coll(2, "Attic")], NONE, {
      "POST /api/collections/1/move": { body: { collection: coll(1, "Car"), batch: null, problems: [], ongoing_status: null } },
    });
    const row = (await screen.findByText("Car")).closest(".tree-row") as HTMLElement;
    await user.pointer({ keys: "[MouseRight]", target: row });
    await user.click(await screen.findByRole("menuitem", { name: "Move down" }));
    await waitFor(() => expect(calls.filter((c) => c.method === "POST" && c.url === "/api/collections/1/move")).toHaveLength(1));
    expect(calls.find((c) => c.url === "/api/collections/1/move")!.body).toEqual({ after_id: 2 });
  });

  it("startClosed opens with the closed collections shown", async () => {
    mockFetch({
      "GET /api/collections": (call) => ({ body: call.url.includes("state=all") ? [coll(1, "Legal"), { ...coll(5, "Old"), state: "closed" }] : [coll(1, "Legal")] }),
    });
    renderWithProviders(
    <MemoryRouter>
      <CollectionTree active={NONE} onPick={vi.fn()} startClosed />
    </MemoryRouter>,
  );
    expect(await screen.findByText("Old")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Show closed" })).toHaveAttribute("aria-pressed", "true");
  });
});

describe("CollectionTree's New collection", () => {
  const created = { ...coll(7, "Sauna"), id: 7 };

  it("startNew opens the New collection sheet at once (the sidebar's +)", async () => {
    mockFetch({ "GET /api/collections": { body: [] } });
    renderWithProviders(
    <MemoryRouter>
      <CollectionTree active={NONE} onPick={vi.fn()} startNew />
    </MemoryRouter>,
  );
    const dialog = await screen.findByRole("dialog", { name: "New collection" });
    expect(within(dialog).getByRole("textbox", { name: "Name" })).toHaveValue("");
  });

  it("creates it from the sheet and picks it", async () => {
    const { calls, onPick, user } = setup([], NONE, { "POST /api/collections": { body: created } });
    await user.click(await screen.findByRole("button", { name: "New collection" }));
    const dialog = await screen.findByRole("dialog", { name: "New collection" });
    await user.type(within(dialog).getByRole("textbox", { name: "Name" }), "  Sauna {Enter}");
    await waitFor(() => expect(onPick).toHaveBeenCalledWith({ kind: "collection", name: "Sauna" }, false));
    expect(calls.filter((c) => c.method === "POST" && c.url === "/api/collections").map((c) => c.body)).toEqual([{ name: "Sauna" }]);
  });

  it("a double Create makes one collection", async () => {
    const pending = deferred<{ body: unknown }>();
    const { calls, user } = setup([], NONE, { "POST /api/collections": () => pending.promise });
    await user.click(await screen.findByRole("button", { name: "New collection" }));
    const dialog = await screen.findByRole("dialog", { name: "New collection" });
    await user.type(within(dialog).getByRole("textbox", { name: "Name" }), "Car");
    const create = within(dialog).getByRole("button", { name: "Create" });
    act(() => {
      create.click();
      create.click();
    });
    await act(async () => pending.resolve({ body: created }));
    expect(calls.filter((c) => c.method === "POST" && c.url === "/api/collections")).toHaveLength(1);
  });

  it("shows a refused name in the sheet", async () => {
    const { user } = setup([], NONE, { "POST /api/collections": { status: 400, body: { error: "a collection named ‮Sauna exists" } } });
    await user.click(await screen.findByRole("button", { name: "New collection" }));
    const dialog = await screen.findByRole("dialog", { name: "New collection" });
    await user.type(within(dialog).getByRole("textbox", { name: "Name" }), "sauna{Enter}");
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("⟨U+202E⟩Sauna exists");
  });
});
