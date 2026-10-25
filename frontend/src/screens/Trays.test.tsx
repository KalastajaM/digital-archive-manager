import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Link, MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ChecklistItem, ItemBarcode, ItemEvent, ItemFile, TrayDef, TrayItem } from "../api/client";
import { STATUS_ON } from "../components/ai/testData";
import { publishSelection } from "../selection";
import { type Call, dataTransfer, deferred, IMPORTANT_REFUSED, mockFetch, quarantineRoute, renderWithProviders, undoButton } from "../test-utils";
import Trays from "./Trays";

vi.mock("../selection", async (actual) => ({
  ...(await actual<typeof import("../selection")>()),
  publishSelection: vi.fn(),
}));

beforeEach(() => {
  vi.mocked(publishSelection).mockClear();
});

const DAY = "2026-10-19";

const TO_PAY: TrayDef = {
  id: "to-pay",
  name: "To pay",
  order: 1,
  item_title: "{name}",
  fields: {
    payee: { type: "text", required: false, prefill: "payee", copy: true },
    due_date: { type: "date", required: true, prefill: "due_date", copy: false },
    amount: { type: "money", required: false, prefill: "total", copy: true },
    iban: { type: "iban", required: false, prefill: "iban", copy: true },
    reference: { type: "reference", required: false, prefill: "reference", copy: true },
    autopay: { type: "checkbox", required: false, copy: false },
  },
  date_field: "due_date",
  done: { label: "Mark paid", fields: { paid_on: { type: "date", required: false, copy: false, default: "today" } } },
  summary: { sum: "amount" },
};
const TO_ACTION: TrayDef = {
  id: "to-action",
  name: "To action",
  order: 2,
  item_title: "{name}",
  fields: { due: { type: "date", required: false, copy: false } },
  date_field: "due",
  done: { label: "Done", fields: {} },
};
const TO_READ: TrayDef = {
  id: "to-read",
  name: "To\u200Bread",
  order: 3,
  item_title: "{name}",
  fields: {},
  date_field: null,
  done: { label: "Done", fields: {} },
};
const TRAYS = { trays: [TO_PAY, TO_ACTION, TO_READ], errors: [] };

const NORTHPOWER_FILE: ItemFile = { drive_id: "f1", path: "10. Financial/Banks/northpower.pdf", ext: "pdf", state: "ok", in_inbox: false, marks: [] };

function item(id: number, overrides: Partial<TrayItem> = {}): TrayItem {
  return {
    id,
    tray_id: "to-pay",
    title: `Item ${id}`,
    fields: {},
    date: null,
    state: "open",
    created: 1_760_000_000,
    done_at: null,
    done_fields: null,
    files: ["f1"],
    created_by_batch: null,
    missing_required: [],
    invalid_fields: [],
    tray_name: "To pay",
    tray_removed: false,
    level: null,
    file_state: "ok",
    has_note: false,
    checklist_open: 0,
    checklist_total: 0,
    summary: null,
    first_file: NORTHPOWER_FILE,
    ...overrides,
  };
}

const BILL = item(1, {
  title: "Northpower sähkö",
  fields: {
    payee: "Northpower Oy",
    due_date: "2026-10-15",
    amount: "84.20",
    iban: "FI2112345600000785",
    reference: "RF18539007547034",
  },
  date: "2026-10-15",
  level: "overdue",
  has_note: true,
  checklist_open: 2,
  checklist_total: 5,
  summary: "ai",
  files: ["f1", "f2"],
});
const LATER = item(2, {
  title: "Water\u202Ebill",
  fields: { due_date: "2026-11-30", amount: "12.00" },
  date: "2026-11-30",
  file_state: "to_delete",
  first_file: { drive_id: "f9", path: "a/b.pdf", ext: "pdf", state: "ok", in_inbox: false, marks: [] },
});
const UNDATED = item(3, { title: "Kotihoito", missing_required: ["due_date"], level: "undated", file_state: "missing" });
const PAID = item(9, {
  title: "Old bill",
  state: "done",
  done_at: Date.parse("2026-10-17T12:00:00") / 1000,
  done_fields: { paid_on: "2026-10-17" },
});

const FILES: ItemFile[] = [
  NORTHPOWER_FILE,
  { drive_id: "f2", path: "##. To Delete/receipt.png", ext: "png", state: "to_delete", in_inbox: false, marks: [] },
];
const BARCODE_CODE = "521123456000007850000842018000000000539007547034261015";
const BARCODE: ItemBarcode = {
  code: BARCODE_CODE,
  modules: [2, 1, 1, 2, 3, 1, 2],
  reason: null,
  printed: null,
  printed_fields: null,
  mismatch: [],
};
const ACTION = item(4, {
  tray_id: "to-action",
  tray_name: "To action",
  title: "Water pipe inspection",
  fields: { due: "2026-10-22" },
  date: "2026-10-22",
  level: "soon",
});
const READ = item(5, {
  tray_id: "to-read",
  tray_name: "To\u200Bread",
  title: "Sauna manual",
  created: Date.parse("2026-09-28T12:00:00") / 1000,
});
const CHECKS: ChecklistItem[] = [
  { id: 11, text: "Check meter", done: false, position: 0 },
  { id: 12, text: "Pay\u202Eit", done: true, position: 1 },
];
const HISTORY: ItemEvent[] = [
  { id: 1, at: Date.parse("2026-10-14T09:00:00") / 1000, kind: "created", data: { title: "Northpower" } },
  {
    id: 2,
    at: Date.parse("2026-10-18T09:00:00") / 1000,
    kind: "edited",
    data: { changes: { amount: ["80.00", "84.20"], title: ["Northpower", "Northpower sähkö"] } },
  },
  {
    id: 3,
    at: Date.parse("2026-10-19T09:00:00") / 1000,
    kind: "file_added",
    data: { drive_id: "f2", name: "receipt\u202E.png", path: "##. To Delete/receipt.png" },
  },
  { id: 4, at: Date.parse("2026-10-19T10:00:00") / 1000, kind: "file_removed", data: { drive_id: "f8" } },
];

function Where() {
  const location = useLocation();
  return (
    <>
      <output data-testid="where">{location.pathname + location.search}</output>
      {/* the sidebar's tray rows, as App renders them */}
      <nav aria-label="Sidebar">
        <Link to="/trays/to-read">To read in the sidebar</Link>
      </nav>
    </>
  );
}

type Routes = Parameters<typeof mockFetch>[0];

function renderTrays(path = "/trays/to-pay", routes: Routes = {}) {
  const calls = mockFetch({
    "GET /api/trays": { body: TRAYS },
    "GET /api/trays/to-pay/items": (call) => ({
      body: call.url.includes("state=done") ? [PAID] : [BILL, LATER, UNDATED],
    }),
    "GET /api/trays/to-read/items": { body: [READ] },
    "GET /api/trays/to-action/items": { body: [ACTION] },
    "GET /api/items/1": { body: BILL },
    "GET /api/items/1/barcode": { body: BARCODE },
    "GET /api/items/1/files": { body: FILES },
    "GET /api/items/1/history": { body: HISTORY },
    "GET /api/notes/item/1": { body: { text: "call first" } },
    "GET /api/checklist/item/1": { body: CHECKS },
    "GET /api/items/2": { body: LATER },
    "GET /api/items/2/files": { body: [{ drive_id: "f9", path: "a/b.pdf", ext: "pdf", state: "ok", in_inbox: false }] },
    "GET /api/items/2/barcode": { body: { ...BARCODE, code: null, modules: null, reason: "no IBAN" } },
    "GET /api/items/4": { body: ACTION },
    "GET /api/items/4/files": { body: [NORTHPOWER_FILE] },
    "GET /api/items/4/history": { body: [] },
    "GET /api/notes/item/4": { body: { text: "" } },
    "GET /api/checklist/item/4": { body: CHECKS },
    "GET /api/items/5": { body: READ },
    "GET /api/items/5/files": { body: [NORTHPOWER_FILE] },
    "GET /api/items/5/history": { body: [] },
    "GET /api/notes/item/5": { body: { text: "" } },
    "GET /api/checklist/item/5": { body: [] },
    "GET /api/items/2/history": { body: [] },
    "GET /api/notes/item/2": { body: { text: "" } },
    "GET /api/checklist/item/2": { body: [] },
    "GET /api/ai/status": { body: STATUS_ON },
    "GET /api/files/f1/summary": { body: { ai: null, user: null } },
    "GET /api/files/f2/summary": { body: { ai: null, user: null } },
    "GET /api/files/f9/summary": { body: { ai: null, user: null } },
    ...routes,
  });
  const user = userEvent.setup();
  renderWithProviders(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/trays/:trayId?" element={<Trays today={DAY} />} />
        <Route path="/inbox" element={<p>Inbox screen</p>} />
      </Routes>
      <Where />
    </MemoryRouter>,
  );
  return { calls, user };
}

const where = () => screen.getByTestId("where").textContent;
const sent = (calls: Call[], method: string, url: string) => calls.filter((c) => c.method === method && c.url === url);
const row = (title: string) => screen.getByRole("article", { name: title });
const detail = () => screen.getByRole("region", { name: "Item" });
/** Opens the header title for editing (its pencil) and returns the text field. */
const editTitle = async (user: ReturnType<typeof userEvent.setup>) => {
  await user.click(await within(await screen.findByRole("region", { name: "Item" })).findByRole("button", { name: "Edit title" }));
  return within(detail()).getByLabelText("Title");
};

describe("Add file in the tray list", () => {
  it("searches the index and puts the chosen file in the tray as a new item, which opens", async () => {
    const created = item(11, { title: "Meter reading", files: ["f7"], first_file: { ...NORTHPOWER_FILE, drive_id: "f7" } });
    const { calls, user } = renderTrays("/trays/to-pay", {
      "GET /api/search": {
        body: [
          { drive_id: "f1", path: "10. Financial/Banks/northpower.pdf", name: "northpower.pdf", snippet: "", rank: 1 },
          { drive_id: "f7", path: "10. Financial/Banks/meter.pdf", name: "meter.pdf", snippet: "", rank: 2 },
        ],
      },
      "POST /api/items/quick": { body: { created: [created], skipped: [] } },
      "GET /api/items/11": { body: created },
      "GET /api/items/11/files": { body: [] },
      "GET /api/items/11/history": { body: [] },
      "GET /api/notes/item/11": { body: { text: "" } },
      "GET /api/checklist/item/11": { body: [] },
    });
    await screen.findByRole("article", { name: "Northpower sähkö" });
    const list = screen.getByRole("region", { name: "Tray items" });
    const add = within(list).getByRole("button", { name: "Add file" });
    expect(add).toHaveAttribute("data-tip", "Add another file to the tray");
    await user.click(add);
    await user.type(within(list).getByLabelText("Find a file"), "meter");
    // a file that already has an item here (northpower.pdf) is not offered again
    expect(await within(list).findByRole("button", { name: /meter\.pdf/ })).toBeInTheDocument();
    expect(within(list).queryByRole("button", { name: /^Add northpower\.pdf/ })).not.toBeInTheDocument();
    await user.click(within(list).getByRole("button", { name: /meter\.pdf/ }));
    await waitFor(() => expect(sent(calls, "POST", "/api/items/quick")).toHaveLength(1));
    expect(sent(calls, "POST", "/api/items/quick")[0].body).toEqual({ tray: "to-pay", drive_ids: ["f7"] });
    await waitFor(() => expect(where()).toBe("/trays/to-pay?item=11"));
    expect(within(list).queryByLabelText("Find a file")).not.toBeInTheDocument();
  });
});

describe("Trays", () => {
  it("/trays (the sidebar's caption) lists the trays with their open counts, each a link", async () => {
    renderTrays("/trays", {
      "GET /api/today": {
        body: {
          overview: {
            inbox: 0,
            collections: [],
            trays: [{ tray_id: "to-pay", name: "To pay", open: 3, overdue: 1, sum: "312.70", waiting_long: 0 }],
          },
        },
      },
    });
    const list = await screen.findByRole("list", { name: "Trays" });
    expect(within(list).getAllByRole("article").map((a) => a.getAttribute("aria-label")).slice(0, 2)).toEqual(["To pay", "To action"]);
    expect(within(list).getAllByRole("article")).toHaveLength(3);
    expect(within(list).getByRole("link", { name: "To pay" })).toHaveAttribute("href", "/trays/to-pay");
    await waitFor(() => expect(within(list).getByRole("article", { name: "To pay" })).toHaveTextContent("3 open · 1 overdue · 312,70 €"));
    expect(screen.queryByRole("region", { name: "Tray items" })).not.toBeInTheDocument();
  });

  it("shows the tray named in the list toolbar; the sidebar picks the tray (no tab row)", async () => {
    const { calls } = renderTrays();
    expect(await screen.findByRole("article", { name: "Northpower sähkö" })).toBeInTheDocument();
    expect(calls.some((c) => c.url === "/api/trays/to-pay/items?state=open")).toBe(true);
    const list = screen.getByRole("region", { name: "Tray items" });
    expect(within(list).getByRole("heading", { level: 2, name: "To pay" })).toBeInTheDocument();
    expect(screen.queryByRole("navigation", { name: "Trays" })).not.toBeInTheDocument();
    expect(within(list).queryAllByRole("link", { name: /To.?read/ })).toEqual([]);
  });

  it("the tray list has a resizable splitter", async () => {
    renderTrays();
    await screen.findByRole("article", { name: "Northpower sähkö" });
    expect(screen.getByRole("separator", { name: "Resize the list" })).toHaveAttribute("aria-valuenow", "295");
  });

  it("the list toolbar has the tray's open total (Today's figure), else the open count", async () => {
    renderTrays("/trays/to-pay", {
      "GET /api/today": {
        body: {
          overview: {
            inbox: 0,
            collections: [],
            trays: [{ tray_id: "to-pay", name: "To pay", open: 3, overdue: 1, sum: "312.70", waiting_long: 0 }],
          },
        },
      },
    });
    const list = await screen.findByRole("region", { name: "Tray items" });
    await waitFor(() => expect(list.querySelector(".toolbar")).toHaveTextContent("To pay312,70 €"));
  });

  it("without Today's figures the list toolbar counts the items", async () => {
    renderTrays("/trays/to-pay");
    await screen.findByRole("article", { name: "Northpower sähkö" });
    const list = screen.getByRole("region", { name: "Tray items" });
    expect(list.querySelector(".toolbar")).toHaveTextContent("To pay3 open");
  });

  it("a row: title, payee, urgency tag, amount, file count, note and badges; copying and Done are in the bill view", async () => {
    renderTrays("/trays/to-pay");
    const bill = await screen.findByRole("article", { name: "Northpower sähkö" });
    expect(bill).toHaveClass("tray-row-overdue");
    const tag = within(bill).getByText("4 days overdue");
    expect(tag).toHaveClass("tag-red");
    expect(tag).toHaveAttribute("title", "Overdue · 15.10.2026");
    expect(bill).toHaveTextContent("Northpower Oy");
    expect(bill).toHaveTextContent("84,20 €");
    expect(bill).not.toHaveTextContent("2 files");
    expect(within(bill).getByRole("img", { name: "Note" })).toBeInTheDocument();
    expect(within(bill).getByRole("img", { name: "2 of 5 to-dos open" })).toBeInTheDocument();
    expect(within(bill).getByRole("img", { name: "AI summary" })).toBeInTheDocument();
    expect(within(bill).queryByRole("button")).not.toBeInTheDocument();
    expect(within(row("Water⟨U+202E⟩bill")).getByText("30 Nov")).toHaveClass("tag-grey");

    const later = row("Water⟨U+202E⟩bill");
    expect(later).not.toHaveClass("tray-row-overdue");
    expect(within(later).getByText("file in ##. To Delete")).toBeInTheDocument();
    expect(within(later).queryByRole("img", { name: "Note" })).not.toBeInTheDocument();
    const undated = row("Kotihoito");
    expect(within(undated).queryByText("needs a due date")).not.toBeInTheDocument();
    expect(within(undated).getByText("file missing")).toBeInTheDocument();
  });

  it("d opens the selected row's item with its done form; Enter posts done", async () => {
    const { calls, user } = renderTrays("/trays/to-pay", {
      "POST /api/items/2/done": { body: { ...LATER, state: "done" } },
    });
    await screen.findByRole("article", { name: "Northpower sähkö" });
    await user.keyboard("jj"); // the first j lands on the first row
    expect(row("Water⟨U+202E⟩bill").closest("li")).toHaveAttribute("aria-current", "true");
    // the highlighted row is the open item: the panel shows it already
    expect(where()).toBe("/trays/to-pay?item=2");
    await user.keyboard("d");
    expect(where()).toBe("/trays/to-pay?item=2");
    const form = await screen.findByRole("form", { name: "Mark paid" });
    expect(within(form).getByLabelText("Paid on")).toHaveValue(DAY);
    expect(within(form).getByLabelText("Paid on")).toHaveFocus();
    await user.keyboard("{Enter}");
    await waitFor(() => expect(sent(calls, "POST", "/api/items/2/done")).toHaveLength(1));
    expect(sent(calls, "POST", "/api/items/2/done")[0].body).toEqual({ fields: { paid_on: DAY } });
  });

  it("a highlighted row is the open item: nothing is highlighted until one is picked, then j/k open it in the panel", async () => {
    const { user } = renderTrays("/trays/to-pay");
    await screen.findByRole("article", { name: "Northpower sähkö" });
    expect(document.querySelector(".tray-items > li[aria-current]")).toBeNull();
    expect(within(detail()).getByText("No item selected")).toBeInTheDocument();
    await user.keyboard("j");
    expect(row("Northpower sähkö").closest("li")).toHaveAttribute("aria-current", "true");
    expect(where()).toBe("/trays/to-pay?item=1");
    expect(await within(detail()).findByRole("heading", { name: "Northpower sähkö" })).toBeInTheDocument();
    await user.keyboard("j");
    expect(where()).toBe("/trays/to-pay?item=2");
    expect(await within(detail()).findByRole("heading", { name: "Water⟨U+202E⟩bill" })).toBeInTheDocument();
    await user.keyboard("k");
    expect(where()).toBe("/trays/to-pay?item=1");
    // the hint strip of a bill tray names the barcode key
    expect(document.querySelector(".key-hints")).toHaveTextContent("large barcode");
  });

  it("j/k never fire while typing", async () => {
    const { user } = renderTrays("/trays/to-pay?item=1");
    await screen.findByRole("article", { name: "Northpower sähkö" });
    await editTitle(user);
    await user.keyboard("j");
    expect(row("Northpower sähkö").closest("li")).toHaveAttribute("aria-current", "true");
  });

  it("Enter opens the selected item in the panel and puts it in the URL", async () => {
    const { user } = renderTrays("/trays/to-pay");
    await screen.findByRole("article", { name: "Northpower sähkö" });
    await user.keyboard("j");
    await user.keyboard("k");
    await user.keyboard("j");
    await user.keyboard("{Enter}");
    expect(where()).toBe("/trays/to-pay?item=2");
    expect(await within(detail()).findByRole("heading", { name: "Water⟨U+202E⟩bill" })).toBeInTheDocument();
  });

  it("opens ?item= from a Today link and selects its row", async () => {
    renderTrays("/trays/to-pay?item=2");
    expect(await within(await screen.findByRole("region", { name: "Item" })).findByRole("heading", { name: "Water⟨U+202E⟩bill" })).toBeInTheDocument();
    expect(row("Water⟨U+202E⟩bill").closest("li")).toHaveAttribute("aria-current", "true");
  });

  it("the Done filter lists done items with their done date and Reopen", async () => {
    const { calls, user } = renderTrays("/trays/to-pay", {
      "POST /api/items/9/reopen": { body: { ...PAID, state: "open" } },
    });
    await screen.findByRole("article", { name: "Northpower sähkö" });
    await user.click(within(screen.getByRole("group", { name: "Show" })).getByRole("button", { name: "Done" }));
    const paid = await screen.findByRole("article", { name: "Old bill" });
    expect(where()).toBe("/trays/to-pay?state=done");
    expect(paid).toHaveTextContent("Done 2 days ago");
    expect(paid).toHaveTextContent("paid on 17.10.2026");
    expect(screen.queryByRole("article", { name: "Northpower sähkö" })).not.toBeInTheDocument();
    await user.click(within(paid).getByRole("button", { name: "Reopen" }));
    await waitFor(() => expect(sent(calls, "POST", "/api/items/9/reopen")).toHaveLength(1));

    // opening a done item keeps the filter; another tray starts on Open again
    await user.click(within(paid).getByRole("link", { name: "Old bill" }));
    expect(where()).toBe("/trays/to-pay?state=done&item=9");
    await user.click(screen.getByRole("link", { name: "To read in the sidebar" }));
    expect(where()).toBe("/trays/to-read");
    expect(within(screen.getByRole("group", { name: "Show" })).getByRole("button", { name: "Open" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("list keys are ignored while typing or with the focus in the item panel", async () => {
    const { user } = renderTrays("/trays/to-pay?item=1");
    await screen.findByRole("article", { name: "Northpower sähkö" });
    await editTitle(user);
    await user.keyboard("d");
    expect(screen.queryByRole("form", { name: "Mark paid" })).not.toBeInTheDocument();

    const check = await within(detail()).findByRole("checkbox", { name: "Check meter" });
    act(() => check.focus());
    await user.keyboard("d");
    await user.keyboard("j");
    expect(screen.queryByRole("form", { name: "Mark paid" })).not.toBeInTheDocument();
    expect(row("Northpower sähkö").closest("li")).toHaveAttribute("aria-current", "true");
  });
});

describe("Item detail", () => {
  it("saves a field on blur with a PATCH of just that field and says Saved", async () => {
    const { calls, user } = renderTrays("/trays/to-pay?item=1", {
      "PATCH /api/items/1": { body: { ...BILL, fields: { ...BILL.fields, amount: "90.00" } } },
    });
    const amount = await within(await screen.findByRole("region", { name: "Item" })).findByLabelText("Amount");
    expect(amount).toHaveValue("84,20");
    await user.clear(amount);
    await user.type(amount, "90");
    await user.tab();
    await waitFor(() => expect(sent(calls, "PATCH", "/api/items/1")).toHaveLength(1));
    expect(sent(calls, "PATCH", "/api/items/1")[0].body).toEqual({ fields: { amount: "90" } });
    expect(await within(detail()).findByText("Saved")).toBeInTheDocument();
    expect(amount).toHaveValue("90,00");
  });

  it("Enter saves the title; an unchanged field sends nothing", async () => {
    const { calls, user } = renderTrays("/trays/to-pay?item=1", {
      "PATCH /api/items/1": { body: { ...BILL, title: "Northpower oct" } },
    });
    await screen.findByRole("region", { name: "Item" });
    await user.click(await within(detail()).findByLabelText("IBAN"));
    await user.tab();
    expect(sent(calls, "PATCH", "/api/items/1")).toHaveLength(0);
    const title = await editTitle(user);
    await user.clear(title);
    await user.type(title, "Northpower oct{Enter}");
    await waitFor(() => expect(sent(calls, "PATCH", "/api/items/1")).toHaveLength(1));
    expect(sent(calls, "PATCH", "/api/items/1")[0].body).toEqual({ title: "Northpower oct" });
    await user.tab(); // the blur after Enter does not send it again
    expect(sent(calls, "PATCH", "/api/items/1")).toHaveLength(1);
    expect(await within(detail()).findByText("Saved")).toBeInTheDocument();
  });

  it("a 400 is shown at the field, which keeps the typed text", async () => {
    const { user } = renderTrays("/trays/to-pay?item=1", {
      "PATCH /api/items/1": { status: 400, body: { error: "amount: not an amount" } },
    });
    const amount = await within(await screen.findByRole("region", { name: "Item" })).findByLabelText("Amount");
    await user.clear(amount);
    await user.type(amount, "lots{Enter}");
    expect(await within(detail()).findByRole("alert")).toHaveTextContent("amount: not an amount");
    expect(amount).toHaveValue("lots");
  });

  it("one save at a time: a value committed meanwhile is sent after, and UI and server agree", async () => {
    let stored = BILL.fields.amount as string;
    const pending: Array<{ amount: string; reply: ReturnType<typeof deferred<{ body: unknown }>> }> = [];
    const { calls, user } = renderTrays("/trays/to-pay?item=1", {
      "GET /api/items/1": () => ({ body: { ...BILL, fields: { ...BILL.fields, amount: stored } } }),
      "PATCH /api/items/1": (call) => {
        const amount = `${(call.body as { fields: { amount: string } }).fields.amount}.00`;
        const reply = deferred<{ body: unknown }>();
        pending.push({ amount, reply });
        return reply.promise;
      },
    });
    const finish = async () => {
      const { amount, reply } = pending.shift()!;
      stored = amount; // what the database now holds
      await act(async () => reply.resolve({ body: { ...BILL, fields: { ...BILL.fields, amount } } }));
    };
    const amount = await within(await screen.findByRole("region", { name: "Item" })).findByLabelText("Amount");
    await user.clear(amount);
    await user.type(amount, "90{Enter}");
    await user.type(amount, "5");
    await user.tab(); // commits 905 while 90 is still in flight
    expect(sent(calls, "PATCH", "/api/items/1")).toHaveLength(1);
    await finish();
    await waitFor(() => expect(sent(calls, "PATCH", "/api/items/1")).toHaveLength(2));
    expect(sent(calls, "PATCH", "/api/items/1")[1].body).toEqual({ fields: { amount: "905" } });
    expect(within(detail()).queryByText("Saved")).not.toBeInTheDocument();
    await finish();
    expect(await within(detail()).findByText("Saved")).toBeInTheDocument();
    expect(stored).toBe("905.00");
    await waitFor(() => expect(amount).toHaveValue("905,00"));
    expect(sent(calls, "PATCH", "/api/items/1")).toHaveLength(2);
  });

  it("a checkbox clicked twice quickly sends two requests, one after the other", async () => {
    const replies: Array<ReturnType<typeof deferred<{ body: unknown }>>> = [];
    const { calls, user } = renderTrays("/trays/to-pay?item=1", {
      "PATCH /api/items/1": () => {
        const reply = deferred<{ body: unknown }>();
        replies.push(reply);
        return reply.promise;
      },
    });
    const box = await within(await screen.findByRole("region", { name: "Item" })).findByLabelText("Autopay");
    await user.click(box);
    await user.click(box);
    expect(sent(calls, "PATCH", "/api/items/1").map((c) => c.body)).toEqual([{ fields: { autopay: true } }]);
    await act(async () => replies[0].resolve({ body: { ...BILL, fields: { ...BILL.fields, autopay: true } } }));
    await waitFor(() => expect(sent(calls, "PATCH", "/api/items/1")).toHaveLength(2));
    expect(sent(calls, "PATCH", "/api/items/1")[1].body).toEqual({ fields: { autopay: false } });
    await act(async () => replies[1].resolve({ body: { ...BILL, fields: { ...BILL.fields, autopay: false } } }));
    expect(await within(detail()).findByText("Saved")).toBeInTheDocument();
    expect(box).not.toBeChecked();
    expect(sent(calls, "PATCH", "/api/items/1")).toHaveLength(2);
  });

  it("switching items with a save in flight leaves the new item alone", async () => {
    const slow = deferred<{ body: unknown }>();
    const { calls, user } = renderTrays("/trays/to-pay?item=1", { "PATCH /api/items/1": () => slow.promise });
    const amount = await within(await screen.findByRole("region", { name: "Item" })).findByLabelText("Amount");
    await user.clear(amount);
    await user.type(amount, "90{Enter}");
    await user.click(within(row("Water⟨U+202E⟩bill")).getByRole("link", { name: "Water⟨U+202E⟩bill" }));
    expect(await within(detail()).findByRole("heading", { name: "Water⟨U+202E⟩bill" })).toBeInTheDocument();
    await act(async () => slow.resolve({ body: { ...BILL, fields: { ...BILL.fields, amount: "90.00" } } }));
    expect(within(detail()).getByLabelText("Amount")).toHaveValue("12,00");
    expect(within(detail()).queryByText("Saved")).not.toBeInTheDocument();
    expect(calls.filter((c) => c.method !== "GET" && c.url !== "/api/items/1")).toEqual([]);
  });

  it("a slow PATCH response never overwrites newer typing", async () => {
    const slow = deferred<{ body: unknown }>();
    const { user } = renderTrays("/trays/to-pay?item=1", { "PATCH /api/items/1": () => slow.promise });
    const amount = await within(await screen.findByRole("region", { name: "Item" })).findByLabelText("Amount");
    await user.clear(amount);
    await user.type(amount, "90{Enter}");
    await user.type(amount, "5");
    await act(async () => slow.resolve({ body: { ...BILL, fields: { ...BILL.fields, amount: "90.00" } } }));
    expect(amount).toHaveValue("905");
  });

  it("shows the files with tabs and badges; the × on a tab takes the file off (Undo puts it back in place) and Add another file… posts", async () => {
    const { calls, user } = renderTrays("/trays/to-pay?item=1", {
      "GET /api/search": {
        body: [
          { drive_id: "f1", path: "10. Financial/Banks/northpower.pdf", name: "northpower.pdf", snippet: "", rank: 1 },
          { drive_id: "f7", path: "10. Financial/Banks/meter.pdf", name: "meter.pdf", snippet: "", rank: 2 },
        ],
      },
      "POST /api/items/1/files": { body: { ...BILL, files: ["f1", "f2", "f7"] } },
      "POST /api/items/1/files/remove": { body: { ...BILL, files: ["f1"] } },
    });
    const panel = await screen.findByRole("region", { name: "Item" });
    const tabs = await within(panel).findByRole("tablist", { name: "Files" });
    expect(within(tabs).getAllByRole("tab").map((t) => t.textContent)).toEqual(["northpower.pdf", "receipt.pngfile in ##. To Delete"]);
    expect(within(panel).getByText("file in ##. To Delete")).toBeInTheDocument();
    await user.click(within(tabs).getByRole("tab", { name: /receipt\.png/ }));
    // the old icon in the action row is gone: the × on each tab replaces it
    expect(within(panel).queryByRole("button", { name: /^Take this file off the item/ })).not.toBeInTheDocument();
    const takeOff = within(tabs).getByRole("button", { name: "Remove receipt.png from this item" });
    expect(within(tabs).getByRole("button", { name: "Remove northpower.pdf from this item" })).toBeInTheDocument();
    expect(takeOff).toHaveAttribute("data-tip", "Take this file off the item (the file stays where it is)");
    takeOff.focus(); // reachable by keyboard
    await user.keyboard("{Enter}");
    await waitFor(() => expect(sent(calls, "POST", "/api/items/1/files/remove")).toHaveLength(1));
    expect(sent(calls, "POST", "/api/items/1/files/remove")[0].body).toEqual({ drive_id: "f2" });
    // the toast's Undo adds the file back
    expect(await screen.findByText("Taken off the item: receipt.png")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Undo" }));
    await waitFor(() => expect(sent(calls, "POST", "/api/items/1/files")).toHaveLength(1));
    expect(sent(calls, "POST", "/api/items/1/files")[0].body).toEqual({ drive_id: "f2", position: 1 });

    const attach = within(panel).getByRole("button", { name: "Add another file…" });
    expect(attach).toHaveAttribute("data-tip", expect.stringContaining("Attach another file to this item"));
    await user.click(attach);
    await user.type(within(panel).getByLabelText("Find a file"), "meter");
    const add = await within(panel).findByRole("button", { name: /meter\.pdf/ });
    expect(within(panel).queryByRole("button", { name: /^Add northpower\.pdf/ })).not.toBeInTheDocument();
    await user.click(add);
    await waitFor(() => expect(sent(calls, "POST", "/api/items/1/files")).toHaveLength(2));
    expect(sent(calls, "POST", "/api/items/1/files")[1].body).toEqual({ drive_id: "f7" });
  });

  it("the item's file tabs and Add another file… hits show ★ / !; the toggles are in the shown file's toolbar", async () => {
    const { user } = renderTrays("/trays/to-pay?item=1", {
      "GET /api/items/1/files": { body: [{ ...FILES[0], marks: ["important"] }, FILES[1]] },
      "GET /api/search": {
        body: [{ drive_id: "f7", path: "10. Financial/Banks/meter.pdf", name: "meter.pdf", snippet: "", rank: 2, marks: ["starred"] }],
      },
    });
    const panel = await screen.findByRole("region", { name: "Item" });
    const tabs = await within(panel).findByRole("tablist", { name: "Files" });
    expect(within(within(tabs).getAllByRole("tab")[0]).getByRole("img", { name: "Important" })).toBeInTheDocument();
    // the toggle is in the toolbar of the shown file's preview
    expect(within(panel).getByRole("button", { name: "Unmark Important" })).toBeInTheDocument();
    await user.click(within(panel).getByRole("button", { name: "Add another file…" }));
    await user.type(within(panel).getByLabelText("Find a file"), "meter");
    const hit = (await within(panel).findByRole("button", { name: /meter\.pdf/ })).closest("li")!;
    expect(within(hit).getByRole("img", { name: "Starred" })).toBeInTheDocument();
  });

  it("checklist: Enter adds, the checkbox toggles, inline edit, reorder (keys and drag) and delete go to the API", async () => {
    const { calls, user } = renderTrays("/trays/to-pay?item=1", {
      "POST /api/checklist/item/1": { body: { id: 13, text: "Photo", done: false, position: 2 } },
      "PATCH /api/checklist/11": { status: 204, body: null },
      "POST /api/checklist/11/move": { status: 204, body: null },
      "POST /api/checklist/12/remove": { status: 204, body: null },
      "POST /api/checklist/12/move": { status: 204, body: null },
    });
    const list = await within(await screen.findByRole("region", { name: "Item" })).findByRole("region", {
      name: "Checklist",
    });
    await within(list).findByText("Check meter");
    expect(within(list).getByText("Pay⟨U+202E⟩it")).toBeInTheDocument();
    await user.type(within(list).getByLabelText("Add to checklist"), "Photo{Enter}");
    await waitFor(() => expect(sent(calls, "POST", "/api/checklist/item/1")).toHaveLength(1));
    expect(sent(calls, "POST", "/api/checklist/item/1")[0].body).toEqual({ text: "Photo" });

    await user.click(within(list).getByRole("checkbox", { name: "Check meter" }));
    await waitFor(() => expect(sent(calls, "PATCH", "/api/checklist/11")).toHaveLength(1));
    expect(sent(calls, "PATCH", "/api/checklist/11")[0].body).toEqual({ done: true });

    // reorder: Option-Down on the focused row, and a drop on another row
    const text = within(list).getByRole("button", { name: "Check meter" });
    text.focus();
    await user.keyboard("{Alt>}{ArrowDown}{/Alt}");
    await waitFor(() => expect(sent(calls, "POST", "/api/checklist/11/move")).toHaveLength(1));
    expect(sent(calls, "POST", "/api/checklist/11/move")[0].body).toEqual({ position: 1 });
    expect(await within(list).findByRole("status")).toHaveTextContent("moved to position 2");
    const rows = within(list).getAllByRole("listitem");
    const dt = { setData: vi.fn(), effectAllowed: "", dropEffect: "" };
    fireEvent.dragStart(rows[1], { dataTransfer: dt });
    fireEvent.dragOver(rows[0], { dataTransfer: dt });
    fireEvent.drop(rows[0], { dataTransfer: dt });
    await waitFor(() => expect(sent(calls, "POST", "/api/checklist/12/move")).toHaveLength(1));
    expect(sent(calls, "POST", "/api/checklist/12/move")[0].body).toEqual({ position: 0 });
    expect(within(list).queryByRole("button", { name: /Move .* (up|down)/ })).not.toBeInTheDocument();

    await user.click(within(list).getByRole("button", { name: "Delete Pay⟨U+202E⟩it" }));
    await waitFor(() => expect(sent(calls, "POST", "/api/checklist/12/remove")).toHaveLength(1));

    // click the text to edit: Esc cancels, Enter saves
    await user.click(within(list).getByRole("button", { name: "Check meter" }));
    await user.keyboard("{Escape}");
    expect(within(list).queryByLabelText("Edit checklist entry")).not.toBeInTheDocument();
    expect(sent(calls, "PATCH", "/api/checklist/11")).toHaveLength(1);
    await user.click(within(list).getByRole("button", { name: "Check meter" }));
    const edit = within(list).getByLabelText("Edit checklist entry");
    await user.clear(edit);
    await user.type(edit, "Read meter{Enter}");
    await waitFor(() => expect(sent(calls, "PATCH", "/api/checklist/11")).toHaveLength(2));
    expect(sent(calls, "PATCH", "/api/checklist/11")[1].body).toEqual({ text: "Read meter" });
  });

  it("Move to tray moves the item (same item), follows it to the other tray and Undo moves it back", async () => {
    const { calls, user } = renderTrays("/trays/to-pay?item=1", {
      "POST /api/items/1/move": { body: { ...BILL, tray_id: "to-action", tray_name: "To action" } },
      "POST /api/items/1/undo-move": { body: BILL },
    });
    await screen.findByRole("region", { name: "Checklist" });
    await user.click(await within(detail()).findByRole("button", { name: "Move to tray" }));
    const menu = await screen.findByRole("menu", { name: "Move to tray" });
    expect(within(menu).queryByRole("menuitem", { name: "To pay" })).not.toBeInTheDocument();
    await user.click(within(menu).getByRole("menuitem", { name: "To action" }));
    await waitFor(() => expect(sent(calls, "POST", "/api/items/1/move")).toHaveLength(1));
    expect(sent(calls, "POST", "/api/items/1/move")[0].body).toEqual({ tray: "to-action" });
    await waitFor(() => expect(where()).toBe("/trays/to-action?item=1"));
    await user.click(await screen.findByRole("button", { name: "Undo" }));
    await waitFor(() => expect(sent(calls, "POST", "/api/items/1/undo-move")).toHaveLength(1));
    await waitFor(() => expect(where()).toBe("/trays/to-pay?item=1"));
  });

  it("Move to tray and Remove from tray are icons in the action row, with the date and Mark paid; Quick Look is in the preview toolbar", async () => {
    renderTrays("/trays/to-pay?item=1");
    await screen.findByRole("region", { name: "Checklist" });
    const group = await within(detail()).findByRole("group", { name: "This item" });
    expect(within(group).getAllByRole("button").map((b) => b.getAttribute("aria-label"))).toEqual([
      "Move to tray",
      "Remove from tray",
    ]);
    const row = detail().querySelector(".item-fields") as HTMLElement;
    expect(row).toContainElement(group);
    expect(row).toContainElement(within(detail()).getByRole("button", { name: "Mark paid" }));
    expect(within(detail().querySelector(".item-header") as HTMLElement).queryByRole("button", { name: "Quick Look" })).toBeNull();
  });

  it("Remove from tray asks first, then deletes the item and closes the panel; Cancel does nothing", async () => {
    const { calls, user } = renderTrays("/trays/to-pay?item=1", {
      "POST /api/items/1/remove": { status: 204, body: null },
    });
    await screen.findByRole("region", { name: "Checklist" });
    await user.click(await within(detail()).findByRole("button", { name: "Remove from tray" }));
    let dialog = await screen.findByRole("dialog", { name: /^Remove .* from To pay\?/ });
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(sent(calls, "POST", "/api/items/1/remove")).toHaveLength(0);
    await user.click(await within(detail()).findByRole("button", { name: "Remove from tray" }));
    dialog = await screen.findByRole("dialog", { name: /^Remove .* from To pay\?/ });
    await user.click(within(dialog).getByRole("button", { name: "Remove from tray" }));
    await waitFor(() => expect(sent(calls, "POST", "/api/items/1/remove")).toHaveLength(1));
    await waitFor(() => expect(where()).toBe("/trays/to-pay"));
  });

  it("Backspace on the selected row asks to remove it from the tray", async () => {
    const { calls, user } = renderTrays("/trays/to-pay?item=1", {
      "POST /api/items/1/remove": { status: 204, body: null },
    });
    await screen.findByRole("article", { name: "Northpower sähkö" });
    await user.keyboard("{Backspace}");
    const dialog = await screen.findByRole("dialog", { name: /^Remove .* from To pay\?/ });
    await user.click(within(dialog).getByRole("button", { name: "Remove from tray" }));
    await waitFor(() => expect(sent(calls, "POST", "/api/items/1/remove")).toHaveLength(1));
  });

  it("renders the history with relative dates and changed values", async () => {
    renderTrays("/trays/to-pay?item=1");
    const history = await within(await screen.findByRole("region", { name: "Item" })).findByRole("region", {
      name: "History",
    });
    const entries = await within(history).findAllByRole("listitem");
    expect(entries).toHaveLength(4);
    expect(entries[0]).toHaveTextContent("Created");
    expect(entries[0]).toHaveTextContent("5 days ago");
    expect(entries[1]).toHaveTextContent("amount 80,00 € → 84,20 €");
    expect(entries[1]).toHaveTextContent("title Northpower → Northpower sähkö");
    expect(entries[1]).toHaveTextContent("yesterday");
    expect(entries[2]).toHaveTextContent("File added: receipt⟨U+202E⟩.png");
    expect(entries[3]).toHaveTextContent("File removed: a file no longer on this item");
  });

  it("saves the note on blur", async () => {
    const { calls, user } = renderTrays("/trays/to-pay?item=1", {
      "PUT /api/notes/item/1": { body: { text: "call first, then pay" } },
    });
    const note = await within(await screen.findByRole("region", { name: "Item" })).findByLabelText("Note (optional)");
    await waitFor(() => expect(note).toHaveValue("call first"));
    await user.type(note, ", then pay");
    fireEvent.blur(note);
    await waitFor(() => expect(sent(calls, "PUT", "/api/notes/item/1")).toHaveLength(1));
    expect(sent(calls, "PUT", "/api/notes/item/1")[0].body).toEqual({ text: "call first, then pay" });
  });

  it("Mark paid in the panel opens the done form there; Enter posts done", async () => {
    const { calls, user } = renderTrays("/trays/to-pay?item=1", {
      "POST /api/items/1/done": { body: { ...BILL, state: "done" } },
    });
    const panel = await screen.findByRole("region", { name: "Item" });
    await user.click(await within(panel).findByRole("button", { name: "Mark paid" }));
    const form = screen.getByRole("form", { name: "Mark paid" });
    expect(within(form).getByLabelText("Paid on")).toHaveFocus();
    expect(within(row("Northpower sähkö")).queryByRole("form")).not.toBeInTheDocument();
    await user.keyboard("{Enter}");
    await waitFor(() => expect(sent(calls, "POST", "/api/items/1/done")).toHaveLength(1));
    expect(sent(calls, "POST", "/api/items/1/done")[0].body).toEqual({ fields: { paid_on: DAY } });
  });

  describe("the done confirm is a popover on its button", () => {
    const openIt = async () => {
      const r = renderTrays("/trays/to-pay?item=1", {
        "POST /api/items/1/done": { body: { ...BILL, state: "done" } },
      });
      const panel = await screen.findByRole("region", { name: "Item" });
      const button = await within(panel).findByRole("button", { name: "Mark paid" });
      await r.user.click(button);
      return { ...r, panel, button };
    };

    it("opens outside the page flow, the button stays and says it is expanded", async () => {
      const { panel, button } = await openIt();
      const pop = screen.getByRole("dialog", { name: "Mark paid" });
      expect(panel).not.toContainElement(pop);
      expect(pop.closest(".popover")).toHaveClass("popover-fixed");
      expect(within(pop).getByRole("form", { name: "Mark paid" })).toBeInTheDocument();
      expect(button).toHaveAttribute("aria-expanded", "true");
    });

    it("Enter confirms", async () => {
      const { calls, user } = await openIt();
      await user.keyboard("{Enter}");
      await waitFor(() => expect(sent(calls, "POST", "/api/items/1/done")).toHaveLength(1));
    });

    it("Cancel closes it and the focus returns to the button", async () => {
      const { user, button } = await openIt();
      await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Cancel" }));
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
      expect(button).toHaveFocus();
    });

    it("Esc closes it and the focus returns to the button", async () => {
      const { user, button, calls } = await openIt();
      await user.keyboard("{Escape}");
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
      expect(button).toHaveFocus();
      expect(sent(calls, "POST", "/api/items/1/done")).toHaveLength(0);
    });

    it("a click outside closes it without marking done", async () => {
      const { user, calls } = await openIt();
      await user.click(row("Water⟨U+202E⟩bill"));
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
      expect(sent(calls, "POST", "/api/items/1/done")).toHaveLength(0);
    });

    it("pressing the button again closes it", async () => {
      const { user, button } = await openIt();
      await user.click(button);
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });
  });

  it("the list header has two rows: the name with its count, then Add file and Open / Done at the right", async () => {
    renderTrays("/trays/to-pay");
    await screen.findByRole("article", { name: "Northpower sähkö" });
    const header = screen.getByRole("region", { name: "Tray items" }).querySelector("header.toolbar") as HTMLElement;
    expect(header).toHaveClass("toolbar-stacked");
    const heading = within(header).getByRole("heading", { name: "To pay" });
    expect(heading).toHaveAttribute("title", "To pay");
    expect(header.querySelector(".toolbar-title")).toContainElement(heading);
    expect(header.querySelector(".toolbar-subtitle")?.textContent).toMatch(/\S/);
    const actions = within(header).getByRole("toolbar");
    expect(header.querySelector(".toolbar-title")).not.toContainElement(actions);
    expect(within(actions).getByRole("button", { name: "Add file" })).toBeInTheDocument();
    expect(within(actions).getByRole("button", { name: "Done" })).toBeInTheDocument();
  });

  it("a done item in the panel shows its done date and Reopen", async () => {
    const { calls, user } = renderTrays("/trays/to-pay?item=9", {
      "GET /api/items/9": { body: PAID },
      "GET /api/items/9/files": { body: [] },
      "GET /api/items/9/history": { body: [] },
      "GET /api/notes/item/9": { body: { text: "" } },
      "GET /api/checklist/item/9": { body: [] },
      "POST /api/items/9/reopen": { body: { ...PAID, state: "open" } },
    });
    const panel = await screen.findByRole("region", { name: "Item" });
    await waitFor(() => expect(panel).toHaveTextContent("Done 2 days ago · paid on 17.10.2026"));
    // Paid: no barcode to scan any more.
    expect(within(panel).queryByText(/Scan it with your banking app/)).not.toBeInTheDocument();
    expect(calls.some((c) => c.url === "/api/items/9/barcode")).toBe(false);
    await user.click(within(panel).getByRole("button", { name: "Reopen" }));
    await waitFor(() => expect(sent(calls, "POST", "/api/items/9/reopen")).toHaveLength(1));
  });
});

describe("Bill view", () => {
  it("has the title, a big amount, the summary box (with a file selector) and the file name", async () => {
    const { user } = renderTrays("/trays/to-pay?item=1", {
      "GET /api/files/f2/summary": {
        body: { ai: { summary: "A receipt", key_facts: [], outdated: false }, user: null },
      },
    });
    const panel = await screen.findByRole("region", { name: "Item" });
    expect(await within(panel).findByRole("heading", { level: 2, name: "Northpower sähkö" })).toBeInTheDocument();
    expect(panel.querySelector(".bill-amount")).toHaveTextContent("84,20 €");
    const summary = await within(panel).findByRole("region", { name: "Summary" });
    expect(await within(summary).findByText("No summary yet.")).toBeInTheDocument();
    expect(await within(summary).findByRole("button", { name: "Summarize with AI…" })).toBeInTheDocument();
    // two files: the first is summarized, the selector picks another
    const select = within(panel).getByLabelText("Summary of");
    expect(select).toHaveValue("f1");
    await user.selectOptions(select, "f2");
    expect(await within(panel).findByText("A receipt")).toBeInTheDocument();
    await waitFor(() => expect(panel.querySelector(".item-sub .item-file")).toHaveTextContent("northpower.pdf"));
  });

  it("an item with no file has no AI button", async () => {
    renderTrays("/trays/to-pay?item=9", {
      "GET /api/items/9": { body: PAID },
      "GET /api/items/9/files": { body: [] },
      "GET /api/items/9/history": { body: [] },
      "GET /api/notes/item/9": { body: { text: "" } },
      "GET /api/checklist/item/9": { body: [] },
    });
    const panel = await screen.findByRole("region", { name: "Item" });
    expect(await within(panel).findByText("No file to summarize.")).toBeInTheDocument();
    expect(within(panel).queryByRole("button", { name: "Summarize with AI…" })).not.toBeInTheDocument();
  });

  it("copy rows: payee, IBAN, reference, amount and due date (with its urgency tag), each copying the raw value", async () => {
    const { user } = renderTrays("/trays/to-pay?item=1");
    const facts = await within(await screen.findByRole("region", { name: "Item" })).findByRole("list", {
      name: "Payment details",
    });
    const rows = within(facts).getAllByRole("listitem");
    expect(rows.map((r) => r.querySelector(".fact-label")?.textContent)).toEqual([
      "Payee",
      "IBAN",
      "Reference",
      "Amount",
      "Due date",
    ]);
    expect(rows[1]).toHaveTextContent("FI21 1234 5600 0007 85");
    expect(rows[2]).toHaveTextContent("RF18 5390 0754 7034");
    expect(within(rows[4]).getByText("4 days overdue")).toHaveClass("tag-red");
    const copied: Record<string, string> = {};
    for (const [label, name] of [
      ["Payee", "payee"],
      ["IBAN", "IBAN"],
      ["Reference", "reference"],
      ["Amount", "amount"],
      ["Due date", "due date"],
    ]) {
      await user.click(within(facts).getByRole("button", { name: `Copy ${name}` }));
      copied[label] = await navigator.clipboard.readText();
    }
    expect(copied).toEqual({
      Payee: "Northpower Oy",
      IBAN: "FI2112345600000785",
      Reference: "RF18539007547034",
      Amount: "84,20",
      "Due date": "15.10.2026",
    });
  });

  it("an empty value has no Copy button", async () => {
    renderTrays("/trays/to-pay?item=1", {
      "GET /api/items/1": { body: { ...BILL, fields: { ...BILL.fields, payee: undefined } } },
    });
    const facts = await within(await screen.findByRole("region", { name: "Item" })).findByRole("list", {
      name: "Payment details",
    });
    expect(within(facts).getAllByRole("listitem")[0]).toHaveTextContent("Payee—");
    expect(within(facts).queryByRole("button", { name: "Copy payee" })).not.toBeInTheDocument();
  });

  it("draws the item's bank barcode", async () => {
    renderTrays("/trays/to-pay?item=1");
    const panel = await screen.findByRole("region", { name: "Item" });
    const svg = await within(panel).findByRole("img", { name: /^Bank barcode/ });
    expect(svg.querySelectorAll("rect")).toHaveLength(4);
    expect(within(panel).getByText(BARCODE_CODE)).toBeInTheDocument();
  });

  it("has no Note button (the note is on the page), and every action button has a tooltip", async () => {
    renderTrays("/trays/to-pay?item=1", {
      "GET /api/items/1/files": { body: [{ ...NORTHPOWER_FILE, drive_id: "i1", path: "##. Organize/x.pdf", in_inbox: true }] },
    });
    const panel = await screen.findByRole("region", { name: "Item" });
    const done = await within(panel).findByRole("button", { name: "Mark paid" });
    expect(within(panel).queryByRole("button", { name: "Note" })).not.toBeInTheDocument();
    expect(done).toHaveAttribute("data-tip", "Mark this item done; it moves to the Done list");
    expect(await within(panel).findByRole("button", { name: "Mark paid and file…" })).toHaveAttribute(
      "data-tip",
      "Mark this item done, then open its file in the Inbox to file it",
    );
  });

  it("Mark done is the default label; Done and file… is offered only while a file is in the inbox", async () => {
    renderTrays("/trays/to-action?item=4");
    const panel = await screen.findByRole("region", { name: "Item" });
    await within(panel).findByRole("button", { name: "Mark done" });
    expect(within(panel).queryByRole("button", { name: /and file/ })).not.toBeInTheDocument();
  });

  it("the selected file's actions are on the action row: Ask AI, Move to To Delete (the × is on the file tabs)", async () => {
    renderTrays("/trays/to-pay?item=1");
    const panel = await screen.findByRole("region", { name: "Item" });
    const mine = await within(panel).findByRole("group", { name: "This file" });
    expect(within(mine).getByRole("button", { name: "Ask AI" })).toBeInTheDocument();
    expect(within(mine).getByRole("button", { name: "Move to To Delete" })).toBeInTheDocument();
    expect(within(mine).queryByRole("button", { name: /^Take this file off the item/ })).not.toBeInTheDocument();
    // the done buttons sit in the fields row at the top, not on the action row
    expect(mine.closest(".item-actions")).not.toContainElement(within(panel).getByRole("button", { name: "Mark paid" }));
    const top = mine.closest(".item-fields") as HTMLElement;
    expect(within(top).getByRole("button", { name: "Mark paid" })).toBeInTheDocument();
  });

  it("Mark paid and file…: done, then the inbox with the file selected when it is still in the inbox", async () => {
    const { calls, user } = renderTrays("/trays/to-pay?item=1", {
      "POST /api/items/1/done": { body: { ...BILL, state: "done" } },
      "GET /api/items/1/files": { body: [FILES[1], { ...NORTHPOWER_FILE, drive_id: "i1", path: "##. Organize/x.pdf", in_inbox: true }] },
    });
    const panel = await screen.findByRole("region", { name: "Item" });
    await user.click(await within(panel).findByRole("button", { name: "Mark paid and file…" }));
    const form = screen.getByRole("form", { name: "Mark paid" });
    await user.click(within(form).getByRole("button", { name: "Mark paid and file…" }));
    await waitFor(() => expect(where()).toBe("/inbox?file=i1"));
    expect(sent(calls, "POST", "/api/items/1/done")).toHaveLength(1);
    expect(screen.getByText("Inbox screen")).toBeInTheDocument();
  });

  it("Mark paid and file… is not offered when no file of the item is in the inbox", async () => {
    renderTrays("/trays/to-pay?item=1");
    const panel = await screen.findByRole("region", { name: "Item" });
    await within(panel).findByRole("button", { name: "Mark paid" });
    expect(within(panel).queryByRole("button", { name: "Mark paid and file…" })).not.toBeInTheDocument();
  });

  it("a non-bill tray has no payment details or barcode", async () => {
    const { calls } = renderTrays("/trays/to-action?item=4");
    const panel = await screen.findByRole("region", { name: "Item" });
    await within(panel).findByRole("heading", { name: "Water pipe inspection" });
    expect(within(panel).queryByRole("list", { name: "Payment details" })).not.toBeInTheDocument();
    expect(calls.some((c) => c.url.endsWith("/barcode"))).toBe(false);
  });
});

describe("To action and To read", () => {
  it("To action shows its title and date fields first, then the summary, with the date and checklist up top", async () => {
    renderTrays("/trays/to-action?item=4");
    const panel = await screen.findByRole("region", { name: "Item" });
    const date = await within(panel).findByLabelText(/^Due/);
    // the date field (tag right after the input) and Mark done share one row; no separate read-only date line
    const row = date.closest(".item-fields") as HTMLElement;
    expect(row).not.toBeNull();
    expect(date).toHaveValue("2026-10-22");
    expect(within(row).queryByLabelText("Title")).not.toBeInTheDocument();
    const tag = within(row).getByText("in 3 days");
    expect(tag).toHaveClass("tag-orange");
    expect(date.nextElementSibling).toBe(tag);
    const mark = within(row).getByRole("button", { name: "Mark done" });
    expect(mark.closest(".item-actions")).toBeNull();
    // keyboard order: the fields, then the done buttons
    expect(date.compareDocumentPosition(mark) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(panel.querySelector(".item-when")).toBeNull();
    expect(within(panel).queryByRole("group", { name: "Due" })).not.toBeInTheDocument();
    const checklist = await within(panel).findByRole("region", { name: "Checklist" });
    const title = within(panel).getByRole("heading", { name: "Water pipe inspection" });
    // the title and date come before the summary and the checklist
    expect(title.compareDocumentPosition(checklist) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    const summary = within(panel).getByRole("region", { name: "Summary" });
    expect(title.compareDocumentPosition(summary) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(await within(checklist).findByText("Check meter")).toBeInTheDocument();
  });

  it("To read shows how long it has waited, in the row and the panel", async () => {
    renderTrays("/trays/to-read?item=5");
    const sauna = await screen.findByRole("article", { name: "Sauna manual" });
    expect(sauna).toHaveTextContent("3 weeks");
    const panel = screen.getByRole("region", { name: "Item" });
    expect(await within(panel).findByText("Waiting 3 weeks")).toBeInTheDocument();
  });

  it("To read: Mark done is in the fields row with the title, not on the action row", async () => {
    renderTrays("/trays/to-read?item=5");
    const panel = await screen.findByRole("region", { name: "Item" });
    const mark = await within(panel).findByRole("button", { name: "Mark done" });
    const row = mark.closest(".item-fields") as HTMLElement;
    expect(row).toContainElement(mark);
    expect(mark.closest(".item-actions")).toBeNull();
  });
});

describe("Quick Look and the selection in a tray", () => {
  const quickLook = () => screen.queryByRole("dialog", { name: /^Quick Look/ });

  it("Space opens Quick Look on the selected row's file; → opens the next item", async () => {
    const { user } = renderTrays("/trays/to-pay");
    await screen.findByRole("article", { name: "Northpower sähkö" });
    expect(row("Northpower sähkö").closest("[data-quicklook]")).not.toBeNull();
    await user.keyboard(" ");
    expect(quickLook()).toHaveAccessibleName("Quick Look: northpower.pdf");
    await user.keyboard("{ArrowRight}");
    expect(quickLook()).toHaveAccessibleName("Quick Look: b.pdf");
    expect(where()).toBe("/trays/to-pay?item=2");
    await user.keyboard("{Escape}");
    expect(quickLook()).toBeNull();
    expect(row("Water⟨U+202E⟩bill").closest("li")).toHaveAttribute("aria-current", "true");
  });

  it("Space on a focused row link opens Quick Look too", async () => {
    const { user } = renderTrays("/trays/to-pay");
    const link = within(await screen.findByRole("article", { name: "Northpower sähkö" })).getByRole("link");
    act(() => link.focus());
    await user.keyboard(" ");
    expect(quickLook()).toHaveAccessibleName("Quick Look: northpower.pdf");
  });

  it("the file preview toolbar has the Quick Look eye with its tooltip, not a text link or a key hint", async () => {
    const { user } = renderTrays("/trays/to-pay?item=1");
    const eye = await screen.findByRole("button", { name: "Quick Look" });
    expect(eye.closest(".preview-tools, .zoom-controls")).not.toBeNull();
    expect(eye.closest(".item-actions")).toBeNull();
    expect(eye).toHaveClass("icon-button");
    expect(eye).toHaveAttribute("data-tip", "Quick Look Space");
    expect(document.querySelector(".item-header kbd")).toBeNull();
    expect(screen.queryByText("Quick Look", { selector: ".link-button" })).toBeNull();
    await user.click(eye);
    expect(quickLook()).toHaveAccessibleName("Quick Look: northpower.pdf");
  });

  it("publishes the selected row's first file for the viewer window", async () => {
    const { user } = renderTrays("/trays/to-pay");
    await screen.findByRole("article", { name: "Northpower sähkö" });
    await waitFor(() => expect(publishSelection).toHaveBeenLastCalledWith("f1"));
    await user.keyboard("jj");
    await waitFor(() => expect(publishSelection).toHaveBeenLastCalledWith("f9"));
  });
});

describe("Review fixes", () => {
  it("hides the barcode while it is rebuilt after a field change, then shows the new one", async () => {
    let reply: ReturnType<typeof deferred<{ body: unknown }>> | null = null;
    const { user } = renderTrays("/trays/to-pay?item=1", {
      "GET /api/items/1/barcode": () => {
        if (reply === null) return { body: BARCODE }; // the first load
        return reply.promise;
      },
      "PATCH /api/items/1": { body: { ...BILL, fields: { ...BILL.fields, amount: "90.00" } } },
    });
    const panel = await screen.findByRole("region", { name: "Item" });
    await within(panel).findByRole("img", { name: /^Bank barcode/ });
    reply = deferred<{ body: unknown }>();
    const amount = within(panel).getByLabelText("Amount");
    await user.clear(amount);
    await user.type(amount, "90{Enter}");
    expect(await within(panel).findByText("Updating…")).toBeInTheDocument();
    expect(within(panel).queryByRole("img", { name: /^Bank barcode/ })).not.toBeInTheDocument();
    expect(within(panel).queryByText(BARCODE_CODE)).not.toBeInTheDocument();
    const NEW_CODE = BARCODE_CODE.replace("0842", "0900");
    await act(async () => reply!.resolve({ body: { ...BARCODE, code: NEW_CODE } }));
    expect(await within(panel).findByText(NEW_CODE)).toBeInTheDocument();
    expect(within(panel).queryByText("Updating…")).not.toBeInTheDocument();
  });

  it("an open done form closes when another item is opened, and stays closed on the way back", async () => {
    const { user } = renderTrays("/trays/to-pay?item=1");
    const panel = await screen.findByRole("region", { name: "Item" });
    await user.click(await within(panel).findByRole("button", { name: "Mark paid" }));
    expect(screen.getByRole("form", { name: "Mark paid" })).toBeInTheDocument();
    await user.click(within(row("Water⟨U+202E⟩bill")).getByRole("link"));
    await within(detail()).findByRole("heading", { name: "Water⟨U+202E⟩bill" });
    await user.click(within(row("Northpower sähkö")).getByRole("link"));
    await within(detail()).findByRole("heading", { name: "Northpower sähkö" });
    expect(screen.queryByRole("form", { name: "Mark paid" })).not.toBeInTheDocument();
    expect(within(detail()).getByRole("button", { name: "Mark paid" })).toBeInTheDocument();
  });

  it("a row shows a payee only when its tray has a payee field", async () => {
    renderTrays("/trays/to-action", {
      "GET /api/trays/to-action/items": { body: [{ ...ACTION, fields: { ...ACTION.fields, payee: "Stray Oy" } }] },
    });
    const action = await screen.findByRole("article", { name: "Water pipe inspection" });
    expect(action).not.toHaveTextContent("Stray Oy");
  });
});

describe("Dragging tray rows", () => {
  it("a row drags its item's files", async () => {
    renderTrays("/trays/to-pay");
    const li = (await screen.findByRole("article", { name: "Northpower sähkö" })).closest("li")!;
    expect(li).toHaveAttribute("draggable", "true");
    const dt = dataTransfer();
    fireEvent.dragStart(li, { dataTransfer: dt });
    expect(JSON.parse(dt.data["application/x-dam-files"])).toEqual({ ids: BILL.files });
    expect(BILL.files.length).toBe(2); // every file of the item
    document.dispatchEvent(new Event("dragend"));
  });

  it("an item without files is not draggable", async () => {
    renderTrays("/trays/to-read", {
      "GET /api/trays/to-read/items": { body: [{ ...READ, files: [], first_file: null }] },
    });
    const li = (await screen.findByRole("article", { name: READ.title })).closest("li")!;
    expect(li).not.toHaveAttribute("draggable", "true");
  });
});

const SEARCH_HITS = [
  { drive_id: "f1", path: "10. Financial/Banks/northpower.pdf", name: "northpower.pdf", snippet: "", rank: 1, marks: [] },
  { drive_id: "f7", path: "10. Financial/Banks/meter.pdf", name: "meter.pdf", snippet: "", rank: 2, marks: [] },
];

describe("Merging items by dragging", () => {
  const dragOnto = (source: HTMLElement, target: HTMLElement) => {
    const dt = dataTransfer();
    fireEvent.dragStart(source.closest("li")!, { dataTransfer: dt });
    fireEvent.dragEnter(target.closest("li")!, { dataTransfer: dt });
    fireEvent.dragOver(target.closest("li")!, { dataTransfer: dt });
    fireEvent.drop(target.closest("li")!, { dataTransfer: dt });
    document.dispatchEvent(new Event("dragend"));
    return dt;
  };

  it("a row also says which item it is, next to its files", async () => {
    renderTrays("/trays/to-pay");
    const li = (await screen.findByRole("article", { name: "Northpower sähkö" })).closest("li")!;
    const dt = dataTransfer();
    fireEvent.dragStart(li, { dataTransfer: dt });
    expect(JSON.parse(dt.data["application/x-dam-item"])).toEqual({ id: 1 });
    expect(JSON.parse(dt.data["application/x-dam-files"])).toEqual({ ids: BILL.files });
    document.dispatchEvent(new Event("dragend"));
  });

  it("dropping an item on another asks first; Merge posts, names the result and Undo posts the undo", async () => {
    const { calls, user } = renderTrays("/trays/to-pay", {
      "POST /api/items/1/merge": { body: { ...BILL, files: ["f1", "f2", "f9"] } },
      "POST /api/items/1/undo-merge": { body: BILL },
    });
    const source = await screen.findByRole("article", { name: "Water⟨U+202E⟩bill" });
    dragOnto(source, row("Northpower sähkö"));
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent(/Merge .*Water.*bill.* into .*Northpower sähkö/);
    expect(dialog).toHaveTextContent(/Its files, notes and checklist are added to .*Northpower sähkö.*, and .*Water.*bill.* is removed/);
    expect(sent(calls, "POST", "/api/items/1/merge")).toHaveLength(0);
    await user.click(within(dialog).getByRole("button", { name: "Merge" }));
    await waitFor(() => expect(sent(calls, "POST", "/api/items/1/merge")).toHaveLength(1));
    expect(sent(calls, "POST", "/api/items/1/merge")[0].body).toEqual({ item_id: 2 });
    expect(await screen.findByText(/Merged .*Water.*bill.* into .*Northpower sähkö/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Undo" }));
    await waitFor(() => expect(sent(calls, "POST", "/api/items/1/undo-merge")).toHaveLength(1));
  });

  it("Cancel merges nothing", async () => {
    const { calls, user } = renderTrays("/trays/to-pay");
    const source = await screen.findByRole("article", { name: "Water⟨U+202E⟩bill" });
    dragOnto(source, row("Northpower sähkö"));
    await user.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(calls.filter((c) => c.url.endsWith("/merge"))).toHaveLength(0);
  });

  it("an item dropped on itself does nothing", async () => {
    renderTrays("/trays/to-pay");
    const only = await screen.findByRole("article", { name: "Northpower sähkö" });
    dragOnto(only, only);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("the open item's panel moves to the item it was merged into", async () => {
    const { user } = renderTrays("/trays/to-pay?item=2", {
      "POST /api/items/1/merge": { body: { ...BILL, files: ["f1", "f2", "f9"] } },
    });
    const source = await screen.findByRole("article", { name: "Water⟨U+202E⟩bill" });
    dragOnto(source, row("Northpower sähkö"));
    await user.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Merge" }));
    await waitFor(() => expect(where()).toBe("/trays/to-pay?item=1"));
  });
});

describe("Dragging a file from Browse onto an item", () => {
  const dragFile = (target: HTMLElement, ids = ["f7"]) => {
    const dt = dataTransfer();
    dt.setData("application/x-dam-files", JSON.stringify({ ids }));
    fireEvent.dragEnter(target, { dataTransfer: dt });
    fireEvent.dragOver(target, { dataTransfer: dt });
    fireEvent.drop(target, { dataTransfer: dt });
  };

  it("onto a row in the list attaches it, with an Undo that takes it off again", async () => {
    const { calls, user } = renderTrays("/trays/to-pay", {
      "POST /api/items/2/files": { body: { ...LATER, files: ["f1", "f7"] } },
      "POST /api/items/2/files/remove": { body: LATER },
    });
    const target = await screen.findByRole("article", { name: "Water⟨U+202E⟩bill" });
    dragFile(target.closest("li")!);
    await waitFor(() => expect(sent(calls, "POST", "/api/items/2/files")).toHaveLength(1));
    expect(sent(calls, "POST", "/api/items/2/files")[0].body).toEqual({ drive_id: "f7" });
    await user.click(await screen.findByRole("button", { name: "Undo" }));
    await waitFor(() => expect(sent(calls, "POST", "/api/items/2/files/remove")).toHaveLength(1));
    expect(sent(calls, "POST", "/api/items/2/files/remove")[0].body).toEqual({ drive_id: "f7" });
  });

  it("a file the item already has is refused, not added twice", async () => {
    const { calls } = renderTrays("/trays/to-pay");
    const target = await screen.findByRole("article", { name: "Northpower sähkö" });
    dragFile(target.closest("li")!, ["f1"]);
    await new Promise((r) => setTimeout(r, 10));
    expect(sent(calls, "POST", "/api/items/1/files")).toHaveLength(0);
  });

  it("onto the open item's panel attaches it", async () => {
    const { calls } = renderTrays("/trays/to-pay?item=1", {
      "POST /api/items/1/files": { body: { ...BILL, files: ["f1", "f2", "f7"] } },
    });
    const panel = await screen.findByRole("region", { name: "Item" });
    await within(panel).findByRole("tablist", { name: "Files" });
    dragFile(panel.querySelector(".item-detail") as HTMLElement);
    await waitFor(() => expect(sent(calls, "POST", "/api/items/1/files")).toHaveLength(1));
    expect(sent(calls, "POST", "/api/items/1/files")[0].body).toEqual({ drive_id: "f7" });
  });

  it("a done item takes no files", async () => {
    const { calls } = renderTrays("/trays/to-pay?state=done", {
      "GET /api/items/9": { body: PAID },
      "GET /api/items/9/files": { body: [] },
      "GET /api/items/9/history": { body: [] },
      "GET /api/notes/item/9": { body: { text: "" } },
      "GET /api/checklist/item/9": { body: [] },
    });
    const target = await screen.findByRole("article", { name: "Old bill" });
    dragFile(target.closest("li")!);
    await new Promise((r) => setTimeout(r, 10));
    expect(calls.filter((c) => c.method === "POST")).toHaveLength(0);
  });
});

describe("The file picker of an item", () => {
  it("the history names a merged-in item with what came along", async () => {
    renderTrays("/trays/to-pay?item=1", {
      "GET /api/items/1/history": {
        body: [{ id: 9, at: 1_760_000_000, kind: "merged_in", data: { title: "Reminder", files: [{ drive_id: "f5" }], note: true, checks: 2 } }],
      },
    });
    expect(await screen.findByText(/Reminder merged in: 1 file, a note, 2 checklist entries/)).toBeInTheDocument();
  });

  it("lists hits with their path, marks files already on the item and does not add them", async () => {
    const { calls, user } = renderTrays("/trays/to-pay?item=1", {
      "GET /api/search": { body: SEARCH_HITS },
    });
    const panel = await screen.findByRole("region", { name: "Item" });
    await user.click(await within(panel).findByRole("button", { name: "Add another file…" }));
    await user.type(within(panel).getByLabelText("Find a file"), "pdf");
    const taken = await within(panel).findByRole("button", { name: /northpower\.pdf \(already on this item\)/ });
    expect(taken).toBeDisabled();
    await user.click(taken);
    expect(sent(calls, "POST", "/api/items/1/files")).toHaveLength(0);
    expect(within(panel).getByText("10. Financial/Banks/meter.pdf")).toBeInTheDocument();
  });

  it("arrow keys move through the hits and Enter adds the one under the focus", async () => {
    const { calls, user } = renderTrays("/trays/to-pay?item=1", {
      "GET /api/search": { body: SEARCH_HITS },
      "POST /api/items/1/files": { body: { ...BILL, files: ["f1", "f2", "f7"] } },
    });
    const panel = await screen.findByRole("region", { name: "Item" });
    await user.click(await within(panel).findByRole("button", { name: "Add another file…" }));
    const box = within(panel).getByLabelText("Find a file");
    await user.type(box, "pdf");
    const meter = await within(panel).findByRole("button", { name: /^Add meter\.pdf/ });
    await user.keyboard("{ArrowDown}"); // the first choosable hit (the taken one is skipped)
    expect(meter).toHaveFocus();
    await user.keyboard("{ArrowUp}");
    expect(box).toHaveFocus();
    await user.keyboard("{ArrowDown}{Enter}");
    await waitFor(() => expect(sent(calls, "POST", "/api/items/1/files")).toHaveLength(1));
    expect(sent(calls, "POST", "/api/items/1/files")[0].body).toEqual({ drive_id: "f7" });
  });

  it("Browse folders walks the archive and adds a file from it", async () => {
    const dir = (name: string, path: string, drive_id: string) => ({ name, path, is_dir: true, is_link: false, size: null, mtime: null, drive_id, marks: [] });
    const file = (name: string, path: string, drive_id: string) => ({ name, path, is_dir: false, is_link: false, size: 1, mtime: 1, drive_id, marks: [] });
    const { calls, user } = renderTrays("/trays/to-pay?item=1", {
      "GET /api/browse": (call) => ({
        body: call.url.includes("path=10.%20Financial")
          ? [file("meter.pdf", "10. Financial/meter.pdf", "f7"), file("northpower.pdf", "10. Financial/northpower.pdf", "f1")]
          : [dir("10. Financial", "10. Financial", "d1")],
      }),
      "POST /api/items/1/files": { body: { ...BILL, files: ["f1", "f2", "f7"] } },
    });
    const panel = await screen.findByRole("region", { name: "Item" });
    await user.click(await within(panel).findByRole("button", { name: "Add another file…" }));
    await user.click(within(panel).getByRole("button", { name: "Browse folders…" }));
    await user.click(await within(panel).findByRole("button", { name: "Open folder 10. Financial" }));
    expect(await within(panel).findByRole("button", { name: /northpower\.pdf \(already on this item\)/ })).toBeDisabled();
    await user.click(within(panel).getByRole("button", { name: /^Add meter\.pdf/ }));
    await waitFor(() => expect(sent(calls, "POST", "/api/items/1/files")).toHaveLength(1));
    expect(sent(calls, "POST", "/api/items/1/files")[0].body).toEqual({ drive_id: "f7" });
  });

  it("an item with one file has no × on it (the item keeps a file)", async () => {
    renderTrays("/trays/to-pay?item=4");
    const panel = await screen.findByRole("region", { name: "Item" });
    await within(panel).findByRole("button", { name: "Add another file…" });
    expect(within(panel).queryByRole("button", { name: /^Remove .* from this item$/ })).not.toBeInTheDocument();
  });

  it("Esc closes the picker", async () => {
    const { user } = renderTrays("/trays/to-pay?item=1");
    const panel = await screen.findByRole("region", { name: "Item" });
    await user.click(await within(panel).findByRole("button", { name: "Add another file…" }));
    await user.keyboard("{Escape}");
    expect(within(panel).queryByLabelText("Find a file")).not.toBeInTheDocument();
  });
});

describe("Tray defaults update", () => {
  const ADDED = [
    { path: "fields.payee", value: { type: "text", prefill: "payee", copy: true }, problem: null },
    { path: "fields.amount.copy", value: true, problem: null },
    { path: "summary", value: { sum: "amount" }, problem: "summary: no field am‮ount" },
  ];
  const CURRENT = "id: to-pay\nname: To pay\nfields:\n  amount: { type: money }\n";
  /** A server stand-in: new_text adds a line per chosen path; dismissed ones are left out. */
  function defaultsApi(dismissedAtStart: string[] = []) {
    let dismissed = [...dismissedAtStart];
    const offered = () => ADDED.filter((a) => !dismissed.includes(a.path));
    return {
      "GET /api/trays/to-pay/defaults-diff": (call: Call) => {
        const q = new URL(call.url, "http://x").searchParams;
        const asked = q.getAll("paths");
        const paths = asked.length ? asked : offered().filter((a) => !a.problem).map((a) => a.path);
        return {
          body: {
            file: "10-to-pay.yaml",
            added: offered(),
            paths,
            current_text: CURRENT,
            new_text: CURRENT + paths.map((p) => `# + ${p}\n`).join(""),
            error: paths.includes("summary") ? "summary: no field amount" : null,
            dismissed: q.get("dismissed") ? dismissed : [],
          },
        };
      },
      "POST /api/trays/to-pay/apply-defaults": { body: { file: "10-to-pay.yaml", backup: "10-to-pay.yaml.bak-20261021-101010" } },
      "POST /api/trays/to-pay/defaults-dismiss": (call: Call) => {
        dismissed = [...dismissed, ...(call.body as { paths: string[] }).paths];
        return { body: { dismissed } };
      },
      "POST /api/trays/to-pay/defaults-undismiss": (call: Call) => {
        const drop = (call.body as { paths: string[] }).paths;
        dismissed = dismissed.filter((p) => !drop.includes(p));
        return { body: { dismissed } };
      },
    };
  }
  const banner = () => screen.findByRole("region", { name: "Tray settings" });
  const sheet = () => screen.findByRole("dialog", { name: "Update To pay settings" });

  it("the banner names what is missing, readably", async () => {
    renderTrays("/trays/to-pay", defaultsApi());
    expect(await banner()).toHaveTextContent(
      "Your To pay settings are missing: Payee field, copy button on Amount, total on Today",
    );
    expect(screen.queryByText(/new in this version/i)).not.toBeInTheDocument();
  });

  it("no banner when nothing is missing", async () => {
    renderTrays("/trays/to-pay", {
      "GET /api/trays/to-pay/defaults-diff": {
        body: { file: "10-to-pay.yaml", added: [], paths: [], current_text: CURRENT, new_text: CURRENT, error: null, dismissed: [] },
      },
    });
    await screen.findByRole("article", { name: "Northpower sähkö" });
    await new Promise((r) => setTimeout(r, 20));
    expect(screen.queryByRole("region", { name: "Tray settings" })).not.toBeInTheDocument();
  });

  it("the sheet lists every item checked, with its problem, the file and the diff; Update applies the checked ones", async () => {
    const { calls, user } = renderTrays("/trays/to-pay", defaultsApi());
    await user.click(within(await banner()).getByRole("button", { name: "Update tray settings…" }));
    const dialog = await sheet();
    const boxes = within(dialog).getAllByRole("checkbox");
    expect(boxes.map((b) => (b as HTMLInputElement).checked)).toEqual([true, true, true]);
    // the value lines are indented by the checkbox width, which is set from here
    const list = within(dialog).getByRole("list", { name: "Missing settings" });
    expect(list.style.getPropertyValue("--check-width")).toBe("14px");
    expect(within(dialog).getByRole("checkbox", { name: /Payee field/ })).toBeInTheDocument();
    expect(dialog).toHaveTextContent("summary: no field am⟨U+202E⟩ount"); // the item's problem
    expect(dialog).toHaveTextContent("config/trays/10-to-pay.yaml");
    // all three together are invalid: Update says why
    await waitFor(() => expect(dialog).toHaveTextContent("summary: no field amount"));
    expect(within(dialog).getByRole("button", { name: "Update" })).toBeDisabled();
    await user.click(within(dialog).getByRole("checkbox", { name: /Total on Today/ }));
    await waitFor(() => expect(within(dialog).getByRole("button", { name: "Update" })).toBeEnabled());
    expect(within(dialog).getByTestId("defaults-diff")).toHaveTextContent("+ # + fields.payee");
    await user.click(within(dialog).getByRole("button", { name: "Update" }));
    await waitFor(() => expect(sent(calls, "POST", "/api/trays/to-pay/apply-defaults")).toHaveLength(1));
    expect(sent(calls, "POST", "/api/trays/to-pay/apply-defaults")[0].body).toEqual({
      paths: ["fields.payee", "fields.amount.copy"],
      expect_current_text: CURRENT,
      expect_new_text: `${CURRENT}# + fields.payee\n# + fields.amount.copy\n`,
    });
    expect(await screen.findByText("Tray settings updated (backup saved)")).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("after Update the chosen subset is not asked for again (it is no longer missing: a 400)", async () => {
    const api = defaultsApi();
    let applied = false;
    const subsetAsked: string[] = [];
    const { calls, user } = renderTrays("/trays/to-pay", {
      ...api,
      "GET /api/trays/to-pay/defaults-diff": (call: Call) => {
        const asked = new URL(call.url, "http://x").searchParams.getAll("paths");
        if (applied && asked.length > 0) {
          subsetAsked.push(call.url);
          return { status: 400, body: { error: "no longer missing", code: "stale_preview" } };
        }
        return api["GET /api/trays/to-pay/defaults-diff"](call);
      },
      "POST /api/trays/to-pay/apply-defaults": () => {
        applied = true;
        return { body: { file: "10-to-pay.yaml", backup: "10-to-pay.yaml.bak-20261021-101010" } };
      },
    });
    await user.click(within(await banner()).getByRole("button", { name: "Update tray settings…" }));
    const dialog = await sheet();
    await user.click(within(dialog).getByRole("checkbox", { name: /Total on Today/ }));
    await waitFor(() => expect(within(dialog).getByRole("button", { name: "Update" })).toBeEnabled());
    await user.click(within(dialog).getByRole("button", { name: "Update" }));
    expect(await screen.findByText("Tray settings updated (backup saved)")).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    await new Promise((r) => setTimeout(r, 30));
    expect(subsetAsked).toEqual([]);
    expect(sent(calls, "POST", "/api/trays/to-pay/apply-defaults")).toHaveLength(1);
  });

  it("Don't offer these dismisses the unchecked items; Show dismissed offers them again", async () => {
    const { calls, user } = renderTrays("/trays/to-pay", defaultsApi());
    await user.click(within(await banner()).getByRole("button", { name: "Update tray settings…" }));
    const dialog = await sheet();
    expect(within(dialog).getByRole("button", { name: "Don't offer these" })).toBeDisabled(); // nothing unchecked
    await user.click(within(dialog).getByRole("checkbox", { name: /Total on Today/ }));
    await user.click(within(dialog).getByRole("checkbox", { name: /Copy button on Amount/ }));
    await user.click(within(dialog).getByRole("button", { name: "Don't offer these" }));
    await waitFor(() => expect(sent(calls, "POST", "/api/trays/to-pay/defaults-dismiss")).toHaveLength(1));
    expect(sent(calls, "POST", "/api/trays/to-pay/defaults-dismiss")[0].body).toEqual({
      paths: ["fields.amount.copy", "summary"],
    });
    await waitFor(() => expect(within(dialog).getAllByRole("checkbox")).toHaveLength(1));
    await user.click(within(dialog).getByRole("button", { name: "Show dismissed (2)" }));
    const list = within(dialog).getByRole("list", { name: "Dismissed settings" });
    expect(list).toHaveTextContent("Copy button on Amount");
    await user.click(within(list).getByRole("button", { name: "Offer Total on Today again" }));
    await waitFor(() => expect(sent(calls, "POST", "/api/trays/to-pay/defaults-undismiss")).toHaveLength(1));
    expect(sent(calls, "POST", "/api/trays/to-pay/defaults-undismiss")[0].body).toEqual({ paths: ["summary"] });
    await waitFor(() => expect(within(dialog).getAllByRole("checkbox")).toHaveLength(2));
  });

  it("with everything dismissed, a small link still opens the dismissed list", async () => {
    const { user } = renderTrays("/trays/to-pay", defaultsApi(["fields.payee", "fields.amount.copy", "summary"]));
    await user.click(await screen.findByRole("button", { name: "Show dismissed tray settings" }));
    const dialog = await sheet();
    expect(within(dialog).getByRole("list", { name: "Dismissed settings" })).toHaveTextContent("Payee field");
  });

  it("while a new subset loads, the older diff is dimmed and says Preparing…", async () => {
    const api = defaultsApi();
    const held = deferred<void>();
    const diffRoute = api["GET /api/trays/to-pay/defaults-diff"];
    const { user } = renderTrays("/trays/to-pay", {
      ...api,
      "GET /api/trays/to-pay/defaults-diff": async (call: Call) => {
        if (new URL(call.url, "http://x").searchParams.getAll("paths").length === 1) await held.promise;
        return diffRoute(call);
      },
    });
    await user.click(within(await banner()).getByRole("button", { name: "Update tray settings…" }));
    const dialog = await sheet();
    await waitFor(() => expect(dialog.querySelector(".defaults-diff-box")).not.toHaveClass("preparing"));
    await user.click(within(dialog).getByRole("checkbox", { name: /Total on Today/ }));
    await user.click(within(dialog).getByRole("checkbox", { name: /Copy button on Amount/ }));
    await waitFor(() => expect(dialog.querySelector(".defaults-diff-box")).toHaveClass("preparing"));
    expect(dialog).toHaveTextContent("Preparing…");
    expect(within(dialog).getByRole("button", { name: "Update" })).toBeDisabled();
    await act(async () => held.resolve());
    await waitFor(() => expect(dialog.querySelector(".defaults-diff-box")).not.toHaveClass("preparing"));
    expect(dialog).not.toHaveTextContent("Preparing…");
  });

  it("two clicks on Update in one batch apply once; a stale preview says so", async () => {
    const held = deferred<{ status: number; body: unknown }>();
    const { calls, user } = renderTrays("/trays/to-pay", {
      ...defaultsApi(),
      "POST /api/trays/to-pay/apply-defaults": () => held.promise,
    });
    await user.click(within(await banner()).getByRole("button", { name: "Update tray settings…" }));
    const dialog = await sheet();
    await user.click(within(dialog).getByRole("checkbox", { name: /Total on Today/ }));
    const update = within(dialog).getByRole("button", { name: "Update" });
    await waitFor(() => expect(update).toBeEnabled());
    fireEvent.click(update);
    fireEvent.click(update);
    await act(async () =>
      held.resolve({ status: 400, body: { error: "the tray file changed: review the update again", code: "stale_preview" } }),
    );
    expect(sent(calls, "POST", "/api/trays/to-pay/apply-defaults")).toHaveLength(1);
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("the tray file changed: review the update again");
  });
});

describe("Trash on a tray item's files", () => {
  const quarantines = (calls: Call[]) => sent(calls, "POST", "/api/quarantine").map((c) => c.body);

  it("the action row's bin moves the shown file to ##. To Delete through the confirm; Undo restores; one in ##. To Delete has none", async () => {
    const { calls, user } = renderTrays("/trays/to-pay?item=1", {
      "POST /api/quarantine": quarantineRoute({ f1: NORTHPOWER_FILE.path! }),
      "POST /api/activity/q1/undo/preview": { body: [] },
      "POST /api/activity/q1/undo": { body: { batch_id: "u1", dry_run: false, done: [], failed: null, error: null, index_error: null } },
    });
    const panel = await screen.findByRole("region", { name: "Item" });
    const tabs = await within(panel).findByRole("tablist", { name: "Files" });
    await user.click(within(tabs).getByRole("tab", { name: /receipt\.png/ }));
    await waitFor(() => expect(within(panel).queryByRole("button", { name: "Move to To Delete" })).toBeNull());
    await user.click(within(tabs).getByRole("tab", { name: /northpower\.pdf/ }));
    await user.click(await within(panel).findByRole("button", { name: "Move to To Delete" }));
    const dialog = await screen.findByRole("dialog", { name: "Move to To Delete?" });
    await user.click(within(dialog).getByRole("button", { name: "Move to To Delete" }));
    await user.click(await screen.findByRole("button", { name: "Undo" }));
    await user.click(await undoButton(await screen.findByRole("dialog", { name: "Undo these changes?" })));
    await waitFor(() => expect(sent(calls, "POST", "/api/activity/q1/undo")).toHaveLength(1));
    expect(quarantines(calls)).toEqual([
      { drive_ids: ["f1"], dry_run: true },
      { drive_ids: ["f1"], dry_run: false },
    ]);
  });

  it("⌘⌫ with the focus on the action row trashes the shown file (a plain ⌫ does not); a file marked Important is refused with the reason", async () => {
    const { calls, user } = renderTrays("/trays/to-pay?item=1", {
      "POST /api/quarantine": IMPORTANT_REFUSED(NORTHPOWER_FILE.path!),
    });
    const panel = await screen.findByRole("region", { name: "Item" });
    await within(panel).findByRole("tablist", { name: "Files" });
    (await within(panel).findByRole("button", { name: "Remove from tray" })).focus();
    await user.keyboard("{Backspace}");
    await new Promise((r) => setTimeout(r, 10));
    expect(quarantines(calls)).toHaveLength(0);
    await user.keyboard("{Meta>}{Backspace}{/Meta}");
    expect(await screen.findByText(/This file is marked Important; unmark it first/)).toBeInTheDocument();
    expect(quarantines(calls)).toEqual([{ drive_ids: ["f1"], dry_run: true }]);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});

describe("The item view layout", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("has no separate Title field; clicking the title (no pencil) or Enter / Space on it opens it, Esc cancels", async () => {
    const { calls, user } = renderTrays("/trays/to-pay?item=1");
    await within(await screen.findByRole("region", { name: "Item" })).findByRole("heading", { name: "Northpower sähkö" });
    expect(within(detail()).queryByLabelText("Title")).not.toBeInTheDocument();
    const clickable = within(detail()).getByRole("button", { name: "Edit title" });
    expect(clickable).toHaveAttribute("title", "Click to edit the title");
    expect(clickable).toHaveTextContent("Northpower sähkö");
    expect(within(detail()).getAllByRole("button", { name: /title/i })).toHaveLength(1); // no pencil beside it

    await user.click(clickable);
    let field = within(detail()).getByLabelText("Title");
    expect(field).toHaveValue("Northpower sähkö");
    await user.type(field, " draft{Escape}");
    expect(within(detail()).queryByLabelText("Title")).not.toBeInTheDocument();
    expect(within(detail()).getByRole("heading", { name: "Northpower sähkö" })).toBeInTheDocument();

    for (const key of ["{Enter}", " "]) {
      within(detail()).getByRole("button", { name: "Edit title" }).focus();
      await user.keyboard(key);
      field = within(detail()).getByLabelText("Title");
      await user.type(field, "x{Escape}");
      expect(within(detail()).queryByLabelText("Title")).not.toBeInTheDocument();
    }
    expect(sent(calls, "PATCH", "/api/items/1")).toHaveLength(0);
  });

  it("the file name under the title is renamed by clicking it, and Esc cancels", async () => {
    const { calls, user } = renderTrays("/trays/to-pay?item=1");
    await within(await screen.findByRole("region", { name: "Item" })).findByRole("heading", { name: "Northpower sähkö" });
    const name = await within(detail()).findByRole("button", { name: "Rename northpower.pdf" });
    expect(within(detail()).getAllByRole("button", { name: /^Rename/ })).toHaveLength(1); // no pencil
    await user.click(name);
    await user.type(await within(detail()).findByRole("textbox", { name: "File name" }), "x{Escape}");
    expect(within(detail()).queryByRole("textbox", { name: "File name" })).not.toBeInTheDocument();
    within(detail()).getByRole("button", { name: "Rename northpower.pdf" }).focus();
    await user.keyboard("{Enter}");
    expect(await within(detail()).findByRole("textbox", { name: "File name" })).toHaveValue("northpower");
    expect(calls.filter((c) => c.method === "POST" && c.url.includes("rename"))).toHaveLength(0);
  });

  it("an empty title is refused with the server's message and nothing is sent", async () => {
    const { calls, user } = renderTrays("/trays/to-pay?item=1");
    const field = await editTitle(user);
    await user.clear(field);
    await user.keyboard("{Enter}");
    expect(await within(detail()).findByRole("alert")).toHaveTextContent("A title must not be blank");
    expect(within(detail()).getByLabelText("Title")).toBeInTheDocument();
    expect(sent(calls, "PATCH", "/api/items/1")).toHaveLength(0);
  });

  it("leaving the title field saves it and says Saved", async () => {
    const { calls, user } = renderTrays("/trays/to-pay?item=1", {
      "PATCH /api/items/1": { body: { ...BILL, title: "Power bill" } },
    });
    const field = await editTitle(user);
    await user.clear(field);
    await user.type(field, "Power bill");
    await user.tab();
    await waitFor(() => expect(sent(calls, "PATCH", "/api/items/1")).toHaveLength(1));
    expect(sent(calls, "PATCH", "/api/items/1")[0].body).toEqual({ title: "Power bill" });
    expect(await within(detail()).findByText("Saved")).toBeInTheDocument();
    expect(within(detail()).queryByLabelText("Title")).not.toBeInTheDocument();
  });

  it("the tags are under the title in the header", async () => {
    renderTrays("/trays/to-pay?item=1");
    await screen.findByRole("region", { name: "Item" });
    const tags = await within(detail()).findByRole("region", { name: "Tags" });
    const header = detail().querySelector(".item-header") as HTMLElement;
    expect(header).toContainElement(tags);
    const heading = within(header).getByRole("heading", { name: "Northpower sähkö" });
    expect(heading.compareDocumentPosition(tags) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("the item view has the file view's block order, with the item's own block in the middle", async () => {
    renderTrays("/trays/to-pay?item=1");
    await screen.findByRole("region", { name: "Item" });
    await within(detail()).findByRole("region", { name: "Tags" });
    await within(detail()).findByRole("img", { name: "Page 1" });
    const blocks = Array.from(detail().querySelectorAll("[data-block]")).map((b) => b.getAttribute("data-block"));
    // the tags sit under the title, inside the header block (the item view's earlier decision)
    expect(blocks).toEqual(["header", "collections", "summary", "own", "preview", "notes"]);
    const inBlock = (name: string) => detail().querySelector(`[data-block="${name}"]`) as HTMLElement;
    expect(within(inBlock("header")).getByRole("heading", { level: 2, name: "Northpower sähkö" })).toBeInTheDocument();
    expect(within(inBlock("header")).getByRole("heading", { level: 2, name: "northpower.pdf" })).toBeInTheDocument();
    expect(within(inBlock("header")).getByRole("region", { name: "Tags" })).toBeInTheDocument();
    expect(within(inBlock("collections")).getByRole("combobox", { name: "Add to collection" })).toBeInTheDocument();
    expect(within(inBlock("summary")).getByRole("region", { name: "Summary" })).toBeInTheDocument();
    expect(within(inBlock("own")).getByRole("button", { name: "Mark paid" })).toBeInTheDocument();
    expect(within(inBlock("own")).getByRole("button", { name: "Remove from tray" })).toBeInTheDocument();
    expect(within(inBlock("preview")).getByRole("button", { name: "Quick Look" })).toBeInTheDocument();
    expect(within(inBlock("notes")).getByRole("region", { name: "Checklist" })).toBeInTheDocument();
    expect(within(inBlock("notes")).getByRole("button", { name: "History" })).toBeInTheDocument();
  });

  it("the file's collections are chips in the item view: × removes, the field adds", async () => {
    const SAUNA = {
      id: 7, name: "Sauna", state: "open", created: 1, closed_at: null, publish: { ongoing: false }, ongoing_rel: null,
      members: [{ drive_id: "f1", path: "10. Financial/Banks/northpower.pdf", is_dir: false, missing: false, quarantined: false, group_id: null, marks: [] }],
      ongoing_status: null, summary: "", groups: [], parent_id: null, path: ["Sauna"], kind: null, position: 0, files: 1, open_checks: 0,
    };
    const CAR = { ...SAUNA, id: 8, name: "Car", path: ["Car"], members: [], files: 0 };
    const change = (c: object) => ({ body: { collection: c, batch: null, problems: [], ongoing_status: null } });
    const { calls, user } = renderTrays("/trays/to-pay?item=1", {
      "GET /api/files/f1/links": { body: { items: [{ id: 1, tray_id: "to-pay", tray_name: "To pay", title: "Northpower sähkö", state: "open" }], collections: [SAUNA], note: "" } },
      "GET /api/collections": { body: [SAUNA, CAR] },
      "POST /api/collections/7/members/remove": change(SAUNA),
      "POST /api/collections/8/members": change(CAR),
    });
    await screen.findByRole("region", { name: "Item" });
    const block = await within(detail()).findByRole("region", { name: "Collections of this file" });
    await within(block).findByRole("link", { name: "Sauna" });
    // the item being viewed is not listed as a link to itself
    expect(within(block).queryByRole("link", { name: /Northpower/ })).not.toBeInTheDocument();
    await user.click(within(block).getByRole("button", { name: "Remove from Sauna" }));
    await waitFor(() => expect(sent(calls, "POST", "/api/collections/7/members/remove")).toHaveLength(1));
    expect(sent(calls, "POST", "/api/collections/7/members/remove")[0].body).toEqual({ drive_id: "f1" });

    await user.type(within(block).getByRole("combobox", { name: "Add to collection" }), "car");
    await user.click(await within(block).findByRole("option", { name: "Car" }));
    await waitFor(() => expect(sent(calls, "POST", "/api/collections/8/members")).toHaveLength(1));
    expect(sent(calls, "POST", "/api/collections/8/members")[0].body).toEqual({ drive_ids: ["f1"] });
  });

  it("Summary, Checklist, Notes and History fold with aria-expanded, a hint, and are remembered", async () => {
    const first = renderTrays("/trays/to-pay?item=1");
    await screen.findByRole("region", { name: "Item" });
    await within(detail()).findByText("Check meter");
    for (const name of ["Summary", "Checklist", "Notes", "History"]) {
      expect(within(detail()).getByRole("button", { name })).toHaveAttribute("aria-expanded", "true");
    }
    const checklist = within(detail()).getByRole("region", { name: "Checklist" });
    await first.user.click(within(detail()).getByRole("button", { name: "Checklist" }));
    expect(within(detail()).getByRole("button", { name: "Checklist" })).toHaveAttribute("aria-expanded", "false");
    expect(checklist).toHaveTextContent("1 of 2 done");
    expect(within(checklist).getByLabelText("Add to checklist")).not.toBeVisible();
    await first.user.click(within(detail()).getByRole("button", { name: "History" }));
    expect(detail().querySelector(".history")).toHaveTextContent("4 entries");
    expect(window.localStorage.getItem("dam.collapsed.checklist")).toBe("1");

    // another item (a fresh mount) starts the way it was left
    cleanup();
    renderTrays("/trays/to-action?item=4");
    await screen.findByRole("region", { name: "Item" });
    await within(detail()).findByRole("region", { name: "Checklist" });
    expect(within(detail()).getByRole("button", { name: "Checklist" })).toHaveAttribute("aria-expanded", "false");
    expect(within(detail()).getByRole("button", { name: "Summary" })).toHaveAttribute("aria-expanded", "true");
    // and it opens again
    const again = userEvent.setup();
    await again.click(within(detail()).getByRole("button", { name: "Checklist" }));
    expect(within(detail()).getByRole("button", { name: "Checklist" })).toHaveAttribute("aria-expanded", "true");
    expect(window.localStorage.getItem("dam.collapsed.checklist")).toBeNull();
  });

  it("a note and the summary show their first line when folded", async () => {
    const { user } = renderTrays("/trays/to-pay?item=1");
    await screen.findByRole("region", { name: "Item" });
    await within(detail()).findByLabelText("Note (optional)");
    await user.click(within(detail()).getByRole("button", { name: "Notes" }));
    expect(within(detail()).getByRole("region", { name: "Notes" })).toHaveTextContent("call first");
    await user.click(within(detail()).getByRole("button", { name: "Summary" }));
    expect(within(detail()).getByRole("region", { name: "Summary" })).toHaveTextContent("No summary yet.");
  });

  it("Space still opens Quick Look from the list", async () => {
    const { user } = renderTrays("/trays/to-pay?item=1");
    await screen.findByRole("button", { name: "Quick Look" });
    await user.keyboard(" ");
    expect(await screen.findByRole("dialog", { name: /^Quick Look/ })).toBeInTheDocument();
  });
});
