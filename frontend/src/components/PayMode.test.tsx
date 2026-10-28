import { cleanup, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";
import type { Item, ItemBarcode, TrayDef } from "../api/client";
import { formatMoney, localToday } from "../format";
import { type Call, mockFetch, renderWithProviders } from "../test-utils";
import { Barcode } from "./Barcode";
import { sumOfBills } from "./usePayBills";

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
  },
  date_field: "due_date",
  summary: { sum: "amount" },
  done: { label: "Mark paid", fields: { paid_on: { type: "date", required: false, copy: false, default: "today" } } },
};
/** A second bill tray: bills are read from every tray with an IBAN field. */
const TAXES: TrayDef = { ...TO_PAY, id: "taxes", name: "Taxes", order: 2 };
const ASKS: TrayDef = {
  ...TO_PAY,
  done: { label: "Mark paid", fields: { paid_on: { type: "date", required: true, copy: false, default: null } } },
};

function bill(id: number, title: string, due: string | null, amount: string, tray = "to-pay", extra: Partial<Item> = {}): Item {
  return {
    id,
    tray_id: tray,
    title,
    fields: { payee: `${title} Oy`, due_date: due ?? "", amount, iban: "FI2112345600000785", reference: "RF18539007547034" },
    date: due,
    state: "open",
    created: 1_760_000_000 + id,
    done_at: null,
    done_fields: null,
    files: [`f${id}`],
    created_by_batch: null,
    missing_required: [],
    invalid_fields: [],
    tray_name: tray === "to-pay" ? "To pay" : "Taxes",
    tray_removed: false,
    ...extra,
  };
}
// by due date: Water (1), Electricity (2, in the other tray), Tax (3), Rent (4, no date)
const WATER = bill(1, "Water", "2026-10-15", "47.90");
const ELECTRICITY = bill(2, "Electricity", "2026-10-22", "84.20", "taxes");
const TAX = bill(3, "Tax", "2026-11-30", "310.00");
const RENT = bill(4, "Rent", null, "600.00");

const barcode = (n: number): ItemBarcode => ({
  code: `42112345600000785${String(n).repeat(37)}`.slice(0, 54),
  modules: [2, 1, 1, 2, 3, 1, 2],
  reason: null,
  printed: null,
  printed_fields: null,
  mismatch: [],
});

function renderPay(opts: { trays?: TrayDef[]; items?: Record<string, Item[]>; routes?: Parameters<typeof mockFetch>[0]; id?: number } = {}) {
  const items = opts.items ?? { "to-pay": [TAX, WATER, RENT], taxes: [ELECTRICITY] };
  const calls = mockFetch({
    "GET /api/trays": { body: { trays: opts.trays ?? [TO_PAY, TAXES], errors: [] } },
    ...Object.fromEntries(Object.entries(items).map(([tray, list]) => [`GET /api/trays/${tray}/items`, { body: list }])),
    ...Object.fromEntries([1, 2, 3, 4].map((n) => [`GET /api/items/${n}/barcode`, { body: barcode(n) }])),
    ...opts.routes,
  });
  const user = userEvent.setup();
  renderWithProviders(<Barcode itemId={opts.id ?? 1} />);
  return { calls, user };
}
const sheet = () => screen.getByRole("dialog", { name: "Bank barcode" });
const posts = (calls: Call[], url: string) => calls.filter((c) => c.method === "POST" && c.url === url);
async function openPayMode(user: ReturnType<typeof userEvent.setup>) {
  await user.click(await screen.findByRole("button", { name: /^Show large barcode/ }));
  return within(sheet());
}

afterEach(() => {
  cleanup();
  delete document.documentElement.dataset.style;
});

describe("Pay mode steps through the open bills", () => {
  it("says which bill it is on and what is open in total, across bill trays, earliest due date first", async () => {
    const { user } = renderPay();
    const pay = await openPayMode(user);
    expect(await pay.findByText(/^Bill 1 of 4/)).toBeInTheDocument();
    expect(pay.getByText(/open in total/).textContent?.replace(/\s/g, " ").trim()).toBe(`· ${formatMoney("1042.10")} open in total`.replace(/\s/g, " "));
    expect(pay.getByRole("button", { name: "Previous bill" })).toBeDisabled();
    expect(pay.getByRole("button", { name: "Next bill" })).toBeEnabled();
    expect(pay.getByText(barcode(1).code!)).toBeInTheDocument();
    expect(pay.getByLabelText("Payment details")).toHaveTextContent("Water Oy");
    // Electricity is in another tray but second by date
    await user.click(pay.getByRole("button", { name: "Next bill" }));
    expect(await pay.findByText(/^Bill 2 of 4/)).toBeInTheDocument();
    expect(pay.getByLabelText("Payment details")).toHaveTextContent("Electricity Oy");
    expect(pay.getByText(barcode(2).code!)).toBeInTheDocument();
  });

  it("steps back and forth, never past the first or the last (the bill without a date is last)", async () => {
    const { user } = renderPay();
    const pay = await openPayMode(user);
    await pay.findByText(/^Bill 1 of 4/);
    for (const n of [2, 3, 4]) {
      await user.click(pay.getByRole("button", { name: "Next bill" }));
      expect(await pay.findByText(new RegExp(`^Bill ${n} of 4`))).toBeInTheDocument();
    }
    expect(pay.getByRole("button", { name: "Next bill" })).toBeDisabled();
    expect(pay.getByLabelText("Payment details")).toHaveTextContent("Rent Oy");
    await user.click(pay.getByRole("button", { name: "Previous bill" }));
    expect(await pay.findByText(/^Bill 3 of 4/)).toBeInTheDocument();
    expect(sheet()).toBe(screen.getByRole("dialog")); // one sheet all the way
  });

  it("the arrow keys step too, but not while typing", async () => {
    const { user } = renderPay();
    const pay = await openPayMode(user);
    await pay.findByText(/^Bill 1 of 4/);
    await user.keyboard("{ArrowRight}");
    expect(await pay.findByText(/^Bill 2 of 4/)).toBeInTheDocument();
    await user.keyboard("{ArrowRight}{ArrowRight}");
    expect(await pay.findByText(/^Bill 4 of 4/)).toBeInTheDocument();
    await user.keyboard("{ArrowLeft}");
    expect(await pay.findByText(/^Bill 3 of 4/)).toBeInTheDocument();
    // a field in the sheet keeps its arrows
    const input = document.createElement("input");
    sheet().appendChild(input);
    input.focus();
    await user.keyboard("{ArrowLeft}");
    expect(pay.getByText(/^Bill 3 of 4/)).toBeInTheDocument();
    input.remove();
  });

  it("the title, amount and values follow the bill in the New look", async () => {
    document.documentElement.dataset.style = "new";
    const { user } = renderPay();
    const pay = await openPayMode(user);
    expect(await pay.findByRole("heading", { name: "Water" })).toBeInTheDocument();
    expect(pay.getAllByText("47,90 €")).toHaveLength(2); // the big total and its card
    expect(pay.getByRole("button", { name: "Copy payee" })).toBeInTheDocument();
    expect(pay.getByRole("list", { name: "How to pay with the barcode" })).toBeInTheDocument();
    await user.click(pay.getByRole("button", { name: "Next bill" }));
    expect(await pay.findByRole("heading", { name: "Electricity" })).toBeInTheDocument();
    expect(pay.getAllByText("84,20 €")).toHaveLength(2);
  });

  it("works the same in Classic, with no title heading", async () => {
    const { user } = renderPay();
    const pay = await openPayMode(user);
    expect(await pay.findByText(/^Bill 1 of 4/)).toBeInTheDocument();
    expect(pay.queryByRole("heading", { name: "Water" })).not.toBeInTheDocument();
    expect(pay.getByLabelText("Payment details")).toHaveTextContent("47,90 €");
  });

  it("a bill whose barcode cannot be built still shows its values, with the reason", async () => {
    const { user } = renderPay({
      routes: { "GET /api/items/2/barcode": { body: { ...barcode(2), code: null, modules: null, reason: "no IBAN" } } },
    });
    const pay = await openPayMode(user);
    await pay.findByText(/^Bill 1 of 4/);
    await user.click(pay.getByRole("button", { name: "Next bill" }));
    expect(await pay.findByText(/No barcode:/)).toHaveTextContent("no IBAN");
    expect(pay.getByLabelText("Payment details")).toHaveTextContent("Electricity Oy");
    expect(pay.queryByRole("button", { name: "Copy barcode number" })).not.toBeInTheDocument();
  });
});

describe("Mark paid in Pay mode", () => {
  it("marks the shown bill paid with the tray's defaults and moves on to the next bill", async () => {
    const { calls, user } = renderPay({ routes: { "POST /api/items/1/done": { body: { ...WATER, state: "done" } } } });
    const pay = await openPayMode(user);
    await pay.findByText(/^Bill 1 of 4/);
    await user.click(pay.getByRole("button", { name: "Mark paid" }));
    await waitFor(() => expect(posts(calls, "/api/items/1/done")).toHaveLength(1));
    expect(posts(calls, "/api/items/1/done")[0].body).toEqual({ fields: { paid_on: localToday() } });
    expect(await pay.findByText(/^Bill 2 of 4/)).toBeInTheDocument();
    expect(pay.getByLabelText("Payment details")).toHaveTextContent("Electricity Oy");
    // the sheet stayed open; the toast offers Undo
    expect(screen.getAllByRole("dialog")).toHaveLength(1);
    expect(screen.getByRole("button", { name: "Undo" })).toBeInTheDocument();
  });

  it("after the last bill it goes back to the previous one", async () => {
    const { calls, user } = renderPay({ routes: { "POST /api/items/4/done": { body: { ...RENT, state: "done" } } } });
    const pay = await openPayMode(user);
    await pay.findByText(/^Bill 1 of 4/);
    for (let n = 2; n <= 4; n++) await user.click(pay.getByRole("button", { name: "Next bill" }));
    await pay.findByText(/^Bill 4 of 4/);
    await user.click(pay.getByRole("button", { name: "Mark paid" }));
    await waitFor(() => expect(posts(calls, "/api/items/4/done")).toHaveLength(1));
    expect(await pay.findByText(/^Bill 3 of 4/)).toBeInTheDocument();
    expect(pay.getByLabelText("Payment details")).toHaveTextContent("Tax Oy");
  });

  it("closes when the only bill was paid", async () => {
    const { calls, user } = renderPay({
      items: { "to-pay": [WATER], taxes: [] },
      routes: { "POST /api/items/1/done": { body: { ...WATER, state: "done" } } },
    });
    const pay = await openPayMode(user);
    await pay.findByText(/^Bill 1 of 1/);
    await user.click(pay.getByRole("button", { name: "Mark paid" }));
    await waitFor(() => expect(posts(calls, "/api/items/1/done")).toHaveLength(1));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("a failed save stays on the bill and says so", async () => {
    const { user } = renderPay({ routes: { "POST /api/items/1/done": { status: 500, body: { error: "disk full" } } } });
    const pay = await openPayMode(user);
    await pay.findByText(/^Bill 1 of 4/);
    await user.click(pay.getByRole("button", { name: "Mark paid" }));
    expect(await screen.findByText(/Could not mark Water paid/)).toBeInTheDocument();
    expect(pay.getByText(/^Bill 1 of 4/)).toBeInTheDocument();
  });

  it("a tray whose done action needs a value asks for it in the sheet, then moves on", async () => {
    const { calls, user } = renderPay({
      trays: [ASKS, TAXES],
      routes: { "POST /api/items/1/done": { body: { ...WATER, state: "done" } } },
    });
    const pay = await openPayMode(user);
    await pay.findByText(/^Bill 1 of 4/);
    await user.click(pay.getByRole("button", { name: "Mark paid" }));
    const form = await screen.findByRole("form", { name: "Mark paid" });
    expect(posts(calls, "/api/items/1/done")).toHaveLength(0);
    await user.type(within(form).getByLabelText("Paid on"), "2026-10-28");
    await user.click(within(form).getByRole("button", { name: "Mark paid" }));
    await waitFor(() => expect(posts(calls, "/api/items/1/done")).toHaveLength(1));
    expect(await pay.findByText(/^Bill 2 of 4/)).toBeInTheDocument();
  });
});

describe("sumOfBills", () => {
  it("adds the amounts in cents, so 0.1 and 0.2 make 0,30", () => {
    const one = { item: bill(1, "A", null, "0.10"), tray: TO_PAY };
    const two = { item: bill(2, "B", null, "0.2"), tray: TO_PAY };
    const none = { item: bill(3, "C", null, ""), tray: TO_PAY };
    expect(sumOfBills([one, two, none])).toBe("0.30");
    expect(sumOfBills([])).toBe("0.00");
  });
});
