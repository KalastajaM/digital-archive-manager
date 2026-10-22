/** Today's Inbox card: "Not recognised: N files — Ask AI" for inbox files without a rule
 * guess; the answer offers "Put in <tray>" with the suggested fields. */
import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it } from "vitest";
import type { AIStatus, InboxEntry, Item, Today as TodayData } from "../../api/client";
import { type Call, mockFetch, renderWithProviders } from "../../test-utils";
import { prepared, STATUS_ON } from "../ai/testData";
import { InboxCard } from "./InboxCard";

function entry(id: string, name: string, trayGuess: string | null): InboxEntry {
  return {
    record: {
      drive_id: id,
      path: `##. Organize/${name}`,
      name,
      ext: "pdf",
      is_dir: false,
      is_link: false,
      link_target: null,
      size: 1000,
      mtime: 1_760_000_000,
      sha256: null,
      doc_date: null,
      index_state: "indexed",
      retry_at: null,
      attempts: 0,
      missing: false,
      last_seen: null,
      parked_at: null,
      marks: [],
    },
    suggestion: { name, folder: null, tags: [], fields: { dates: [], amounts: [], iban: null, reference: null }, doc_date: null, sources: [], name_source: "scan", folder_source: null, tag_sources: {} },
    text_excerpt: "",
    prefill: {},
    tray_guess: trayGuess,
    open_trays: [],
    fields: [],
    fields_edited: false,
  };
}

const ENTRIES = [entry("d1", "scan‮001.pdf", null), entry("d2", "bill.pdf", "to-pay"), entry("d3", "letter.pdf", null)];

const TRAYS = {
  trays: [
    {
      id: "to-pay",
      name: "To pay",
      order: 1,
      item_title: "{name}",
      fields: {
        due_date: { type: "date", required: true, prefill: "due_date", copy: false },
        amount: { type: "money", required: false, prefill: "total", copy: true },
      },
      date_field: "due_date",
    },
  ],
  errors: [],
};

const DATA = {
  inbox_stats: { count: 3, oldest_days: 2, this_week: 3, last_week: 0, older: 0, overdue: 0 },
  found: [
    { drive_id: "d2", name: "bill.pdf", tray: "to-pay", tray_name: "To pay", due_date: null, total: null, overdue: false },
  ],
} as unknown as TodayData;

const SUGGESTION = {
  name: "20261001_Northpower.pdf",
  folder: "20. Home/Electricity",
  tags: [],
  tray: "to-pay",
  // the tray has no payee field, and a blank value is not shown: neither is sent
  tray_fields: { due_date: "2026-10-15", amount: "84.20", payee: "Northpower", iban: " " },
  summary: "An electricity bill.",
  confidence: { name: 0.9, folder: 0.7, tags: 0.5, tray: 0.8, tray_fields: 0.6 },
  reason: "Northpower Oy sends bills",
  rejected: {},
};

const CREATED: Item = {
  id: 11,
  tray_id: "to-pay",
  title: "Scan bill",
  fields: {},
  date: "2026-10-15",
  state: "open",
  created: 1_760_000_000,
  done_at: null,
  done_fields: null,
  files: ["d1"],
  created_by_batch: null,
  missing_required: [],
  invalid_fields: [],
  tray_name: "To pay",
  tray_removed: false,
};

const posts = (calls: Call[], url: string) => calls.filter((c) => c.method === "POST" && c.url === url);

function setup(
  status: AIStatus = STATUS_ON,
  suggestion: Record<string, unknown> = SUGGESTION,
  quick: { created: Item[]; skipped: string[] } = { created: [CREATED], skipped: [] },
) {
  const calls = mockFetch({
    "GET /api/ai/status": { body: status },
    "GET /api/inbox": { body: ENTRIES },
    "GET /api/trays": { body: TRAYS },
    "POST /api/ai/suggest-filing/prepare": { body: prepared() },
    "POST /api/ai/suggest-filing/run": { body: { data: suggestion, cost_eur: 0.0004, cached: false } },
    "POST /api/items/quick": { body: quick },
    "POST /api/items/11/discard": { status: 204, body: null },
  });
  const user = userEvent.setup();
  const { client } = renderWithProviders(
    <MemoryRouter>
      <InboxCard data={DATA} />
    </MemoryRouter>,
  );
  return { calls, user, client };
}

afterEach(() => {
  fireEvent.keyUp(window, { key: "Meta" });
});

const toasts = () => document.querySelector<HTMLElement>(".toasts")!;

describe("InboxCard: Ask AI", () => {
  it("switching AI off hides an answer and its Put in", async () => {
    const { user, client } = setup();
    await user.click(await screen.findByRole("button", { name: "Ask AI" }));
    const rows = within(screen.getByRole("list", { name: "Not recognised" })).getAllByRole("listitem");
    await user.click(within(rows[0]).getByRole("button", { name: "Ask AI about scan⟨U+202E⟩001.pdf" }));
    await user.click(within(await screen.findByRole("dialog", { name: "What will be sent" })).getByRole("button", { name: "Send" }));
    expect(await within(rows[0]).findByRole("button", { name: "Put in To pay" })).toBeInTheDocument();
    act(() => client.setQueryData(["ai", "status"], { ...STATUS_ON, enabled: false, switched_on: false }));
    await waitFor(() => expect(screen.queryByRole("list", { name: "Not recognised" })).not.toBeInTheDocument());
    expect(rows[0]).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/^AI suggested/)).not.toBeInTheDocument();
    expect(screen.queryByText(/due date 15.10.2026/)).not.toBeInTheDocument();
  });

  it("counts the files without a rule guess; found rows get no Ask AI", async () => {
    setup();
    const row = await screen.findByText(/Not recognised: 2 files/);
    expect(row.closest("p")).toHaveTextContent("Not recognised: 2 files");
    const found = screen.getByRole("list", { name: "Found in the inbox" });
    expect(within(found).queryByRole("button", { name: /Ask AI/ })).not.toBeInTheDocument();
  });

  it("Ask AI opens the chooser; the answer offers Put in <tray> with its fields", async () => {
    const { calls, user } = setup();
    const open = await screen.findByRole("button", { name: "Ask AI" });
    expect(open).toHaveAttribute("aria-expanded", "false");
    await user.click(open);
    const chooser = screen.getByRole("list", { name: "Not recognised" });
    const rows = within(chooser).getAllByRole("listitem");
    expect(rows.map((r) => r.querySelector(".today-row-title")?.textContent)).toEqual(["scan⟨U+202E⟩001.pdf", "letter.pdf"]);
    // nothing was prepared just by opening the chooser
    expect(posts(calls, "/api/ai/suggest-filing/prepare")).toHaveLength(0);

    await user.click(within(rows[0]).getByRole("button", { name: "Ask AI about scan⟨U+202E⟩001.pdf" }));
    const dialog = await screen.findByRole("dialog", { name: "What will be sent" });
    expect(posts(calls, "/api/ai/suggest-filing/prepare")[0].body).toEqual({ params: { drive_id: "d1" } });
    await user.click(within(dialog).getByRole("button", { name: "Send" }));
    const put = await within(rows[0]).findByRole("button", { name: "Put in To pay" });
    expect(rows[0]).toHaveTextContent("due date 15.10.2026 · amount 84,20 €");
    expect(within(rows[0]).getByLabelText(/^AI suggested tray: 80% sure/)).toBeInTheDocument();
    expect(posts(calls, "/api/items/quick")).toHaveLength(0);

    await user.click(put);
    await waitFor(() => expect(posts(calls, "/api/items/quick")).toHaveLength(1));
    // through the server's "already in" and folder checks, with only the fields shown
    expect(posts(calls, "/api/items/quick")[0].body).toEqual({
      tray: "to-pay",
      drive_ids: ["d1"],
      fields: { due_date: "2026-10-15", amount: "84.20" },
    });
    expect(await within(toasts()).findByText("Put in To pay: Scan bill")).toBeInTheDocument();
    await user.click(within(toasts()).getByRole("button", { name: "Undo" }));
    await waitFor(() => expect(posts(calls, "/api/items/11/discard")).toHaveLength(1));
  });

  it("a double click on Put in creates one item", async () => {
    const { calls, user } = setup();
    await user.click(await screen.findByRole("button", { name: "Ask AI" }));
    const row = within(screen.getByRole("list", { name: "Not recognised" })).getAllByRole("listitem")[0];
    await user.click(within(row).getByRole("button", { name: /^Ask AI about/ }));
    await user.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Send" }));
    const put = await within(row).findByRole("button", { name: "Put in To pay" });
    put.click();
    put.click();
    await within(toasts()).findByText("Put in To pay: Scan bill");
    expect(posts(calls, "/api/items/quick")).toHaveLength(1);
  });

  it("a stale row (the file was put in the tray meanwhile) gets already in, not a second item", async () => {
    // the server's check: an open item in that tray already (put there from elsewhere)
    const { calls, user } = setup(STATUS_ON, SUGGESTION, { created: [], skipped: ["d1"] });
    await user.click(await screen.findByRole("button", { name: "Ask AI" }));
    const row = within(screen.getByRole("list", { name: "Not recognised" })).getAllByRole("listitem")[0];
    await user.click(within(row).getByRole("button", { name: /^Ask AI about/ }));
    await user.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Send" }));
    await user.click(await within(row).findByRole("button", { name: "Put in To pay" }));
    expect(await within(toasts()).findByText("scan⟨U+202E⟩001.pdf: already in To pay")).toBeInTheDocument();
    expect(posts(calls, "/api/items/quick")).toHaveLength(1);
  });

  it("no tray suggested: says so and links to the Inbox", async () => {
    const { user } = setup(STATUS_ON, { ...SUGGESTION, tray: null, tray_fields: {} });
    await user.click(await screen.findByRole("button", { name: "Ask AI" }));
    const row = within(screen.getByRole("list", { name: "Not recognised" })).getAllByRole("listitem")[0];
    await user.click(within(row).getByRole("button", { name: /^Ask AI about/ }));
    await user.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Send" }));
    expect(await within(row).findByText(/No tray suggested/)).toBeInTheDocument();
    expect(within(row).getByRole("link", { name: "File in the Inbox" })).toHaveAttribute("href", "/inbox");
    expect(within(row).queryByRole("button", { name: /^Put in/ })).not.toBeInTheDocument();
  });

  it("without a key: no Ask AI, one Turn on AI hint, and the inbox is not fetched", async () => {
    const { calls } = setup({ ...STATUS_ON, enabled: false, has_key: false });
    expect(await screen.findByText(/Turn on AI/)).toBeInTheDocument();
    expect(screen.getAllByText(/Turn on AI/)).toHaveLength(1);
    expect(screen.queryByRole("button", { name: /Ask AI/ })).not.toBeInTheDocument();
    expect(calls.filter((c) => c.url === "/api/inbox")).toHaveLength(0);
  });
});
