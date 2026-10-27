import { CONFIRM_KEY_DELAY_MS } from "../components/PlanPreview";
import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { BatchSummary, JournalEntry } from "../api/client";
import { MemoryRouter, useLocation } from "react-router-dom";
import { type Call, deferred, mockFetch, renderWithProviders as renderBare, undoButton } from "../test-utils";
import { STATUS_ON } from "../components/ai/testData";
import Activity, {
  ACTIVITY_SEARCH_DEBOUNCE_MS,
  Highlight,
  batchTitle,
  dayLabel,
  derivedTitle,
  opsSummary,
  syncLabel,
  whenSince,
} from "./Activity";

function Where() {
  const l = useLocation();
  return <output aria-label="location">{l.pathname + l.search}</output>;
}

beforeEach(() => localStorage.clear());
const expandAll = async () => userEvent.setup().click(await screen.findByRole("button", { name: "Expand all" }));

/** Activity in a router (its search and filters live in the URL), at ``url``. */
function renderWithProviders(ui: React.ReactElement, url = "/activity") {
  return renderBare(
    <MemoryRouter initialEntries={[url]}>
      {ui}
      <Where />
    </MemoryRouter>,
  );
}

function row(batch: string, overrides: Partial<JournalEntry> = {}): JournalEntry {
  return {
    id: 1,
    batch_id: batch,
    seq: 0,
    kind: "move",
    src: "##. Organize/scan001.pdf",
    dst: "10. Financial/Banks/2026-10-01 lasku.pdf",
    drive_id: "d1",
    size: 10,
    mtime: 1,
    is_file: true,
    state: "done",
    error: null,
    origin: "ui",
    undo_of: null,
    created: 1_760_000_000,
    finished: 1_760_000_001,
    marks: [],
    ...overrides,
  };
}

function batch(id: string, ops: JournalEntry[], overrides: Partial<BatchSummary> = {}): BatchSummary {
  return { batch_id: id, created: ops[0].created, origin: "ui", ops, undone: false, is_undo: false, undoable: true, ...overrides };
}

const B1 = batch("b1", [
  row("b1", { id: 1, kind: "mkdir", src: null, dst: "10. Financial/Banks", drive_id: null }),
  row("b1", { id: 2, seq: 1 }),
]);
const B2 = batch(
  "b2",
  [row("b2", { id: 3, src: "##. Organize/old.pdf", dst: "13. Taxes/old.pdf", state: "undone", origin: "cli" })],
  { undone: true, undoable: false, origin: "cli", created: 1_750_000_000 },
);
const B3 = batch(
  "b3",
  [row("b3", { id: 4, src: "13. Taxes/x.pdf", dst: "##. Organize/x.pdf", origin: "undo", undo_of: "b9" })],
  { is_undo: true, undoable: false, origin: "undo", undo_of: "b9", undoes_label: "Filed Offer of Näkymä into 80. Misc" },
);

const B1_UNDO = [
  { kind: "move", src: "10. Financial/Banks/2026-10-01 lasku.pdf", dst: "##. Organize/scan001.pdf", drive_id: "d1", note: null },
];

const UNDO_RESULT = { batch_id: "u1", dry_run: false, done: [], failed: null, error: null, index_error: null, follow_up_error: null };

const posts = (calls: Call[], url: string) => calls.filter((c) => c.method === "POST" && c.url === url);

function api(extra: Parameters<typeof mockFetch>[0] = {}) {
  return mockFetch({
    "GET /api/activity": { body: [B1, B2, B3] },
    "GET /api/recovery": { body: [] },
    "POST /api/activity/b1/undo/preview": { body: B1_UNDO },
    "POST /api/activity/b1/undo": { body: UNDO_RESULT },
    ...extra,
  });
}

const batchArticle = (id: string) => screen.getByRole("article", { name: `Batch ${id}` });

describe("Activity", () => {
  it("lists batches with their ops; Undo posts to the batch; undone batches cannot be undone", async () => {
    const calls = api();
    const user = userEvent.setup();
    renderWithProviders(<Activity />);
    await screen.findByRole("article", { name: "Batch b1" });
    await expandAll();
    const articles = screen.getAllByRole("article");
    expect(articles.map((a) => a.getAttribute("aria-label"))).toEqual(["Batch b1", "Batch b2", "Batch b3"]);
    expect(within(batchArticle("b1")).getByText("10. Financial/Banks/2026-10-01 lasku.pdf")).toBeInTheDocument();
    expect(within(batchArticle("b2")).getByText("command line")).toBeInTheDocument();
    expect(within(batchArticle("b2")).getByText("Undone")).toBeInTheDocument();

    expect(within(batchArticle("b2")).getByRole("button", { name: "Undo" })).toBeDisabled();
    expect(within(batchArticle("b3")).getByRole("button", { name: "Undo" })).toBeDisabled();
    // an undo batch names what it reverted; "Undone" is the one state word for the reverted batch
    expect(within(batchArticle("b3")).getByText("Undo of Filed Offer of Näkymä into 80. Misc")).toBeInTheDocument();
    expect(within(batchArticle("b3")).queryByText("Reverted")).not.toBeInTheDocument();
    expect(within(batchArticle("b3")).queryByText("undo")).not.toBeInTheDocument();
    expect(within(batchArticle("b2")).getByText("Undone")).toHaveClass("tag-grey");

    await user.click(within(batchArticle("b1")).getByRole("button", { name: "Undo" }));
    const dialog = await screen.findByRole("dialog");
    // the server's undo preview, rendered as a plan: exactly what undo will run
    expect(await within(dialog).findByText("Undoing will:")).toBeInTheDocument();
    expect([...dialog.querySelectorAll(".plan-op")].map((li) => li.textContent)).toEqual([
      "Move10. Financial/Banks/2026-10-01 lasku.pdf → ##. Organize/scan001.pdf",
    ]);
    expect(posts(calls, "/api/activity/b1/undo/preview")).toHaveLength(1);
    expect(posts(calls, "/api/activity/b1/undo")).toHaveLength(0);
    await user.click(await undoButton(dialog));
    await waitFor(() => expect(posts(calls, "/api/activity/b1/undo")).toHaveLength(1));
    const [post] = posts(calls, "/api/activity/b1/undo");
    expect(post.body).toEqual({});
    expect(post.headers["Content-Type"]).toBe("application/json");
    expect(post.credentials).toBe("same-origin");
    expect(await screen.findByText("Undone.")).toBeInTheDocument();
  });

  it("an undo whose follow-up removal failed says so as a warning", async () => {
    const calls = api({
      "POST /api/activity/b1/undo/preview": { body: [] }, "POST /api/activity/b1/undo": { body: { ...UNDO_RESULT, follow_up_error: "note\u202E not removed" } },
    });
    const user = userEvent.setup();
    renderWithProviders(<Activity />);
    await user.click(within(await screen.findByRole("article", { name: "Batch b1" })).getByRole("button", { name: "Undo" }));
    await user.click(await undoButton(await screen.findByRole("dialog")));
    await waitFor(() => expect(posts(calls, "/api/activity/b1/undo")).toHaveLength(1));
    const warning = await screen.findByText(/Files restored, but: note⟨U\+202E⟩ not removed/);
    expect(warning.closest(".toast")).toHaveClass("toast-warning");
    expect(screen.queryByText("Undone.")).not.toBeInTheDocument();
  });

  it("an automatic Ongoing sync has no Undo button and says what to undo instead", async () => {
    api({
      "GET /api/activity": {
        body: [batch("w1", [row("w1", { kind: "symlink", origin: "workflow" })], { origin: "workflow", undoable: false })],
      },
    });
    renderWithProviders(<Activity />);
    const article = await screen.findByRole("article", { name: "Batch w1" });
    expect(within(article).queryByRole("button", { name: "Undo" })).not.toBeInTheDocument();
    expect(within(article).getByText(/Made automatically after a collection change/)).toBeInTheDocument();
    expect(within(article).getByText(/change the collection to undo it/)).toBeInTheDocument();
  });

  it("an automatic sync names the folder it changed: ##. Important, ##. Ongoing, or neither", async () => {
    api({
      "GET /api/status": {
        body: { special_folders: { inbox: "##. Organize", ongoing: "##. Ongoing", important: "##. Important", quarantine: "##. To Delete" } },
      },
      "GET /api/activity": {
        body: [
          batch("i1", [
            row("i1", { kind: "unlink_symlink", src: "##. Important/beach.jpg", dst: "40. Family/beach.jpg", origin: "workflow" }),
            row("i1", { id: 2, kind: "symlink", src: "40. Family/beach.jpg", dst: "##. Important/Houses/beach.jpg", origin: "workflow" }),
          ], { origin: "workflow", undoable: false }),
          batch("o1", [row("o1", { kind: "symlink", src: "30. Home/a.pdf", dst: "##. Ongoing/a.pdf", origin: "workflow" })], { origin: "workflow", undoable: false }),
          batch("b1", [
            row("b1", { kind: "symlink", src: "30. Home/a.pdf", dst: "##. Ongoing/a.pdf", origin: "workflow" }),
            row("b1", { id: 2, kind: "mkdir", src: null, dst: "##. Important/Houses", origin: "workflow" }),
          ], { origin: "workflow", undoable: false }),
          batch("n1", [row("n1", { kind: "move", origin: "workflow" })], { origin: "workflow", undoable: false }),
        ],
      },
    });
    renderWithProviders(<Activity />);
    const note = async (id: string) => (await screen.findByRole("article", { name: `Batch ${id}` })).querySelector(".batch-note")!;
    const title = async (id: string) => (await screen.findByRole("article", { name: `Batch ${id}` })).querySelector(".batch-title")!;
    expect(await title("i1")).toHaveTextContent("Automatic ##. Important update");
    expect(await title("o1")).toHaveTextContent("Automatic ##. Ongoing update");
    expect(await title("b1")).toHaveTextContent(/^Automatic update$/);
    expect(await title("n1")).toHaveTextContent(/^Automatic update$/);
    expect(await note("i1")).toHaveTextContent("Made automatically after a collection change");
  });

  it("syncLabel reads the server's folder names", () => {
    const roots = { ongoing: "Työn alla", important: "Tärkeät" };
    expect(syncLabel([{ kind: "mkdir", src: null, dst: "Tärkeät/A" }], roots)).toBe("Automatic Tärkeät sync");
    expect(syncLabel([{ kind: "mkdir", src: null, dst: "Tärkeät2/A" }], roots)).toBe("Automatic sync"); // a prefix is not the folder
    expect(syncLabel([{ kind: "mkdir", src: null, dst: "Tärkeät/A" }], roots, "update")).toBe("Automatic Tärkeät update");
  });

  it("a batch the server marks not undoable cannot be undone", async () => {
    api({ "GET /api/activity": { body: [batch("b7", [row("b7", {})], { undoable: false })] } });
    renderWithProviders(<Activity />);
    const article = await screen.findByRole("article", { name: "Batch b7" });
    expect(within(article).getByRole("button", { name: "Undo" })).toBeDisabled();
  });

  it("the confirm shows the server's undo plan, after a loading state, as a plan list", async () => {
    const plan = deferred<{ body: unknown }>();
    const ONG = "##. Ongoing/Legal";
    const calls = api({ "POST /api/activity/b1/undo/preview": () => plan.promise });
    const user = userEvent.setup();
    renderWithProviders(<Activity />);
    await user.click(within(await screen.findByRole("article", { name: "Batch b1" })).getByRole("button", { name: "Undo" }));
    const dialog = await screen.findByRole("dialog", { name: "Undo these changes?" });
    expect(within(dialog).getByText("Checking what undo will do…")).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Undo" })).toBeDisabled();
    expect(posts(calls, "/api/activity/b1/undo/preview")).toHaveLength(1);
    await act(async () =>
      plan.resolve({
        body: [
          { kind: "move", src: "40. Family/Legal/a.pdf", dst: `${ONG}/a.pdf`, drive_id: "d1", note: null },
          { kind: "remove_empty_dir", src: ONG, dst: ONG, drive_id: null, note: null },
          { kind: "mkdir", src: null, dst: ONG, drive_id: null, note: null },
        ],
      }),
    );
    expect(await within(dialog).findByText("Undoing will:")).toBeInTheDocument();
    // exactly the server's ops (not guessed from the journal), as KIND_LABEL / SINGLE_PATH show them
    expect(within(dialog).getAllByRole("listitem").map((li) => li.textContent)).toEqual([
      `Move40. Family/Legal/a.pdf → ${ONG}/a.pdf`,
      `Remove empty folder${ONG}`,
      `New folder${ONG}`,
    ]);
    expect(within(dialog).getByText("New folders it created stay, empty.")).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Undo" })).toBeEnabled();
  });

  it("a refused undo preview says why and disables Undo, also for ⌘Enter", async () => {
    const calls = api({
      "POST /api/activity/b1/undo/preview": {
        status: 409,
        body: { error: "changed since the operation: 10. Financial/Banks/2026-10-01 lasku.pdf" },
      },
    });
    const user = userEvent.setup();
    renderWithProviders(<Activity />);
    await user.click(within(await screen.findByRole("article", { name: "Batch b1" })).getByRole("button", { name: "Undo" }));
    const dialog = await screen.findByRole("dialog", { name: "Undo these changes?" });
    expect(await within(dialog).findByRole("alert")).toHaveTextContent(
      /^Cannot undo: .*changed since the operation: 10\. Financial\/Banks\/2026-10-01 lasku\.pdf$/,
    );
    const undo = within(dialog).getByRole("button", { name: "Undo" });
    expect(undo).toBeDisabled();
    expect(within(dialog).queryByText("Undoing will:")).not.toBeInTheDocument();
    await new Promise((r) => setTimeout(r, CONFIRM_KEY_DELAY_MS + 50));
    await user.keyboard("{Meta>}{Enter}{/Meta}");
    await user.click(undo);
    expect(posts(calls, "/api/activity/b1/undo")).toHaveLength(0);
    expect(posts(calls, "/api/activity/b1/undo/preview")).toHaveLength(1); // never retried
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("a double click on the dialog's Undo sends one request", async () => {
    const held = deferred<{ body: unknown }>();
    const calls = api({ "POST /api/activity/b1/undo/preview": { body: [] }, "POST /api/activity/b1/undo": () => held.promise });
    const user = userEvent.setup();
    renderWithProviders(<Activity />);
    await user.click(within(await screen.findByRole("article", { name: "Batch b1" })).getByRole("button", { name: "Undo" }));
    const confirm = await undoButton(await screen.findByRole("dialog"));
    fireEvent.click(confirm);
    fireEvent.click(confirm);
    await act(async () => held.resolve({ body: UNDO_RESULT }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(posts(calls, "/api/activity/b1/undo")).toHaveLength(1);
  });

  describe("collapsible cards", () => {
    const two = () =>
      api({ "GET /api/activity": { body: [batch("c1", [row("c1", { src: "A/x.pdf", dst: "B/x.pdf" })]), batch("c2", [row("c2", { id: 9, src: "A/y.pdf", dst: "B/y.pdf" })])] } });
    const toggleOf = (id: string) => within(batchArticle(id)).getByRole("button", { name: /operations of/ });

    it("starts collapsed: the top part and Undo only; a click on the title row or the chevron toggles one card", async () => {
      two();
      const user = userEvent.setup();
      renderWithProviders(<Activity />);
      await screen.findByRole("article", { name: "Batch c1" });
      expect(toggleOf("c1")).toHaveAttribute("aria-expanded", "false");
      expect(within(batchArticle("c1")).queryByRole("list")).not.toBeInTheDocument();
      expect(within(batchArticle("c1")).getByRole("button", { name: "Undo" })).toBeInTheDocument();
      await user.click(toggleOf("c1"));
      expect(toggleOf("c1")).toHaveAttribute("aria-expanded", "true");
      expect(within(batchArticle("c1")).getByRole("list")).toBeInTheDocument();
      expect(toggleOf("c2")).toHaveAttribute("aria-expanded", "false");
      await user.click(batchArticle("c1").querySelector(".batch-title")!);
      expect(toggleOf("c1")).toHaveAttribute("aria-expanded", "false");
      toggleOf("c2").focus();
      await user.keyboard("{Enter}");
      expect(toggleOf("c2")).toHaveAttribute("aria-expanded", "true");
    });

    it("Expand all and Collapse all apply to every card; single toggles override afterwards; the default is remembered", async () => {
      two();
      const user = userEvent.setup();
      const first = renderWithProviders(<Activity />);
      await user.click(await screen.findByRole("button", { name: "Expand all" }));
      expect(toggleOf("c1")).toHaveAttribute("aria-expanded", "true");
      expect(toggleOf("c2")).toHaveAttribute("aria-expanded", "true");
      await user.click(toggleOf("c2"));
      expect(toggleOf("c1")).toHaveAttribute("aria-expanded", "true");
      expect(toggleOf("c2")).toHaveAttribute("aria-expanded", "false");
      // a fresh page remembers "expanded"
      first.unmount();
      renderWithProviders(<Activity />);
      await screen.findByRole("article", { name: "Batch c1" });
      expect(toggleOf("c2")).toHaveAttribute("aria-expanded", "true");
      await user.click(screen.getByRole("button", { name: "Collapse all" }));
      expect(toggleOf("c1")).toHaveAttribute("aria-expanded", "false");
      expect(toggleOf("c2")).toHaveAttribute("aria-expanded", "false");
    });

    it("a search shows every card expanded", async () => {
      two();
      renderWithProviders(<Activity />, "/activity?q=x.pdf");
      await screen.findByRole("article", { name: "Batch c1" });
      expect(toggleOf("c1")).toHaveAttribute("aria-expanded", "true");
      expect(within(batchArticle("c1")).getByRole("list")).toBeInTheDocument();
    });
  });

  it("shows hidden characters in op paths", async () => {
    api({
      "GET /api/activity": {
        body: [batch("b1", [row("b1", { src: "a‮fdp.exe", dst: "X/a‮fdp.exe" })])],
      },
    });
    renderWithProviders(<Activity />);
    await expandAll();
    expect(await screen.findByText("a⟨U+202E⟩fdp.exe")).toBeInTheDocument();
  });

  it("offers recovery for pending entries behind a confirm and shows the result", async () => {
    const pending = row("b5", { id: 9, state: "planned", src: "a.pdf", dst: "X/a.pdf", finished: null });
    const calls = api({
      "GET /api/recovery": { body: [pending] },
      "POST /api/recovery": {
        body: { entries: [{ ...pending, state: "done" }], index_errors: ["index locked"] },
      },
    });
    const user = userEvent.setup();
    renderWithProviders(<Activity />);
    const panel = await screen.findByRole("region", { name: "Recovery" });
    expect(within(panel).getByText("X/a.pdf")).toBeInTheDocument();
    await user.click(within(panel).getByRole("button", { name: "Run recovery" }));
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent(/moves, renames or deletes no files/);
    expect(posts(calls, "/api/recovery")).toHaveLength(0);
    await user.click(within(dialog).getByRole("button", { name: "Run recovery" }));
    expect(await screen.findByText(/Index error: index locked/)).toBeInTheDocument();
    const [post] = posts(calls, "/api/recovery");
    expect(post.body).toEqual({});
    expect(post.headers["Content-Type"]).toBe("application/json");
  });

  it("a double click on the confirm's Run recovery sends one request", async () => {
    const held = deferred<{ body: unknown }>();
    const calls = api({
      "GET /api/recovery": { body: [row("b5", { id: 9, state: "planned", finished: null })] },
      "POST /api/recovery": () => held.promise,
    });
    const user = userEvent.setup();
    renderWithProviders(<Activity />);
    await user.click(await screen.findByRole("button", { name: "Run recovery" }));
    const run = within(await screen.findByRole("dialog")).getByRole("button", { name: "Run recovery" });
    fireEvent.click(run);
    fireEvent.click(run);
    await act(async () => held.resolve({ body: { entries: [], index_errors: [] } }));
    expect(await screen.findByText("Nothing to recover.")).toBeInTheDocument();
    expect(posts(calls, "/api/recovery")).toHaveLength(1);
  });

  it("an interrupted batch cannot be undone until recovery has run", async () => {
    api({
      "GET /api/activity": {
        body: [batch("b7", [row("b7", { id: 7 }), row("b7", { id: 8, seq: 1, state: "planned", finished: null })], { undoable: false })],
      },
    });
    renderWithProviders(<Activity />);
    const article = await screen.findByRole("article", { name: "Batch b7" });
    expect(within(article).getByText("Interrupted")).toBeInTheDocument();
    const button = within(article).getByRole("button", { name: "Undo" });
    expect(button).toBeDisabled();
    expect(button).toHaveAccessibleDescription("Run recovery first");
  });

  it("shows hidden characters in activity and recovery errors", async () => {
    api({
      "GET /api/activity": { status: 500, body: { error: "db a\u202Eb" } },
      "GET /api/recovery": { body: [row("b5", { id: 9, state: "planned", finished: null })] },
      "POST /api/recovery": { status: 500, body: { error: "rec c\u202Ed" } },
    });
    const user = userEvent.setup();
    renderWithProviders(<Activity />);
    expect(await screen.findByText(/db a⟨U\+202E⟩b/)).toBeInTheDocument();
    await user.click(await screen.findByRole("button", { name: "Run recovery" }));
    await user.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Run recovery" }));
    expect(await screen.findByText(/rec c⟨U\+202E⟩d/)).toBeInTheDocument();
  });

  it("has no recovery panel when nothing is pending", async () => {
    api();
    renderWithProviders(<Activity />);
    await screen.findByRole("article", { name: "Batch b1" });
    expect(screen.queryByRole("region", { name: "Recovery" })).not.toBeInTheDocument();
  });

  it("is a timeline: batches under day headers, Today, Yesterday, then the date", async () => {
    const now = new Date();
    const noonYesterday = new Date(now.getFullYear(), now.getMonth(), now.getDate() - 1, 12).getTime() / 1000;
    const today = batch("t1", [row("t1", { created: Math.floor(now.getTime() / 1000) })]);
    const yesterday = batch("y1", [row("y1", { created: noonYesterday })]);
    const older = batch("o1", [row("o1", { created: 1_750_000_000 })]);
    api({ "GET /api/activity": { body: [today, yesterday, older] } });
    renderWithProviders(<Activity />);
    await screen.findByRole("article", { name: "Batch t1" });
    const days = screen.getAllByRole("heading", { level: 3 }).map((h) => h.textContent);
    expect(days).toEqual(["Today", "Yesterday", expect.stringMatching(/1[45] June 2025/)]);
    expect(within(screen.getByRole("region", { name: "Today" })).getByRole("article", { name: "Batch t1" })).toBeInTheDocument();
    expect(within(screen.getByRole("region", { name: "Yesterday" })).getByRole("article", { name: "Batch y1" })).toBeInTheDocument();
    expect(within(screen.getByRole("region", { name: "Today" })).queryByRole("article", { name: "Batch y1" })).toBeNull();
    // each batch keeps its own Undo
    for (const id of ["t1", "y1", "o1"]) {
      expect(within(batchArticle(id)).getByRole("button", { name: "Undo" })).toBeEnabled();
    }
  });

  it("says what a batch did in its title", async () => {
    api();
    renderWithProviders(<Activity />);
    // an older batch without a label: a sentence derived from its ops, not the op counts
    expect(
      await within(await screen.findByRole("article", { name: "Batch b1" })).findByText("Moved 2026-10-01 lasku.pdf to 10. Financial/Banks"),
    ).toBeInTheDocument();
  });

  it("shows the label the workflow stored as the title", async () => {
    api({ "GET /api/activity": { body: [batch("b1", [row("b1")], { label: "Filed Offer of Näkymä into 80. Misc" })] } });
    renderWithProviders(<Activity />);
    const article = await screen.findByRole("article", { name: "Batch b1" });
    expect(within(article).getByText("Filed Offer of Näkymä into 80. Misc")).toBeInTheDocument();
  });

  it("an automatic batch links the collection it belongs to", async () => {
    api({
      "GET /api/collections": { body: [{ id: 7, name: "2026 Sauna rebuild" }] },
      "GET /api/activity": {
        body: [
          batch("w1", [row("w1", { kind: "symlink", src: "40. House/a.pdf", dst: "##. Ongoing/2026 Sauna rebuild/a.pdf", origin: "workflow" })], {
            origin: "workflow",
            undoable: false,
          }),
        ],
      },
    });
    renderWithProviders(<Activity />);
    const article = await screen.findByRole("article", { name: "Batch w1" });
    const link = await within(article).findByRole("link", { name: "2026 Sauna rebuild" });
    expect(link).toHaveAttribute("href", "/collections/7");
    expect(article.querySelector(".batch-note")).toHaveTextContent(
      "Made automatically after a collection change — change 2026 Sauna rebuild to undo it",
    );
  });

  it("keeps the ops of a batch with many of them behind a fold", async () => {
    const many = [1, 2, 3, 4].map((i) => row("m1", { id: i, seq: i, src: `A/f${i}.pdf`, dst: `B/f${i}.pdf` }));
    api({ "GET /api/activity": { body: [batch("m1", many), batch("m2", [row("m2", { id: 9 })])] } });
    renderWithProviders(<Activity />);
    const article = await screen.findByRole("article", { name: "Batch m1" });
    await expandAll();
    const details = article.querySelector("details")!;
    expect(details).not.toHaveAttribute("open");
    expect(details.querySelector("summary")).toHaveTextContent("4 moves");
    expect(batchArticle("m2").querySelector("details")).toBeNull();
  });

  it("derives titles from the ops of batches without a label", () => {
    const q = (id: number, src: string) => row("q", { id, kind: "quarantine", src, dst: `##. To Delete/${src}` });
    expect(derivedTitle([q(1, "A/2025_Käynti.pdf")])).toBe("Moved 2025_Käynti.pdf to To Delete");
    expect(derivedTitle([q(1, "A/a.pdf"), q(2, "A/b.pdf")])).toBe("Moved 2 files to To Delete");
    expect(derivedTitle([row("r", { kind: "rename", src: "A/old.pdf", dst: "A/new.pdf" })])).toBe("Renamed old.pdf to new.pdf");
    const mk = (id: number, dst: string) => row("r", { id, kind: "mkdir", dst });
    expect(derivedTitle([mk(1, "##. To Delete/A"), mk(2, "##. To Delete/A/B"), q(3, "A/a.pdf")])).toBe("Moved a.pdf to To Delete");
    const link = { src: "Bank/x.pdf", dst: "##. Ongoing/C/x.pdf" };
    expect(
      derivedTitle([row("r", { kind: "unlink_symlink", src: link.dst, dst: "old" }), row("r", { id: 2, kind: "symlink", ...link })]),
    ).toBe("Updated the link to x.pdf");
    expect(derivedTitle([mk(1, "##. Ongoing/C"), row("r", { id: 2, kind: "symlink", ...link })])).toBe("Linked x.pdf");
  });

  it("titles an undo from the batch it reverted, loaded or named by the server", () => {
    const orig = batch("o", [row("o")], { label: "Filed X into Y" });
    const undo = batch("u", [row("u")], { is_undo: true, undo_of: "o" });
    expect(batchTitle(undo, [undo, orig])).toBe("Undo of Filed X into Y");
    expect(batchTitle({ ...undo, undoes_label: "Starred Z" }, [undo])).toBe("Undo of Starred Z");
    expect(batchTitle(undo, [undo])).toBe("Undo of an earlier change");
  });
});

describe("journal rows", () => {
  it("a removed link shows the link's own path (the journal keeps its old target in dst)", async () => {
    api({
      "GET /api/activity": {
        body: [
          batch("w2", [
            row("w2", { id: 1, kind: "unlink_symlink", src: "##. Ongoing/C/a.pdf", dst: "30. Home/a.pdf", drive_id: null }),
            row("w2", { id: 2, seq: 1, kind: "remove_empty_dir", src: "##. Ongoing/C/G", dst: null, drive_id: null }),
            row("w2", { id: 3, seq: 2, kind: "mkdir", src: null, dst: "##. Ongoing/D", drive_id: null }),
          ], { origin: "workflow", undoable: false }),
        ],
      },
    });
    renderWithProviders(<Activity />);
    await expandAll();
    const rows = within(await screen.findByRole("article", { name: "Batch w2" })).getAllByRole("listitem");
    expect(rows[0]).toHaveTextContent(/^Remove link##\. Ongoing\/C\/a\.pdf/);
    expect(rows[0]).toHaveTextContent("(was a link to 30. Home/a.pdf)");
    expect(rows[1]).toHaveTextContent(/^Remove empty folder##\. Ongoing\/C\/G$/);
    expect(rows[2]).toHaveTextContent(/^New folder##\. Ongoing\/D$/);
  });
});

describe("dayLabel", () => {
  const now = new Date(2026, 9, 20, 9, 30); // Tuesday 20 October 2026, local time
  const at = (y: number, m: number, d: number, h = 12) => new Date(y, m, d, h).getTime() / 1000;
  it("names today and yesterday, and dates otherwise", () => {
    expect(dayLabel(at(2026, 9, 20, 0), now)).toBe("Today");
    expect(dayLabel(at(2026, 9, 19, 23), now)).toBe("Yesterday");
    expect(dayLabel(at(2026, 9, 19, 0), now)).toBe("Yesterday");
    expect(dayLabel(at(2026, 9, 18), now)).toBe("Sunday 18 October");
    expect(dayLabel(at(2025, 9, 18), now)).toBe("Saturday 18 October 2025");
  });
});

describe("opsSummary", () => {
  it("counts the ops by kind, in the order they first appear", () => {
    expect(opsSummary(["mkdir", "move", "move", "symlink"])).toBe("1 new folder, 2 moves, 1 link");
    expect(opsSummary([])).toBe("No operations");
  });
});

describe("Activity → AI", () => {
  const LOG = [
    {
      id: 2,
      at: 1_760_000_100,
      task: "ask-archive",
      model: "claude-sonnet-5-5",
      files: ["b1", "b2"],
      input_tokens: 1200,
      output_tokens: 300,
      cost_eur: 0.0123,
      outcome: "ok",
      error: null,
      duration_ms: 12_345,
    },
    {
      id: 1,
      at: 1_760_000_000,
      task: "summarize-document",
      model: "fake:claude-haiku-5-5",
      files: ["d1"],
      input_tokens: 100,
      output_tokens: 50,
      cost_eur: 0,
      outcome: "error",
      error: "did not match‮ the schema",
      duration_ms: 10,
    },
  ];

  function aiApi(status = STATUS_ON) {
    let current = status;
    return api({
      "GET /api/ai/status": () => ({ body: current }),
      "GET /api/ai/log": { body: { rows: LOG } },
      "POST /api/ai/state": (call) => {
        const on = (call.body as { enabled: boolean }).enabled;
        current = { ...current, switched_on: on, enabled: on && current.has_key };
        return { body: current };
      },
    });
  }

  it("lists the AI calls with tokens, cost and outcome, and the month against the budget", async () => {
    const calls = aiApi();
    const user = userEvent.setup();
    renderWithProviders(<Activity />);
    await user.click(screen.getByRole("button", { name: "AI" }));
    const table = await screen.findByRole("table", { name: "AI calls" });
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent("Ask the archive");
    expect(rows[0]).toHaveTextContent("claude-sonnet-5-5");
    expect(rows[0]).toHaveTextContent("1200 in · 300 out");
    expect(rows[0]).toHaveTextContent("0,01 €");
    expect(rows[0]).toHaveTextContent("sent");
    const headers = within(table).getAllByRole("columnheader").map((h) => h.textContent);
    expect(headers).toContain("Duration");
    expect(rows[0]).toHaveTextContent("12,3 s");
    expect(rows[1]).toHaveTextContent("10 ms");
    expect(rows[1]).toHaveTextContent("error");
    expect(rows[1]).toHaveTextContent("did not match⟨U+202E⟩ the schema");
    const month = screen.getByRole("region", { name: "This month" });
    expect(within(month).getByText("1,25 € of 5,00 € this month")).toBeInTheDocument();
    expect(calls.some((c) => c.url.startsWith("/api/ai/log"))).toBe(true);
  });

  it("the switch turns AI off and on (ai-state.json), one change at a time", async () => {
    const calls = aiApi();
    const user = userEvent.setup();
    renderWithProviders(<Activity />);
    await user.click(screen.getByRole("button", { name: "AI" }));
    const toggle = await screen.findByRole("switch", { name: "Use AI" });
    expect(toggle).toBeChecked();
    await user.click(toggle);
    await waitFor(() => expect(posts(calls, "/api/ai/state")).toHaveLength(1));
    expect(posts(calls, "/api/ai/state")[0].body).toEqual({ enabled: false });
    await waitFor(() => expect(toggle).not.toBeChecked());
    expect(screen.getByText(/Off: the AI buttons are hidden/)).toBeInTheDocument();
    await user.click(toggle);
    await waitFor(() => expect(posts(calls, "/api/ai/state")).toHaveLength(2));
    expect(posts(calls, "/api/ai/state")[1].body).toEqual({ enabled: true });
    await waitFor(() => expect(toggle).toBeChecked());
  });

  it("an unreadable ai-state.json reads as off and the switch says why", async () => {
    aiApi({
      ...STATUS_ON,
      enabled: false,
      switched_on: false,
      state_error: "ai-state.json is not valid JSON; AI is off until it is switched on again",
    });
    const user = userEvent.setup();
    renderWithProviders(<Activity />);
    await user.click(screen.getByRole("button", { name: "AI" }));
    expect(await screen.findByRole("switch", { name: "Use AI" })).not.toBeChecked();
    expect(screen.getByText(/ai-state.json is not valid JSON/)).toBeInTheDocument();
  });

  it("without a key the switch says how to add one", async () => {
    aiApi({ ...STATUS_ON, has_key: false, enabled: false });
    const user = userEvent.setup();
    renderWithProviders(<Activity />);
    await user.click(screen.getByRole("button", { name: "AI" }));
    expect(await screen.findByText(/No key yet/)).toHaveTextContent("dam ai --set-key");
  });
});

describe("Activity search and filters", () => {
  const activityCalls = (calls: Call[]) => calls.filter((c) => c.method === "GET" && c.url.startsWith("/api/activity?"));
  const lastParams = (calls: Call[]) => new URL(activityCalls(calls).at(-1)!.url, "http://x").searchParams;
  const where = () => screen.getByLabelText("location").textContent;

  it("searches after a pause, sends the filters to the server and keeps them in the URL", async () => {
    const calls = api();
    const user = userEvent.setup();
    renderWithProviders(<Activity />);
    await screen.findByRole("article", { name: "Batch b1" });
    expect(lastParams(calls).get("limit")).toBe("51"); // one more than a page: tells if there is more
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      await user.type(screen.getByRole("searchbox", { name: "Search the changes" }), "lasku");
      expect(where()).toBe("/activity"); // not yet: debounced
      await act(async () => {
        await vi.advanceTimersByTimeAsync(ACTIVITY_SEARCH_DEBOUNCE_MS + 10);
      });
    } finally {
      vi.useRealTimers();
    }
    await waitFor(() => expect(lastParams(calls).get("q")).toBe("lasku"));
    expect(where()).toBe("/activity?q=lasku");

    await user.selectOptions(screen.getByLabelText("Kind of change"), "rename");
    await user.selectOptions(screen.getByLabelText("Status"), "undoable");
    await user.selectOptions(screen.getByLabelText("Made by"), "cli");
    await user.selectOptions(screen.getByLabelText("When"), "7d");
    await waitFor(() => expect(lastParams(calls).get("origin")).toBe("cli"));
    const sent = lastParams(calls);
    expect([sent.get("q"), sent.get("kind"), sent.get("status")]).toEqual(["lasku", "rename", "undoable"]);
    expect(Number(sent.get("since"))).toBeCloseTo(whenSince("7d")!, -1);
    expect(where()).toBe("/activity?q=lasku&kind=rename&status=undoable&origin=cli&when=7d");
  });

  it("New folders is a kind of change of its own", async () => {
    const calls = api();
    const user = userEvent.setup();
    renderWithProviders(<Activity />);
    await screen.findByRole("article", { name: "Batch b1" });
    await user.selectOptions(screen.getByLabelText("Kind of change"), "New folders");
    await waitFor(() => expect(lastParams(calls).get("kind")).toBe("folders"));
  });

  it("starts from the URL (?file= is a search), clears everything with Clear filters", async () => {
    const calls = api();
    const user = userEvent.setup();
    renderWithProviders(<Activity />, "/activity?file=scan001.pdf&kind=filed");
    await screen.findByRole("article", { name: "Batch b1" });
    expect(lastParams(calls).get("q")).toBe("scan001.pdf");
    expect(lastParams(calls).get("kind")).toBe("filed");
    expect(screen.getByRole("searchbox", { name: "Search the changes" })).toHaveValue("scan001.pdf");
    expect(screen.getByLabelText("Kind of change")).toHaveValue("filed");
    await user.click(screen.getByRole("button", { name: "Clear filters" }));
    await waitFor(() => expect(where()).toBe("/activity"));
    expect(screen.getByRole("searchbox", { name: "Search the changes" })).toHaveValue("");
    await waitFor(() => expect(lastParams(calls).get("q")).toBeNull());
    expect(screen.queryByRole("button", { name: "Clear filters" })).not.toBeInTheDocument();
  });

  it("says when nothing matches", async () => {
    api({ "GET /api/activity": { body: [] } });
    renderWithProviders(<Activity />, "/activity?q=zzz");
    expect(await screen.findByText("No matching changes.")).toBeInTheDocument();
    expect(screen.queryByText("Nothing has been done yet.")).not.toBeInTheDocument();
  });

  it("loads more with the last batch shown as the cursor", async () => {
    const many = Array.from({ length: 51 }, (_, i) => batch(`m${i}`, [row(`m${i}`, { id: 100 + i })]));
    const calls = api({
      "GET /api/activity": (call) =>
        new URL(call.url, "http://x").searchParams.get("before") === "m49"
          ? { body: [batch("older", [row("older", { id: 7 })])] }
          : { body: many },
    });
    const user = userEvent.setup();
    renderWithProviders(<Activity />);
    await screen.findByRole("article", { name: "Batch m0" });
    expect(screen.getAllByRole("article")).toHaveLength(50); // the extra one only says there is more
    await user.click(screen.getByRole("button", { name: "Load more" }));
    await screen.findByRole("article", { name: "Batch older" });
    expect(screen.getAllByRole("article")).toHaveLength(51);
    expect(lastParams(calls).get("before")).toBe("m49");
    expect(screen.queryByRole("button", { name: "Load more" })).not.toBeInTheDocument();
  });

  it("marks the search words in a title, ignoring case and accents", () => {
    const { container } = renderBare(<Highlight text="Filed Lasku Äiti.pdf" words={["lasku", "aiti"]} />);
    expect([...container.querySelectorAll("mark")].map((m) => m.textContent)).toEqual(["Lasku", "Äiti"]);
    expect(container.textContent).toBe("Filed Lasku Äiti.pdf");
  });

  it("date presets start at local midnight, or the start of the year", () => {
    const now = new Date(2026, 9, 22, 15, 30);
    expect(whenSince("today", now)).toBe(new Date(2026, 9, 22).getTime() / 1000);
    expect(whenSince("7d", now)).toBe(new Date(2026, 9, 16).getTime() / 1000);
    expect(whenSince("year", now)).toBe(new Date(2026, 0, 1).getTime() / 1000);
    expect(whenSince("", now)).toBeUndefined();
  });
});

describe("Activity: where each file is now", () => {
  const now = (state: "here" | "moved" | "to_delete" | "missing", path: string | null, extra = {}) => ({
    state,
    path,
    drive_id: path === null ? null : "d1",
    is_dir: false,
    ...extra,
  });
  const WHERE = batch("bw", [
    row("bw", { id: 11, dst: "10. Financial/a.pdf", file_now: now("here", "10. Financial/a.pdf") }),
    row("bw", { id: 12, seq: 1, dst: "10. Financial/b.pdf", file_now: now("moved", "13. Taxes/2026/b renamed.pdf") }),
    row("bw", { id: 13, seq: 2, dst: "10. Financial/c.pdf", file_now: now("to_delete", "##. To Delete/10. Financial/c.pdf") }),
    row("bw", { id: 14, seq: 3, dst: "10. Financial/d.pdf", file_now: now("missing", null) }),
    row("bw", { id: 15, seq: 4, kind: "move", src: "Old", dst: "10. Financial/Old", is_file: false, file_now: now("here", "10. Financial/Old", { is_dir: true, drive_id: "f1" }) }),
  ]);
  const opRow = (path: string) => screen.getByText(path).closest("li") as HTMLElement;

  async function open() {
    api({ "GET /api/activity": { body: [WHERE] } });
    renderWithProviders(<Activity />);
    await screen.findByRole("article", { name: "Batch bw" });
    await expandAll();
    await userEvent.setup().click(screen.getByText("5 moves"));
  }

  it("a file still where the op left it has a Show in Browse link to its folder, selected", async () => {
    await open();
    const user = userEvent.setup();
    const li = opRow("10. Financial/a.pdf");
    expect(li).not.toHaveTextContent(/now|no longer/);
    await user.click(within(li).getByRole("button", { name: "Show in Browse" }));
    expect(screen.getByLabelText("location").textContent).toBe("/browse?path=10.+Financial&select=d1");
  });

  it("a file moved since says where it is now and links there", async () => {
    await open();
    const user = userEvent.setup();
    const li = opRow("10. Financial/b.pdf");
    expect(li).toHaveTextContent("now at 13. Taxes/2026/b renamed.pdf");
    await user.click(within(li).getByRole("button", { name: "Show in Browse" }));
    expect(screen.getByLabelText("location").textContent).toBe("/browse?path=13.+Taxes%2F2026&select=d1");
  });

  it("a file marked for deletion since says so and still links to it", async () => {
    await open();
    const li = opRow("10. Financial/c.pdf");
    expect(li).toHaveTextContent("marked for deletion since, now in ##. To Delete/10. Financial");
    expect(within(li).getByRole("button", { name: "Show in Browse" })).toBeInTheDocument();
  });

  it("a file deleted by hand says it is no longer in the archive, with no link", async () => {
    await open();
    const li = opRow("10. Financial/d.pdf");
    expect(li).toHaveTextContent("no longer in the archive");
    expect(within(li).queryByRole("button", { name: "Show in Browse" })).not.toBeInTheDocument();
  });

  it("a folder opens in Browse itself", async () => {
    await open();
    const user = userEvent.setup();
    await user.click(within(opRow("10. Financial/Old")).getByRole("button", { name: "Show in Browse" }));
    expect(screen.getByLabelText("location").textContent).toBe("/browse?path=10.+Financial%2FOld");
  });

  it("ops that name no file have no link", async () => {
    api();
    renderWithProviders(<Activity />);
    await screen.findByRole("article", { name: "Batch b1" });
    await expandAll();
    expect(within(batchArticle("b1")).queryByRole("button", { name: "Show in Browse" })).not.toBeInTheDocument();
  });
});
