/** "Ask AI" on the inbox review card: the answer becomes chips (stars spec §7), one per
 * field and one per tag, each with Use, plus Use all; filing still goes through File it
 * with exactly what the form shows. */
import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it } from "vitest";
import type { AIStatus, InboxEntry } from "../api/client";
import { prepared, STATUS_ON } from "../components/ai/testData";
import { type Call, deferred, mockFetch, renderWithProviders } from "../test-utils";
import Inbox from "./Inbox";

const ENTRY: InboxEntry = {
  record: {
    drive_id: "d1",
    path: "##. Organize/scan001.pdf",
    name: "scan001.pdf",
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
    connected: true, marks: [],
  },
  suggestion: {
    name: "scan001.pdf",
    folder: null,
    tags: ["invoice"],
    fields: { dates: [], amounts: [], iban: null, reference: null },
    doc_date: null,
    sources: [],
    name_source: "scan",
    folder_source: null,
    tag_sources: {},
    tray: null,
    tray_source: null,
    collections: [],
    collection_sources: {},
    codes: [],
    conflict: false, star: null, important: null, marks_unclear: false, waiting_for_page1: false, people_found: [], areas: [], person_line: null,
  },
  text_excerpt: "Northpower Oy lasku",
  prefill: { due_date: "2026-10-01" },
  tray_guess: null,
  open_trays: [],
  fields: [],
  fields_edited: false,
  person_follows_folder: false,
};

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
    { id: "to-read", name: "To read", order: 2, item_title: "{name}", fields: {} },
  ],
  errors: [],
};

const FOLDERS = ["10. Financial/Bills", "20. Home/Electricity"];

const SUGGESTION = {
  name: "20261001_Northpower electricity bill‮.pdf",
  folder: "20. Home/Electricity",
  tags: ["invoice", "power"], // invoice is in the form already: no chip for it
  tray: "to-pay",
  tray_fields: { due_date: "2026-10-15", amount: "84.20" },
  summary: "An electricity bill from Northpower Oy‮ for October.",
  confidence: { name: 0.85, folder: 0.7, tags: 0.9, tray: 0.8, tray_fields: 0.6 },
  reason: "Northpower Oy sends electricity bills",
  rejected: {},
};

const posts = (calls: Call[], url: string) => calls.filter((c) => c.method === "POST" && c.url === url);

async function setup(
  status: AIStatus | null = STATUS_ON,
  suggestion: Record<string, unknown> = SUGGESTION,
  extra: Parameters<typeof mockFetch>[0] = {},
) {
  const calls = mockFetch({
    "GET /api/inbox": { body: [ENTRY] },
    "GET /api/folders": { body: FOLDERS },
    "GET /api/trays": { body: TRAYS },
    "GET /api/collections": { body: [] },
    ...(status ? { "GET /api/ai/status": { body: status } } : {}),
    "POST /api/ai/suggest-filing/prepare": { body: prepared() },
    "POST /api/ai/suggest-filing/run": { body: { data: suggestion, cost_eur: 0.0004, cached: false } },
    "POST /api/inbox/preview": { body: [] },
    ...extra,
  });
  const user = userEvent.setup();
  const { client } = renderWithProviders(
    <MemoryRouter>
      <Inbox />
    </MemoryRouter>,
  );
  await screen.findByLabelText("Name");
  return { calls, user, client };
}

async function askAI(user: ReturnType<typeof userEvent.setup>) {
  await user.click(await screen.findByRole("button", { name: "Ask AI" }));
  const dialog = await screen.findByRole("dialog", { name: "What will be sent" });
  await user.click(within(dialog).getByRole("button", { name: "Send" }));
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
}

const field = (label: RegExp | string) => screen.getByLabelText(label) as HTMLInputElement;

afterEach(() => {
  fireEvent.keyUp(window, { key: "Meta" });
});

const chip = (label: RegExp) => screen.getByRole("group", { name: label });
const useChip = async (user: ReturnType<typeof userEvent.setup>, label: RegExp) =>
  user.click(within(chip(label)).getByRole("button", { name: "Use" }));

/** The tag chips of the filing form's tags field, in order. */
const tagList = () => Array.from(document.querySelectorAll(".tag-field .tag-token")).map((t) => t.firstChild?.textContent ?? "");

describe("ReviewCard: Ask AI", () => {
  it("switching AI off hides its chips and the AI summary; the form keeps its values", async () => {
    const { user, client } = await setup();
    await askAI(user);
    expect(chip(/^Suggested Name: .* \(AI\)$/)).toBeInTheDocument();
    act(() => client.setQueryData(["ai", "status"], { ...STATUS_ON, enabled: false, switched_on: false }));
    await waitFor(() => expect(screen.queryByRole("group", { name: /\(AI\)$/ })).not.toBeInTheDocument());
    expect(screen.queryByRole("region", { name: "AI summary" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Use all" })).not.toBeInTheDocument();
    expect(field("Name")).toHaveValue("scan001.pdf");
  });

  it("is hidden without a key; a small Turn on AI hint says where to read", async () => {
    await setup({ ...STATUS_ON, enabled: false, has_key: false });
    expect(await screen.findByText(/Turn on AI/)).toBeInTheDocument();
    expect(screen.getByText(/Turn on AI/).closest("p")).toHaveTextContent("README");
    expect(screen.queryByRole("button", { name: "Ask AI" })).not.toBeInTheDocument();
  });

  it("is hidden when AI is switched off (key present)", async () => {
    await setup({ ...STATUS_ON, enabled: false });
    expect(await screen.findByText(/Turn on AI/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Ask AI" })).not.toBeInTheDocument();
  });

  it("is hidden, with no hint, while the status is unknown", async () => {
    await setup(null);
    expect(screen.queryByRole("button", { name: "Ask AI" })).not.toBeInTheDocument();
    expect(screen.queryByText(/Turn on AI/)).not.toBeInTheDocument();
  });

  it("Ask AI is a link in the panel header with a tooltip", async () => {
    await setup();
    const button = await screen.findByRole("button", { name: "Ask AI" });
    expect(button).toHaveClass("link-button");
    expect(button).toHaveAttribute("title", expect.stringContaining("Ask AI to suggest"));
  });

  it("the answer becomes chips; the form stays as it was and nothing is filed", async () => {
    const { calls, user } = await setup();
    // before asking: the rules' values pre-fill the empty fields, so there is no chip
    expect(screen.queryByRole("group", { name: /^Suggested/ })).not.toBeInTheDocument();
    await askAI(user);
    expect(posts(calls, "/api/ai/suggest-filing/prepare")[0].body).toEqual({ params: { drive_id: "d1" } });
    expect(field("Name")).toHaveValue("scan001.pdf");
    expect(field("Folder")).toHaveValue("");
    expect(tagList()).toEqual(["invoice"]);
    expect(screen.getByRole("button", { name: "Nothing (just file)", pressed: true })).toBeInTheDocument();

    // hidden characters are shown in a chip
    expect(chip(/^Suggested Name: 20261001_Northpower electricity bill⟨U\+202E⟩\.pdf \(AI\)$/)).toHaveTextContent(
      "Suggested: 20261001_Northpower electricity bill⟨U+202E⟩.pdf",
    );
    expect(chip(/^Suggested Folder: 20\. Home\/Electricity \(AI\)$/)).toBeInTheDocument();
    expect(chip(/^Suggested tray: To pay \(AI\)$/)).toBeInTheDocument();
    // the AI tag says how sure it was and why
    expect(within(chip(/^Suggested Name: .* \(AI\)$/)).getByText("AI")).toHaveAttribute(
      "title",
      "AI: 85% sure — Northpower Oy sends electricity bills",
    );
    // Use all counts what it applies: name, folder, power, the tray and its two fields
    expect(screen.getByText("6 suggestions below the fields")).toBeInTheDocument();
    // each tag is its own chip; one already in the form gets none
    expect(chip(/^Suggested tag: power \(AI\)$/)).toBeInTheDocument();
    expect(screen.queryByRole("group", { name: /^Suggested tag: invoice/ })).not.toBeInTheDocument();

    // the summary is offered as a note, shown with hidden characters visible
    const summary = screen.getByRole("region", { name: "AI summary" });
    expect(within(summary).getByText("An electricity bill from Northpower Oy⟨U+202E⟩ for October.")).toBeInTheDocument();
    expect(posts(calls, "/api/inbox/preview")).toHaveLength(0);
    expect(posts(calls, "/api/inbox/file")).toHaveLength(0);
  });

  it("Use on one chip changes only that field", async () => {
    const { user } = await setup();
    await askAI(user);
    await useChip(user, /^Suggested Folder:/);
    expect(field("Folder")).toHaveValue("20. Home/Electricity");
    expect(field("Name")).toHaveValue("scan001.pdf");
    expect(tagList()).toEqual(["invoice"]);
    expect(screen.getByRole("button", { name: "Nothing (just file)", pressed: true })).toBeInTheDocument();
    expect(screen.queryByRole("group", { name: /^Suggested Folder:/ })).not.toBeInTheDocument();

    await useChip(user, /^Suggested tag: power/);
    expect(tagList()).toEqual(["invoice", "power"]);
    expect(field("Name")).toHaveValue("scan001.pdf");

    // the rules' name comes back as a chip once the field is edited away from it
    await useChip(user, /^Suggested Name: .* \(AI\)$/);
    expect(field("Name")).toHaveValue("20261001_Northpower electricity bill\u202E.pdf");
    expect(chip(/^Suggested Name: scan001\.pdf \(scan\)$/)).toBeInTheDocument();
  });

  it("the tray chip picks the tray; then each of its fields is a chip of its own", async () => {
    const { user } = await setup();
    await askAI(user);
    expect(screen.queryByRole("group", { name: /^Suggested due date/ })).not.toBeInTheDocument();
    await useChip(user, /^Suggested tray: To pay/);
    expect(screen.getByRole("button", { name: "To pay", pressed: true })).toBeInTheDocument();
    expect(field(/^Due date/)).toHaveValue("2026-10-01"); // still the scan's value
    expect(screen.getByText("found in scan")).toBeInTheDocument();
    await useChip(user, /^Suggested due date: 2026-10-15 \(AI\)$/);
    expect(field(/^Due date/)).toHaveValue("2026-10-15");
    expect(field(/^Amount/)).toHaveValue("");
    await useChip(user, /^Suggested amount: 84,20 \(AI\)$/);
    expect(field(/^Amount/)).toHaveValue("84,20");
    expect(field("Name")).toHaveValue("scan001.pdf");
  });

  it("Use all applies every chip; the preview and the filing are exactly the form", async () => {
    const op = { kind: "move", src: "##. Organize/scan001.pdf", dst: "20. Home/Electricity/x.pdf", drive_id: "d1", note: null };
    const { calls, user } = await setup(STATUS_ON, SUGGESTION, {
      "POST /api/inbox/preview": { body: [{ kind: "mkdir", src: null, dst: "20. Home/Electricity", drive_id: null, note: null }, op] },
      "POST /api/inbox/file": {
        body: { batch_id: "b1", dry_run: false, done: [op], failed: null, error: null, index_error: null, tag_error: null, untagged: [], items: [{ tray: "to-pay", id: 1 }], follow_up_error: null },
      },
    });
    await askAI(user);
    await user.click(screen.getByRole("button", { name: "Use all" }));
    expect(field("Name")).toHaveValue("20261001_Northpower electricity bill\u202E.pdf");
    expect(field("Folder")).toHaveValue("20. Home/Electricity");
    expect(tagList()).toEqual(["invoice", "power"]);
    expect(screen.getByRole("button", { name: "To pay", pressed: true })).toBeInTheDocument();
    expect(field(/^Due date/)).toHaveValue("2026-10-15");
    expect(field(/^Amount/)).toHaveValue("84,20");
    expect(screen.queryByRole("group", { name: /\(AI\)$/ })).not.toBeInTheDocument();
    await user.click(within(screen.getByRole("region", { name: "AI summary" })).getByRole("button", { name: "Use as note" }));

    const expected = {
      drive_id: "d1",
      name: "20261001_Northpower electricity bill\u202E.pdf",
      folder: "20. Home/Electricity",
      tags: ["invoice", "power"],
      tray: "to-pay",
      tray_fields: { due_date: "2026-10-15", amount: "84,20" },
      note: "An electricity bill from Northpower Oy\u202E for October.",
    };
    await user.click(screen.getByRole("button", { name: "Preview" }));
    await waitFor(() => expect(posts(calls, "/api/inbox/preview")).toHaveLength(1));
    expect(posts(calls, "/api/inbox/preview")[0].body).toEqual([expected]);
    await user.click(within(screen.getByRole("region", { name: "Planned changes" })).getByRole("button", { name: "File it" }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "File" }));
    await waitFor(() => expect(posts(calls, "/api/inbox/file")).toHaveLength(1));
    // the snapshot rule: what is filed is what was previewed, which is the form
    expect(posts(calls, "/api/inbox/file")[0].body).toEqual({ requests: [expected], dry_run: false, via: "form" });
    expect(posts(calls, "/api/inbox/preview")).toHaveLength(1);
  });

  it("a rejected field keeps its value and shows why the suggestion was not used", async () => {
    const { user } = await setup(STATUS_ON, {
      ...SUGGESTION,
      folder: null,
      tray: null,
      tray_fields: {},
      rejected: { folder: "unknown folder", "tray_fields.payee": "unknown field" },
    });
    await askAI(user);
    expect(field("Folder")).toHaveValue("");
    expect(screen.getByText("AI’s folder not used: unknown folder")).toBeInTheDocument();
    expect(screen.getByText("AI’s payee not used: unknown field")).toBeInTheDocument();
    expect(screen.queryByRole("group", { name: /^Suggested Folder/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("group", { name: /^Suggested tray/ })).not.toBeInTheDocument();
  });
});

describe("ReviewCard: chips while filing", () => {
  it("the chips and Use all are disabled while a preview is in flight", async () => {
    const held = deferred<{ body: unknown }>();
    const { user } = await setup(STATUS_ON, SUGGESTION, { "POST /api/inbox/preview": () => held.promise });
    await askAI(user);
    await useChip(user, /^Suggested Folder:/); // a folder, so Preview sends
    await user.click(screen.getByRole("button", { name: "Preview" }));
    expect(screen.getByRole("button", { name: "Preview" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Use all" })).toBeDisabled();
    for (const use of screen.getAllByRole("button", { name: "Use" })) expect(use).toBeDisabled();
    await act(async () => held.resolve({ body: [] }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Use all" })).toBeEnabled());
  });
});
