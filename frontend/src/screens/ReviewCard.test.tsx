import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Profiler } from "react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { forgetUnlocks, type InboxEntry, type ResolvedOp } from "../api/client";
import {
  type Call,
  dataTransfer,
  deferred,
  IMPORTANT_REFUSED,
  mockFetch,
  quarantineRoute,
  renderWithProviders,
  replayJob,
  undoButton,
} from "../test-utils";
import Inbox from "./Inbox";

function entry(id: string, name: string, suggested: string, folder: string | null): InboxEntry {
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
      connected: true, marks: [],
    },
    suggestion: {
      name: suggested,
      folder,
      tags: ["invoice"],
      fields: {
        dates: ["2026-10-01"],
        amounts: ["123.45"],
        iban: "FI21 1234 5600 0007 85",
        reference: "RF18 5390 0754 7034",
      },
      doc_date: "2026-10-01",
      sources: ["rule:kotihoito", "date:filename"],
      name_source: "rule:kotihoito",
      folder_source: folder ? "rule:kotihoito" : null,
      tag_sources: { invoice: "rule:kotihoito" },
      tray: null,
      tray_source: null,
      collections: [],
      collection_sources: {},
      codes: [],
      conflict: false, star: null, important: null, marks_unclear: false, waiting_for_page1: false, people_found: [], areas: [], person_line: null,
    },
    text_excerpt: "Kotihoito lasku",
    prefill: {},
    tray_guess: null,
    open_trays: [],
    fields: [
      { kind: "doc_date", label: null, value: "2026-10-01" },
      { kind: "amount", label: null, value: "123.45" },
      { kind: "iban", label: null, value: "FI2112345600000785" },
      { kind: "reference", label: null, value: "RF18539007547034" },
    ],
    fields_edited: false,
    person_follows_folder: false,
  };
}

const ENTRIES = [
  entry("d1", "scan001.pdf", "2026-10-01 Kotihoito lasku.pdf", "20. Health/Kotihoito"),
  entry("d2", "scan002.pdf", "2026-10-02 Sähkölasku.pdf", "30. Home/Electricity"),
];
const FOLDERS = ["10. Financial/Banks", "20. Health/Kotihoito", "30. Home/Electricity"];

function move(src: string, dst: string, note: string | null = null): ResolvedOp {
  return { kind: "move", src, dst, drive_id: "d1", note };
}

const SIMPLE_MOVE = [
  move("##. Organize/scan001.pdf", "10. Financial/Banks/2026-10-01 Kotihoito lasku.pdf"),
];

function fileResult(overrides: Record<string, unknown> = {}) {
  return {
    batch_id: "b1",
    dry_run: false,
    done: SIMPLE_MOVE,
    failed: null,
    error: null,
    index_error: null,
    tag_error: null,
    untagged: [],
    items: [],
    follow_up_error: null,
    ...overrides,
  };
}

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
        iban: { type: "iban", required: false, prefill: "iban", copy: true },
        reference: { type: "reference", required: false, prefill: "reference", copy: true },
        urgent: { type: "checkbox", required: false, copy: false },
      },
      date_field: "due_date",
    },
    {
      id: "to-action",
      name: "To action",
      order: 2,
      item_title: "{name}",
      fields: { action_date: { type: "date", required: true, copy: false } },
      date_field: "action_date",
    },
    { id: "to-read", name: "To read", order: 3, item_title: "{name}", fields: {} },
  ],
  errors: [],
};

function collection(id: number, name: string) {
  return {
    id,
    name,
    state: "open",
    created: 1_760_000_000,
    closed_at: null,
    publish: {},
    ongoing_rel: null,
    members: [],
    ongoing_status: null,
  };
}

const COLLECTIONS = [collection(1, "Legal"), collection(2, "Sauna conversion"), collection(3, "Straße")];

function api(extra: Record<string, Parameters<typeof mockFetch>[0][string]> = {}) {
  return mockFetch({
    "GET /api/inbox": { body: ENTRIES },
    "GET /api/folders": { body: FOLDERS },
    "GET /api/trays": { body: TRAYS },
    "GET /api/collections": { body: COLLECTIONS },
    ...extra,
  });
}

const posts = (calls: Call[], url: string) =>
  calls.filter((c) => c.method === "POST" && c.url === url);

async function setup(extra: Parameters<typeof api>[0] = {}) {
  const calls = api(extra);
  const user = userEvent.setup();
  renderWithProviders(
    <MemoryRouter>
      <Inbox />
    </MemoryRouter>,
  );
  const name = await screen.findByLabelText("Name");
  return { calls, user, name: name as HTMLInputElement };
}

async function setFolder(user: ReturnType<typeof userEvent.setup>, value: string) {
  const folder = screen.getByLabelText("Folder");
  await user.clear(folder);
  await user.type(folder, value);
  return folder;
}

/** The tag chips of the filing form's tags field, in order. */
const tagList = () => Array.from(document.querySelectorAll(".tag-field .tag-token")).map((t) => t.firstChild?.textContent ?? "");
/** Removes every tag chip. */
const clearTags = async (user: ReturnType<typeof userEvent.setup>) => {
  for (const b of screen.queryAllByRole("button", { name: /^Remove tag / })) await user.click(b);
};

/** The names of the × buttons (of the collection chips) matching ``name``. */
const removers = (name: RegExp) =>
  screen.queryAllByRole("button", { name }).map((b) => b.getAttribute("aria-label") ?? "");

describe("ReviewCard", () => {
  it("a locked inbox file is not filed until it is unlocked", async () => {
    const first = ENTRIES[0].record.drive_id;
    const { calls, user } = await setup({
      "GET /api/locks": { body: { files: [{ drive_id: first, reason: "file" }], folders: [] } },
      "POST /api/inbox/preview": { body: SIMPLE_MOVE },
    });
    const fileIt = await screen.findByRole("button", { name: "File it" });
    await waitFor(() => expect(fileIt).toBeDisabled());
    expect(screen.getByRole("button", { name: "Preview" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Move to To Delete" }).closest(".button-wrap")).toHaveAttribute(
      "data-tip",
      "This file is locked. Unlock it to change it.",
    );
    expect(screen.getByRole("button", { name: "Unlock" })).toBeInTheDocument();
    await user.keyboard("{Meta>}{Enter}{/Meta}");
    expect(posts(calls, "/api/inbox/file")).toHaveLength(0);
  });

  it("renders the suggested name, folder, tags and detected fields", async () => {
    const { name } = await setup();
    expect(name).toHaveValue("2026-10-01 Kotihoito lasku.pdf");
    expect(screen.getByLabelText("Folder")).toHaveValue("20. Health/Kotihoito");
    expect(tagList()).toEqual(["invoice"]);
    const fields = screen.getByRole("region", { name: "Detected fields" });
    expect(within(fields).getByText("1.10.2026")).toBeInTheDocument();
    expect(within(fields).getByText("123,45 €")).toBeInTheDocument();
    expect(within(fields).getByText("RF18539007547034")).toBeInTheDocument();
    expect(within(fields).getByText("FI21 1234 5600 0007 85")).toBeInTheDocument();
    expect(within(fields).getByText(/rule kotihoito/)).toBeInTheDocument();
    expect(within(fields).queryByText(/mtime|text-date/)).not.toBeInTheDocument();
  });

  it("the inbox list has a resizable splitter", async () => {
    await setup();
    expect(screen.getByRole("separator", { name: "Resize the list" })).toHaveAttribute("aria-valuenow", "280");
  });

  it("Cmd+Enter files a simple single move directly with the edited folder", async () => {
    const { calls, user } = await setup({
      "POST /api/inbox/preview": { body: SIMPLE_MOVE },
      "POST /api/inbox/file": { body: fileResult() },
      "POST /api/activity/b1/undo/preview": { body: [] },
    });
    await setFolder(user, "10. Financial/Banks");
    await user.keyboard("{Meta>}{Enter}{/Meta}");

    await waitFor(() => expect(posts(calls, "/api/inbox/file")).toHaveLength(1));
    const request = {
      drive_id: "d1",
      name: "2026-10-01 Kotihoito lasku.pdf",
      folder: "10. Financial/Banks",
      tags: ["invoice"],
    };
    const [preview] = posts(calls, "/api/inbox/preview");
    expect(preview.body).toEqual([request]);
    const [file] = posts(calls, "/api/inbox/file");
    expect(file.headers["Content-Type"]).toBe("application/json");
    expect(file.credentials).toBe("same-origin");
    expect(file.body).toEqual({ requests: [request], dry_run: false, via: "form" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

    // Advances to the next entry and offers undo.
    await waitFor(() =>
      expect(screen.getByLabelText("Name")).toHaveValue("2026-10-02 Sähkölasku.pdf"),
    );
    await user.click(await screen.findByRole("button", { name: "Undo" }));
    const undo = await screen.findByRole("dialog", { name: "Undo these changes?" });
    expect(posts(calls, "/api/activity/b1/undo")).toHaveLength(0);
    await user.click(await undoButton(undo));
    await waitFor(() => expect(posts(calls, "/api/activity/b1/undo")).toHaveLength(1));
  });

  it("u asks before undoing the last batch and sends one undo however often confirmed", async () => {
    const { calls, user } = await setup({
      "POST /api/inbox/preview": { body: SIMPLE_MOVE },
      "POST /api/inbox/file": { body: fileResult() },
      "POST /api/activity/b1/undo/preview": { body: [{ ...SIMPLE_MOVE[0], src: SIMPLE_MOVE[0].dst, dst: SIMPLE_MOVE[0].src }] },
      "POST /api/activity/b1/undo": { body: { ...fileResult(), batch_id: "u1" } },
    });
    await user.click(screen.getByRole("button", { name: "File it" }));
    await screen.findByRole("button", { name: "Undo" });
    (document.activeElement as HTMLElement | null)?.blur();
    await user.keyboard("u");
    const undo = await screen.findByRole("dialog", { name: "Undo these changes?" });
    expect(await within(undo).findByText("Undoing will:")).toBeInTheDocument();
    expect(posts(calls, "/api/activity/b1/undo/preview")).toHaveLength(1);
    const back = undo.querySelector(".plan-op");
    expect(back).toHaveTextContent(`${SIMPLE_MOVE[0].dst} → ${SIMPLE_MOVE[0].src}`);
    await user.keyboard("u"); // a second u while the confirm is open does nothing
    expect(posts(calls, "/api/activity/b1/undo")).toHaveLength(0);
    // Two clicks in the same tick: only the in-flight guard can stop the second one.
    const button = await undoButton(undo);
    fireEvent.click(button);
    fireEvent.click(button);
    await waitFor(() => expect(posts(calls, "/api/activity/b1/undo")).toHaveLength(1));
    await new Promise((r) => setTimeout(r, 20));
    expect(posts(calls, "/api/activity/b1/undo")).toHaveLength(1);
    expect(posts(calls, "/api/activity/b1/undo")[0].headers["Content-Type"]).toBe(
      "application/json",
    );
  });

  it.each([
    [400, "invalid name 'a/b'"],
    [409, "destination changed during the batch"],
  ])("a %i from File it shows the error and does not advance", async (status, error) => {
    const { calls, user } = await setup({
      "POST /api/inbox/preview": { body: SIMPLE_MOVE },
      "POST /api/inbox/file": { status, body: { error } },
    });
    await user.click(screen.getByRole("button", { name: "File it" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(error);
    expect(screen.getByLabelText("Name")).toHaveValue("2026-10-01 Kotihoito lasku.pdf");
    expect(posts(calls, "/api/inbox/file")).toHaveLength(1);
    expect(screen.queryByRole("button", { name: "Undo" })).not.toBeInTheDocument();
  });

  it("shows hidden characters in a filing error", async () => {
    await setup({
      "POST /api/inbox/preview": { body: SIMPLE_MOVE },
      "POST /api/inbox/file": { status: 409, body: { error: "changed: a\u202Efdp.exe" } },
    });
    await userEvent.click(screen.getByRole("button", { name: "File it" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("changed: a⟨U+202E⟩fdp.exe");
  });

  it("a 400 from the preview shows the error and files nothing", async () => {
    const { calls, user } = await setup({
      "POST /api/inbox/preview": { status: 400, body: { error: "invalid name 'a/b'" } },
    });
    await user.click(screen.getByRole("button", { name: "File it" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("invalid name 'a/b'");
    expect(posts(calls, "/api/inbox/file")).toHaveLength(0);
    expect(screen.getByLabelText("Name")).toHaveValue("2026-10-01 Kotihoito lasku.pdf");
  });

  it("a plan with an MKDIR opens the confirm dialog instead of posting", async () => {
    const plan: ResolvedOp[] = [
      { kind: "mkdir", src: null, dst: "40. New", drive_id: null, note: "create missing folder" },
      move("##. Organize/scan001.pdf", "40. New/2026-10-01 Kotihoito lasku.pdf"),
    ];
    const { calls, user } = await setup({
      "POST /api/inbox/preview": { body: plan },
      "POST /api/inbox/file": { body: fileResult({ done: plan }) },
    });
    await setFolder(user, "40. New");
    await user.keyboard("{Meta>}{Enter}{/Meta}");

    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("40. New")).toBeInTheDocument();
    expect(within(dialog).getByText(/create missing folder/)).toBeInTheDocument();
    expect(posts(calls, "/api/inbox/file")).toHaveLength(0);

    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(posts(calls, "/api/inbox/file")).toHaveLength(0);

    // the shown plan has File it of its own, and × closes it
    const shown = screen.getByRole("region", { name: "Planned changes" });
    await user.click(within(shown).getByRole("button", { name: "File it" }));
    await user.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "File" }));
    await waitFor(() => expect(posts(calls, "/api/inbox/file")).toHaveLength(1));
    const previewed = posts(calls, "/api/inbox/preview").at(-1)!.body;
    expect(posts(calls, "/api/inbox/file")[0].body).toEqual({ requests: previewed, dry_run: false, via: "form" });
  });

  it("a collision note opens the confirm dialog", async () => {
    const plan = [
      move(
        "##. Organize/scan001.pdf",
        "20. Health/Kotihoito/2026-10-01 Kotihoito lasku_2.pdf",
        "renamed to avoid collision",
      ),
    ];
    const { calls, user } = await setup({ "POST /api/inbox/preview": { body: plan } });
    await user.click(screen.getByRole("button", { name: "File it" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/renamed to avoid collision/)).toBeInTheDocument();
    expect(posts(calls, "/api/inbox/file")).toHaveLength(0);
  });

  it("shows a tagging failure as a warning", async () => {
    const { user } = await setup({
      "POST /api/inbox/preview": { body: SIMPLE_MOVE },
      "POST /api/inbox/file": {
        body: fileResult({ tag_error: "OperationalError: locked", untagged: ["d1"] }),
      },
    });
    await user.click(screen.getByRole("button", { name: "File it" }));
    expect(await screen.findByText(/OperationalError: locked/)).toBeInTheDocument();
  });

  it("ignores shortcuts while typing in the name field", async () => {
    const { calls, user, name } = await setup({ "POST /api/inbox/preview": { body: SIMPLE_MOVE } });
    await user.click(name);
    await user.keyboard("jkfnu{Enter}");
    expect(name).toHaveValue("2026-10-01 Kotihoito lasku.pdfjkfnu");
    expect(name).toHaveFocus();
    expect(calls.filter((c) => c.method === "POST")).toHaveLength(0);

    await user.keyboard("{Escape}");
    expect(name).not.toHaveFocus();
    await user.keyboard("j");
    expect(screen.getByLabelText("Name")).toHaveValue("2026-10-02 Sähkölasku.pdf");
  });

  it("keeps the selected entry scrolled into view in the list", async () => {
    const scrolled: string[] = [];
    const spy = vi
      .spyOn(HTMLElement.prototype, "scrollIntoView")
      .mockImplementation(function (this: HTMLElement) {
        scrolled.push(this.textContent ?? "");
      });
    try {
      const { user } = await setup();
      scrolled.length = 0;
      await user.keyboard("j");
      expect(scrolled.at(-1)).toContain("Sähkölasku");
    } finally {
      spy.mockRestore();
    }
  });

  it("j/k move between entries, n and f focus the fields, Enter previews", async () => {
    const { calls, user } = await setup({ "POST /api/inbox/preview": { body: SIMPLE_MOVE } });
    await user.keyboard("j");
    expect(screen.getByLabelText("Name")).toHaveValue("2026-10-02 Sähkölasku.pdf");
    await user.keyboard("k");
    expect(screen.getByLabelText("Name")).toHaveValue("2026-10-01 Kotihoito lasku.pdf");

    await user.keyboard("f");
    expect(screen.getByLabelText("Folder")).toHaveFocus();
    await user.keyboard("{Escape}{Escape}n");
    expect(screen.getByLabelText("Name")).toHaveFocus();
    await user.keyboard("{Escape}{Enter}");

    const plan = await screen.findByRole("region", { name: "Planned changes" });
    expect(within(plan).getByText(SIMPLE_MOVE[0].dst)).toBeInTheDocument();
    expect(posts(calls, "/api/inbox/preview")).toHaveLength(1);
    expect(posts(calls, "/api/inbox/file")).toHaveLength(0);
  });

  it("the batch card's file list shows each file's ★ / ! icons", async () => {
    const marked = [{ ...ENTRIES[0], record: { ...ENTRIES[0].record, marks: ["starred" as const] } }, ENTRIES[1]];
    const { user } = await setup({ "GET /api/inbox": { body: marked } });
    await user.click(screen.getByRole("checkbox", { name: "Select scan001.pdf" }));
    await user.click(screen.getByRole("checkbox", { name: "Select scan002.pdf" }));
    const files = await screen.findByRole("list", { name: "Files" });
    const [first, second] = within(files).getAllByRole("listitem");
    expect(within(first).getByRole("img", { name: "Starred" })).toBeInTheDocument();
    expect(within(second).queryByRole("img")).toBeNull();
  });

  it("batch mode always confirms and sends one request per file", async () => {
    const { calls, user } = await setup({
      "POST /api/inbox/preview": { body: SIMPLE_MOVE },
      "POST /api/inbox/file": { body: fileResult() },
    });
    await user.click(screen.getByRole("checkbox", { name: "Select scan001.pdf" }));
    await user.click(screen.getByRole("checkbox", { name: "Select scan002.pdf" }));
    await setFolder(user, "10. Financial/Banks");
    await user.type(screen.getByLabelText("Tags"), "2026");
    await user.click(screen.getByRole("button", { name: "File 2 files" }));

    const dialog = await screen.findByRole("dialog");
    expect(posts(calls, "/api/inbox/file")).toHaveLength(0);
    await user.click(within(dialog).getByRole("button", { name: "File" }));
    await waitFor(() => expect(posts(calls, "/api/inbox/file")).toHaveLength(1));
    expect(posts(calls, "/api/inbox/file")[0].body).toEqual({
      dry_run: false,
      via: "batch",
      requests: [
        {
          drive_id: "d1",
          name: "2026-10-01 Kotihoito lasku.pdf",
          folder: "10. Financial/Banks",
          tags: ["2026"],
        },
        {
          drive_id: "d2",
          name: "2026-10-02 Sähkölasku.pdf",
          folder: "10. Financial/Banks",
          tags: ["2026"],
        },
      ],
    });
  });
  describe("keyboard confirm in the dialog", () => {
    const MKDIR_PLAN: ResolvedOp[] = [
      { kind: "mkdir", src: null, dst: "40. New", drive_id: null, note: "create missing folder" },
      move("##. Organize/scan001.pdf", "40. New/2026-10-01 Kotihoito lasku.pdf"),
    ];

    /** performance.now() runs on, plus whatever the test adds with ``advance``. */
    function clock() {
      const real = performance.now.bind(performance);
      let offset = 0;
      vi.spyOn(performance, "now").mockImplementation(() => real() + offset);
      return { advance: (ms: number) => (offset += ms) };
    }

    /** Cmd+Enter with keys released before the MKDIR confirm opens. */
    async function openByKeyboard() {
      const held = deferred<{ body: unknown }>();
      const env = await setup({
        "POST /api/inbox/preview": () => held.promise,
        "POST /api/inbox/file": { body: fileResult({ done: MKDIR_PLAN }) },
      });
      await env.user.keyboard("{Meta>}{Enter}{/Meta}");
      await act(async () => held.resolve({ body: MKDIR_PLAN }));
      const dialog = await screen.findByRole("dialog");
      return { ...env, dialog };
    }

    const settle = () => new Promise((r) => setTimeout(r, 20));

    it("Cmd+Enter pressed twice on an MKDIR plan never confirms it", async () => {
      const time = clock();
      const held = deferred<{ body: unknown }>();
      const { calls, user } = await setup({
        "POST /api/inbox/preview": () => held.promise,
        "POST /api/inbox/file": { body: fileResult({ done: MKDIR_PLAN }) },
      });
      await user.keyboard("{Meta>}{Enter}{/Meta}{Meta>}{Enter}{/Meta}");
      await act(async () => held.resolve({ body: MKDIR_PLAN }));
      const dialog = await screen.findByRole("dialog");
      const cancel = within(dialog).getByRole("button", { name: "Cancel" });
      expect(cancel).toHaveFocus();
      // Straight after it opened: ignored.
      fireEvent.keyDown(cancel, { key: "Enter", metaKey: true });
      await settle();
      expect(posts(calls, "/api/inbox/preview")).toHaveLength(1);
      expect(posts(calls, "/api/inbox/file")).toHaveLength(0);
      // Once the dialog has been visible long enough, a deliberate Cmd+Enter confirms.
      time.advance(600);
      await user.keyboard("{Meta>}{Enter}{/Meta}");
      await waitFor(() => expect(posts(calls, "/api/inbox/file")).toHaveLength(1));
    });

    it("a reflexive second press 100 ms after opening does not confirm", async () => {
      const time = clock();
      const { calls, user } = await openByKeyboard();
      time.advance(100);
      await user.keyboard("{Meta>}{Enter}{/Meta}");
      await settle();
      expect(posts(calls, "/api/inbox/file")).toHaveLength(0);
    });

    it("a press 600 ms after opening confirms exactly once", async () => {
      const time = clock();
      const { calls, user } = await openByKeyboard();
      time.advance(600);
      await user.keyboard("{Meta>}{Enter}{/Meta}");
      await waitFor(() => expect(posts(calls, "/api/inbox/file")).toHaveLength(1));
      await settle();
      expect(posts(calls, "/api/inbox/file")).toHaveLength(1);
    });

    it("keys held at open and never released never confirm", async () => {
      const time = clock();
      const held = deferred<{ body: unknown }>();
      const { calls, user } = await setup({
        "POST /api/inbox/preview": () => held.promise,
        "POST /api/inbox/file": { body: fileResult({ done: MKDIR_PLAN }) },
      });
      await user.keyboard("{Meta>}{Enter>}"); // pressed and still held
      await act(async () => held.resolve({ body: MKDIR_PLAN }));
      const dialog = await screen.findByRole("dialog");
      time.advance(600);
      fireEvent.keyDown(within(dialog).getByRole("button", { name: "Cancel" }), {
        key: "Enter",
        metaKey: true,
      });
      await settle();
      expect(posts(calls, "/api/inbox/file")).toHaveLength(0);
    });

    it("a mouse-opened confirm takes Cmd+Enter after the delay", async () => {
      const time = clock();
      const plan = [move("##. Organize/scan001.pdf", "X/a_2.pdf", "renamed to avoid collision")];
      const { calls, user } = await setup({
        "POST /api/inbox/preview": { body: plan },
        "POST /api/inbox/file": { body: fileResult({ done: plan }) },
      });
      await user.click(screen.getByRole("button", { name: "File it" }));
      await screen.findByRole("dialog");
      time.advance(600);
      await user.keyboard("{Meta>}{Enter}{/Meta}");
      await waitFor(() => expect(posts(calls, "/api/inbox/file")).toHaveLength(1));
    });

    it("Enter on the focused Apply button applies at once", async () => {
      const { calls, user, dialog } = await openByKeyboard();
      within(dialog).getByRole("button", { name: "File" }).focus();
      await user.keyboard("{Enter}");
      await waitFor(() => expect(posts(calls, "/api/inbox/file")).toHaveLength(1));
    });
  });

  it("File it never applies a preview that answers for an edited form", async () => {
    const held = deferred<{ body: unknown }>();
    const { calls, user } = await setup({
      "POST /api/inbox/preview": () => held.promise,
      "POST /api/inbox/file": { body: fileResult() },
    });
    await user.click(screen.getByRole("button", { name: "File it" }));
    await setFolder(user, "10. Financial/Banks");
    await act(async () => held.resolve({ body: SIMPLE_MOVE }));
    expect(await screen.findByText("Form changed — press File it again")).toBeInTheDocument();
    await new Promise((r) => setTimeout(r, 20));
    expect(posts(calls, "/api/inbox/file")).toHaveLength(0);
  });

  it("an error stays with its entry", async () => {
    const { user } = await setup({
      "POST /api/inbox/preview": { body: SIMPLE_MOVE },
      "POST /api/inbox/file": { status: 409, body: { error: "source changed" } },
    });
    await user.click(screen.getByRole("button", { name: "File it" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("source changed");
    (document.activeElement as HTMLElement | null)?.blur();
    await user.keyboard("j");
    expect(screen.getByLabelText("Name")).toHaveValue("2026-10-02 Sähkölasku.pdf");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    await user.keyboard("k");
    expect(screen.getByRole("alert")).toHaveTextContent("source changed");
  });

  it("an error for an entry that left the inbox becomes a toast naming the file", async () => {
    let lists = 0;
    const { user } = await setup({
      "GET /api/inbox": () => ({ body: ++lists === 1 ? ENTRIES : ENTRIES.slice(1) }),
      "POST /api/inbox/preview": { body: SIMPLE_MOVE },
      "POST /api/inbox/file": { status: 409, body: { error: "source changed" } },
    });
    await user.click(screen.getByRole("button", { name: "File it" }));
    expect(await screen.findByText(/scan001\.pdf: source changed/)).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("the toast Undo is disabled while a file call is in flight", async () => {
    const held = deferred<{ body: unknown }>();
    let files = 0;
    const { calls, user } = await setup({
      "POST /api/inbox/preview": { body: SIMPLE_MOVE },
      "POST /api/inbox/file": () => (++files === 1 ? { body: fileResult() } : held.promise),
    });
    await user.click(screen.getByRole("button", { name: "File it" }));
    const toastUndo = await screen.findByRole("button", { name: "Undo" });
    expect(toastUndo).toBeEnabled();
    await waitFor(() =>
      expect(screen.getByLabelText("Name")).toHaveValue("2026-10-02 Sähkölasku.pdf"),
    );
    await user.click(screen.getByRole("button", { name: "File it" }));
    await waitFor(() => expect(posts(calls, "/api/inbox/file")).toHaveLength(2));
    expect(screen.getByRole("button", { name: "Undo" })).toBeDisabled();
    await act(async () => held.resolve({ body: fileResult({ batch_id: "b2" }) }));
    await waitFor(() => expect(screen.getAllByRole("button", { name: "Undo" })[0]).toBeEnabled());
  });

  it("shows hidden characters in inbox names", async () => {
    mockFetch({
      "GET /api/inbox": { body: [entry("d9", "in\u202Efdp.exe", "x\u200By.pdf", null)] },
      "GET /api/folders": { body: FOLDERS },
    });
    renderWithProviders(
      <MemoryRouter>
        <Inbox />
      </MemoryRouter>,
    );
    // the list shows the suggestion as the title and the file's own name under it
    expect((await screen.findAllByText("in⟨U+202E⟩fdp.exe")).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/x⟨U\+200B⟩y/).length).toBeGreaterThan(0);
  });

  it("ignores auto-repeated keydowns", async () => {
    const { calls } = await setup({ "POST /api/inbox/preview": { body: SIMPLE_MOVE } });
    fireEvent.keyDown(document.body, { key: "Enter", metaKey: true, repeat: true });
    fireEvent.keyDown(document.body, { key: "Enter", repeat: true });
    fireEvent.keyDown(document.body, { key: "j", repeat: true });
    await new Promise((r) => setTimeout(r, 20));
    expect(calls.filter((c) => c.method === "POST")).toHaveLength(0);
    expect(screen.getByLabelText("Name")).toHaveValue("2026-10-01 Kotihoito lasku.pdf");
  });

  it("holding Cmd+Enter on simple moves files at most one entry", async () => {
    const { calls, user } = await setup({
      "POST /api/inbox/preview": { body: SIMPLE_MOVE },
      "POST /api/inbox/file": { body: fileResult() },
    });
    await user.keyboard("{Meta>}{Enter>8}{/Enter}{/Meta}");
    await new Promise((r) => setTimeout(r, 50));
    expect(posts(calls, "/api/inbox/file").length).toBeLessThanOrEqual(1);
  });

  it("j while File it is in flight is ignored and the 409 still shows", async () => {
    const held = deferred<{ status: number; body: unknown }>();
    const { calls, user } = await setup({
      "POST /api/inbox/preview": { body: SIMPLE_MOVE },
      "POST /api/inbox/file": () => held.promise,
    });
    await user.keyboard("{Meta>}{Enter}{/Meta}");
    await waitFor(() => expect(posts(calls, "/api/inbox/file")).toHaveLength(1));
    await user.keyboard("j");
    expect(screen.getByLabelText("Name")).toHaveValue("2026-10-01 Kotihoito lasku.pdf");
    await act(async () => held.resolve({ status: 409, body: { error: "source changed" } }));
    expect(await screen.findByRole("alert")).toHaveTextContent("source changed");
    expect(screen.getByLabelText("Name")).toHaveValue("2026-10-01 Kotihoito lasku.pdf");
  });

  it("drops a preview that answers for an edited form; File it previews again", async () => {
    const held = deferred<{ body: unknown }>();
    let previews = 0;
    const { calls, user } = await setup({
      "POST /api/inbox/preview": () => (++previews === 1 ? held.promise : { body: SIMPLE_MOVE }),
      "POST /api/inbox/file": { body: fileResult() },
    });
    await user.keyboard("{Enter}");
    await setFolder(user, "10. Financial/Banks");
    await act(async () =>
      held.resolve({ body: [move("##. Organize/scan001.pdf", "20. Health/Kotihoito/stale.pdf")] }),
    );
    expect(screen.queryByRole("region", { name: "Planned changes" })).not.toBeInTheDocument();
    expect(screen.queryByText(/stale\.pdf/)).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "File it" }));
    await waitFor(() => expect(posts(calls, "/api/inbox/file")).toHaveLength(1));
    const previewBodies = posts(calls, "/api/inbox/preview").map((c) => c.body);
    expect(previewBodies).toHaveLength(2);
    expect(posts(calls, "/api/inbox/file")[0].body).toEqual({
      requests: previewBodies[1],
      dry_run: false,
      via: "form",
    });
    expect((previewBodies[1] as { folder: string }[])[0].folder).toBe("10. Financial/Banks");
  });

  it("Esc closes the confirm dialog", async () => {
    const plan = [move("##. Organize/scan001.pdf", "X/a_2.pdf", "renamed to avoid collision")];
    const { calls, user } = await setup({ "POST /api/inbox/preview": { body: plan } });
    await user.click(screen.getByRole("button", { name: "File it" }));
    await screen.findByRole("dialog");
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(posts(calls, "/api/inbox/file")).toHaveLength(0);
  });

  it("warns when files landed somewhere other than previewed", async () => {
    const { user } = await setup({
      "POST /api/inbox/preview": { body: SIMPLE_MOVE },
      "POST /api/inbox/file": {
        body: fileResult({
          done: [move("##. Organize/scan001.pdf", "10. Financial/Banks/lasku_2.pdf", "renamed")],
        }),
      },
    });
    await user.click(screen.getByRole("button", { name: "File it" }));
    expect(
      await screen.findByText(/other than previewed: 10\. Financial\/Banks\/lasku_2\.pdf/),
    ).toBeInTheDocument();
  });
  it("batch folder follows the selection until the user edits it", async () => {
    const { user } = await setup();
    await user.click(screen.getByRole("checkbox", { name: "Select scan001.pdf" }));
    expect(screen.getByLabelText("Folder")).toHaveValue("20. Health/Kotihoito");
    await user.click(screen.getByRole("checkbox", { name: "Select scan002.pdf" }));
    expect(screen.getByLabelText("Folder")).toHaveValue(""); // suggestions differ
    await setFolder(user, "10. Financial/Banks");
    await user.click(screen.getByRole("checkbox", { name: "Select scan002.pdf" }));
    expect(screen.getByLabelText("Folder")).toHaveValue("10. Financial/Banks");
  });

  it("a second file selected never shows the first file's folder in between (no flicker)", async () => {
    api();
    // after every commit: how many files are ticked, and what the folder field shows
    const seen: string[] = [];
    const probe = () => {
      const folder = document.querySelector<HTMLInputElement>(".inbox-card input[role=combobox]");
      const ticked = document.querySelectorAll<HTMLInputElement>("input[type=checkbox][aria-label^='Select ']:checked").length;
      if (folder) seen.push(`${ticked}:${folder.value}`);
    };
    renderWithProviders(
      <MemoryRouter>
        <Profiler id="inbox" onRender={probe}>
          <Inbox />
        </Profiler>
      </MemoryRouter>,
    );
    await screen.findByLabelText("Name");
    const user = userEvent.setup();
    await user.click(screen.getByRole("checkbox", { name: "Select scan001.pdf" }));
    expect(screen.getByLabelText("Folder")).toHaveValue("20. Health/Kotihoito");
    await user.click(screen.getByRole("checkbox", { name: "Select scan002.pdf" }));
    expect(screen.getByLabelText("Folder")).toHaveValue("");
    expect(seen).toContain("2:");
    expect(seen).not.toContain("2:20. Health/Kotihoito");
  });

  it("every folder field has the Browse folders… button: the single and the batch card", async () => {
    await setup();
    expect(within(screen.getByRole("region", { name: "Review" })).getByRole("button", { name: "Browse folders…" })).toBeInTheDocument();
    const user = userEvent.setup();
    await user.click(screen.getByRole("checkbox", { name: "Select scan001.pdf" }));
    await user.click(screen.getByRole("checkbox", { name: "Select scan002.pdf" }));
    expect(within(screen.getByRole("region", { name: "Review" })).getByRole("button", { name: "Browse folders…" })).toBeInTheDocument();
  });

  describe("filing into trays", () => {
    const PREFILLED = [
      {
        ...ENTRIES[0],
        prefill: { due_date: "2026-10-15", total: "84.20", reference: "RF18539007547034" },
      },
      ENTRIES[1],
    ];

    async function trays(extra: Parameters<typeof api>[0] = {}) {
      const env = await setup({ "GET /api/inbox": { body: PREFILLED }, ...extra });
      await screen.findByRole("button", { name: "To pay" });
      return env;
    }

    const pressed = (name: string) => screen.getByRole("button", { name, pressed: true });
    const field = (label: RegExp) => screen.getByLabelText(label) as HTMLInputElement;

    it("defaults to Nothing and shows the tray's fields prefilled from the scan", async () => {
      const { user } = await trays();
      expect(pressed("Nothing (just file)")).toBeInTheDocument();
      expect(screen.queryByLabelText(/^Due date/)).not.toBeInTheDocument();
      expect(screen.getByRole("button", { name: "To pay" })).toHaveAttribute("aria-keyshortcuts", "1");

      await user.click(screen.getByRole("button", { name: "To pay" }));
      expect(pressed("To pay")).toBeInTheDocument();
      expect(field(/^Due date/)).toHaveValue("2026-10-15");
      expect(field(/^Due date/)).toHaveAttribute("type", "date");
      expect(screen.getByText("Due date")).toBeInTheDocument();
      expect(screen.queryByText(/required/)).not.toBeInTheDocument();
      expect(field(/^Amount/)).toHaveValue("84,20");
      expect(field(/^Reference/)).toHaveValue("RF18539007547034");
      expect(field(/^IBAN/)).toHaveValue("");
      expect(field(/^Urgent/)).not.toBeChecked();
      expect(screen.getAllByText("found in scan")).toHaveLength(3);

      // Editing a field drops its "found in scan"; a required field left empty is
      // neither blocked nor nagged about.
      fireEvent.change(field(/^Due date/), { target: { value: "" } });
      expect(screen.getAllByText("found in scan")).toHaveLength(2);
      expect(screen.queryByText(/needs a due date/)).not.toBeInTheDocument();
    });

    it("the file request carries tray, fields, collections and note exactly as shown", async () => {
      const { calls, user } = await trays({
        "POST /api/inbox/preview": { body: SIMPLE_MOVE },
        "POST /api/inbox/file": { body: fileResult({ items: [7] }) },
      });
      await user.click(screen.getByRole("button", { name: "To pay" }));
      await user.clear(field(/^Amount/));
      await user.type(field(/^Amount/), "90,00");
      fireEvent.change(field(/^Reference/), { target: { value: "" } });

      const picker = screen.getByLabelText("Also add to collection");
      await user.type(picker, "Kitchen{Enter}"); // new: created on filing
      await user.type(picker, "leg");
      expect(screen.getByRole("option", { name: 'Create collection "leg"' })).toBeInTheDocument();
      await user.keyboard("{ArrowDown}{Enter}"); // the existing "Legal"
      await user.type(picker, "kitchen{Enter}"); // already chosen: no second chip
      expect(removers(/^Remove (Kitchen|Legal)$/)).toEqual(["Remove Kitchen", "Remove Legal"]);
      await user.type(screen.getByLabelText("Note (optional)"), "Pay before the trip");
      // Enter in the picker and typing never previewed or filed anything.
      expect(calls.filter((c) => c.method === "POST")).toHaveLength(0);

      await user.click(screen.getByRole("button", { name: "File it" }));
      await waitFor(() => expect(posts(calls, "/api/inbox/file")).toHaveLength(1));
      const request = {
        drive_id: "d1",
        name: "2026-10-01 Kotihoito lasku.pdf",
        folder: "20. Health/Kotihoito",
        tags: ["invoice"],
        tray: "to-pay",
        tray_fields: {
          due_date: "2026-10-15",
          amount: "90,00",
          iban: "",
          reference: "",
          urgent: false,
        },
        collections: ["Kitchen", "Legal"],
        note: "Pay before the trip",
      };
      expect(posts(calls, "/api/inbox/preview")[0].body).toEqual([request]);
      expect(posts(calls, "/api/inbox/file")[0].body).toEqual({ requests: [request], dry_run: false, via: "form" });
      expect(
        await screen.findByText(
          "Filed as 10. Financial/Banks/2026-10-01 Kotihoito lasku.pdf · added to To pay, Kitchen, Legal",
        ),
      ).toBeInTheDocument();
    });

    it("changing the tray after a preview previews again before applying", async () => {
      const { calls, user } = await trays({
        "POST /api/inbox/preview": { body: SIMPLE_MOVE },
        "POST /api/inbox/file": { body: fileResult() },
      });
      await user.keyboard("{Enter}");
      await screen.findByRole("region", { name: "Planned changes" });
      await user.click(screen.getByRole("button", { name: "To read" }));
      expect(screen.queryByRole("region", { name: "Planned changes" })).not.toBeInTheDocument();

      await user.click(screen.getByRole("button", { name: "File it" }));
      await waitFor(() => expect(posts(calls, "/api/inbox/file")).toHaveLength(1));
      const previews = posts(calls, "/api/inbox/preview").map((c) => c.body as { tray?: string }[]);
      expect(previews).toHaveLength(2);
      expect(previews[0][0].tray).toBeUndefined();
      expect(previews[1][0]).toMatchObject({ tray: "to-read", tray_fields: {} });
      expect(posts(calls, "/api/inbox/file")[0].body).toEqual({ requests: previews[1], dry_run: false, via: "form" });
    });

    it("1–9 pick a tray and 0 picks Nothing, never while typing", async () => {
      const { user, name } = await trays();
      (document.activeElement as HTMLElement | null)?.blur();
      await user.keyboard("1");
      expect(pressed("To pay")).toBeInTheDocument();
      await user.keyboard("3");
      expect(pressed("To read")).toBeInTheDocument();
      await user.keyboard("9"); // no ninth tray: nothing changes
      expect(pressed("To read")).toBeInTheDocument();
      await user.keyboard("0");
      expect(pressed("Nothing (just file)")).toBeInTheDocument();

      await user.click(name);
      await user.keyboard("1");
      expect(name).toHaveValue("2026-10-01 Kotihoito lasku.pdf1");
      expect(pressed("Nothing (just file)")).toBeInTheDocument();
      await user.click(screen.getByLabelText("Note (optional)"));
      await user.keyboard("2");
      expect(pressed("Nothing (just file)")).toBeInTheDocument();
      await user.click(screen.getByLabelText("Also add to collection"));
      await user.keyboard("2");
      expect(screen.getByLabelText("Also add to collection")).toHaveValue("2");
      expect(pressed("Nothing (just file)")).toBeInTheDocument();

      // The tray's own fields: text and date inputs.
      await user.click(screen.getByRole("button", { name: "To pay" }));
      await user.click(field(/^Amount/));
      await user.keyboard("3");
      expect(field(/^Amount/)).toHaveValue("84,203");
      fireEvent.keyDown(field(/^Due date/), { key: "2" });
      fireEvent.keyDown(field(/^Due date/), { key: "0" });
      expect(pressed("To pay")).toBeInTheDocument();
    });

    it("the next entry starts with Nothing again", async () => {
      const { user } = await trays();
      await user.click(screen.getByRole("button", { name: "To pay" }));
      await user.keyboard("j");
      expect(screen.getByLabelText("Name")).toHaveValue("2026-10-02 Sähkölasku.pdf");
      expect(pressed("Nothing (just file)")).toBeInTheDocument();
      await user.keyboard("k");
      expect(pressed("Nothing (just file)")).toBeInTheDocument();
    });

    it("the confirm lists the tray, collections and note", async () => {
      const plan: ResolvedOp[] = [
        { kind: "mkdir", src: null, dst: "40. New", drive_id: null, note: "create missing folder" },
        move("##. Organize/scan001.pdf", "40. New/2026-10-01 Kotihoito lasku.pdf"),
      ];
      const { user } = await trays({ "POST /api/inbox/preview": { body: plan } });
      await user.click(screen.getByRole("button", { name: "To pay" }));
      await user.type(screen.getByLabelText("Also add to collection"), "Sauna conversion{Enter}");
      await user.type(screen.getByLabelText("Note (optional)"), "ask‮");
      await user.click(screen.getByRole("button", { name: "File it" }));
      const dialog = await screen.findByRole("dialog");
      expect(
        within(dialog).getByText(
          "Put in To pay: due date 15.10.2026, amount 84,20 €, reference RF18539007547034, urgent no",
        ),
      ).toBeInTheDocument();
      expect(within(dialog).getByText("Add to collection: Sauna conversion")).toBeInTheDocument();
      expect(within(dialog).getByText("Note: ask⟨U+202E⟩")).toBeInTheDocument();
    });

    it("a follow-up error is a warning naming the file", async () => {
      const { user } = await trays({
        "POST /api/inbox/preview": { body: SIMPLE_MOVE },
        "POST /api/inbox/file": {
          body: fileResult({ follow_up_error: "note not added: scan001.pdf already has a note" }),
        },
      });
      await user.type(screen.getByLabelText("Note (optional)"), "  x  ");
      await user.click(screen.getByRole("button", { name: "File it" }));
      expect(
        await screen.findByText(
          "2026-10-01 Kotihoito lasku.pdf: Filed, but adding to tray/collection failed: note not added: scan001.pdf already has a note",
        ),
      ).toBeInTheDocument();
      expect(screen.getByText("Filed as 10. Financial/Banks/2026-10-01 Kotihoito lasku.pdf")).toBeInTheDocument();
    });

    it("sends the note trimmed, as the server stores it", async () => {
      const { calls, user } = await trays({
        "POST /api/inbox/preview": { body: SIMPLE_MOVE },
        "POST /api/inbox/file": { body: fileResult() },
      });
      await user.type(screen.getByLabelText("Note (optional)"), "  call first  ");
      await user.click(screen.getByRole("button", { name: "File it" }));
      await waitFor(() => expect(posts(calls, "/api/inbox/file")).toHaveLength(1));
      const body = posts(calls, "/api/inbox/file")[0].body as { requests: { note?: string }[] };
      expect(body.requests[0].note).toBe("call first");
    });

    it("never files while a collection name is typed but not added", async () => {
      const { calls, user } = await trays({
        "POST /api/inbox/preview": { body: SIMPLE_MOVE },
        "POST /api/inbox/file": { body: fileResult() },
      });
      await user.type(screen.getByLabelText("Also add to collection"), "Kitchen");
      await user.keyboard("{Meta>}{Enter}{/Meta}");
      expect(await screen.findByRole("alert")).toHaveTextContent(
        "Press Enter to add ‘Kitchen’ or clear it",
      );
      (document.activeElement as HTMLElement | null)?.blur();
      await user.keyboard("{Enter}"); // Preview too
      await user.click(screen.getByRole("button", { name: "File it" }));
      await new Promise((r) => setTimeout(r, 20));
      expect(calls.filter((c) => c.method === "POST")).toHaveLength(0);

      await user.type(screen.getByLabelText("Also add to collection"), "{Enter}");
      await user.click(screen.getByRole("button", { name: "File it" }));
      await waitFor(() => expect(posts(calls, "/api/inbox/file")).toHaveLength(1));
      const body = posts(calls, "/api/inbox/file")[0].body as { requests: { collections?: string[] }[] };
      expect(body.requests[0].collections).toEqual(["Kitchen"]);
    });

    it("the batch never files while a collection name is pending", async () => {
      const { calls, user } = await trays({ "POST /api/inbox/preview": { body: SIMPLE_MOVE } });
      await user.click(screen.getByRole("checkbox", { name: "Select scan001.pdf" }));
      await user.click(screen.getByRole("checkbox", { name: "Select scan002.pdf" }));
      await setFolder(user, "10. Financial/Banks");
      await user.type(screen.getByLabelText("Also add to collection"), "Kitchen");
      await user.keyboard("{Meta>}{Enter}{/Meta}");
      expect(await screen.findByRole("alert")).toHaveTextContent(
        "Press Enter to add ‘Kitchen’ or clear it",
      );
      await user.click(screen.getByRole("button", { name: "File 2 files" }));
      await new Promise((r) => setTimeout(r, 20));
      expect(calls.filter((c) => c.method === "POST")).toHaveLength(0);
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });

    it("an amount the server refuses shows on the card and files nothing", async () => {
      const { calls, user } = await trays({
        "POST /api/inbox/preview": { status: 400, body: { error: "amount: expected an amount" } },
        "POST /api/inbox/file": { body: fileResult() },
      });
      await user.click(screen.getByRole("button", { name: "To pay" }));
      await user.clear(field(/^Amount/));
      await user.type(field(/^Amount/), "abc");
      await user.click(screen.getByRole("button", { name: "File it" }));
      expect(await screen.findByRole("alert")).toHaveTextContent("amount: expected an amount");
      expect((posts(calls, "/api/inbox/preview")[0].body as { tray_fields: object }[])[0].tray_fields).toMatchObject({
        amount: "abc",
      });
      expect(posts(calls, "/api/inbox/file")).toHaveLength(0);
    });

    it("the plan shows blank fields: required ones flagged, cleared scan values", async () => {
      const { user } = await trays({ "POST /api/inbox/preview": { body: SIMPLE_MOVE } });
      await user.click(screen.getByRole("button", { name: "To pay" }));
      fireEvent.change(field(/^Due date/), { target: { value: "" } });
      fireEvent.change(field(/^Reference/), { target: { value: "" } });
      await user.click(screen.getByRole("button", { name: "Preview" }));
      const plan = await screen.findByRole("region", { name: "Planned changes" });
      expect(
        within(plan).getByText(
          "Put in To pay: due date: none (will be flagged), amount 84,20 €, reference: cleared, urgent no",
        ),
      ).toBeInTheDocument();
    });

    it("hints when the collections cannot be loaded", async () => {
      await trays({ "GET /api/collections": { status: 500, body: { error: "x" } } });
      expect(await screen.findByText(/Collections could not be loaded/)).toBeInTheDocument();
    });

    it("matches collection names the way the server folds them", async () => {
      const { user } = await trays();
      const picker = screen.getByLabelText("Also add to collection");
      await user.type(picker, "STRASSE");
      expect(screen.queryByRole("option", { name: /Create/ })).not.toBeInTheDocument();
      await user.keyboard("{Enter}");
      expect(removers(/^Remove /).filter((n) => n.includes("Straße"))).toEqual(["Remove Straße"]);
    });

    it("a batch follow-up error names the files it may concern", async () => {
      const { user } = await trays({
        "POST /api/inbox/preview": { body: SIMPLE_MOVE },
        "POST /api/inbox/file": { body: fileResult({ follow_up_error: "OperationalError: locked" }) },
      });
      await user.click(screen.getByRole("checkbox", { name: "Select scan001.pdf" }));
      await user.click(screen.getByRole("checkbox", { name: "Select scan002.pdf" }));
      await setFolder(user, "10. Financial/Banks");
      await user.click(screen.getByRole("button", { name: "File 2 files" }));
      await user.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "File" }));
      expect(
        await screen.findByText(
          "Filed, but adding to tray/collection failed for one or more of: 2026-10-01 Kotihoito lasku.pdf, 2026-10-02 Sähkölasku.pdf: OperationalError: locked",
        ),
      ).toBeInTheDocument();
    });

    it("counts note characters near the limit and stops at 10 000", async () => {
      await trays();
      const note = screen.getByLabelText("Note (optional)");
      expect(note).toHaveAttribute("maxLength", "10000");
      expect(screen.queryByText(/\/ 10 000/)).not.toBeInTheDocument();
      fireEvent.change(note, { target: { value: "a".repeat(9500) } });
      expect(screen.getByText("9 500 / 10 000")).toBeInTheDocument();
    });

    it("the batch shares tray and collections; each file is prefilled server-side", async () => {
      const { calls, user } = await trays({
        "POST /api/inbox/preview": { body: SIMPLE_MOVE },
        "POST /api/inbox/file": { body: fileResult({ items: [7, 8] }) },
      });
      await user.click(screen.getByRole("checkbox", { name: "Select scan001.pdf" }));
      await user.click(screen.getByRole("checkbox", { name: "Select scan002.pdf" }));
      expect(pressed("Nothing (just file)")).toBeInTheDocument();
      await user.keyboard("1");
      expect(pressed("To pay")).toBeInTheDocument();
      expect(screen.queryByLabelText(/^Due date/)).not.toBeInTheDocument();
      expect(screen.queryByLabelText("Note (optional)")).not.toBeInTheDocument();
      await user.type(screen.getByLabelText("Also add to collection"), "Legal{Enter}");
      await setFolder(user, "10. Financial/Banks");
      await user.click(screen.getByRole("button", { name: "File 2 files" }));
      const dialog = await screen.findByRole("dialog");
      expect(within(dialog).getByText("Put in To pay")).toBeInTheDocument();
      await user.click(within(dialog).getByRole("button", { name: "File" }));
      await waitFor(() => expect(posts(calls, "/api/inbox/file")).toHaveLength(1));
      const shared = {
        folder: "10. Financial/Banks",
        tags: [],
        tray: "to-pay",
        tray_fields: {},
        collections: ["Legal"],
      };
      expect(posts(calls, "/api/inbox/file")[0].body).toEqual({
        dry_run: false,
        via: "batch",
        requests: [
          { drive_id: "d1", name: "2026-10-01 Kotihoito lasku.pdf", ...shared },
          { drive_id: "d2", name: "2026-10-02 Sähkölasku.pdf", ...shared },
        ],
      });
    });
  });

  describe("inbox fixes", () => {
    it("the missing-folder error goes away as soon as a folder is chosen, then files", async () => {
      const { calls, user } = await setup({
        "GET /api/inbox": { body: [entry("d1", "scan001.pdf", "2026-10-01 Kotihoito lasku.pdf", null)] },
        "POST /api/inbox/preview": { body: SIMPLE_MOVE },
        "POST /api/inbox/file": { body: fileResult() },
      });
      await user.click(screen.getByRole("button", { name: "File it" }));
      expect(await screen.findByRole("alert")).toHaveTextContent("Choose a folder.");
      await setFolder(user, "10. Financial/Banks");
      expect(screen.queryByText("Choose a folder.")).not.toBeInTheDocument();
      await user.click(screen.getByRole("button", { name: "File it" }));
      await waitFor(() => expect(posts(calls, "/api/inbox/file")).toHaveLength(1));
    });

    it("a batch can be added to a collection without a folder; the files stay in the inbox", async () => {
      const change = {
        collection: collection(1, "Legal"),
        batch: null,
        problems: [],
        ongoing_status: null,
      };
      const { calls, user } = await setup({ "POST /api/collections/1/members": { body: change } });
      await user.click(screen.getByRole("checkbox", { name: "Select scan001.pdf" }));
      await user.click(screen.getByRole("checkbox", { name: "Select scan002.pdf" }));
      await user.clear(screen.getByLabelText("Folder"));
      const addOnly = screen.getByRole("button", { name: "Add to collection only" });
      expect(addOnly).toBeDisabled();
      await user.type(screen.getByLabelText("Also add to collection"), "Legal{Enter}");
      await user.click(addOnly);
      await waitFor(() => expect(posts(calls, "/api/collections/1/members")).toHaveLength(1));
      expect(posts(calls, "/api/collections/1/members")[0].body).toEqual({ drive_ids: ["d1", "d2"] });
      expect(posts(calls, "/api/inbox/file")).toHaveLength(0);
      expect(posts(calls, "/api/collections")).toHaveLength(0); // existing: not created again
      await waitFor(() =>
        expect(screen.getByRole("checkbox", { name: "Select scan001.pdf" })).not.toBeChecked(),
      );
      expect(screen.getByRole("checkbox", { name: "Select scan002.pdf" })).not.toBeChecked();
    });
  });
  describe("three columns and multi-select", () => {
    const THREE = [...ENTRIES, entry("d3", "scan003.pdf", "2026-10-03 Vesilasku.pdf", "30. Home/Water")];
    const row = (suggested: RegExp) => screen.getByRole("button", { name: suggested });

    it("the batch sets From and For for every selected file", async () => {
      const { calls, user } = await setup({
        "GET /api/inbox": { body: THREE },
        "GET /api/senders": { body: [] },
        "GET /api/settings/people": { body: { people: [{ name: "Tiina", match: [] }], address_zone: [0, 0, 1, 1], default_address_zone: [0, 0, 1, 1] } },
        "PUT /api/assignments": { body: [] },
      });
      await user.keyboard("{Meta>}");
      await user.click(row(/Sähkölasku/));
      await user.keyboard("{/Meta}");
      await user.click(screen.getByRole("button", { name: "For…" }));
      const sheet = await screen.findByRole("dialog", { name: "For (2 documents)" });
      await user.click(await within(sheet).findByRole("button", { name: "Tiina" }));
      await user.click(within(sheet).getByRole("button", { name: "Save" }));
      await waitFor(() => expect(calls.filter((c) => c.method === "PUT")).toHaveLength(1));
      expect(calls.find((c) => c.method === "PUT")?.body).toEqual({ drive_ids: ["d1", "d2"], person: "Tiina" });
      expect(screen.getByRole("button", { name: "From…" })).toBeInTheDocument();
    });

    it("the card shows who a file is from and for, with the Draw a box tool", async () => {
      await setup();
      expect(screen.getByRole("button", { name: "From Who sent it?" })).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "For Who is it for?" })).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Draw a box" })).toBeInTheDocument();
    });

    it("⌘-click selects two entries and shows the batch form; a plain click goes back to one", async () => {
      const { user } = await setup({ "GET /api/inbox": { body: THREE } });
      await user.keyboard("{Meta>}");
      await user.click(row(/Sähkölasku/));
      await user.keyboard("{/Meta}");
      expect(screen.getByRole("button", { name: "File 2 files" })).toBeInTheDocument();
      expect(screen.getByRole("checkbox", { name: "Select scan001.pdf" })).toBeChecked();
      expect(screen.getByRole("checkbox", { name: "Select scan002.pdf" })).toBeChecked();
      expect(screen.getByRole("checkbox", { name: "Select scan003.pdf" })).not.toBeChecked();
      // ⌘-click again takes one out: the one left is shown on its own, as in Mail.
      await user.keyboard("{Meta>}");
      await user.click(row(/Sähkölasku/));
      await user.keyboard("{/Meta}");
      expect(screen.queryByRole("button", { name: /^File \d+ files?$/ })).not.toBeInTheDocument();
      expect(screen.getByLabelText("Name")).toHaveValue("2026-10-01 Kotihoito lasku.pdf");
      expect(screen.getByRole("checkbox", { name: "Select scan002.pdf" })).not.toBeChecked();
      await user.click(screen.getByRole("checkbox", { name: "Select scan002.pdf" }));
      await user.click(screen.getByRole("checkbox", { name: "Select scan003.pdf" }));
      expect(screen.getByRole("button", { name: "File 2 files" })).toBeInTheDocument();
      await user.click(row(/Vesilasku/));
      expect(screen.queryByRole("button", { name: /^File \d+ files?$/ })).not.toBeInTheDocument();
      expect(screen.getByLabelText("Name")).toHaveValue("2026-10-03 Vesilasku.pdf");
      expect(screen.getByRole("checkbox", { name: "Select scan001.pdf" })).not.toBeChecked();
    });

    it("⇧-click selects the range from the current entry", async () => {
      const { user } = await setup({ "GET /api/inbox": { body: THREE } });
      await user.keyboard("{Shift>}");
      await user.click(row(/Vesilasku/));
      await user.keyboard("{/Shift}");
      expect(screen.getByRole("button", { name: "File 3 files" })).toBeInTheDocument();
      for (const n of ["scan001.pdf", "scan002.pdf", "scan003.pdf"]) {
        expect(screen.getByRole("checkbox", { name: `Select ${n}` })).toBeChecked();
      }
    });

    it("⇧↓/⇧↑ grow and shrink the selection from where a plain move left off", async () => {
      const { user } = await setup({ "GET /api/inbox": { body: THREE } });
      const box = (n: string) => screen.getByRole("checkbox", { name: `Select ${n}` });
      await user.keyboard("{Shift>}{ArrowDown}{/Shift}");
      expect(screen.getByRole("button", { name: "File 2 files" })).toBeInTheDocument();
      await user.keyboard("{Shift>}J{/Shift}");
      expect(screen.getByRole("button", { name: "File 3 files" })).toBeInTheDocument();
      await user.keyboard("{Shift>}{ArrowUp}{ArrowUp}{/Shift}");
      expect(screen.queryByRole("button", { name: /^File \d+ files?$/ })).not.toBeInTheDocument();
      expect(box("scan001.pdf")).not.toBeChecked();
      // A plain move puts the anchor where it lands.
      await user.keyboard("{ArrowDown}{Shift>}{ArrowDown}{/Shift}");
      expect(box("scan001.pdf")).not.toBeChecked();
      expect(box("scan002.pdf")).toBeChecked();
      expect(box("scan003.pdf")).toBeChecked();
    });

    it("the tray choices show their 1–9 key", async () => {
      await setup();
      const group = await screen.findByRole("group", { name: "Then put it in" });
      const keys = [...group.querySelectorAll("kbd")].map((k) => k.textContent);
      expect(keys[0]).toBe("1");
      expect(keys.at(-1)).toBe("0");
    });

    it("the list rows show the suggested name, the file name and the scanned due date and amount", async () => {
      const bill = { ...ENTRIES[0], prefill: { due_date: "2099-10-15", total: "84.20" } };
      await setup({ "GET /api/inbox": { body: [bill, ENTRIES[1]] } });
      const first = row(/Kotihoito/);
      expect(first).toHaveTextContent("Kotihoito lasku");
      expect(first).toHaveTextContent("scan001.pdf");
      expect(first).toHaveTextContent(/Due .* · 84,20 €/);
      expect(row(/Sähkölasku/)).not.toHaveTextContent(/Due|Overdue/);
    });

    it("shows hidden characters in the scanned chip", async () => {
      const odd = { ...ENTRIES[0], prefill: { total: "8\u202E4" } };
      await setup({ "GET /api/inbox": { body: [odd] } });
      expect(row(/Kotihoito/)).toHaveTextContent("8⟨U+202E⟩4");
    });

    it("↑/↓ move through the list, but not from the inspector or the preview", async () => {
      const { user } = await setup({ "GET /api/inbox": { body: THREE } });
      await user.keyboard("{ArrowDown}");
      expect(screen.getByLabelText("Name")).toHaveValue("2026-10-02 Sähkölasku.pdf");
      for (const pane of [".inspector", ".preview-pane"]) {
        const el = document.querySelector(pane) as HTMLElement;
        el.tabIndex = -1;
        el.focus();
        await user.keyboard("{ArrowDown}");
        expect(screen.getByLabelText("Name")).toHaveValue("2026-10-02 Sähkölasku.pdf");
      }
      (document.activeElement as HTMLElement).blur();
      await user.keyboard("{ArrowUp}");
      expect(screen.getByLabelText("Name")).toHaveValue("2026-10-01 Kotihoito lasku.pdf");
    });
  });

  describe("a tray the file is already in", () => {
    const ITEM = {
      id: 7,
      tray_id: "to-pay",
      title: "Kotihoito",
      fields: {},
      date: null,
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

    it("shows a link to the item and sends no tray follow-up", async () => {
      const already = { ...ENTRIES[0], open_trays: ["to-pay"] };
      const calls = api({
        "GET /api/inbox": { body: [already, ENTRIES[1]] },
        "GET /api/files/d1/links": { body: { items: [ITEM], collections: [], note: "" } },
        "POST /api/inbox/preview": { body: SIMPLE_MOVE },
        "POST /api/inbox/file": { body: fileResult() },
      });
      const user = userEvent.setup();
      renderWithProviders(
        <MemoryRouter>
          <Inbox />
        </MemoryRouter>,
      );
      await user.click(await screen.findByRole("button", { name: "To pay" }));
      const link = await screen.findByRole("link", { name: "open it to change it" });
      expect(link.closest("p")).toHaveTextContent("Already in To pay — open it to change it");
      expect(link).toHaveAttribute("href", "/trays/to-pay?item=7");
      expect(screen.queryByLabelText(/^Due date/)).not.toBeInTheDocument();
      await user.click(screen.getByRole("button", { name: "File it" }));
      await waitFor(() => expect(posts(calls, "/api/inbox/file")).toHaveLength(1));
      const [request] = (posts(calls, "/api/inbox/file")[0].body as { requests: Record<string, unknown>[] }).requests;
      expect(request).not.toHaveProperty("tray");
      expect(request).not.toHaveProperty("tray_fields");
    });

    it("links to the tray while the item is not known yet", async () => {
      const already = { ...ENTRIES[0], open_trays: ["to-pay"] };
      api({ "GET /api/inbox": { body: [already] } });
      const user = userEvent.setup();
      renderWithProviders(
        <MemoryRouter>
          <Inbox />
        </MemoryRouter>,
      );
      await user.click(await screen.findByRole("button", { name: "To pay" }));
      expect(screen.getByRole("link", { name: "open it to change it" })).toHaveAttribute("href", "/trays/to-pay");
    });

    it("a batch sends the tray only for the files not in it yet", async () => {
      const already = { ...ENTRIES[0], open_trays: ["to-pay"] };
      const calls = api({
        "GET /api/inbox": { body: [already, ENTRIES[1]] },
        "POST /api/inbox/preview": { body: SIMPLE_MOVE },
        "POST /api/inbox/file": { body: fileResult() },
      });
      const user = userEvent.setup();
      renderWithProviders(
        <MemoryRouter>
          <Inbox />
        </MemoryRouter>,
      );
      await user.click(await screen.findByRole("checkbox", { name: "Select scan001.pdf" }));
      await user.click(screen.getByRole("checkbox", { name: "Select scan002.pdf" }));
      await user.click(screen.getByRole("button", { name: "To pay" }));
      expect(screen.getByText("1 file is already in To pay: no new item for it.")).toBeInTheDocument();
      await setFolder(user, "10. Financial/Banks");
      await user.click(screen.getByRole("button", { name: "File 2 files" }));
      const dialog = await screen.findByRole("dialog");
      expect(within(dialog).getByText("Put in To pay (1 of 2; 1 already in it)")).toBeInTheDocument();
      await user.click(within(dialog).getByRole("button", { name: "File" }));
      await waitFor(() => expect(posts(calls, "/api/inbox/file")).toHaveLength(1));
      const { requests } = posts(calls, "/api/inbox/file")[0].body as { requests: Record<string, unknown>[] };
      expect(requests[0]).not.toHaveProperty("tray");
      expect(requests[1]).toMatchObject({ tray: "to-pay", tray_fields: {} });
    });
  });
});

describe("Dragging inbox rows", () => {
  const rowOf = (name: string) => screen.getByRole("checkbox", { name: `Select ${name}` }).closest("li")!;
  const dragged = (li: HTMLElement) => {
    const dt = dataTransfer();
    fireEvent.dragStart(li, { dataTransfer: dt });
    document.dispatchEvent(new Event("dragend"));
    return JSON.parse(dt.data["application/x-dam-files"]).ids;
  };

  it("a row drags its file; a row in the selection drags all selected files", async () => {
    const { user } = await setup();
    const first = rowOf("scan001.pdf");
    expect(first).toHaveAttribute("draggable", "true");
    expect(dragged(first)).toEqual(["d1"]);
    await user.click(screen.getByRole("checkbox", { name: "Select scan001.pdf" }));
    await user.click(screen.getByRole("checkbox", { name: "Select scan002.pdf" }));
    expect(dragged(rowOf("scan002.pdf"))).toEqual(["d1", "d2"]);
  });
});

describe("Detected fields", () => {
  const FIELDS = ENTRIES[0].fields;
  const puts = (calls: Call[]) => calls.filter((c) => c.method === "PUT" && c.url === "/api/files/d1/fields");
  const saved = (fields: unknown) => ({ "PUT /api/files/d1/fields": { body: { fields, edited: true } } });
  const section = () => screen.getByRole("region", { name: "Detected fields" });

  it("× removes a field and saves the rest of the list", async () => {
    const { calls, user } = await setup(saved([]));
    await user.click(within(section()).getByRole("button", { name: "Remove Amount 123,45 €" }));
    await waitFor(() => expect(puts(calls)).toHaveLength(1));
    expect(puts(calls)[0].body).toEqual({ fields: FIELDS.filter((f) => f.kind !== "amount") });
  });

  it("the pencil edits a value in place: Enter saves, Escape cancels", async () => {
    const { calls, user } = await setup(saved([]));
    await user.click(within(section()).getByRole("button", { name: "Edit Amount" }));
    const input = within(section()).getByLabelText("Value of Amount");
    expect(input).toHaveAttribute("inputmode", "decimal");
    await user.clear(input);
    await user.type(input, "99,5{Escape}");
    expect(within(section()).queryByLabelText("Value of Amount")).not.toBeInTheDocument();
    expect(puts(calls)).toHaveLength(0);
    // Escape in the field leaves the inbox's own Escape alone: the name is still there
    expect(screen.getByLabelText("Name")).toBeInTheDocument();

    await user.click(within(section()).getByRole("button", { name: "Edit Amount" }));
    await user.clear(within(section()).getByLabelText("Value of Amount"));
    await user.type(within(section()).getByLabelText("Value of Amount"), "99,5{Enter}");
    await waitFor(() => expect(puts(calls)).toHaveLength(1));
    expect(puts(calls)[0].body).toEqual({
      fields: FIELDS.map((f) => (f.kind === "amount" ? { ...f, value: "99,5" } : f)),
    });
    await waitFor(() => expect(within(section()).queryByLabelText("Value of Amount")).not.toBeInTheDocument());
  });

  it("typing in a field does not fire the inbox shortcuts", async () => {
    const { user } = await setup({ "GET /api/inbox": { body: [ENTRIES[0], ENTRIES[1]] } });
    await user.click(within(section()).getByRole("button", { name: "Edit Amount" }));
    await user.type(within(section()).getByLabelText("Value of Amount"), "jk");
    expect(screen.getByLabelText("Name")).toHaveValue("2026-10-01 Kotihoito lasku.pdf");
  });

  it("Add field saves a new field; single-valued kinds already there are disabled", async () => {
    const { calls, user } = await setup(saved([]));
    await user.click(within(section()).getByRole("button", { name: "Add field" }));
    const kind = within(section()).getByLabelText("Kind");
    expect(within(section()).getByRole("option", { name: "Document date" })).toBeDisabled();
    expect(within(section()).getByRole("option", { name: "Due date" })).toBeEnabled();
    await user.selectOptions(kind, "Other…");
    await user.type(within(section()).getByLabelText("Label"), "Customer no");
    await user.type(within(section()).getByLabelText("Value of new field"), "12345");
    await user.click(within(section()).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(puts(calls)).toHaveLength(1));
    expect(puts(calls)[0].body).toEqual({
      fields: [...FIELDS, { kind: "custom", label: "Customer no", value: "12345" }],
    });
  });

  it("Add field offers a date input for the date kinds", async () => {
    const { calls, user } = await setup(saved([]));
    await user.click(within(section()).getByRole("button", { name: "Add field" }));
    await user.selectOptions(within(section()).getByLabelText("Kind"), "Due date");
    const input = within(section()).getByLabelText("Value of new field");
    expect(input).toHaveAttribute("type", "date");
    fireEvent.change(input, { target: { value: "2026-11-15" } });
    await user.keyboard("{Enter}");
    await waitFor(() => expect(puts(calls)).toHaveLength(1));
    expect(puts(calls)[0].body).toEqual({
      fields: [...FIELDS, { kind: "due_date", label: null, value: "2026-11-15" }],
    });
  });

  it("Reset to detected shows only for an edited list and deletes it", async () => {
    const edited = { ...ENTRIES[0], fields_edited: true };
    const { calls, user } = await setup({
      "GET /api/inbox": { body: [edited, ENTRIES[1]] },
      "DELETE /api/files/d1/fields": { body: { fields: FIELDS, edited: false } },
    });
    await user.click(within(section()).getByRole("button", { name: "Reset to detected" }));
    await waitFor(() => expect(calls.filter((c) => c.method === "DELETE")).toHaveLength(1));
  });

  it("has no Reset button until the list was edited", async () => {
    await setup();
    expect(within(section()).queryByRole("button", { name: "Reset to detected" })).not.toBeInTheDocument();
  });

  it("shows the server's message when saving fails", async () => {
    const { user } = await setup({
      "PUT /api/files/d1/fields": { status: 400, body: { error: "amount: expected an amount" } },
    });
    await user.click(within(section()).getByRole("button", { name: "Edit Amount" }));
    await user.type(within(section()).getByLabelText("Value of Amount"), "x{Enter}");
    expect(await within(section()).findByRole("alert")).toHaveTextContent("amount: expected an amount");
    // the editor stays open for another try
    expect(within(section()).getByLabelText("Value of Amount")).toBeInTheDocument();
  });
});

describe("Suggestion chips (rules and scan)", () => {
  const chip = (label: RegExp) => screen.getByRole("group", { name: label });
  const noChips = () => expect(screen.queryByRole("group", { name: /^Suggested/ })).not.toBeInTheDocument();

  it("empty inbox fields are pre-filled, so a file with its suggestion shows no chips", async () => {
    await setup();
    noChips();
    expect(screen.queryByRole("button", { name: "Use all" })).not.toBeInTheDocument();
  });

  it("a chip of a rule that was corrected recently says so in its tip", async () => {
    const flagged = (flag: boolean) => ({
      rules: [{ id: "kotihoito", file: "learned.toml", learned: true, when: { text_contains: ["x"], filename_matches: null, folder_is: null, zones: [], person: null }, then: { folder: null, name: null, tags: [], tray: null, payee: null }, stats: { suggested: 5, changed: 2, last_used: null, flagged: flag } }],
      errors: [],
      state: { offer: true, declined: 0 },
    });
    const { user, name } = await setup({ "GET /api/rules": { body: flagged(true) } });
    await user.clear(name);
    await user.type(name, "mine.pdf");
    const nameChip = chip(/^Suggested Name: 2026-10-01 Kotihoito lasku\.pdf \(rule kotihoito\)$/);
    await waitFor(() => expect(within(nameChip).getByText("rule kotihoito")).toHaveAttribute("title", "rule kotihoito: this rule was corrected recently"));
  });

  it("a chip of a rule that was not flagged has no note", async () => {
    const { user, name } = await setup({
      "GET /api/rules": { body: { rules: [], errors: [], state: { offer: true, declined: 0 } } },
    });
    await user.clear(name);
    await user.type(name, "mine.pdf");
    const nameChip = chip(/^Suggested Name: 2026-10-01 Kotihoito lasku\.pdf \(rule kotihoito\)$/);
    expect(within(nameChip).getByText("rule kotihoito")).toHaveAttribute("title", "rule kotihoito");
  });

  it("a field edited away from the rule's value gets a chip; Use changes only that field", async () => {
    const { user, name } = await setup();
    await user.clear(name);
    await user.type(name, "mine.pdf");
    await setFolder(user, "10. Financial/Banks");
    await clearTags(user);
    const nameChip = chip(/^Suggested Name: 2026-10-01 Kotihoito lasku\.pdf \(rule kotihoito\)$/);
    expect(nameChip).toHaveTextContent("rule kotihoito");
    expect(chip(/^Suggested Folder: 20\. Health\/Kotihoito \(rule kotihoito\)$/)).toBeInTheDocument();
    expect(chip(/^Suggested tag: invoice \(rule kotihoito\)$/)).toBeInTheDocument();

    await user.click(within(nameChip).getByRole("button", { name: "Use" }));
    expect(name).toHaveValue("2026-10-01 Kotihoito lasku.pdf");
    expect(screen.getByLabelText("Folder")).toHaveValue("10. Financial/Banks");
    expect(tagList()).toEqual([]);
    expect(screen.queryByRole("group", { name: /^Suggested Name/ })).not.toBeInTheDocument();
  });

  it("Use all applies every chip, and the preview sends exactly the form", async () => {
    const { calls, user, name } = await setup({ "POST /api/inbox/preview": { body: SIMPLE_MOVE } });
    await user.clear(name);
    await user.type(name, "mine.pdf");
    await setFolder(user, "10. Financial/Banks");
    await clearTags(user);
    await user.type(screen.getByLabelText("Tags"), "own");
    await user.click(screen.getByRole("button", { name: "Use all" }));
    noChips();
    expect(name).toHaveValue("2026-10-01 Kotihoito lasku.pdf");
    expect(screen.getByLabelText("Folder")).toHaveValue("20. Health/Kotihoito");
    expect(tagList()).toEqual(["own", "invoice"]);
    await user.click(screen.getByRole("button", { name: "Preview" }));
    await waitFor(() => expect(posts(calls, "/api/inbox/preview")).toHaveLength(1));
    expect(posts(calls, "/api/inbox/preview")[0].body).toEqual([
      { drive_id: "d1", name: "2026-10-01 Kotihoito lasku.pdf", folder: "20. Health/Kotihoito", tags: ["own", "invoice"] },
    ]);
  });

  it("the batch card offers each file's folder and every tag as chips", async () => {
    const two = [ENTRIES[0], { ...ENTRIES[1], suggestion: { ...ENTRIES[1].suggestion, tags: ["power"], tag_sources: { power: "scan" } } }];
    const { calls, user } = await setup({
      "GET /api/inbox": { body: two },
      "POST /api/inbox/preview": { body: SIMPLE_MOVE },
    });
    await user.click(screen.getByRole("checkbox", { name: "Select scan001.pdf" }));
    await user.click(screen.getByRole("checkbox", { name: "Select scan002.pdf" }));
    expect(screen.getByLabelText("Folder")).toHaveValue("");
    expect(chip(/^Suggested Folder: 20\. Health\/Kotihoito/)).toBeInTheDocument();
    const electricity = chip(/^Suggested Folder: 30\. Home\/Electricity/);
    expect(chip(/^Suggested tag: invoice \(rule kotihoito\)$/)).toBeInTheDocument();
    const power = chip(/^Suggested tag: power \(scan\)$/);
    // the files suggest different folders: Use all leaves the folder, and says so
    expect(screen.getByText("The files suggest different folders: pick one. Use all leaves the folder as it is.")).toBeInTheDocument();
    expect(screen.getByText("2 suggestions below the fields")).toBeInTheDocument();

    await user.click(within(power).getByRole("button", { name: "Use" }));
    expect(tagList()).toEqual(["power"]);
    expect(screen.getByLabelText("Folder")).toHaveValue(""); // only that field
    await user.click(within(electricity).getByRole("button", { name: "Use" }));
    expect(screen.getByLabelText("Folder")).toHaveValue("30. Home/Electricity");
    await user.click(screen.getByRole("button", { name: "Use all" }));
    expect(screen.getByLabelText("Folder")).toHaveValue("20. Health/Kotihoito");
    expect(tagList()).toEqual(["power", "invoice"]);

    await user.click(screen.getByRole("button", { name: "Preview" }));
    await waitFor(() => expect(posts(calls, "/api/inbox/preview")).toHaveLength(1));
    const tags = ["power", "invoice"];
    expect(posts(calls, "/api/inbox/preview")[0].body).toEqual([
      { drive_id: "d1", name: "2026-10-01 Kotihoito lasku.pdf", folder: "20. Health/Kotihoito", tags },
      { drive_id: "d2", name: "2026-10-02 Sähkölasku.pdf", folder: "20. Health/Kotihoito", tags },
    ]);
  });
});

describe("Tags field and action tooltips", () => {
  const TAGS = [
    { name: "bank", files: 9 },
    { name: "bills", files: 4 },
  ];

  it("tags are chips; suggestions come from the existing tags; Enter adds, backspace removes", async () => {
    const { calls, user } = await setup({ "GET /api/tags": { body: TAGS } });
    expect(screen.queryByPlaceholderText("comma, separated")).not.toBeInTheDocument();
    const box = screen.getByLabelText("Tags");
    await user.type(box, "b");
    const list = await screen.findByRole("listbox", { name: "Existing tags" });
    expect(calls.some((c) => c.url.startsWith("/api/tags") && c.url.includes("prefix=b"))).toBe(true);
    await user.click(within(list).getByRole("option", { name: /^bills/ }));
    expect(tagList()).toEqual(["invoice", "bills"]);
    await user.type(box, "2026{Enter}");
    expect(tagList()).toEqual(["invoice", "bills", "2026"]);
    await user.keyboard("{Backspace}");
    expect(tagList()).toEqual(["invoice", "bills"]);
  });

  it("⌘↩ in the tags field files with the text being typed", async () => {
    const { calls, user } = await setup({ "POST /api/inbox/preview": { body: SIMPLE_MOVE }, "POST /api/inbox/file": { body: fileResult() } });
    await setFolder(user, "10. Financial/Banks");
    await user.type(screen.getByLabelText("Tags"), "2026");
    await user.keyboard("{Meta>}{Enter}{/Meta}");
    await waitFor(() => expect(posts(calls, "/api/inbox/preview").length + posts(calls, "/api/inbox/file").length).toBeGreaterThan(0));
    const sent = [...posts(calls, "/api/inbox/preview"), ...posts(calls, "/api/inbox/file")][0].body as { requests?: { tags: string[] }[] };
    const request = Array.isArray(sent) ? sent[0] : sent.requests![0];
    expect(request.tags).toEqual(["invoice", "2026"]);
  });

  it("Preview and File it say what they do", async () => {
    await setup();
    expect(screen.getByRole("button", { name: "Preview" })).toHaveAttribute("data-tip", expect.stringContaining("before anything changes"));
    expect(screen.getByRole("button", { name: "File it" })).toHaveAttribute("data-tip", expect.stringContaining("⌘↩"));
  });

  it("the batch card has the same tags field and tooltips", async () => {
    const { user } = await setup();
    await user.click(screen.getByRole("checkbox", { name: "Select scan001.pdf" }));
    await user.click(screen.getByRole("checkbox", { name: "Select scan002.pdf" }));
    await user.type(screen.getByLabelText("Tags"), "2026{Enter}");
    expect(tagList()).toEqual(["2026"]);
    expect(screen.getByRole("button", { name: "File 2 files" })).toHaveAttribute("data-tip", expect.stringContaining("⌘↩"));
    expect(screen.getByRole("button", { name: "Preview" })).toHaveAttribute("data-tip", expect.stringContaining("before anything changes"));
  });
});

describe("Trash in the inbox", () => {
  const PATHS = { d1: "##. Organize/scan001.pdf", d2: "##. Organize/scan002.pdf" };
  const trashRoutes = (extra: Parameters<typeof api>[0] = {}) => ({ "POST /api/quarantine": quarantineRoute(PATHS), ...extra });
  const quarantines = (calls: Call[]) => posts(calls, "/api/quarantine").map((c) => c.body);

  it("the review card's bin moves the file to ##. To Delete and moves on to the next entry; Undo restores", async () => {
    const { calls, user } = await setup(
      trashRoutes({
        "POST /api/activity/q1/undo/preview": {
          body: [{ kind: "move", src: `##. To Delete/${PATHS.d1}`, dst: PATHS.d1, drive_id: "d1", note: null }],
        },
        "POST /api/activity/q1/undo": { body: { batch_id: "u1", dry_run: false, done: [], failed: null, error: null, index_error: null } },
      }),
    );
    const card = screen.getByRole("article", { name: "Review scan001.pdf" });
    await user.click(within(card).getByRole("button", { name: "Move to To Delete" }));
    const dialog = await screen.findByRole("dialog", { name: "Move to To Delete?" });
    expect(dialog).toHaveTextContent(`${PATHS.d1} → ##. To Delete/${PATHS.d1}`);
    await user.click(within(dialog).getByRole("button", { name: "Move to To Delete" }));
    await waitFor(() => expect(screen.getByLabelText("Name")).toHaveValue("2026-10-02 Sähkölasku.pdf"));
    expect(quarantines(calls)).toEqual([
      { drive_ids: ["d1"], dry_run: true },
      { drive_ids: ["d1"], dry_run: false },
    ]);
    expect(posts(calls, "/api/inbox/file")).toHaveLength(0);
    await user.click(await screen.findByRole("button", { name: "Undo" }));
    await user.click(await undoButton(await screen.findByRole("dialog", { name: "Undo these changes?" })));
    await waitFor(() => expect(posts(calls, "/api/activity/q1/undo")).toHaveLength(1));
  });

  it("⌘⌫ on the list trashes the current entry; a plain ⌫ does not; ⌘⌫ while typing in the card does nothing", async () => {
    const { calls, user, name } = await setup(trashRoutes());
    await user.click(name);
    await user.keyboard("{Meta>}{Backspace}{/Meta}");
    expect(quarantines(calls)).toHaveLength(0);
    await user.click(screen.getByRole("button", { name: /scan002\.pdf/ }));
    await user.keyboard("{Backspace}");
    await new Promise((r) => setTimeout(r, 10));
    expect(quarantines(calls)).toHaveLength(0);
    await user.keyboard("{Meta>}{Backspace}{/Meta}");
    await screen.findByRole("dialog", { name: "Move to To Delete?" });
    expect(quarantines(calls)).toEqual([{ drive_ids: ["d2"], dry_run: true }]);
  });

  it("the batch card's bin moves every selected file in one batch and unticks them", async () => {
    const { calls, user } = await setup(trashRoutes());
    await user.click(screen.getByRole("checkbox", { name: "Select scan001.pdf" }));
    await user.click(screen.getByRole("checkbox", { name: "Select scan002.pdf" }));
    const card = screen.getByRole("article", { name: "Batch of 2 files" });
    await user.click(within(card).getByRole("button", { name: "Move 2 to To Delete" }));
    await user.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Move to To Delete" }));
    await waitFor(() => expect(screen.getByRole("checkbox", { name: "Select scan001.pdf" })).not.toBeChecked());
    expect(screen.getByRole("checkbox", { name: "Select scan002.pdf" })).not.toBeChecked();
    expect(quarantines(calls)).toEqual([
      { drive_ids: ["d1", "d2"], dry_run: true },
      { drive_ids: ["d1", "d2"], dry_run: false },
    ]);
  });

  it("the batch card stars and marks Important every selected file in one request", async () => {
    const change = { body: { collection: null, problems: [], batch: null, ongoing_status: null } };
    const { calls, user } = await setup({ "POST /api/marks/star": change, "POST /api/marks/important": change });
    await user.click(screen.getByRole("checkbox", { name: "Select scan001.pdf" }));
    await user.click(screen.getByRole("checkbox", { name: "Select scan002.pdf" }));
    const card = screen.getByRole("article", { name: "Batch of 2 files" });
    await user.click(within(card).getByRole("button", { name: "Star" }));
    await user.click(within(card).getByRole("button", { name: "Mark Important" }));
    await waitFor(() => expect(calls.filter((c) => c.url.startsWith("/api/marks/"))).toHaveLength(2));
    expect(calls.filter((c) => c.url.startsWith("/api/marks/")).map((c) => [c.url, c.body])).toEqual([
      ["/api/marks/star", { drive_ids: ["d1", "d2"] }],
      ["/api/marks/important", { drive_ids: ["d1", "d2"] }],
    ]);
    expect(await screen.findByText("Starred 2 files")).toBeInTheDocument();
  });

  it("a file marked Important is refused with the server's reason; the entry stays", async () => {
    const { calls, user } = await setup({ "POST /api/quarantine": IMPORTANT_REFUSED(PATHS.d1) });
    await user.click(screen.getByRole("button", { name: "Move to To Delete" }));
    expect(await screen.findByText(/This file is marked Important; unmark it first/)).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Name")).toHaveValue("2026-10-01 Kotihoito lasku.pdf");
    expect(quarantines(calls)).toHaveLength(1);
  });

  it("Quick Look's bin trashes the file it shows: open through the dry run, gone as the confirm opens, Cancel focused", async () => {
    const held = deferred<{ body: unknown }>();
    const { calls, user } = await setup({
      "POST /api/quarantine": (call) => (quarantines(calls).length === 1 ? held.promise : quarantineRoute(PATHS)(call)),
    });
    (document.activeElement as HTMLElement | null)?.blur();
    await user.keyboard(" ");
    const ql = await screen.findByRole("dialog", { name: /^Quick Look/ });
    await user.keyboard("j"); // the second file
    await user.click(within(ql).getByRole("button", { name: "Move to To Delete" }));
    expect(screen.getByRole("dialog", { name: /^Quick Look/ })).toBeInTheDocument(); // the dry run runs
    await act(async () => held.resolve(quarantineRoute(PATHS)(posts(calls, "/api/quarantine")[0])));
    const dialog = await screen.findByRole("dialog", { name: "Move to To Delete?" });
    expect(screen.queryByRole("dialog", { name: /^Quick Look/ })).not.toBeInTheDocument();
    expect(dialog).toHaveTextContent(PATHS.d2);
    await waitFor(() => expect(document.activeElement).toBe(within(dialog).getByRole("button", { name: "Cancel" })));
    expect(quarantines(calls)).toEqual([{ drive_ids: ["d2"], dry_run: true }]);
  });

  it("⌘⌫ in Quick Look trashes the file it shows; a plain ⌫ there does not", async () => {
    const { calls, user } = await setup(trashRoutes());
    (document.activeElement as HTMLElement | null)?.blur();
    await user.keyboard(" ");
    await screen.findByRole("dialog", { name: /^Quick Look/ });
    await user.keyboard("{Backspace}");
    await new Promise((r) => setTimeout(r, 10));
    expect(quarantines(calls)).toHaveLength(0);
    await user.keyboard("{Meta>}{Backspace}{/Meta}");
    await screen.findByRole("dialog", { name: "Move to To Delete?" });
    expect(quarantines(calls)).toEqual([{ drive_ids: ["d1"], dry_run: true }]);
  });

  it("a refusal from Quick Look is said on its status line, and Quick Look stays", async () => {
    await setup({ "POST /api/quarantine": IMPORTANT_REFUSED(PATHS.d1) });
    const user = userEvent.setup();
    (document.activeElement as HTMLElement | null)?.blur();
    await user.keyboard(" ");
    const ql = await screen.findByRole("dialog", { name: /^Quick Look/ });
    await user.click(within(ql).getByRole("button", { name: "Move to To Delete" }));
    await waitFor(() =>
      expect(within(ql).getByRole("status")).toHaveTextContent(
        `Not moved to To Delete: This file is marked Important; unmark it first: ${PATHS.d1}`,
      ),
    );
    expect(screen.getByRole("dialog", { name: /^Quick Look/ })).toBeInTheDocument();
    expect(screen.queryByRole("dialog", { name: "Move to To Delete?" })).not.toBeInTheDocument();
  });

  describe("filing form fixes", () => {
    it("every filing-form input has an accessible name", async () => {
      await setup();
      expect(screen.getByRole("textbox", { name: "Name" })).toBeInTheDocument();
      expect(screen.getByRole("combobox", { name: "Folder" })).toBeInTheDocument();
      expect(screen.getByRole("combobox", { name: "Tags" })).toBeInTheDocument();
      expect(screen.getByRole("textbox", { name: "Note (optional)" })).toBeInTheDocument();
      expect(screen.getByRole("combobox", { name: "Also add to collection" })).toBeInTheDocument();
    });

    it("Enter in the folder field takes the first suggestion; the arrows move; Esc closes", async () => {
      const { user } = await setup();
      const folder = await setFolder(user, "30. Home");
      expect(screen.getByRole("option", { name: "30. Home/Electricity" })).toHaveAttribute("aria-selected", "true");
      expect(folder).toHaveAttribute("aria-activedescendant", screen.getByRole("option", { name: "30. Home/Electricity" }).id);
      await user.keyboard("{Enter}");
      expect(folder).toHaveValue("30. Home/Electricity");
      expect(screen.queryByRole("listbox")).not.toBeInTheDocument();

      await user.clear(folder);
      await user.type(folder, "0");
      const options = screen.getAllByRole("option");
      expect(options.length).toBeGreaterThan(1);
      await user.keyboard("{ArrowDown}");
      expect(options[1]).toHaveAttribute("aria-selected", "true");
      await user.keyboard("{ArrowUp}{ArrowUp}");
      expect(options[0]).toHaveAttribute("aria-selected", "true");
      await user.keyboard("{Escape}");
      expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
    });

    it("a missing folder is an error on the Folder field, which gets the focus (single)", async () => {
      const { user } = await setup({
        "GET /api/inbox": { body: [entry("d1", "scan001.pdf", "2026-10-01 Kotihoito lasku.pdf", null)] },
      });
      await user.click(screen.getByRole("button", { name: "File it" }));
      const folder = screen.getByRole("combobox", { name: "Folder" });
      expect(folder).toHaveAttribute("aria-invalid", "true");
      expect(folder).toHaveFocus();
      expect(folder).toHaveAccessibleDescription("Choose a folder.");
      await setFolder(user, "10. Financial/Banks");
      expect(folder).not.toHaveAttribute("aria-invalid");
    });

    it("a missing name is an error on the Name field, which gets the focus", async () => {
      const { user, name } = await setup();
      await user.clear(name);
      await user.click(screen.getByRole("button", { name: "Preview" }));
      expect(name).toHaveAttribute("aria-invalid", "true");
      expect(name).toHaveFocus();
      expect(name).toHaveAccessibleDescription("Enter a name.");
    });

    it("batch mode puts 'Choose a folder.' on the Folder field and focuses it", async () => {
      const entries = ENTRIES.map((e, i) => ({ ...e, suggestion: { ...e.suggestion, folder: i ? "30. Home/Electricity" : null } }));
      const { user } = await setup({ "GET /api/inbox": { body: entries } });
      await user.click(screen.getByRole("checkbox", { name: "Select scan001.pdf" }));
      await user.click(screen.getByRole("checkbox", { name: "Select scan002.pdf" }));
      await user.click(screen.getByRole("button", { name: "File 2 files" }));
      const folder = screen.getByRole("combobox", { name: "Folder" });
      expect(folder).toHaveAttribute("aria-invalid", "true");
      expect(folder).toHaveFocus();
      expect(folder).toHaveAccessibleDescription("Choose a folder.");
    });

    it("the batch helper text is one short line", async () => {
      const { user } = await setup();
      await user.click(screen.getByRole("checkbox", { name: "Select scan001.pdf" }));
      await user.click(screen.getByRole("checkbox", { name: "Select scan002.pdf" }));
      expect(screen.getByText(/Collection only\? Choose it/)).toBeInTheDocument();
    });

    it("the planned changes come after the form fields", async () => {
      const { user } = await setup({ "POST /api/inbox/preview": { body: SIMPLE_MOVE } });
      await user.click(screen.getByRole("button", { name: "Preview" }));
      const plan = await screen.findByRole("region", { name: "Planned changes" });
      expect(plan.closest(".inbox-plan")).not.toBeNull();
      const name = screen.getByLabelText("Name");
      expect(name.compareDocumentPosition(plan) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    });
  });

  describe("detected fields in plain words", () => {
    const withSources = (sources: string[], fields: InboxEntry["fields"]) => [
      { ...ENTRIES[0], suggestion: { ...ENTRIES[0].suggestion, sources }, fields },
    ];

    it("names the sources in plain words and copes with unknown ones", async () => {
      await setup({ "GET /api/inbox": { body: withSources(["mtime", "text-date", "filename-date", "barcode", "similar-files", "rule:x", "brand-new"], []) } });
      const fields = screen.getByRole("region", { name: "Detected fields" });
      expect(within(fields).getByText("file date, date in the text, file name, barcode, similar files, rule x, brand new")).toBeInTheDocument();
    });

    it("tells several amounts apart, the total first", async () => {
      await setup({
        "GET /api/inbox": {
          body: withSources([], [
            { kind: "amount", label: null, value: "10.00" },
            { kind: "total", label: null, value: "99.00" },
            { kind: "amount", label: null, value: "5.00" },
          ]),
        },
      });
      const fields = screen.getByRole("region", { name: "Detected fields" });
      const labels = Array.from(fields.querySelectorAll(".detected-label")).map((n) => n.textContent);
      expect(labels).toEqual(["Total", "Other amount 1", "Other amount 2"]);
    });
  });
});

describe("Filing codes in the form", () => {
  const FILING_CODES = {
    codes: [
      { code: "P", label: "To pay", tray: "to-pay", folder: null, name: null, tags: [], collections: [], as_suggested: false, inbox_folder: "To pay" },
      { code: "D", label: "File as suggested", tray: null, folder: null, name: null, tags: [], collections: [], as_suggested: true, inbox_folder: "File as suggested" },
    ],
    problems: [],
    warnings: [],
  };
  const coded = (suggestion: Partial<InboxEntry["suggestion"]>) => [
    { ...ENTRIES[0], suggestion: { ...ENTRIES[0].suggestion, ...suggestion } },
  ];
  const FROM_P = {
    tray: "to-pay",
    tray_source: "code:P",
    folder: "Bills/2026",
    folder_source: "code:P",
    collections: ["Legal"],
    collection_sources: { Legal: "code:P" },
    codes: [{ code: "P", via: "folder" as const, raw: null, unclear: false, overridden: false }],
  };
  const route = (suggestion: Partial<InboxEntry["suggestion"]>) => ({
    "GET /api/inbox": { body: coded(suggestion) },
    "GET /api/filing-codes": { body: FILING_CODES },
  });

  it("preselects the tray, the collections and names the folder a code came from", async () => {
    await setup(route(FROM_P));
    const trayGroup = await screen.findByRole("group", { name: "Then put it in" });
    await waitFor(() => expect(within(trayGroup).getByRole("button", { name: "To pay" })).toHaveAttribute("aria-pressed", "true"));
    expect(screen.getByRole("button", { name: "Remove Legal" })).toBeInTheDocument();
    expect(screen.getByLabelText("Folder")).toHaveValue("Bills/2026");
  });

  it("labels a code's chip with the code's inbox folder", async () => {
    const { user } = await setup(route({ ...FROM_P, tray_source: null, tray: null }));
    await user.clear(screen.getByLabelText("Folder"));
    expect(await screen.findByRole("group", { name: "Suggested Folder: Bills/2026 (from folder To pay)" })).toBeInTheDocument();
  });

  it("falls back to the plain code when the codes cannot be loaded", async () => {
    const { user } = await setup({
      ...route({ ...FROM_P, tray_source: null, tray: null }),
      "GET /api/filing-codes": { status: 500, body: { error: "boom" } },
    });
    await user.clear(screen.getByLabelText("Folder"));
    expect(await screen.findByRole("group", { name: "Suggested Folder: Bills/2026 (code `P`)" })).toBeInTheDocument();
  });

  it("starts with no tray for a file as suggested code", async () => {
    await setup(route({ tray: null, tray_source: "code:D", codes: [{ code: "D", via: "folder", raw: null, unclear: false, overridden: false }] }));
    const trayGroup = await screen.findByRole("group", { name: "Then put it in" });
    expect(within(trayGroup).getByRole("button", { name: "Nothing (just file)" })).toHaveAttribute("aria-pressed", "true");
  });

  it("leaves the tray on Nothing for a rule's tray guess", async () => {
    await setup(route({ tray: "to-pay", tray_source: "rule:x" }));
    const trayGroup = await screen.findByRole("group", { name: "Then put it in" });
    expect(within(trayGroup).getByRole("button", { name: "Nothing (just file)" })).toHaveAttribute("aria-pressed", "true");
  });

  it("preselects a rule's tray on a coded file, as File N marked files it", async () => {
    const codes = [{ code: "X", via: "qr" as const, raw: "dam:1:X:x:0", unclear: false, overridden: false }];
    await setup(route({ tray: "to-pay", tray_source: "rule:x", codes }));
    const trayGroup = await screen.findByRole("group", { name: "Then put it in" });
    await waitFor(() => expect(within(trayGroup).getByRole("button", { name: "To pay" })).toHaveAttribute("aria-pressed", "true"));
  });

  const STICKER = { ...FROM_P, tray: null, tray_source: null, codes: [{ code: "P", via: "qr" as const, raw: "dam:1:P:x:0", unclear: false, overridden: false }] };

  it("labels a sticker's chip with the code", async () => {
    const { user } = await setup(route(STICKER));
    await user.clear(screen.getByLabelText("Folder"));
    expect(await screen.findByRole("group", { name: "Suggested Folder: Bills/2026 (from sticker `P`)" })).toBeInTheDocument();
  });

  it("preselects the sticker's ticked boxes and sends them", async () => {
    const { calls, user } = await setup({
      ...route({ ...STICKER, star: true, important: false }),
      "POST /api/inbox/preview": { body: SIMPLE_MOVE },
    });
    const group = screen.getByRole("group", { name: "From the sticker" });
    const star = within(group).getByRole("checkbox", { name: "Star when filed" });
    const important = within(group).getByRole("checkbox", { name: "Mark Important when filed" });
    expect(star).toBeChecked();
    expect(important).not.toBeChecked();
    expect(screen.queryByText(/Tick box unclear/)).not.toBeInTheDocument();
    await user.click(important);
    await user.click(screen.getByRole("button", { name: "Preview" }));
    await waitFor(() => expect(posts(calls, "/api/inbox/preview")).toHaveLength(1));
    expect(posts(calls, "/api/inbox/preview")[0].body).toEqual([expect.objectContaining({ star: true, important: true })]);
    expect(await screen.findByText("Star it")).toBeInTheDocument(); // the plan says what follows
    expect(screen.getByText("Mark Important")).toBeInTheDocument();
  });

  it("shows no sticker group for a file without a sticker, and sends neither", async () => {
    const { calls, user } = await setup({ ...route(FROM_P), "POST /api/inbox/preview": { body: SIMPLE_MOVE } });
    expect(screen.queryByRole("group", { name: "From the sticker" })).not.toBeInTheDocument();
    expect(screen.queryByRole("checkbox", { name: "Star when filed" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Preview" }));
    await waitFor(() => expect(posts(calls, "/api/inbox/preview")).toHaveLength(1));
    const [request] = posts(calls, "/api/inbox/preview")[0].body as Array<Record<string, unknown>>;
    expect(request).not.toHaveProperty("star");
    expect(request).not.toHaveProperty("important");
  });

  it("says which tick box could not be read", async () => {
    await setup(route({ ...STICKER, star: null, important: false, marks_unclear: true }));
    const group = screen.getByRole("group", { name: "From the sticker" });
    expect(within(group).getByText("Tick box unclear: check star")).toBeInTheDocument();
    expect(within(group).getByRole("checkbox", { name: "Star when filed" })).not.toBeChecked();
  });

  it("does not offer a mark the file already has", async () => {
    const starredFile = [{ ...coded({ ...STICKER, star: true, important: true })[0] }];
    starredFile[0].record = { ...starredFile[0].record, marks: ["starred"] };
    const { calls, user } = await setup({
      ...route({}),
      "GET /api/inbox": { body: starredFile },
      "POST /api/inbox/preview": { body: SIMPLE_MOVE },
    });
    const group = screen.getByRole("group", { name: "From the sticker" });
    expect(within(group).queryByRole("checkbox", { name: "Star when filed" })).not.toBeInTheDocument();
    expect(within(group).getByText("already starred")).toBeInTheDocument();
    expect(within(group).getByRole("checkbox", { name: "Mark Important when filed" })).toBeChecked();
    await user.click(screen.getByRole("button", { name: "Preview" }));
    await waitFor(() => expect(posts(calls, "/api/inbox/preview")).toHaveLength(1));
    const [request] = posts(calls, "/api/inbox/preview")[0].body as Array<Record<string, unknown>>;
    expect(request).not.toHaveProperty("star");
    expect(request.important).toBe(true);
  });

  it("says when the codes disagree, and the list row shows the code badge", async () => {
    await setup(route({ ...FROM_P, tray: null, tray_source: null, conflict: true }));
    expect(screen.getByText("These filing codes disagree; pick the values here.")).toBeInTheDocument();
    const row = document.querySelector("[data-inbox-entry]") as HTMLElement;
    expect(within(row).getByText("P")).toBeInTheDocument();
  });

  const puts = (calls: Call[]) => calls.filter((c) => c.method === "PUT" && c.url === "/api/filing-codes/assigned");
  const ASSIGNED = { "PUT /api/filing-codes/assigned": { body: { drive_ids: ["d1"], code: "D" } } };

  it("assigns a code with c: type it and press Enter", async () => {
    const { calls, user } = await setup({ ...route({}), ...ASSIGNED });
    await waitFor(() => expect(screen.getByRole("button", { name: "Assign a filing code…" })).toBeEnabled());
    await user.keyboard("c");
    const field = await screen.findByRole("combobox", { name: "Filing code" });
    expect(screen.getByRole("option", { name: "P: To pay" })).toBeInTheDocument();
    await user.type(field, "d{Enter}");
    await waitFor(() => expect(puts(calls)).toHaveLength(1));
    expect(puts(calls)[0].body).toEqual({ drive_ids: ["d1"], code: "D" });
    expect(await screen.findByText(/filing code D\./)).toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: "Filing code" })).not.toBeInTheDocument();
  });

  it("assigns a code from the toolbar button with a click, and filters by label", async () => {
    const { calls, user } = await setup({ ...route({}), ...ASSIGNED });
    const button = screen.getByRole("button", { name: "Assign a filing code…" });
    await waitFor(() => expect(button).toBeEnabled());
    await user.click(button);
    await user.type(await screen.findByRole("combobox", { name: "Filing code" }), "sugg");
    expect(screen.queryByRole("option", { name: "P: To pay" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("option", { name: "D: File as suggested" }));
    await waitFor(() => expect(puts(calls)).toHaveLength(1));
    expect(puts(calls)[0].body).toEqual({ drive_ids: ["d1"], code: "D" });
  });

  it("shows an assigned code with × to take it off, and leaves out what it overrides", async () => {
    const codes = [
      { code: "D", via: "assigned" as const, raw: null, unclear: false, overridden: false },
      { code: "P", via: "folder" as const, raw: null, unclear: false, overridden: true },
    ];
    const { calls, user } = await setup({
      ...route({ ...FROM_P, tray: null, tray_source: "code:D", folder_source: "code:D", codes }),
      ...ASSIGNED,
    });
    const row = document.querySelector("[data-inbox-entry]") as HTMLElement;
    expect(within(row).getByText("D")).toBeInTheDocument();
    expect(within(row).queryByText(/P/)).not.toBeInTheDocument();
    expect(await screen.findByText(/Filing code D · File as suggested/)).toBeInTheDocument();
    await user.clear(screen.getByLabelText("Folder"));
    expect(
      await screen.findByRole("group", { name: "Suggested Folder: Bills/2026 (from code `D` you assigned)" }),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Take filing code D off" }));
    await waitFor(() => expect(puts(calls)).toHaveLength(1));
    expect(puts(calls)[0].body).toEqual({ drive_ids: ["d1"], code: null });
  });
});

const DRAFT = {
  id: "kotihoito",
  words: [
    { word: "kotihoito", ticked: true },
    { word: "lasku", ticked: false },
  ],
  folder: "20. Health/Kotihoito",
  name: "{doc_date}_{stem}",
  tags: ["invoice"],
  tray: null,
  payee: null,
};
const OFFER = { kind: "new", rule_id: null, drive_id: "d1", draft: DRAFT };
const REPLAY = {
  matched: 3,
  same: 3,
  different: [],
  inbox: 0,
  shadowed: [],
  checked: 3,
  total: 3,
  truncated: false,
};

describe("Filing says where it came from and offers a rule", () => {
  it("a single document sends via form, a batch via batch", async () => {
    const { calls, user } = await setup({
      "POST /api/inbox/preview": { body: SIMPLE_MOVE },
      "POST /api/inbox/file": { body: fileResult() },
    });
    await user.click(screen.getByRole("button", { name: "File it" }));
    await waitFor(() => expect(posts(calls, "/api/inbox/file")).toHaveLength(1));
    expect(posts(calls, "/api/inbox/file")[0].body).toMatchObject({ via: "form" });

    await user.click(await screen.findByRole("checkbox", { name: "Select scan001.pdf" }));
    await user.click(screen.getByRole("checkbox", { name: "Select scan002.pdf" }));
    await setFolder(user, "10. Financial/Banks");
    await user.click(screen.getByRole("button", { name: "File 2 files" }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "File" }));
    await waitFor(() => expect(posts(calls, "/api/inbox/file")).toHaveLength(2));
    expect(posts(calls, "/api/inbox/file")[1].body).toMatchObject({ via: "batch" });
  });

  it("a result with an offer adds Make a rule and Not for these to the toast", async () => {
    const { user } = await setup({
      "POST /api/inbox/preview": { body: SIMPLE_MOVE },
      "POST /api/inbox/file": { body: fileResult({ offer: OFFER }) },
    });
    await user.click(screen.getByRole("button", { name: "File it" }));
    expect(await screen.findByRole("button", { name: "Undo" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Make a rule…" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Not for these" })).toBeInTheDocument();
  });

  it("an update offer says which rule", async () => {
    const { user } = await setup({
      "POST /api/inbox/preview": { body: SIMPLE_MOVE },
      "POST /api/inbox/file": { body: fileResult({ offer: { ...OFFER, kind: "update", rule_id: "kotihoito" } }) },
    });
    await user.click(screen.getByRole("button", { name: "File it" }));
    expect(await screen.findByRole("button", { name: "Update rule kotihoito…" })).toBeInTheDocument();
  });

  it("no offer, no extra buttons", async () => {
    const { user } = await setup({
      "POST /api/inbox/preview": { body: SIMPLE_MOVE },
      "POST /api/inbox/file": { body: fileResult() },
    });
    await user.click(screen.getByRole("button", { name: "File it" }));
    await screen.findByRole("button", { name: "Undo" });
    expect(screen.queryByRole("button", { name: "Make a rule…" })).toBeNull();
  });

  it("Make a rule opens the sheet with the filed document and the inbox as folder_is", async () => {
    const { calls, user } = await setup({
      "GET /api/status": { body: { special_folders: { inbox: "##. Organize" } } },
      "POST /api/inbox/preview": { body: SIMPLE_MOVE },
      "POST /api/inbox/file": { body: fileResult({ offer: OFFER }) },
      ...replayJob(REPLAY),
    });
    await user.click(screen.getByRole("button", { name: "File it" }));
    await user.click(await screen.findByRole("button", { name: "Make a rule…" }));
    const sheet = await screen.findByRole("dialog", { name: "Make a rule" });
    expect(within(sheet).getByText(/Filed as:/)).toHaveTextContent("20. Health/Kotihoito/2026-10-01 Kotihoito lasku.pdf");
    await waitFor(() => expect(posts(calls, "/api/rules/replay/jobs").length).toBeGreaterThan(0));
    const sent = posts(calls, "/api/rules/replay/jobs").at(-1)?.body as { rule: { when: { folder_is: string; text_contains: string[] } } };
    expect(sent.rule.when.text_contains).toEqual(["kotihoito"]);
    expect(sent.rule.when.folder_is).toBe("##. Organize");
  });

  it("Update rule opens the existing rule and saves it under its own id with its own conditions", async () => {
    const when = { text_contains: ["kotihoito", "hoitomaksu"], filename_matches: "(?i)hoito", folder_is: "##. Organize" };
    const existing = {
      id: "kotihoito",
      file: "learned.yaml",
      learned: true,
      when: { ...when, zones: [], person: null },
      then: { folder: "20. Health/{year}", name: "{doc_date}_Kotihoito", tags: ["health"], tray: null, payee: null },
      stats: { suggested: 3, changed: 1, last_used: null, flagged: false },
    };
    const draft = { ...DRAFT, id: "kotihoito-2", words: [{ word: "lasku", ticked: true }] };
    const { calls, user } = await setup({
      "GET /api/status": { body: { special_folders: { inbox: "##. Organize" } } },
      "GET /api/rules": { body: { rules: [existing], errors: [], state: { offer: true, declined: 0 } } },
      "POST /api/inbox/preview": { body: SIMPLE_MOVE },
      "POST /api/inbox/file": { body: fileResult({ offer: { ...OFFER, kind: "update", rule_id: "kotihoito", draft } }) },
      ...replayJob(REPLAY),
      "PUT /api/rules/kotihoito": { body: { rules: [existing], errors: [], state: { offer: true, declined: 0 } } },
    });
    await user.click(screen.getByRole("button", { name: "File it" }));
    await user.click(await screen.findByRole("button", { name: "Update rule kotihoito…" }));
    const sheet = await screen.findByRole("dialog", { name: "Update rule kotihoito" });
    expect(within(sheet).getByText(/Filed as:/)).toHaveTextContent("20. Health/Kotihoito/2026-10-01 Kotihoito lasku.pdf");
    const save = await within(sheet).findByRole("button", { name: "Save rule" });
    await waitFor(() => expect(save).toBeEnabled());
    await user.click(save);
    await waitFor(() => expect(calls.some((c) => c.method === "PUT")).toBe(true));
    const put = calls.find((c) => c.method === "PUT")!;
    expect(put.url).toBe("/api/rules/kotihoito?replaces=kotihoito");
    const body = put.body as { id: string; when: unknown; then: Record<string, unknown> };
    expect(body.id).toBe("kotihoito");
    expect(body.when).toEqual(when);
    // the filing's folder and name patterns; the rule's other actions stay
    expect(body.then).toMatchObject({ folder: DRAFT.folder, name: DRAFT.name, tags: ["health"] });
  });

  it("Not for these posts the ticked words", async () => {
    const { calls, user } = await setup({
      "POST /api/inbox/preview": { body: SIMPLE_MOVE },
      "POST /api/inbox/file": { body: fileResult({ offer: OFFER }) },
      "POST /api/rules/state/decline": { body: { offer: true, declined: 1 } },
    });
    await user.click(screen.getByRole("button", { name: "File it" }));
    await user.click(await screen.findByRole("button", { name: "Not for these" }));
    await waitFor(() => expect(posts(calls, "/api/rules/state/decline")).toHaveLength(1));
    expect(posts(calls, "/api/rules/state/decline")[0].body).toEqual({ words: ["kotihoito"] });
  });
});

describe("review card header", () => {
  it("names no folder for a file directly in the inbox, and the folder inside it otherwise", async () => {
    const inCode = { ...ENTRIES[1], record: { ...ENTRIES[1].record, path: "##. Organize/To pay/scan002.pdf" } };
    const { user } = await setup({
      "GET /api/status": { body: { special_folders: { inbox: "##. Organize" } } },
      "GET /api/inbox": { body: [ENTRIES[0], inCode] },
    });
    const card = () => screen.getByRole("article");
    await waitFor(() => expect(card().querySelector(".doc-meta")).not.toHaveTextContent(/ in /));
    await user.click(screen.getAllByRole("button", { name: /scan002\.pdf/ })[0]);
    await waitFor(() => expect(card().querySelector(".doc-meta")).toHaveTextContent(/ in To pay$/));
  });
});

describe("the inline plan", () => {
  it("closes with its ×", async () => {
    const { user } = await setup({ "POST /api/inbox/preview": { body: SIMPLE_MOVE } });
    await user.click(screen.getByRole("button", { name: "Preview" }));
    const shown = await screen.findByRole("region", { name: "Planned changes" });
    await user.click(within(shown).getByRole("button", { name: "Close the preview" }));
    expect(screen.queryByRole("region", { name: "Planned changes" })).not.toBeInTheDocument();
  });
});

describe("Renews …?", () => {
  afterEach(() => forgetUnlocks());

  const candidate = (item_id: number, title: string, folder: string | null, extra: Record<string, unknown> = {}) => ({
    item_id,
    title,
    drive_id: `old${item_id}`,
    expires: "2027-06-30",
    kind: "Passport",
    folder,
    person: null,
    locked: false,
    ...extra,
  });
  const PASSPORT = candidate(7, "Passport Tiina", "20. Health/Kotihoito");
  const ELSEWHERE = candidate(8, "Driving licence", "30. Home/Electricity");
  const RENEW_PLAN: ResolvedOp[] = [
    move("##. Organize/scan001.pdf", "20. Health/Kotihoito/2026-10-01 Kotihoito lasku.pdf"),
    { kind: "mkdir", src: null, dst: "20. Health/Kotihoito/Expired", drive_id: null, note: null },
    { kind: "move", src: "20. Health/Kotihoito/passport.pdf", dst: "20. Health/Kotihoito/Expired/passport.pdf", drive_id: "old7", note: null },
  ];
  const chipName = 'Suggested renewal: Renews "Passport Tiina" (same folder and person)';
  const setDate = (value: string) => fireEvent.change(screen.getByLabelText("New expiry date"), { target: { value } });

  it("one match shows the chip; taking it asks for a date; File it sends renews and renew_expires", async () => {
    const { calls, user } = await setup({
      "GET /api/renewals/open": { body: [PASSPORT, ELSEWHERE] },
      "POST /api/inbox/preview": { body: RENEW_PLAN },
      "POST /api/inbox/file": { body: fileResult({ done: RENEW_PLAN, renew_batch: "b1", renew_undo: "activity" }) },
    });
    const chip = await screen.findByRole("group", { name: chipName });
    expect(screen.getByText("Then put it in")).toBeInTheDocument();
    await user.click(within(chip).getByRole("button", { name: "Use" }));

    // the tray is the renewal's: the picker is gone, and a date is asked for
    expect(screen.queryByText("Then put it in")).not.toBeInTheDocument();
    expect(screen.queryByRole("group", { name: chipName })).not.toBeInTheDocument();
    expect(screen.getByText(/Renews "Passport Tiina"/)).toBeInTheDocument();
    const fileIt = () => screen.getByRole("button", { name: "File it" }); // a disabled one is wrapped
    expect(screen.getByLabelText("New expiry date")).toBeRequired();
    expect(fileIt()).toBeDisabled();
    expect(fileIt().closest(".button-wrap")).toHaveAttribute("data-tip", "Enter the new expiry date.");
    await user.keyboard("{Meta>}{Enter}{/Meta}");
    expect(posts(calls, "/api/inbox/preview")).toHaveLength(0);

    setDate("2037-06-30");
    expect(fileIt()).toBeEnabled();
    await user.click(fileIt());
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("Renews Passport Tiina, old file to Expired")).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "File" }));
    await waitFor(() => expect(posts(calls, "/api/inbox/file")).toHaveLength(1));
    const [request] = (posts(calls, "/api/inbox/file")[0].body as { requests: Record<string, unknown>[] }).requests;
    expect(request).toEqual({
      drive_id: "d1",
      name: "2026-10-01 Kotihoito lasku.pdf",
      folder: "20. Health/Kotihoito",
      tags: ["invoice"],
      renews: 7,
      renew_expires: "2037-06-30",
    });
  });

  it("Don't renew puts the tray picker back and sends no renewal", async () => {
    const { calls, user } = await setup({
      "GET /api/renewals/open": { body: [PASSPORT] },
      "POST /api/inbox/preview": { body: SIMPLE_MOVE },
    });
    await user.click(within(await screen.findByRole("group", { name: chipName })).getByRole("button", { name: "Use" }));
    await user.click(screen.getByRole("button", { name: "Don’t renew" }));
    expect(screen.getByText("Then put it in")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Preview" }));
    await waitFor(() => expect(posts(calls, "/api/inbox/preview")).toHaveLength(1));
    expect((posts(calls, "/api/inbox/preview")[0].body as Record<string, unknown>[])[0]).not.toHaveProperty("renews");
  });

  it("folder changed: the chip disappears", async () => {
    const { user } = await setup({ "GET /api/renewals/open": { body: [PASSPORT] } });
    await screen.findByRole("group", { name: chipName });
    await setFolder(user, "10. Financial/Banks");
    expect(screen.queryByRole("group", { name: chipName })).not.toBeInTheDocument();
  });

  it("another person's item is no match", async () => {
    await setup({ "GET /api/renewals/open": { body: [{ ...PASSPORT, person: "Tiina" }] } });
    await screen.findByRole("button", { name: "Renews…" });
    expect(screen.queryByRole("group", { name: chipName })).not.toBeInTheDocument();
  });

  /** The first entry with a rule's {person} folder for Tiina, and ``assignment``. */
  const personEntries = (assignment: InboxEntry["assignment"] = null) => {
    const [first, ...rest] = ENTRIES;
    const withPerson: InboxEntry = {
      ...first,
      suggestion: { ...first.suggestion, person: "Tiina", person_source: "address area" },
      person_follows_folder: true,
      assignment,
    };
    return [withPerson, ...rest];
  };
  const assigned = (person: string, set_by: "owner" | "filing") => ({ drive_id: "d1", sender: null, person, set_by, set_at: 0 });
  const tiina = candidate(7, "Passport Tiina", "20. Health/Kotihoito", { person: "Tiina" });

  it("the person is the one the filing records: the rule's, only while its folder is kept", async () => {
    const banks = candidate(10, "Bank card Tiina", "10. Financial/Banks", { person: "Tiina" });
    const { user } = await setup({
      "GET /api/inbox": { body: personEntries() },
      "GET /api/renewals/open": { body: [tiina, banks] },
    });
    expect(await screen.findByRole("group", { name: chipName })).toBeInTheDocument();
    // another folder: the rule's person is not recorded, so Tiina's items are no match
    await setFolder(user, "10. Financial/Banks");
    expect(screen.queryByRole("group", { name: /Suggested renewal/ })).not.toBeInTheDocument();
  });

  it("the owner's For wins over the rule's person", async () => {
    const mikko = candidate(11, "Passport Mikko", "20. Health/Kotihoito", { person: "Mikko" });
    await setup({
      "GET /api/inbox": { body: personEntries(assigned("Mikko", "owner")) },
      "GET /api/renewals/open": { body: [tiina, mikko] },
    });
    expect(await screen.findByRole("group", { name: 'Suggested renewal: Renews "Passport Mikko" (same folder and person)' })).toBeInTheDocument();
    expect(screen.queryByRole("group", { name: chipName })).not.toBeInTheDocument();
  });

  it("a For a filing set is replaced by the rule's person while its folder is kept", async () => {
    const mikko = candidate(11, "Bank card Mikko", "10. Financial/Banks", { person: "Mikko" });
    const { user } = await setup({
      "GET /api/inbox": { body: personEntries(assigned("Mikko", "filing")) },
      "GET /api/renewals/open": { body: [tiina, mikko] },
    });
    expect(await screen.findByRole("group", { name: chipName })).toBeInTheDocument();
    await setFolder(user, "10. Financial/Banks");
    expect(await screen.findByRole("group", { name: 'Suggested renewal: Renews "Bank card Mikko" (same folder and person)' })).toBeInTheDocument();
  });

  it("a renewal taken from the chip is dropped when the folder no longer matches", async () => {
    const { user } = await setup({ "GET /api/renewals/open": { body: [PASSPORT, ELSEWHERE] } });
    await user.click(within(await screen.findByRole("group", { name: chipName })).getByRole("button", { name: "Use" }));
    expect(screen.getByLabelText("New expiry date")).toBeInTheDocument();
    await setFolder(user, "10. Financial/Banks");
    await waitFor(() => expect(screen.queryByLabelText("New expiry date")).not.toBeInTheDocument());
    expect(screen.queryByText(/Renews "Passport Tiina"/)).not.toBeInTheDocument();
  });

  it("a renewal picked by hand stays when the folder changes", async () => {
    const { user } = await setup({ "GET /api/renewals/open": { body: [PASSPORT, ELSEWHERE] } });
    await screen.findByRole("group", { name: chipName });
    await user.click(screen.getByRole("button", { name: "Renews…" }));
    await user.selectOptions(screen.getByRole("combobox", { name: "Renews" }), "7");
    await setFolder(user, "10. Financial/Banks");
    expect(screen.getByLabelText("New expiry date")).toBeInTheDocument();
    expect(screen.getByText(/Renews "Passport Tiina"/)).toBeInTheDocument();
  });

  it("a renewal the server did not record gives no Renewed toast", async () => {
    const { user } = await setup({
      "GET /api/renewals/open": { body: [PASSPORT] },
      "POST /api/inbox/preview": { body: RENEW_PLAN },
      "POST /api/inbox/file": {
        body: fileResult({ done: RENEW_PLAN, renew_batch: null, renew_undo: null, follow_up_error: "InvalidRequest: reopen it" }),
      },
    });
    await user.click(within(await screen.findByRole("group", { name: chipName })).getByRole("button", { name: "Use" }));
    setDate("2037-06-30");
    await user.click(screen.getByRole("button", { name: "File it" }));
    await user.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "File" }));
    expect(await screen.findByText(/^Filed 2 files/)).toBeInTheDocument();
    expect(screen.queryByText(/renewed/i)).not.toBeInTheDocument();
    expect(screen.getByText(/adding to tray\/collection failed/)).toBeInTheDocument();
  });

  it("several matches show a select", async () => {
    const second = candidate(9, "Passport Mikko", "20. Health/Kotihoito");
    const { calls, user } = await setup({
      "GET /api/renewals/open": { body: [PASSPORT, second, ELSEWHERE] },
      "POST /api/inbox/preview": { body: RENEW_PLAN },
    });
    const select = await screen.findByRole("combobox", { name: "Renews" });
    expect(within(select).getAllByRole("option").map((o) => o.textContent)).toEqual([
      "Nothing",
      "Passport Tiina · expires 30.6.2027",
      "Passport Mikko · expires 30.6.2027",
    ]);
    expect(screen.queryByRole("group", { name: chipName })).not.toBeInTheDocument();
    await user.selectOptions(select, "9");
    setDate("2037-01-31");
    await user.click(screen.getByRole("button", { name: "Preview" }));
    await waitFor(() => expect(posts(calls, "/api/inbox/preview")).toHaveLength(1));
    expect((posts(calls, "/api/inbox/preview")[0].body as Record<string, unknown>[])[0]).toMatchObject({
      renews: 9,
      renew_expires: "2037-01-31",
    });
  });

  it("Renews… opens the select over every candidate", async () => {
    const { user } = await setup({ "GET /api/renewals/open": { body: [ELSEWHERE, PASSPORT] } });
    await screen.findByRole("group", { name: chipName });
    await user.click(screen.getByRole("button", { name: "Renews…" }));
    const select = screen.getByRole("combobox", { name: "Renews" });
    expect(within(select).getAllByRole("option")).toHaveLength(3);
    await user.selectOptions(select, "8");
    expect(screen.getByText(/Renews "Driving licence"/)).toBeInTheDocument();
    expect(screen.getByLabelText("New expiry date")).toBeInTheDocument();
  });

  it("a locked old file: Unlock and move unlocks it for the filing and locks it again after", async () => {
    const locked = { ...PASSPORT, locked: true };
    const { calls, user } = await setup({
      "GET /api/renewals/open": { body: [locked] },
      "POST /api/inbox/preview": (call) =>
        call.headers["X-Dam-Unlock"] === "tok-1"
          ? { body: RENEW_PLAN }
          : { status: 400, body: { error: "This file is locked: 20. Health/Kotihoito/passport.pdf" } },
      "POST /api/inbox/file": { body: fileResult({ done: RENEW_PLAN, renew_batch: "b1", renew_undo: "activity" }) },
      "POST /api/files/old7/unlock": { body: { token: "tok-1" } },
      "DELETE /api/files/old7/unlock": { status: 204 },
    });
    await user.click(within(await screen.findByRole("group", { name: chipName })).getByRole("button", { name: "Use" }));
    setDate("2037-06-30");
    await user.click(screen.getByRole("button", { name: "Preview" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("This file is locked");
    await user.click(screen.getByRole("button", { name: "Unlock and move" }));
    const dialog = await screen.findByRole("dialog");
    expect(posts(calls, "/api/files/old7/unlock")[0].body).toEqual({ mode: "now" });
    expect(calls.filter((c) => c.method === "DELETE")).toHaveLength(0); // held while the confirm is open
    await user.click(within(dialog).getByRole("button", { name: "File" }));
    await waitFor(() => expect(posts(calls, "/api/inbox/file")).toHaveLength(1));
    expect(posts(calls, "/api/inbox/file")[0].headers["X-Dam-Unlock"]).toBe("tok-1");
    await waitFor(() => expect(calls.filter((c) => c.method === "DELETE" && c.url === "/api/files/old7/unlock")).toHaveLength(1));
  });

  it("Unlock and move waits for a preview that reported the lock", async () => {
    const { user } = await setup({
      "GET /api/renewals/open": { body: [{ ...PASSPORT, locked: true }] },
      "POST /api/inbox/preview": { status: 400, body: { error: "This file is locked: 20. Health/Kotihoito/passport.pdf" } },
    });
    await user.click(within(await screen.findByRole("group", { name: chipName })).getByRole("button", { name: "Use" }));
    setDate("2037-06-30");
    expect(screen.queryByRole("button", { name: "Unlock and move" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Preview" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("This file is locked");
    expect(screen.getByRole("button", { name: "Unlock and move" })).toBeInTheDocument();
  });

  it("cancelling the confirm after Unlock and move locks the old file again", async () => {
    let unlocked = false;
    const { calls, user } = await setup({
      "GET /api/renewals/open": { body: [{ ...PASSPORT, locked: true }] },
      "POST /api/inbox/preview": (call) =>
        call.headers["X-Dam-Unlock"] === "tok-1"
          ? { body: RENEW_PLAN }
          : { status: 400, body: { error: "This file is locked: 20. Health/Kotihoito/passport.pdf" } },
      "POST /api/files/old7/unlock": () => ((unlocked = true), { body: { token: "tok-1" } }),
      "DELETE /api/files/old7/unlock": { status: 204 },
    });
    await user.click(within(await screen.findByRole("group", { name: chipName })).getByRole("button", { name: "Use" }));
    setDate("2037-06-30");
    await user.click(screen.getByRole("button", { name: "Preview" }));
    await screen.findByRole("alert");
    await user.click(screen.getByRole("button", { name: "Unlock and move" }));
    expect(unlocked).toBe(true);
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(calls.filter((c) => c.method === "DELETE" && c.url === "/api/files/old7/unlock")).toHaveLength(1));
    expect(posts(calls, "/api/inbox/file")).toHaveLength(0);
  });

  it("a renewal with its own Undo, and a skipped move, say so in the toast", async () => {
    const { calls, user } = await setup({
      "GET /api/renewals/open": { body: [PASSPORT] },
      "POST /api/inbox/preview": { body: [] },
      "POST /api/inbox/file": {
        body: fileResult({ done: [], renew_batch: "r1", renew_undo: "renewal", renew_skipped: "The old file is already in Expired" }),
      },
      "POST /api/renewals/undo": { body: {} },
    });
    await user.click(within(await screen.findByRole("group", { name: chipName })).getByRole("button", { name: "Use" }));
    setDate("2037-06-30");
    await user.click(screen.getByRole("button", { name: "File it" }));
    await user.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "File" }));
    expect(await screen.findByText(/Renewed Passport Tiina\. The old file is already in Expired, so it was not moved\./)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Undo" }));
    await waitFor(() => expect(posts(calls, "/api/renewals/undo")).toHaveLength(1));
    expect(posts(calls, "/api/renewals/undo")[0].body).toEqual({ batch_id: "r1" });
  });
});
