/** Dropping files on a folder in Browse: Move / Link / Copy, Option for Copy, rows of
 * ##. Ongoing / ##. Important / ##. To Delete as sources, the visible reason on a refused
 * target (and a toast when dropped anyway), and the collection folders in ##. Ongoing. */
import { createEvent, fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it } from "vitest";
import type { CollectionRow, DirEntry, FileLinks, ResolvedOp } from "../api/client";
import { type Call, dataTransfer, mockFetch, renderWithProviders } from "../test-utils";
import {
  ADD_FROM_OWN_FOLDER,
  ALREADY_HERE,
  DELETE_TARGET_REASON,
  IMPORTANT_MOVE_REASON,
  IMPORTANT_TARGET_REASON,
  LINK_OFF_REASON,
  ONGOING_ROOT_REASON,
  SEARCH_DROP_REASON,
} from "../dropModes";
import { folderMoveRequest } from "../components/MoveTo";
import Browse from "./Browse";

const dir = (path: string): DirEntry => ({
  name: path.slice(path.lastIndexOf("/") + 1),
  path,
  is_dir: true,
  is_link: false,
  size: null,
  mtime: 1,
  drive_id: `d-${path}`,
  connected: true, marks: [], open_items: [],
});
const file = (path: string, drive_id: string, is_link = false): DirEntry => ({
  name: path.slice(path.lastIndexOf("/") + 1),
  path,
  is_dir: false,
  is_link,
  size: 10,
  mtime: 1,
  drive_id,
  connected: true, marks: [], open_items: [],
});

const LISTINGS: Record<string, DirEntry[]> = {
  "": [dir("10. Financial"), dir("13. Taxes"), dir("##. Ongoing"), dir("##. Important"), dir("##. To Delete")],
  "10. Financial": [dir("10. Financial/Banks"), file("10. Financial/x.pdf", "fx")],
  "10. Financial/Banks": [file("10. Financial/Banks/a.pdf", "f1"), file("10. Financial/Banks/b.pdf", "f2")],
  "##. Ongoing": [dir("##. Ongoing/Sauna")],
  "##. Ongoing/Sauna": [file("##. Ongoing/Sauna/a.pdf", "l1", true)],
  "##. Important": [file("##. Important/passport.pdf", "i1", true)],
  "##. To Delete/10. Financial": [file("##. To Delete/10. Financial/old.pdf", "t1")],
};
const SAUNA: CollectionRow = {
  id: 7,
  name: "Sauna",
  state: "open",
  created: 1,
  closed_at: null,
  publish: { ongoing: true },
  ongoing_rel: "##. Ongoing/Sauna",
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
const NO_LINKS: FileLinks = { items: [], collections: [], note: "" };
const queryOf = (call: Call) => new URL(call.url, "http://x").searchParams;
const posts = (calls: Call[], url: string) => calls.filter((c) => c.method === "POST" && c.url === url);
const op = (kind: ResolvedOp["kind"], src: string, dst: string, drive_id: string): ResolvedOp => ({ kind, src, dst, drive_id, note: null });
const result = (done: ResolvedOp[], extra: Record<string, unknown> = {}) => ({
  batch_id: "b1",
  dry_run: false,
  done,
  failed: null,
  error: null,
  index_error: null,
  unchanged: [],
  folder: "13. Taxes",
  ...extra,
});

function setup(url: string, extra: Parameters<typeof mockFetch>[0] = {}, status: Record<string, unknown> = {}) {
  const calls = mockFetch({
    "GET /api/browse": (call) => ({ body: LISTINGS[queryOf(call).get("path") ?? ""] ?? [] }),
    "GET /api/activity": { body: [] },
    "GET /api/status": {
      body: {
        special_folders: { inbox: "##. Organize", ongoing: "##. Ongoing", important: "##. Important", quarantine: "##. To Delete" },
        ...status,
      },
    },
    "GET /api/collections": { body: [SAUNA] },
    "GET /api/files/f1/links": { body: NO_LINKS },
    "GET /api/notes/file/f1": { body: { text: "" } },
    ...extra,
  });
  const user = userEvent.setup();
  renderWithProviders(
    <MemoryRouter initialEntries={[url]}>
      <Routes>
        <Route path="/browse" element={<Browse />} />
      </Routes>
    </MemoryRouter>,
  );
  return { calls, user };
}
const one = (path: string) => `/browse?path=${encodeURIComponent(path)}`;
const two = (left: string, right: string) => `/browse?left=${encodeURIComponent(left)}&right=${encodeURIComponent(right)}`;

const listing = () => screen.getByRole("list", { name: "Folder contents" });
const pane = (name: "Left pane" | "Right pane") => screen.getByRole("region", { name });
const rowOf = (scope: HTMLElement, name: string) => within(scope).getByText(name).closest("li")!;
function dragFrom(row: HTMLElement) {
  const dt = dataTransfer();
  fireEvent.dragStart(row, { dataTransfer: dt });
  return dt;
}
// jsdom has no DragEvent, so the modifier key is put on the event by hand
function fire(type: "dragEnter" | "dragOver" | "drop", target: HTMLElement, dt: ReturnType<typeof dataTransfer>, alt: boolean) {
  const event = createEvent[type](target, { dataTransfer: dt });
  Object.defineProperty(event, "altKey", { value: alt });
  return fireEvent(target, event);
}
function dropOn(target: HTMLElement, dt: ReturnType<typeof dataTransfer>, alt = false) {
  fire("dragEnter", target, dt, alt);
  fire("dragOver", target, dt, alt);
  return fire("drop", target, dt, alt);
}
const FILES = "application/x-dam-files";
const SPECIAL = "application/x-dam-special";

afterEach(() => {
  document.dispatchEvent(new Event("dragend"));
});

const BANKS = "10. Financial/Banks";
const MOVE = [op("move", "10. Financial/x.pdf", `${BANKS}/x.pdf`, "fx")];
const LINK = [op("symlink", "10. Financial/x.pdf", `${BANKS}/x.pdf`, "fx")];
const COPY = [op("copy", "10. Financial/x.pdf", `${BANKS}/x.pdf`, "fx")];
const byMode = (call: Call) => {
  const mode = (call.body as { mode?: string }).mode;
  return { body: mode === "link" ? LINK : mode === "copy" ? COPY : MOVE };
};
const radio = (dialog: HTMLElement, name: string) => within(dialog).getByRole("radio", { name: new RegExp(`^${name}`) });

describe("Move / Link / Copy on a drop", () => {
  it("offers Move (the default), Link and Copy; Copy is marked not recommended", async () => {
    const { calls } = setup(one("10. Financial"), { "POST /api/browse/move/preview": byMode });
    await screen.findByText("x.pdf");
    dropOn(rowOf(listing(), "Banks"), dragFrom(rowOf(listing(), "x.pdf")));
    const dialog = await screen.findByRole("dialog", { name: `Move 1 file to ${BANKS}?` });
    expect(radio(dialog, "Move")).toBeChecked();
    expect(radio(dialog, "Link")).not.toBeChecked();
    expect(radio(dialog, "Copy")).not.toBeChecked();
    expect(radio(dialog, "Link")).toBeEnabled();
    expect(within(dialog).getByText("not recommended: makes a duplicate")).toBeInTheDocument();
    // a plain move sends no mode, as it always did
    expect(posts(calls, "/api/browse/move/preview").map((c) => c.body)).toEqual([{ drive_ids: ["fx"], folder: BANKS }]);
  });

  it("says in a line of its own that holding Option picks Copy", async () => {
    setup(one("10. Financial"), { "POST /api/browse/move/preview": byMode });
    await screen.findByText("x.pdf");
    dropOn(rowOf(listing(), "Banks"), dragFrom(rowOf(listing(), "x.pdf")));
    const dialog = await screen.findByRole("dialog", { name: `Move 1 file to ${BANKS}?` });
    const note = within(dialog).getByText("Holding ⌥ while dropping picks Copy.");
    expect(note).toHaveClass("drop-mode-note");
    expect(note.tagName).toBe("P");
  });

  it("choosing Link previews it again, applies the link and offers Undo", async () => {
    const { calls, user } = setup(one("10. Financial"), {
      "POST /api/browse/move/preview": byMode,
      "POST /api/browse/move": { body: result(LINK, { folder: BANKS }) },
    });
    await screen.findByText("x.pdf");
    dropOn(rowOf(listing(), "Banks"), dragFrom(rowOf(listing(), "x.pdf")));
    const dialog = await screen.findByRole("dialog", { name: `Move 1 file to ${BANKS}?` });
    await user.click(radio(dialog, "Link"));
    const linked = await screen.findByRole("dialog", { name: `Link 1 file in ${BANKS}?` });
    expect(posts(calls, "/api/browse/move/preview").map((c) => c.body)).toEqual([
      { drive_ids: ["fx"], folder: BANKS },
      { drive_ids: ["fx"], folder: BANKS, mode: "link" },
    ]);
    expect(radio(linked, "Link")).toBeChecked();
    expect(linked).toHaveTextContent("the file itself stays where it is");
    expect(posts(calls, "/api/browse/move")).toHaveLength(0); // a drop never changes anything by itself
    await user.click(within(linked).getByRole("button", { name: /Make links/ }));
    await waitFor(() => expect(posts(calls, "/api/browse/move")).toHaveLength(1));
    expect(posts(calls, "/api/browse/move")[0].body).toEqual({ drive_ids: ["fx"], folder: BANKS, mode: "link" });
    expect(await screen.findByText(`Linked x.pdf in ${BANKS}`)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Undo" })).toBeInTheDocument();
  });

  it("holding Option at the drop preselects Copy", async () => {
    const { calls, user } = setup(one("10. Financial"), {
      "POST /api/browse/move/preview": byMode,
      "POST /api/browse/move": { body: result(COPY, { folder: BANKS }) },
    });
    await screen.findByText("x.pdf");
    dropOn(rowOf(listing(), "Banks"), dragFrom(rowOf(listing(), "x.pdf")), true);
    const dialog = await screen.findByRole("dialog", { name: `Copy 1 file to ${BANKS}?` });
    expect(radio(dialog, "Copy")).toBeChecked();
    expect(posts(calls, "/api/browse/move/preview").map((c) => c.body)).toEqual([
      { drive_ids: ["fx"], folder: BANKS, mode: "copy" },
    ]);
    expect(dialog).toHaveTextContent("Undo moves the copies to To Delete");
    await user.click(within(dialog).getByRole("button", { name: /^Copy/ }));
    await waitFor(() => expect(posts(calls, "/api/browse/move")).toHaveLength(1));
    expect(posts(calls, "/api/browse/move")[0].body).toEqual({ drive_ids: ["fx"], folder: BANKS, mode: "copy" });
    expect(await screen.findByText(`Copied x.pdf to ${BANKS}`)).toBeInTheDocument();
  });

  it("Link is off, with the reason, where the computer cannot make links", async () => {
    setup(one("10. Financial"), { "POST /api/browse/move/preview": byMode }, { can_link: false });
    await screen.findByText("x.pdf");
    await waitFor(() => expect(screen.getByRole("list", { name: "Folder contents" })).toBeInTheDocument());
    // the status has loaded once Banks accepts the drop
    await waitFor(() => {
      const dt = dragFrom(rowOf(listing(), "x.pdf"));
      dropOn(rowOf(listing(), "Banks"), dt);
      expect(screen.getByRole("dialog")).toBeInTheDocument();
    });
    const dialog = screen.getByRole("dialog");
    expect(radio(dialog, "Link")).toBeDisabled();
    expect(within(dialog).getByText(LINK_OFF_REASON)).toBeInTheDocument();
    expect(radio(dialog, "Copy")).toBeEnabled();
  });

  it("a way that cannot be previewed says why in the sheet, which stays open on Move", async () => {
    const { user } = setup(one("10. Financial"), {
      "POST /api/browse/move/preview": (call) =>
        (call.body as { mode?: string }).mode === "link" ? { status: 400, body: { error: "links cannot be made here" } } : { body: MOVE },
    });
    await screen.findByText("x.pdf");
    dropOn(rowOf(listing(), "Banks"), dragFrom(rowOf(listing(), "x.pdf")));
    const dialog = await screen.findByRole("dialog", { name: `Move 1 file to ${BANKS}?` });
    await user.click(radio(dialog, "Link"));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("Cannot link: links cannot be made here");
    expect(radio(dialog, "Move")).toBeChecked();
  });
});

describe("Dropping on the file's own folder", () => {
  it("is refused for a plain drop: the reason shows on the pane and in a toast", async () => {
    const { calls } = setup(one("10. Financial"), { "POST /api/browse/move/preview": byMode });
    await screen.findByText("x.pdf");
    const zone = screen.getByTestId("pane-drop");
    const dt = dragFrom(rowOf(listing(), "x.pdf"));
    fireEvent.dragEnter(zone, { dataTransfer: dt });
    expect(zone).toHaveAttribute("data-drop", "refused");
    expect(within(zone).getByRole("status")).toHaveTextContent(ALREADY_HERE);
    fireEvent.drop(zone, { dataTransfer: dt });
    expect(await screen.findAllByText(new RegExp(`^${ALREADY_HERE}`))).not.toHaveLength(0);
    expect(posts(calls, "/api/browse/move/preview")).toHaveLength(0);
  });

  it("with Option it offers Copy only (a numbered name); Move and Link say why they are off", async () => {
    const copy = [op("copy", "10. Financial/x.pdf", "10. Financial/x_2.pdf", "fx")];
    const { calls } = setup(one("10. Financial"), {
      "POST /api/browse/move/preview": { body: copy },
    });
    await screen.findByText("x.pdf");
    dropOn(screen.getByTestId("pane-drop"), dragFrom(rowOf(listing(), "x.pdf")), true);
    const dialog = await screen.findByRole("dialog", { name: "Copy 1 file to 10. Financial?" });
    expect(radio(dialog, "Move")).toBeDisabled();
    expect(radio(dialog, "Link")).toBeDisabled();
    expect(within(dialog).getAllByText(ALREADY_HERE)).toHaveLength(2);
    expect(radio(dialog, "Copy")).toBeChecked();
    expect(dialog).toHaveTextContent("x.pdf → 10. Financial/x_2.pdf");
    expect(posts(calls, "/api/browse/move/preview")[0].body).toEqual({ drive_ids: ["fx"], folder: "10. Financial", mode: "copy" });
  });
});

describe("Rows of ##. Ongoing, ##. Important and ##. To Delete as sources", () => {
  it("an Ongoing row drags as special and moves the real file: the sheet names where it is now", async () => {
    const real = [op("move", `${BANKS}/a.pdf`, "13. Taxes/a.pdf", "f1")];
    const { calls } = setup(two("##. Ongoing/Sauna", "13. Taxes"), { "POST /api/browse/move/preview": { body: real } });
    const left = pane("Left pane");
    await within(left).findByText("a.pdf");
    const row = rowOf(left, "a.pdf");
    expect(row).toHaveAttribute("draggable", "true");
    const dt = dragFrom(row);
    expect(Object.keys(dt.data)).toContain(SPECIAL);
    expect(Object.keys(dt.data)).not.toContain(FILES); // the sidebar's collections, trays and Inbox never see it
    dropOn(within(pane("Right pane")).getByTestId("pane-drop"), dt);
    const dialog = await screen.findByRole("dialog", { name: "Move 1 file to 13. Taxes?" });
    expect(posts(calls, "/api/browse/move/preview")[0].body).toEqual({ drive_ids: ["l1"], folder: "13. Taxes" });
    expect(dialog).toHaveTextContent("This moves the filed document itself");
    expect(dialog).toHaveTextContent(`currently in ${BANKS}`);
    expect(dialog).toHaveTextContent("It stays in its collections, and the link in Ongoing follows");
    expect(dialog).toHaveTextContent(`a.pdf → 13. Taxes/a.pdf`);
  });

  it("Link and Copy of an Ongoing row act on the original", async () => {
    const real = [op("copy", `${BANKS}/a.pdf`, "13. Taxes/a.pdf", "f1")];
    const { calls } = setup(two("##. Ongoing/Sauna", "13. Taxes"), { "POST /api/browse/move/preview": { body: real } });
    const left = pane("Left pane");
    await within(left).findByText("a.pdf");
    dropOn(within(pane("Right pane")).getByTestId("pane-drop"), dragFrom(rowOf(left, "a.pdf")), true);
    const dialog = await screen.findByRole("dialog", { name: "Copy 1 file to 13. Taxes?" });
    expect(posts(calls, "/api/browse/move/preview")[0].body).toEqual({ drive_ids: ["l1"], folder: "13. Taxes", mode: "copy" });
    expect(dialog).toHaveTextContent(`The copy is made from the filed document itself (in ${BANKS})`);
  });

  it("an Important row: Move is refused with the reason, Link is preselected", async () => {
    const link = [op("symlink", `${BANKS}/p.pdf`, "13. Taxes/p.pdf", "p0")];
    const { calls } = setup(two("##. Important", "13. Taxes"), { "POST /api/browse/move/preview": { body: link } });
    const left = pane("Left pane");
    await within(left).findByText("passport.pdf");
    await waitFor(() => {
      dropOn(within(pane("Right pane")).getByTestId("pane-drop"), dragFrom(rowOf(left, "passport.pdf")));
      expect(screen.getByRole("dialog")).toBeInTheDocument();
    });
    const dialog = screen.getByRole("dialog", { name: "Link 1 file in 13. Taxes?" });
    expect(radio(dialog, "Move")).toBeDisabled();
    expect(within(dialog).getByText(IMPORTANT_MOVE_REASON)).toBeInTheDocument();
    expect(radio(dialog, "Link")).toBeChecked();
    expect(radio(dialog, "Copy")).toBeEnabled();
    expect(posts(calls, "/api/browse/move/preview")[0].body).toMatchObject({ drive_ids: ["i1"], mode: "link" });
  });

  it("a To Delete row dropped on a folder is a restore into it, with no Link or Copy", async () => {
    const restored = [op("move", "##. To Delete/10. Financial/old.pdf", "13. Taxes/old.pdf", "t1")];
    const { calls, user } = setup(two("##. To Delete/10. Financial", "13. Taxes"), {
      "POST /api/restore": (call) => ({
        body: { batch_id: (call.body as { dry_run: boolean }).dry_run ? "dry" : "r1", dry_run: (call.body as { dry_run: boolean }).dry_run, done: restored, failed: null, error: null, index_error: null },
      }),
    });
    const left = pane("Left pane");
    await within(left).findByText("old.pdf");
    const dt = dragFrom(rowOf(left, "old.pdf"));
    expect(Object.keys(dt.data)).toContain(SPECIAL);
    await waitFor(() => {
      dropOn(within(pane("Right pane")).getByTestId("pane-drop"), dt);
      expect(screen.getByRole("dialog")).toBeInTheDocument();
    });
    const dialog = screen.getByRole("dialog", { name: "Restore from To Delete to 13. Taxes?" });
    expect(within(dialog).queryByRole("radio")).toBeNull(); // no Link or Copy
    expect(dialog).toHaveTextContent("Undo puts it back in To Delete");
    expect(posts(calls, "/api/restore")[0].body).toEqual({ drive_ids: ["t1"], to: "folder", folder: "13. Taxes", dry_run: true });
    await user.click(within(dialog).getByRole("button", { name: "Restore here" }));
    await waitFor(() => expect(posts(calls, "/api/restore")).toHaveLength(2));
    expect(posts(calls, "/api/restore")[1].body).toEqual({ drive_ids: ["t1"], to: "folder", folder: "13. Taxes", dry_run: false });
    expect(await screen.findByText("Restored old.pdf from To Delete to 13. Taxes")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Undo" })).toBeInTheDocument();
  });
});

describe("Refused targets say why, visibly, and a drop there says it in a toast", () => {
  it.each([
    ["##. Ongoing", ONGOING_ROOT_REASON],
    ["##. To Delete", DELETE_TARGET_REASON],
    ["##. Important", IMPORTANT_TARGET_REASON],
  ])("%s", async (name, reason) => {
    const { calls } = setup(two("10. Financial", ""));
    const left = pane("Left pane");
    await within(left).findByText("x.pdf");
    const right = pane("Right pane");
    await within(right).findByText(name);
    const row = rowOf(right, name);
    const dt = dragFrom(rowOf(left, "x.pdf"));
    fireEvent.dragEnter(row, { dataTransfer: dt });
    fireEvent.dragOver(row, { dataTransfer: dt });
    expect(row).toHaveAttribute("data-drop", "refused");
    expect(within(row).getByRole("status")).toHaveTextContent(reason); // on the row, not only a tooltip
    expect(dt.dropEffect).not.toBe("none"); // so the browser still delivers the drop
    fireEvent.drop(row, { dataTransfer: dt });
    expect(await screen.findByText(reason)).toBeInTheDocument(); // the toast
    expect(within(row).queryByRole("status")).toBeNull();
    expect(posts(calls, "/api/browse/move/preview")).toHaveLength(0);
  });

  it("a folder dragged onto another folder is a move only: Option does not switch to Copy", async () => {
    const plan = [op("move", "10. Financial", "13. Taxes/10. Financial", "d-10. Financial")];
    const { calls } = setup(one(""), { "POST /api/browse/move/preview": { body: plan } });
    await within(await screen.findByRole("list", { name: "Folder contents" })).findByText("13. Taxes");
    const dt = dragFrom(rowOf(listing(), "10. Financial"));
    const target = rowOf(listing(), "13. Taxes");
    dropOn(target, dt, true);
    const dialog = await screen.findByRole("dialog", { name: "Move 10. Financial to 13. Taxes?" });
    expect(posts(calls, "/api/browse/move/preview").map((c) => c.body)).toEqual([
      { drive_ids: ["d-10. Financial"], folder: "13. Taxes" },
    ]);
    expect(within(dialog).queryByRole("radio")).toBeNull(); // Move only: no Link / Copy choice shown
    // the request still says why Link and Copy are off, should anything reach them
    expect(folderMoveRequest("d", "X").modes).toEqual({ move: null, link: "Folders can only be moved", copy: "Folders can only be moved" });
    expect(within(dialog).getByRole("button", { name: /^Move folder/ })).toBeInTheDocument();
  });

  it("files dropped on a folder still get the Move / Link / Copy choice", async () => {
    setup(two("10. Financial", "13. Taxes"), { "POST /api/browse/move/preview": { body: [op("move", "10. Financial/x.pdf", "13. Taxes/x.pdf", "fx")] } });
    const left = pane("Left pane");
    await within(left).findByText("x.pdf");
    dropOn(within(pane("Right pane")).getByTestId("pane-drop"), dragFrom(rowOf(left, "x.pdf")));
    const dialog = await screen.findByRole("dialog", { name: "Move 1 file to 13. Taxes?" });
    expect(within(dialog).getAllByRole("radio")).toHaveLength(3);
  });

  it("search results are no folder", async () => {
    const hit = { drive_id: "fx", path: "10. Financial/x.pdf", name: "x.pdf", snippet: "[x]", rank: -1, size: 1, mtime: 1, marks: [] };
    const { user } = setup(one("10. Financial"), { "GET /api/search": { body: [hit] }, "GET /api/folders": { body: [] } });
    await screen.findByText("x.pdf");
    await user.type(screen.getByRole("combobox", { name: "Search" }), "x");
    const row = (await screen.findByRole("button", { name: /^x\.pdf/ })).closest("li")!;
    const zone = screen.getByTestId("pane-drop");
    const dt = dragFrom(row);
    fireEvent.dragEnter(zone, { dataTransfer: dt });
    expect(within(zone).getByRole("status")).toHaveTextContent(SEARCH_DROP_REASON);
    fireEvent.drop(zone, { dataTransfer: dt });
    expect(await screen.findByText(SEARCH_DROP_REASON)).toBeInTheDocument();
  });
});

describe("A collection's folder in ##. Ongoing", () => {
  it("takes a drop as Add to collection, with Undo; the link appears through the rebuild", async () => {
    const change = { collection: { ...SAUNA, members: [{ drive_id: "fx" }] }, batch: null, problems: [], ongoing_status: null };
    const { calls, user } = setup(two("10. Financial", "##. Ongoing"), {
      "POST /api/collections/7/members": { body: change },
      "POST /api/collections/7/members/remove": { body: { ...change, collection: SAUNA } },
    });
    const left = pane("Left pane");
    await within(left).findByText("x.pdf");
    const right = pane("Right pane");
    await within(right).findByText("Sauna");
    const row = rowOf(right, "Sauna");
    const dt = dragFrom(rowOf(left, "x.pdf"));
    await waitFor(() => {
      fireEvent.dragEnter(row, { dataTransfer: dt });
      expect(row).toHaveAttribute("data-drop", "over"); // the collections have loaded
    });
    fireEvent.drop(row, { dataTransfer: dt });
    await waitFor(() => expect(posts(calls, "/api/collections/7/members")).toHaveLength(1));
    expect(posts(calls, "/api/collections/7/members")[0].body).toEqual({ drive_ids: ["fx"] });
    expect(posts(calls, "/api/browse/move/preview")).toHaveLength(0); // no move, no sheet
    expect(await screen.findByText("Added x.pdf to Sauna")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Undo" }));
    await waitFor(() => expect(posts(calls, "/api/collections/7/members/remove")).toHaveLength(1));
    expect(posts(calls, "/api/collections/7/members/remove")[0].body).toEqual({ drive_id: "fx" });
  });

  it("refuses a file that is already a member, and a row of Ongoing itself", async () => {
    const member = { ...SAUNA, members: [{ drive_id: "fx" }] } as unknown as CollectionRow;
    setup(two("10. Financial", "##. Ongoing"), { "GET /api/collections": { body: [member] } });
    const left = pane("Left pane");
    await within(left).findByText("x.pdf");
    const right = pane("Right pane");
    await within(right).findByText("Sauna");
    const row = rowOf(right, "Sauna");
    const dt = dragFrom(rowOf(left, "x.pdf"));
    await waitFor(() => {
      fireEvent.dragEnter(row, { dataTransfer: dt });
      expect(row).toHaveAttribute("data-drop", "refused");
    });
    expect(within(row).getByRole("status")).toHaveTextContent("Already in Sauna");
  });

  it("another Ongoing row cannot be added from here", async () => {
    setup(two("##. Ongoing/Sauna", "##. Ongoing"));
    const left = pane("Left pane");
    await within(left).findByText("a.pdf");
    const right = pane("Right pane");
    await within(right).findByText("Sauna");
    const row = rowOf(right, "Sauna");
    const dt = dragFrom(rowOf(left, "a.pdf"));
    fireEvent.dragEnter(row, { dataTransfer: dt });
    expect(within(row).getByRole("status")).toHaveTextContent(ADD_FROM_OWN_FOLDER);
  });
});
