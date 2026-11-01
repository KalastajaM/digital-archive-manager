import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { AttentionItem, Item, Today as TodayData, TrayDef } from "../api/client";
import { AgeBar } from "../components/AgeBar";
import { CopyButton } from "../components/CopyButton";
import { RelativeDate, useLocalClock, useLocalToday } from "../components/RelativeDate";
import { UrgencyTag, urgency } from "../components/UrgencyTag";
import { formatMoney, groupIban } from "../format";
import { type Call, mockFetch, quarantineRoute, renderWithProviders } from "../test-utils";
import { longDate } from "../format";
import Today from "./Today";

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
  content_changes: { count: 0, rows: [] },
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
  marked: 0,
  reading_codes: 0,
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
const posts = (calls: Call[], url: string) => calls.filter((c) => c.method === "POST" && c.url === url);
const toasts = () => document.querySelector<HTMLElement>(".toasts")!;

describe("formatting", () => {
  it("shows money with a comma and the euro sign, IBANs grouped in fours", () => {
    expect(formatMoney("84.20")).toBe("84,20 €");
    expect(formatMoney("-5.00")).toBe("-5,00 €");
    expect(groupIban("FI2112345600000785")).toBe("FI21 1234 5600 0007 85");
  });

  it("writes the long date", () => {
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

  it("the clock's hour moves on too", () => {
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
  it("Done stays disabled when the tray settings cannot be loaded", async () => {
    renderToday({ "GET /api/trays": { status: 500, body: { error: "x" } } });
    expect(await screen.findByText(/Tray settings could not be loaded/)).toBeInTheDocument();
    expect(within(row("Northpower sähkö")).getByRole("checkbox", { name: /^Mark Northpower sähkö/ })).toBeDisabled();
  });

  it("the Inbox card's File N marked opens the marked panel, and is hidden when none are marked", async () => {
    const { user } = renderToday({ "GET /api/today": { body: { ...TODAY, marked: 3 } } });
    const inbox = await screen.findByRole("region", { name: "Inbox" });
    const link = within(inbox).getByRole("link", { name: "File 3 marked" });
    expect(link).toHaveAttribute("href", "/inbox?marked=1");
    await user.click(link);
    expect(screen.getByTestId("where")).toHaveTextContent("/inbox?marked=1");
  });

  it("the Inbox card has no File N marked when no file is marked", async () => {
    renderToday();
    const inbox = await screen.findByRole("region", { name: "Inbox" });
    expect(within(inbox).queryByRole("link", { name: /marked/ })).not.toBeInTheDocument();
    expect(within(inbox).queryByText("Reading filing codes…")).not.toBeInTheDocument();
  });

  it("the Inbox card says Reading filing codes… while stickers are read, beside File N marked or alone", async () => {
    renderToday({ "GET /api/today": { body: { ...TODAY, marked: 2, reading_codes: 1 } } });
    let inbox = await screen.findByRole("region", { name: "Inbox" });
    expect(within(inbox).getByRole("link", { name: "File 2 marked" })).toBeInTheDocument();
    expect(within(inbox).getByText("Reading filing codes…")).toHaveAttribute("role", "status");
    cleanup();
    renderToday({ "GET /api/today": { body: { ...TODAY, marked: 0, reading_codes: 3 } } });
    inbox = await screen.findByRole("region", { name: "Inbox" });
    expect(within(inbox).queryByRole("link", { name: /marked/ })).not.toBeInTheDocument();
    expect(within(inbox).getByText("Reading filing codes…")).toBeInTheDocument();
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
    expect(collection).toHaveAttribute("href", "/browse?tree=collections&q=collection%3ASauna%E2%80%AEconversion");
    expect(collections).toHaveTextContent("23 files · 2 checklist items open");
    expect(collections).toHaveTextContent("still⟨U+200B⟩needed");
  });

  it("says once when the Ongoing sync keeps failing", async () => {
    renderToday({
      "GET /api/today": { body: { ...TODAY, ongoing_sync_failure: "stopped at symlink X\u200B: EIO" } },
    });
    const notice = await screen.findByText(/Ongoing sync is failing/);
    expect(notice).toHaveTextContent("Ongoing sync is failing: stopped at symlink X⟨U+200B⟩: EIO");
    expect(screen.getAllByText(/Ongoing sync is failing/)).toHaveLength(1);
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

  it("shows a load error", async () => {
    renderToday({ "GET /api/today": { status: 500, body: { error: "boom" } } });
    expect(await screen.findByRole("alert")).toHaveTextContent(/Could not load Today/);
  });
});

describe("Collections to do", () => {
  const collection = (id: number, name: string, files: number, open_checks: number, in_inbox: number) => ({
    id,
    name,
    files,
    open_checks,
    note_excerpt: "",
    in_inbox,
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

  it("no Collections section when none needs attention", async () => {
    const collections = [collection(9, "Riverside", 0, 0, 0), collection(10, "Done deal", 12, 0, 0)];
    renderToday({ "GET /api/today": { body: { ...TODAY, overview: { ...TODAY.overview, collections } } } });
    await screen.findByRole("article", { name: "Water pipe inspection" });
    expect(screen.queryByRole("region", { name: /Collections/ })).not.toBeInTheDocument();
    expect(document.querySelector('[data-card-id="collections"]')).toBeNull();
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
    // the whole card is the starred list: no ★ on its rows
    expect(within(list).queryByRole("img", { name: "Starred" })).not.toBeInTheDocument();
    // a folder is shown in Finder only: no Quick Look, no Open
    expect(within(rows[0]).queryByRole("button", { name: "Quick Look" })).toBeNull();
    expect(within(rows[0]).queryByRole("button", { name: "Open" })).toBeNull();
    expect(within(rows[0]).getByRole("button", { name: "Show in Finder" })).toBeInTheDocument();
    await user.click(within(rows[1]).getByRole("button", { name: "Open" }));
    await waitFor(() => expect(posts(calls, "/api/files/a/open")).toHaveLength(1));
    await user.click(within(rows[1]).getByRole("button", { name: "Quick Look" }));
    expect(await screen.findByRole("dialog", { name: "Quick Look: 2026_Plan.xlsx" })).toBeInTheDocument();
  });

  it("a row wears the tray-row markup: the hints sit under the name, a long name has its tooltip and keeps its mark", async () => {
    const long = `${"Very_long_name_".repeat(12)}.pdf`;
    renderToday({
      "GET /api/marks/collection/starred": {
        body: {
          ...STARRED,
          members: [
            member("l", `20. Plans/${long}`, { marks: ["starred", "important"] }),
            member("m", "20. Plans/gone.pdf", { missing: true }),
            member("q", "##. To Delete/old.pdf", { quarantined: true }),
          ],
        },
      },
    });
    const list = await within(await screen.findByRole("region", { name: "Starred" })).findByRole("list", { name: "Starred files" });
    expect(list).toHaveClass("tn-rows");
    const [gone, old, longRow] = within(list).getAllByRole("listitem"); // A–Z
    for (const row of [gone, old, longRow]) expect(row).toHaveClass("today-row");
    const link = within(longRow).getByRole("link", { name: long });
    expect(link).toHaveAttribute("title", `Show 20. Plans/${long} in Browse`);
    // the mark is beside the name, not inside what the ellipsis cuts
    expect(link.querySelector(".mark-icons")).toBeNull();
    expect(within(longRow).getByRole("img", { name: "Important" })).toBeInTheDocument();
    expect(gone.querySelector(".today-row-sub")).toHaveTextContent("missing");
    expect(old.querySelector(".today-row-sub")).toHaveTextContent("in ##. To Delete");
  });

  it("folds to a count while arranging, and says when nothing is starred", async () => {
    const { user, view } = renderToday({ "GET /api/marks/collection/starred": { body: STARRED } });
    const starred = await screen.findByRole("region", { name: "Starred" });
    await within(starred).findByRole("list", { name: "Starred files" });
    await user.click(screen.getByRole("button", { name: "Customize" }));
    await user.click(within(starred).getByRole("button", { name: "Collapse Starred" }));
    expect(starred).toHaveTextContent("3 starred files");
    expect(within(starred).queryByRole("list")).toBeNull();
    view.unmount();
    localStorage.clear();
    renderToday({ "GET /api/marks/collection/starred": { body: { ...STARRED, members: [] } } });
    expect(await screen.findByText(/No starred files\. Click ★ on a file/)).toBeInTheDocument();
  });

  it("☆ unstars a row in one click; the toast offers Star again", async () => {
    const { calls, user } = renderToday({
      "GET /api/marks/collection/starred": { body: STARRED },
      "POST /api/marks/unstar": { body: { collection: STARRED, batch: null, problems: [], ongoing_status: null } },
      "POST /api/marks/star": { body: { collection: STARRED, batch: null, problems: [], ongoing_status: null } },
    });
    const list = await within(await screen.findByRole("region", { name: "Starred" })).findByRole("list", { name: "Starred files" });
    const row = within(list).getAllByRole("listitem")[1]; // 2026_Plan.xlsx
    await user.click(within(row).getByRole("button", { name: "Remove the star" }));
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
    const button = within(within(list).getAllByRole("listitem")[1]).getByRole("button", { name: "Remove the star" });
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

});
