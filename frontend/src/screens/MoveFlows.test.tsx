/** Browse and the sidebar Inbox each run a move flow: one move at a time across both,
 * and toast actions stay blocked while either one has a confirm or a call open. */
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it } from "vitest";
import type { DirEntry } from "../api/client";
import { ToastProvider, useBlockToastActions, useToast } from "../components/Toasts";
import { Sidebar } from "../components/ui/Sidebar";
import { type Call, dataTransfer, deferred, mockFetch, renderWithProviders } from "../test-utils";
import Browse from "./Browse";

const SPECIAL = { inbox: "##. Organize", ongoing: "##. Ongoing", important: "##. Important", quarantine: "##. To Delete" };
const file = (path: string, drive_id: string): DirEntry => ({
  name: path.slice(path.lastIndexOf("/") + 1), path, is_dir: false, is_link: false, size: 1, mtime: 1, drive_id, connected: true, marks: [], open_items: [],
});
const dir = (path: string): DirEntry => ({
  name: path.slice(path.lastIndexOf("/") + 1), path, is_dir: true, is_link: false, size: null, mtime: 1, drive_id: `id-${path}`, connected: true, marks: [], open_items: [],
});
const LISTING = [dir("13. Taxes"), file("a.pdf", "f1"), file("b.pdf", "f2")];
const op = (id: string, dst: string) => ({ kind: "move", src: `${id}.pdf`, dst, drive_id: id, note: null });
const result = (ops: unknown[], folder: string) => ({
  batch_id: "m1", dry_run: false, done: ops, failed: null, error: null, index_error: null, unchanged: [], folder,
});
const posts = (calls: Call[], url: string) => calls.filter((c) => c.method === "POST" && c.url === url);

function setup(extra: Parameters<typeof mockFetch>[0] = {}) {
  const calls = mockFetch({
    "GET /api/status": { body: { inbox_count: 1, special_folders: SPECIAL } },
    "GET /api/today": { body: { attention: [], overview: { inbox: 0, trays: [], collections: [] } } },
    "GET /api/trays": { body: { trays: [], errors: [] } },
    "GET /api/collections": { body: [] },
    "GET /api/browse": { body: LISTING },
    "GET /api/activity": { body: [] },
    ...extra,
  });
  renderWithProviders(
    <MemoryRouter initialEntries={["/browse"]}>
      <Sidebar />
      <Routes>
        <Route path="/browse" element={<Browse />} />
      </Routes>
    </MemoryRouter>,
  );
  return { calls, user: userEvent.setup() };
}

const listing = () => screen.getByRole("list", { name: "Folder contents" });
const rowOf = (name: string) => within(listing()).getByText(name).closest("li")!;
const inboxRow = () => within(screen.getByRole("navigation", { name: "Main" })).findByRole("link", { name: "Inbox (1)" });
function drag(from: HTMLElement, to: HTMLElement) {
  const dt = dataTransfer();
  fireEvent.dragStart(from, { dataTransfer: dt });
  fireEvent.dragEnter(to, { dataTransfer: dt });
  fireEvent.dragOver(to, { dataTransfer: dt });
  fireEvent.drop(to, { dataTransfer: dt });
  document.dispatchEvent(new Event("dragend"));
}

afterEach(() => document.dispatchEvent(new Event("dragend")));

describe("move flows in Browse and the sidebar", () => {
  it("Browse finishing during a Sidebar drop keeps the toasts blocked", async () => {
    const { user } = setup({
      "POST /api/browse/move/preview": (call) => {
        const body = call.body as { drive_ids: string[]; folder: string };
        return { body: [op(body.drive_ids[0], `${body.folder}/${body.drive_ids[0]}.pdf`)] };
      },
      "POST /api/browse/move": { body: result([op("f2", "13. Taxes/f2.pdf")], "13. Taxes") },
    });
    await screen.findByText("a.pdf");
    // the sidebar drop: its confirm stays open
    drag(rowOf("a.pdf"), await inboxRow());
    const inboxConfirm = await screen.findByRole("dialog", { name: "Move 1 file to ##. Organize?" });
    // meanwhile a Browse move runs to the end and offers Undo
    drag(rowOf("b.pdf"), rowOf("13. Taxes"));
    const browseConfirm = await screen.findByRole("dialog", { name: "Move 1 file to 13. Taxes?" });
    await user.click(within(browseConfirm).getByRole("button", { name: "Move" }));
    const undo = await screen.findByRole("button", { name: "Undo" });
    // Browse released its block; the sidebar's confirm still holds one
    expect(undo).toBeDisabled();
    await user.click(within(inboxConfirm).getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Undo" })).toBeEnabled());
  });

  it("a move across disks says Copy and move, and hands over to the progress view", async () => {
    const started: string[] = [];
    const listen = (e: Event) => started.push((e as CustomEvent<string>).detail);
    window.addEventListener("dam:copy-job-started", listen);
    const copy = { kind: "copy_across", src: "b.pdf", dst: "13. Taxes/b.pdf", drive_id: "f2", note: null, size: 1, cloud_only: false };
    const aside = { kind: "quarantine", src: "b.pdf", dst: "##. To Delete/b.pdf", drive_id: "f2", note: "copied to 13. Taxes/b.pdf" };
    const { user } = setup({
      "POST /api/browse/move/preview": { body: [copy, aside] },
      "POST /api/browse/move": { body: { ...result([], "13. Taxes"), batch_id: "", job_id: "j9" } },
    });
    await screen.findByText("b.pdf");
    drag(rowOf("b.pdf"), rowOf("13. Taxes"));
    const confirm = await screen.findByRole("dialog", { name: "Move 1 file to 13. Taxes?" });
    expect(within(confirm).getByText(/Copies 1 file \(1 bytes\) to another disk/)).toBeInTheDocument();
    await user.click(within(confirm).getByRole("button", { name: "Copy and move" }));
    await waitFor(() => expect(started).toEqual(["j9"]));
    expect(screen.queryByText(/^Moved /)).toBeNull(); // the progress view says when it is done
    window.removeEventListener("dam:copy-job-started", listen);
  });

  it("the sidebar Inbox refuses a drop while a Browse move is running", async () => {
    const held = deferred<{ body: unknown }>();
    const { calls } = setup({ "POST /api/browse/move/preview": () => held.promise });
    await screen.findByText("a.pdf");
    drag(rowOf("b.pdf"), rowOf("13. Taxes")); // Browse's preview is in flight
    await waitFor(() => expect(posts(calls, "/api/browse/move/preview")).toHaveLength(1));
    const inbox = await inboxRow();
    const dt = dataTransfer();
    fireEvent.dragStart(rowOf("a.pdf"), { dataTransfer: dt });
    fireEvent.dragEnter(inbox, { dataTransfer: dt });
    expect(inbox).toHaveAttribute("data-drop", "refused");
    expect(inbox).toHaveAttribute("data-tip", "Another move is still running");
    fireEvent.drop(inbox, { dataTransfer: dt });
    await act(async () => held.resolve({ body: [] }));
    expect(posts(calls, "/api/browse/move/preview")).toHaveLength(1);
  });
});

describe("moving a folder in Browse", () => {
  const TO_PAY = { id: "to-pay", name: "To pay", order: 1, item_title: "{name}", fields: {}, date_field: null, done: { label: "Mark paid", fields: {} } };
  const LISTINGS: Record<string, DirEntry[]> = {
    "": [dir("20. Home"), dir("Old years")],
    "20. Home": [dir("20. Home/2009"), dir("20. Home/2010")],
    "20. Home/2009": [dir("20. Home/2009/sub"), file("20. Home/2009/a.pdf", "fa")],
    "Old years": [dir("Old years/1990s")],
    "Old years/1990s": [],
  };
  const FOLDER = "id-20. Home/2009";
  const moveOp = { kind: "move", src: "20. Home/2009", dst: "Old years/2009", drive_id: FOLDER, note: null };
  const acrossOps = [
    { kind: "mkdir", src: null, dst: "Old years/2009", drive_id: null, note: null },
    { kind: "copy_across", src: "20. Home/2009/a.pdf", dst: "Old years/2009/a.pdf", drive_id: "fa", note: null, size: 1, cloud_only: false },
    { kind: "quarantine", src: "20. Home/2009", dst: "##. To Delete/20. Home/2009", drive_id: FOLDER, note: "copied to Old years/2009" },
  ];

  function open(url: string, extra: Parameters<typeof mockFetch>[0] = {}) {
    const calls = mockFetch({
      "GET /api/status": { body: { inbox_count: 1, special_folders: SPECIAL } },
      "GET /api/today": { body: { attention: [], overview: { inbox: 0, trays: [], collections: [] } } },
      "GET /api/trays": { body: { trays: [TO_PAY], errors: [] } },
      "GET /api/collections": { body: [] },
      "GET /api/browse": (call) => ({ body: LISTINGS[new URL(call.url, "http://x").searchParams.get("path") ?? ""] ?? [] }),
      "GET /api/activity": { body: [] },
      "GET /api/folders": { body: [] },
      [`GET /api/files/${encodeURIComponent(FOLDER)}/links`]: { body: { items: [], collections: [], note: "" } },
      ...extra,
    });
    renderWithProviders(
      <MemoryRouter initialEntries={[url]}>
        <Sidebar />
        <Routes>
          <Route path="/browse" element={<Browse />} />
        </Routes>
      </MemoryRouter>,
    );
    return { calls, user: userEvent.setup() };
  }
  const twoPanes = (left: string, right: string) => `/browse?left=${encodeURIComponent(left)}&right=${encodeURIComponent(right)}`;
  const pane = (name: "Left pane" | "Right pane") => screen.getByRole("region", { name });
  const rowIn = (scope: HTMLElement, name: string) => within(scope).getByText(name).closest("li")!;
  const folderDrag = (row: HTMLElement) => {
    const dt = dataTransfer({ protectedMode: true }); // hovering: only the types are readable
    fireEvent.dragStart(row, { dataTransfer: dt });
    return dt;
  };
  const nav = () => screen.getByRole("navigation", { name: "Main" });

  it("a folder row, the other pane and a breadcrumb take it; a tray, the Inbox and the sidebar do not", async () => {
    open(twoPanes("20. Home", "Old years/1990s"));
    const left = pane("Left pane");
    await within(left).findByText("2009");
    const right = pane("Right pane");
    const targets = [
      rowIn(left, "2010"),
      within(right).getByTestId("pane-drop"),
      within(within(right).getByRole("navigation", { name: "Breadcrumb" })).getByRole("link", { name: "Old years" }),
    ];
    for (const target of targets) {
      const dt = folderDrag(rowIn(left, "2009"));
      fireEvent.dragEnter(target, { dataTransfer: dt });
      expect(target).toHaveAttribute("data-drop", "over");
      fireEvent.dragOver(target, { dataTransfer: dt });
      expect(dt.dropEffect).toBe("move");
      document.dispatchEvent(new Event("dragend"));
    }
    const sidebar = [
      await within(nav()).findByRole("link", { name: "To pay" }),
      await inboxRow(),
      within(nav()).getByRole("link", { name: "Browse" }),
    ];
    for (const target of sidebar) {
      const dt = folderDrag(rowIn(left, "2009"));
      expect(fireEvent.dragEnter(target, { dataTransfer: dt })).toBe(true); // not taken
      expect(target).not.toHaveAttribute("data-drop");
      document.dispatchEvent(new Event("dragend"));
    }
  });

  it("a refused breadcrumb says why in a toast too", async () => {
    const { calls } = open("/browse?path=20.%20Home");
    await screen.findByText("2009");
    const top = within(screen.getByRole("navigation", { name: "Breadcrumb" })).getByRole("link", { name: "Archive" });
    const dt = folderDrag(rowIn(listing(), "2009"));
    fireEvent.dragEnter(top, { dataTransfer: dt });
    expect(top).toHaveAttribute("data-drop", "refused");
    fireEvent.drop(top, { dataTransfer: dt });
    expect(await screen.findByText("Not allowed: a folder is not moved to the top of the archive")).toBeInTheDocument();
    expect(posts(calls, "/api/browse/move/preview")).toHaveLength(0);
  });

  it("dropped into itself or its own subfolder, it is refused before the drop", async () => {
    const { calls } = open(twoPanes("20. Home", "20. Home/2009"));
    const left = pane("Left pane");
    await within(left).findByText("2009");
    const right = pane("Right pane");
    await within(right).findByText("sub");
    for (const target of [rowIn(right, "sub"), within(right).getByTestId("pane-drop"), rowIn(left, "2009")]) {
      const dt = folderDrag(rowIn(left, "2009"));
      fireEvent.dragEnter(target, { dataTransfer: dt });
      expect(target).toHaveAttribute("data-drop", "refused");
      expect(target).toHaveAttribute("data-tip", "Cannot move a folder into itself");
      fireEvent.drop(target, { dataTransfer: dt });
      document.dispatchEvent(new Event("dragend"));
    }
    expect((await screen.findAllByText("Cannot move a folder into itself")).length).toBeGreaterThan(0); // the toast
    expect(posts(calls, "/api/browse/move/preview")).toHaveLength(0);
  });

  it("a drop on one disk previews a move of that folder alone and confirms with Move folder", async () => {
    const { calls, user } = open(twoPanes("20. Home", "Old years"), {
      "POST /api/browse/move/preview": { body: [moveOp] },
      "POST /api/browse/move": { body: result([moveOp], "Old years") },
    });
    const left = pane("Left pane");
    await within(left).findByText("2009");
    const right = pane("Right pane");
    await within(right).findByText("1990s");
    drag(rowIn(left, "2009"), within(right).getByTestId("pane-drop"));
    const confirm = await screen.findByRole("dialog", { name: "Move 2009 to Old years?" });
    expect(posts(calls, "/api/browse/move/preview").map((c) => c.body)).toEqual([{ drive_ids: [FOLDER], folder: "Old years" }]);
    await user.click(within(confirm).getByRole("button", { name: /^Move folder/ }));
    await waitFor(() => expect(posts(calls, "/api/browse/move")).toHaveLength(1));
    expect(posts(calls, "/api/browse/move")[0].body).toEqual({ drive_ids: [FOLDER], folder: "Old years" });
    expect(await screen.findByText("Moved folder 2009 to Old years")).toBeInTheDocument();
  });

  it("the folder's panel has Move to…: picking Old years previews it, and across disks the confirm says Copy and move", async () => {
    const started: string[] = [];
    const listen = (e: Event) => started.push((e as CustomEvent<string>).detail);
    window.addEventListener("dam:copy-job-started", listen);
    const { calls, user } = open("/browse?path=20.%20Home", {
      "POST /api/browse/move/preview": { body: acrossOps },
      "POST /api/browse/move": { body: { ...result([], "Old years"), batch_id: "", job_id: "j9" } },
    });
    await screen.findByText("2009");
    await user.keyboard("{ArrowDown}"); // the cursor on 2009: its panel
    const panel = screen.getByRole("region", { name: "Preview" });
    const button = await within(panel).findByRole("button", { name: "Move to…" });
    expect(button).toBeEnabled();
    expect(button.tagName).toBe("BUTTON"); // a plain button: Tab reaches it
    await user.click(button);
    const sheet = await screen.findByRole("dialog", { name: "Move 2009 to…" });
    await user.type(within(sheet).getByRole("combobox", { name: "Folder" }), "Old years");
    await user.click(within(sheet).getByRole("button", { name: "Preview move" }));
    const confirm = await screen.findByRole("dialog", { name: "Move 2009 to Old years?" });
    expect(posts(calls, "/api/browse/move/preview").map((c) => c.body)).toEqual([{ drive_ids: [FOLDER], folder: "Old years" }]);
    expect(within(confirm).getByText(/Copies 1 folder and 1 file \(1 bytes\) to 'Old years'/)).toBeInTheDocument();
    await user.click(within(confirm).getByRole("button", { name: /^Copy and move/ }));
    await waitFor(() => expect(started).toEqual(["j9"]));
    window.removeEventListener("dam:copy-job-started", listen);
  });

  it("Move to… is off, with the reason, for a folder the app keeps in place", async () => {
    const top = LISTINGS[""];
    LISTINGS[""] = [dir("##. Organize")];
    try {
      const { user } = open("/browse?path=", {
        [`GET /api/files/${encodeURIComponent("id-##. Organize")}/links`]: { body: { items: [], collections: [], note: "" } },
      });
      expect((await screen.findAllByText("##. Organize")).length).toBeGreaterThan(0); // in the tree and the list
      await user.keyboard("{ArrowDown}");
      const panel = screen.getByRole("region", { name: "Preview" });
      const button = await within(panel).findByRole("button", { name: "Move to…" });
      expect(button).toBeDisabled();
      expect(button.closest(".button-wrap")).toHaveAttribute("data-tip", "The app keeps this folder in place");
    } finally {
      LISTINGS[""] = top;
    }
  });
});

describe("useBlockToastActions", () => {
  function Blocker({ label }: { label: string }) {
    const [on, setOn] = useState(false);
    useBlockToastActions(on);
    return (
      <button type="button" onClick={() => setOn((v) => !v)}>
        {label}
      </button>
    );
  }
  function Toaster() {
    const toast = useToast();
    return (
      <button type="button" onClick={() => toast({ kind: "info", text: "hi", action: { label: "Act", run: () => {} } })}>
        toast
      </button>
    );
  }

  it("counts blockers: actions stay disabled until every blocker lets go", async () => {
    const user = userEvent.setup();
    render(
      <ToastProvider>
        <Blocker label="one" />
        <Blocker label="two" />
        <Toaster />
      </ToastProvider>,
    );
    await user.click(screen.getByRole("button", { name: "toast" }));
    const act_ = () => screen.getByRole("button", { name: "Act" });
    await user.click(screen.getByRole("button", { name: "one" }));
    await user.click(screen.getByRole("button", { name: "two" }));
    expect(act_()).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "one" })); // one lets go
    expect(act_()).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "two" }));
    expect(act_()).toBeEnabled();
  });
});
