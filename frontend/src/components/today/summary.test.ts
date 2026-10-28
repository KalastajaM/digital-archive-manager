import { describe, expect, it } from "vitest";
import type { Item, Today as TodayData, TrayDef } from "../../api/client";
import { countWord, countsOf, headlineOf, isWaitingTray, tilesOf } from "./summary";
import type { TrayCardInfo } from "./TrayCard";

describe("the headline", () => {
  const none = { overdueBills: 0, overdueOther: 0, toFile: 0, dueSoon: 0 };
  it.each([
    [{ overdueBills: 1, toFile: 7 }, "One bill is overdue, seven documents to file"],
    [{ overdueBills: 3, toFile: 1 }, "Three bills are overdue, one document to file"],
    [{ overdueBills: 1 }, "One bill is overdue"],
    [{ overdueBills: 1, overdueOther: 2 }, "One bill and two items are overdue"],
    [{ overdueOther: 1, toFile: 12 }, "One item is overdue, 12 documents to file"],
    [{ toFile: 7 }, "Nothing is overdue, seven documents to file"],
    [{ dueSoon: 2 }, "Two bills due soon"],
    [{}, "All clear"],
  ])("%j reads %s", (counts, text) => {
    expect(headlineOf({ ...none, ...counts })).toBe(text);
  });

  it("writes small counts in words and the rest as figures", () => {
    expect([0, 1, 10, 11].map(countWord)).toEqual(["no", "one", "ten", "11"]);
  });
});

const TO_PAY: TrayDef = {
  id: "to-pay",
  name: "To pay",
  order: 1,
  item_title: "{name}",
  fields: { iban: { type: "iban", required: false, copy: true }, amount: { type: "money", required: false, copy: true } },
  date_field: "due_date",
  summary: { sum: "amount" },
  done: { label: "Mark paid", fields: {} },
};
const FOLLOW: TrayDef = { ...TO_PAY, id: "follow-up", name: "Follow up", fields: { waiting_for: { type: "text", required: false, copy: false } }, summary: null };
const TODAY = "2026-10-19";

function item(id: number, date: string | null, amount = "10.00"): Item {
  return {
    id,
    tray_id: "to-pay",
    title: `Bill ${id}`,
    fields: { amount },
    date,
    state: "open",
    created: 1_760_000_000,
    done_at: null,
    done_fields: null,
    files: [],
    created_by_batch: null,
    missing_required: [],
    invalid_fields: [],
    tray_name: "To pay",
    tray_removed: false,
  };
}

function data(over: Partial<TodayData["inbox_stats"]> = {}): TodayData {
  return {
    attention: [],
    overview: {
      inbox: 3,
      trays: [
        { tray_id: "to-pay", name: "To pay", open: 3, overdue: 1, sum: "30.00", waiting_long: 0 },
        { tray_id: "follow-up", name: "Follow up", open: 2, overdue: 0, sum: null, waiting_long: 0 },
        { tray_id: "to-read", name: "To read", open: 1, overdue: 1, sum: null, waiting_long: 0 },
      ],
      collections: [],
    },
    unmanaged_ongoing: 0,
    unmanaged_important: 0,
    ongoing_sync_failure: null,
    reminders: { last_run: null, errors: {}, skipped: null },
    tray_errors: [],
    inbox_stats: { count: 3, oldest_days: 2, this_week: 3, last_week: 0, older: 0, overdue: 0, ...over },
    found: [],
    open_items: [{ tray_id: "follow-up", items: [{ ...item(9, "2026-10-22"), tray_id: "follow-up" }] }],
    marked: 0,
    reading_codes: 0,
  } as unknown as TodayData;
}

const cards: TrayCardInfo[] = [
  { id: "to-pay", name: "To pay", def: TO_PAY, kind: "money", count: { tray_id: "to-pay", name: "To pay", open: 3, overdue: 1, sum: "30.00", waiting_long: 0 } },
  { id: "follow-up", name: "Follow up", def: FOLLOW, kind: "dated", count: { tray_id: "follow-up", name: "Follow up", open: 2, overdue: 0, sum: null, waiting_long: 0 } },
] as TrayCardInfo[];
const bill = (i: Item) => ({ item: i, tray: TO_PAY });

describe("the stat tiles", () => {
  const bills = [bill(item(1, "2026-10-09", "84.20")), bill(item(2, "2026-10-22", "54.20")), bill(item(3, "2026-11-30", "47.90")), bill(item(4, "2026-11-02", "1.00")), bill(item(5, null, "5.00"))];
  const tiles = (d = data(), loaded = true) =>
    Object.fromEntries(
      tilesOf({ data: d, bills, billsLoaded: loaded, trays: cards, billTrayIds: new Set(["to-pay"]), today: TODAY }).map((t) => [t.id, t]),
    );

  it("to file: the inbox count and when the oldest arrived, linked to the Inbox", () => {
    expect(tiles()["to-file"]).toMatchObject({ value: "3", note: "oldest from 17 Oct", to: "/inbox", tone: "normal" });
    expect(tiles(data({ count: 0, oldest_days: null }))["to-file"]).toMatchObject({ value: "0", note: "The inbox is empty", tone: "muted" });
  });

  it("overdue: the overdue bills' amount, how many and how late, plus other trays and the inbox", () => {
    const t = tiles(data({ overdue: 2 })).overdue;
    expect(t.value).toBe("84,20 €");
    expect(t.note).toBe("1 bill, 10 days late · 1 other item · 2 in the inbox");
    expect(t.tone).toBe("red");
    expect(t.to).toBe("/trays/to-pay?item=1");
  });

  it("due in 14 days: the bills due within two weeks that are not late yet, without the later ones", () => {
    const t = tiles().due;
    // 22 Oct (54,20) and 2 Nov (1,00); 30 Nov is too far, 9 Oct is late, no date is left out
    expect(t.label).toBe("Due in 14 days");
    expect(t.value).toBe("55,20 €");
    expect(t.note).toBe("2 bills");
    expect(t.to).toBe("/trays/to-pay");
  });

  it("figures wait for the bills to load", () => {
    expect(tiles(data(), false).due.value).toBe("…");
    expect(tiles(data(), false).overdue.value).toBe("…");
  });

  it("waiting on others: the open count of the follow-up trays and the next date", () => {
    const t = tiles().waiting;
    expect(t).toMatchObject({ value: "2", note: "Follow up, next in 3 days", to: "/trays/follow-up" });
    expect(isWaitingTray(cards[1])).toBe(true);
    expect(isWaitingTray(cards[0])).toBe(false);
  });

  it("has no waiting tile when no tray holds what is waiting on others", () => {
    const list = tilesOf({ data: data(), bills, billsLoaded: true, trays: [cards[0]], billTrayIds: new Set(["to-pay"]), today: TODAY });
    expect(list.map((t) => t.id)).toEqual(["to-file", "overdue", "due"]);
  });

  it("has no due tile when there are no bill trays", () => {
    const list = tilesOf({ data: data(), bills: [], billsLoaded: true, trays: [cards[1]], billTrayIds: new Set(), today: TODAY });
    expect(list.map((t) => t.id)).toEqual(["to-file", "overdue", "waiting"]);
  });

  it("counts the headline's overdue from the overview: bills apart from the other trays", () => {
    expect(countsOf(data({ overdue: 1 }), new Set(["to-pay"]))).toEqual({ overdueBills: 2, overdueOther: 1, toFile: 3, dueSoon: 0 });
  });
});
