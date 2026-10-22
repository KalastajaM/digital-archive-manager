import { createEvent, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { AttentionItem, Item, Today as TodayData, TrayDef } from "../api/client";
import { AgeBar } from "../components/AgeBar";
import { CopyButton } from "../components/CopyButton";
import { RelativeDate, useLocalClock, useLocalToday } from "../components/RelativeDate";
import { UrgencyTag, urgency } from "../components/UrgencyTag";
import { formatMoney, groupIban } from "../format";
import { setDragFiles } from "../dnd";
import { CARD_DRAG_TYPE, LAYOUT_KEY } from "../components/useCardLayout";
import { type Call, dataTransfer, mockFetch, quarantineRoute, renderWithProviders } from "../test-utils";
import Today, { greeting, longDate } from "./Today";

const DAY = "2026-10-19";
const DAY_S = Date.parse(`${DAY}T12:00:00`) / 1000;

const TO_PAY: TrayDef = {
  id: "to-pay",
  name: "To pay",
  order: 1,
  item_title: "{name}",
  fields: {
    payee: { type: "text", required: false, prefill: "payee", copy: false },
    due_date: { type: "date", required: true, prefill: "due_date", copy: false },
    amount: { type: "money", required: false, prefill: "total", copy: true },
    iban: { type: "iban", required: false, prefill: "iban", copy: true },
    reference: { type: "reference", required: false, prefill: "reference", copy: true },
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
const TRAYS = { trays: [TO_PAY, TO_ACTION], errors: [] };

function item(id: number, overrides: Partial<Item> = {}): Item {
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
    ...overrides,
  };
}

const BILL = item(1, {
  title: "Northpower sähkö",
  fields: {
    payee: "Northpower\u202EOy",
    due_date: "2026-10-15",
    amount: "84.20",
    iban: "FI2112345600000785",
    reference: "RF18123456789",
  },
  date: "2026-10-15",
});
const ACTION = item(2, {
  tray_id: "to-action",
  tray_name: "To action",
  title: "Water pipe inspection",
  fields: { action_date: DAY },
  date: DAY,
});
const SOON = item(3, { title: "Kotihoito lasku", fields: { due_date: "2026-10-22", amount: "123.45" }, date: "2026-10-22" });
const UNDATED = item(4, { title: "Bill\u202Egpj.exe", missing_required: ["due_date"] });
/** Dated later than "soon": not on the attention list, only in the tray's own list. */
const LATER = item(5, {
  title: "Water",
  fields: { payee: "HSY", due_date: "2026-11-12", amount: "80.00" },
  date: "2026-11-12",
});
const READ = item(6, {
  tray_id: "to-read",
  tray_name: "To read",
  title: "Pension statement 2026",
  created: DAY_S - 21 * 86_400,
});

const attention = (i: Item, level: AttentionItem["level"], extra: Partial<AttentionItem> = {}): AttentionItem => ({
  item: i,
  tray: i.tray_id,
  level,
  missing_required: i.missing_required,
  file_state: "ok",
  note_excerpt: null,
  ...extra,
});

const TODAY: TodayData = {
  attention: [
    attention(BILL, "overdue"),
    attention(ACTION, "today", { note_excerpt: "fill\u202Ebuckets the evening before" }),
    attention(SOON, "soon", { file_state: "missing" }),
    attention(UNDATED, "undated", { file_state: "to_delete" }),
  ],
  overview: {
    inbox: 35,
    trays: [
      { tray_id: "to-pay", name: "To pay", open: 4, overdue: 1, sum: "412.90", waiting_long: 0 },
      { tray_id: "to-action", name: "To action", open: 1, overdue: 0, sum: null, waiting_long: 0 },
      { tray_id: "to-read", name: "To\u200Bread", open: 6, overdue: 0, sum: null, waiting_long: 2 },
    ],
    collections: [
      { id: 7, name: "Sauna\u202Econversion", files: 23, open_checks: 2, note_excerpt: "still\u200Bneeded", in_inbox: 0 },
    ],
  },
  unmanaged_ongoing: 0,
  unmanaged_important: 0,
  ongoing_sync_failure: null,
  reminders: { last_run: null, errors: {}, skipped: null },
  tray_errors: [],
  inbox_stats: { count: 35, oldest_days: 20, this_week: 10, last_week: 5, older: 20, overdue: 0 },
  found: [],
  // the first open items per tray (by date, undated last), as the API sends them
  open_items: [
    { tray_id: "to-pay", items: [BILL, SOON, LATER, UNDATED] },
    { tray_id: "to-action", items: [ACTION] },
    { tray_id: "to-read", items: [READ] },
  ],
};

const FOUND = {
  drive_id: "d9",
  name: "scan\u202Ebill.pdf",
  tray: "to-pay",
  tray_name: "To pay",
  due_date: "2026-10-15",
  total: "84.20",
  overdue: true,
};
const CREATED = item(11, { title: "Scan\u202Ebill", files: ["d9"], date: "2026-10-15" });

function Where() {
  const location = useLocation();
  return <p data-testid="where">{location.pathname + location.search}</p>;
}

function renderToday(routes: Parameters<typeof mockFetch>[0] = {}) {
  const calls = mockFetch({
    "GET /api/today": { body: TODAY },
    "GET /api/trays": { body: TRAYS },
    ...routes,
  });
  const user = userEvent.setup();
  const view = renderWithProviders(
    <MemoryRouter>
      <Routes>
        <Route path="/" element={<Today today={DAY} />} />
        <Route path="*" element={null} />
      </Routes>
      <Where />
    </MemoryRouter>,
  );
  return { calls, user, view };
}

// The card layout (order and folds) is kept in localStorage: every test starts fresh.
afterEach(() => localStorage.clear());

const row = (title: string) => screen.getByRole("article", { name: title });
const card = (name: string) => screen.getByRole("region", { name });
const posts = (calls: Call[], url: string) => calls.filter((c) => c.method === "POST" && c.url === url);
const toasts = () => document.querySelector<HTMLElement>(".toasts")!;

describe("formatting", () => {
  it("shows money with a comma and the euro sign, IBANs grouped in fours", () => {
    expect(formatMoney("84.20")).toBe("84,20 €");
    expect(formatMoney("-5.00")).toBe("-5,00 €");
    expect(groupIban("FI2112345600000785")).toBe("FI21 1234 5600 0007 85");
  });

  it("greets by the hour and writes the long date", () => {
    expect(greeting(5)).toBe("Good morning");
    expect(greeting(11)).toBe("Good morning");
    expect(greeting(12)).toBe("Good afternoon");
    expect(greeting(17)).toBe("Good afternoon");
    expect(greeting(18)).toBe("Good evening");
    expect(greeting(2)).toBe("Good evening");
    expect(longDate("2026-10-20")).toBe("Tuesday 20 October");
  });
});

describe("RelativeDate", () => {
  it("shows a date it cannot read as it is, hidden characters made visible", () => {
    render(<RelativeDate date={"soon\u202E"} today={DAY} />);
    expect(screen.getByText("soon⟨U+202E⟩")).toHaveAttribute("title", "soon⟨U+202E⟩");
  });

  it.each([
    ["2026-10-19", "today", false],
    ["2026-10-20", "tomorrow", false],
    ["2026-10-22", "in 3 days", false],
    ["2026-10-18", "yesterday", true],
    ["2026-10-15", "4 days ago", true],
  ])("%s is %s", (date, text, overdue) => {
    render(<RelativeDate date={date} today={DAY} />);
    const time = screen.getByText(text);
    expect(time).toHaveAttribute("title", expect.stringContaining(date.split("-")[0]));
    expect(time).toHaveAttribute("dateTime", date);
    expect(time.classList.contains("overdue")).toBe(overdue);
  });
});

describe("urgency tags", () => {
  it.each([
    ["2026-10-15", "4 days overdue", "red"],
    ["2026-10-18", "1 day overdue", "red"],
    ["2026-10-19", "today", "orange"],
    ["2026-10-20", "tomorrow", "orange"],
    ["2026-10-22", "in 3 days", "orange"],
    ["2026-10-23", "23 Oct", "grey"],
    ["2026-11-12", "12 Nov", "grey"],
    ["2027-01-05", "5 Jan 2027", "grey"],
  ])("%s is %s (%s)", (date, text, tone) => {
    expect(urgency(date, DAY)).toEqual({ text, tone });
    render(<UrgencyTag date={date} today={DAY} />);
    const tag = screen.getByText(text);
    expect(tag).toHaveClass(`tag-${tone}`);
    expect(tag).toHaveAttribute("title", expect.stringContaining(date.split("-")[0]));
  });

  it("shows a date it cannot read as it is, grey", () => {
    render(<UrgencyTag date={"soon\u202E"} today={DAY} />);
    expect(screen.getByText("soon⟨U+202E⟩")).toHaveClass("tag-grey");
  });
});

describe("AgeBar", () => {
  it("shows the three buckets in proportion, with their numbers in the legend", () => {
    render(<AgeBar thisWeek={2} lastWeek={1} older={1} />);
    const bar = screen.getByRole("img", { name: "2 this week, 1 last week, 1 older" });
    const segments = [...bar.querySelectorAll<HTMLElement>(".age-bar-segment")];
    expect(segments.map((s) => s.style.width)).toEqual(["50%", "25%", "25%"]);
    const legend = screen.getByRole("list", { name: "Inbox age" });
    expect(within(legend).getAllByRole("listitem").map((li) => li.textContent)).toEqual([
      "2 this week",
      "1 last week",
      "1 older",
    ]);
  });

  it("leaves out empty buckets from the bar but keeps them in the legend", () => {
    render(<AgeBar thisWeek={3} lastWeek={0} older={0} />);
    const bar = screen.getByRole("img", { name: "3 this week, 0 last week, 0 older" });
    expect(bar.querySelectorAll(".age-bar-segment")).toHaveLength(1);
    expect(screen.getAllByRole("listitem")).toHaveLength(3);
  });
});

describe("useLocalToday", () => {
  afterEach(() => vi.useRealTimers());

  it("the clock's hour moves on too (for the greeting)", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date(2026, 9, 19, 11, 59, 30));
    const { result } = renderHook(() => useLocalClock());
    expect(result.current).toEqual({ today: "2026-10-19", hour: 11 });
    act(() => vi.advanceTimersByTime(60_000));
    expect(result.current).toEqual({ today: "2026-10-19", hour: 12 });
  });

  it("moves on after midnight without a reload", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date(2026, 9, 19, 23, 59, 30));
    const { result } = renderHook(() => useLocalToday());
    expect(result.current).toBe("2026-10-19");
    act(() => vi.advanceTimersByTime(60_000));
    expect(result.current).toBe("2026-10-20");
    vi.setSystemTime(new Date(2026, 9, 21, 9, 0, 0));
    act(() => window.dispatchEvent(new Event("focus")));
    expect(result.current).toBe("2026-10-21");
  });
});

describe("CopyButton", () => {
  it("copies the value and confirms with Copied", async () => {
    const user = userEvent.setup();
    renderWithProviders(<CopyButton value="84.20" type="money" label="amount" />);
    await user.click(screen.getByRole("button", { name: "Copy amount" }));
    expect(await navigator.clipboard.readText()).toBe("84,20");
    expect(screen.getByText("Copied")).toHaveAttribute("role", "status");
  });

  it("says copy is not available when the clipboard API is missing", async () => {
    const user = userEvent.setup();
    const saved = Object.getOwnPropertyDescriptor(navigator, "clipboard");
    Object.defineProperty(navigator, "clipboard", { value: undefined, configurable: true });
    try {
      renderWithProviders(<CopyButton value="x" label="ref" />);
      await user.click(screen.getByRole("button", { name: "Copy ref" }));
      expect(await screen.findByText(/copy not available/i)).toBeInTheDocument();
      expect(screen.queryByText("Copied")).not.toBeInTheDocument();
    } finally {
      if (saved) Object.defineProperty(navigator, "clipboard", saved);
    }
  });
});

describe("Today", () => {
  it("greets with the date and says how much needs attention", async () => {
    renderToday();
    expect(await screen.findByRole("heading", { level: 1, name: /^Good (morning|afternoon|evening)$/ })).toBeVisible();
    expect(screen.getByText("Monday 19 October")).toBeInTheDocument();
    // the hero line counts what waits: the inbox, what is due soon, undated items, overdue
    expect(screen.getByText("35 to file · 2 items due soon · 1 item without a due date · 1 overdue")).toBeInTheDocument();
  });

  it("the hero line says bills when everything due soon is a bill, and nothing overdue when so", async () => {
    renderToday({
      "GET /api/today": {
        body: { ...TODAY, attention: [attention(SOON, "soon")], inbox_stats: { ...TODAY.inbox_stats, count: 6 } },
      },
    });
    expect(await screen.findByText("6 to file · 1 bill due soon · nothing overdue")).toBeInTheDocument();
  });

  it("lists what needs attention in its tray's card, with urgency tags, key fields and badges", async () => {
    renderToday();
    const bill = await screen.findByRole("article", { name: "Northpower sähkö" });
    expect(card("To pay")).toContainElement(bill);
    expect(bill).toHaveClass("attention-overdue");
    expect(within(bill).getByText("4 days overdue")).toHaveClass("tag-red");
    expect(within(bill).getByText("4 days overdue")).toHaveAttribute("title", "Overdue · 15.10.2026");
    expect(bill).toHaveTextContent("Northpower⟨U+202E⟩Oy");
    expect(bill).toHaveTextContent("84,20 €");
    expect(bill).toHaveTextContent("FI21 1234 5600 0007 85");

    const action = row("Water pipe inspection");
    expect(card("To action")).toContainElement(action);
    expect(action).toHaveClass("attention-today");
    expect(within(action).getByText("today")).toHaveClass("tag-orange");
    expect(action).toHaveTextContent("Note: fill⟨U+202E⟩buckets the evening before");
    expect(bill).not.toHaveTextContent("Note:");
    expect(within(action).getByRole("checkbox", { name: "Mark Water pipe inspection done" })).toBeInTheDocument();
    expect(within(action).queryByRole("button", { name: "Done" })).not.toBeInTheDocument();

    const soon = row("Kotihoito lasku");
    expect(soon).toHaveClass("attention-soon");
    expect(within(soon).getByText("in 3 days")).toHaveClass("tag-orange");
    expect(within(soon).getByText("file missing")).toBeInTheDocument();

    const undated = row("Bill⟨U+202E⟩gpj.exe");
    expect(within(undated).queryByText(/needs a/)).not.toBeInTheDocument();
    expect(within(undated).getByText(/To Delete/)).toBeInTheDocument();
  });

  it("To pay shows the total and the open bills from the payload by date, later ones grey without actions", async () => {
    const { calls } = renderToday();
    const pay = await screen.findByRole("region", { name: "To pay" });
    expect(pay).toHaveTextContent("412,90 €");
    expect(pay).toHaveTextContent("4 open · 1 overdue");
    await within(pay).findByRole("article", { name: "Water" });
    expect(within(pay).getAllByRole("article").map((a) => a.getAttribute("aria-label"))).toEqual([
      "Northpower sähkö",
      "Kotihoito lasku",
      "Water",
      "Bill⟨U+202E⟩gpj.exe",
    ]);
    const later = row("Water");
    expect(within(later).getByText("12 Nov")).toHaveClass("tag-grey");
    expect(later).toHaveTextContent("HSY");
    expect(later).toHaveTextContent("80,00 €");
    expect(within(later).queryByRole("button")).not.toBeInTheDocument();
    expect(within(pay).getByRole("link", { name: "Show all in To pay" })).toHaveAttribute("href", "/trays/to-pay");
    expect(within(pay).getByRole("link", { name: "Water" })).toHaveAttribute("href", "/trays/to-pay?item=5");
    // the rows come with /api/today: no request per tray
    expect(calls.filter((c) => c.url.includes("/items"))).toEqual([]);
  });

  it("says how many open items the card does not show", async () => {
    renderToday({
      "GET /api/today": {
        body: { ...TODAY, overview: { ...TODAY.overview, trays: [{ ...TODAY.overview.trays[0], open: 11 }] } },
      },
    });
    const pay = await screen.findByRole("region", { name: "To pay" });
    expect(within(pay).getByRole("link", { name: "7 more items" })).toHaveAttribute("href", "/trays/to-pay");
  });

  it("attention items missing from the open items still show", async () => {
    renderToday({ "GET /api/today": { body: { ...TODAY, open_items: [] } } });
    const pay = await screen.findByRole("region", { name: "To pay" });
    await within(pay).findByRole("article", { name: "Northpower sähkö" });
    expect(within(pay).getAllByRole("article")).toHaveLength(3);
    expect(within(pay).queryByRole("article", { name: "Water" })).not.toBeInTheDocument();
  });

  it("To read shows the count, how long the oldest waited and how many wait long", async () => {
    renderToday();
    const read = await screen.findByRole("region", { name: "To⟨U+200B⟩read" });
    expect(read).toHaveTextContent("6");
    expect(read).toHaveTextContent("2 waiting long");
    expect(await within(read).findByText("oldest 3 weeks")).toBeInTheDocument();
    expect(within(read).getByRole("article", { name: "Pension statement 2026" })).toHaveTextContent("3 weeks");
    expect(within(read).getByRole("link", { name: "Show all in To⟨U+200B⟩read" })).toHaveAttribute(
      "href",
      "/trays/to-read",
    );
  });

  it("shows copy buttons only for copy fields that have a value", async () => {
    renderToday();
    const bill = await screen.findByRole("article", { name: "Northpower sähkö" });
    const names = within(bill)
      .getAllByRole("button")
      .map((b) => b.textContent);
    expect(names).toEqual(["Copy amount", "Copy IBAN", "Copy reference"]);
    // the action has no copy fields; the soon bill has only an amount
    expect(within(row("Water pipe inspection")).queryByRole("button", { name: /^Copy/ })).not.toBeInTheDocument();
    expect(within(row("Kotihoito lasku")).getAllByRole("button", { name: /^Copy/ })).toHaveLength(1);
  });

  it("the IBAN copy button writes the compact IBAN and shows Copied", async () => {
    const { user } = renderToday();
    const bill = await screen.findByRole("article", { name: "Northpower sähkö" });
    await user.click(within(bill).getByRole("button", { name: "Copy IBAN" }));
    expect(await navigator.clipboard.readText()).toBe("FI2112345600000785");
    expect(within(bill).getByRole("status")).toHaveTextContent("Copied");
  });

  it("Mark paid asks for the done fields (paid on = today); Enter posts them and the row goes", async () => {
    let done = false;
    const { calls, user } = renderToday({
      "GET /api/today": () => ({
        body: done
          ? {
              ...TODAY,
              attention: TODAY.attention.slice(1),
              open_items: [{ tray_id: "to-pay", items: [SOON, LATER, UNDATED] }, ...TODAY.open_items.slice(1)],
            }
          : TODAY,
      }),
      "POST /api/items/1/done": () => {
        done = true;
        return { body: { ...BILL, state: "done" } };
      },
      "POST /api/items/1/reopen": { body: BILL },
    });
    const bill = await screen.findByRole("article", { name: "Northpower sähkö" });
    await user.click(within(bill).getByRole("checkbox", { name: "Mark Northpower sähkö paid" }));
    const form = within(bill).getByRole("form", { name: "Mark paid" });
    const paidOn = within(form).getByLabelText("Paid on");
    expect(paidOn).toHaveValue(DAY);
    expect(paidOn).toHaveFocus();
    expect(posts(calls, "/api/items/1/done")).toHaveLength(0);
    await user.keyboard("{Enter}");
    await waitFor(() => expect(posts(calls, "/api/items/1/done")).toHaveLength(1));
    expect(posts(calls, "/api/items/1/done")[0].body).toEqual({ fields: { paid_on: DAY } });
    await waitFor(() => expect(screen.queryByRole("article", { name: "Northpower sähkö" })).not.toBeInTheDocument());

    expect(toasts()).toHaveTextContent(/Mark paid: Northpower sähkö/);
    await user.click(within(toasts()).getByRole("button", { name: "Reopen" }));
    await waitFor(() => expect(posts(calls, "/api/items/1/reopen")).toHaveLength(1));
    expect(await within(toasts()).findByText("Reopened: Northpower sähkö")).toBeInTheDocument();
  });

  it("Esc closes the done form without posting; a tray without done fields completes at once, with Undo", async () => {
    const { calls, user } = renderToday({
      "POST /api/items/2/done": { body: { ...ACTION, state: "done" } },
      "POST /api/items/2/reopen": { body: ACTION },
    });
    const bill = await screen.findByRole("article", { name: "Northpower sähkö" });
    await user.click(within(bill).getByRole("checkbox", { name: "Mark Northpower sähkö paid" }));
    await user.keyboard("{Escape}");
    expect(within(bill).queryByRole("form")).not.toBeInTheDocument();
    expect(posts(calls, "/api/items/1/done")).toHaveLength(0);

    const action = row("Water pipe inspection");
    await user.click(within(action).getByRole("checkbox", { name: "Mark Water pipe inspection done" }));
    expect(within(action).queryByRole("form")).not.toBeInTheDocument();
    await waitFor(() => expect(posts(calls, "/api/items/2/done")).toHaveLength(1));
    expect(posts(calls, "/api/items/2/done")[0].body).toEqual({ fields: {} });
    expect(await within(toasts()).findByText("Marked done: Water pipe inspection")).toBeInTheDocument();
    await user.click(within(toasts()).getByRole("button", { name: "Undo" }));
    await waitFor(() => expect(posts(calls, "/api/items/2/reopen")).toHaveLength(1));
  });

  it("Esc closes the done form even when the focus has left it", async () => {
    const { user } = renderToday();
    const bill = await screen.findByRole("article", { name: "Northpower sähkö" });
    await user.click(within(bill).getByRole("checkbox", { name: "Mark Northpower sähkö paid" }));
    await user.click(screen.getByRole("heading", { level: 1 }));
    expect(within(bill).getByLabelText("Paid on")).not.toHaveFocus();
    await user.keyboard("{Escape}");
    expect(within(bill).queryByRole("form")).not.toBeInTheDocument();
  });

  it("Done stays disabled when the tray settings cannot be loaded", async () => {
    renderToday({ "GET /api/trays": { status: 500, body: { error: "x" } } });
    expect(await screen.findByText(/Tray settings could not be loaded/)).toBeInTheDocument();
    expect(within(row("Northpower sähkö")).getByRole("checkbox", { name: /^Mark Northpower sähkö/ })).toBeDisabled();
  });

  it("a failed done keeps the form and shows the error", async () => {
    const { user } = renderToday({ "POST /api/items/1/done": { status: 400, body: { error: "paid_on: expected a date" } } });
    const bill = await screen.findByRole("article", { name: "Northpower sähkö" });
    await user.click(within(bill).getByRole("checkbox", { name: "Mark Northpower sähkö paid" }));
    await user.keyboard("{Enter}");
    expect(await within(bill).findByRole("alert")).toHaveTextContent("paid_on: expected a date");
    expect(within(bill).getByRole("form", { name: "Mark paid" })).toBeInTheDocument();
  });

  it("the Inbox card shows the count, the oldest age, the age buckets and Start filing", async () => {
    renderToday({
      "GET /api/today": { body: { ...TODAY, inbox_stats: { ...TODAY.inbox_stats, overdue: 1 } } },
    });
    const inbox = await screen.findByRole("region", { name: "Inbox" });
    expect(inbox).toHaveTextContent("35 documents");
    expect(inbox).toHaveTextContent("oldest 2 weeks");
    expect(within(inbox).getByText("1 overdue")).toHaveClass("tag-red");
    expect(within(inbox).getByRole("img", { name: "10 this week, 5 last week, 20 older" })).toBeInTheDocument();
    expect(
      within(within(inbox).getByRole("list", { name: "Inbox age" }))
        .getAllByRole("listitem")
        .map((li) => li.textContent),
    ).toEqual(["10 this week", "5 last week", "20 older"]);
    expect(within(inbox).getByRole("link", { name: "Start filing" })).toHaveAttribute("href", "/inbox");
    expect(within(inbox).queryByRole("list", { name: "Found in the inbox" })).not.toBeInTheDocument();
  });

  it("an empty inbox says so, without a bar", async () => {
    renderToday({
      "GET /api/today": {
        body: {
          ...TODAY,
          inbox_stats: { count: 0, oldest_days: null, this_week: 0, last_week: 0, older: 0, overdue: 0 },
        },
      },
    });
    const inbox = await screen.findByRole("region", { name: "Inbox" });
    expect(inbox).toHaveTextContent("The inbox is empty.");
    expect(within(inbox).queryByRole("img")).not.toBeInTheDocument();
    expect(within(inbox).queryByRole("link", { name: "Start filing" })).not.toBeInTheDocument();
  });

  it("Put in creates the item from the found file; the toast opens it or takes it back", async () => {
    const { calls, user } = renderToday({
      "GET /api/today": { body: { ...TODAY, found: [FOUND] } },
      "POST /api/items/quick": { body: { created: [CREATED], skipped: [] } },
      "POST /api/items/11/discard": { status: 204, body: null },
    });
    const found = await screen.findByRole("list", { name: "Found in the inbox" });
    const entry = within(found).getByRole("listitem");
    expect(entry).toHaveTextContent("scan⟨U+202E⟩bill.pdf");
    expect(entry).toHaveTextContent("due date 15.10.2026 · 84,20 €");
    expect(within(entry).getByText("overdue")).toHaveClass("tag-red");

    await user.click(within(entry).getByRole("button", { name: "Put in To pay" }));
    await waitFor(() => expect(posts(calls, "/api/items/quick")).toHaveLength(1));
    expect(posts(calls, "/api/items/quick")[0].body).toEqual({ tray: "to-pay", drive_ids: ["d9"] });
    expect(await within(toasts()).findByText("Put in To pay: Scan⟨U+202E⟩bill")).toBeInTheDocument();

    await user.click(within(toasts()).getByRole("button", { name: "Undo" }));
    await waitFor(() => expect(posts(calls, "/api/items/11/discard")).toHaveLength(1));
    expect(await within(toasts()).findByText("Taken back: Scan⟨U+202E⟩bill")).toBeInTheDocument();
    expect(within(toasts()).queryByRole("button", { name: "Open" })).not.toBeInTheDocument();
  });

  it("a double click on Put in or Take back sends one request each", async () => {
    const { calls } = renderToday({
      "GET /api/today": { body: { ...TODAY, found: [FOUND] } },
      "POST /api/items/quick": async () => {
        await new Promise((r) => setTimeout(r, 30));
        return { body: { created: [CREATED], skipped: [] } };
      },
      "POST /api/items/11/discard": async () => {
        await new Promise((r) => setTimeout(r, 30));
        return { status: 204, body: null };
      },
    });
    const put = await screen.findByRole("button", { name: "Put in To pay" });
    // two clicks before React re-renders (a double click on a slow machine)
    put.click();
    put.click();
    const takeBack = await within(toasts()).findByRole("button", { name: "Undo" });
    expect(posts(calls, "/api/items/quick")).toHaveLength(1);
    // the toast goes on the first click; fire both clicks at the same button
    takeBack.click();
    takeBack.click();
    expect(await within(toasts()).findByText("Taken back: Scan⟨U+202E⟩bill")).toBeInTheDocument();
    expect(posts(calls, "/api/items/11/discard")).toHaveLength(1);
  });

  it("Open in the Put in toast goes to the new item", async () => {
    const { user } = renderToday({
      "GET /api/today": { body: { ...TODAY, found: [FOUND] } },
      "POST /api/items/quick": { body: { created: [CREATED], skipped: [] } },
    });
    await user.click(await screen.findByRole("button", { name: "Put in To pay" }));
    await user.click(await within(toasts()).findByRole("button", { name: "Open" }));
    expect(screen.getByTestId("where")).toHaveTextContent("/trays/to-pay?item=11");
  });

  it("Take back of a changed item says to mark it done instead", async () => {
    const { user } = renderToday({
      "GET /api/today": { body: { ...TODAY, found: [FOUND] } },
      "POST /api/items/quick": { body: { created: [CREATED], skipped: [] } },
      "POST /api/items/11/discard": {
        status: 409,
        body: { error: "item was changed — mark it done instead" },
      },
    });
    await user.click(await screen.findByRole("button", { name: "Put in To pay" }));
    await user.click(await within(toasts()).findByRole("button", { name: "Undo" }));
    expect(
      await within(toasts()).findByText(
        "Could not take back Scan⟨U+202E⟩bill: item was changed — mark it done instead",
      ),
    ).toBeInTheDocument();
  });

  it("a file already in the tray is skipped and the toast says so", async () => {
    const { user } = renderToday({
      "GET /api/today": { body: { ...TODAY, found: [FOUND] } },
      "POST /api/items/quick": { body: { created: [], skipped: ["d9"] } },
    });
    await user.click(await screen.findByRole("button", { name: "Put in To pay" }));
    expect(await within(toasts()).findByText("scan⟨U+202E⟩bill.pdf: already in To pay")).toBeInTheDocument();
    await user.click(within(toasts()).getByRole("button", { name: "Open" }));
    expect(screen.getByTestId("where")).toHaveTextContent("/trays/to-pay");
  });

  it("a failed Put in shows the error", async () => {
    const { user } = renderToday({
      "GET /api/today": { body: { ...TODAY, found: [FOUND] } },
      "POST /api/items/quick": { status: 404, body: { error: "no such tray" } },
    });
    await user.click(await screen.findByRole("button", { name: "Put in To pay" }));
    expect(
      await within(toasts()).findByText("Could not put scan⟨U+202E⟩bill.pdf in To pay: no such tray"),
    ).toBeInTheDocument();
  });

  it("shows the open collections that need attention", async () => {
    renderToday();
    const collections = await screen.findByRole("region", { name: "Collections to do" });
    const collection = within(collections).getByRole("link", { name: "Sauna⟨U+202E⟩conversion" });
    expect(collection).toHaveAttribute("href", "/collections/7");
    expect(collections).toHaveTextContent("23 files · 2 checklist items open");
    expect(collections).toHaveTextContent("still⟨U+200B⟩needed");
  });

  it("links to the Ongoing conversion when entries are unmanaged; no banner otherwise", async () => {
    renderToday({ "GET /api/today": { body: { ...TODAY, unmanaged_ongoing: 3 } } });
    const banner = await screen.findByRole("region", { name: "Ongoing" });
    expect(banner).toHaveTextContent("3 entries in ##. Ongoing are not in the app yet.");
    expect(within(banner).getByRole("link", { name: "Convert" })).toHaveAttribute("href", "/ongoing");
  });

  it("says once when the Ongoing sync keeps failing", async () => {
    renderToday({
      "GET /api/today": { body: { ...TODAY, ongoing_sync_failure: "stopped at symlink X\u200B: EIO" } },
    });
    const notice = await screen.findByText(/Ongoing sync is failing/);
    expect(notice).toHaveTextContent("Ongoing sync is failing: stopped at symlink X⟨U+200B⟩: EIO");
    expect(screen.getAllByText(/Ongoing sync is failing/)).toHaveLength(1);
  });

  it("no Ongoing banner when everything is managed", async () => {
    renderToday();
    await screen.findByRole("article", { name: "Northpower sähkö" });
    expect(screen.queryByRole("link", { name: "Convert ##. Ongoing" })).not.toBeInTheDocument();
  });

  it("warns about reminder errors and skipped checks, notes skipped tray files", async () => {
    renderToday({
      "GET /api/today": {
        body: {
          ...TODAY,
          reminders: { last_run: null, errors: { email: "login\u202Efailed" }, skipped: "another run is busy" },
          tray_errors: [{ file: "bad\u200B.yaml", message: "line 2: id: required" }],
        },
      },
    });
    const reminders = await screen.findByRole("region", { name: "Reminders" });
    expect(within(reminders).getByText(/email: login⟨U\+202E⟩failed/)).toHaveClass("notice");
    expect(within(reminders).getByText(/Check skipped: another run is busy/)).toHaveClass("notice");
    expect(reminders).toHaveTextContent("Not checked yet.");
    expect(screen.getByText(/bad⟨U\+200B⟩\.yaml: line 2: id: required/)).toBeInTheDocument();
  });

  it("the Reminders card says when the reminders last ran", async () => {
    renderToday({
      "GET /api/today": {
        body: { ...TODAY, reminders: { last_run: "2026-10-19T08:30:00", errors: {}, skipped: null } },
      },
    });
    const reminders = await screen.findByRole("region", { name: "Reminders" });
    expect(reminders).toHaveTextContent("Last checked today at 08:30");
  });

  it("says when nothing needs attention", async () => {
    renderToday({
      "GET /api/today": { body: { ...TODAY, attention: [], inbox_stats: { ...TODAY.inbox_stats, count: 0 } } },
    });
    expect(await screen.findByText("All clear")).toBeInTheDocument();
  });

  it("never says nothing needs attention while an overdue bill waits in the inbox", async () => {
    renderToday({
      "GET /api/today": { body: { ...TODAY, attention: [], inbox_stats: { ...TODAY.inbox_stats, overdue: 1 } } },
    });
    expect(await screen.findByText("35 to file · 1 overdue")).toBeInTheDocument();
    expect(screen.queryByText("All clear")).not.toBeInTheDocument();
  });

  it("shows a load error", async () => {
    renderToday({ "GET /api/today": { status: 500, body: { error: "boom" } } });
    expect(await screen.findByRole("alert")).toHaveTextContent(/Could not load Today/);
  });
});

describe("Today card layout", () => {
  /** The cards' titles in page order: the first column, then the second. */
  const order = () =>
    [...document.querySelectorAll<HTMLElement>(".today-col > .today-slot")].map(
      (slot) => slot.querySelector("h3")!.textContent,
    );
  // dealt out between the columns by the cards' rough heights (the first five, then the rest)
  const DEFAULT_ORDER = ["Inbox", "To action", "To⟨U+200B⟩read", "Collections to do", "Reminders", "To pay", "Starred"];
  const header = (name: string) => card(name).querySelector("header")!;
  const foundN = (n: number) =>
    Array.from({ length: n }, (_, i) => ({ ...FOUND, drive_id: `d${i}`, name: `scan ${i}.pdf` }));

  it("each card folds from its chevron button down to its headline; the fold is kept after a remount", async () => {
    const { user, view } = renderToday();
    await screen.findByRole("article", { name: "Northpower sähkö" });
    const fold = within(card("To pay")).getByRole("button", { name: "Collapse To pay" });
    expect(fold).toHaveAttribute("aria-expanded", "true");
    await user.click(fold);
    const pay = card("To pay");
    expect(within(pay).getByRole("button", { name: "Expand To pay" })).toHaveAttribute("aria-expanded", "false");
    expect(within(pay).queryByRole("article")).not.toBeInTheDocument();
    expect(pay).toHaveTextContent(formatMoney("412.90"));
    expect(pay).toHaveTextContent("4 open");
    expect(pay).toHaveTextContent("1 overdue");

    view.unmount();
    renderToday();
    const again = await screen.findByRole("region", { name: "To pay" });
    expect(within(again).getByRole("button", { name: "Expand To pay" })).toBeInTheDocument();
    expect(within(again).queryByRole("article")).not.toBeInTheDocument();
    expect(screen.getByRole("article", { name: "Water pipe inspection" })).toBeInTheDocument(); // To action stays open
  });

  it("folded, To action shows its next date and To read its count", async () => {
    const { user } = renderToday();
    await screen.findByRole("article", { name: "Water pipe inspection" });
    await user.click(screen.getByRole("button", { name: "Collapse To action" }));
    await user.click(screen.getByRole("button", { name: "Collapse To⟨U+200B⟩read" }));
    const action = card("To action");
    expect(within(action).queryByRole("article")).not.toBeInTheDocument();
    expect(action).toHaveTextContent("Next: Water pipe inspection");
    expect(within(action).getByText("today")).toHaveClass("tag-orange");
    const read = card("To⟨U+200B⟩read");
    expect(within(read).queryByRole("article")).not.toBeInTheDocument();
    expect(within(read).getByText("6")).toHaveClass("today-big");
  });

  it("the Inbox starts folded when more than 5 were found: the count and age bar, no Found list", async () => {
    const { user } = renderToday({ "GET /api/today": { body: { ...TODAY, found: foundN(7) } } });
    const inbox = await screen.findByRole("region", { name: "Inbox" });
    expect(inbox).toHaveTextContent("35 documents");
    expect(within(inbox).getByRole("img", { name: "10 this week, 5 last week, 20 older" })).toBeInTheDocument();
    expect(within(inbox).queryByRole("list", { name: "Found in the inbox" })).not.toBeInTheDocument();
    expect(within(inbox).queryByRole("button", { name: /^Put in/ })).not.toBeInTheDocument();

    await user.click(within(inbox).getByRole("button", { name: "Expand Inbox" }));
    const found = within(inbox).getByRole("list", { name: "Found in the inbox" });
    expect(within(found).getAllByRole("listitem")).toHaveLength(5);
    await user.click(within(inbox).getByRole("button", { name: "Show 2 more" }));
    expect(within(found).getAllByRole("listitem")).toHaveLength(7);
  });

  it("the Inbox starts open with 5 found or fewer", async () => {
    renderToday({ "GET /api/today": { body: { ...TODAY, found: foundN(5) } } });
    const found = await screen.findByRole("list", { name: "Found in the inbox" });
    expect(within(found).getAllByRole("listitem")).toHaveLength(5);
    expect(screen.queryByRole("button", { name: /^Show \d+ more$/ })).not.toBeInTheDocument();
    expect(within(card("Inbox")).getByRole("button", { name: "Collapse Inbox" })).toBeInTheDocument();
  });

  it("Move up and Move down in a card's ⋯ menu reorder the cards, kept after a remount; Reset layout restores", async () => {
    const { user, view } = renderToday();
    await screen.findByRole("article", { name: "Northpower sähkö" });
    expect(order()).toEqual(DEFAULT_ORDER);

    await user.click(within(card("Inbox")).getByRole("button", { name: "More for Inbox" }));
    expect(screen.getByRole("menuitem", { name: "Move up" })).toBeDisabled();
    await user.click(screen.getByRole("menuitem", { name: "Move down" }));
    expect(order()).toEqual(["To action", "Inbox", "To⟨U+200B⟩read", "Collections to do", "Reminders", "To pay", "Starred"]);
    // the focus stays with the moved card's menu, so the keys can move it again
    expect(document.activeElement).toBe(within(card("Inbox")).getByRole("button", { name: "More for Inbox" }));

    await user.click(within(card("Collections to do")).getByRole("button", { name: "More for Collections to do" }));
    await user.click(screen.getByRole("menuitem", { name: "Move up" }));
    expect(order()).toEqual(["To action", "Inbox", "Collections to do", "To⟨U+200B⟩read", "Reminders", "To pay", "Starred"]);

    await user.click(within(card("Starred")).getByRole("button", { name: "More for Starred" }));
    expect(screen.getByRole("menuitem", { name: "Move down" })).toBeDisabled();
    await user.keyboard("{Escape}");

    view.unmount();
    renderToday();
    await screen.findByRole("article", { name: "Northpower sähkö" });
    expect(order()).toEqual(["To action", "Inbox", "Collections to do", "To⟨U+200B⟩read", "Reminders", "To pay", "Starred"]);

    await user.click(within(card("Inbox")).getByRole("button", { name: "More for Inbox" }));
    await user.click(screen.getByRole("menuitem", { name: "Reset layout" }));
    expect(order()).toEqual(DEFAULT_ORDER);
    expect(localStorage.getItem(LAYOUT_KEY)).toBeNull();
  });

  it("dragging a card by its header drops it before another card or at the end of a column", async () => {
    renderToday();
    await screen.findByRole("article", { name: "Northpower sähkö" });
    expect(header("Starred")).toHaveAttribute("draggable", "true");

    const dt = dataTransfer();
    fireEvent.dragStart(header("Starred"), { dataTransfer: dt });
    expect(dt.types).toEqual([CARD_DRAG_TYPE]); // never files: no application/x-dam-files
    dt.protectedMode = true; // while hovering, a page sees the types only
    expect(fireEvent.dragOver(card("Inbox"), { dataTransfer: dt })).toBe(false); // accepted
    dt.protectedMode = false;
    fireEvent.drop(card("Inbox"), { dataTransfer: dt });
    fireEvent.dragEnd(header("Starred"), { dataTransfer: dt });
    expect(order()).toEqual(["Starred", "Inbox", "To action", "To⟨U+200B⟩read", "Collections to do", "Reminders", "To pay"]);

    const again = dataTransfer();
    fireEvent.dragStart(header("Inbox"), { dataTransfer: again });
    const columns = document.querySelectorAll<HTMLElement>(".today-col");
    fireEvent.dragOver(columns[1], { dataTransfer: again });
    fireEvent.drop(columns[1], { dataTransfer: again });
    expect(order()).toEqual(["Starred", "To action", "To⟨U+200B⟩read", "Collections to do", "Reminders", "To pay", "Inbox"]);
    expect(JSON.parse(localStorage.getItem(LAYOUT_KEY)!).order).toEqual([
      "starred",
      "tray:to-action",
      "tray:to-read",
      "collections",
      "clear", // hidden here (no tray is clear) but it keeps its place
      "reminders",
      "|",
      "tray:to-pay",
      "inbox",
    ]);
  });

  it("Move down past the bottom of a column puts the focus on the card's menu in the next column", async () => {
    const { user } = renderToday();
    await screen.findByRole("article", { name: "Northpower sähkö" });
    await user.click(within(card("Reminders")).getByRole("button", { name: "More for Reminders" }));
    await user.click(screen.getByRole("menuitem", { name: "Move down" }));
    expect(order()).toEqual(DEFAULT_ORDER); // the same page order, but in the other column
    const columns = document.querySelectorAll<HTMLElement>(".today-col");
    expect(columns[1].contains(card("Reminders"))).toBe(true); // a new element in the other column
    expect(document.activeElement).toBe(within(card("Reminders")).getByRole("button", { name: "More for Reminders" }));
    await user.click(screen.getByRole("button", { name: "More for Reminders" })); // it opens again: keys go on
    await user.click(screen.getByRole("menuitem", { name: "Move up" }));
    expect(order()).toEqual(DEFAULT_ORDER);
    expect(columns[0].contains(card("Reminders"))).toBe(true);
    expect(document.activeElement).toBe(within(card("Reminders")).getByRole("button", { name: "More for Reminders" }));
  });

  it("a drop in the gap between two cards lands between them (the nearest slot by height)", async () => {
    renderToday();
    await screen.findByRole("article", { name: "Northpower sähkö" });
    const columns = document.querySelectorAll<HTMLElement>(".today-col");
    // the second column's cards: 100 px tall with 10 px gaps
    [...columns[1].querySelectorAll<HTMLElement>(".today-slot")].forEach((slot, i) => {
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
      const event = createEvent[type](columns[1], { dataTransfer: dt });
      Object.defineProperty(event, "clientY", { value: clientY });
      fireEvent(columns[1], event);
    };
    const dt = dataTransfer();
    fireEvent.dragStart(header("Inbox"), { dataTransfer: dt });
    at("dragOver", 105, dt); // between To pay (0–100) and Starred (110–210)
    expect(card("Starred").closest(".today-slot")).toHaveAttribute("data-drop", "before");
    at("drop", 105, dt);
    expect(order()).toEqual(["To action", "To⟨U+200B⟩read", "Collections to do", "Reminders", "To pay", "Inbox", "Starred"]);

    const below = dataTransfer();
    fireEvent.dragStart(header("To action"), { dataTransfer: below });
    at("drop", 10_000, below); // under the last card: the end of the column
    expect(order().at(-1)).toBe("To action");
  });

  it("files dragged over a card are not taken as a card", async () => {
    renderToday();
    await screen.findByRole("article", { name: "Northpower sähkö" });
    const dt = dataTransfer();
    setDragFiles({ dataTransfer: dt } as unknown as DragEvent, ["d1"], "bill.pdf");
    dt.setData(CARD_DRAG_TYPE, "reminders"); // even a forged card id beside the files
    expect(fireEvent.dragOver(card("To pay"), { dataTransfer: dt })).toBe(true); // not accepted
    fireEvent.drop(card("To pay"), { dataTransfer: dt });
    expect(order()).toEqual(DEFAULT_ORDER);
    document.dispatchEvent(new Event("dragend"));
  });

  it("a saved layout naming a removed tray still shows every card; a new card goes to its default place", async () => {
    localStorage.setItem(
      LAYOUT_KEY,
      JSON.stringify({ order: ["tray:gone", "tray:to-action", "|", "reminders", "inbox"], collapsed: { "tray:gone": true } }),
    );
    renderToday();
    await screen.findByRole("article", { name: "Northpower sähkö" });
    expect(order()).toEqual(["To action", "To⟨U+200B⟩read", "Collections to do", "Reminders", "Inbox", "To pay", "Starred"]);
  });

  describe("one figure per tray card, and collections only when they need attention", () => {
    const collection = (id: number, name: string, files: number, open_checks: number, in_inbox: number) => ({
      id,
      name,
      files,
      open_checks,
      note_excerpt: "",
      in_inbox,
    });

    it("every tray card leads with one big figure: the total for To pay, the open count otherwise", async () => {
      renderToday();
      await screen.findByRole("article", { name: "Water pipe inspection" });
      expect(within(card("To pay")).getByText("412,90 €")).toHaveClass("today-big");
      expect(card("To pay")).toHaveTextContent("4 open · 1 overdue");
      expect(within(card("To action")).getByText("1")).toHaveClass("today-big");
      expect(card("To action")).toHaveTextContent("1 open");
      expect(within(card("To⟨U+200B⟩read")).getByText("6")).toHaveClass("today-big");
      expect(card("To⟨U+200B⟩read")).toHaveTextContent("6 open · oldest");
    });

    it("an empty tray joins the one Clear card instead of showing a Nothing open. card", async () => {
      const body = {
        ...TODAY,
        attention: TODAY.attention.filter((a) => a.tray !== "to-action"),
        open_items: TODAY.open_items.filter((t) => t.tray_id !== "to-action"),
        overview: {
          ...TODAY.overview,
          trays: TODAY.overview.trays.map((t) => (t.tray_id === "to-action" ? { ...t, open: 0 } : t)),
        },
      };
      renderToday({ "GET /api/today": { body } });
      const clear = await screen.findByRole("region", { name: "Clear" });
      expect(clear).toHaveTextContent("To action is clear.");
      expect(within(clear).getByRole("link", { name: "To action" })).toHaveAttribute("href", "/trays/to-action");
      expect(screen.queryByRole("region", { name: "To action" })).toBeNull();
      expect(screen.queryByText("Nothing open.")).toBeNull();
    });

    it("lists only the collections with open checklist items or files still in the inbox", async () => {
      const collections = [
        collection(7, "Sauna", 23, 2, 0),
        collection(8, "House sale", 4, 0, 1),
        collection(9, "Riverside", 0, 0, 0),
      ];
      renderToday({ "GET /api/today": { body: { ...TODAY, overview: { ...TODAY.overview, collections } } } });
      const region = await screen.findByRole("region", { name: "Collections to do" });
      expect(within(region).getByRole("link", { name: "Sauna" })).toBeInTheDocument();
      expect(within(region).getByRole("link", { name: "House sale" })).toBeInTheDocument();
      expect(region).toHaveTextContent("4 files · 1 file in the inbox");
      expect(within(region).queryByRole("link", { name: "Riverside" })).not.toBeInTheDocument();
    });

    it("no collections card when none needs attention", async () => {
      const collections = [collection(9, "Riverside", 0, 0, 0), collection(10, "Done deal", 12, 0, 0)];
      renderToday({ "GET /api/today": { body: { ...TODAY, overview: { ...TODAY.overview, collections } } } });
      await screen.findByRole("article", { name: "Water pipe inspection" });
      expect(screen.queryByRole("region", { name: /Collections/ })).not.toBeInTheDocument();
      expect(document.querySelector('[data-card-id="collections"]')).toBeNull();
    });
  });
});

describe("Starred card and the Important notice (stars)", () => {
  const member = (drive_id: string, path: string, extra: Record<string, unknown> = {}) => ({
    drive_id,
    path,
    is_dir: false,
    missing: false,
    quarantined: false,
    is_link: false,
    group_id: null,
    marks: ["starred"],
    ...extra,
  });
  const STARRED = {
    id: 1,
    name: "Ongoing",
    kind: "starred",
    members: [
      member("p", "10. Financial/FinancialPlanning_Management.xlsx", { marks: ["starred", "important"] }),
      member("a", "20. Plans/2026_Plan.xlsx"),
      member("dir", "30. Car", { is_dir: true }),
    ],
    groups: [],
  };

  it("lists the ★ files A–Z with Open and Quick Look; Open launches by drive id", async () => {
    const { calls, user } = renderToday({
      "GET /api/marks/collection/starred": { body: STARRED },
      "POST /api/files/a/open": { status: 204, body: null },
      "GET /api/files/a/links": { body: { items: [], collections: [], note: "" } },
      "GET /api/files/a": { body: { record: { drive_id: "a", path: "20. Plans/2026_Plan.xlsx", name: "2026_Plan.xlsx", ext: "xlsx", marks: ["starred"] }, tags: [], link_target_id: null, link_target_path: null, link_target_inside: false } },
    });
    const list = await within(await screen.findByRole("region", { name: "Starred" })).findByRole("list", { name: "Starred files" });
    const rows = within(list).getAllByRole("listitem");
    expect(rows.map((r) => r.querySelector(".starred-name")!.textContent)).toEqual([
      "30. Car", // numbers in names sort as numbers (30 before 2026)
      "2026_Plan.xlsx",
      "FinancialPlanning_Management.xlsx",
    ]);
    expect(within(rows[2]).getByRole("img", { name: "Important" })).toBeInTheDocument();
    // a folder is shown in Finder only: no Quick Look, no Open
    expect(within(rows[0]).queryByRole("button", { name: "Quick Look" })).toBeNull();
    expect(within(rows[0]).queryByRole("button", { name: "Open" })).toBeNull();
    expect(within(rows[0]).getByRole("button", { name: "Show in Finder" })).toBeInTheDocument();
    await user.click(within(rows[1]).getByRole("button", { name: "Open" }));
    await waitFor(() => expect(posts(calls, "/api/files/a/open")).toHaveLength(1));
    await user.click(within(rows[1]).getByRole("button", { name: "Quick Look" }));
    expect(await screen.findByRole("dialog", { name: "Quick Look: 2026_Plan.xlsx" })).toBeInTheDocument();
  });

  it("☆ unstars a row in one click; the toast offers Star again", async () => {
    const { calls, user } = renderToday({
      "GET /api/marks/collection/starred": { body: STARRED },
      "POST /api/marks/unstar": { body: { collection: STARRED, batch: null, problems: [], ongoing_status: null } },
      "POST /api/marks/star": { body: { collection: STARRED, batch: null, problems: [], ongoing_status: null } },
    });
    const list = await within(await screen.findByRole("region", { name: "Starred" })).findByRole("list", { name: "Starred files" });
    const row = within(list).getAllByRole("listitem")[1]; // 2026_Plan.xlsx
    await user.click(within(row).getByRole("button", { name: "Unstar" }));
    await waitFor(() => expect(posts(calls, "/api/marks/unstar")).toHaveLength(1));
    expect(posts(calls, "/api/marks/unstar")[0].body).toEqual({ drive_ids: ["a"] });
    await user.click(await within(toasts()).findByRole("button", { name: "Undo" }));
    await waitFor(() => expect(posts(calls, "/api/marks/star")).toHaveLength(1));
    expect(posts(calls, "/api/marks/star")[0].body).toEqual({ drive_ids: ["a"] });
  });

  it("two Unstar clicks in one tick send one request (the inFlight guard)", async () => {
    const { calls } = renderToday({
      "GET /api/marks/collection/starred": { body: STARRED },
      "POST /api/marks/unstar": { body: { collection: STARRED, batch: null, problems: [], ongoing_status: null } },
    });
    const list = await within(await screen.findByRole("region", { name: "Starred" })).findByRole("list", { name: "Starred files" });
    const button = within(within(list).getAllByRole("listitem")[1]).getByRole("button", { name: "Unstar" });
    act(() => {
      button.click();
      button.click();
    });
    await waitFor(() => expect(posts(calls, "/api/marks/unstar")).toHaveLength(1));
    await new Promise((r) => setTimeout(r, 20));
    expect(posts(calls, "/api/marks/unstar")).toHaveLength(1);
  });

  it("the card's Quick Look has Trash like every Quick Look: the bin dry-runs that file; an Important one is refused up front", async () => {
    const { calls, user } = renderToday({
      "GET /api/marks/collection/starred": { body: STARRED },
      "GET /api/files/a": { body: { record: { drive_id: "a", path: "20. Plans/2026_Plan.xlsx", name: "2026_Plan.xlsx", ext: "xlsx", marks: ["starred"] }, tags: [] } },
      "GET /api/files/p": { body: { record: { drive_id: "p", path: "10. Financial/FinancialPlanning_Management.xlsx", name: "FinancialPlanning_Management.xlsx", ext: "xlsx", marks: ["starred", "important"] }, tags: [] } },
      "POST /api/quarantine": quarantineRoute({ a: "20. Plans/2026_Plan.xlsx" }),
    });
    const list = await within(await screen.findByRole("region", { name: "Starred" })).findByRole("list", { name: "Starred files" });
    const rows = within(list).getAllByRole("listitem");
    await user.click(within(rows[2]).getByRole("button", { name: "Quick Look" })); // the Important one
    const important = await screen.findByRole("dialog", { name: "Quick Look: FinancialPlanning_Management.xlsx" });
    const refused = within(important).getByRole("button", { name: "Move to To Delete" });
    expect(refused).toBeDisabled();
    expect(refused.parentElement).toHaveAttribute("data-tip", "This file is marked Important; unmark it first");
    await user.keyboard("{Escape}");
    await user.click(within(rows[1]).getByRole("button", { name: "Quick Look" }));
    const ql = await screen.findByRole("dialog", { name: "Quick Look: 2026_Plan.xlsx" });
    await user.click(within(ql).getByRole("button", { name: "Move to To Delete" }));
    await screen.findByRole("dialog", { name: "Move to To Delete?" });
    expect(ql).not.toBeInTheDocument();
    expect(posts(calls, "/api/quarantine").map((c) => c.body)).toEqual([{ drive_ids: ["a"], dry_run: true }]);
  });

  it("folds to a count like every card, and says when nothing is starred", async () => {
    const { user, view } = renderToday({ "GET /api/marks/collection/starred": { body: STARRED } });
    const starred = await screen.findByRole("region", { name: "Starred" });
    await within(starred).findByRole("list", { name: "Starred files" });
    await user.click(within(starred).getByRole("button", { name: "Collapse Starred" }));
    expect(starred).toHaveTextContent("3 starred files");
    expect(within(starred).queryByRole("list")).toBeNull();
    view.unmount();
    localStorage.clear();
    renderToday({ "GET /api/marks/collection/starred": { body: { ...STARRED, members: [] } } });
    expect(await screen.findByText(/No starred files\. Click ★ on a file/)).toBeInTheDocument();
  });

  it("links to Convert ##. Important when its entries are unmanaged; no banner otherwise", async () => {
    const { view } = renderToday({ "GET /api/today": { body: { ...TODAY, unmanaged_important: 3 } } });
    const banner = await screen.findByRole("region", { name: "Convert ##. Important" });
    expect(banner).toHaveTextContent("3 entries in ##. Important are not in the app yet.");
    expect(within(banner).getByRole("link", { name: "Convert" })).toHaveAttribute("href", "/important/convert");
    view.unmount();
    renderToday();
    await screen.findByRole("region", { name: "Inbox" });
    expect(screen.queryByRole("region", { name: "Convert ##. Important" })).toBeNull();
  });
});
