/** Today: the board's arrangement (headline, stat tiles, the To pay table, compact tray
 * lists, the Inbox summary on the right), plus Customize (arrange mode). */
import { cleanup, createEvent, fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { AttentionItem, Item, Today as TodayData, TrayDef } from "../api/client";
import { setDragFiles } from "../dnd";
import { CARD_DRAG_TYPE, LAYOUT_KEY } from "../components/useCardLayout";
import { type Call, dataTransfer, mockFetch, renderWithProviders } from "../test-utils";
import Today from "./Today";

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
  },
  date_field: "due_date",
  summary: { sum: "amount" },
  done: { label: "Mark paid", fields: { paid_on: { type: "date", required: false, copy: false, default: "today" } } },
};
const TO_ACTION: TrayDef = {
  id: "to-action",
  name: "To action",
  order: 2,
  item_title: "{name}",
  fields: { action_date: { type: "date", required: true, copy: false } },
  date_field: "action_date",
  done: { label: "Done", fields: {} },
};
const FOLLOW_UP: TrayDef = {
  id: "follow-up",
  name: "Follow up",
  order: 3,
  item_title: "{name}",
  fields: { check_by: { type: "date", required: false, copy: false }, waiting_for: { type: "text", required: false, copy: false } },
  date_field: "check_by",
  done: { label: "Done", fields: {} },
};
const TRAYS = { trays: [TO_PAY, TO_ACTION, FOLLOW_UP], errors: [] };

function item(id: number, tray: string, title: string, over: Partial<Item> = {}): Item {
  return {
    id,
    tray_id: tray,
    title,
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
    tray_name: tray,
    tray_removed: false,
    ...over,
  };
}
const bill = (id: number, title: string, date: string, amount: string) =>
  item(id, "to-pay", title, {
    date,
    fields: { payee: `${title} Oy`, due_date: date, amount, iban: "FI2112345600000785" },
    tray_name: "To pay",
  });
const POWER = bill(1, "Electricity", "2026-10-09", "84.20");
const INSURANCE = bill(2, "Insurance", "2026-10-21", "54.20");
const WATER = bill(3, "Water", "2026-11-05", "47.90");
const SERVICE = item(4, "to-action", "Car service", { date: "2026-10-21", fields: { action_date: "2026-10-21" } });
const PASSPORT = item(5, "to-action", "Renew passport", { date: "2026-11-06", fields: { action_date: "2026-11-06" } });
const QUOTE = item(6, "follow-up", "Builder quote", { date: "2026-10-31", fields: { check_by: "2026-10-31", waiting_for: "builder" } });

const attention = (i: Item, level: AttentionItem["level"], extra: Partial<AttentionItem> = {}): AttentionItem => ({
  item: i,
  tray: i.tray_id,
  level,
  missing_required: [],
  file_state: "ok",
  note_excerpt: null,
  ...extra,
});

const TODAY: TodayData = {
  attention: [
    attention(POWER, "overdue", { note_excerpt: "Ask why September is higher" }),
    attention(INSURANCE, "soon"),
    attention(SERVICE, "soon"),
  ],
  overview: {
    inbox: 7,
    trays: [
      { tray_id: "to-pay", name: "To pay", open: 3, overdue: 1, sum: "186.30", waiting_long: 0 },
      { tray_id: "to-action", name: "To action", open: 2, overdue: 0, sum: null, waiting_long: 0 },
      { tray_id: "follow-up", name: "Follow up", open: 1, overdue: 0, sum: null, waiting_long: 0 },
    ],
    collections: [{ id: 7, name: "House sale", files: 4, open_checks: 3, note_excerpt: "", in_inbox: 1 }],
  },
  unmanaged_ongoing: 4,
  unmanaged_important: 1,
  ongoing_sync_failure: null,
  reminders: { last_run: null, errors: {}, skipped: null },
  tray_errors: [],
  inbox_stats: { count: 7, oldest_days: 2, this_week: 7, last_week: 0, older: 0, overdue: 0 },
  found: [],
  open_items: [
    { tray_id: "to-pay", items: [POWER, INSURANCE, WATER] },
    { tray_id: "to-action", items: [SERVICE, PASSPORT] },
    { tray_id: "follow-up", items: [QUOTE] },
  ],
  marked: 2,
  reading_codes: 0,
};

const inboxEntry = (id: string, guess: string | null) => ({
  record: { drive_id: id, path: `##. Organize/${id}.pdf`, name: `${id}.pdf`, is_dir: false },
  tray_guess: guess,
  open_trays: [],
});

function renderToday(over: Partial<TodayData> = {}, routes: Parameters<typeof mockFetch>[0] = {}) {
  const calls = mockFetch({
    "GET /api/today": { body: { ...TODAY, ...over } },
    "GET /api/trays": { body: TRAYS },
    "GET /api/trays/to-pay/items": { body: [POWER, INSURANCE, WATER] },
    "GET /api/inbox": { body: [inboxEntry("a", "to-pay"), inboxEntry("b", "to-pay"), inboxEntry("c", null)] },
    "GET /api/builtin/starred": { body: { id: 1, members: [] } },
    ...routes,
  });
  const user = userEvent.setup();
  renderWithProviders(
    <MemoryRouter>
      <Routes>
        <Route path="/" element={<Today today={DAY} />} />
        <Route path="*" element={null} />
      </Routes>
    </MemoryRouter>,
  );
  return { calls, user };
}

afterEach(() => {
  cleanup();
  localStorage.clear();
});

const posts = (calls: Call[], url: string) => calls.filter((c) => c.method === "POST" && c.url === url);
const section = (name: string) => screen.getByRole("region", { name });
const order = () => screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent);

describe("Today: header and tiles", () => {
  it("has the date, a headline built from the counts, and Start filing with the inbox count", async () => {
    renderToday();
    expect(await screen.findByRole("heading", { level: 1 })).toHaveTextContent("One bill is overdue, seven documents to file");
    expect(screen.getByText("Monday 19 October 2026")).toBeInTheDocument();
    const start = screen.getByRole("link", { name: /^Start filing/ });
    expect(start).toHaveTextContent("Start filing 7");
    expect(start).toHaveAttribute("href", "/inbox");
    expect(screen.getByRole("button", { name: "Customize" })).toBeInTheDocument();
  });

  it("has no Start filing when the inbox is empty, and says All clear when nothing waits", async () => {
    renderToday({
      attention: [],
      overview: { ...TODAY.overview, trays: [], collections: [] },
      open_items: [],
      unmanaged_ongoing: 0,
      unmanaged_important: 0,
      inbox_stats: { ...TODAY.inbox_stats, count: 0, oldest_days: null },
    });
    expect(await screen.findByRole("heading", { level: 1 })).toHaveTextContent("All clear");
    expect(screen.queryByRole("link", { name: /^Start filing/ })).not.toBeInTheDocument();
  });

  it("shows the four tiles with their figures, each linking on", async () => {
    renderToday();
    const tiles = within(await screen.findByRole("group", { name: "At a glance" }));
    const tile = (label: string) => tiles.getByText(label).closest("a")!;
    expect(tile("To file")).toHaveAttribute("href", "/inbox");
    expect(tile("To file")).toHaveTextContent("oldest from 17 Oct");
    await waitFor(() => expect(tile("Overdue")).toHaveTextContent("84,20 €"));
    expect(tile("Overdue")).toHaveTextContent("1 bill, 10 days late");
    expect(tile("Overdue")).toHaveAttribute("href", "/trays/to-pay?item=1");
    expect(tile("Due in 14 days")).toHaveTextContent("54,20 €");
    expect(tile("Due in 14 days")).toHaveTextContent("1 bill");
    expect(tile("Waiting on others")).toHaveTextContent("1");
    expect(tile("Waiting on others")).toHaveAttribute("href", "/trays/follow-up");
  });

  it("shows the two Convert notices as one, with a link for each", async () => {
    renderToday();
    const banner = await screen.findByRole("region", { name: "Not in the app yet" });
    expect(banner).toHaveTextContent("4 entries in ##. Ongoing and 1 entry in ##. Important are not in the app yet.");
    expect(within(banner).getByRole("link", { name: "Convert Ongoing" })).toHaveAttribute("href", "/ongoing");
    expect(within(banner).getByRole("link", { name: "Convert Important" })).toHaveAttribute("href", "/important/convert");
  });

  it("names only the one that is there", async () => {
    renderToday({ unmanaged_ongoing: 0 });
    const banner = await screen.findByRole("region", { name: "Not in the app yet" });
    expect(banner).toHaveTextContent("1 entry in ##. Important is not in the app yet.");
    expect(within(banner).queryByRole("link", { name: "Convert Ongoing" })).not.toBeInTheDocument();
  });
});

describe("Today: To pay", () => {
  it("is a table of the open bills by due date with the due tag, amount, Pay and Paid", async () => {
    renderToday();
    const table = await screen.findByRole("table");
    await within(table).findByText("Water");
    const rows = within(table).getAllByRole("row");
    expect(within(rows[0]).getAllByRole("columnheader").map((c) => c.textContent)).toEqual(["Bill", "Due", "Amount", "Actions"]);
    const names = within(table).getAllByRole("link").map((l) => l.textContent);
    expect(names).toEqual(["Electricity", "Insurance", "Water"]);
    expect(within(table).getByText("10 days overdue")).toHaveClass("tag-red");
    expect(within(table).getByText("in 2 days")).toHaveClass("tag-orange");
    expect(within(table).getByText("84,20 €")).toBeInTheDocument();
    expect(within(table).getByRole("link", { name: "Electricity" })).toHaveAttribute("href", "/trays/to-pay?item=1");
    expect(within(table).getByText("Electricity Oy")).toBeInTheDocument();
    expect(within(table).getAllByRole("button", { name: /^Open Pay mode for/ })).toHaveLength(3);
  });

  it("names the figures beside the heading", async () => {
    renderToday();
    const pay = await screen.findByRole("region", { name: "To pay" });
    await within(pay).findByText("Water");
    expect(within(pay).getByText(/3 open/)).toHaveTextContent("3 open · 186,30 €");
    expect(within(pay).getByRole("link", { name: "Show all in To pay" })).toHaveAttribute("href", "/trays/to-pay");
  });

  it("opens the overdue bill up with its copy buttons and note; the later ones stay one line", async () => {
    renderToday();
    const table = await screen.findByRole("table");
    await within(table).findByText("Water");
    expect(within(table).getByRole("button", { name: "Copy payee" })).toBeInTheDocument();
    expect(within(table).getByRole("button", { name: "Copy amount" })).toBeInTheDocument();
    expect(within(table).getByRole("button", { name: "Copy IBAN" })).toBeInTheDocument();
    expect(within(table).getByText("Note: Ask why September is higher")).toBeInTheDocument();
    // one set of copy buttons: only the overdue bill is open
    expect(within(table).getAllByRole("button", { name: "Copy IBAN" })).toHaveLength(1);
  });

  it("Pay opens Pay mode on that bill, stepping through every bill from there", async () => {
    const { user } = renderToday({}, { "GET /api/items/2/barcode": { body: { code: "4".padEnd(54, "2"), modules: [2, 1, 1, 2], reason: null, printed: null, printed_fields: null, mismatch: [] } } });
    await user.click(await screen.findByRole("button", { name: "Open Pay mode for Insurance" }));
    const sheet = await screen.findByRole("dialog", { name: "Bank barcode" });
    expect(await within(sheet).findByText(/^Bill 2 of 3/)).toBeInTheDocument();
    expect(within(sheet).getByRole("heading", { name: "Insurance" })).toBeInTheDocument();
    expect(within(sheet).getByRole("button", { name: "Previous bill" })).toBeEnabled();
  });

  it("the Pay mode link in the heading starts at the first bill", async () => {
    const { user } = renderToday();
    await screen.findByRole("table");
    await user.click(screen.getByRole("button", { name: "Pay mode" }));
    const sheet = await screen.findByRole("dialog", { name: "Bank barcode" });
    expect(await within(sheet).findByText(/^Bill 1 of 3/)).toBeInTheDocument();
  });

  it("Paid marks the bill paid at once with the tray's default, and the toast offers Undo", async () => {
    const { calls, user } = renderToday({}, { "POST /api/items/2/done": { body: { ...INSURANCE, state: "done" } } });
    await user.click(await screen.findByRole("button", { name: "Mark Insurance paid" }));
    await waitFor(() => expect(posts(calls, "/api/items/2/done")).toHaveLength(1));
    expect(posts(calls, "/api/items/2/done")[0].body).toEqual({ fields: { paid_on: expect.stringMatching(/^\d{4}-\d{2}-\d{2}$/) } });
    expect(await screen.findByText("Marked paid: Insurance")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Undo" })).toBeInTheDocument();
  });

  it("a tray whose done action needs a value opens the small form under the bill", async () => {
    const asks = { trays: [{ ...TO_PAY, done: { label: "Mark paid", fields: { paid_on: { type: "date", required: true, copy: false, default: null } } } }, TO_ACTION, FOLLOW_UP], errors: [] };
    const { calls, user } = renderToday({}, { "GET /api/trays": { body: asks } });
    await user.click(await screen.findByRole("button", { name: "Mark Water paid" }));
    const form = await screen.findByRole("form", { name: "Mark paid" });
    expect(posts(calls, "/api/items/3/done")).toHaveLength(0);
    expect(form).toBeInTheDocument();
  });

  it("keeps the To pay section with a calm empty line when nothing is open, and no Clear card", async () => {
    renderToday(
      {
        attention: [],
        overview: { ...TODAY.overview, trays: TODAY.overview.trays.map((t) => ({ ...t, open: 0, overdue: 0, sum: t.sum ? "0.00" : null })) },
        open_items: TODAY.open_items.map((t) => ({ ...t, items: [] })),
      },
      { "GET /api/trays/to-pay/items": { body: [] } },
    );
    const pay = await screen.findByRole("region", { name: "To pay" });
    expect(await within(pay).findByText("Nothing open.")).toBeInTheDocument();
    expect(within(pay).getByText("0 open")).toBeInTheDocument();
    expect(within(section("To action")).getByText("Nothing open.")).toBeInTheDocument();
    expect(within(section("Follow up")).getByText("Nothing open.")).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Clear" })).not.toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("with many bills shows eight rows and links to the rest; long names stay in their row", async () => {
    const many = Array.from({ length: 12 }, (_, i) => bill(30 + i, `A very long bill name number ${i} ${"x".repeat(60)}`, `2026-11-${10 + i}`, "10.00"));
    renderToday({}, { "GET /api/trays/to-pay/items": { body: many } });
    const table = await screen.findByRole("table");
    await within(table).findByRole("link", { name: /number 0 / });
    expect(within(table).getAllByRole("button", { name: /^Open Pay mode for/ })).toHaveLength(8);
    expect(within(table).getByRole("link", { name: "4 more bills" })).toHaveAttribute("href", "/trays/to-pay");
  });
});

describe("Today: the other trays", () => {
  it("gives each a compact list with its count, a done checkbox, an urgency tag and Show all", async () => {
    const { calls, user } = renderToday({}, { "POST /api/items/4/done": { body: { ...SERVICE, state: "done" } } });
    const action = await screen.findByRole("region", { name: "To action" });
    expect(within(action).getByText("2 open")).toBeInTheDocument();
    expect(within(action).getByRole("link", { name: "Car service" })).toHaveAttribute("href", "/trays/to-action?item=4");
    expect(within(action).getByText("in 2 days")).toHaveClass("tag-orange");
    expect(within(action).getByRole("link", { name: "Show all in To action" })).toHaveAttribute("href", "/trays/to-action");
    await user.click(within(action).getByRole("checkbox", { name: "Mark Car service done" }));
    await waitFor(() => expect(posts(calls, "/api/items/4/done")).toHaveLength(1));
    // Follow up is its own section
    expect(within(section("Follow up")).getByRole("link", { name: "Builder quote" })).toBeInTheDocument();
  });

  it("shows four rows and says how many more", async () => {
    const many = Array.from({ length: 6 }, (_, i) => item(20 + i, "to-action", `Task ${i}`, { date: `2026-11-0${i + 1}`, fields: { action_date: `2026-11-0${i + 1}` } }));
    renderToday({
      attention: [],
      open_items: [{ tray_id: "to-pay", items: [] }, { tray_id: "to-action", items: many }, { tray_id: "follow-up", items: [QUOTE] }],
      overview: { ...TODAY.overview, trays: TODAY.overview.trays.map((t) => (t.tray_id === "to-action" ? { ...t, open: 9 } : t)) },
    });
    const action = await screen.findByRole("region", { name: "To action" });
    expect(within(action).getAllByRole("article")).toHaveLength(4);
    expect(within(action).getByRole("link", { name: "5 more items" })).toHaveAttribute("href", "/trays/to-action");
  });
});

describe("Today: the right column", () => {
  it("summarises the inbox: count, oldest, how many the rules recognised, and the age bar", async () => {
    renderToday();
    const inbox = await screen.findByRole("region", { name: "Inbox" });
    expect(within(inbox).getByText("7 files, oldest 2 days")).toBeInTheDocument();
    expect(await within(inbox).findByRole("img", { name: "2 recognised by a rule, 1 not recognised" })).toBeInTheDocument();
    expect(within(inbox).getByText("2 recognised by a rule")).toBeInTheDocument();
    expect(within(inbox).getByText("1 not recognised")).toBeInTheDocument();
    expect(within(inbox).getByRole("img", { name: /7 this week/ })).toBeInTheDocument();
    expect(within(inbox).getByRole("link", { name: "Open" })).toHaveAttribute("href", "/inbox");
    expect(within(inbox).getByRole("link", { name: "File 2 marked" })).toBeInTheDocument();
  });

  it("keeps the files found by the scan rules, each with its one-click Put in", async () => {
    renderToday({
      found: [{ drive_id: "d9", name: "scan.pdf", tray: "to-pay", tray_name: "To pay", due_date: "2026-10-15", total: "84.20", overdue: true, marks: [] }],
    });
    const inbox = await screen.findByRole("region", { name: "Inbox" });
    expect(await within(inbox).findByRole("button", { name: "Put in To pay" })).toBeInTheDocument();
  });

  it("lists the collections to do, Starred and Reminders as sections of their own", async () => {
    renderToday();
    expect(within(await screen.findByRole("region", { name: "Collections to do" })).getByRole("link", { name: "House sale" })).toHaveAttribute("href", "/browse?tree=collections&q=collection%3A%22House+sale%22");
    expect(section("Starred")).toBeInTheDocument();
    expect(within(section("Reminders")).getByText("Not checked yet.")).toBeInTheDocument();
  });

  it("has no Search card (the palette and Browse search), and a saved layout that still lists it is read without it", async () => {
    localStorage.setItem(LAYOUT_KEY, JSON.stringify({ order: ["search", "pay", "|", "inbox", "search", "starred"], collapsed: { search: true } }));
    const { user } = renderToday();
    await screen.findByRole("table");
    expect(screen.queryByRole("region", { name: "Search" })).not.toBeInTheDocument();
    expect(screen.queryByRole("searchbox")).not.toBeInTheDocument();
    expect(order()).not.toContain("Search");
    await user.click(screen.getByRole("button", { name: "Customize" }));
    await user.click(screen.getByRole("button", { name: "Collapse Starred" }));
    expect(localStorage.getItem(LAYOUT_KEY)).not.toContain("search"); // pruned when the layout is next saved
  });
});

describe("Today: Customize", () => {
  it("starts calm: no fold chevrons, no Move buttons, no Reset layout", async () => {
    renderToday();
    await screen.findByRole("table");
    expect(screen.queryByRole("button", { name: /^Move / })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Collapse / })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Reset layout" })).not.toBeInTheDocument();
  });

  it("Customize turns the sections into an arrange mode with fold, Move up and Move down, and Reset layout", async () => {
    const { user } = renderToday();
    await screen.findByRole("table");
    const button = screen.getByRole("button", { name: "Customize" });
    await user.click(button);
    expect(button).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "Collapse To pay" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Move To pay up" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Move To pay down" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Reset layout" })).toBeInTheDocument();
    await user.click(button);
    expect(screen.queryByRole("button", { name: /^Move / })).not.toBeInTheDocument();
  });

  it("Move down reorders and is remembered; Reset layout puts it back", async () => {
    const { user } = renderToday();
    await screen.findByRole("table");
    const before = order();
    expect(before.slice(0, 3)).toEqual(["To pay", "To action", "Follow up"]);
    await user.click(screen.getByRole("button", { name: "Customize" }));
    await user.click(screen.getByRole("button", { name: "Move To pay down" }));
    expect(order().slice(0, 3)).toEqual(["To action", "To pay", "Follow up"]);
    expect(localStorage.getItem(LAYOUT_KEY)).toContain('"order":["tray:to-action","pay"');
    await user.click(screen.getByRole("button", { name: "Reset layout" }));
    expect(order()).toEqual(before);
    expect(localStorage.getItem(LAYOUT_KEY)).toBeNull();
  });

  it("a folded section stays folded after arranging, and can be opened again from its chevron", async () => {
    const { user } = renderToday();
    await screen.findByRole("table");
    await user.click(screen.getByRole("button", { name: "Customize" }));
    await user.click(screen.getByRole("button", { name: "Collapse To action" }));
    await user.click(screen.getByRole("button", { name: "Done arranging" }));
    expect(within(section("To action")).queryByRole("link", { name: "Car service" })).not.toBeInTheDocument();
    const open = within(section("To action")).getByRole("button", { name: "Expand To action" });
    await user.click(open);
    expect(within(section("To action")).getByRole("link", { name: "Car service" })).toBeInTheDocument();
  });

  it("Option-Down on a heading moves the section too", async () => {
    const { user } = renderToday();
    await screen.findByRole("table");
    await user.click(screen.getByRole("button", { name: "Customize" }));
    screen.getByRole("button", { name: "Collapse To pay" }).focus();
    await user.keyboard("{Alt>}{ArrowDown}{/Alt}");
    expect(order().slice(0, 2)).toEqual(["To action", "To pay"]);
  });
});

describe("Today: the small done form", () => {
  // a tray whose done action needs a value the user must give (no default)
  const ASKS = {
    trays: [{ ...TO_PAY, done: { label: "Mark paid", fields: { paid_on: { type: "date", required: true, copy: false, default: null } } } }, TO_ACTION, FOLLOW_UP],
    errors: [],
  };

  it("posts the value given on Enter; a failed done keeps the form open and shows the error", async () => {
    const { calls, user } = renderToday({}, { "GET /api/trays": { body: ASKS }, "POST /api/items/3/done": { status: 400, body: { error: "paid_on: expected a date" } } });
    await user.click(await screen.findByRole("button", { name: "Mark Water paid" }));
    const form = await screen.findByRole("form", { name: "Mark paid" });
    const paidOn = within(form).getByLabelText("Paid on");
    expect(paidOn).toHaveFocus();
    fireEvent.change(paidOn, { target: { value: DAY } });
    await user.keyboard("{Enter}");
    await waitFor(() => expect(posts(calls, "/api/items/3/done")).toHaveLength(1));
    expect(posts(calls, "/api/items/3/done")[0].body).toEqual({ fields: { paid_on: DAY } });
    expect(await within(form).findByRole("alert")).toHaveTextContent("paid_on: expected a date");
    expect(screen.getByRole("form", { name: "Mark paid" })).toBeInTheDocument();
  });

  it("Esc closes the form without posting, also when the focus has left it", async () => {
    const { calls, user } = renderToday({}, { "GET /api/trays": { body: ASKS } });
    await user.click(await screen.findByRole("button", { name: "Mark Water paid" }));
    const form = await screen.findByRole("form", { name: "Mark paid" });
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("form")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Mark Water paid" }));
    await user.click(screen.getByRole("heading", { level: 1 }));
    expect(within(screen.getByRole("form", { name: "Mark paid" })).getByLabelText("Paid on")).not.toHaveFocus();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("form")).not.toBeInTheDocument();
    expect(form).not.toBeInTheDocument();
    expect(posts(calls, "/api/items/3/done")).toHaveLength(0);
  });
});

describe("Today: copying from the overdue bill", () => {
  it("the IBAN copy button writes the compact IBAN and shows Copied", async () => {
    const { user } = renderToday();
    const table = await screen.findByRole("table");
    await within(table).findByText("Water");
    await user.click(within(table).getByRole("button", { name: "Copy IBAN" }));
    expect(await navigator.clipboard.readText()).toBe("FI2112345600000785");
    expect(within(table).getByRole("status")).toHaveTextContent("Copied");
  });
});

describe("Today: Inbox found files", () => {
  const found = (n: number) =>
    Array.from({ length: n }, (_, i) => ({ drive_id: `d${i}`, name: `scan ${i}.pdf`, tray: "to-pay", tray_name: "To pay", due_date: "2026-10-15", total: "84.20", overdue: true, marks: [] }));

  it("lists the first five and offers the rest behind Show N more", async () => {
    const { user } = renderToday({ found: found(7) });
    const inbox = await screen.findByRole("region", { name: "Inbox" });
    const list = await within(inbox).findByRole("list", { name: "Found in the inbox" });
    expect(within(list).getAllByRole("listitem")).toHaveLength(5);
    await user.click(within(inbox).getByRole("button", { name: "Show 2 more" }));
    expect(within(list).getAllByRole("listitem")).toHaveLength(7);
  });

  it("with five or fewer found there is no Show more", async () => {
    renderToday({ found: found(5) });
    const list = await screen.findByRole("list", { name: "Found in the inbox" });
    expect(within(list).getAllByRole("listitem")).toHaveLength(5);
    expect(screen.queryByRole("button", { name: /^Show \d+ more$/ })).not.toBeInTheDocument();
  });
});

describe("Today: arranging by drag and keyboard", () => {
  const column = (i: number) => document.querySelectorAll<HTMLElement>(".today-col")[i];
  const head = (name: string) => section(name).querySelector("header")!;
  const arrange = async (user: ReturnType<typeof userEvent.setup>) => {
    await screen.findByRole("table");
    await user.click(screen.getByRole("button", { name: "Customize" }));
  };

  it("a folded section is kept folded after a remount", async () => {
    const { user } = renderToday();
    await arrange(user);
    await user.click(screen.getByRole("button", { name: "Collapse To action" }));
    cleanup();
    renderToday();
    await screen.findByRole("table");
    expect(within(section("To action")).queryByRole("link", { name: "Car service" })).not.toBeInTheDocument();
    expect(within(section("To pay")).getAllByRole("link").length).toBeGreaterThan(0);
  });

  it("dragging a section by its heading drops it before another section or at the end of a column", async () => {
    const { user } = renderToday();
    await arrange(user);
    const before = order();
    expect(head("Starred")).toHaveAttribute("draggable", "true");

    const dt = dataTransfer();
    fireEvent.dragStart(head("Starred"), { dataTransfer: dt });
    expect(dt.types).toEqual([CARD_DRAG_TYPE]); // never files: no application/x-dam-files
    dt.protectedMode = true; // while hovering, a page sees the types only
    expect(fireEvent.dragOver(section("Inbox"), { dataTransfer: dt })).toBe(false); // accepted
    dt.protectedMode = false;
    fireEvent.drop(section("Inbox"), { dataTransfer: dt });
    fireEvent.dragEnd(head("Starred"), { dataTransfer: dt });
    expect(order()).toEqual(["To pay", "To action", "Follow up", "Starred", "Inbox", "Collections to do", "Reminders"]);
    expect(order()).not.toEqual(before);

    const again = dataTransfer();
    fireEvent.dragStart(head("Inbox"), { dataTransfer: again });
    fireEvent.dragOver(column(0), { dataTransfer: again });
    fireEvent.drop(column(0), { dataTransfer: again });
    expect(order()).toEqual(["To pay", "To action", "Follow up", "Inbox", "Starred", "Collections to do", "Reminders"]);
    expect(JSON.parse(localStorage.getItem(LAYOUT_KEY)!).order).toEqual([
      "pay",
      "tray:to-action",
      "tray:follow-up",
      "inbox",
      "|",
      "starred",
      "collections",
      "reminders",
    ]);
  });

  it("Option-Down past the bottom of a column puts the focus on the section's heading in the next column", async () => {
    const { user } = renderToday();
    await arrange(user);
    screen.getByRole("button", { name: "Collapse Follow up" }).focus();
    await user.keyboard("{Alt>}{ArrowDown}{/Alt}");
    expect(column(1).contains(section("Follow up"))).toBe(true); // a new element in the other column
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Collapse Follow up" }));
    expect(document.body).toHaveTextContent("Follow up moved down");
    await user.keyboard("{Alt>}{ArrowUp}{/Alt}"); // the keys go on
    expect(column(0).contains(section("Follow up"))).toBe(true);
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Collapse Follow up" }));
  });

  it("a drop in the gap between two sections lands between them (the nearest slot by height)", async () => {
    const { user } = renderToday();
    await arrange(user);
    // the second column's sections: 100 px tall with 10 px gaps
    [...column(1).querySelectorAll<HTMLElement>(":scope > .today-slot")].forEach((slot, i) => {
      const top = i * 110;
      vi.spyOn(slot, "getBoundingClientRect").mockReturnValue({
        top,
        bottom: top + 100,
        height: 100,
        left: 0,
        right: 300,
        width: 300,
        x: 0,
        y: top,
        toJSON: () => ({}),
      } as DOMRect);
    });
    const at = (type: "dragOver" | "drop", clientY: number, dt: ReturnType<typeof dataTransfer>) => {
      const event = createEvent[type](column(1), { dataTransfer: dt });
      Object.defineProperty(event, "clientY", { value: clientY });
      fireEvent(column(1), event);
    };
    const dt = dataTransfer();
    fireEvent.dragStart(head("To action"), { dataTransfer: dt });
    at("dragOver", 215, dt); // between Collections to do (110–210) and Starred (220–320)
    expect(section("Starred").closest(".today-slot")).toHaveAttribute("data-drop", "before");
    at("drop", 215, dt);
    expect(order()).toEqual(["To pay", "Follow up", "Inbox", "Collections to do", "To action", "Starred", "Reminders"]);

    const below = dataTransfer();
    fireEvent.dragStart(head("Follow up"), { dataTransfer: below });
    at("drop", 10_000, below); // under the last section: the end of the column
    expect(order().at(-1)).toBe("Follow up");
  });

  it("files dragged over a section are not taken as a section", async () => {
    const { user } = renderToday();
    await arrange(user);
    const before = order();
    const dt = dataTransfer();
    setDragFiles({ dataTransfer: dt } as unknown as DragEvent, ["d1"], "bill.pdf");
    dt.setData(CARD_DRAG_TYPE, "reminders"); // even a forged id beside the files
    expect(fireEvent.dragOver(section("To pay"), { dataTransfer: dt })).toBe(true); // not accepted
    fireEvent.drop(section("To pay"), { dataTransfer: dt });
    expect(order()).toEqual(before);
    document.dispatchEvent(new Event("dragend"));
  });

  it("a saved layout naming a removed tray still shows every section; a new one goes to its default place", async () => {
    localStorage.setItem(
      LAYOUT_KEY,
      JSON.stringify({ order: ["tray:gone", "tray:to-action", "|", "reminders", "inbox"], collapsed: { "tray:gone": true } }),
    );
    renderToday();
    await screen.findByRole("table");
    expect(order()).toEqual(["To action", "To pay", "Follow up", "Reminders", "Inbox", "Collections to do", "Starred"]);
  });
});
