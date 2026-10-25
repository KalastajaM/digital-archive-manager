/** Browse under ##. To Delete: everything is read-only, and Restore (one file, a
 * selection, a folder) goes through a previewed batch with Undo. */
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it } from "vitest";
import type { DirEntry, FileLinks } from "../api/client";
import { type Call, mockFetch, renderWithProviders } from "../test-utils";
import Browse from "./Browse";

const PATH = "##. To Delete/10. Financial/Banks";
const TIP = "Marked for deletion: restore it first";
const entry = (name: string, id: string, is_dir = false): DirEntry => ({
  name,
  path: `${PATH}/${name}`,
  is_dir,
  is_link: false,
  size: is_dir ? null : 10,
  mtime: 1,
  drive_id: id,
  marks: [],
});
const NO_LINKS: FileLinks = { items: [], collections: [], note: "" };
const posts = (calls: Call[], url: string) => calls.filter((c) => c.method === "POST" && c.url === url);

const restoreRoute = (call: Call) => {
  const { drive_ids, to, dry_run } = call.body as { drive_ids: string[]; to: string; dry_run: boolean };
  const done = [
    ...(to === "original"
      ? [{ kind: "mkdir", src: null, dst: "10. Financial/Banks", drive_id: null, note: "create missing folder" }]
      : []),
    ...drive_ids.map((id) => ({
      kind: "move",
      src: `${PATH}/${id}.pdf`,
      dst: to === "inbox" ? `##. Organize/${id}.pdf` : `10. Financial/Banks/${id}_2.pdf`,
      drive_id: id,
      note: to === "original" ? "renamed to avoid collision" : null,
    })),
  ];
  return { body: { batch_id: dry_run ? "dry" : "r1", dry_run, done, failed: null, error: null, index_error: null } };
};

function setup(extra: Parameters<typeof mockFetch>[0] = {}) {
  const calls = mockFetch({
    "GET /api/browse": { body: [entry("Old", "d1", true), entry("a.pdf", "f1"), entry("b.pdf", "f2")] },
    "GET /api/activity": { body: [] },
    "GET /api/status": {
      body: { special_folders: { inbox: "##. Organize", ongoing: "##. Ongoing", important: "##. Important", quarantine: "##. To Delete" } },
    },
    "GET /api/files/f1/links": { body: NO_LINKS },
    "GET /api/files/f1/summary": { body: { ai: null, user: null } },
    "GET /api/notes/file/f1": { body: { text: "kept note" } },
    "POST /api/restore": restoreRoute,
    ...extra,
  });
  const user = userEvent.setup();
  renderWithProviders(
    <MemoryRouter initialEntries={[`/browse?path=${encodeURIComponent(PATH)}`]}>
      <Routes>
        <Route path="/browse" element={<Browse />} />
      </Routes>
    </MemoryRouter>,
  );
  return { calls, user };
}

// a disabled button is wrapped by the element that carries the reason
const tip = (name: string) => screen.getByRole("button", { name }).parentElement;

describe("Files in To Delete are read-only", () => {
  it("the file view turns every action off, with the reason as the tooltip", async () => {
    const { user } = setup();
    await user.click(await screen.findByText("a.pdf"));
    const preview = await screen.findByRole("region", { name: "Preview" });
    expect(within(preview).getByRole("button", { name: "Star" })).toBeDisabled();
    expect(within(preview).getByRole("button", { name: "Mark Important" })).toBeDisabled();
    expect(within(preview).getByRole("button", { name: "Star" }).parentElement).toHaveAttribute("data-tip", TIP);
    expect(within(preview).getByRole("combobox", { name: "Add to collection" })).toBeDisabled();
    const tray = within(preview).getByRole("button", { name: "Put in tray" });
    expect(tray).toBeDisabled();
    expect(tray.parentElement).toHaveAttribute("data-tip", TIP);
    expect(within(preview).getByRole("button", { name: "Back to inbox" })).toBeDisabled();
    expect(await within(preview).findByRole("button", { name: "Write a summary" })).toBeDisabled();
    expect(within(preview).getByRole("textbox", { name: "Note on this file" })).toBeDisabled();
    expect(within(preview).getByRole("combobox", { name: /Add a tag/ })).toBeDisabled();
  });

  it("the selection's actions are off too; Restore is offered instead", async () => {
    const { user } = setup();
    await screen.findByText("a.pdf");
    await user.click(screen.getByRole("checkbox", { name: "Select a.pdf" }));
    await user.click(screen.getByRole("checkbox", { name: "Select b.pdf" }));
    for (const name of ["Star", "Mark Important", "From…", "For…", "Move to…"]) {
      expect(screen.getByRole("button", { name })).toBeDisabled();
    }
    expect(tip("Star")).toHaveAttribute("data-tip", TIP);
    expect(tip("Move to…")).toHaveAttribute("data-tip", TIP);
    expect(screen.getByRole("button", { name: "Restore from To Delete" })).toBeEnabled();
  });
});

describe("Restore", () => {
  it("one file: previews the batch, restores it, and the toast's Undo goes through the undo confirm", async () => {
    const { calls, user } = setup({
      "POST /api/activity/r1/undo/preview": {
        body: [{ kind: "move", src: "10. Financial/Banks/f1_2.pdf", dst: `${PATH}/f1.pdf`, drive_id: "f1", note: null }],
      },
    });
    await user.click(await screen.findByText("a.pdf"));
    const preview = await screen.findByRole("region", { name: "Preview" });
    await user.click(within(preview).getByRole("button", { name: "Restore to where it was" }));
    const dialog = await screen.findByRole("dialog", { name: "Restore from To Delete?" });
    expect(posts(calls, "/api/restore").map((c) => c.body)).toEqual([{ drive_ids: ["f1"], to: "original", dry_run: true }]);
    expect(dialog).toHaveTextContent("New folder");
    expect(dialog).toHaveTextContent("renamed to avoid collision");
    expect(dialog).toHaveTextContent(/Undo puts it back in To Delete/);
    await user.click(within(dialog).getByRole("button", { name: "Restore to where it was" }));
    await waitFor(() => expect(posts(calls, "/api/restore")).toHaveLength(2));
    expect(posts(calls, "/api/restore")[1].body).toEqual({ drive_ids: ["f1"], to: "original", dry_run: false });
    expect(await screen.findByText("Restored f1_2.pdf from To Delete")).toBeInTheDocument();
    await user.click(await screen.findByRole("button", { name: "Undo" }));
    const confirm = await screen.findByRole("dialog", { name: "Undo these changes?" });
    await waitFor(() => expect(confirm).toHaveTextContent("10. Financial/Banks/f1_2.pdf"));
  });

  it("a selection: Restore to Inbox restores every checked item in one batch", async () => {
    const { calls, user } = setup();
    await screen.findByText("a.pdf");
    await user.click(screen.getByRole("checkbox", { name: "Select all files" }));
    await user.click(screen.getByRole("button", { name: "Restore from To Delete" }));
    await user.click(await screen.findByRole("menuitem", { name: "Restore to Inbox" }));
    const dialog = await screen.findByRole("dialog", { name: "Restore from To Delete?" });
    expect(posts(calls, "/api/restore")[0].body).toEqual({ drive_ids: ["f1", "f2"], to: "inbox", dry_run: true });
    expect(dialog).toHaveTextContent(/These 2 move out of To Delete into the inbox/);
    await user.click(within(dialog).getByRole("button", { name: "Restore to Inbox" }));
    await waitFor(() => expect(posts(calls, "/api/restore")).toHaveLength(2));
    expect(posts(calls, "/api/restore")[1].body).toEqual({ drive_ids: ["f1", "f2"], to: "inbox", dry_run: false });
    expect(await screen.findByText("Restored 2 files from To Delete to the inbox")).toBeInTheDocument();
  });

  it("a folder marked for deletion is restored from its context menu, or from its panel", async () => {
    const { calls, user } = setup();
    await screen.findByText("a.pdf");
    fireEvent.contextMenu(screen.getByText("Old"));
    await user.click(await screen.findByRole("menuitem", { name: "Restore to where it was" }));
    const dialog = await screen.findByRole("dialog", { name: "Restore from To Delete?" });
    expect(posts(calls, "/api/restore")[0].body).toEqual({ drive_ids: ["d1"], to: "original", dry_run: true });
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
    // the folder under the cursor shows its panel with the same two buttons
    await user.keyboard("j");
    const panel = await screen.findByRole("region", { name: "Preview" });
    await user.click(within(panel).getByRole("button", { name: "Restore to Inbox" }));
    await screen.findByRole("dialog", { name: "Restore from To Delete?" });
    expect(posts(calls, "/api/restore")[1].body).toEqual({ drive_ids: ["d1"], to: "inbox", dry_run: true });
  });

  it("cancelling the confirm restores nothing", async () => {
    const { calls, user } = setup();
    await user.click(await screen.findByText("a.pdf"));
    const preview = await screen.findByRole("region", { name: "Preview" });
    await user.click(within(preview).getByRole("button", { name: "Restore to Inbox" }));
    const dialog = await screen.findByRole("dialog", { name: "Restore from To Delete?" });
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(posts(calls, "/api/restore")).toHaveLength(1); // the dry run only
  });

  it("a refusal is said in a toast and nothing is applied", async () => {
    const { calls, user } = setup({
      "POST /api/restore": { status: 400, body: { error: "a.pdf: it stood at the top of the archive; restore it to the inbox" } },
    });
    await user.click(await screen.findByText("a.pdf"));
    const preview = await screen.findByRole("region", { name: "Preview" });
    await user.click(within(preview).getByRole("button", { name: "Restore to where it was" }));
    expect(await screen.findByText(/Not restored: .*stood at the top of the archive/)).toBeInTheDocument();
    expect(screen.queryByRole("dialog", { name: "Restore from To Delete?" })).not.toBeInTheDocument();
    expect(posts(calls, "/api/restore")).toHaveLength(1);
  });
});
