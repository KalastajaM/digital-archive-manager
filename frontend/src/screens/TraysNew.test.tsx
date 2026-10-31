/** A tray, laid out as drawn: the list pane with its own header (name, count,
 * Add file, Open and Done with their counts) and rows with a second line, the item pane with
 * its own header (Move to tray…, the file's actions, Close), the fields card with Mark done,
 * then the files, checklist, note and history beside the summary and the document. */
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import type { ItemFile, TrayDef, TrayItem } from "../api/client";
import { STATUS_ON } from "../components/ai/testData";
import { mockFetch, renderWithProviders } from "../test-utils";
import Trays from "./Trays";

const FOLLOW: TrayDef = {
  id: "follow-up",
  name: "Follow up",
  order: 1,
  item_title: "{name}",
  fields: {
    check_by: { type: "date", required: false, copy: false },
    waiting_for: { type: "text", required: false, copy: false },
  },
  date_field: "check_by",
  done: { label: "Done", fields: {} },
};
const F1: ItemFile = { drive_id: "f1", path: "30. Home/20261012_Builder quote.pdf", ext: "pdf", state: "ok", in_inbox: false, connected: true, marks: [] };
const F2: ItemFile = { drive_id: "f2", path: "30. Home/20261003_Sauna drawings.pdf", ext: "pdf", state: "ok", in_inbox: false, connected: true, marks: [] };
const ITEM: TrayItem = {
  id: 1,
  tray_id: "follow-up",
  title: "Builder quote, sauna",
  fields: { check_by: "2026-10-31", waiting_for: "Revised quote from the builder" },
  date: "2026-10-31",
  state: "open",
  created: 1_760_000_000,
  done_at: null,
  done_fields: null,
  files: ["f1", "f2"],
  created_by_batch: null,
  missing_required: [],
  invalid_fields: [],
  tray_name: "Follow up",
  tray_removed: false,
  level: "soon",
  file_state: "ok",
  has_note: false,
  checklist_open: 2,
  checklist_total: 3,
  summary: null,
  first_file: F1,
};
const DONE_ONE: TrayItem = { ...ITEM, id: 2, title: "Old quote", state: "done", done_at: 1_760_100_000 };

function setup() {
  mockFetch({
    "GET /api/trays": { body: { trays: [FOLLOW], errors: [] } },
    "GET /api/trays/follow-up/items": (call) => ({ body: call.url.includes("state=done") ? [DONE_ONE, { ...DONE_ONE, id: 3 }] : [ITEM] }),
    "GET /api/items/1": { body: ITEM },
    "GET /api/items/1/files": { body: [F1, F2] },
    "GET /api/items/1/history": { body: [] },
    "GET /api/notes/item/1": { body: { text: "" } },
    "GET /api/checklist/item/1": { body: [] },
    "GET /api/ai/status": { body: STATUS_ON },
    "GET /api/files/f1/summary": { body: { ai: null, user: null } },
    "GET /api/files/f1/links": { body: { items: [], collections: [], note: "" } },
  });
  renderWithProviders(
    <MemoryRouter initialEntries={["/trays/follow-up?item=1"]}>
      <Routes>
        <Route path="/trays/:trayId?" element={<Trays today="2026-10-27" />} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => localStorage.clear());
afterEach(() => {
  cleanup();
});

describe("a tray", () => {
  it("heads the list pane with the name, the count, Add file and Open and Done with their counts", async () => {
    setup();
    const list = await screen.findByRole("region", { name: "Tray items" });
    const head = list.querySelector(".trays-toolbar") as HTMLElement;
    expect(head).not.toBeNull();
    expect(within(head).getByRole("heading", { name: "Follow up" })).toBeInTheDocument();
    expect(head).toHaveTextContent("1 open");
    expect(within(head).getByRole("button", { name: "Add file" })).toBeInTheDocument();
    expect(await within(head).findByRole("button", { name: "Open 1" })).toHaveAttribute("aria-pressed", "true");
    expect(await within(head).findByRole("button", { name: "Done 2" })).toBeInTheDocument();
  });

  it("gives each row a second line: who it waits for, its files and its checklist", async () => {
    setup();
    const row = await screen.findByRole("article", { name: "Builder quote, sauna" });
    expect(row.querySelector(".tray-row-meta")).toHaveTextContent("Waiting for: Revised quote from the builder · 2 files · Checklist 1 of 3");
  });

  it("puts Move to tray…, the file's actions and Close in the item's own header", async () => {
    setup();
    const item = await screen.findByRole("region", { name: "Item" });
    const head = await waitForHeader(item);
    expect(within(head).getByRole("button", { name: "Move to tray" })).toHaveTextContent("Move to tray…");
    expect(within(head).getByRole("button", { name: "Close" })).toBeInTheDocument();
    expect(await within(head).findByRole("button", { name: "Remove from tray" })).toBeInTheDocument();
    expect(document.querySelector(".trays-toolbar .toolbar-trailing")).toBeNull();
  });

  it("lays the item out in one column: the fields card, the files, the file panel, then checklist and note", async () => {
    setup();
    const item = await screen.findByRole("region", { name: "Item" });
    await waitForHeader(item);
    const done = await within(item).findByRole("button", { name: /^Mark done/ });
    expect(done.querySelector("kbd")).toHaveTextContent("d");
    const main = item.querySelector(".item-stack") as HTMLElement;
    const side = item.querySelector(".item-file-panel") as HTMLElement;
    const files = await within(main).findByRole("region", { name: "Files on this item" });
    expect(files.querySelectorAll(".item-file-pick")).toHaveLength(2);
    expect(within(files).getByRole("button", { name: /Builder quote\.pdf/, pressed: true })).toBeInTheDocument();
    expect(within(main).getByText("Checklist")).toBeInTheDocument();
    expect(within(main).getByText("History")).toBeInTheDocument();
    // the one file panel, for the file shown, between the files and the checklist
    const kidsOf = [...main.children];
    expect(kidsOf.indexOf(files)).toBeLessThan(kidsOf.indexOf(side));
    expect(side.compareDocumentPosition(within(main).getByText("Checklist")) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    const blocks = (await waitFor(() => {
      const found = [...side.querySelectorAll(".file-skeleton > [data-block]")].map((b) => (b as HTMLElement).dataset.block);
      if (found.length === 0) throw new Error("no file panel yet");
      return found;
    })) as string[];
    const order = ["header", "actions", "tags", "collections", "summary", "relatives", "preview", "notes"];
    expect(blocks.filter((b) => order.includes(b))).toEqual(order.filter((b) => blocks.includes(b)));
    expect(blocks.slice(0, 2)).toEqual(["header", "actions"]);
    // the shown file's relatives, folded until opened
    expect(await within(side).findByRole("button", { name: /^Relatives/, expanded: false })).toBeInTheDocument();
    // Show in folder takes the file to Browse
    expect(within(within(side).getByRole("group", { name: "Look at it" })).getByRole("button", { name: "Show in folder" })).toBeInTheDocument();
    // the file's icon row: the item's own actions (Remove from tray, Move to tray) stay in the item's header
    const filing = within(side).getByRole("group", { name: "File it" });
    expect(within(filing).queryByRole("button", { name: "Put in tray" })).toBeNull();
    expect(within(filing).queryByRole("button", { name: "Remove from tray" })).toBeNull();
    expect(within(filing).getByRole("button", { name: "Back to inbox" })).toBeInTheDocument();
    expect(within(filing).getByRole("button", { name: "Move to To Delete" })).toBeInTheDocument();
    expect(within(item.querySelector(".item-header") as HTMLElement).getByRole("button", { name: "Remove from tray" })).toBeInTheDocument();
    // the fields card comes before the column
    const kids = [...(item.querySelector(".item-detail") as HTMLElement).children].map((c) => c.className);
    expect(kids.findIndex((c) => c.includes("item-fields"))).toBeLessThan(kids.findIndex((c) => c.includes("item-stack")));
  });
});

async function waitForHeader(item: HTMLElement): Promise<HTMLElement> {
  return await waitFor(() => {
    const head = item.querySelector<HTMLElement>(".item-header");
    if (!head) throw new Error("no item header yet");
    return head;
  });
}

describe("a tray item's right-click menu", () => {
  const names = (menu: HTMLElement) =>
    Array.from(menu.querySelectorAll('[role^="menuitem"]')).map((b) => b.querySelector(".menu-item-text")?.firstChild?.textContent);

  it("opens the item it is on, then offers Mark done, Remove from tray… and the item's file", async () => {
    setup();
    const row = await screen.findByRole("article", { name: "Builder quote, sauna" });
    fireEvent.contextMenu(row, { clientX: 20, clientY: 20 });
    const menu = await screen.findByRole("menu", { name: "Actions for Builder quote, sauna" });
    expect(names(menu)).toEqual(["Mark done", "Remove from tray…", "Open file", "Show in folder", "Show in Finder"]);
    await userEvent.setup().click(within(menu).getByRole("menuitem", { name: "Remove from tray…" }));
    expect(await screen.findByRole("dialog", { name: "Remove Builder quote, sauna from Follow up?" })).toBeInTheDocument();
  });

  it("a done item offers Reopen", async () => {
    setup();
    await userEvent.setup().click(await screen.findByRole("button", { name: "Done 2" }));
    const rows = await screen.findAllByRole("article", { name: "Old quote" });
    fireEvent.contextMenu(rows[0]);
    expect(names(await screen.findByRole("menu", { name: "Actions for Old quote" }))[0]).toBe("Reopen");
  });
});
