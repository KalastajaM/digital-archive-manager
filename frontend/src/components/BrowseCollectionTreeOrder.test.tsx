/** Ordering collections in Browse's collection tree, as in the sidebar: drag a row with a
 * drop line (top third before, bottom third after, middle inside), a strip for the top
 * level while dragging, and Alt+arrows on a focused row. */
import { cleanup, createEvent, fireEvent as rtlFire, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { CollectionRow } from "../api/client";
import type { ScopeState } from "../browseScope";
import { setDragCollection } from "../dnd";
import { type Call, dataTransfer, mockFetch, renderWithProviders } from "../test-utils";
import { CollectionTree } from "./BrowseCollectionTree";

/** fireEvent with a pointer height: jsdom has no DragEvent, so ``clientY`` is set by hand. */
type Kind = "dragEnter" | "dragOver" | "drop";
const fire = (kind: Kind) => (el: Element, init: { dataTransfer: unknown; clientY?: number }) => {
  const ev = createEvent[kind](el, { dataTransfer: init.dataTransfer } as EventInit);
  Object.defineProperty(ev, "clientY", { value: init.clientY ?? 0 });
  return rtlFire(el, ev);
};
const fireEvent = { dragEnter: fire("dragEnter"), dragOver: fire("dragOver"), drop: fire("drop") };

const coll = (id: number, name: string, position: number, parent_id: number | null = null): CollectionRow => ({
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
  position,
  files: 0,
  open_checks: 0,
});
// Car, Attic, Boat, and Sofa inside Attic
const CAR = coll(1, "Car", 0);
const ATTIC = coll(2, "Attic", 1);
const BOAT = coll(3, "Boat", 2);
const SOFA = coll(4, "Sofa", 0, 2);
const LIST = [CAR, ATTIC, SOFA, BOAT];
const CHANGE = { collection: CAR, batch: null, problems: [], ongoing_status: null };
const NONE: ScopeState = { collections: [], tags: [], starred: false, important: false };
const moves = (calls: Call[]) => calls.filter((c) => c.method === "POST" && /\/move$/.test(c.url));
const parents = (calls: Call[], id: number) => calls.filter((c) => c.url === `/api/collections/${id}/parent`);

function setup() {
  const calls = mockFetch({
    "GET /api/collections": { body: LIST },
    "POST /api/collections/1/move": { body: CHANGE },
    "POST /api/collections/2/move": { body: CHANGE },
    "POST /api/collections/3/move": { body: CHANGE },
    "POST /api/collections/4/move": { body: CHANGE },
    "PATCH /api/collections/3/parent": { body: CHANGE },
    "PATCH /api/collections/4/parent": { body: CHANGE },
  });
  renderWithProviders(
    <MemoryRouter>
      <CollectionTree active={NONE} onPick={vi.fn()} />
    </MemoryRouter>,
  );
  return { calls, user: userEvent.setup() };
}

/** A collection's row, 40px high at the top of the window: clientY 2 is its top edge, 20 the middle, 38 the bottom. */
const rowOf = async (name: string) => {
  const row = (await screen.findByRole("treeitem", { name })).querySelector(".tree-row") as HTMLElement;
  row.getBoundingClientRect = () => ({ top: 0, left: 0, right: 100, bottom: 40, width: 100, height: 40, x: 0, y: 0, toJSON: () => ({}) });
  return row;
};
const itemOf = (name: string) => screen.getByRole("treeitem", { name });
function dragColl(id: number, label: string) {
  const dt = dataTransfer();
  setDragCollection({ dataTransfer: dt } as unknown as DragEvent, id, label);
  return dt;
}

afterEach(cleanup);

describe("CollectionTree order", () => {
  it("a row drags as its collection", async () => {
    setup();
    expect(await rowOf("Boat")).toHaveAttribute("draggable", "true");
  });

  it("the top third of a sibling shows a line and drops before it; the bottom third after it", async () => {
    const { calls } = setup();
    const car = await rowOf("Car");
    const dt = dragColl(3, "Boat");
    fireEvent.dragOver(car, { dataTransfer: dt, clientY: 10 });
    expect(car).toHaveAttribute("data-reorder", "before");
    fireEvent.drop(car, { dataTransfer: dt, clientY: 10 });
    await waitFor(() => expect(moves(calls)).toHaveLength(1));
    expect(moves(calls)[0]).toMatchObject({ url: "/api/collections/3/move", body: { before_id: 1 } });
    const boat = await rowOf("Boat");
    const back = dragColl(1, "Car");
    fireEvent.dragOver(boat, { dataTransfer: back, clientY: 30 });
    expect(boat).toHaveAttribute("data-reorder", "after");
  });

  it("the middle third highlights the row, and dropping there moves the collection inside", async () => {
    const { calls } = setup();
    const car = await rowOf("Car");
    const dt = dragColl(3, "Boat");
    fireEvent.dragEnter(car, { dataTransfer: dt, clientY: 20 });
    fireEvent.dragOver(car, { dataTransfer: dt, clientY: 20 });
    expect(car).toHaveAttribute("data-drop", "over");
    expect(car).not.toHaveAttribute("data-reorder");
    fireEvent.drop(car, { dataTransfer: dt, clientY: 20 });
    await waitFor(() => expect(parents(calls, 3)).toHaveLength(1));
    expect(parents(calls, 3)[0].body).toEqual({ parent_id: 1 });
    expect(moves(calls)).toHaveLength(0);
  });

  it("a row is not its own drop place", async () => {
    setup();
    const car = await rowOf("Car");
    fireEvent.dragOver(car, { dataTransfer: dragColl(1, "Car"), clientY: 10 });
    expect(car).not.toHaveAttribute("data-reorder");
  });

  it("while a collection is dragged a strip takes it to the top level", async () => {
    const { calls } = setup();
    const sofa = await rowOf("Sofa");
    expect(screen.queryByText(/top level, last/)).toBeNull();
    const dt = dragColl(4, "Sofa");
    rtlFire(sofa, createEvent.dragStart(sofa, { dataTransfer: dt } as EventInit));
    const strip = await screen.findByText(/top level, last/);
    fireEvent.dragEnter(strip, { dataTransfer: dt });
    fireEvent.drop(strip, { dataTransfer: dt });
    await waitFor(() => expect(parents(calls, 4)).toHaveLength(1));
    expect(parents(calls, 4)[0].body).toEqual({ parent_id: null });
  });

  it("after Alt+ArrowUp the focus stays on the tree's row, not the sidebar's for the same collection", async () => {
    mockFetch({ "GET /api/collections": { body: LIST }, "POST /api/collections/2/move": { body: CHANGE } });
    renderWithProviders(
      <MemoryRouter>
        <a href="#attic" data-collection-id="2">
          Attic in the sidebar
        </a>
        <CollectionTree active={NONE} onPick={vi.fn()} />
      </MemoryRouter>,
    );
    const user = userEvent.setup();
    (await screen.findByRole("treeitem", { name: "Attic" })).focus();
    await user.keyboard("{Alt>}{ArrowUp}{/Alt}");
    await new Promise((done) => setTimeout(done, 80));
    expect(document.activeElement).toBe(screen.getByRole("treeitem", { name: "Attic" }));
  });

  it("Alt+ArrowUp on a focused row moves it up; the first one cannot", async () => {
    const { calls, user } = setup();
    await screen.findByRole("treeitem", { name: "Attic" });
    itemOf("Attic").focus();
    await user.keyboard("{Alt>}{ArrowUp}{/Alt}");
    await waitFor(() => expect(moves(calls)).toHaveLength(1));
    expect(moves(calls)[0]).toMatchObject({ url: "/api/collections/2/move", body: { before_id: 1 } });
    itemOf("Car").focus();
    await user.keyboard("{Alt>}{ArrowUp}{/Alt}");
    expect(moves(calls)).toHaveLength(1);
  });
});
