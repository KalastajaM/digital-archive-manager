import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { CollectionChange, CollectionRow, DirEntry, FileLinks, Item, ResolvedOp, SearchHit, TrayDef } from "../api/client";
import { type Call, dataTransfer, deferred, IMPORTANT_REFUSED, mockFetch, quarantineRoute, renderWithProviders, undoButton } from "../test-utils";
import { FILES_MOVED_EVENT } from "../components/MoveTo";
import Browse, { folderCollectRefusal } from "./Browse";

function dir(path: string, drive_id = `id-${path}`): DirEntry {
  return { name: path.slice(path.lastIndexOf("/") + 1), path, is_dir: true, is_link: false, size: null, mtime: 1, drive_id, marks: [] };
}
function file(path: string, drive_id: string, is_link = false): DirEntry {
  return { name: path.slice(path.lastIndexOf("/") + 1), path, is_dir: false, is_link, size: 10, mtime: 1, drive_id, marks: [] };
}

const LISTINGS: Record<string, DirEntry[]> = {
  "": [file("readme.txt", "f0"), dir("10. Financial"), dir("13. Taxes")],
  "10. Financial": [dir("10. Financial/Banks")],
  "##. Important": [file("##. Important/passport.pdf", "p1")],
  "10. Financial/Banks": [
    file("10. Financial/Banks/b.pdf", "f2"),
    file("10. Financial/Banks/a.pdf", "f1"),
    file("10. Financial/Banks/link.pdf", "f3", true),
  ],
};

const browseCalls = (calls: Call[]) => calls.filter((c) => c.url.startsWith("/api/browse"));
const posts = (calls: Call[], url: string) => calls.filter((c) => c.method === "POST" && c.url === url);
const searches = (calls: Call[]) => calls.filter((c) => c.url.startsWith("/api/search"));
const queryOf = (call: Call) => new URL(call.url, "http://x").searchParams;

const QUARANTINE_PLAN: ResolvedOp[] = [
  { kind: "mkdir", src: null, dst: "##. To Delete/10. Financial", drive_id: null, note: "create missing folder" },
  { kind: "mkdir", src: null, dst: "##. To Delete/10. Financial/Banks", drive_id: null, note: "create missing folder" },
  {
    kind: "quarantine",
    src: "10. Financial/Banks/a.pdf",
    dst: "##. To Delete/10. Financial/Banks/a.pdf",
    drive_id: "f1",
    note: null,
  },
];
const batchResult = (overrides: Record<string, unknown> = {}) => ({
  batch_id: "q1",
  dry_run: false,
  done: QUARANTINE_PLAN,
  failed: null,
  error: null,
  index_error: null,
  ...overrides,
});

const NO_LINKS: FileLinks = { items: [], collections: [], note: "" };

function api(extra: Parameters<typeof mockFetch>[0] = {}) {
  return mockFetch({
    "GET /api/browse": (call) => ({ body: LISTINGS[queryOf(call).get("path") ?? ""] ?? [] }),
    "GET /api/activity": { body: [] },
    "GET /api/status": {
      body: { special_folders: { inbox: "##. Organize", ongoing: "##. Ongoing", important: "##. Important", quarantine: "##. To Delete" } },
    },
    "GET /api/files/f1/links": { body: NO_LINKS },
    "GET /api/notes/file/f1": { body: { text: "" } },
    ...extra,
  });
}

function setup(path: string | null, extra: Parameters<typeof mockFetch>[0] = {}) {
  const calls = api(extra);
  const user = userEvent.setup();
  const url = path === null ? "/browse" : `/browse?path=${encodeURIComponent(path)}`;
  renderWithProviders(
    <MemoryRouter initialEntries={[url]}>
      <Routes>
        <Route path="/browse" element={<Browse />} />
      </Routes>
    </MemoryRouter>,
  );
  return { calls, user };
}

const listing = () => screen.getByRole("list", { name: "Folder contents" });
const rowNames = () =>
  within(listing())
    .getAllByRole("listitem")
    .map((li) => li.querySelector(".entry-name")?.textContent);

describe("Browse", () => {
  it("lists folders first, marks symlinks and navigates with the breadcrumb", async () => {
    const { calls, user } = setup("10. Financial/Banks");
    expect(await screen.findByText("a.pdf")).toBeInTheDocument();
    expect(browseCalls(calls)[0].url).toBe("/api/browse?path=10.%20Financial%2FBanks");
    expect(rowNames()).toEqual(["b.pdf", "a.pdf", "link.pdf"]);
    const linkRow = screen.getByText("link.pdf").closest("li")!;
    expect(within(linkRow).getByRole("img", { name: "Symbolic link" })).toBeInTheDocument();

    const crumbs = screen.getByRole("navigation", { name: "Breadcrumb" });
    await user.click(within(crumbs).getByRole("link", { name: "10. Financial" }));
    expect(await screen.findByText("Banks")).toBeInTheDocument();
    expect(browseCalls(calls).at(-1)!.url).toBe("/api/browse?path=10.%20Financial");

    await user.click(within(crumbs).getByRole("link", { name: "Archive" }));
    expect(await screen.findByText("readme.txt")).toBeInTheDocument();
    expect(rowNames()).toEqual(["10. Financial", "13. Taxes", "readme.txt"]);
  });

  it("Backspace goes up, j/k move, Enter opens a folder or previews a file", async () => {
    const { calls, user } = setup("10. Financial/Banks");
    await screen.findByText("a.pdf");
    await user.keyboard("{Backspace}");
    expect(await screen.findByText("Banks")).toBeInTheDocument();
    expect(browseCalls(calls).at(-1)!.url).toBe("/api/browse?path=10.%20Financial");
    await user.keyboard("{Enter}");
    expect(await screen.findByText("a.pdf")).toBeInTheDocument();
    await user.keyboard("jj"); // the first j lands on the first row
    expect(screen.getByRole("button", { name: "a.pdf" }).closest("li")).toHaveAttribute("aria-current", "true");
    await user.keyboard("{ArrowUp}{ArrowDown}{Enter}");
    const preview = await screen.findByRole("region", { name: "Preview" });
    expect(within(preview).getByRole("img", { name: "Page 1" })).toHaveAttribute(
      "src",
      "/api/files/f1/page/1.png?w=900",
    );
  });

  it("shortcuts are ignored while typing in the search box", async () => {
    const { calls, user } = setup("10. Financial/Banks", { "GET /api/search": { body: [] } });
    await screen.findByText("a.pdf");
    const box = screen.getByRole("searchbox", { name: "Search" });
    await user.type(box, "jk{Backspace}");
    expect(box).toHaveValue("j");
    expect(browseCalls(calls)).toHaveLength(1); // Backspace did not go up
    // Out of the box (Esc blurs it) the same keys are shortcuts again.
    await user.clear(box);
    await user.keyboard("{Escape}");
    expect(box).not.toHaveFocus();
    await user.keyboard("j");
    expect((await screen.findByRole("button", { name: "b.pdf" })).closest("li")).toHaveAttribute("aria-current", "true");
    // the highlighted row is the selected file: its detail shows
    expect(within(screen.getByRole("region", { name: "Preview" })).getByRole("heading", { name: "b.pdf" })).toBeInTheDocument();
  });

  it("Enter on a focused checkbox toggles it only; Backspace there does nothing", async () => {
    const { calls, user } = setup("10. Financial/Banks");
    const box = await screen.findByRole("checkbox", { name: "Select a.pdf" });
    box.focus();
    await user.keyboard("{Enter}");
    expect(box).toBeChecked();
    expect(screen.queryByRole("img", { name: "Page 1" })).not.toBeInTheDocument();
    await user.keyboard(" ");
    expect(box).not.toBeChecked();
    await user.keyboard("{Backspace}");
    expect(browseCalls(calls)).toHaveLength(1);
    expect(screen.getByText("a.pdf")).toBeInTheDocument();
  });

  it("shows hidden characters in listing and search errors", async () => {
    const { user } = setup("x", {
      "GET /api/browse": { status: 500, body: { error: "bad a\u202Eb" } },
      "GET /api/search": { status: 400, body: { error: "bad c\u202Ed" } },
    });
    expect(await screen.findByRole("alert")).toHaveTextContent("bad a⟨U+202E⟩b");
    await user.type(screen.getByRole("searchbox", { name: "Search" }), "q");
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("bad c⟨U+202E⟩d"));
  });

  it("clicking a file opens the side preview", async () => {
    const { user } = setup("", { "GET /api/files/f0/text": { body: { text: "Read me", truncated: false } } });
    await user.click(await screen.findByRole("button", { name: "readme.txt" }));
    const preview = screen.getByRole("region", { name: "Preview" });
    expect(await within(preview).findByText("Read me")).toBeInTheDocument();
  });

  it("?select= (Go to target) selects and previews that file once the folder is listed", async () => {
    const calls = api({ "GET /api/files/f1/page/1.png": { body: {} } });
    renderWithProviders(
      <MemoryRouter initialEntries={["/browse?path=10.%20Financial%2FBanks&select=f1"]}>
        <Routes>
          <Route path="/browse" element={<Browse />} />
        </Routes>
      </MemoryRouter>,
    );
    const preview = screen.getByRole("region", { name: "Preview" });
    expect(await within(preview).findByText("10. Financial/Banks/a.pdf")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "a.pdf" }).closest("li")).toHaveAttribute("aria-current", "true");
    expect(browseCalls(calls).length).toBeGreaterThan(0);
  });
});

describe("Search", () => {
  const hit = (overrides: Partial<SearchHit> = {}): SearchHit => ({
    drive_id: "f1",
    path: "10. Financial/Banks/a.pdf",
    name: "a.pdf",
    snippet: "Total of the [invoice] is due",
    rank: -1,
    size: 1000,
    mtime: 1_700_000_000,
    marks: [],
    ...overrides,
  });

  it("is debounced: typing a word sends one request", async () => {
    const { calls, user } = setup("", { "GET /api/search": { body: [hit()] } });
    await screen.findByText("readme.txt");
    await user.type(screen.getByRole("searchbox", { name: "Search" }), "invoice");
    expect(searches(calls)).toHaveLength(0); // nothing before the pause
    await screen.findByText("invoice");
    expect(searches(calls)).toHaveLength(1);
    expect(searches(calls)[0].url).toBe("/api/search?q=invoice&limit=500");
  });

  it("renders matches as <mark> and can search only this folder", async () => {
    const { calls, user } = setup("10. Financial", { "GET /api/search": { body: [hit()] } });
    await screen.findByText("Banks");
    // the scope sits beside the box, so it can be chosen before typing
    const scope = screen.getByRole("group", { name: "Search scope" });
    expect(within(scope).getByRole("button", { name: "Archive" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("searchbox", { name: "Search" })).toHaveAttribute("placeholder", "Search the archive");
    await user.type(screen.getByRole("searchbox", { name: "Search" }), "invoice");
    const results = await screen.findByRole("list", { name: "Search results" });
    expect(queryOf(searches(calls).at(-1)!).get("folder")).toBeNull(); // the whole archive by default
    await user.click(within(scope).getByRole("button", { name: "Folder" }));
    expect(screen.getByRole("searchbox", { name: "Search" })).toHaveAttribute("placeholder", "Search 10. Financial");
    const mark = await within(results).findByText("invoice");
    expect(mark.tagName).toBe("MARK");
    expect(mark.parentElement).toHaveTextContent("Total of the invoice is due");
    await waitFor(() => expect(queryOf(searches(calls).at(-1)!).get("folder")).toBe("10. Financial"));
  });

  it("drops a response that arrives after a newer query's", async () => {
    const first = deferred<{ body: unknown }>();
    const { user } = setup("", {
      "GET /api/search": (call) =>
        queryOf(call).get("q") === "inv"
          ? first.promise
          : { body: [hit({ drive_id: "new", name: "new.pdf", path: "X/new.pdf", snippet: "[invoice]" })] },
    });
    await screen.findByText("readme.txt");
    const box = screen.getByRole("searchbox", { name: "Search" });
    await user.type(box, "inv");
    await new Promise((r) => setTimeout(r, 300));
    await user.type(box, "oice");
    expect(await screen.findByText("new.pdf")).toBeInTheDocument();
    await act(async () =>
      first.resolve({ body: [hit({ drive_id: "old", name: "old.pdf", path: "X/old.pdf" })] }),
    );
    await new Promise((r) => setTimeout(r, 20));
    expect(screen.queryByText("old.pdf")).not.toBeInTheDocument();
    expect(screen.getByText("new.pdf")).toBeInTheDocument();
  });

  it("a new search clears the preview of the previous results", async () => {
    const { user } = setup("", {
      "GET /api/search": (call) =>
        queryOf(call).get("q") === "tiliote"
          ? { body: [hit()] }
          : { body: [hit({ drive_id: "f2", path: "10. Financial/Banks/b.pdf", name: "b.pdf" })] },
    });
    await screen.findByText("readme.txt");
    const box = screen.getByRole("searchbox", { name: "Search" });
    await user.type(box, "tiliote");
    await user.click(await screen.findByRole("button", { name: /^a\.pdf/ }));
    const preview = screen.getByRole("region", { name: "Preview" });
    expect(within(preview).getByText("10. Financial/Banks/a.pdf")).toBeInTheDocument();
    await user.clear(box);
    await user.type(box, "passport");
    await screen.findByRole("button", { name: /^b\.pdf/ });
    expect(within(preview).queryByText("10. Financial/Banks/a.pdf")).not.toBeInTheDocument();
    expect(within(preview).getByText("No file selected")).toBeInTheDocument();
  });

  it("shows HTML-looking names and snippets as text", async () => {
    const evil = "<img src=x onerror=alert(1)>.pdf";
    const { user } = setup("", {
      "GET /api/search": { body: [hit({ name: evil, path: `X/${evil}`, snippet: "<b>[bold]</b> ‮x" })] },
    });
    await screen.findByText("readme.txt");
    await user.type(screen.getByRole("searchbox", { name: "Search" }), "bold");
    expect(await screen.findByText(evil)).toBeInTheDocument();
    expect(document.querySelector("img[src=x]")).toBeNull();
    expect(document.querySelector("b")).toBeNull();
    expect(screen.getByText("bold").tagName).toBe("MARK");
    expect(screen.getByText(/⟨U\+202E⟩x/)).toBeInTheDocument();
  });
});

describe("Search results' columns", () => {
  const hits: SearchHit[] = [
    { drive_id: "b", path: "20. Home/b.pdf", name: "b.pdf", snippet: "b.pdf", rank: -3, size: 10, mtime: 1_600_000_000, marks: [] },
    { drive_id: "a", path: "10. Financial/a.pdf", name: "a.pdf", snippet: "a.pdf", rank: -2, size: 300, mtime: 1_700_000_000, marks: [] },
    { drive_id: "c", path: "30. Car/c.pdf", name: "c.pdf", snippet: "c.pdf", rank: -1, size: null, mtime: null, marks: [] },
  ];
  const order = () =>
    within(screen.getByRole("list", { name: "Search results" }))
      .getAllByRole("checkbox")
      .map((c) => c.getAttribute("aria-label")!.replace("Select ", ""));

  it("show folder, date and size, sort by a column and go back to best match", async () => {
    const { user } = setup("", { "GET /api/search": { body: hits } });
    await screen.findByText("readme.txt");
    await user.type(screen.getByRole("searchbox", { name: "Search" }), "pdf");
    await screen.findByRole("list", { name: "Search results" });
    expect(order()).toEqual(["b.pdf", "a.pdf", "c.pdf"]); // best match first
    const head = screen.getByRole("group", { name: "Sort by" });
    expect(screen.getByText("10. Financial")).toBeInTheDocument(); // the folder column
    const size = within(head).getByRole("button", { name: "Sort by size" });
    await user.click(size);
    expect(order()).toEqual(["a.pdf", "b.pdf", "c.pdf"]); // largest first, no size last
    await user.click(within(head).getByRole("button", { name: /^Sort by size/ }));
    expect(order()).toEqual(["b.pdf", "a.pdf", "c.pdf"]);
    await user.click(within(head).getByRole("button", { name: /^Sort by size/ }));
    expect(order()).toEqual(["b.pdf", "a.pdf", "c.pdf"]); // best match again
    expect(within(head).getByRole("button", { name: "Sort by size" })).toHaveAttribute("aria-pressed", "false");
    await user.click(within(head).getByRole("button", { name: "Sort by folder" }));
    expect(order()).toEqual(["a.pdf", "b.pdf", "c.pdf"]);
    await user.click(within(head).getByRole("button", { name: /^Sort by date/ }));
    expect(order()).toEqual(["a.pdf", "b.pdf", "c.pdf"]); // newest first
  });
});

describe("Mark for deletion", () => {
  async function checkA(extra: Parameters<typeof mockFetch>[0]) {
    const env = setup("10. Financial/Banks", extra);
    await env.user.click(await screen.findByRole("checkbox", { name: "Select a.pdf" }));
    return env;
  }

  it("previews with a dry run, then applies exactly those ids; Undo goes through the confirm", async () => {
    const { calls, user } = await checkA({
      "POST /api/quarantine": (call) =>
        (call.body as { dry_run: boolean }).dry_run
          ? { body: batchResult({ batch_id: "dry", dry_run: true }) }
          : { body: batchResult() },
      "POST /api/activity/q1/undo/preview": {
        body: [{ kind: "move", src: "##. To Delete/10. Financial/Banks/a.pdf", dst: "10. Financial/Banks/a.pdf", drive_id: "f1", note: null }],
      },
      "POST /api/activity/q1/undo": {
        body: { batch_id: "u1", dry_run: false, done: [], failed: null, error: null, index_error: null },
      },
    });
    await user.click(screen.getByRole("button", { name: "Move to To Delete" }));
    const dialog = await screen.findByRole("dialog");
    expect(posts(calls, "/api/quarantine")).toHaveLength(1);
    expect(posts(calls, "/api/quarantine")[0].body).toEqual({ drive_ids: ["f1"], dry_run: true });
    expect(dialog).toHaveTextContent("10. Financial/Banks/a.pdf → ##. To Delete/10. Financial/Banks/a.pdf");
    expect(dialog).toHaveTextContent(/Nothing is deleted/);

    await user.click(within(dialog).getByRole("button", { name: "Move to To Delete" }));
    await waitFor(() => expect(posts(calls, "/api/quarantine")).toHaveLength(2));
    const apply = posts(calls, "/api/quarantine")[1];
    expect(apply.body).toEqual({ drive_ids: ["f1"], dry_run: false });
    expect(apply.headers["Content-Type"]).toBe("application/json");
    expect(apply.credentials).toBe("same-origin");
    expect(screen.queryByText(/other than previewed/)).not.toBeInTheDocument();

    await user.click(await screen.findByRole("button", { name: "Undo" }));
    const undo = await screen.findByRole("dialog");
    expect(await within(undo).findByText("Undoing will:")).toBeInTheDocument();
    expect(undo).toHaveTextContent("##. To Delete/10. Financial/Banks/a.pdf → 10. Financial/Banks/a.pdf");
    expect(posts(calls, "/api/activity/q1/undo")).toHaveLength(0);
    await user.click(await undoButton(undo));
    await waitFor(() => expect(posts(calls, "/api/activity/q1/undo")).toHaveLength(1));
  });

  it.each([
    ["a 400", { status: 400, body: { error: "invalid request: 'X/x.pdf' is protected and cannot be quarantined" } }, "in a protected folder"],
    ["a failed op", { body: batchResult({ dry_run: true, done: [], failed: QUARANTINE_PLAN[2], error: "guard" }) }, "guard"],
  ])("a preview with %s shows the error and offers no confirm", async (_label, reply, text) => {
    const { calls, user } = await checkA({ "POST /api/quarantine": reply });
    await user.click(screen.getByRole("button", { name: "Move to To Delete" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(text);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(posts(calls, "/api/quarantine")).toHaveLength(1);
  });

  it("drops a preview when the selection changed while it was running", async () => {
    const held = deferred<{ body: unknown }>();
    const { calls, user } = await checkA({ "POST /api/quarantine": () => held.promise });
    await user.click(screen.getByRole("button", { name: "Move to To Delete" }));
    await user.click(screen.getByRole("checkbox", { name: "Select b.pdf" }));
    await act(async () => held.resolve({ body: batchResult({ dry_run: true }) }));
    expect(await screen.findByText("Selection changed — press Move to To Delete again")).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(posts(calls, "/api/quarantine")).toHaveLength(1);
  });

  it("two clicks in one event batch send one dry run, and one apply", async () => {
    const held = deferred<{ body: unknown }>();
    const { calls } = await checkA({
      "POST /api/quarantine": (call) =>
        (call.body as { dry_run: boolean }).dry_run ? { body: batchResult({ dry_run: true }) } : held.promise,
    });
    const mark = screen.getByRole("button", { name: "Move to To Delete" });
    act(() => {
      mark.click();
      mark.click(); // the button cannot have re-rendered disabled yet
    });
    const apply = within(await screen.findByRole("dialog")).getByRole("button", { name: "Move to To Delete" });
    act(() => {
      apply.click();
      apply.click();
    });
    await act(async () => held.resolve({ body: batchResult() }));
    await screen.findByRole("button", { name: "Undo" });
    expect(posts(calls, "/api/quarantine").map((c) => c.body)).toEqual([
      { drive_ids: ["f1"], dry_run: true },
      { drive_ids: ["f1"], dry_run: false },
    ]);
  });

  it("takes the current row when nothing is ticked, like Move to…", async () => {
    const { calls, user } = setup("10. Financial/Banks", {
      "POST /api/quarantine": { body: batchResult({ batch_id: "dry", dry_run: true }) },
    });
    const row = await screen.findByRole("button", { name: "a.pdf" });
    expect(screen.getByRole("button", { name: "Move to To Delete" })).toBeDisabled();
    await user.click(row);
    await user.click(screen.getByRole("button", { name: "Move to To Delete" }));
    await screen.findByRole("dialog");
    expect(posts(calls, "/api/quarantine")[0].body).toEqual({ drive_ids: ["f1"], dry_run: true });
  });

  it("refuses protected files up front, with the reason", async () => {
    const { calls, user } = setup("##. Important");
    await user.click(await screen.findByRole("checkbox", { name: "Select passport.pdf" }));
    const mark = screen.getByRole("button", { name: "Move to To Delete" });
    expect(mark).toBeDisabled();
    expect(mark.parentElement).toHaveAttribute("data-tip", "Files in ##. Important are protected");
    expect(posts(calls, "/api/quarantine")).toHaveLength(0);
  });

  it("a dry run that plans nothing says so and offers no confirm", async () => {
    const { calls, user } = await checkA({
      "POST /api/quarantine": { body: batchResult({ dry_run: true, done: [] }) },
    });
    await user.click(screen.getByRole("button", { name: "Move to To Delete" }));
    expect(await screen.findByText(/Nothing to mark/)).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(posts(calls, "/api/quarantine")).toHaveLength(1);
  });

  it("a preview error for a selection that changed meanwhile says the selection changed", async () => {
    const held = deferred<{ status: number; body: unknown }>();
    const { user } = await checkA({ "POST /api/quarantine": () => held.promise });
    await user.click(screen.getByRole("button", { name: "Move to To Delete" }));
    await user.click(screen.getByRole("checkbox", { name: "Select b.pdf" }));
    await act(async () => held.resolve({ status: 400, body: { error: "boom" } }));
    expect(await screen.findByText("Selection changed — press Move to To Delete again")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("warns when a file landed somewhere other than previewed", async () => {
    const { user } = await checkA({
      "POST /api/quarantine": (call) =>
        (call.body as { dry_run: boolean }).dry_run
          ? { body: batchResult({ dry_run: true }) }
          : {
              body: batchResult({
                done: [{ ...QUARANTINE_PLAN[2], dst: "##. To Delete/10. Financial/Banks/a_2.pdf" }],
              }),
            },
    });
    await user.click(screen.getByRole("button", { name: "Move to To Delete" }));
    await user.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Move to To Delete" }));
    expect(
      await screen.findByText(/other than previewed: ##\. To Delete\/10\. Financial\/Banks\/a_2\.pdf/),
    ).toBeInTheDocument();
  });
});

const TO_PAY: TrayDef = {
  id: "to-pay",
  name: "To pay",
  order: 1,
  item_title: "{name}",
  fields: {
    due_date: { type: "date", required: true, copy: false },
    amount: { type: "money", required: false, copy: true },
    autopay: { type: "checkbox", required: false, copy: false },
  },
  date_field: "due_date",
  done: { label: "Mark paid", fields: {} },
};
const TO_READ: TrayDef = { ...TO_PAY, id: "to-read", name: "To read", order: 2, fields: {}, date_field: null };

const ITEM: Item = {
  id: 42,
  tray_id: "to-pay",
  title: "Northpower‮ bill",
  fields: {},
  date: null,
  state: "open",
  created: 1,
  done_at: null,
  done_fields: null,
  files: ["f1"],
  created_by_batch: null,
  missing_required: [],
  invalid_fields: [],
  tray_name: "To pay",
  tray_removed: false,
};
const SAUNA: CollectionRow = {
  id: 7,
  name: "Sauna",
  state: "open",
  created: 1,
  closed_at: null,
  publish: { ongoing: true },
  ongoing_rel: null,
  members: [],
  ongoing_status: null,
  summary: "",
  groups: [],
  parent_id: null,
  path: ["Sauna"],
  kind: null,
  position: 0,
  files: 0,
  open_checks: 0,
};
const added = (overrides: Partial<CollectionChange> = {}): CollectionChange => ({
  collection: SAUNA,
  batch: null,
  problems: [],
  ongoing_status: null,
  ...overrides,
});

describe("Selected file", () => {
  const openFile = async (user: ReturnType<typeof userEvent.setup>) => {
    await user.click(await screen.findByText("a.pdf"));
    return screen.findByRole("region", { name: "Preview" });
  };

  it("the preview has the name, folder, tags and ★ / ! inline, and no Edit details…", async () => {
    const { user } = setup("10. Financial/Banks", {
      "GET /api/files/f1": {
        body: {
          record: { drive_id: "f1", path: "10. Financial/Banks/a.pdf", name: "a.pdf", ext: "pdf", is_dir: false, is_link: false, marks: [] },
          tags: ["bank"],
          link_target_id: null,
          link_target_path: null,
          link_target_inside: false,
        },
      },
      "GET /api/files/f1/suggestions": {
        body: { name: null, name_source: null, folder: null, folder_source: null, tags: [], tag_sources: {}, sources: [] },
      },
    });
    const preview = await openFile(user);
    expect(within(preview).queryByRole("button", { name: "Edit details…" })).not.toBeInTheDocument();
    expect(within(preview).getByRole("heading", { name: "a.pdf" })).toBeInTheDocument();
    expect(within(preview).getByRole("button", { name: /^Rename/ })).toBeEnabled();
    expect(within(preview).getByRole("button", { name: "Move file to…" })).toBeEnabled();
    // the toggles sit in the preview's toolbar, with zoom and Open
    const tools = within(preview).getByRole("group", { name: "Zoom" });
    expect(within(tools).getByRole("button", { name: "Star" })).toBeInTheDocument();
    expect(within(tools).getByRole("button", { name: "Mark Important" })).toBeInTheDocument();
    expect(await within(preview).findByRole("button", { name: "Remove tag bank" })).toBeInTheDocument();
  });

  it("a link's name, folder and tags are disabled, saying why", async () => {
    const { user } = setup("10. Financial/Banks");
    await user.click(await screen.findByText("link.pdf"));
    const preview = await screen.findByRole("region", { name: "Preview" });
    const rename = within(preview).getByRole("button", { name: /^Rename/ });
    expect(rename).toBeDisabled();
    expect(rename).toHaveAttribute("title", "Links cannot be renamed or moved");
    expect(within(preview).getByRole("button", { name: "Move file to…" })).toBeDisabled();
    expect(within(preview).getByRole("combobox", { name: "Add a tag to link.pdf" })).toBeDisabled();
  });

  it("badges under the file name link to its open items and collections", async () => {
    const { user } = setup("10. Financial/Banks", {
      "GET /api/files/f1/links": {
        body: { items: [ITEM], collections: [SAUNA, { ...SAUNA, id: 8, name: "Old", state: "closed" }], note: "" },
      },
    });
    const preview = await openFile(user);
    const badges = await within(preview).findByRole("list", { name: "In trays and collections" });
    const links = within(badges).getAllByRole("link");
    expect(links.map((a) => [a.textContent, a.getAttribute("href")])).toEqual([
      ["To pay: Northpower⟨U+202E⟩ bill", "/trays/to-pay?item=42"],
      ["Sauna", "/collections/7"],
      ["Old (closed)", "/collections/8?state=closed"],
    ]);
  });

  it("a folder on the cursor shows its own panel: its path, its collections and Add to collection", async () => {
    const { calls, user } = setup("10. Financial", {
      "GET /api/files/id-10.%20Financial%2FBanks/links": { body: { items: [], collections: [SAUNA], note: "" } },
      "POST /api/collections/7/members": { body: { collection: SAUNA, batch: null, problems: [] } },
    });
    await user.click(await screen.findByRole("button", { name: "Banks" })); // opens the folder
    await screen.findByText("a.pdf");
    await user.keyboard("{Backspace}"); // back: the cursor is on Banks
    const preview = await screen.findByRole("region", { name: "Preview" });
    expect(await within(preview).findByRole("heading", { level: 2, name: "Banks" })).toBeInTheDocument();
    expect(preview.querySelector(".current-path")).toHaveTextContent("10. Financial/Banks");
    expect(within(preview).getByText(/brings everything in it/)).toBeInTheDocument();
    expect(await within(preview).findByRole("link", { name: "Sauna" })).toBeInTheDocument();
    expect(within(preview).queryByRole("button", { name: "Put in tray" })).toBeNull(); // a folder: collections only
    await user.click(within(preview).getByRole("button", { name: "Add to collection…" }));
    expect(within(preview).getByRole("region", { name: "Add to collection" })).toBeInTheDocument();
    expect(calls.filter((c) => c.method === "POST")).toHaveLength(0); // nothing until a collection is picked
  });

  it("folders in the app's own areas cannot be added to a collection", () => {
    const special = { quarantine: "##. To Delete", ongoing: "##. Ongoing", important: "##. Important" };
    expect(folderCollectRefusal("10. Financial/Banks", special)).toBeNull();
    expect(folderCollectRefusal("##. To Delete/old", special)).toBe("Folders in ##. To Delete can't be added to a collection");
    expect(folderCollectRefusal("##. ongoing/Sauna", special)).toBe("Folders in ##. Ongoing can't be added to a collection");
    expect(folderCollectRefusal("##. Important", special)).toBe("Folders in ##. Important can't be added to a collection");
  });

  it("a × on a collection badge takes the file out of that collection; Undo adds it back into its group", async () => {
    const member = { drive_id: "f1", path: "10. Financial/Banks/a.pdf", is_dir: false, missing: false, quarantined: false, group_id: 3, marks: [] };
    const direct = { ...SAUNA, members: [member] };
    const { calls, user } = setup("10. Financial/Banks", {
      "GET /api/files/f1/links": {
        body: {
          items: [],
          collections: [
            direct,
            { ...SAUNA, id: 8, name: "Old", state: "closed", members: [member] }, // closed: no ×
            { ...SAUNA, id: 9, name: "Houses", members: [{ ...member, drive_id: "d1", is_dir: true }] }, // through a folder: no ×
            { ...SAUNA, id: 10, name: "Ongoing", kind: "starred", members: [member] }, // built in: its ★ toggle does it
          ],
          note: "",
        },
      },
      "POST /api/collections/7/members/remove": { body: { collection: SAUNA, batch: null, problems: [] } },
      "POST /api/collections/7/members": { body: { collection: direct, batch: null, problems: [] } },
      "POST /api/collections/7/members/group": { body: { collection: direct, batch: null, problems: [] } },
    });
    const preview = await openFile(user);
    const badges = await within(preview).findByRole("list", { name: "In trays and collections" });
    expect(within(badges).getAllByRole("button").map((b) => b.getAttribute("aria-label"))).toEqual(["Remove from Sauna"]);
    await user.click(within(badges).getByRole("button", { name: "Remove from Sauna" }));
    await waitFor(() => expect(posts(calls, "/api/collections/7/members/remove")).toHaveLength(1));
    expect(posts(calls, "/api/collections/7/members/remove")[0].body).toEqual({ drive_id: "f1" });
    await user.click(await screen.findByRole("button", { name: "Undo" }));
    await waitFor(() => expect(posts(calls, "/api/collections/7/members")).toHaveLength(1));
    expect(posts(calls, "/api/collections/7/members")[0].body).toEqual({ drive_ids: ["f1"] });
    await waitFor(() => expect(posts(calls, "/api/collections/7/members/group")).toHaveLength(1));
    expect(posts(calls, "/api/collections/7/members/group")[0].body).toEqual({ drive_ids: ["f1"], group_id: 3 });
  });

  it("Put in tray is a menu of the trays: one pick puts the file in it", async () => {
    const { calls, user } = setup("10. Financial/Banks", {
      "GET /api/trays": { body: { trays: [TO_PAY, TO_READ], errors: [] } },
      "POST /api/items/quick": { body: { created: [ITEM], skipped: [] } },
    });
    const preview = await openFile(user);
    await user.click(within(preview).getByRole("button", { name: "Put in tray" }));
    const menu = await screen.findByRole("menu", { name: "Put in tray" });
    await within(menu).findByRole("menuitemcheckbox", { name: "To read" });
    expect(within(menu).getAllByRole("menuitemcheckbox").map((x) => x.textContent?.replace("✓", "").trim())).toEqual(["To pay", "To read"]);
    await user.click(within(menu).getByRole("menuitemcheckbox", { name: "To pay" }));
    await waitFor(() => expect(posts(calls, "/api/items/quick")).toHaveLength(1));
    expect(posts(calls, "/api/items/quick")[0].body).toEqual({ tray: "to-pay", drive_ids: ["f1"] });
    expect(await screen.findByText("Put in To pay: Northpower⟨U+202E⟩ bill")).toBeInTheDocument();
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });

  it("digit keys keep zooming the preview (no tray shortcuts here)", async () => {
    const { calls, user } = setup("10. Financial/Banks", {
      "GET /api/trays": { body: { trays: [TO_PAY, TO_READ], errors: [] } },
    });
    const preview = await openFile(user);
    await user.keyboard("2");
    await user.keyboard("+");
    expect(within(preview).getByTestId("zoom-level")).toHaveTextContent("150%");
    await user.keyboard("0"); // fit, as before
    expect(within(preview).getByTestId("zoom-level")).toHaveTextContent("Fit");
    expect(posts(calls, "/api/items/quick")).toHaveLength(0);
  });

  it("a refused put says so in a toast", async () => {
    const { user } = setup("10. Financial/Banks", {
      "GET /api/trays": { body: { trays: [TO_PAY], errors: [] } },
      "POST /api/items/quick": { status: 400, body: { error: "not a ‮number" } },
    });
    const preview = await openFile(user);
    await user.click(within(preview).getByRole("button", { name: "Put in tray" }));
    await user.click(await screen.findByRole("menuitemcheckbox", { name: "To pay" }));
    expect(await screen.findByText(/Could not put .* in To pay: .*not a ⟨U\+202E⟩number/)).toBeInTheDocument();
  });

  it("Add to collection adds the file to an existing one", async () => {
    const { calls, user } = setup("10. Financial/Banks", {
      "GET /api/collections": { body: [SAUNA] },
      "POST /api/collections/7/members": {
        body: added({
          batch: {
            batch_id: "s1",
            dry_run: false,
            done: [{ kind: "symlink", src: null, dst: "##. Ongoing/Sauna/a‮.pdf", drive_id: null, note: null }],
            failed: null,
            error: null,
            index_error: null,
          },
          problems: ["plan refused: ‮x"],
        }),
      },
    });
    const preview = await openFile(user);
    await user.click(within(preview).getByRole("button", { name: "Add to collection…" }));
    const form = within(preview).getByRole("region", { name: "Add to collection" });
    await user.type(within(form).getByRole("combobox", { name: "Collection" }), "sau");
    await user.click(await within(form).findByRole("option", { name: "Sauna" }));
    await waitFor(() => expect(posts(calls, "/api/collections/7/members")).toHaveLength(1));
    expect(posts(calls, "/api/collections/7/members")[0].body).toEqual({ drive_ids: ["f1"] });
    expect(posts(calls, "/api/collections")).toHaveLength(0);
    expect(await screen.findByText("Added to Sauna, but: plan refused: ⟨U+202E⟩x")).toBeInTheDocument();
    // the batch that ran, as returned, under the actions
    const shown = within(preview).getByRole("region", { name: "What changed in ##. Ongoing" });
    expect(shown.querySelector(".plan-op")).toHaveTextContent("Link##. Ongoing/Sauna/a⟨U+202E⟩.pdf");
    expect(shown).toHaveTextContent("plan refused: ⟨U+202E⟩x");
  });

  it("Add to collection creates a new one first", async () => {
    const { calls, user } = setup("10. Financial/Banks", {
      "GET /api/collections": { body: [SAUNA] },
      "POST /api/collections": { body: { ...SAUNA, id: 9, name: "Car" } },
      "POST /api/collections/9/members": { body: added({ collection: { ...SAUNA, id: 9, name: "Car" } }) },
    });
    const preview = await openFile(user);
    await user.click(within(preview).getByRole("button", { name: "Add to collection…" }));
    const form = within(preview).getByRole("region", { name: "Add to collection" });
    await user.type(within(form).getByRole("combobox", { name: "Collection" }), "Car{Enter}");
    await waitFor(() => expect(posts(calls, "/api/collections/9/members")).toHaveLength(1));
    expect(posts(calls, "/api/collections").map((c) => c.body)).toEqual([{ name: "Car" }]);
    expect(await screen.findByText("Added to Car")).toBeInTheDocument();
    const shown = within(preview).getByRole("region", { name: "What changed in ##. Ongoing" });
    expect(shown).toHaveTextContent("Nothing needed to change in ##. Ongoing.");
  });

  it("edits the file's own note (saved on blur)", async () => {
    const { calls, user } = setup("10. Financial/Banks", {
      "GET /api/notes/file/f1": { body: { text: "old" } },
      "PUT /api/notes/file/f1": { body: { text: "old and new" } },
    });
    const preview = await openFile(user);
    const note = within(preview).getByRole("textbox", { name: "Note on this file" });
    await waitFor(() => expect(note).toHaveValue("old"));
    await user.type(note, " and new");
    await user.tab();
    await waitFor(() => expect(calls.filter((c) => c.method === "PUT")).toHaveLength(1));
    expect(calls.find((c) => c.method === "PUT")!.body).toEqual({ text: "old and new" });
  });

  it("list shortcuts still work with the file panel open", async () => {
    const { user } = setup("10. Financial/Banks", {
      "GET /api/files/f2/links": { body: NO_LINKS },
      "GET /api/notes/file/f2": { body: { text: "" } },
    });
    const preview = await openFile(user);
    expect(within(preview).getByRole("button", { name: "Put in tray" })).toBeInTheDocument();
    await user.keyboard("k{Enter}");
    expect(await within(preview).findByText("10. Financial/Banks/b.pdf")).toBeInTheDocument();
  });
});

// -- Task 11: two panes, Move to…, drag and drop -------------------------------------

const MOVE_PLAN: ResolvedOp[] = [
  { kind: "move", src: "readme.txt", dst: "13. Taxes/readme.txt", drive_id: "f0", note: null },
];
const moveResult = (overrides: Record<string, unknown> = {}) => ({
  batch_id: "m1",
  dry_run: false,
  done: MOVE_PLAN,
  failed: null,
  error: null,
  index_error: null,
  unchanged: [],
  folder: "13. Taxes",
  ...overrides,
});
const UNDONE = { batch_id: "u1", dry_run: false, done: [], failed: null, error: null, index_error: null };

const pane = (name: "Left pane" | "Right pane") => screen.getByRole("region", { name });
const rowOf = (scope: HTMLElement, name: string) => within(scope).getByText(name).closest("li")!;
function dragFrom(row: HTMLElement) {
  const dt = dataTransfer();
  fireEvent.dragStart(row, { dataTransfer: dt });
  return dt;
}
function dropOn(target: HTMLElement, dt: ReturnType<typeof dataTransfer>) {
  fireEvent.dragEnter(target, { dataTransfer: dt });
  fireEvent.dragOver(target, { dataTransfer: dt });
  return fireEvent.drop(target, { dataTransfer: dt });
}

describe("Back to inbox", () => {
  const BACK: ResolvedOp[] = [
    { kind: "move", src: "10. Financial/Banks/a.pdf", dst: "##. Organize/a.pdf", drive_id: "f1", note: null },
  ];
  const openFile = async (user: ReturnType<typeof userEvent.setup>, name = "a.pdf") => {
    await user.click(await screen.findByText(name));
    return screen.findByRole("region", { name: "Preview" });
  };

  it("moves the previewed file into ##. Organize through the confirm, with Undo", async () => {
    const { calls, user } = setup("10. Financial/Banks", {
      "POST /api/browse/move/preview": { body: BACK },
      "POST /api/browse/move": { body: moveResult({ done: BACK, folder: "##. Organize" }) },
      "POST /api/activity/m1/undo/preview": {
        body: [{ kind: "move", src: "##. Organize/a.pdf", dst: "10. Financial/Banks/a.pdf", drive_id: "f1", note: null }],
      },
      "POST /api/activity/m1/undo": { body: UNDONE },
    });
    const preview = await openFile(user);
    const back = await within(preview).findByRole("button", { name: "Back to inbox" });
    await waitFor(() => expect(back).toBeEnabled());
    await user.click(back);
    const dialog = await screen.findByRole("dialog", { name: "Move 1 file to ##. Organize?" });
    expect(posts(calls, "/api/browse/move/preview").map((c) => c.body)).toEqual([
      { drive_ids: ["f1"], folder: "##. Organize" },
    ]);
    expect(posts(calls, "/api/browse/move")).toHaveLength(0);
    await user.click(within(dialog).getByRole("button", { name: "Move" }));
    await waitFor(() => expect(posts(calls, "/api/browse/move")).toHaveLength(1));
    expect(await screen.findByText("Moved a.pdf to ##. Organize")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Undo" }));
    const undo = await screen.findByRole("dialog", { name: "Undo these changes?" });
    await user.click(await undoButton(undo));
    await waitFor(() => expect(posts(calls, "/api/activity/m1/undo")).toHaveLength(1));
  });

  it("a move made elsewhere (the sidebar Inbox) takes the file out of the preview and the selection", async () => {
    // (the listing itself reloads with the move's query refresh; this is what Browse holds)
    const { user } = setup("10. Financial/Banks");
    await openFile(user);
    const box = within(rowOf(listing(), "a.pdf")).getByRole("checkbox");
    await user.click(box);
    expect(box).toBeChecked();
    act(() => {
      window.dispatchEvent(new CustomEvent(FILES_MOVED_EVENT, { detail: { ids: ["f1"] } }));
    });
    expect(await screen.findByText("No file selected")).toBeInTheDocument();
    expect(within(rowOf(listing(), "a.pdf")).getByRole("checkbox")).not.toBeChecked();
  });

  it("the moved file leaves the preview, also when its ops carry no Drive id", async () => {
    const noId = BACK.map((op) => ({ ...op, drive_id: null }));
    const { user } = setup("10. Financial/Banks", {
      "POST /api/browse/move/preview": { body: noId },
      "POST /api/browse/move": { body: moveResult({ done: noId, folder: "##. Organize" }) },
    });
    const preview = await openFile(user);
    const back = await within(preview).findByRole("button", { name: "Back to inbox" });
    await waitFor(() => expect(back).toBeEnabled());
    await user.click(back);
    const dialog = await screen.findByRole("dialog", { name: "Move 1 file to ##. Organize?" });
    await user.click(within(dialog).getByRole("button", { name: "Move" }));
    expect(await screen.findByText("No file selected")).toBeInTheDocument();
  });

  it("a file already in ##. Organize is refused: the button says why", async () => {
    LISTINGS["##. Organize"] = [file("##. Organize/scan.pdf", "f1")];
    try {
      const { calls, user } = setup("##. Organize");
      const preview = await openFile(user, "scan.pdf");
      const back = await within(preview).findByRole("button", { name: "Back to inbox" });
      await waitFor(() => expect(back.closest("[data-tip]")).toHaveAttribute("data-tip", "Already in the inbox"));
      expect(within(preview).getByRole("button", { name: "Back to inbox" })).toBeDisabled();
      expect(posts(calls, "/api/browse/move/preview")).toHaveLength(0);
    } finally {
      delete LISTINGS["##. Organize"];
    }
  });

  it("a Browse row dragged onto a drop target carries its path (for the Inbox refusal)", async () => {
    const { draggedPaths } = await import("../dnd");
    setup("10. Financial/Banks");
    await screen.findByText("a.pdf");
    const dt = dataTransfer();
    fireEvent.dragStart(within(listing()).getByText("a.pdf").closest("li")!, { dataTransfer: dt });
    expect(draggedPaths()).toEqual(["10. Financial/Banks/a.pdf"]);
    document.dispatchEvent(new Event("dragend"));
  });
});

describe("Drag and drop in Browse", () => {
  afterEach(() => {
    document.dispatchEvent(new Event("dragend"));
    try {
      localStorage.clear();
    } catch {
      // ignore
    }
  });

  it("files drag as files; a folder drags only as a folder (for a collection), never as files", async () => {
    setup("");
    const folder = rowOf(await screen.findByRole("list", { name: "Folder contents" }), "13. Taxes");
    expect(folder).toHaveAttribute("draggable", "true");
    const dt = dataTransfer();
    fireEvent.dragStart(folder, { dataTransfer: dt });
    expect(dt.types).toEqual(["application/x-dam-folder"]);
    const file = rowOf(listing(), "readme.txt");
    expect(file).toHaveAttribute("draggable", "true");
    expect(JSON.parse(dragFrom(file).data["application/x-dam-files"])).toEqual({ ids: ["f0"] });
  });

  it("dropping on a folder previews, confirms, applies exactly that, and offers Undo", async () => {
    const { calls, user } = setup("", {
      "POST /api/browse/move/preview": { body: MOVE_PLAN },
      "POST /api/browse/move": { body: moveResult() },
      "POST /api/activity/m1/undo/preview": {
        body: [{ kind: "move", src: "13. Taxes/readme.txt", dst: "readme.txt", drive_id: "f0", note: null }],
      },
      "POST /api/activity/m1/undo": { body: UNDONE },
    });
    await screen.findByRole("button", { name: "readme.txt" });
    const dt = dragFrom(rowOf(listing(), "readme.txt"));
    const taxes = rowOf(listing(), "13. Taxes");
    fireEvent.dragEnter(taxes, { dataTransfer: dt });
    expect(taxes).toHaveAttribute("data-drop", "over");
    fireEvent.drop(taxes, { dataTransfer: dt });

    const dialog = await screen.findByRole("dialog", { name: "Move 1 file to 13. Taxes?" });
    expect(posts(calls, "/api/browse/move/preview").map((c) => c.body)).toEqual([
      { drive_ids: ["f0"], folder: "13. Taxes" },
    ]);
    expect(dialog).toHaveTextContent("readme.txt → 13. Taxes/readme.txt");
    expect(within(dialog).getByRole("button", { name: "Cancel" })).toHaveFocus();
    expect(posts(calls, "/api/browse/move")).toHaveLength(0); // a drop never moves by itself

    await user.click(within(dialog).getByRole("button", { name: "Move" }));
    await waitFor(() => expect(posts(calls, "/api/browse/move")).toHaveLength(1));
    expect(posts(calls, "/api/browse/move")[0].body).toEqual({ drive_ids: ["f0"], folder: "13. Taxes" });
    expect(await screen.findByText("Moved readme.txt to 13. Taxes")).toBeInTheDocument();
    expect(screen.queryByText(/other than previewed/)).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Undo" }));
    const undo = await screen.findByRole("dialog", { name: "Undo these changes?" });
    await waitFor(() => expect(undo).toHaveTextContent("13. Taxes/readme.txt → readme.txt"));
    await user.click(await undoButton(undo));
    await waitFor(() => expect(posts(calls, "/api/activity/m1/undo")).toHaveLength(1));
  });

  it("Cancel in the confirm moves nothing", async () => {
    const { calls, user } = setup("", { "POST /api/browse/move/preview": { body: MOVE_PLAN } });
    await screen.findByText("readme.txt");
    dropOn(rowOf(listing(), "13. Taxes"), dragFrom(rowOf(listing(), "readme.txt")));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(posts(calls, "/api/browse/move")).toHaveLength(0);
  });

  it("warns when the apply put a file somewhere other than previewed", async () => {
    const { user } = setup("", {
      "POST /api/browse/move/preview": { body: MOVE_PLAN },
      "POST /api/browse/move": { body: moveResult({ done: [{ ...MOVE_PLAN[0], dst: "13. Taxes/readme_2.txt" }] }) },
    });
    await screen.findByText("readme.txt");
    dropOn(rowOf(listing(), "13. Taxes"), dragFrom(rowOf(listing(), "readme.txt")));
    await user.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Move" }));
    expect(await screen.findByText(/Moved somewhere other than previewed: 13\. Taxes\/readme_2\.txt/)).toBeInTheDocument();
  });

  it("a refused preview shows the reason and offers no confirm", async () => {
    const { calls } = setup("", {
      "POST /api/browse/move/preview": { status: 400, body: { error: "the index is out of date: ‮rescan" } },
    });
    await screen.findByText("readme.txt");
    dropOn(rowOf(listing(), "13. Taxes"), dragFrom(rowOf(listing(), "readme.txt")));
    expect(await screen.findByText("Cannot move: the index is out of date: ⟨U+202E⟩rescan")).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(posts(calls, "/api/browse/move")).toHaveLength(0);
  });

  it("a preview with nothing to move says the files are already there", async () => {
    setup("", { "POST /api/browse/move/preview": { body: [] } });
    await screen.findByText("readme.txt");
    dropOn(rowOf(listing(), "13. Taxes"), dragFrom(rowOf(listing(), "readme.txt")));
    expect(await screen.findByText("Nothing to move: already in 13. Taxes")).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("two clicks on Move apply once", async () => {
    const held = deferred<{ body: unknown }>();
    const { calls } = setup("", {
      "POST /api/browse/move/preview": { body: MOVE_PLAN },
      "POST /api/browse/move": () => held.promise,
    });
    await screen.findByText("readme.txt");
    dropOn(rowOf(listing(), "13. Taxes"), dragFrom(rowOf(listing(), "readme.txt")));
    const apply = within(await screen.findByRole("dialog")).getByRole("button", { name: "Move" });
    act(() => {
      apply.click();
      apply.click();
    });
    await act(async () => held.resolve({ body: moveResult() }));
    await screen.findByText("Moved readme.txt to 13. Taxes");
    expect(posts(calls, "/api/browse/move")).toHaveLength(1);
  });

  it("##. To Delete and ##. Ongoing are not allowed as drop targets", async () => {
    const { calls } = setup("", {
      "GET /api/browse": { body: [file("readme.txt", "f0"), dir("##. To Delete"), dir("##. Ongoing")] },
    });
    await screen.findByText("readme.txt");
    const dt = dragFrom(rowOf(listing(), "readme.txt"));
    const trash = rowOf(listing(), "##. To Delete");
    fireEvent.dragEnter(trash, { dataTransfer: dt });
    expect(trash).toHaveAttribute("data-drop", "refused");
    expect(trash).toHaveAttribute("data-tip", "Not allowed: use Move to To Delete");
    expect(fireEvent.drop(trash, { dataTransfer: dt })).toBe(false);
    const ongoing = rowOf(listing(), "##. Ongoing");
    fireEvent.dragEnter(ongoing, { dataTransfer: dt });
    expect(ongoing).toHaveAttribute("data-tip", "Not allowed: ##. Ongoing is kept by the app");
    fireEvent.drop(ongoing, { dataTransfer: dt });
    await new Promise((r) => setTimeout(r, 10));
    expect(posts(calls, "/api/browse/move/preview")).toHaveLength(0);
  });

  it("⌘-click and ⇧-click select several files, and a drag carries all of them", async () => {
    const { user } = setup("10. Financial/Banks");
    await screen.findByText("a.pdf");
    await user.click(screen.getByRole("button", { name: "b.pdf" }));
    await user.keyboard("{Shift>}");
    await user.click(screen.getByRole("button", { name: /^link\.pdf/ }));
    await user.keyboard("{/Shift}");
    expect(screen.getByRole("checkbox", { name: "Select b.pdf" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Select a.pdf" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Select link.pdf" })).toBeChecked();
    await user.keyboard("{Meta>}");
    await user.click(screen.getByRole("button", { name: "a.pdf" }));
    await user.keyboard("{/Meta}");
    expect(screen.getByRole("checkbox", { name: "Select a.pdf" })).not.toBeChecked();
    expect(screen.getByRole("button", { name: "Move 2 to To Delete" })).toBeEnabled();
    const dt = dragFrom(rowOf(listing(), "b.pdf"));
    expect(JSON.parse(dt.data["application/x-dam-files"])).toEqual({ ids: ["f2", "f3"] });
    // a row outside the selection drags alone
    expect(JSON.parse(dragFrom(rowOf(listing(), "a.pdf")).data["application/x-dam-files"])).toEqual({ ids: ["f1"] });
  });

  it("Space opens Quick Look on the current file", async () => {
    const { user } = setup("10. Financial/Banks");
    await user.click(await screen.findByRole("button", { name: "a.pdf" }));
    await user.keyboard(" ");
    expect(screen.getByRole("dialog", { name: "Quick Look: a.pdf" })).toBeInTheDocument();
    await user.keyboard("j");
    expect(screen.getByRole("dialog", { name: "Quick Look: link.pdf" })).toBeInTheDocument();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});

describe("Two panes", () => {
  afterEach(() => {
    document.dispatchEvent(new Event("dragend"));
    try {
      localStorage.clear();
    } catch {
      // ignore
    }
  });

  function Where() {
    const loc = useLocation();
    return <p data-testid="where">{loc.search}</p>;
  }

  function setupSplit(url: string, extra: Parameters<typeof mockFetch>[0] = {}) {
    const calls = api(extra);
    const user = userEvent.setup();
    const view = renderWithProviders(
      <MemoryRouter initialEntries={[url]}>
        <Routes>
          <Route
            path="/browse"
            element={
              <>
                <Browse />
                <Where />
              </>
            }
          />
        </Routes>
      </MemoryRouter>,
    );
    return { calls, user, unmount: view.unmount };
  }

  it("the toolbar toggle splits Browse; each pane keeps its own path, back and forward", async () => {
    const { user } = setupSplit("/browse?path=10.%20Financial");
    await screen.findByText("Banks");
    const toggle = screen.getByRole("button", { name: "Two panes" });
    expect(toggle).toHaveAttribute("aria-pressed", "false");
    await user.click(toggle);
    expect(toggle).toHaveAttribute("aria-pressed", "true");
    expect(localStorage.getItem("dam.browse.split")).toBe("1");
    expect(within(pane("Left pane")).getByText("Banks")).toBeInTheDocument();
    expect(await within(pane("Right pane")).findByText("Banks")).toBeInTheDocument();
    // the single pane's preview is not shown beside two panes
    expect(screen.queryByRole("region", { name: "Preview" })).not.toBeInTheDocument();

    await user.click(within(pane("Right pane")).getByRole("button", { name: "Banks" }));
    expect(await within(pane("Right pane")).findByText("a.pdf")).toBeInTheDocument();
    expect(within(pane("Left pane")).getByText("Banks")).toBeInTheDocument();
    const where = new URLSearchParams(screen.getByTestId("where").textContent!);
    expect(where.get("left")).toBe("10. Financial");
    expect(where.get("right")).toBe("10. Financial/Banks");

    await user.click(within(pane("Left pane")).getByRole("link", { name: "Archive" }));
    expect(await within(pane("Left pane")).findByText("readme.txt")).toBeInTheDocument();
    expect(within(pane("Right pane")).getByText("a.pdf")).toBeInTheDocument();

    await user.click(within(pane("Right pane")).getByRole("button", { name: "Back" }));
    expect(await within(pane("Right pane")).findByText("Banks")).toBeInTheDocument();
    expect(within(pane("Left pane")).getByText("readme.txt")).toBeInTheDocument();
    await user.click(within(pane("Right pane")).getByRole("button", { name: "Forward" }));
    expect(await within(pane("Right pane")).findByText("a.pdf")).toBeInTheDocument();
    await user.click(within(pane("Left pane")).getByRole("button", { name: "Back" }));
    expect(await within(pane("Left pane")).findByText("Banks")).toBeInTheDocument();
    expect(within(pane("Left pane")).getByRole("button", { name: "Forward" })).toBeEnabled();
    expect(within(pane("Right pane")).getByRole("button", { name: "Forward" })).toBeDisabled();

    // back to one pane: the left pane's folder stays
    await user.click(toggle);
    expect(localStorage.getItem("dam.browse.split")).toBe("0");
    expect(screen.queryByRole("region", { name: "Right pane" })).not.toBeInTheDocument();
    expect(new URLSearchParams(screen.getByTestId("where").textContent!).get("path")).toBe("10. Financial");
  });

  it("the split is remembered, and works when storage is unavailable", async () => {
    localStorage.setItem("dam.browse.split", "1");
    const { unmount } = setupSplit("/browse");
    expect(await within(pane("Right pane")).findByText("readme.txt")).toBeInTheDocument();
    unmount();
    const spy = vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("denied");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("denied");
    });
    const { user } = setupSplit("/browse");
    expect(await screen.findByText("readme.txt")).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Right pane" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Two panes" }));
    expect(await within(pane("Right pane")).findByText("readme.txt")).toBeInTheDocument();
    spy.mockRestore();
  });

  it("dragging files onto the other pane moves them into its folder, through the confirm", async () => {
    const plan: ResolvedOp[] = [
      { kind: "move", src: "10. Financial/Banks/a.pdf", dst: "13. Taxes/a.pdf", drive_id: "f1", note: null },
      { kind: "move", src: "10. Financial/Banks/b.pdf", dst: "13. Taxes/b_2.pdf", drive_id: "f2", note: "name taken" },
    ];
    const { calls, user } = setupSplit("/browse?left=10.%20Financial%2FBanks&right=13.%20Taxes", {
      "POST /api/browse/move/preview": { body: plan },
      "POST /api/browse/move": { body: moveResult({ done: plan }) },
    });
    const left = pane("Left pane");
    await within(left).findByText("a.pdf");
    await within(pane("Right pane")).findByText("This folder is empty.");
    await user.click(within(left).getByRole("checkbox", { name: "Select a.pdf" }));
    await user.click(within(left).getByRole("checkbox", { name: "Select b.pdf" }));
    const dt = dragFrom(rowOf(left, "a.pdf"));
    // its own pane is where the files already are: not a target
    fireEvent.dragEnter(within(left).getByRole("list", { name: "Folder contents" }), { dataTransfer: dt });
    expect(within(left).getByTestId("pane-drop")).not.toHaveAttribute("data-drop");
    const target = within(pane("Right pane")).getByTestId("pane-drop");
    const empty = within(pane("Right pane")).getByText("This folder is empty.");
    fireEvent.dragEnter(empty, { dataTransfer: dt });
    expect(target).toHaveAttribute("data-drop", "over");
    fireEvent.drop(empty, { dataTransfer: dt });
    const dialog = await screen.findByRole("dialog", { name: "Move 2 files to 13. Taxes?" });
    expect(posts(calls, "/api/browse/move/preview")[0].body).toEqual({ drive_ids: ["f1", "f2"], folder: "13. Taxes" });
    expect(dialog).toHaveTextContent("(name taken)");
    await user.click(within(dialog).getByRole("button", { name: "Move" }));
    await waitFor(() => expect(posts(calls, "/api/browse/move")).toHaveLength(1));
    expect(await screen.findByText("Moved 2 files to 13. Taxes")).toBeInTheDocument();
    // the moved files are no longer selected
    expect(within(left).getByRole("checkbox", { name: "Select a.pdf" })).not.toBeChecked();
  });

  it("the top of the archive takes no files", async () => {
    const { calls } = setupSplit("/browse?left=10.%20Financial%2FBanks&right=");
    const left = pane("Left pane");
    await within(left).findByText("a.pdf");
    await within(pane("Right pane")).findByText("readme.txt");
    const dt = dragFrom(rowOf(left, "a.pdf"));
    const target = within(pane("Right pane")).getByTestId("pane-drop");
    fireEvent.dragEnter(within(pane("Right pane")).getByText("readme.txt"), { dataTransfer: dt });
    expect(target).toHaveAttribute("data-drop", "refused");
    expect(target).toHaveAttribute("data-tip", "Not allowed: the top of the archive holds folders only");
    // a folder there is fine
    const taxes = rowOf(pane("Right pane"), "13. Taxes");
    fireEvent.dragEnter(taxes, { dataTransfer: dt });
    expect(taxes).toHaveAttribute("data-drop", "over");
    expect(posts(calls, "/api/browse/move/preview")).toHaveLength(0);
  });
});

describe("Move to…", () => {
  it("⇧⌘M opens a folder picker for the selected files, then previews, confirms and applies", async () => {
    const { calls, user } = setup("10. Financial/Banks", {
      "GET /api/folders": { body: ["10. Financial", "13. Taxes"] },
      "POST /api/browse/move/preview": {
        body: [{ kind: "move", src: "10. Financial/Banks/a.pdf", dst: "13. Taxes/a.pdf", drive_id: "f1", note: null }],
      },
      "POST /api/browse/move": {
        body: moveResult({
          done: [{ kind: "move", src: "10. Financial/Banks/a.pdf", dst: "13. Taxes/a.pdf", drive_id: "f1", note: null }],
        }),
      },
    });
    await user.click(await screen.findByRole("checkbox", { name: "Select a.pdf" }));
    await user.keyboard("{Meta>}{Shift>}m{/Shift}{/Meta}");
    const sheet = await screen.findByRole("dialog", { name: "Move 1 file to…" });
    const picker = within(sheet).getByRole("combobox", { name: "Folder" });
    expect(picker).toHaveFocus();
    expect(within(sheet).getByRole("button", { name: "Preview move" })).toBeDisabled();
    await user.type(picker, "13. Taxes");
    await user.click(within(sheet).getByRole("button", { name: "Preview move" }));
    const dialog = await screen.findByRole("dialog", { name: "Move 1 file to 13. Taxes?" });
    expect(posts(calls, "/api/browse/move/preview")[0].body).toEqual({ drive_ids: ["f1"], folder: "13. Taxes" });
    await user.click(within(dialog).getByRole("button", { name: "Move" }));
    await waitFor(() => expect(posts(calls, "/api/browse/move")).toHaveLength(1));
    expect(posts(calls, "/api/browse/move")[0].body).toEqual({ drive_ids: ["f1"], folder: "13. Taxes" });
    expect(await screen.findByText("Moved a.pdf to 13. Taxes")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Undo" })).toBeInTheDocument();
  });

  it("the folder browser over Move to…: walk, choose, and Esc closes only the browser", async () => {
    const { calls, user } = setup("10. Financial/Banks", {
      "GET /api/folders": { body: ["10. Financial", "10. Financial/Banks", "13. Taxes", "13. Taxes/2025"] },
    });
    await user.click(await screen.findByRole("checkbox", { name: "Select a.pdf" }));
    await user.keyboard("{Meta>}{Shift>}m{/Shift}{/Meta}");
    const sheet = await screen.findByRole("dialog", { name: "Move 1 file to…" });
    const picker = within(sheet).getByRole("combobox", { name: "Folder" });
    // Esc in the browser closes it alone; Move to… stays, focus back on its field
    await user.click(within(sheet).getByRole("button", { name: "Browse folders…" }));
    let browser = await screen.findByRole("dialog", { name: "Choose a folder" });
    await within(browser).findByRole("treeitem", { name: "13. Taxes" });
    await user.keyboard("{ArrowDown}{Escape}");
    expect(browser).not.toBeInTheDocument();
    expect(sheet).toBeInTheDocument();
    await waitFor(() => expect(picker).toHaveFocus());
    expect(picker).toHaveValue("");
    // walk to 13. Taxes/2025 and choose it: only the field changes, nothing is previewed
    await user.click(within(sheet).getByRole("button", { name: "Browse folders…" }));
    browser = await screen.findByRole("dialog", { name: "Choose a folder" });
    await within(browser).findByRole("treeitem", { name: "13. Taxes" });
    await user.keyboard("{ArrowDown}{ArrowRight}{ArrowRight}{Enter}");
    expect(browser).not.toBeInTheDocument();
    expect(picker).toHaveValue("13. Taxes/2025");
    expect(sheet).toBeInTheDocument();
    expect(posts(calls, "/api/browse/move/preview")).toHaveLength(0);
  });

  it("the toolbar button moves the previewed file when nothing is checked; Esc closes the picker", async () => {
    const { calls, user } = setup("10. Financial/Banks", { "GET /api/folders": { body: [] } });
    const move = await screen.findByRole("button", { name: "Move to…" });
    await screen.findByRole("button", { name: "a.pdf" });
    expect(move).toBeDisabled(); // nothing selected yet
    await user.click(screen.getByRole("button", { name: "a.pdf" }));
    expect(move).toBeEnabled();
    await user.click(move);
    const sheet = await screen.findByRole("dialog", { name: "Move 1 file to…" });
    expect(sheet).toHaveTextContent("a.pdf");
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(posts(calls, "/api/browse/move/preview")).toHaveLength(0);
  });

  it("is not offered for a folder", async () => {
    const { user } = setup("10. Financial", { "GET /api/folders": { body: [] } });
    await user.click(await screen.findByRole("button", { name: "Banks" })); // opens the folder
    await screen.findByText("a.pdf");
    await user.keyboard("{Backspace}");
    await within(listing()).findByText("Banks");
    expect(screen.getByRole("button", { name: "Move to…" })).toBeDisabled();
    await user.keyboard("{Meta>}{Shift>}m{/Shift}{/Meta}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});

describe("Task 11 review fixes", () => {
  afterEach(() => {
    document.dispatchEvent(new Event("dragend"));
  });

  it("while a move is being previewed, another drop is refused with a reason", async () => {
    const held = deferred<{ body: unknown }>();
    const { calls } = setup("", { "POST /api/browse/move/preview": () => held.promise });
    await screen.findByText("readme.txt");
    dropOn(rowOf(listing(), "13. Taxes"), dragFrom(rowOf(listing(), "readme.txt")));
    await waitFor(() => expect(posts(calls, "/api/browse/move/preview")).toHaveLength(1));
    const dt = dragFrom(rowOf(listing(), "readme.txt"));
    const other = rowOf(listing(), "10. Financial");
    fireEvent.dragEnter(other, { dataTransfer: dt });
    expect(other).toHaveAttribute("data-drop", "refused");
    expect(other).toHaveAttribute("data-tip", "Another move is still running");
    expect(fireEvent.drop(other, { dataTransfer: dt })).toBe(false);
    await act(async () => held.resolve({ body: MOVE_PLAN }));
    expect(posts(calls, "/api/browse/move/preview")).toHaveLength(1);
  });

  it.each([
    ["##. To Delete/10. Financial", "Files in ##. To Delete cannot be moved: Undo puts them back"],
    ["##. Ongoing/Sauna", "Files in ##. Ongoing cannot be moved: the app keeps them"],
  ])("files under %s are not draggable and Move to… says why", async (folder, reason) => {
    const { user } = setup(folder, {
      "GET /api/browse": { body: [file(`${folder}/x.pdf`, "fx"), dir(`${folder}/Sub`)] },
      "GET /api/files/fx/links": { body: NO_LINKS },
      "GET /api/notes/file/fx": { body: { text: "" } },
    });
    await user.click(await screen.findByRole("button", { name: "x.pdf" }));
    expect(rowOf(listing(), "x.pdf")).not.toHaveAttribute("draggable", "true");
    const moveTo = screen.getByRole("button", { name: "Move to…" });
    expect(moveTo).toBeDisabled();
    expect(moveTo.closest(".icon-button-wrap")).toHaveAttribute("data-tip", reason);
    await user.keyboard("{Meta>}{Shift>}m{/Shift}{/Meta}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("undoing a move reloads the search results", async () => {
    const hit: SearchHit = { drive_id: "f1", path: "10. Financial/Banks/a.pdf", name: "a.pdf", snippet: "[a]", rank: -1, size: 1, mtime: 1, marks: [] };
    const op = { kind: "move" as const, src: hit.path, dst: "13. Taxes/a.pdf", drive_id: "f1", note: null };
    const { calls, user } = setup("", {
      "GET /api/search": { body: [hit] },
      "GET /api/folders": { body: [] },
      "POST /api/browse/move/preview": { body: [op] },
      "POST /api/browse/move": { body: moveResult({ done: [op] }) },
      "POST /api/activity/m1/undo/preview": { body: [] }, "POST /api/activity/m1/undo": { body: UNDONE },
    });
    await screen.findByText("readme.txt");
    await user.type(screen.getByRole("searchbox", { name: "Search" }), "a");
    await user.click(await screen.findByRole("button", { name: /^a\.pdf/ }));
    await user.click(screen.getByRole("button", { name: "Move to…" }));
    const sheet = await screen.findByRole("dialog", { name: "Move 1 file to…" });
    await user.type(within(sheet).getByRole("combobox", { name: "Folder" }), "13. Taxes{Enter}");
    await user.click(within(await screen.findByRole("dialog", { name: /^Move 1 file to 13/ })).getByRole("button", { name: "Move" }));
    await screen.findByText("Moved a.pdf to 13. Taxes");
    await waitFor(() => expect(searches(calls)).toHaveLength(2)); // the move reloaded it
    await user.click(screen.getByRole("button", { name: "Undo" }));
    await user.click(await undoButton(await screen.findByRole("dialog", { name: "Undo these changes?" })));
    await waitFor(() => expect(posts(calls, "/api/activity/m1/undo")).toHaveLength(1));
    await waitFor(() => expect(searches(calls)).toHaveLength(3)); // and so did the undo
  });
});

describe("Collection filter and Files view", () => {
  afterEach(() => {
    document.dispatchEvent(new Event("dragend"));
    try {
      localStorage.clear();
    } catch {
      // ignore
    }
  });

  const HOUSES: CollectionRow = { ...SAUNA, id: 3, name: "Houses", path: ["Houses"] };
  const CHILD: CollectionRow = { ...SAUNA, parent_id: 3, path: ["Houses", "Sauna"] };
  // the built-ins, as ?builtin=true lists them (the Browse filter's "Marked")
  const STAR: CollectionRow = { ...SAUNA, id: 50, name: "Ongoing", path: ["Ongoing"], kind: "starred", members: [] };
  const IMPORTANT: CollectionRow = { ...SAUNA, id: 51, name: "Important", path: ["Important"], kind: "important", members: [] };
  const FLAT_ROWS: DirEntry[] = [
    file("10. Financial/Banks/a.pdf", "f1"),
    file("10. Financial/Banks/b.pdf", "f2"),
    { ...file("10. Financial/Banks/link.pdf", "f3", true), size: 2048, mtime: 1_699_963_200 } // 14 Nov 2023, noon UTC,
  ];

  function Where() {
    const loc = useLocation();
    return <p data-testid="where">{loc.search}</p>;
  }
  const where = () => new URLSearchParams(screen.getByTestId("where").textContent!);

  function start(url: string, extra: Parameters<typeof mockFetch>[0] = {}) {
    const calls = api({
      "GET /api/collections": { body: [HOUSES, CHILD, IMPORTANT, STAR] },
      // the filtered folder: only the way to the members
      "GET /api/browse": (call) => {
        const p = queryOf(call);
        const rows = LISTINGS[p.get("path") ?? ""] ?? [];
        return { body: p.get("collection") ? rows.filter((r) => r.is_dir || r.drive_id === "f1") : rows };
      },
      "GET /api/browse/files": (call) => {
        const p = queryOf(call);
        const rows = p.get("collection") ? FLAT_ROWS.slice(0, 1) : FLAT_ROWS;
        return { body: { rows: p.get("dir") === "desc" ? [...rows].reverse() : rows, total: p.get("collection") ? 1 : 1203 } };
      },
      ...extra,
    });
    const user = userEvent.setup();
    renderWithProviders(
      <MemoryRouter initialEntries={[url]}>
        <Routes>
          <Route
            path="/browse"
            element={
              <>
                <Browse />
                <Where />
              </>
            }
          />
        </Routes>
      </MemoryRouter>,
    );
    return { calls, user };
  }
  const flatCalls = (calls: Call[]) => calls.filter((c) => c.url.startsWith("/api/browse/files"));
  const dirCalls = (calls: Call[]) => calls.filter((c) => c.url.startsWith("/api/browse?"));

  const menuItems = () => within(screen.getByRole("menu", { name: "Collection" })).getAllByRole("menuitemcheckbox");

  it("the Collection menu button filters the folder and shows the chosen name; All files clears it", async () => {
    const { calls, user } = start("/browse?path=10.%20Financial%2FBanks");
    await screen.findByText("b.pdf");
    expect(dirCalls(calls)[0].url).toBe("/api/browse?path=10.%20Financial%2FBanks"); // unfiltered as before
    const button = screen.getByRole("button", { name: "Collection" });
    expect(button).toHaveTextContent("Collection");
    await user.click(button);
    // All files, the built-ins, then the open collections as a tree (Sauna is inside Houses)
    await waitFor(() => expect(menuItems().map((o) => o.textContent)).toEqual(["✓All files", "★ Starred", "! Important", "Houses", "Sauna"]));
    expect(menuItems()[0]).toHaveAttribute("aria-checked", "true");
    expect(menuItems()[4].style.paddingLeft).toBe("calc(18px)"); // indented under Houses
    await user.click(screen.getByRole("menuitemcheckbox", { name: "Sauna" }));
    expect(where().get("collection")).toBe("7");
    await waitFor(() => expect(screen.queryByText("b.pdf")).not.toBeInTheDocument());
    expect(dirCalls(calls).at(-1)!.url).toBe("/api/browse?path=10.%20Financial%2FBanks&collection=7");
    expect(rowNames()).toEqual(["a.pdf"]);
    // the button now carries the collection's name (no chip after the path)
    const named = screen.getByRole("button", { name: "Collection: Sauna" });
    expect(named).toHaveTextContent("Sauna");
    const crumbs = screen.getByRole("navigation", { name: "Breadcrumb" });
    expect(within(crumbs).queryByText("Sauna")).not.toBeInTheDocument();

    // the filter stays while moving between folders
    await user.click(within(crumbs).getByRole("link", { name: "10. Financial" }));
    await screen.findByText("Banks");
    expect(where().get("collection")).toBe("7");
    expect(dirCalls(calls).at(-1)!.url).toBe("/api/browse?path=10.%20Financial&collection=7");

    await user.click(screen.getByRole("button", { name: "Collection: Sauna" }));
    expect(screen.getByRole("menuitemcheckbox", { name: "Sauna" })).toHaveAttribute("aria-checked", "true");
    await user.click(screen.getByRole("menuitemcheckbox", { name: "All files" }));
    expect(where().has("collection")).toBe(false);
    expect(screen.getByRole("button", { name: "Collection" })).toHaveTextContent("Collection");
  });

  it("a built-in is a filter too, and Esc closes the menu", async () => {
    const { user } = start("/browse?path=10.%20Financial%2FBanks&collection=7");
    await screen.findByText("a.pdf");
    expect(await screen.findByRole("button", { name: "Collection: Sauna" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Collection: Sauna" }));
    await user.click(await screen.findByRole("menuitemcheckbox", { name: "★ Starred" }));
    expect(where().get("collection")).toBe("50");
    expect(await screen.findByRole("button", { name: "Collection: ★ Starred" })).toHaveTextContent("★ Starred");
    await user.click(screen.getByRole("button", { name: "Collection: ★ Starred" }));
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });

  it("a filtered folder with nothing of the collection says so", async () => {
    start("/browse?path=10.%20Financial%2FBanks&collection=7", {
      "GET /api/browse": { body: [] },
    });
    expect(await screen.findByText("Nothing of this collection here.")).toBeInTheDocument();
  });

  it("the Files view lists every file below with folder, date and size, sortable, capped with 'N more'", async () => {
    const { calls, user } = start("/browse?path=10.%20Financial%2FBanks");
    await screen.findByText("b.pdf");
    const view = screen.getByRole("group", { name: "View" });
    expect(within(view).getByRole("button", { name: "Folders" })).toHaveAttribute("aria-pressed", "true");
    await user.click(within(view).getByRole("button", { name: "Files" }));
    expect(where().get("view")).toBe("files");
    const list = await screen.findByRole("list", { name: "Files" });
    expect(queryOf(flatCalls(calls)[0])).toEqual(
      new URLSearchParams({ path: "10. Financial/Banks", sort: "name", dir: "asc", limit: "500" }),
    );
    const link = rowOf(list, "link.pdf");
    expect(within(link).getByText("10. Financial/Banks")).toHaveClass("entry-folder");
    expect(within(link).getByText("2,0 KB")).toHaveClass("entry-size");
    expect(within(link).getByText("14 Nov 2023")).toHaveClass("entry-date");
    expect(within(link).getByRole("img", { name: "Symbolic link" })).toBeInTheDocument();
    expect(screen.getByText(/more — narrow the folder or search/)).toHaveTextContent("1 200 more — narrow the folder or search");

    const sortBar = screen.getByRole("group", { name: "Sort by" });
    expect(within(sortBar).getByRole("button", { name: "Sort by name, ascending" })).toHaveAttribute("aria-pressed", "true");
    await user.click(within(sortBar).getByRole("button", { name: "Sort by date" }));
    await waitFor(() => expect(queryOf(flatCalls(calls).at(-1)!).get("sort")).toBe("date"));
    expect(queryOf(flatCalls(calls).at(-1)!).get("dir")).toBe("desc"); // newest first
    await user.click(screen.getByRole("button", { name: "Sort by date, descending" }));
    await waitFor(() => expect(queryOf(flatCalls(calls).at(-1)!).get("dir")).toBe("asc"));
    await user.click(screen.getByRole("button", { name: "Sort by size" }));
    await waitFor(() => expect(queryOf(flatCalls(calls).at(-1)!).get("sort")).toBe("size"));

    // back to the folders, without the folder listing being asked again for nothing
    await user.click(within(view).getByRole("button", { name: "Folders" }));
    expect(where().has("view")).toBe(false);
    expect(await screen.findByRole("list", { name: "Folder contents" })).toBeInTheDocument();
  });

  it("no 'more' line when every file is listed", async () => {
    start("/browse?path=10.%20Financial%2FBanks&view=files&collection=7");
    const list = await screen.findByRole("list", { name: "Files" });
    expect(within(list).getAllByRole("listitem")).toHaveLength(1);
    expect(screen.queryByText(/more — narrow/)).not.toBeInTheDocument();
  });

  it("the Files view comes straight from the URL, with its filter", async () => {
    const { calls } = start("/browse?path=10.%20Financial&view=files&collection=7");
    await screen.findByRole("list", { name: "Files" });
    expect(queryOf(flatCalls(calls)[0]).get("collection")).toBe("7");
    expect(queryOf(flatCalls(calls)[0]).get("path")).toBe("10. Financial");
    expect(dirCalls(calls)).toHaveLength(0); // the folder listing is not fetched in this view
  });

  it("rows in the Files view select, drag, preview and Quick Look as in Folders", async () => {
    const { user } = start("/browse?path=10.%20Financial%2FBanks&view=files");
    const list = await screen.findByRole("list", { name: "Files" });
    await user.click(within(list).getByRole("button", { name: /^a\.pdf/ }));
    const preview = await screen.findByRole("region", { name: "Preview" });
    expect(within(preview).getByText("10. Financial/Banks/a.pdf")).toBeInTheDocument();
    await user.keyboard("{Meta>}");
    await user.click(within(list).getByRole("button", { name: /^b\.pdf/ }));
    await user.keyboard("{/Meta}");
    expect(screen.getByRole("checkbox", { name: "Select a.pdf" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Select b.pdf" })).toBeChecked();
    expect(JSON.parse(dragFrom(rowOf(list, "a.pdf")).data["application/x-dam-files"])).toEqual({ ids: ["f1", "f2"] });
    expect(screen.getByRole("button", { name: "Move to…" })).toBeEnabled();
    await user.keyboard(" ");
    expect(screen.getByRole("dialog", { name: "Quick Look: b.pdf" })).toBeInTheDocument();
    await user.keyboard("{Escape}");
  });

  it("two panes: each has its own filter and view, kept in the URL", async () => {
    const { calls, user } = start("/browse?left=10.%20Financial%2FBanks&right=10.%20Financial%2FBanks&rcol=7&rview=files");
    const right = pane("Right pane");
    const left = pane("Left pane");
    expect(await within(left).findByText("b.pdf")).toBeInTheDocument();
    expect(await within(right).findByRole("list", { name: "Files" })).toBeInTheDocument();
    expect(within(right).getByRole("button", { name: "Collection: Sauna" })).toBeInTheDocument();
    expect(within(left).getByRole("button", { name: "Collection" })).toBeInTheDocument();
    expect(dirCalls(calls).every((c) => !queryOf(c).has("collection"))).toBe(true);
    expect(flatCalls(calls).every((c) => queryOf(c).get("collection") === "7")).toBe(true);

    // a filter on the left changes the left only
    await user.click(within(left).getByRole("button", { name: "Collection" }));
    await user.click(await screen.findByRole("menuitemcheckbox", { name: "Houses" }));
    expect(where().get("lcol")).toBe("3");
    expect(where().get("rcol")).toBe("7");
    await user.click(within(within(left).getByRole("group", { name: "View" })).getByRole("button", { name: "Files" }));
    expect(where().get("lview")).toBe("files");
    expect(where().get("rview")).toBe("files");
    await user.click(within(within(right).getByRole("group", { name: "View" })).getByRole("button", { name: "Folders" }));
    expect(where().has("rview")).toBe(false);
    expect(where().get("lview")).toBe("files");
    // sorting one pane leaves the other's order alone
    await within(left).findByRole("list", { name: "Files" });
    await user.click(within(left).getByRole("button", { name: "Sort by size" }));
    await waitFor(() =>
      expect(flatCalls(calls).some((c) => queryOf(c).get("sort") === "size" && queryOf(c).get("collection") === "3")).toBe(true),
    );
    // back to one pane: the left pane's state stays, in the one-pane parameters
    await user.click(screen.getByRole("button", { name: "Two panes" }));
    expect(where().get("collection")).toBe("3");
    expect(where().get("view")).toBe("files");
    expect(where().get("path")).toBe("10. Financial/Banks");
  });
});

describe("marks in Browse (stars)", () => {
  it("rows show their ★ / ! icons; the preview's toggle stars the file and the listing follows", async () => {
    let starred = false;
    const { calls, user } = setup("10. Financial/Banks", {
      "GET /api/browse": (call) => {
        const rows = LISTINGS[queryOf(call).get("path") ?? ""] ?? [];
        return { body: rows.map((r) => (r.drive_id === "f1" && starred ? { ...r, marks: ["starred"] } : r.drive_id === "f2" ? { ...r, marks: ["important"] } : r)) };
      },
      "POST /api/marks/star": () => {
        starred = true;
        return { body: { collection: { id: 1, members: [], groups: [] }, batch: null, problems: [], ongoing_status: null } };
      },
      "GET /api/files/f1/text": { body: { text: "A", truncated: false } },
    });
    const b = (await screen.findByText("b.pdf")).closest("li")!;
    expect(within(b).getByRole("img", { name: "Important" })).toBeInTheDocument();
    const a = screen.getByText("a.pdf").closest("li")!;
    expect(within(a).queryByRole("img", { name: "Starred" })).toBeNull();
    await user.click(within(a).getByRole("button", { name: "a.pdf" }));
    const preview = screen.getByRole("region", { name: "Preview" });
    await user.click(within(preview).getByRole("button", { name: "Star" }));
    await waitFor(() => expect(posts(calls, "/api/marks/star")).toHaveLength(1));
    expect(posts(calls, "/api/marks/star")[0].body).toEqual({ drive_ids: ["f1"] });
    await waitFor(() => expect(within(screen.getByRole("button", { name: /^a\.pdf/ }).closest("li")!).getByRole("img", { name: "Starred" })).toBeInTheDocument());
    expect(within(preview).getByRole("button", { name: "Remove the star" })).toBeInTheDocument();
  });

  it("with two panes the active pane's toolbar has the toggles of the file it is on", async () => {
    const { calls, user } = setup(null, {
      "POST /api/marks/important": { body: { collection: { id: 2, members: [], groups: [] }, batch: null, problems: [], ongoing_status: null } },
    });
    await screen.findByText("readme.txt");
    await user.click(screen.getByRole("button", { name: "Two panes" }));
    const left = await screen.findByRole("region", { name: "Left pane" });
    const right = screen.getByRole("region", { name: "Right pane" });
    expect(within(left).queryByRole("button", { name: "Star" })).toBeNull(); // no file chosen yet
    await user.click(within(left).getAllByRole("button", { name: "readme.txt" })[0]);
    const bar = left.querySelector<HTMLElement>(".pane-bar")!;
    await user.click(within(bar).getByRole("button", { name: "Mark Important" }));
    await waitFor(() => expect(posts(calls, "/api/marks/important")).toHaveLength(1));
    expect(posts(calls, "/api/marks/important")[0].body).toEqual({ drive_ids: ["f0"] });
    expect(within(bar).getByRole("button", { name: "Unmark Important" })).toBeInTheDocument();
    expect(within(right.querySelector<HTMLElement>(".pane-bar")!).queryByRole("button", { name: /Important/ })).toBeNull();
    localStorage.clear();
  });

  it("search hits fetch again after a mark, so their icons follow (MARKS_CHANGED)", async () => {
    let starred = false;
    const { calls, user } = setup("", {
      "GET /api/search": () => ({
        body: [{ drive_id: "f1", path: "10. Financial/Banks/a.pdf", name: "a.pdf", snippet: "", rank: 1, marks: starred ? ["starred"] : [] }],
      }),
      "POST /api/marks/star": () => {
        starred = true;
        return { body: { collection: { id: 1, members: [], groups: [] }, batch: null, problems: [], ongoing_status: null } };
      },
      "GET /api/files/f1/page/1.png": { body: {} },
    });
    await user.type(screen.getByRole("searchbox", { name: "Search" }), "invoice");
    const results = await screen.findByRole("list", { name: "Search results" });
    const hit = await within(results).findByRole("button", { name: /^a\.pdf/ });
    expect(within(results).queryByRole("img", { name: "Starred" })).toBeNull();
    const before = calls.filter((c) => c.url.startsWith("/api/search")).length;
    await user.click(hit);
    await user.click(within(screen.getByRole("region", { name: "Preview" })).getByRole("button", { name: "Star" }));
    expect(await within(results).findByRole("img", { name: "Starred" })).toBeInTheDocument();
    expect(calls.filter((c) => c.url.startsWith("/api/search")).length).toBe(before + 1);
  });
});

describe("Trash in Browse (stars spec §8)", () => {
  afterEach(() => {
    try {
      localStorage.clear();
    } catch {
      // ignore
    }
  });
  const PATHS = { f1: "10. Financial/Banks/a.pdf", f2: "10. Financial/Banks/b.pdf" };
  const quarantines = (calls: Call[]) => posts(calls, "/api/quarantine").map((c) => c.body);
  const trash = { "POST /api/quarantine": quarantineRoute(PATHS) };

  it("the toolbar bin is named and tipped for ##. To Delete with ⌘⌫", async () => {
    setup("10. Financial/Banks");
    await screen.findByText("a.pdf");
    const bin = screen.getByRole("button", { name: "Move to To Delete" });
    expect(bin).toHaveAttribute("data-tip", "Move to To Delete ⌘⌫");
  });

  it("⌘⌫ on the list trashes the ticked files in one batch; plain ⌫ still goes up; ⌘⌫ in the search box edits it", async () => {
    const { calls, user } = setup("10. Financial/Banks", trash);
    await user.click(await screen.findByRole("checkbox", { name: "Select a.pdf" }));
    await user.click(screen.getByRole("checkbox", { name: "Select b.pdf" }));
    await user.click(screen.getByRole("searchbox"));
    await user.keyboard("{Meta>}{Backspace}{/Meta}");
    expect(quarantines(calls)).toHaveLength(0);
    screen.getByRole("checkbox", { name: "Select b.pdf" }).focus();
    await user.keyboard("{Meta>}{Backspace}{/Meta}");
    const dialog = await screen.findByRole("dialog", { name: "Move to To Delete?" });
    await user.click(within(dialog).getByRole("button", { name: "Move to To Delete" }));
    await screen.findByText("Moved to To Delete: b.pdf, a.pdf");
    expect(quarantines(calls)).toEqual([
      { drive_ids: ["f2", "f1"], dry_run: true },
      { drive_ids: ["f2", "f1"], dry_run: false },
    ]);
    // the moved files leave the selection
    expect(screen.getByRole("button", { name: "Move to To Delete" })).toBeDisabled();
    // a plain ⌫ on the list still goes up a folder, and trashes nothing
    screen.getByRole("button", { name: "a.pdf" }).focus();
    await user.keyboard("{Backspace}");
    expect(await screen.findByText("Banks")).toBeInTheDocument();
    expect(quarantines(calls)).toHaveLength(2);
  });

  it("the right pane's bin takes the right pane's file", async () => {
    const { calls, user } = setup("10. Financial", trash);
    await screen.findByText("Banks");
    await user.click(screen.getByRole("button", { name: "Two panes" }));
    await user.click(await within(pane("Right pane")).findByRole("button", { name: "Banks" }));
    await user.click(await within(pane("Right pane")).findByRole("button", { name: "b.pdf" }));
    await user.click(screen.getByRole("button", { name: "Move to To Delete" }));
    await screen.findByRole("dialog", { name: "Move to To Delete?" });
    expect(quarantines(calls)).toEqual([{ drive_ids: ["f2"], dry_run: true }]);
  });

  it("the Files view's bin takes its row", async () => {
    const { calls, user } = setup("10. Financial", {
      ...trash,
      "GET /api/browse/files": { body: { rows: [file(PATHS.f1, "f1"), file(PATHS.f2, "f2")], total: 2 } },
    });
    await screen.findByText("Banks");
    await user.click(within(screen.getByRole("group", { name: "View" })).getByRole("button", { name: "Files" }));
    const list = await screen.findByRole("list", { name: "Files" });
    await user.click(within(list).getByRole("button", { name: /b\.pdf/ }));
    await user.click(screen.getByRole("button", { name: "Move to To Delete" }));
    await screen.findByRole("dialog", { name: "Move to To Delete?" });
    expect(quarantines(calls)).toEqual([{ drive_ids: ["f2"], dry_run: true }]);
  });

  it("a ticked file marked Important refuses the whole batch with the server's reason", async () => {
    const { calls, user } = setup("10. Financial/Banks", { "POST /api/quarantine": IMPORTANT_REFUSED(PATHS.f1) });
    await user.click(await screen.findByRole("checkbox", { name: "Select a.pdf" }));
    await user.click(screen.getByRole("checkbox", { name: "Select b.pdf" }));
    await user.click(screen.getByRole("button", { name: "Move 2 to To Delete" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(`This file is marked Important; unmark it first: ${PATHS.f1}`);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(quarantines(calls)).toHaveLength(1);
  });

  it("Quick Look on a protected file: the bin is disabled saying why, and ⌘⌫ says it on the status line", async () => {
    const { calls, user } = setup("##. Important", trash);
    await user.click(await screen.findByRole("button", { name: "passport.pdf" }));
    await user.keyboard(" ");
    const ql = await screen.findByRole("dialog", { name: /^Quick Look/ });
    const bin = within(ql).getByRole("button", { name: "Move to To Delete" });
    expect(bin).toBeDisabled();
    expect(bin.parentElement).toHaveAttribute("data-tip", "Files in ##. Important are protected");
    await user.keyboard("{Meta>}{Backspace}{/Meta}");
    expect(within(ql).getByRole("status")).toHaveTextContent("Files in ##. Important are protected");
    expect(quarantines(calls)).toHaveLength(0);
  });

  it("Quick Look's bin trashes the file it shows", async () => {
    const { calls, user } = setup("10. Financial/Banks", trash);
    await user.click(await screen.findByRole("button", { name: "a.pdf" }));
    await user.keyboard(" ");
    const ql = await screen.findByRole("dialog", { name: /^Quick Look/ });
    await user.click(within(ql).getByRole("button", { name: "Move to To Delete" }));
    await screen.findByRole("dialog", { name: "Move to To Delete?" });
    expect(quarantines(calls)).toEqual([{ drive_ids: ["f1"], dry_run: true }]);
  });

  const IMPORTANT_TEXT = "This file is marked Important; unmark it first";
  const importantListing = {
    "GET /api/browse": (call: Call) => {
      const rows = LISTINGS[queryOf(call).get("path") ?? ""] ?? [];
      return { body: rows.map((r) => (r.drive_id === "f1" ? { ...r, marks: ["important"] } : r)) };
    },
  };

  it("a file the listing marks Important: the bins are disabled up front with the server's reason, and ⌘⌫ says it", async () => {
    const { calls, user } = setup("10. Financial/Banks", { ...trash, ...importantListing });
    await user.click(await screen.findByRole("button", { name: /^a\.pdf/ })); // the row names its marks too
    const bin = screen.getByRole("button", { name: "Move to To Delete" });
    expect(bin).toBeDisabled();
    expect(bin.parentElement).toHaveAttribute("data-tip", IMPORTANT_TEXT);
    await user.keyboard("{Meta>}{Backspace}{/Meta}");
    expect(await screen.findByText(IMPORTANT_TEXT, { selector: ".toast-text" })).toBeInTheDocument();
    await user.keyboard(" ");
    const ql = await screen.findByRole("dialog", { name: "Quick Look: a.pdf" });
    const qlBin = within(ql).getByRole("button", { name: "Move to To Delete" });
    expect(qlBin).toBeDisabled();
    expect(qlBin.parentElement).toHaveAttribute("data-tip", IMPORTANT_TEXT);
    await user.keyboard("{Meta>}{Backspace}{/Meta}");
    expect(within(ql).getByRole("status")).toHaveTextContent(IMPORTANT_TEXT);
    expect(quarantines(calls)).toHaveLength(0);
    // the other file is not affected
    await user.keyboard("{Escape}");
    await user.click(screen.getByRole("button", { name: "b.pdf" }));
    expect(screen.getByRole("button", { name: "Move to To Delete" })).toBeEnabled();
  });

  it("a second ⌘⌫ while the dry run runs says so instead of nothing", async () => {
    const held = deferred<{ body: unknown }>();
    const { calls, user } = setup("10. Financial/Banks", { "POST /api/quarantine": () => held.promise });
    await user.click(await screen.findByRole("button", { name: "a.pdf" }));
    await user.keyboard("{Meta>}{Backspace}{/Meta}");
    await waitFor(() => expect(quarantines(calls)).toHaveLength(1));
    await user.keyboard("{Meta>}{Backspace}{/Meta}");
    expect(await screen.findByText("Already moving…", { selector: ".toast-text" })).toBeInTheDocument();
    expect(quarantines(calls)).toHaveLength(1);
    await act(async () => held.resolve({ body: batchResult({ dry_run: true }) }));
    await screen.findByRole("dialog", { name: "Move to To Delete?" });
  });

  it("Quick Look closed during the dry run: the refusal is still said, as a toast", async () => {
    const held = deferred<{ status: number; body: unknown }>();
    const { calls, user } = setup("10. Financial/Banks", { "POST /api/quarantine": () => held.promise });
    await user.click(await screen.findByRole("button", { name: "a.pdf" }));
    await user.keyboard(" ");
    const ql = await screen.findByRole("dialog", { name: "Quick Look: a.pdf" });
    await user.keyboard("{Meta>}{Backspace}{/Meta}");
    await waitFor(() => expect(quarantines(calls)).toHaveLength(1));
    await user.keyboard("{Escape}");
    expect(ql).not.toBeInTheDocument();
    await act(async () => held.resolve(IMPORTANT_REFUSED(PATHS.f1)));
    expect(await screen.findByText(`Not moved to To Delete: ${IMPORTANT_TEXT}: ${PATHS.f1}`, { selector: ".toast-text" })).toBeInTheDocument();
  });

  it("Cancel from Quick Look's confirm brings Quick Look back, and closing that returns the focus to the row", async () => {
    const { calls, user } = setup("10. Financial/Banks", trash);
    const rowButton = await screen.findByRole("button", { name: "a.pdf" });
    await user.click(rowButton);
    await user.keyboard(" ");
    const ql = await screen.findByRole("dialog", { name: "Quick Look: a.pdf" });
    await user.click(within(ql).getByRole("button", { name: "Move to To Delete" }));
    const confirm = await screen.findByRole("dialog", { name: "Move to To Delete?" });
    expect(ql).not.toBeInTheDocument();
    await user.click(within(confirm).getByRole("button", { name: "Cancel" }));
    expect(confirm).not.toBeInTheDocument();
    const again = await screen.findByRole("dialog", { name: "Quick Look: a.pdf" });
    expect(again).toContainElement(document.activeElement as HTMLElement);
    await user.keyboard("{Escape}");
    expect(again).not.toBeInTheDocument();
    expect(rowButton).toHaveFocus();
    expect(quarantines(calls)).toEqual([{ drive_ids: ["f1"], dry_run: true }]);
  });
});

describe("Selection, folders and layout (UI review)", () => {
  it("a highlighted row is the selected file: j shows its detail, preview first", async () => {
    const { user } = setup("10. Financial/Banks");
    await screen.findByRole("button", { name: "b.pdf" });
    const preview = screen.getByRole("region", { name: "Preview" });
    // nothing is highlighted yet, and the centred empty state says so
    expect(within(preview).getByText("No file selected")).toBeInTheDocument();
    expect(within(preview).getByText("Select a file to see its preview and details.")).toBeInTheDocument();
    expect(listing().querySelector("[aria-current]")).toBeNull();
    await user.keyboard("j");
    const row = screen.getByRole("button", { name: "b.pdf" }).closest("li")!;
    expect(row).toHaveAttribute("aria-current", "true");
    expect(within(preview).getByRole("heading", { name: "b.pdf" })).toBeInTheDocument();
    // the preview comes before the actions
    const html = preview.innerHTML;
    expect(html.indexOf("Page 1")).toBeGreaterThan(-1);
    expect(html.indexOf("Page 1")).toBeLessThan(html.indexOf("Put in tray"));
  });

  it("after a move the detail of the moved file is gone, and the next step is highlighted and shown", async () => {
    const { user } = setup("10. Financial/Banks");
    await user.click(await screen.findByRole("button", { name: "b.pdf" }));
    act(() => {
      window.dispatchEvent(new CustomEvent(FILES_MOVED_EVENT, { detail: { ids: ["f2"] } }));
    });
    // (the mock listing keeps b.pdf; a real one drops it, and its next row is selected)
    expect(await screen.findByText("No file selected")).toBeInTheDocument();
    await user.keyboard("j");
    const row = screen.getByRole("button", { name: "a.pdf" }).closest("li")!;
    expect(row).toHaveAttribute("aria-current", "true");
    expect(within(screen.getByRole("region", { name: "Preview" })).getByRole("heading", { name: "a.pdf" })).toBeInTheDocument();
  });

  it("folder rows have no selection checkbox but keep the alignment; file rows have one", async () => {
    setup(null);
    await screen.findByText("readme.txt");
    const folder = screen.getByText("10. Financial").closest("li")!;
    expect(within(folder).queryByRole("checkbox")).toBeNull();
    expect(folder.querySelector(".entry-check-spacer")).not.toBeNull();
    expect(within(screen.getByText("readme.txt").closest("li")!).getByRole("checkbox")).toBeInTheDocument();
  });

  it("the hint strip is a wrapping list of key groups", async () => {
    setup(null);
    await screen.findByText("readme.txt");
    const hint = document.querySelector(".browse-keys")!;
    expect(hint).toHaveClass("key-hints");
    expect(within(hint as HTMLElement).getByText("Quick Look", { exact: false })).toBeInTheDocument();
    expect(hint.querySelectorAll(".key-group").length).toBeGreaterThan(5);
  });

  it("the list can be resized with the splitter's arrow keys, and the width is remembered", async () => {
    localStorage.removeItem("dam.browse.listwidth");
    const { user } = setup(null);
    await screen.findByText("readme.txt");
    const bar = screen.getByRole("separator", { name: "Resize the list" });
    expect(bar).toHaveAttribute("aria-valuenow", "45");
    bar.focus();
    await user.keyboard("{ArrowRight}{ArrowRight}");
    expect(bar).toHaveAttribute("aria-valuenow", "49");
    expect(localStorage.getItem("dam.browse.listwidth")).toBe("49");
    localStorage.removeItem("dam.browse.listwidth");
  });

  it("double-clicking the splitter restores the default list width", async () => {
    localStorage.setItem("dam.browse.listwidth", "60");
    const { user } = setup(null);
    await screen.findByText("readme.txt");
    const bar = screen.getByRole("separator", { name: "Resize the list" });
    expect(bar).toHaveAttribute("aria-valuenow", "60");
    await user.dblClick(bar);
    expect(bar).toHaveAttribute("aria-valuenow", "45");
    expect(localStorage.getItem("dam.browse.listwidth")).toBeNull();
  });

  it("the breadcrumb names each folder with a title (long paths are shortened by CSS, never wrapped)", async () => {
    setup("10. Financial/Banks");
    await screen.findByText("a.pdf");
    const crumbs = screen.getByRole("navigation", { name: "Breadcrumb" });
    expect(within(crumbs).getByRole("link", { name: "10. Financial" })).toHaveAttribute("title", "10. Financial");
    expect(within(crumbs).getByText("Banks")).toHaveAttribute("title", "Banks");
  });

  it("with two panes only the active one is marked as active", async () => {
    const { user } = setup(null);
    await screen.findByText("readme.txt");
    await user.click(screen.getByRole("button", { name: "Two panes" }));
    const left = await screen.findByRole("region", { name: "Left pane" });
    const right = screen.getByRole("region", { name: "Right pane" });
    expect(left).toHaveClass("browse-pane-active");
    expect(right).not.toHaveClass("browse-pane-active");
    await user.click(within(right).getByRole("checkbox", { name: "Select readme.txt" }));
    expect(right).toHaveClass("browse-pane-active");
    expect(left).not.toHaveClass("browse-pane-active");
  });
});

describe("New folder", () => {
  beforeEach(() => {
    try {
      localStorage.clear(); // an earlier test may have left two panes on
    } catch {
      // ignore
    }
  });
  const MADE = (folder: string) => ({
    batch_id: "n1",
    dry_run: false,
    done: [{ kind: "mkdir", src: null, dst: folder, drive_id: null, note: null }],
    failed: null,
    error: null,
    index_error: null,
  });
  const newButton = () => screen.getByRole("button", { name: "New folder" });
  const nameField = () => screen.getByRole("textbox", { name: "New folder name" });

  it("makes the folder where the pane is: a name row on top, Enter creates, the new folder is selected, Undo offered", async () => {
    let made = false;
    const { calls, user } = setup("10. Financial", {
      "GET /api/browse": (call) => {
        const rows = LISTINGS[queryOf(call).get("path") ?? ""] ?? [];
        return { body: made ? [...rows, dir("10. Financial/Taxes")] : rows };
      },
      "POST /api/folders/new": () => {
        made = true;
        return { body: MADE("10. Financial/Taxes") };
      },
      "POST /api/activity/n1/undo/preview": {
        body: [{ kind: "remove_empty_dir", src: "10. Financial/Taxes", dst: "10. Financial/Taxes", drive_id: null, note: null }],
      },
      "POST /api/activity/n1/undo": { body: UNDONE },
    });
    await screen.findByRole("list", { name: "Folder contents" });
    await user.click(newButton());
    expect(nameField()).toHaveValue("untitled folder");
    expect(nameField()).toHaveFocus();
    expect((nameField() as HTMLInputElement).selectionStart).toBe(0);
    expect((nameField() as HTMLInputElement).selectionEnd).toBe("untitled folder".length);
    expect(within(listing()).getAllByRole("listitem")[0]).toContainElement(nameField()); // at the top
    await user.keyboard("Taxes{Enter}");
    expect(await screen.findByText("Created folder Taxes")).toBeInTheDocument();
    expect(posts(calls, "/api/folders/new").map((c) => c.body)).toEqual([{ parent: "10. Financial", name: "Taxes" }]);
    expect(screen.queryByRole("textbox", { name: "New folder name" })).not.toBeInTheDocument();
    const row = (await within(listing()).findByText("Taxes")).closest("li")!;
    await waitFor(() => expect(row).toHaveAttribute("aria-current", "true")); // selected
    await user.click(screen.getByRole("button", { name: "Undo" }));
    const confirm = await screen.findByRole("dialog", { name: "Undo these changes?" });
    expect(await within(confirm).findByText("Remove empty folder")).toBeInTheDocument();
    expect(within(confirm).queryByText("New folders it created stay, empty.")).not.toBeInTheDocument();
    await user.click(await undoButton(confirm));
    await waitFor(() => expect(posts(calls, "/api/activity/n1/undo")).toHaveLength(1));
  });

  it("works in an empty folder, and ⇧⌘N opens the row; Esc cancels", async () => {
    const { calls, user } = setup("13. Taxes");
    await screen.findByText("This folder is empty.");
    await user.keyboard("{Meta>}{Shift>}n{/Shift}{/Meta}");
    expect(nameField()).toBeInTheDocument();
    expect(screen.queryByText("This folder is empty.")).not.toBeInTheDocument();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("textbox", { name: "New folder name" })).not.toBeInTheDocument();
    expect(screen.getByText("This folder is empty.")).toBeInTheDocument();
    expect(posts(calls, "/api/folders/new")).toHaveLength(0);
  });

  it("a refusal stays under the name field to fix", async () => {
    const { user } = setup("10. Financial", {
      "POST /api/folders/new": { status: 409, body: { error: "There is already an item named Banks in 10. Financial." } },
    });
    await screen.findByRole("list", { name: "Folder contents" });
    await user.click(newButton());
    await user.keyboard("Banks{Enter}");
    expect(await screen.findByRole("alert")).toHaveTextContent("There is already an item named Banks in 10. Financial.");
    expect(nameField()).toHaveValue("Banks");
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("textbox", { name: "New folder name" })).not.toBeInTheDocument();
  });

  it.each([
    ["##. To Delete/10. Financial", "Folders can't be made in ##. To Delete"],
    ["##. Ongoing/Sauna", "Folders can't be made in ##. Ongoing"],
    ["##. Important", "Folders can't be made in ##. Important"],
  ])("is off at %j with a reason", async (path, reason) => {
    const { user } = setup(path || null, { "GET /api/browse": { body: [] } });
    await screen.findByRole("button", { name: "Two panes" });
    await waitFor(() => expect(newButton().closest(".icon-button-wrap")).toHaveAttribute("data-tip", reason));
    expect(newButton()).toBeDisabled();
    await user.keyboard("{Meta>}{Shift>}n{/Shift}{/Meta}");
    expect(screen.queryByRole("textbox", { name: "New folder name" })).not.toBeInTheDocument();
    expect(await screen.findByText(reason, { selector: ".toast-text" })).toBeInTheDocument();
  });

  it("is off in the Files view, with a collection filter and in search results", async () => {
    const { user } = setup("10. Financial/Banks", {
      "GET /api/collections": { body: [SAUNA] },
      "GET /api/browse/files": { body: { rows: [], total: 0 } },
      "GET /api/search": { body: [] },
    });
    await screen.findByRole("list", { name: "Folder contents" });
    expect(newButton()).toBeEnabled();
    await user.click(screen.getByRole("button", { name: "Files" }));
    await waitFor(() => expect(newButton()).toBeDisabled());
    expect(newButton().closest(".icon-button-wrap")).toHaveAttribute("data-tip", "Switch to Folders to make a folder here");
    await user.click(screen.getByRole("button", { name: "Folders" }));
    await waitFor(() => expect(newButton()).toBeEnabled());
    await user.click(screen.getByRole("button", { name: "Collection" }));
    await user.click(await screen.findByRole("menuitemcheckbox", { name: "Sauna" }));
    await waitFor(() => expect(newButton()).toBeDisabled());
    expect(newButton().closest(".icon-button-wrap")?.getAttribute("data-tip")).toMatch(/^Show all files/);
    await user.click(screen.getByRole("button", { name: "Collection: Sauna" }));
    await user.click(await screen.findByRole("menuitemcheckbox", { name: "All files" }));
    await waitFor(() => expect(newButton()).toBeEnabled());
    await user.type(screen.getByRole("searchbox", { name: "Search" }), "zzz");
    await waitFor(() => expect(newButton()).toBeDisabled());
    expect(newButton().closest(".icon-button-wrap")?.getAttribute("data-tip")).toMatch(/^Search results/);
  });
});

describe("Locked files in Browse", () => {
  const LOCKS = { "GET /api/locks": { body: { files: [{ drive_id: "f1", reason: "file" }], folders: [] } } };
  const REASON = "This file is locked. Unlock it to change it.";

  it("shows the lock on the row, and the bin and Move to… are off with the reason", async () => {
    const { user } = setup("10. Financial/Banks", LOCKS);
    await user.click(await screen.findByRole("checkbox", { name: "Select a.pdf" }));
    const row = rowOf(listing(), "a.pdf");
    expect(await within(row).findByRole("img", { name: "Locked" })).toBeInTheDocument();
    expect(within(rowOf(listing(), "b.pdf")).queryByRole("img", { name: "Locked" })).toBeNull();
    const bin = screen.getByRole("button", { name: "Move to To Delete" });
    expect(bin).toBeDisabled();
    expect(bin.closest(".icon-button-wrap")).toHaveAttribute("data-tip", REASON);
    expect(screen.getByRole("button", { name: "Move to…" })).toBeDisabled();
  });

  it("a locked file dragged onto a folder is not moved", async () => {
    const { calls } = setup("", {
      "GET /api/locks": { body: { files: [{ drive_id: "f0", reason: "file" }], folders: [] } },
      "POST /api/browse/move/preview": { body: [] },
    });
    await screen.findByText("readme.txt");
    await within(rowOf(listing(), "readme.txt")).findByRole("img", { name: "Locked" });
    const dt = dragFrom(rowOf(listing(), "readme.txt"));
    const taxes = rowOf(listing(), "13. Taxes");
    fireEvent.dragEnter(taxes, { dataTransfer: dt });
    expect(taxes).not.toHaveAttribute("data-drop", "over");
    fireEvent.drop(taxes, { dataTransfer: dt });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(posts(calls, "/api/browse/move/preview")).toHaveLength(0);
  });
});
