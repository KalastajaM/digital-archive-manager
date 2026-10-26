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
  name: path.slice(path.lastIndexOf("/") + 1), path, is_dir: false, is_link: false, size: 1, mtime: 1, drive_id, connected: true, marks: [],
});
const dir = (path: string): DirEntry => ({
  name: path.slice(path.lastIndexOf("/") + 1), path, is_dir: true, is_link: false, size: null, mtime: 1, drive_id: `id-${path}`, connected: true, marks: [],
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
