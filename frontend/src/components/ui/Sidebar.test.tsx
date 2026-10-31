import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it } from "vitest";
import type { CollectionRow, Item, Member, Status, TrayDef } from "../../api/client";
import { setDragCollection, setDragFiles, setDragFolder, setDragSource } from "../../dnd";
import { type Call, dataTransfer, deferred, mockFetch, renderWithProviders } from "../../test-utils";
import { FILES_MOVED_EVENT, type FilesMovedDetail } from "../MoveTo";
import { Sidebar, trayIcon } from "./Sidebar";

const TO_PAY: TrayDef = {
  id: "to-pay",
  name: "To pay",
  order: 1,
  item_title: "{name}",
  fields: {},
  date_field: null,
  done: { label: "Mark paid", fields: {} },
};

const member = (drive_id: string): Member => ({
  drive_id,
  path: `X/${drive_id}.pdf`,
  is_dir: false,
  missing: false,
  quarantined: false,
  is_link: false,
  group_id: null,
  connected: true, marks: [],
});

const SAUNA: CollectionRow = {
  id: 7,
  name: "Sauna",
  state: "open",
  created: 1,
  closed_at: null,
  publish: { ongoing: true },
  ongoing_rel: null,
  members: [member("f9")],
  ongoing_status: null,
  summary: "",
  groups: [],
  parent_id: null,
  path: ["Sauna"],
  kind: null,
  position: 0,
  files: 0,
  open_checks: 0,
};

const ITEM: Item = {
  id: 42,
  tray_id: "to-pay",
  title: "Northpower‮ bill",
  fields: {},
  date: null,
  state: "open",
  created: 1,
  done_at: null,
  done_fields: null,
  files: ["f1"],
  created_by_batch: null,
  missing_required: [],
  invalid_fields: [],
  tray_name: "To pay",
  tray_removed: false,
};

const posts = (calls: Call[], url: string) => calls.filter((c) => c.method === "POST" && c.url === url);

function Where() {
  const loc = useLocation();
  return <p data-testid="where">{loc.pathname + loc.search}</p>;
}

function setup(extra: Parameters<typeof mockFetch>[0] = {}, collections: CollectionRow[] = [SAUNA], url = "/browse") {
  const calls = mockFetch({
    "GET /api/status": { body: { inbox_count: 0 } },
    "GET /api/today": { body: { attention: [], overview: { inbox: 0, trays: [], collections: [] } } },
    "GET /api/trays": { body: { trays: [TO_PAY], errors: [] } },
    "GET /api/collections": { body: collections },
    ...extra,
  });
  renderWithProviders(
    <MemoryRouter initialEntries={[url]}>
      <Sidebar />
      <Where />
    </MemoryRouter>,
  );
  return { calls, user: userEvent.setup() };
}

/** Start a drag of ``ids`` as a list row would, and return its DataTransfer. */
function drag(ids: string[], label = "a.pdf") {
  const dt = dataTransfer();
  setDragFiles({ dataTransfer: dt } as unknown as DragEvent, ids, label);
  return dt;
}

const nav = () => screen.getByRole("navigation", { name: "Main" });

describe("Sidebar drops", () => {
  it("dropping on a tray puts the files in it; the toast opens the item or takes it back", async () => {
    const { calls, user } = setup({
      "POST /api/items/quick": { body: { created: [ITEM], skipped: [] } },
      "POST /api/items/42/discard": { status: 204, body: null },
    });
    const row = await within(nav()).findByRole("link", { name: "To pay" });
    const dt = drag(["f1"]);
    fireEvent.dragEnter(row, { dataTransfer: dt });
    expect(row).toHaveAttribute("data-drop", "over");
    fireEvent.drop(row, { dataTransfer: dt });
    expect(row).not.toHaveAttribute("data-drop");
    await waitFor(() => expect(posts(calls, "/api/items/quick")).toHaveLength(1));
    expect(posts(calls, "/api/items/quick")[0].body).toEqual({ tray: "to-pay", drive_ids: ["f1"] });
    expect(await screen.findByText("Put in To pay: Northpower⟨U+202E⟩ bill")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Open" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Undo" }));
    await waitFor(() => expect(posts(calls, "/api/items/42/discard")).toHaveLength(1));
    expect(await screen.findByText("Taken back: Northpower⟨U+202E⟩ bill")).toBeInTheDocument();
  });

  it("several files: one toast for all; files already in the tray are counted as such", async () => {
    const { calls, user } = setup({
      "POST /api/items/quick": { body: { created: [ITEM, { ...ITEM, id: 43, title: "Other" }], skipped: ["f3"] } },
      "POST /api/items/42/discard": { status: 204, body: null },
      "POST /api/items/43/discard": { status: 204, body: null },
    });
    const row = await within(nav()).findByRole("link", { name: "To pay" });
    const dt = drag(["f1", "f2", "f3"]);
    fireEvent.dragEnter(row, { dataTransfer: dt });
    fireEvent.drop(row, { dataTransfer: dt });
    expect(await screen.findByText("Put 2 files in To pay (1 already in it)")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Open" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Undo" }));
    await waitFor(() => expect(posts(calls, "/api/items/43/discard")).toHaveLength(1));
    expect(posts(calls, "/api/items/42/discard")).toHaveLength(1);
    expect(await screen.findByText("Taken back 2 items from To pay")).toBeInTheDocument();
  });

  it("Open in the toast shows the new item", async () => {
    const { user } = setup({ "POST /api/items/quick": { body: { created: [ITEM], skipped: [] } } });
    const row = await within(nav()).findByRole("link", { name: "To pay" });
    const dt = drag(["f1"]);
    fireEvent.dragEnter(row, { dataTransfer: dt });
    fireEvent.drop(row, { dataTransfer: dt });
    await user.click(await screen.findByRole("button", { name: "Open" }));
    expect(screen.getByTestId("where")).toHaveTextContent("/trays/to-pay?item=42");
  });

  it("a file already in the tray: 'already in', with Open", async () => {
    const { user } = setup({ "POST /api/items/quick": { body: { created: [], skipped: ["f1"] } } });
    const row = await within(nav()).findByRole("link", { name: "To pay" });
    const dt = drag(["f1"]);
    fireEvent.dragEnter(row, { dataTransfer: dt });
    fireEvent.drop(row, { dataTransfer: dt });
    expect(await screen.findByText("a.pdf: already in To pay")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Undo" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Open" }));
    expect(screen.getByTestId("where")).toHaveTextContent("/trays/to-pay");
  });

  it("a second drop while the first is in flight sends nothing", async () => {
    const held = deferred<{ body: unknown }>();
    const { calls } = setup({ "POST /api/items/quick": () => held.promise });
    const row = await within(nav()).findByRole("link", { name: "To pay" });
    const dt = drag(["f1"]);
    fireEvent.dragEnter(row, { dataTransfer: dt });
    fireEvent.drop(row, { dataTransfer: dt });
    fireEvent.dragEnter(row, { dataTransfer: dt });
    fireEvent.drop(row, { dataTransfer: dt });
    await act(async () => held.resolve({ body: { created: [ITEM], skipped: [] } }));
    expect(posts(calls, "/api/items/quick")).toHaveLength(1);
  });

  it("a refused quick put shows the error", async () => {
    setup({ "POST /api/items/quick": { status: 400, body: { error: "no such ‮tray" } } });
    const row = await within(nav()).findByRole("link", { name: "To pay" });
    const dt = drag(["f1"]);
    fireEvent.dragEnter(row, { dataTransfer: dt });
    fireEvent.drop(row, { dataTransfer: dt });
    expect(await screen.findByText("Could not put a.pdf in To pay: no such ⟨U+202E⟩tray")).toBeInTheDocument();
  });

  it("dropping on a collection adds the files (ungrouped) and shows the Ongoing result", async () => {
    const { calls } = setup({
      "POST /api/collections/7/members": {
        body: { collection: SAUNA, batch: null, problems: ["plan refused: ‮x"], ongoing_status: null },
      },
    });
    const row = await within(nav()).findByRole("link", { name: "Sauna" });
    const dt = drag(["f1", "f2"]);
    fireEvent.dragEnter(row, { dataTransfer: dt });
    expect(row).toHaveAttribute("data-drop", "over");
    fireEvent.drop(row, { dataTransfer: dt });
    await waitFor(() => expect(posts(calls, "/api/collections/7/members")).toHaveLength(1));
    expect(posts(calls, "/api/collections/7/members")[0].body).toEqual({ drive_ids: ["f1", "f2"] });
    expect(await screen.findByText("Added 2 files to Sauna, but: plan refused: ⟨U+202E⟩x")).toBeInTheDocument();
  });

  it("files already in the collection are refused with a reason", async () => {
    const { calls } = setup();
    const row = await within(nav()).findByRole("link", { name: "Sauna" });
    const dt = drag(["f9"]);
    fireEvent.dragEnter(row, { dataTransfer: dt });
    expect(row).toHaveAttribute("data-drop", "refused");
    expect(row).toHaveAttribute("data-tip", "Already in Sauna");
    expect(fireEvent.drop(row, { dataTransfer: dt })).toBe(false);
    expect(posts(calls, "/api/collections/7/members")).toHaveLength(0);
  });

  it("a closed collection is not allowed", async () => {
    const { calls } = setup({}, [{ ...SAUNA, state: "closed" }]);
    const row = await within(nav()).findByRole("link", { name: "Sauna" });
    const dt = drag(["f1"]);
    fireEvent.dragEnter(row, { dataTransfer: dt });
    expect(row).toHaveAttribute("data-drop", "refused");
    expect(row).toHaveAttribute("data-tip", "Sauna is closed: reopen it to add files");
    fireEvent.drop(row, { dataTransfer: dt });
    await new Promise((r) => setTimeout(r, 10));
    expect(posts(calls, "/api/collections/7/members")).toHaveLength(0);
  });

  it("a file dragged from a collection onto another of the same tree moves; onto another tree it is added", async () => {
    const legal = coll(1, "Legal", ["Legal"], null);
    const mine = coll(2, "Michiel", ["Legal", "Michiel"], 1, { members: [member("f1")] });
    const both = coll(3, "Together", ["Legal", "Together"], 1);
    const car = coll(4, "Car", ["Car"], null);
    const { calls } = setup(
      {
        "POST /api/collections/2/members/move": { body: { collection: both, batch: null, problems: [], ongoing_status: null } },
        "POST /api/collections/4/members": { body: { collection: car, batch: null, problems: [], ongoing_status: null } },
      },
      [legal, mine, both, car],
    );
    const fromMichiel = () => {
      const dt = drag(["f1"]);
      setDragSource({ dataTransfer: dt } as unknown as DragEvent, 2);
      return dt;
    };
    const together = await within(nav()).findByRole("link", { name: "Together" });
    let dt = fromMichiel();
    fireEvent.dragEnter(together, { dataTransfer: dt });
    fireEvent.drop(together, { dataTransfer: dt });
    await waitFor(() => expect(posts(calls, "/api/collections/2/members/move")).toHaveLength(1));
    expect(posts(calls, "/api/collections/2/members/move")[0].body).toEqual({ to: 3, drive_ids: ["f1"] });
    expect(await screen.findByText(/Moved a\.pdf from Michiel to Together/)).toBeInTheDocument();

    const carRow = within(nav()).getByRole("link", { name: "Car" });
    dt = fromMichiel();
    fireEvent.dragEnter(carRow, { dataTransfer: dt });
    fireEvent.drop(carRow, { dataTransfer: dt });
    await waitFor(() => expect(posts(calls, "/api/collections/4/members")).toHaveLength(1));
  });

  it("a collection row opens it in Browse and is current only while Browse shows it", async () => {
    setup({}, [SAUNA], "/browse?q=collection:Sauna");
    const row = await within(nav()).findByRole("link", { name: /^Sauna/ });
    expect(row).toHaveAttribute("href", "/browse?tree=collections&q=collection%3ASauna");
    expect(row).toHaveAttribute("aria-current", "page");
    cleanup();
    setup({}, [SAUNA], "/browse?q=kela");
    expect(await within(nav()).findByRole("link", { name: /^Sauna/ })).not.toHaveAttribute("aria-current");
  });

  it("other rows are not drop targets", async () => {
    setup();
    const today = await within(nav()).findByRole("link", { name: "Today" });
    const dt = drag(["f1"]);
    expect(fireEvent.dragEnter(today, { dataTransfer: dt })).toBe(true); // not taken
    expect(today).not.toHaveAttribute("data-drop");
  });
});

const coll = (id: number, name: string, path: string[], parent_id: number | null, extra: Partial<CollectionRow> = {}): CollectionRow => ({
  ...SAUNA,
  id,
  name,
  path,
  parent_id,
  members: [],
  files: 0,
  ...extra,
});
const HOUSES = coll(1, "Houses", ["Houses"], null);
const IN_HOUSES = { ...SAUNA, parent_id: 1, path: ["Houses", "Sauna"] };
const DECK = coll(9, "Deck", ["Houses", "Sauna", "Deck"], 7);
const CAR = coll(3, "Car", ["Car"], null);
const TREE = [HOUSES, IN_HOUSES, DECK, CAR];

/** Start a drag of collection ``id`` as a sidebar row would. */
function dragColl(id: number, label: string, protectedMode = false) {
  const dt = dataTransfer({ protectedMode });
  setDragCollection({ dataTransfer: dt } as unknown as DragEvent, id, label);
  return dt;
}
const patches = (calls: Call[], url: string) => calls.filter((c) => c.method === "PATCH" && c.url === url);
const moved = (c: CollectionRow, parent_id: number | null) => ({
  collection: { ...c, parent_id },
  batch: {
    batch_id: "b9",
    dry_run: false,
    done: [{ kind: "move", src: "##. Ongoing/Houses/Sauna", dst: "##. Ongoing/Car/Sauna", drive_id: null, note: null }],
    failed: null,
    error: null,
    index_error: null,
  },
  problems: [],
  ongoing_status: null,
});

describe("Sidebar collection tree", () => {
  beforeEach(() => {
    localStorage.clear();
    document.dispatchEvent(new Event("dragend"));
  });

  it("nests the collections under their parents, A–Z on each level", async () => {
    setup({}, [CAR, DECK, IN_HOUSES, HOUSES]);
    const houses = await within(nav()).findByRole("link", { name: "Houses" });
    const item = houses.closest("li")!;
    expect(within(item).getByRole("link", { name: "Sauna" })).toBeInTheDocument();
    const sauna = within(item).getByRole("link", { name: "Sauna" }).closest("li")!;
    expect(within(sauna).getByRole("link", { name: "Deck" })).toBeInTheDocument();
    const top = within(nav()).getAllByRole("link").map((a) => a.textContent);
    expect(top.indexOf("Car")).toBeLessThan(top.indexOf("Houses"));
    expect(within(nav()).getByRole("button", { name: "Collections in Houses" })).toHaveAttribute("aria-expanded", "true");
    expect(within(nav()).queryByRole("button", { name: "Collections in Car" })).not.toBeInTheDocument(); // no children
  });

  it("folds a parent, and remembers it", async () => {
    const { user } = setup({}, TREE);
    await within(nav()).findByRole("link", { name: "Sauna" });
    await user.click(within(nav()).getByRole("button", { name: "Collections in Houses" }));
    expect(within(nav()).queryByRole("link", { name: "Sauna" })).not.toBeInTheDocument();
    expect(within(nav()).getByRole("button", { name: "Collections in Houses" })).toHaveAttribute("aria-expanded", "false");
    cleanup();
    setup({}, TREE);
    await within(nav()).findByRole("link", { name: "Houses" });
    expect(within(nav()).queryByRole("link", { name: "Sauna" })).not.toBeInTheDocument();
    await user.click(within(nav()).getByRole("button", { name: "Collections in Houses" }));
    expect(within(nav()).getByRole("link", { name: "Sauna" })).toBeInTheDocument();
    cleanup();
    setup({}, TREE);
    expect(await within(nav()).findByRole("link", { name: "Sauna" })).toBeInTheDocument();
  });

  it("works without storage (a private window): folds still toggle", async () => {
    const real = Object.getOwnPropertyDescriptor(window, "localStorage")!;
    Object.defineProperty(window, "localStorage", {
      configurable: true,
      get() {
        throw new Error("blocked");
      },
    });
    try {
      const { user } = setup({}, TREE);
      await within(nav()).findByRole("link", { name: "Sauna" });
      await user.click(within(nav()).getByRole("button", { name: "Collections in Houses" }));
      expect(within(nav()).queryByRole("link", { name: "Sauna" })).not.toBeInTheDocument();
    } finally {
      Object.defineProperty(window, "localStorage", real);
    }
  });

  it("dragging a collection onto another moves it inside, and the toast says what Ongoing did", async () => {
    const { calls } = setup({ "PATCH /api/collections/7/parent": { body: { ...moved(IN_HOUSES, 3), problems: ["user‮ file left"] } } }, TREE);
    await within(nav()).findByRole("link", { name: "Sauna" });
    const car = within(nav()).getByRole("link", { name: "Car" });
    const dt = dragColl(7, "Sauna", true); // hovering: the data is hidden
    fireEvent.dragEnter(car, { dataTransfer: dt });
    expect(car).toHaveAttribute("data-drop", "over");
    dt.protectedMode = false;
    fireEvent.drop(car, { dataTransfer: dt });
    await waitFor(() => expect(patches(calls, "/api/collections/7/parent")).toHaveLength(1));
    expect(patches(calls, "/api/collections/7/parent")[0].body).toEqual({ parent_id: 3 });
    expect(await screen.findByText("Moved Sauna into Car, but: user⟨U+202E⟩ file left")).toBeInTheDocument();
    expect(posts(calls, "/api/collections/3/members")).toHaveLength(0); // not taken as files
    // Open goes to the moved collection's page (its LastChange and Activity)
    await userEvent.setup().click(screen.getByRole("button", { name: "Open" }));
    expect(screen.getByTestId("where")).toHaveTextContent("/open-collection/7");
  });

  it("a drag that recreated many links says how many in the toast", async () => {
    const done = Array.from({ length: 60 }, (_, i) => ({ kind: "symlink", src: `f${i}.pdf`, dst: `##. Ongoing/Car/Sauna/f${i}.pdf`, drive_id: null, note: null }));
    const result = moved(IN_HOUSES, 3);
    const { calls } = setup({ "PATCH /api/collections/7/parent": { body: { ...result, batch: { ...result.batch, done } } } }, TREE);
    await within(nav()).findByRole("link", { name: "Sauna" });
    const car = within(nav()).getByRole("link", { name: "Car" });
    const dt = dragColl(7, "Sauna");
    fireEvent.dragEnter(car, { dataTransfer: dt });
    fireEvent.drop(car, { dataTransfer: dt });
    await waitFor(() => expect(patches(calls, "/api/collections/7/parent")).toHaveLength(1));
    expect(await screen.findByText("Moved Sauna into Car (recreated 60 links)")).toBeInTheDocument();
  });

  it("has Starred under Important in Collections, with its count, opening it in Browse", async () => {
    const members = [{ drive_id: "a" }, { drive_id: "b" }, { drive_id: "c" }];
    const { user } = setup({
      "GET /api/marks/collection/starred": { body: { id: 1, name: "Ongoing", kind: "starred", members, groups: [] } },
      "GET /api/marks/collection/important": { body: { id: 2, name: "Important", kind: "important", members: [{ drive_id: "p" }], groups: [] } },
    });
    const starred = await within(nav()).findByRole("link", { name: "Starred (3)" });
    expect(starred).toHaveTextContent("Starred");
    expect(starred).toHaveTextContent("3");
    const rows = within(nav()).getAllByRole("link");
    const important = rows.indexOf(within(nav()).getByRole("link", { name: "Important (1)" }));
    expect(rows.indexOf(starred)).toBe(important + 1);
    await user.click(starred);
    expect(screen.getByTestId("where")).toHaveTextContent("/browse?tree=collections&q=is%3Astarred");
  });

  it("dropping a collection on the Collections header moves it to the top level", async () => {
    const { calls } = setup({ "PATCH /api/collections/7/parent": { body: moved(IN_HOUSES, null) } }, TREE);
    await within(nav()).findByRole("link", { name: "Sauna" });
    const header = within(nav()).getByRole("link", { name: "Collections" });
    const dt = dragColl(7, "Sauna");
    fireEvent.dragEnter(header, { dataTransfer: dt });
    expect(header).toHaveAttribute("data-drop", "over");
    fireEvent.drop(header, { dataTransfer: dt });
    await waitFor(() => expect(patches(calls, "/api/collections/7/parent")).toHaveLength(1));
    expect(patches(calls, "/api/collections/7/parent")[0].body).toEqual({ parent_id: null });
    expect(await screen.findByText("Moved Sauna to the top level")).toBeInTheDocument();
  });

  it("a top-level collection on the header, or one on its own parent, is refused with a reason", async () => {
    const { calls } = setup({}, TREE);
    await within(nav()).findByRole("link", { name: "Sauna" });
    const header = within(nav()).getByRole("link", { name: "Collections" });
    const car = dragColl(3, "Car");
    fireEvent.dragEnter(header, { dataTransfer: car });
    expect(header).toHaveAttribute("data-drop", "refused");
    expect(header).toHaveAttribute("data-tip", "Car is already at the top level");
    fireEvent.drop(header, { dataTransfer: car });
    document.dispatchEvent(new Event("dragend"));
    const houses = within(nav()).getByRole("link", { name: "Houses" });
    const sauna = dragColl(7, "Sauna");
    fireEvent.dragEnter(houses, { dataTransfer: sauna });
    expect(houses).toHaveAttribute("data-tip", "Sauna is already in Houses");
    fireEvent.drop(houses, { dataTransfer: sauna });
    await new Promise((r) => setTimeout(r, 10));
    expect(calls.filter((c) => c.method === "PATCH")).toHaveLength(0);
  });

  it("a collection cannot go into itself or one of its own collections: no drop target", async () => {
    const { calls } = setup({}, TREE);
    await within(nav()).findByRole("link", { name: "Deck" });
    const houses = within(nav()).getByRole("link", { name: "Houses" });
    const deck = within(nav()).getByRole("link", { name: "Deck" });
    const dt = dragColl(1, "Houses");
    fireEvent.dragEnter(houses, { dataTransfer: dt });
    expect(houses).toHaveAttribute("data-drop", "refused");
    expect(houses).toHaveAttribute("data-tip", "Houses cannot go inside itself");
    expect(fireEvent.drop(houses, { dataTransfer: dt })).toBe(false);
    fireEvent.dragEnter(deck, { dataTransfer: dt });
    expect(deck).toHaveAttribute("data-drop", "refused");
    expect(deck).toHaveAttribute("data-tip", "Deck is inside Houses: Houses cannot go inside it");
    const over = { dataTransfer: dt };
    fireEvent.dragOver(deck, over);
    expect(dt.dropEffect).toBe("none");
    fireEvent.drop(deck, { dataTransfer: dt });
    await new Promise((r) => setTimeout(r, 10));
    expect(calls.filter((c) => c.method === "PATCH")).toHaveLength(0);
  });

  it("a closed collection takes no collection", async () => {
    const { calls } = setup({}, [IN_HOUSES, { ...CAR, state: "closed" }, HOUSES]);
    const car = await within(nav()).findByRole("link", { name: "Car" });
    const dt = dragColl(7, "Sauna");
    fireEvent.dragEnter(car, { dataTransfer: dt });
    expect(car).toHaveAttribute("data-tip", "Car is closed: reopen it first");
    fireEvent.drop(car, { dataTransfer: dt });
    await new Promise((r) => setTimeout(r, 10));
    expect(calls.filter((c) => c.method === "PATCH")).toHaveLength(0);
  });

  it("a folder dropped on a collection is added as one member (protected drag: read from this window); trays and the Inbox ignore it", async () => {
    const { calls } = setup({
      "GET /api/status": { body: { inbox_count: 2, special_folders: SPECIAL } },
      "POST /api/collections/7/members": { body: { collection: SAUNA, batch: null, problems: [], ongoing_status: null } },
    });
    const folder = () => {
      const dt = dataTransfer({ protectedMode: true }); // hovering: only the types are readable
      setDragFolder({ dataTransfer: dt } as unknown as DragEvent, "d9", "13. Taxes");
      return dt;
    };
    const row = await within(nav()).findByRole("link", { name: "Sauna" });
    for (const name of ["To pay", "Inbox (2)"]) {
      const other = within(nav()).getByRole("link", { name });
      expect(fireEvent.dragEnter(other, { dataTransfer: folder() })).toBe(true); // not taken
      expect(other).not.toHaveAttribute("data-drop");
      document.dispatchEvent(new Event("dragend"));
    }
    const dt = folder();
    fireEvent.dragEnter(row, { dataTransfer: dt });
    expect(row).toHaveAttribute("data-drop", "over");
    // the drop effect must be one the folder drag allows, or a real browser cancels the
    // drop (the row highlighted, nothing added)
    fireEvent.dragOver(row, { dataTransfer: dt });
    expect(dt.effectAllowed).toBe("copyMove");
    expect(dt.dropEffect).toBe("move");
    fireEvent.drop(row, { dataTransfer: dt });
    await waitFor(() => expect(posts(calls, "/api/collections/7/members")).toHaveLength(1));
    expect(posts(calls, "/api/collections/7/members")[0].body).toEqual({ drive_ids: ["d9"] });
    expect(await screen.findByText("Added 13. Taxes to Sauna")).toBeInTheDocument();
    expect(calls.filter((c) => c.method !== "GET" && !c.url.startsWith("/api/collections/7/members"))).toHaveLength(0);
  });

  it("a collection drag is not taken by a tray, the Inbox or Today; files are not taken by the header", async () => {
    const { calls } = setup({ "GET /api/status": { body: { inbox_count: 2, special_folders: SPECIAL } } }, TREE);
    await within(nav()).findByRole("link", { name: "Sauna" });
    const dt = dragColl(7, "Sauna");
    for (const name of ["To pay", "Inbox (2)", "Today"]) {
      const row = within(nav()).getByRole("link", { name });
      expect(fireEvent.dragEnter(row, { dataTransfer: dt })).toBe(true); // not taken
      expect(row).not.toHaveAttribute("data-drop");
      fireEvent.drop(row, { dataTransfer: dt });
    }
    document.dispatchEvent(new Event("dragend"));
    const header = within(nav()).getByRole("link", { name: "Collections" });
    const files = drag(["f1"]);
    expect(fireEvent.dragEnter(header, { dataTransfer: files })).toBe(true);
    expect(header).not.toHaveAttribute("data-drop");
    await new Promise((r) => setTimeout(r, 10));
    expect(calls.filter((c) => c.method !== "GET")).toHaveLength(0);
  });

  it("files dropped on a nested collection are still added as members", async () => {
    const { calls } = setup({ "POST /api/collections/9/members": { body: { collection: DECK, batch: null, problems: [], ongoing_status: null } } }, TREE);
    const deck = await within(nav()).findByRole("link", { name: "Deck" });
    const dt = drag(["f1"]);
    fireEvent.dragEnter(deck, { dataTransfer: dt });
    expect(deck).toHaveAttribute("data-drop", "over");
    fireEvent.drop(deck, { dataTransfer: dt });
    await waitFor(() => expect(posts(calls, "/api/collections/9/members")).toHaveLength(1));
    expect(posts(calls, "/api/collections/9/members")[0].body).toEqual({ drive_ids: ["f1"] });
    expect(await screen.findByText("Added a.pdf to Deck")).toBeInTheDocument();
    expect(calls.filter((c) => c.method === "PATCH")).toHaveLength(0);
  });

  it("a second collection drop while a move runs sends nothing; a refused move shows why", async () => {
    const held = deferred<{ status?: number; body: unknown }>();
    const { calls } = setup({ "PATCH /api/collections/7/parent": () => held.promise }, TREE);
    await within(nav()).findByRole("link", { name: "Sauna" });
    const car = within(nav()).getByRole("link", { name: "Car" });
    const dt = dragColl(7, "Sauna");
    fireEvent.dragEnter(car, { dataTransfer: dt });
    fireEvent.drop(car, { dataTransfer: dt });
    const again = dragColl(7, "Sauna");
    fireEvent.dragEnter(car, { dataTransfer: again });
    fireEvent.drop(car, { dataTransfer: again });
    await act(async () => held.resolve({ status: 409, body: { error: "Car is ‮closed" } }));
    expect(patches(calls, "/api/collections/7/parent")).toHaveLength(1);
    expect(await screen.findByText(/^Could not move Sauna into Car: .*Car is ⟨U\+202E⟩closed/)).toBeInTheDocument();
  });

  it("collection rows are draggable; dragging one carries the collection type only", async () => {
    setup({}, TREE);
    const sauna = await within(nav()).findByRole("link", { name: "Sauna" });
    expect(sauna).toHaveAttribute("draggable", "true");
    const dt = dataTransfer();
    fireEvent.dragStart(sauna, { dataTransfer: dt });
    expect(dt.types).toEqual(["application/x-dam-collection"]);
    expect(JSON.parse(dt.data["application/x-dam-collection"])).toEqual({ id: 7 });
    document.dispatchEvent(new Event("dragend"));
  });
});

const SPECIAL = { inbox: "##. Organize", ongoing: "##. Ongoing", important: "##. Important", quarantine: "##. To Delete" };
const BACK_PLAN = [
  { kind: "move", src: "10. Financial/a.pdf", dst: "##. Organize/a.pdf", drive_id: "f1", note: null },
];

describe("Back to inbox: dropping on the sidebar Inbox", () => {
  const inboxSetup = (extra: Parameters<typeof mockFetch>[0] = {}) =>
    setup({ "GET /api/status": { body: { inbox_count: 2, special_folders: SPECIAL } }, ...extra });
  const inboxRow = () => within(nav()).findByRole("link", { name: "Inbox (2)" });
  const dragWith = (ids: string[], paths: string[]) => {
    const dt = dataTransfer();
    setDragFiles({ dataTransfer: dt } as unknown as DragEvent, ids, "a.pdf", paths);
    return dt;
  };

  it("always confirms first: preview into the inbox folder, then the move, with Undo", async () => {
    const { calls, user } = inboxSetup({
      "POST /api/browse/move/preview": { body: BACK_PLAN },
      "POST /api/browse/move": {
        body: { batch_id: "m1", dry_run: false, done: BACK_PLAN, failed: null, error: null, index_error: null, unchanged: [], folder: "##. Organize" },
      },
    });
    const row = await inboxRow();
    const dt = dragWith(["f1"], ["10. Financial/a.pdf"]);
    fireEvent.dragEnter(row, { dataTransfer: dt });
    expect(row).toHaveAttribute("data-drop", "over");
    fireEvent.drop(row, { dataTransfer: dt });
    const dialog = await screen.findByRole("dialog", { name: "Move 1 file to ##. Organize?" });
    expect(posts(calls, "/api/browse/move/preview").map((c) => c.body)).toEqual([
      { drive_ids: ["f1"], folder: "##. Organize" },
    ]);
    expect(posts(calls, "/api/browse/move")).toHaveLength(0); // a drop never moves by itself
    await user.click(within(dialog).getByRole("button", { name: "Move" }));
    await waitFor(() => expect(posts(calls, "/api/browse/move")).toHaveLength(1));
    expect(posts(calls, "/api/browse/move")[0].body).toEqual({ drive_ids: ["f1"], folder: "##. Organize" });
    expect(await screen.findByText("Moved a.pdf to ##. Organize")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Undo" })).toBeInTheDocument();
  });

  it("tells the rest of the app which files moved (Browse forgets them and reloads)", async () => {
    const seen: FilesMovedDetail[] = [];
    const listen = (e: Event) => seen.push((e as CustomEvent<FilesMovedDetail>).detail);
    window.addEventListener(FILES_MOVED_EVENT, listen);
    try {
      const { user } = inboxSetup({
        "POST /api/browse/move/preview": { body: BACK_PLAN },
        "POST /api/browse/move": {
          body: { batch_id: "m1", dry_run: false, done: BACK_PLAN, failed: null, error: null, index_error: null, unchanged: [], folder: "##. Organize" },
        },
      });
      const row = await inboxRow();
      const dt = dragWith(["f1"], ["10. Financial/a.pdf"]);
      fireEvent.dragEnter(row, { dataTransfer: dt });
      fireEvent.drop(row, { dataTransfer: dt });
      const dialog = await screen.findByRole("dialog", { name: "Move 1 file to ##. Organize?" });
      expect(seen).toEqual([]);
      await user.click(within(dialog).getByRole("button", { name: "Move" }));
      await waitFor(() => expect(seen).toEqual([{ ids: ["f1"] }]));
    } finally {
      window.removeEventListener(FILES_MOVED_EVENT, listen);
    }
  });

  it("Cancel in the confirm moves nothing", async () => {
    const { calls, user } = inboxSetup({ "POST /api/browse/move/preview": { body: BACK_PLAN } });
    const row = await inboxRow();
    const dt = dragWith(["f1"], ["10. Financial/a.pdf"]);
    fireEvent.dragEnter(row, { dataTransfer: dt });
    fireEvent.drop(row, { dataTransfer: dt });
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(posts(calls, "/api/browse/move")).toHaveLength(0);
  });

  it("a mixed drag leaves out the files already in the inbox, and the confirm says how many", async () => {
    const { calls, user } = inboxSetup({
      "POST /api/browse/move/preview": { body: BACK_PLAN },
      "POST /api/browse/move": {
        body: { batch_id: "m1", dry_run: false, done: BACK_PLAN, failed: null, error: null, index_error: null, unchanged: [], folder: "##. Organize" },
      },
    });
    const row = await inboxRow();
    const dt = dragWith(
      ["f1", "o1", "o2"],
      ["10. Financial/a.pdf", "##. Organize/b.pdf", "##. Organize/sub/c.pdf"], // anywhere under the inbox
    );
    fireEvent.dragEnter(row, { dataTransfer: dt });
    fireEvent.drop(row, { dataTransfer: dt });
    const dialog = await screen.findByRole("dialog", { name: "Move 1 file to ##. Organize?" });
    expect(posts(calls, "/api/browse/move/preview").map((c) => c.body)).toEqual([
      { drive_ids: ["f1"], folder: "##. Organize" },
    ]);
    expect(dialog).toHaveTextContent("2 already in the inbox (skipped)");
    await user.click(within(dialog).getByRole("button", { name: "Move" }));
    await waitFor(() => expect(posts(calls, "/api/browse/move")).toHaveLength(1));
    expect(posts(calls, "/api/browse/move")[0].body).toEqual({ drive_ids: ["f1"], folder: "##. Organize" });
  });

  it("files already in ##. Organize are refused before the drop", async () => {
    const { calls } = inboxSetup();
    const row = await inboxRow();
    const dt = dragWith(["f1", "f2"], ["##. Organize/a.pdf", "##. organize/sub/b.pdf"]);
    fireEvent.dragEnter(row, { dataTransfer: dt });
    expect(row).toHaveAttribute("data-drop", "refused");
    expect(row).toHaveAttribute("data-tip", "Already in the inbox");
    fireEvent.drop(row, { dataTransfer: dt });
    await new Promise((r) => setTimeout(r, 10));
    expect(posts(calls, "/api/browse/move/preview")).toHaveLength(0);
  });

  it("files whose area keeps them are refused too", async () => {
    const { calls } = inboxSetup();
    const row = await inboxRow();
    const dt = dragWith(["f1"], ["##. To Delete/x/a.pdf"]);
    fireEvent.dragEnter(row, { dataTransfer: dt });
    expect(row).toHaveAttribute("data-tip", "Marked for deletion: restore it first");
    fireEvent.drop(row, { dataTransfer: dt });
    await new Promise((r) => setTimeout(r, 10));
    expect(posts(calls, "/api/browse/move/preview")).toHaveLength(0);
  });

  it("a drag without paths (a tray item) asks the server; nothing to move says it is already in the inbox", async () => {
    const { calls } = inboxSetup({ "POST /api/browse/move/preview": { body: [] } });
    const row = await inboxRow();
    const dt = drag(["f1"]);
    fireEvent.dragEnter(row, { dataTransfer: dt });
    expect(row).toHaveAttribute("data-drop", "over");
    fireEvent.drop(row, { dataTransfer: dt });
    expect(await screen.findByText("Already in the inbox")).toBeInTheDocument();
    expect(posts(calls, "/api/browse/move/preview")).toHaveLength(1);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("before the status is known the inbox takes no drop", async () => {
    const { calls } = setup(); // the status has no special_folders
    const row = await within(nav()).findByRole("link", { name: "Inbox" });
    const dt = dragWith(["f1"], ["10. Financial/a.pdf"]);
    fireEvent.dragEnter(row, { dataTransfer: dt });
    expect(row).toHaveAttribute("data-drop", "refused");
    fireEvent.drop(row, { dataTransfer: dt });
    await new Promise((r) => setTimeout(r, 10));
    expect(posts(calls, "/api/browse/move/preview")).toHaveLength(0);
  });
});

describe("Sidebar and Today counts", () => {
  it("Today and the inbox are fetched again when the inbox count or indexing changes, not on every status poll", async () => {
    const { QueryClient, QueryClientProvider } = await import("@tanstack/react-query");
    const { renderHook } = await import("@testing-library/react");
    const { useInbox, useToday, useTodayFollowsInbox } = await import("../../api/client");
    const calls = mockFetch({
      "GET /api/today": { body: { attention: [], overview: { trays: [] } } },
      "GET /api/inbox": { body: [] },
    });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const todays = () => calls.filter((c) => c.url === "/api/today").length;
    // Today's "Not recognised" reads the inbox's tray guesses, which indexing fills in.
    const inboxes = () => calls.filter((c) => c.url === "/api/inbox").length;
    const at = (inbox_count: number, indexed: number, pending: number) =>
      ({ files: 10, inbox_count, indexed, pending }) as Status;
    const { rerender } = renderHook(
      ({ status }: { status: Status | undefined }) => {
        useToday();
        useInbox();
        useTodayFollowsInbox(status);
      },
      {
        initialProps: { status: undefined as Status | undefined },
        wrapper: ({ children }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>,
      },
    );
    await waitFor(() => expect(todays()).toBe(1));
    await waitFor(() => expect(inboxes()).toBe(1));
    rerender({ status: at(3, 5, 5) }); // the first status: nothing to catch up on
    rerender({ status: at(3, 5, 5) });
    await new Promise((r) => setTimeout(r, 20));
    expect(todays()).toBe(1);
    expect(inboxes()).toBe(1);
    rerender({ status: at(4, 5, 5) }); // a scan found a new inbox file
    await waitFor(() => expect(todays()).toBe(2));
    rerender({ status: at(4, 10, 0) }); // indexing finished: "Found in the inbox" may have grown
    await waitFor(() => expect(todays()).toBe(3));
    await waitFor(() => expect(inboxes()).toBe(3));
  });
});

describe("trayIcon", () => {
  it("Follow up gets the hourglass, the others keep theirs", () => {
    const tray = (id: string, name: string) => ({ ...TO_PAY, id, name });
    const follow = trayIcon(tray("follow-up", "Follow up"));
    expect(follow.displayName).toBe("Hourglass");
    for (const [id, name] of [["to-pay", "To pay"], ["to-action", "To action"], ["to-read", "To read"]]) {
      expect(trayIcon(tray(id, name))).not.toBe(follow);
    }
  });

  it("Renew gets the calendar clock, as an Expiry tray would", () => {
    const tray = (id: string, name: string) => ({ ...TO_PAY, id, name });
    expect(trayIcon(tray("renew", "Renew")).displayName).toBe("CalendarClock");
    expect(trayIcon(tray("expiry", "Expiring documents")).displayName).toBe("CalendarClock");
  });
});
