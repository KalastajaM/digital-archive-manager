/** Right-click menus in Browse: a file row has the header's file actions plus Add tag… and
 * Add to collection… and acts on the selection as Finder does; a folder (in the list or the
 * folder tree) has New folder inside, Move to…, Move to To Delete and Show in Finder. */
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import type { DirEntry } from "../api/client";
import { useContextMenuKeys } from "../contextMenus";
import { type Call, mockFetch, renderWithProviders } from "../test-utils";
import Browse from "./Browse";

const entry = (path: string, drive_id: string, is_dir = false): DirEntry => ({
  name: path.slice(path.lastIndexOf("/") + 1),
  path,
  is_dir,
  is_link: false,
  size: is_dir ? null : 10,
  mtime: 1,
  drive_id,
  connected: true,
  marks: [],
  open_items: [],
});
const BANKS = "10. Financial/Banks";
const GONE = "##. To Delete/10. Financial";
const LISTINGS: Record<string, DirEntry[]> = {
  "": [entry("10. Financial", "d0", true), entry("##. To Delete", "dq", true)],
  "10. Financial": [entry(BANKS, "d1", true)],
  [BANKS]: [entry(`${BANKS}/Old`, "d2", true), entry(`${BANKS}/a.pdf`, "f1"), entry(`${BANKS}/b.pdf`, "f2"), entry(`${BANKS}/c.pdf`, "f3")],
  [GONE]: [entry(`${GONE}/x.pdf`, "fx")],
};
const STATUS = { special_folders: { inbox: "##. Organize", ongoing: "##. Ongoing", important: "##. Important", quarantine: "##. To Delete" } };
const queryOf = (call: Call) => new URL(call.url, "http://x").searchParams;
const posts = (calls: Call[], url: string) => calls.filter((c) => c.method === "POST" && c.url === url);
const op = { kind: "quarantine", src: `${BANKS}/a.pdf`, dst: `##. To Delete/${BANKS}/a.pdf`, drive_id: "f1", note: null };
const dryRun = { body: { batch_id: "dry", dry_run: true, done: [op], failed: null, error: null, index_error: null } };

function Keys() {
  useContextMenuKeys();
  return null;
}

function setup(path = BANKS) {
  const calls = mockFetch({
    "GET /api/browse": (call) => ({ body: LISTINGS[queryOf(call).get("path") ?? ""] ?? [] }),
    "GET /api/collections": { body: [] },
    "GET /api/activity": { body: [] },
    "GET /api/status": { body: STATUS },
    "GET /api/trays": { body: { trays: [{ id: "pay", name: "To pay" }] } },
    "GET /api/tags/all": { body: { tags: [{ name: "bank", files: 1, pinned: false, group_id: null }], groups: [] } },
    "POST /api/quarantine": dryRun,
    "POST /api/files/d2/reveal": { body: null },
  });
  const user = userEvent.setup();
  renderWithProviders(
    <MemoryRouter initialEntries={[`/browse?path=${encodeURIComponent(path)}`]}>
      <Keys />
      <Routes>
        <Route path="/browse" element={<Browse />} />
      </Routes>
    </MemoryRouter>,
  );
  return { calls, user };
}

const names = (menu: HTMLElement) =>
  Array.from(menu.querySelectorAll('[role^="menuitem"]')).map((b) => b.querySelector(".menu-item-text")?.firstChild?.textContent);
const list = () => screen.getByLabelText("Folder contents");
const inList = (name: string) => within(list()).getByText(name);
const row = (name: string) => inList(name).closest("li") as HTMLElement;

beforeEach(() => {
  localStorage.clear();
});
afterEach(() => {
  cleanup();
});

describe("A file row's right-click menu", () => {
  it("selects an unselected row, then offers the header's actions plus Add tag… and Add to collection…", async () => {
    const { user } = setup();
    await screen.findByRole("checkbox", { name: "Select a.pdf" });
    fireEvent.contextMenu(inList("b.pdf"), { clientX: 40, clientY: 40 });
    const menu = await screen.findByRole("menu", { name: "Actions for b.pdf" });
    expect(row("b.pdf")).toHaveAttribute("aria-current", "true");
    expect(names(menu)).toEqual([
      "Put in To pay",
      "Move to…",
      "Back to inbox",
      "From…",
      "For…",
      "Ask AI",
      "Add tag…",
      "Add to collection…",
      "Star",
      "Mark Important",
      "Move to To Delete",
    ]);
    await user.click(within(menu).getByRole("menuitem", { name: "Add tag…" }));
    expect(await screen.findByRole("dialog", { name: "Add a tag to b.pdf" })).toBeInTheDocument();
  });

  it("on a checked row acts on the whole selection; on another row, selects only that one", async () => {
    const { calls, user } = setup();
    await user.click(await screen.findByRole("checkbox", { name: "Select a.pdf" }));
    await user.click(screen.getByRole("checkbox", { name: "Select b.pdf" }));
    fireEvent.contextMenu(inList("a.pdf"));
    const menu = await screen.findByRole("menu", { name: "Actions for 2 selected files" });
    await user.click(within(menu).getByRole("menuitem", { name: "Move 2 to To Delete" }));
    await waitFor(() => expect(posts(calls, "/api/quarantine")).toHaveLength(1));
    expect(posts(calls, "/api/quarantine")[0].body).toEqual({ drive_ids: ["f1", "f2"], dry_run: true });
    await user.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Cancel" }));
    fireEvent.contextMenu(inList("c.pdf"));
    await screen.findByRole("menu", { name: "Actions for c.pdf" });
    expect(screen.getByRole("checkbox", { name: "Select a.pdf" })).not.toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Select b.pdf" })).not.toBeChecked();
  });

  it("disabled entries say why, as the header's icons do (a file in To Delete)", async () => {
    setup(GONE);
    fireEvent.contextMenu(await screen.findByText("x.pdf"));
    const menu = await screen.findByRole("menu", { name: "Actions for x.pdf" });
    const move = within(menu).getByRole("menuitem", { name: /Move to…/ });
    expect(move).toBeDisabled();
    expect(move).toHaveAccessibleDescription("Marked for deletion: restore it first");
    expect(names(menu)).toContain("Restore to where it was");
  });

  it("Shift+F10 on the focused row opens the same menu", async () => {
    const { user } = setup();
    await user.click(await screen.findByRole("checkbox", { name: "Select a.pdf" }));
    await user.click(screen.getByRole("checkbox", { name: "Select a.pdf" }));
    (row("a.pdf").querySelector("button.entry") as HTMLElement).focus();
    await user.keyboard("{Shift>}{F10}{/Shift}");
    expect(await screen.findByRole("menu", { name: "Actions for a.pdf" })).toBeInTheDocument();
  });
});

describe("A folder's right-click menu", () => {
  it("in the list: New folder inside, Move to…, Move to To Delete, Show in Finder", async () => {
    const { calls, user } = setup();
    await screen.findByRole("checkbox", { name: "Select a.pdf" });
    fireEvent.contextMenu(inList("Old"));
    const menu = await screen.findByRole("menu", { name: "Actions for Old" });
    expect(names(menu)).toEqual(["New folder inside Old…", "Move to…", "Move to To Delete", "Show in Finder"]);
    await user.click(within(menu).getByRole("menuitem", { name: "Show in Finder" }));
    await waitFor(() => expect(posts(calls, "/api/files/d2/reveal")).toHaveLength(1));
    fireEvent.contextMenu(inList("Old"));
    await user.click(await screen.findByRole("menuitem", { name: "Move to To Delete" }));
    await waitFor(() => expect(posts(calls, "/api/quarantine")).toHaveLength(1));
    expect(posts(calls, "/api/quarantine")[0].body).toEqual({ drive_ids: ["d2"], dry_run: true });
  });

  it("in the folder tree: the same menu, also from the keyboard; Move to… opens its sheet", async () => {
    const { user } = setup();
    const tree = await screen.findByRole("tree", { name: "Folder tree" });
    const banks = await within(tree).findByRole("treeitem", { name: "Banks" });
    banks.focus();
    await user.keyboard("{Shift>}{F10}{/Shift}");
    const menu = await screen.findByRole("menu", { name: "Actions for Banks" });
    expect(names(menu)).toEqual(["New folder inside Banks…", "Move to…", "Move to To Delete", "Show in Finder"]);
    await user.click(within(menu).getByRole("menuitem", { name: "Move to…" }));
    expect(await screen.findByRole("dialog", { name: "Move Banks to…" })).toBeInTheDocument();
  });

  it("the app's own folders cannot move: their entries say why", async () => {
    setup();
    const tree = await screen.findByRole("tree", { name: "Folder tree" });
    fireEvent.contextMenu(await within(tree).findByRole("treeitem", { name: "##. To Delete" }));
    const menu = await screen.findByRole("menu", { name: "Actions for ##. To Delete" });
    for (const name of [/New folder inside/, /Move to…/]) {
      const entry = within(menu).getByRole("menuitem", { name });
      expect(entry).toBeDisabled();
      expect(entry).toHaveAccessibleDescription(/.+/);
    }
    // To Delete itself is no folder marked for deletion: nothing to restore, and it stays
    expect(names(menu)).not.toContain("Restore to where it was");
    const bin = within(menu).getByRole("menuitem", { name: /Move to To Delete/ });
    expect(bin).toBeDisabled();
    expect(bin).toHaveAccessibleDescription("The app keeps this folder in place");
  });
});
