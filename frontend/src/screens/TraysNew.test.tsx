/** A tray in the New look, laid out as drawn: the list pane with its own header (name, count,
 * Add file, Open and Done with their counts) and rows with a second line, the item pane with
 * its own header (Move to tray…, the file's actions, Close), the fields card with Mark done,
 * then the files, checklist, note and history beside the summary and the document. Classic
 * renders none of it. */
import { cleanup, screen, waitFor, within } from "@testing-library/react";
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
  delete document.documentElement.dataset.style;
});

describe("a tray in New", () => {
  it("heads the list pane with the name, the count, Add file and Open and Done with their counts", async () => {
    document.documentElement.dataset.style = "new";
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
    document.documentElement.dataset.style = "new";
    setup();
    const row = await screen.findByRole("article", { name: "Builder quote, sauna" });
    expect(row.querySelector(".tray-row-meta")).toHaveTextContent("Waiting for: Revised quote from the builder · 2 files · Checklist 1 of 3");
  });

  it("puts Move to tray…, the file's actions and Close in the item's own header", async () => {
    document.documentElement.dataset.style = "new";
    setup();
    const item = await screen.findByRole("region", { name: "Item" });
    const head = await waitForHeader(item);
    expect(within(head).getByRole("button", { name: "Move to tray" })).toHaveTextContent("Move to tray…");
    expect(within(head).getByRole("button", { name: "Close" })).toBeInTheDocument();
    expect(await within(head).findByRole("button", { name: "Remove from tray" })).toBeInTheDocument();
    expect(document.querySelector(".trays-toolbar .toolbar-trailing")).toBeNull();
  });

  it("lays the item out as the board does: the fields card, then files, checklist and note beside the summary", async () => {
    document.documentElement.dataset.style = "new";
    setup();
    const item = await screen.findByRole("region", { name: "Item" });
    await waitForHeader(item);
    const done = await within(item).findByRole("button", { name: /^Mark done/ });
    expect(done.querySelector("kbd")).toHaveTextContent("d");
    const main = item.querySelector(".item-col-main") as HTMLElement;
    const side = item.querySelector(".item-col-side") as HTMLElement;
    const files = await within(main).findByRole("region", { name: "Files on this item" });
    expect(files.querySelectorAll(".item-file-pick")).toHaveLength(2);
    expect(within(files).getByRole("button", { name: /Builder quote\.pdf/, pressed: true })).toBeInTheDocument();
    expect(within(main).getByText("Checklist")).toBeInTheDocument();
    expect(within(main).getByText("History")).toBeInTheDocument();
    expect(within(side).getByText("Summary of")).toBeInTheDocument();
    // the shown file's relatives, folded until opened
    expect(await within(side).findByRole("button", { name: /^Relatives/ })).toHaveAttribute("aria-expanded", "false");
    // the fields card comes before the two columns
    const order = [...(item.querySelector(".item-new") as HTMLElement).children].map((c) => c.className);
    expect(order.findIndex((c) => c.includes("item-fields"))).toBeLessThan(order.findIndex((c) => c.includes("item-cols")));
  });

  it("renders none of it in Classic", async () => {
    setup();
    await screen.findByRole("article", { name: "Builder quote, sauna" });
    expect(document.querySelector(".tray-row-meta")).toBeNull();
    expect(document.querySelector(".seg-count")).toBeNull();
    expect(document.querySelector(".item-new")).toBeNull();
    expect(screen.queryByRole("button", { name: /^Relatives/ })).toBeNull();
    expect(document.querySelector(".trays-list > .trays-toolbar")).toBeNull();
  });
});

async function waitForHeader(item: HTMLElement): Promise<HTMLElement> {
  return await waitFor(() => {
    const head = item.querySelector<HTMLElement>(".item-header");
    if (!head) throw new Error("no item header yet");
    return head;
  });
}
