import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it } from "vitest";
import type { DirEntry, ResolvedOp } from "../api/client";
import { DRAG_TYPE } from "../dnd";
import { type Call, mockFetch, renderWithProviders, undoButton } from "../test-utils";
import Browse from "./Browse";
import Inbox from "./Inbox";

const SPECIAL = { inbox: "##. Organize", ongoing: "##. Ongoing", important: "##. Important", quarantine: "##. To Delete" };
const status = (inbox_exists = true) => ({
  files: 0,
  indexed: 0,
  pending: 0,
  cloud_pending: 0,
  errors: 0,
  unsupported: 0,
  missing: 0,
  inbox_count: 0,
  rule_errors: [],
  tray_errors: [],
  recovery_pending: 0,
  archive_available: true,
  special_folders: SPECIAL,
  inbox_exists,
});
const batch = (id: string, done: ResolvedOp[] = []) => ({ batch_id: id, dry_run: false, done, failed: null, error: null, index_error: null });
const mkdir = (dst: string): ResolvedOp => ({ kind: "mkdir", src: null, dst, drive_id: null, note: "create missing folder" });
const dir = (path: string): DirEntry => ({ name: path.slice(path.lastIndexOf("/") + 1), path, is_dir: true, is_link: false, size: null, mtime: 1, drive_id: `id-${path}`, marks: [] });
const posts = (calls: Call[], url: string) => calls.filter((c) => c.method === "POST" && c.url.split("?")[0] === url);

// -- the inbox: how documents get in ----------------------------------------------------

function renderInbox(inboxExists: boolean, extra: Parameters<typeof mockFetch>[0] = {}) {
  const calls = mockFetch({
    "GET /api/inbox": { body: [] },
    "GET /api/status": { body: status(inboxExists) },
    "GET /api/trays": { body: { trays: [], errors: [] } },
    "GET /api/activity": { body: [] },
    ...extra,
  });
  renderWithProviders(
    <MemoryRouter initialEntries={["/inbox"]}>
      <Inbox />
    </MemoryRouter>,
  );
  return calls;
}

describe("the empty inbox", () => {
  it("explains how documents get in and offers to show the folder and to choose files", async () => {
    const user = userEvent.setup();
    const calls = renderInbox(true, { "POST /api/folders/reveal": { status: 204, body: null } });
    expect(await screen.findByText("The inbox is empty.")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("##. Organize")).toBeInTheDocument());
    expect(screen.getByText(/Put new files in/)).toHaveTextContent(/drag them there in .+, or point your scanner at it/);
    await user.click(screen.getByRole("button", { name: /^Show (in |folder)/ }));
    await waitFor(() => expect(posts(calls, "/api/folders/reveal")).toHaveLength(1));
    expect(posts(calls, "/api/folders/reveal")[0].body).toEqual({ path: "##. Organize" });
    expect(screen.getByRole("button", { name: /Choose files…/ })).toBeEnabled();
  });

  it("copies the chosen files into the inbox and offers Undo", async () => {
    const user = userEvent.setup();
    const calls = renderInbox(true, {
      "POST /api/inbox/upload": () => ({ body: batch("u1", [{ kind: "copy", src: "abs:/tmp/scan.pdf", dst: "##. Organize/scan.pdf", drive_id: null, note: null }]) }),
      "POST /api/activity/u1/undo/preview": { body: [{ kind: "quarantine", src: "##. Organize/scan.pdf", dst: "##. To Delete/##. Organize/scan.pdf", drive_id: null, note: null }] },
      "POST /api/activity/u1/undo": { body: { ...batch("undo1"), follow_up_error: null, kept: [] } },
    });
    await screen.findByText("The inbox is empty.");
    const file = new File(["%PDF-1.4 x"], "scan.pdf", { type: "application/pdf" });
    fireEvent.change(screen.getByTestId("add-files-input"), { target: { files: [file] } });
    expect(await screen.findByText("Copied 1 file into the inbox.")).toBeInTheDocument();
    const upload = posts(calls, "/api/inbox/upload")[0];
    expect(upload.url).toBe("/api/inbox/upload?name=scan.pdf");
    expect(upload.headers["Content-Type"]).toBe("application/octet-stream");
    expect(upload.body).toBe(file);
    await user.click(screen.getByRole("button", { name: "Undo" }));
    const dialog = await screen.findByRole("dialog", { name: "Undo these changes?" });
    expect(await within(dialog).findByText("Move to To Delete")).toBeInTheDocument();
    await user.click(await undoButton(dialog));
    await waitFor(() => expect(posts(calls, "/api/activity/u1/undo")).toHaveLength(1));
  });

  it("names the files that were refused and does not send an oversized one", async () => {
    const calls = renderInbox(true, {
      "POST /api/inbox/upload": () => ({ status: 413, body: { error: "That file is larger than 200 MB." } }),
    });
    await screen.findByText("The inbox is empty.");
    const small = new File(["x"], "a.pdf");
    const huge = new File(["x"], "huge.bin");
    Object.defineProperty(huge, "size", { value: 201 * 1024 * 1024 });
    fireEvent.change(screen.getByTestId("add-files-input"), { target: { files: [huge, small] } });
    const toast = await screen.findByText(/Not copied:/);
    expect(toast).toHaveTextContent("huge.bin: larger than 200 MB");
    expect(toast).toHaveTextContent("a.pdf: That file is larger than 200 MB.");
    expect(posts(calls, "/api/inbox/upload")).toHaveLength(1); // the oversized file never left
  });

  it("says when the inbox folder is not there yet and offers to set the folders up", async () => {
    const user = userEvent.setup();
    renderInbox(false, {
      "GET /api/layout/templates": { body: { templates: [], special_folders: [] } },
    });
    expect(await screen.findByText("The inbox folder is not there yet.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Choose files/ })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Set up folders…" }));
    expect(await screen.findByRole("dialog", { name: "Set up folders" })).toBeInTheDocument();
  });
});

/** A file or folder as the browser's entries API hands a Finder drop over. */
type FakeEntry = { name: string; isFile: boolean; isDirectory: boolean; file?: (ok: (f: File) => void) => void; createReader?: () => unknown };
const fileEntry = (name: string): FakeEntry => ({ name, isFile: true, isDirectory: false, file: (ok) => ok(new File(["x"], name)) });
const folderEntry = (name: string, children: FakeEntry[]): FakeEntry => ({
  name,
  isFile: false,
  isDirectory: true,
  createReader: () => {
    let read = false; // one batch, then the empty one that ends it
    return { readEntries: (ok: (e: FakeEntry[]) => void) => ok(read ? [] : ((read = true), children)) };
  },
});
/** The drag data of a drop from Finder: the type "Files" and one item per dropped entry. */
const finderDrop = (entries: FakeEntry[]) => ({
  types: ["Files"],
  items: entries.map((e) => ({ kind: "file", webkitGetAsEntry: () => e })),
  files: [],
  effectAllowed: "all",
  dropEffect: "none",
});
const uploaded = (calls: Call[]) => posts(calls, "/api/inbox/upload").map((c) => new URL(c.url, "http://x").searchParams.get("name"));

describe("dropping from Finder on the inbox list", () => {
  const upload = { "POST /api/inbox/upload": () => ({ body: batch("u1") }) };

  it("copies dropped files and every file in a dropped folder, flat, leaving out hidden ones", async () => {
    const calls = renderInbox(true, upload);
    await screen.findByText("The inbox is empty.");
    const list = screen.getByRole("navigation", { name: "Inbox" });
    const dt = finderDrop([
      fileEntry("bill.pdf"),
      folderEntry("Scans", [fileEntry("a.pdf"), fileEntry(".DS_Store"), folderEntry("2026", [fileEntry("b.pdf")]), folderEntry(".git", [fileEntry("c")])]),
    ]);
    fireEvent.dragEnter(list, { dataTransfer: dt });
    expect(list).toHaveAttribute("data-drop", "over");
    fireEvent.drop(list, { dataTransfer: dt });
    expect(await screen.findByText(/Copied 3 files into the inbox\. Left out 2 hidden files\./)).toBeInTheDocument();
    expect(uploaded(calls)).toEqual(["bill.pdf", "a.pdf", "b.pdf"]);
  });

  it("ignores a drag of the app's own documents", async () => {
    const calls = renderInbox(true, upload);
    await screen.findByText("The inbox is empty.");
    const list = screen.getByRole("navigation", { name: "Inbox" });
    const dt = { ...finderDrop([fileEntry("x.pdf")]), types: [DRAG_TYPE], getData: () => JSON.stringify({ ids: ["f1"] }) };
    fireEvent.dragEnter(list, { dataTransfer: dt });
    expect(list).not.toHaveAttribute("data-drop");
    fireEvent.drop(list, { dataTransfer: dt });
    await new Promise((r) => setTimeout(r, 20));
    expect(posts(calls, "/api/inbox/upload")).toHaveLength(0);
  });

  it("refuses a drop of too many files, sending none", async () => {
    const calls = renderInbox(true, upload);
    await screen.findByText("The inbox is empty.");
    const many = Array.from({ length: 101 }, (_, i) => fileEntry(`f${i}.pdf`));
    fireEvent.drop(screen.getByRole("navigation", { name: "Inbox" }), { dataTransfer: finderDrop([folderEntry("Documents", many)]) });
    expect(await screen.findByText(/Not copied: that is 101 files; drop at most 100 at a time\./)).toBeInTheDocument();
    expect(posts(calls, "/api/inbox/upload")).toHaveLength(0);
  });

  it("refuses a drop while the inbox folder does not exist", async () => {
    const calls = renderInbox(false, { ...upload, "GET /api/layout/templates": { body: { templates: [], special_folders: [] } } });
    await screen.findByText("The inbox folder is not there yet.");
    const list = screen.getByRole("navigation", { name: "Inbox" });
    const dt = finderDrop([fileEntry("bill.pdf")]);
    fireEvent.dragEnter(list, { dataTransfer: dt });
    expect(list).toHaveAttribute("data-drop", "refused");
    expect(list).toHaveAttribute("data-tip", "The inbox folder does not exist yet");
    fireEvent.drop(list, { dataTransfer: dt });
    await new Promise((r) => setTimeout(r, 20));
    expect(posts(calls, "/api/inbox/upload")).toHaveLength(0);
  });
});

// -- Browse: New folder and Set up folders ----------------------------------------------------

const TEMPLATES = {
  templates: [
    {
      id: "household",
      title: "Household",
      description: "Finance, bills and more.",
      folders: [
        { key: "finance", name: "Finance" },
        { key: "bills", name: "Bills & Receipts" },
      ],
    },
    { id: "empty", title: "Empty", description: "Only the special folders.", folders: [] },
  ],
  special_folders: [
    { role: "inbox", title: "Inbox", name: "##. Organize", purpose: "New documents wait here until you file them." },
    { role: "ongoing", title: "Ongoing", name: "##. Ongoing", purpose: "Shortcuts to the collections you are working on now." },
    { role: "important", title: "Important", name: "##. Important", purpose: "Shortcuts to the key documents you must not lose." },
    { role: "quarantine", title: "To delete", name: "##. To Delete", purpose: "Files you mark for deletion wait here instead." },
  ],
};
const LAYOUT_PREVIEW = {
  folders: [
    { path: "##. Organize", role: "inbox", title: "Inbox", exists: false },
    { path: "10. Finance", role: "layout", title: "Finance", exists: false },
    { path: "11. Bills & Receipts", role: "layout", title: "Bills & Receipts", exists: true },
  ],
  to_create: 2,
  label: "Created the archive layout (2 folders)",
  ops: [],
  rule_ids: [],
  rules_seedable: false,
};

function renderBrowse(root: DirEntry[], extra: Parameters<typeof mockFetch>[0] = {}, path = "") {
  const calls = mockFetch({
    "GET /api/browse": (call) => ({ body: new URL(call.url, "http://x").searchParams.get("path") === "" ? root : [] }),
    "GET /api/activity": { body: [] },
    "GET /api/status": { body: status() },
    "GET /api/collections": { body: [] },
    ...extra,
  });
  renderWithProviders(
    <MemoryRouter initialEntries={[path ? `/browse?path=${encodeURIComponent(path)}` : "/browse"]}>
      <Routes>
        <Route path="/browse" element={<Browse />} />
      </Routes>
    </MemoryRouter>,
  );
  return calls;
}

describe("Browse in a new archive", () => {
  it("says the archive has no folders and offers Set up folders and New folder", async () => {
    renderBrowse([]);
    expect(await screen.findByText("This archive has no folders yet.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Set up folders…" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "New folder…" })).toBeInTheDocument(); // here: the sheet
    expect(screen.getByRole("button", { name: "New folder" })).toBeInTheDocument(); // toolbar: a row in the list
  });

  it("sets up folders from a layout: previewed, special names fixed, one batch, with Undo", async () => {
    const user = userEvent.setup();
    const calls = renderBrowse([], {
      "GET /api/layout/templates": { body: TEMPLATES },
      "POST /api/layout/preview": { body: LAYOUT_PREVIEW },
      "POST /api/layout": { body: { batch: batch("l1"), created: 2, rules_written: false, rule_ids: [], rules_error: null, error: null } },
    });
    await user.click(await screen.findByRole("button", { name: "Set up folders…" }));
    const dialog = await screen.findByRole("dialog", { name: "Set up folders" });
    const preview = await within(dialog).findByRole("region", { name: "Folders that will be made" });
    expect(within(preview).getByText("2 folders will be made")).toBeInTheDocument();
    expect(within(preview).getByText(/already there, left as it is/)).toBeInTheDocument();
    for (const input of within(within(dialog).getByRole("list", { name: "Special folders" })).getAllByRole("textbox")) {
      expect(input).toBeDisabled(); // inside the running app the names are the configured ones
    }
    await user.click(within(dialog).getByRole("checkbox", { name: /Number the folders/ }));
    const button = await within(dialog).findByRole("button", { name: "Make 2 folders" });
    await waitFor(() => expect(button).toBeEnabled());
    await user.click(button);
    expect(await screen.findByText("Made 2 folders.")).toBeInTheDocument();
    expect(posts(calls, "/api/layout")[0].body).toEqual({
      template: "household",
      numbered: false,
      folders: [
        { key: "finance", name: "Finance" },
        { key: "bills", name: "Bills & Receipts" },
      ],
    });
    expect(screen.getByRole("button", { name: "Undo" })).toBeInTheDocument();
  });

  it("New folder… in an empty archive: previews, refuses a bad name, makes it and offers Undo", async () => {
    const user = userEvent.setup();
    const calls = renderBrowse([], {
      "POST /api/folders/new/preview": (call) => {
        const { name } = call.body as { name: string };
        return name.includes("/")
          ? { status: 400, body: { error: "A folder name cannot contain / or \\ . Make one folder at a time." } }
          : { body: [mkdir(name)] };
      },
      "POST /api/folders/new": { body: batch("n1", [mkdir("Taxes")]) },
      "POST /api/activity/n1/undo/preview": { body: [{ kind: "remove_empty_dir", src: "Taxes", dst: "Taxes", drive_id: null, note: null }] },
      "POST /api/activity/n1/undo": { body: { ...batch("undo-n1"), follow_up_error: null, kept: ["Taxes"] } },
    });
    await user.click(await screen.findByRole("button", { name: "New folder…" }));
    const dialog = await screen.findByRole("dialog", { name: "New folder" });
    expect(within(dialog).getByText(/at the top of the archive/)).toBeInTheDocument();
    const make = within(dialog).getByRole("button", { name: "Make folder" });
    expect(make).toBeDisabled();
    await user.type(within(dialog).getByLabelText("Folder name"), "a/b");
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("one folder at a time");
    expect(make).toBeDisabled();
    await user.clear(within(dialog).getByLabelText("Folder name"));
    await user.type(within(dialog).getByLabelText("Folder name"), "Taxes");
    expect(await within(dialog).findByText("New folder")).toBeInTheDocument(); // the previewed op
    await waitFor(() => expect(make).toBeEnabled());
    await user.click(make);
    expect(await screen.findByText("Made the folder Taxes.")).toBeInTheDocument();
    expect(posts(calls, "/api/folders/new")[0].body).toEqual({ parent: "", name: "Taxes" });
    await user.click(screen.getByRole("button", { name: "Undo" }));
    const undo = await screen.findByRole("dialog", { name: "Undo these changes?" });
    expect(await within(undo).findByText(/Only folders that are still empty are removed/)).toBeInTheDocument();
    await user.click(await undoButton(undo));
    expect(await screen.findByText(/something in them now and stays: Taxes/)).toBeInTheDocument();
  });

  it("New folder from the toolbar: a name row in the folder being browsed, made at once", async () => {
    const user = userEvent.setup();
    const calls = renderBrowse(
      [dir("10. Financial")],
      {
        "GET /api/browse": (call) => ({ body: new URL(call.url, "http://x").searchParams.get("path") === "10. Financial" ? [dir("10. Financial/Banks")] : [dir("10. Financial")] }),
        "POST /api/folders/new": (call) =>
          (call.body as { name: string }).name.includes("/")
            ? { status: 400, body: { error: "A folder name cannot contain / or \\ . Make one folder at a time." } }
            : { body: batch("n2", [mkdir("10. Financial/2026")]) },
      },
      "10. Financial",
    );
    await screen.findByText("Banks");
    await user.click(screen.getByRole("button", { name: "New folder" }));
    const field = screen.getByRole("textbox", { name: "New folder name" });
    await user.clear(field);
    await user.type(field, "a/b{Enter}");
    expect(await screen.findByRole("alert")).toHaveTextContent("one folder at a time");
    await user.clear(field);
    await user.type(field, "2026{Enter}");
    expect(await screen.findByText("Created folder 2026")).toBeInTheDocument();
    expect(posts(calls, "/api/folders/new").map((c) => c.body)).toEqual([
      { parent: "10. Financial", name: "a/b" },
      { parent: "10. Financial", name: "2026" },
    ]);
  });

  it("the context menu of a folder makes a folder inside it", async () => {
    const user = userEvent.setup();
    renderBrowse([dir("13. Taxes")], { "POST /api/folders/new/preview": { body: [mkdir("13. Taxes/x")] } });
    const row = (await screen.findByText("13. Taxes")).closest("li")!;
    fireEvent.contextMenu(row, { clientX: 40, clientY: 40 });
    const menu = await screen.findByRole("menu", { name: "13. Taxes actions" });
    await user.click(within(menu).getByRole("menuitem", { name: "New folder inside 13. Taxes…" }));
    const dialog = await screen.findByRole("dialog", { name: "New folder" });
    expect(within(dialog).getByText(/inside 13\. Taxes/)).toBeInTheDocument();
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });
});
