/** Changing the order of collections: drag with a drop line (sidebar and collections page),
 * Alt+arrows and the context menu, Starred and Important pinned, files still dropped on a
 * sidebar collection. */
import { createEvent, fireEvent as rtlFire, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { CollectionRow } from "../api/client";
import { setDragCollection, setDragFiles } from "../dnd";
import Collections from "../screens/Collections";
import { type Call, dataTransfer, mockFetch, renderWithProviders } from "../test-utils";
import { Sidebar } from "./ui/Sidebar";

afterEach(() => vi.unstubAllGlobals());

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
// the API lists them in the owner's order: Car, Attic, Boat, and Sofa inside Attic
const CAR = coll(1, "Car", 0);
const ATTIC = coll(2, "Attic", 1);
const BOAT = coll(3, "Boat", 2);
const LIST = [CAR, ATTIC, BOAT];

const CHANGE = { collection: CAR, batch: null, problems: [], ongoing_status: null };
const moves = (calls: Call[]) => calls.filter((c) => c.method === "POST" && /\/move$/.test(c.url));

const BASE = {
  "GET /api/status": { body: { inbox_count: 0 } },
  "GET /api/today": { body: { attention: [], overview: { inbox: 0, trays: [], collections: [] } } },
  "GET /api/trays": { body: { trays: [], errors: [] } },
  "GET /api/marks/collection/starred": { body: { id: 90, kind: "starred", members: [], groups: [] } },
  "GET /api/marks/collection/important": { body: { id: 91, kind: "important", members: [], groups: [] } },
  "POST /api/collections/1/move": { body: CHANGE },
  "POST /api/collections/2/move": { body: CHANGE },
  "POST /api/collections/3/move": { body: CHANGE },
  "POST /api/collections/1/members": { body: { ...CHANGE, collection: { ...CAR, members: [] } } },
};

function sidebar(list = LIST) {
  const calls = mockFetch({ ...BASE, "GET /api/collections": { body: list } });
  renderWithProviders(
    <MemoryRouter initialEntries={["/browse"]}>
      <Sidebar />
    </MemoryRouter>,
  );
  return { calls, user: userEvent.setup() };
}

function page(list = LIST) {
  const calls = mockFetch({ ...BASE, "GET /api/collections": { body: list } });
  renderWithProviders(
    <MemoryRouter initialEntries={["/collections"]}>
      <Routes>
        <Route path="/collections/:id?" element={<Collections today="2026-10-19" />} />
      </Routes>
    </MemoryRouter>,
  );
  return { calls, user: userEvent.setup() };
}

/** A row 40px high at the top of the window: clientY 2 is its top edge, 20 the middle, 38 the bottom. */
function sized<T extends HTMLElement>(el: T): T {
  el.getBoundingClientRect = () => ({ top: 0, left: 0, right: 100, bottom: 40, width: 100, height: 40, x: 0, y: 0, toJSON: () => ({}) });
  return el;
}
function dragColl(id: number, label: string) {
  const dt = dataTransfer();
  setDragCollection({ dataTransfer: dt } as unknown as DragEvent, id, label);
  return dt;
}
const nav = () => screen.getByRole("navigation", { name: "Main" });
const sideNames = () => within(nav()).getAllByRole("link").map((a) => a.getAttribute("aria-label"));

describe("sidebar order", () => {
  it("lists Important and Starred first, then the collections in the API's order", async () => {
    sidebar();
    await within(nav()).findByRole("link", { name: "Car" });
    const names = sideNames();
    const at = (n: string) => names.indexOf(n);
    expect(at("Important")).toBeLessThan(at("Starred"));
    expect(at("Starred")).toBeLessThan(at("Car"));
    expect([at("Car"), at("Attic"), at("Boat")]).toEqual([...[at("Car"), at("Attic"), at("Boat")]].sort((a, b) => a - b));
  });

  it("orders siblings by position, not by name", async () => {
    sidebar([coll(1, "Zed", 0), coll(2, "Alpha", 1)]);
    await within(nav()).findByRole("link", { name: "Zed" });
    const names = sideNames();
    expect(names.indexOf("Zed")).toBeLessThan(names.indexOf("Alpha"));
  });

  it("Starred and Important are not draggable and take no collection drop", async () => {
    sidebar();
    const starred = await within(nav()).findByRole("link", { name: "Starred" });
    const important = within(nav()).getByRole("link", { name: "Important" });
    expect(starred).toHaveAttribute("draggable", "false");
    expect(important).toHaveAttribute("draggable", "false");
    const dt = dragColl(3, "Boat");
    sized(starred);
    fireEvent.dragOver(starred, { dataTransfer: dt, clientY: 2 });
    expect(starred).not.toHaveAttribute("data-reorder");
    expect(starred).not.toHaveAttribute("data-drop");
  });

  it("dragging over a sibling's top edge shows a line before it; the drop moves it there", async () => {
    const { calls } = sidebar();
    const car = sized(await within(nav()).findByRole("link", { name: "Car" }));
    const dt = dragColl(3, "Boat");
    fireEvent.dragEnter(car, { dataTransfer: dt, clientY: 2 });
    fireEvent.dragOver(car, { dataTransfer: dt, clientY: 2 });
    expect(car).toHaveAttribute("data-reorder", "before");
    expect(car).not.toHaveAttribute("data-drop");
    fireEvent.drop(car, { dataTransfer: dt, clientY: 2 });
    expect(car).not.toHaveAttribute("data-reorder");
    await waitFor(() => expect(moves(calls)).toHaveLength(1));
    expect(moves(calls)[0].url).toBe("/api/collections/3/move");
    expect(moves(calls)[0].body).toEqual({ before_id: 1 });
    expect(await screen.findByText("Moved Boat before Car")).toBeInTheDocument();
  });

  it("the bottom edge puts it after the sibling", async () => {
    const { calls } = sidebar();
    const boat = sized(await within(nav()).findByRole("link", { name: "Boat" }));
    const dt = dragColl(1, "Car");
    fireEvent.dragOver(boat, { dataTransfer: dt, clientY: 38 });
    expect(boat).toHaveAttribute("data-reorder", "after");
    fireEvent.drop(boat, { dataTransfer: dt, clientY: 38 });
    await waitFor(() => expect(moves(calls)).toHaveLength(1));
    expect(moves(calls)[0].url).toBe("/api/collections/1/move");
    expect(moves(calls)[0].body).toEqual({ after_id: 3 });
  });

  it("the middle of a row still moves the collection inside it (no line)", async () => {
    const { calls } = sidebar();
    const attic = sized(await within(nav()).findByRole("link", { name: "Attic" }));
    const dt = dragColl(3, "Boat");
    fireEvent.dragEnter(attic, { dataTransfer: dt, clientY: 20 });
    fireEvent.dragOver(attic, { dataTransfer: dt, clientY: 20 });
    expect(attic).not.toHaveAttribute("data-reorder");
    expect(attic).toHaveAttribute("data-drop", "over");
    fireEvent.drop(attic, { dataTransfer: dt, clientY: 20 });
    expect(moves(calls)).toHaveLength(0);
  });

  it("a collection of another parent is not reordered at an edge", async () => {
    const inner = coll(4, "Sofa", 0, 2);
    sidebar([CAR, ATTIC, inner, BOAT]);
    const car = sized(await within(nav()).findByRole("link", { name: "Car" }));
    const dt = dragColl(4, "Sofa");
    fireEvent.dragOver(car, { dataTransfer: dt, clientY: 2 });
    expect(car).not.toHaveAttribute("data-reorder");
  });

  it("a file dropped on a sidebar collection is still added to it", async () => {
    const { calls } = sidebar();
    const car = sized(await within(nav()).findByRole("link", { name: "Car" }));
    const dt = dataTransfer();
    setDragFiles({ dataTransfer: dt } as unknown as DragEvent, ["f1"], "a.pdf");
    fireEvent.dragEnter(car, { dataTransfer: dt, clientY: 2 });
    expect(car).toHaveAttribute("data-drop", "over");
    expect(car).not.toHaveAttribute("data-reorder");
    fireEvent.dragOver(car, { dataTransfer: dt, clientY: 2 });
    fireEvent.drop(car, { dataTransfer: dt, clientY: 2 });
    await waitFor(() => expect(calls.filter((c) => c.url === "/api/collections/1/members")).toHaveLength(1));
    expect(calls.find((c) => c.url === "/api/collections/1/members")!.body).toEqual({ drive_ids: ["f1"] });
    expect(moves(calls)).toHaveLength(0);
  });

  it("Alt+ArrowDown moves the focused collection down and says so", async () => {
    const { calls, user } = sidebar();
    const car = await within(nav()).findByRole("link", { name: "Car" });
    car.focus();
    await user.keyboard("{Alt>}{ArrowDown}{/Alt}");
    await waitFor(() => expect(moves(calls)).toHaveLength(1));
    expect(moves(calls)[0].url).toBe("/api/collections/1/move");
    expect(moves(calls)[0].body).toEqual({ after_id: 2 });
    expect(await screen.findByText("Moved Car down")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Moved Car down");
  });

  it("the context menu has Move up and Move down; the first has no Move up", async () => {
    const { calls, user } = sidebar();
    const car = await within(nav()).findByRole("link", { name: "Car" });
    await user.pointer({ keys: "[MouseRight]", target: car });
    const menu = await screen.findByRole("menu", { name: "Order of Car" });
    expect(within(menu).getByRole("menuitem", { name: "Move up" })).toBeDisabled();
    await user.keyboard("{Escape}");
    const boat = within(nav()).getByRole("link", { name: "Boat" });
    await user.pointer({ keys: "[MouseRight]", target: boat });
    const second = await screen.findByRole("menu", { name: "Order of Boat" });
    expect(within(second).getByRole("menuitem", { name: "Move down" })).toBeDisabled();
    await user.click(within(second).getByRole("menuitem", { name: "Move up" }));
    await waitFor(() => expect(moves(calls)).toHaveLength(1));
    expect(moves(calls)[0].body).toEqual({ before_id: 2 });
    expect(await screen.findByText("Moved Boat up")).toBeInTheDocument();
  });
});

describe("collections page order", () => {
  const rowOf = async (name: string) => sized(await screen.findByRole("article", { name }));

  it("lists the collections by position", async () => {
    page([coll(1, "Zed", 0), coll(2, "Alpha", 1)]);
    await screen.findByRole("article", { name: "Zed" });
    const names = screen.getAllByRole("article").map((a) => a.getAttribute("aria-label"));
    expect(names).toEqual(["Zed", "Alpha"]);
  });

  it("dragging a row over the upper half of a sibling shows a line and drops before it", async () => {
    const { calls } = page();
    const car = await rowOf("Car");
    const dt = dragColl(3, "Boat");
    fireEvent.dragOver(car, { dataTransfer: dt, clientY: 10 });
    expect(car).toHaveAttribute("data-reorder", "before");
    fireEvent.drop(car, { dataTransfer: dt, clientY: 10 });
    await waitFor(() => expect(moves(calls)).toHaveLength(1));
    expect(moves(calls)[0].url).toBe("/api/collections/3/move");
    expect(moves(calls)[0].body).toEqual({ before_id: 1 });
  });

  it("the lower half drops after it", async () => {
    const { calls } = page();
    const boat = await rowOf("Boat");
    const dt = dragColl(1, "Car");
    fireEvent.dragOver(boat, { dataTransfer: dt, clientY: 30 });
    expect(boat).toHaveAttribute("data-reorder", "after");
    fireEvent.drop(boat, { dataTransfer: dt, clientY: 30 });
    await waitFor(() => expect(moves(calls)).toHaveLength(1));
    expect(moves(calls)[0].body).toEqual({ after_id: 3 });
  });

  it("a row is not its own drop place", async () => {
    page();
    const car = await rowOf("Car");
    fireEvent.dragOver(car, { dataTransfer: dragColl(1, "Car"), clientY: 10 });
    expect(car).not.toHaveAttribute("data-reorder");
  });

  it("Alt+ArrowUp on a row moves it up; the first row cannot", async () => {
    const { calls, user } = page();
    (await screen.findByRole("link", { name: "Attic" })).focus();
    await user.keyboard("{Alt>}{ArrowUp}{/Alt}");
    await waitFor(() => expect(moves(calls)).toHaveLength(1));
    expect(moves(calls)[0].url).toBe("/api/collections/2/move");
    expect(moves(calls)[0].body).toEqual({ before_id: 1 });
    (await screen.findByRole("link", { name: "Car" })).focus();
    await user.keyboard("{Alt>}{ArrowUp}{/Alt}");
    expect(moves(calls)).toHaveLength(1);
  });

  it("the context menu moves a row down", async () => {
    const { calls, user } = page();
    await user.pointer({ keys: "[MouseRight]", target: await screen.findByRole("article", { name: "Car" }) });
    await user.click(await screen.findByRole("menuitem", { name: "Move down" }));
    await waitFor(() => expect(moves(calls)).toHaveLength(1));
    expect(moves(calls)[0].body).toEqual({ after_id: 2 });
  });
});
