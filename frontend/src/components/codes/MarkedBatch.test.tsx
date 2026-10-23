import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, useLocation } from "react-router-dom";
import { describe, expect, it } from "vitest";
import type { InboxEntry } from "../../api/client";
import { type Call, deferred, mockFetch, renderWithProviders } from "../../test-utils";
import Inbox from "../../screens/Inbox";

function entry(id: string, name: string, suggested: string): InboxEntry {
  return {
    record: {
      drive_id: id,
      path: `##. Organize/To pay/${name}`,
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
    suggestion: {
      name: suggested,
      folder: "30. Home/Electricity",
      tags: [],
      fields: { dates: [], amounts: [], iban: null, reference: null },
      doc_date: null,
      sources: [],
      name_source: "rule:x",
      folder_source: null,
      tag_sources: {},
      tray: null,
      tray_source: null,
      collections: [],
      collection_sources: {},
      codes: [],
      conflict: false,
    },
    text_excerpt: "",
    prefill: {},
    tray_guess: null,
    open_trays: [],
    fields: [],
    fields_edited: false,
  };
}

const ENTRIES = [
  entry("d1", "scan001.pdf", "2026-10-01 Northpower.pdf"),
  entry("d2", "scan002.pdf", "2026-10-02 Water.pdf"),
  entry("d3", "scan003.pdf", "2026-10-03 Letter.pdf"),
];

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

const BILL = {
  drive_id: "d1",
  name: "2026-10-01 Northpower.pdf",
  folder: "30. Home/Electricity",
  tags: ["bill"],
  tray: "to-pay",
  tray_fields: { due_date: "2026-10-15", amount: "84.20" },
  collections: ["House"],
  note: "",
};
const WATER = {
  drive_id: "d2",
  name: "2026-10-02 Water.pdf",
  folder: "30. Home/Water",
  tags: [],
  tray: "to-pay",
  tray_fields: { due_date: "", amount: "40.00" },
  collections: [],
  note: "",
};
const LETTER = {
  drive_id: "d3",
  name: "2026-10-03 Letter.pdf",
  folder: "40. Letters",
  tags: [],
  tray: null,
  tray_fields: {},
  collections: [],
  note: "",
};

const ROWS = [
  {
    drive_id: "d1",
    codes: [{ code: "P", via: "folder", raw: null, unclear: false }],
    request: BILL,
    tray_fields: { due_date: "2026-10-15", amount: "84.20" },
    flag: null,
    problem: null,
  },
  {
    drive_id: "d2",
    codes: [
      { code: "P", via: "folder", raw: null, unclear: false },
      { code: "A", via: "qr", raw: "A", unclear: false },
    ],
    request: WATER,
    tray_fields: { due_date: "", amount: "40.00" },
    flag: "needs_input",
    problem: "due date",
  },
  {
    drive_id: "d3",
    codes: [{ code: "D", via: "folder", raw: null, unclear: false }],
    request: LETTER,
    tray_fields: {},
    flag: null,
    problem: null,
  },
];

const MOVES = [
  { kind: "move", src: "##. Organize/To pay/scan001.pdf", dst: "30. Home/Electricity/2026-10-01 Northpower.pdf", drive_id: "d1", note: null },
  { kind: "move", src: "##. Organize/To pay/scan003.pdf", dst: "40. Letters/2026-10-03 Letter.pdf", drive_id: "d3", note: null },
];

function Where() {
  const location = useLocation();
  return <p data-testid="where">{location.pathname + location.search}</p>;
}

function setup(routes: Parameters<typeof mockFetch>[0] = {}, at = "/inbox?marked=1") {
  const calls = mockFetch({
    "GET /api/inbox": { body: ENTRIES },
    "GET /api/folders": { body: [] },
    "GET /api/trays": { body: TRAYS },
    "GET /api/collections": { body: [] },
    "GET /api/today": { body: { marked: 3 } },
    "GET /api/filing-codes/batch": { body: ROWS },
    ...routes,
  });
  const user = userEvent.setup();
  const { client } = renderWithProviders(
    <MemoryRouter initialEntries={[at]}>
      <Inbox />
      <Where />
    </MemoryRouter>,
  );
  return { calls, user, client };
}

const posts = (calls: Call[], url: string) => calls.filter((c) => c.method === "POST" && c.url === url);
const panel = () => screen.findByRole("region", { name: "Marked files" });
const rowOf = (name: string) => screen.getByRole("listitem", { name });

describe("File N marked", () => {
  it("the Inbox toolbar shows File N marked and opens the panel", async () => {
    const { user } = setup({}, "/inbox");
    const button = await screen.findByRole("button", { name: "File 3 marked" });
    expect(screen.queryByRole("region", { name: "Marked files" })).not.toBeInTheDocument();
    await user.click(button);
    expect(screen.getByTestId("where")).toHaveTextContent("/inbox?marked=1");
    await panel();
  });

  it("hides the button when nothing is marked", async () => {
    setup({ "GET /api/today": { body: { marked: 0 } } }, "/inbox");
    await screen.findByLabelText("Name");
    expect(screen.queryByRole("button", { name: /marked/ })).not.toBeInTheDocument();
  });

  it("shows each row's codes, name, folder, tray and fields; a flagged row starts unticked with its problem", async () => {
    setup();
    await panel();
    const bill = await screen.findByRole("listitem", { name: "2026-10-01 Northpower.pdf" });
    expect(within(bill).getByRole("checkbox")).toBeChecked();
    expect(within(bill).getByText("P (folder)")).toBeInTheDocument();
    expect(bill).toHaveTextContent("30. Home/Electricity");
    expect(bill).toHaveTextContent("To pay: due date 15.10.2026 · amount 84,20 €");
    expect(bill).toHaveTextContent("bill");
    expect(bill).toHaveTextContent("House");
    expect(bill).toHaveTextContent("scan001.pdf");

    const water = rowOf("2026-10-02 Water.pdf");
    expect(within(water).getByRole("checkbox")).not.toBeChecked();
    expect(within(water).getByText("Needs input: due date")).toBeInTheDocument();
    // every code found, with how it was found
    expect(within(water).getByText("P (folder)")).toBeInTheDocument();
    expect(within(water).getByText("A (sticker)")).toBeInTheDocument();

    const letter = rowOf("2026-10-03 Letter.pdf");
    expect(within(letter).getByText("D (folder)")).toBeInTheDocument();
    expect(letter).toHaveTextContent("no tray");
    expect(screen.getByRole("button", { name: "File 2" })).toBeInTheDocument();
  });

  it("names conflicts and unclear readings", async () => {
    setup({
      "GET /api/filing-codes/batch": {
        body: [
          { ...ROWS[0], flag: "conflict", problem: null },
          { ...ROWS[2], codes: [{ code: "D", via: "pen", raw: "0", unclear: true }], flag: "unclear", problem: "D or 0" },
        ],
      },
    });
    await panel();
    const bill = await screen.findByRole("listitem", { name: "2026-10-01 Northpower.pdf" });
    expect(within(bill).getByText("Codes disagree")).toBeInTheDocument();
    expect(within(bill).getByRole("checkbox")).not.toBeChecked();
    const letter = rowOf("2026-10-03 Letter.pdf");
    expect(within(letter).getByText("Unclear: D or 0")).toBeInTheDocument();
    expect(within(letter).getByText("D? (pen)")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "File 0" })).toBeDisabled();
  });

  it("File previews the ticked requests, then files them in one call, with undo", async () => {
    const { calls, user } = setup({
      "POST /api/inbox/preview": { body: MOVES },
      "POST /api/inbox/file": {
        body: {
          batch_id: "b1",
          dry_run: false,
          done: MOVES,
          failed: null,
          error: null,
          index_error: null,
          tag_error: null,
          untagged: [],
          items: [],
          follow_up_error: null,
        },
      },
    });
    await panel();
    await screen.findByRole("listitem", { name: "2026-10-01 Northpower.pdf" });
    await user.click(screen.getByRole("button", { name: "File 2" }));
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent("2026-10-01 Northpower.pdf: Put in To pay: due date 15.10.2026, amount 84,20 €");
    expect(posts(calls, "/api/inbox/file")).toHaveLength(0);
    await user.click(within(dialog).getByRole("button", { name: "File" }));
    await waitFor(() => expect(posts(calls, "/api/inbox/file")).toHaveLength(1));
    // exactly the rows' requests, as the server built them, flagged row left out
    expect(posts(calls, "/api/inbox/preview")[0].body).toEqual([BILL, LETTER]);
    expect(posts(calls, "/api/inbox/file")[0].body).toEqual({ requests: [BILL, LETTER], dry_run: false });
    expect(await screen.findByRole("button", { name: "Undo" })).toBeInTheDocument();
  });

  it("a conflict row can be ticked on purpose; unticking removes a row", async () => {
    const { calls, user } = setup({
      "GET /api/filing-codes/batch": { body: [{ ...ROWS[0], flag: "conflict", problem: null }, ROWS[2]] },
      "POST /api/inbox/preview": { body: MOVES },
    });
    await panel();
    const bill = await screen.findByRole("listitem", { name: "2026-10-01 Northpower.pdf" });
    expect(within(bill).getByRole("checkbox")).not.toBeChecked();
    await user.click(within(bill).getByRole("checkbox"));
    expect(screen.getByRole("button", { name: "File 2" })).toBeInTheDocument();
    await user.click(within(rowOf("2026-10-03 Letter.pdf")).getByRole("checkbox"));
    await user.click(screen.getByRole("button", { name: "File 1" }));
    await waitFor(() => expect(posts(calls, "/api/inbox/preview")).toHaveLength(1));
    expect(posts(calls, "/api/inbox/preview")[0].body).toEqual([BILL]);
  });

  it("a row that needs input cannot be ticked and is never sent", async () => {
    const { calls, user } = setup({ "POST /api/inbox/preview": { body: MOVES } });
    await panel();
    const water = await screen.findByRole("listitem", { name: "2026-10-02 Water.pdf" });
    const box = within(water).getByRole("checkbox");
    expect(box).toBeDisabled();
    expect(box).toHaveAttribute("title", "Open it to fix it in the form");
    await user.click(box);
    expect(box).not.toBeChecked();
    await user.click(screen.getByRole("button", { name: "File 2" }));
    await waitFor(() => expect(posts(calls, "/api/inbox/preview")).toHaveLength(1));
    expect(posts(calls, "/api/inbox/preview")[0].body).toEqual([BILL, LETTER]);
  });

  it("says when the rows changed while File was previewing", async () => {
    let rows = ROWS;
    const answer = deferred<{ body: unknown }>();
    const { calls, user, client } = setup({
      "GET /api/filing-codes/batch": () => ({ body: rows }),
      "POST /api/inbox/preview": () => answer.promise,
    });
    await panel();
    await screen.findByRole("listitem", { name: "2026-10-03 Letter.pdf" });
    await user.click(screen.getByRole("button", { name: "File 2" }));
    await waitFor(() => expect(posts(calls, "/api/inbox/preview")).toHaveLength(1));
    // the letter leaves the inbox while the preview is in flight (a status change reloads)
    rows = [ROWS[0]];
    await client.invalidateQueries({ queryKey: ["inbox"] });
    await waitFor(() => expect(screen.queryByRole("listitem", { name: "2026-10-03 Letter.pdf" })).not.toBeInTheDocument());
    answer.resolve({ body: MOVES });
    expect(await screen.findByText("The marked files changed; check the list and press File again")).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(posts(calls, "/api/inbox/file")).toHaveLength(0);
  });

  it("clicking a list row closes the panel and shows that file in the form", async () => {
    const { user } = setup();
    await panel();
    await screen.findByRole("listitem", { name: "2026-10-01 Northpower.pdf" });
    const row = screen.getAllByRole("button", { name: /scan002\.pdf/ })[0];
    await user.click(row);
    expect(await screen.findByLabelText("Name")).toHaveValue("2026-10-02 Water.pdf");
    expect(screen.queryByRole("region", { name: "Marked files" })).not.toBeInTheDocument();
    expect(screen.getByTestId("where")).toHaveTextContent(/^\/inbox$/);
  });

  it("⌘⌫ does nothing while the panel hides the selection", async () => {
    const { calls, user } = setup();
    await panel();
    await screen.findByRole("listitem", { name: "2026-10-01 Northpower.pdf" });
    await user.keyboard("{Meta>}{Backspace}{/Meta}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(calls.filter((c) => c.method === "POST")).toHaveLength(0);
    expect(screen.getByRole("region", { name: "Marked files" })).toBeInTheDocument();
  });

  it("Open shows the file in the Inbox form", async () => {
    const { user } = setup();
    await panel();
    const water = await screen.findByRole("listitem", { name: "2026-10-02 Water.pdf" });
    await user.click(within(water).getByRole("button", { name: "Open" }));
    expect(await screen.findByLabelText("Name")).toHaveValue("2026-10-02 Water.pdf");
    expect(screen.queryByRole("region", { name: "Marked files" })).not.toBeInTheDocument();
    expect(screen.getByTestId("where")).toHaveTextContent(/^\/inbox$/);
  });
});
