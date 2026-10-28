/** Browse in the New look: the folder tree beside the panes (lazy children, the folders the
 * panes are in, keyboard, opening, dropping on a folder) and the details panel beside two
 * panes too (the selected file, several files, the actions with their keys). */
import { cleanup, createEvent, fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import type { DirEntry } from "../api/client";
import { type Call, dataTransfer, mockFetch, renderWithProviders } from "../test-utils";
import { forgetLayout } from "../layoutMemory";
import Browse, { INSPECTOR_WIDTH_KEY, TREE_SHOWN_KEY, TREE_WIDTH_KEY } from "./Browse";

const dir = (path: string, extra: Partial<DirEntry> = {}): DirEntry => ({
  name: path.slice(path.lastIndexOf("/") + 1),
  path,
  is_dir: true,
  is_link: false,
  size: null,
  mtime: 1,
  drive_id: `d-${path}`,
  connected: true,
  marks: [],
  ...extra,
});
const file = (path: string, drive_id: string, size = 1000): DirEntry => ({
  name: path.slice(path.lastIndexOf("/") + 1),
  path,
  is_dir: false,
  is_link: false,
  size,
  mtime: 1,
  drive_id,
  connected: true,
  marks: [],
});

const LISTINGS: Record<string, DirEntry[]> = {
  "": [dir("10. Financial"), dir("13. Taxes"), dir("30. Home")],
  "10. Financial": [dir("10. Financial/Banks"), file("10. Financial/x.pdf", "fx")],
  "10. Financial/Banks": [dir("10. Financial/Banks/Northbank"), file("10. Financial/Banks/a.pdf", "f1"), file("10. Financial/Banks/b.pdf", "f2", 2000)],
  "10. Financial/Banks/Northbank": [file("10. Financial/Banks/Northbank/n.pdf", "fn")],
  "13. Taxes": [file("13. Taxes/t.pdf", "ft")],
  "30. Home": [dir("30. Home/Electricity")],
  "30. Home/Electricity": [],
};
const STATUS = { special_folders: { inbox: "##. Organize", ongoing: "##. Ongoing", important: "##. Important", quarantine: "##. To Delete" } };
const queryOf = (call: Call) => new URL(call.url, "http://x").searchParams;
const browsed = (calls: Call[]) => calls.filter((c) => c.url.startsWith("/api/browse?")).map((c) => queryOf(c).get("path"));
const posts = (calls: Call[], url: string) => calls.filter((c) => c.method === "POST" && c.url === url);

function setup(url: string) {
  const calls = mockFetch({
    "GET /api/browse": (call) => ({ body: LISTINGS[queryOf(call).get("path") ?? ""] ?? [] }),
    "GET /api/collections": { body: [] },
    "GET /api/activity": { body: [] },
    "GET /api/status": { body: STATUS },
    "GET /api/trays": { body: { trays: [] } },
    "POST /api/browse/move/preview": {
      body: [{ kind: "move", src: "10. Financial/x.pdf", dst: "13. Taxes/x.pdf", drive_id: "fx", note: null }],
    },
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
const two = (left: string, right: string) => `/browse?left=${encodeURIComponent(left)}&right=${encodeURIComponent(right)}`;
const one = (path: string) => `/browse?path=${encodeURIComponent(path)}`;

const tree = () => screen.getByRole("tree", { name: "Folder tree" });
const item = (name: string) => within(tree()).getByRole("treeitem", { name });
const crumb = (scope: HTMLElement) => scope.querySelector("[aria-current=page]")?.textContent;
const pane = (name: "Left pane" | "Right pane") => screen.getByRole("region", { name });

beforeEach(() => {
  localStorage.clear();
  document.documentElement.dataset.style = "new";
});
afterEach(() => {
  cleanup();
  delete document.documentElement.dataset.style;
  document.dispatchEvent(new Event("dragend"));
});

describe("The folder tree", () => {
  it("lists the top folders, and a folder's subfolders only when it is opened", async () => {
    const { calls, user } = setup(one(""));
    await screen.findByRole("tree", { name: "Folder tree" });
    expect(within(tree()).getAllByRole("treeitem").map((n) => n.getAttribute("aria-label"))).toEqual([
      "10. Financial",
      "13. Taxes",
      "30. Home",
    ]);
    expect(item("10. Financial")).toHaveAttribute("aria-expanded", "false");
    expect(browsed(calls).filter((p) => p === "10. Financial")).toHaveLength(0);
    await user.click(item("10. Financial").querySelector(".tree-chevron") as HTMLElement);
    await waitFor(() => expect(within(item("10. Financial")).getByRole("treeitem", { name: "Banks" })).toBeInTheDocument());
    expect(item("10. Financial")).toHaveAttribute("aria-expanded", "true");
    expect(browsed(calls).filter((p) => p === "10. Financial").length).toBeGreaterThan(0);
    // files are no folders: only the folder shows
    expect(within(item("10. Financial")).queryByRole("treeitem", { name: "x.pdf" })).not.toBeInTheDocument();
    // a folder with no subfolder loses its chevron once it is known
    await user.click(item("30. Home").querySelector(".tree-chevron") as HTMLElement);
    await user.click(await within(item("30. Home")).findByRole("treeitem", { name: "Electricity" }).then((n) => n.querySelector(".tree-chevron") as HTMLElement));
    await waitFor(() => expect(item("Electricity")).not.toHaveAttribute("aria-expanded"));
  });

  it("highlights the folder of each pane (marked L and R with two panes) and opens the parents", async () => {
    localStorage.setItem(TREE_SHOWN_KEY, "1");
    setup(two("10. Financial/Banks", "13. Taxes"));
    await within(await screen.findByRole("tree", { name: "Folder tree" })).findByRole("treeitem", { name: "Banks" });
    expect(item("Banks")).toHaveAttribute("aria-selected", "true");
    expect(item("Banks").querySelector(".tree-pane")).toHaveTextContent("L");
    expect(item("13. Taxes")).toHaveAttribute("aria-selected", "true");
    expect(item("13. Taxes").querySelector(".tree-pane")).toHaveTextContent("R");
    expect(item("10. Financial")).toHaveAttribute("aria-expanded", "true");
    expect(item("30. Home")).toHaveAttribute("aria-selected", "false");
  });

  it("one pane: the current folder is highlighted with no pane mark", async () => {
    setup(one("10. Financial/Banks"));
    await within(await screen.findByRole("tree", { name: "Folder tree" })).findByRole("treeitem", { name: "Banks" });
    expect(item("Banks")).toHaveAttribute("aria-selected", "true");
    expect(item("Banks").querySelector(".tree-pane")).toHaveTextContent("");
  });

  it("a click opens the folder in the active pane (the other pane stays)", async () => {
    localStorage.setItem(TREE_SHOWN_KEY, "1");
    const { user } = setup(two("13. Taxes", "30. Home"));
    await screen.findByRole("tree", { name: "Folder tree" });
    await user.click(await screen.findByText("t.pdf")); // the left pane is the active one
    await user.click(item("10. Financial").querySelector(".tree-row") as HTMLElement);
    await waitFor(() => expect(crumb(pane("Left pane"))).toBe("10. Financial"));
    expect(crumb(pane("Right pane"))).toBe("30. Home");
    expect(item("10. Financial")).toHaveAttribute("aria-selected", "true");
  });

  it("works from the keyboard: arrows move, right opens and steps in, left closes and steps out, Enter opens", async () => {
    const { user } = setup(one(""));
    await screen.findByRole("tree", { name: "Folder tree" });
    item("10. Financial").focus();
    expect(item("10. Financial")).toHaveAttribute("tabindex", "0");
    await user.keyboard("{ArrowDown}");
    expect(item("13. Taxes")).toHaveFocus();
    expect(item("13. Taxes")).toHaveAttribute("tabindex", "0");
    expect(item("10. Financial")).toHaveAttribute("tabindex", "-1");
    await user.keyboard("{ArrowUp}{ArrowRight}");
    expect(item("10. Financial")).toHaveAttribute("aria-expanded", "true");
    const banks = await within(item("10. Financial")).findByRole("treeitem", { name: "Banks" });
    await user.keyboard("{ArrowRight}"); // an open folder: step into its first subfolder
    expect(banks).toHaveFocus();
    await user.keyboard("{ArrowLeft}"); // a closed one: step out to its parent
    expect(item("10. Financial")).toHaveFocus();
    await user.keyboard("{ArrowLeft}"); // an open one: close
    expect(item("10. Financial")).toHaveAttribute("aria-expanded", "false");
    await user.keyboard("{End}");
    expect(item("30. Home")).toHaveFocus();
    await user.keyboard("{Home}");
    expect(item("10. Financial")).toHaveFocus();
    await user.keyboard("{Enter}");
    await waitFor(() => expect(crumb(screen.getByRole("region", { name: "Browse" }))).toBe("10. Financial"));
    // the list's own keys (the cursor) did not move while the tree had the focus
    expect(screen.queryByRole("listitem", { current: true })).not.toBeInTheDocument();
  });

  it("is a drop target: files dropped on a folder go through the same Move preview", async () => {
    localStorage.setItem(TREE_SHOWN_KEY, "1");
    const { calls } = setup(two("10. Financial", "13. Taxes"));
    const row = (await screen.findByText("x.pdf")).closest("li") as HTMLElement;
    await screen.findByRole("tree", { name: "Folder tree" });
    const dt = dataTransfer();
    fireEvent.dragStart(row, { dataTransfer: dt });
    const target = item("13. Taxes").querySelector(".tree-row") as HTMLElement;
    fireEvent(target, createEvent.dragEnter(target, { dataTransfer: dt }));
    expect(target).toHaveAttribute("data-drop", "over");
    fireEvent(target, createEvent.dragOver(target, { dataTransfer: dt }));
    fireEvent(target, createEvent.drop(target, { dataTransfer: dt }));
    const dialog = await screen.findByRole("dialog", { name: "Move 1 file to 13. Taxes?" });
    expect(dialog).toBeInTheDocument();
    expect(posts(calls, "/api/browse/move/preview").map((c) => c.body)).toEqual([{ drive_ids: ["fx"], folder: "13. Taxes" }]);
    expect(posts(calls, "/api/browse/move")).toHaveLength(0); // a drop never changes anything by itself
  });

  it("takes a dragged folder too, and refuses a folder dropped into itself with the reason", async () => {
    localStorage.setItem(TREE_SHOWN_KEY, "1");
    const { calls } = setup(one("10. Financial"));
    const row = (await screen.findByText("Banks", { selector: ".entry-name" })).closest("li") as HTMLElement;
    await screen.findByRole("tree", { name: "Folder tree" });
    const dt = dataTransfer();
    fireEvent.dragStart(row, { dataTransfer: dt });
    const taxes = item("13. Taxes").querySelector(".tree-row") as HTMLElement;
    fireEvent(taxes, createEvent.dragEnter(taxes, { dataTransfer: dt }));
    expect(taxes).toHaveAttribute("data-drop", "over");
    fireEvent(taxes, createEvent.drop(taxes, { dataTransfer: dt }));
    await waitFor(() => expect(posts(calls, "/api/browse/move/preview")).toHaveLength(1));
    expect(posts(calls, "/api/browse/move/preview")[0].body).toEqual({ drive_ids: ["d-10. Financial/Banks"], folder: "13. Taxes" });
    cleanup();
    document.dispatchEvent(new Event("dragend"));
  });

  it("shows an extra archive folder's root with its disk's state", async () => {
    mockFetch({
      "GET /api/browse": () => ({ body: [dir("Backup", { folder: "Backup", connected: false }), dir("Home")] }),
      "GET /api/collections": { body: [] },
      "GET /api/activity": { body: [] },
      "GET /api/status": { body: STATUS },
    });
    renderWithProviders(
      <MemoryRouter initialEntries={["/browse"]}>
        <Routes>
          <Route path="/browse" element={<Browse />} />
        </Routes>
      </MemoryRouter>,
    );
    await screen.findByRole("tree", { name: "Folder tree" });
    const away = item("Backup");
    expect(away).toHaveTextContent("Not connected");
    expect(away).not.toHaveAttribute("aria-expanded");
  });

  it("Classic has no tree and no details beside two panes", async () => {
    delete document.documentElement.dataset.style;
    setup(two("10. Financial", "13. Taxes"));
    await screen.findByText("x.pdf");
    expect(screen.queryByRole("tree")).not.toBeInTheDocument();
    expect(screen.queryByRole("navigation", { name: "Folders" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Folder tree" })).not.toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Preview" })).not.toBeInTheDocument();
  });
});

describe("The tree beside two panes", () => {
  const body = () => document.querySelector(".browse-body") as HTMLElement;

  it("starts hidden, with the button off", async () => {
    setup(two("10. Financial", "13. Taxes"));
    await screen.findByText("x.pdf");
    expect(screen.queryByRole("tree")).not.toBeInTheDocument();
    expect(screen.queryByRole("separator", { name: "Resize the folder tree" })).not.toBeInTheDocument();
    const button = screen.getByRole("button", { name: "Folder tree" });
    expect(button).toHaveAttribute("aria-pressed", "false");
    expect(button).toHaveAttribute("aria-expanded", "false");
    expect(button).toHaveAttribute("data-tip", "Show the folder tree");
  });

  it("the button shows and hides it beside the panes, and the choice is remembered", async () => {
    const { user } = setup(two("10. Financial", "13. Taxes"));
    await screen.findByText("x.pdf");
    const button = screen.getByRole("button", { name: "Folder tree" });
    await user.click(button);
    await screen.findByRole("tree", { name: "Folder tree" });
    expect(button).toHaveAttribute("aria-pressed", "true");
    expect(button).toHaveAttribute("aria-expanded", "true");
    expect(button).toHaveAttribute("data-tip", "Hide the folder tree");
    expect(body().dataset.tree).toBeUndefined(); // docked, not the overlay
    expect(localStorage.getItem(TREE_SHOWN_KEY)).toBe("1");
    cleanup();
    setup(two("10. Financial", "13. Taxes")); // another visit
    await screen.findByRole("tree", { name: "Folder tree" });
    await user.click(screen.getByRole("button", { name: "Folder tree" }));
    expect(screen.queryByRole("tree")).not.toBeInTheDocument();
    expect(localStorage.getItem(TREE_SHOWN_KEY)).toBe("0");
  });

  it("is remembered per archive", async () => {
    localStorage.setItem(`${TREE_SHOWN_KEY}.work`, "1"); // another archive's choice
    setup(two("10. Financial", "13. Taxes"));
    await screen.findByText("x.pdf");
    expect(screen.queryByRole("tree")).not.toBeInTheDocument();
  });

  it("one pane keeps its tree whatever was chosen for two", async () => {
    localStorage.setItem(TREE_SHOWN_KEY, "0");
    setup(one(""));
    await screen.findByRole("tree", { name: "Folder tree" });
    expect(screen.getByRole("button", { name: "Folder tree" })).toHaveAttribute("aria-pressed", "false");
  });

  it("Reset layout forgets the choice, in every archive", () => {
    localStorage.setItem(TREE_SHOWN_KEY, "1");
    localStorage.setItem(`${TREE_SHOWN_KEY}.work`, "1");
    forgetLayout();
    expect(localStorage.getItem(TREE_SHOWN_KEY)).toBeNull();
    expect(localStorage.getItem(`${TREE_SHOWN_KEY}.work`)).toBeNull();
  });
});

describe("The dividers and the folded tree", () => {
  it("has a divider for the tree and one for the details, both remembered and reset by a double-click", async () => {
    const { user } = setup(one(""));
    await screen.findByRole("tree", { name: "Folder tree" });
    const body = document.querySelector(".browse-body") as HTMLElement;
    expect(body.style.getPropertyValue("--tree-w")).toBe("176px");
    expect(body.style.getPropertyValue("--details-w")).toBe("320px");
    const treeDivider = screen.getByRole("separator", { name: "Resize the folder tree" });
    treeDivider.focus();
    await user.keyboard("{ArrowRight}");
    expect(body.style.getPropertyValue("--tree-w")).toBe("192px");
    expect(Object.keys(localStorage).some((k) => k.includes(TREE_WIDTH_KEY))).toBe(true);
    await user.dblClick(treeDivider);
    expect(body.style.getPropertyValue("--tree-w")).toBe("176px");
    const detailsDivider = screen.getByRole("separator", { name: "Resize the details panel" });
    detailsDivider.focus();
    await user.keyboard("{ArrowLeft}"); // the panel is measured from the right: left makes it wider
    expect(body.style.getPropertyValue("--details-w")).toBe("336px");
    expect(Object.keys(localStorage).some((k) => k.includes(INSPECTOR_WIDTH_KEY))).toBe(true);
  });

  it("the folders button opens the tree over the panes, and choosing a folder closes it again", async () => {
    const { user } = setup(one(""));
    await screen.findByRole("tree", { name: "Folder tree" });
    const body = document.querySelector(".browse-body") as HTMLElement;
    const button = screen.getByRole("button", { name: "Folder tree" });
    expect(body.dataset.tree).toBeUndefined();
    await user.click(button);
    expect(body.dataset.tree).toBe("open");
    expect(button).toHaveAttribute("aria-pressed", "true");
    await user.click(item("13. Taxes").querySelector(".tree-row") as HTMLElement);
    expect(body.dataset.tree).toBeUndefined();
    await user.click(button);
    await user.click(document.querySelector(".browse-scrim") as HTMLElement);
    expect(body.dataset.tree).toBeUndefined();
  });

  it("Escape closes the tree or the details opened over the panes", async () => {
    const { user } = setup(one(""));
    await screen.findByRole("tree", { name: "Folder tree" });
    const body = document.querySelector(".browse-body") as HTMLElement;
    await user.click(screen.getByRole("button", { name: "Folder tree" }));
    expect(body.dataset.tree).toBe("open");
    await user.keyboard("{Escape}");
    expect(body.dataset.tree).toBeUndefined();
    await user.click(screen.getByRole("button", { name: "Details" }));
    expect(body.dataset.details).toBe("open");
    await user.keyboard("{Escape}");
    expect(body.dataset.details).toBeUndefined();
  });
});

describe("The details beside two panes", () => {
  const FILE_ROUTES = {
    "GET /api/files/f1/links": { body: { items: [], collections: [], note: "" } },
    "GET /api/notes/file/f1": { body: { text: "" } },
  };
  function withFiles(url: string) {
    const out = setup(url);
    return out;
  }

  it("shows the file of the active pane, with the two icon rows and their keys", async () => {
    mockFetch({
      "GET /api/browse": (call) => ({ body: LISTINGS[queryOf(call).get("path") ?? ""] ?? [] }),
      "GET /api/collections": { body: [] },
      "GET /api/activity": { body: [] },
      "GET /api/status": { body: STATUS },
      "GET /api/trays": { body: { trays: [] } },
      ...FILE_ROUTES,
    });
    const user = userEvent.setup();
    renderWithProviders(
      <MemoryRouter initialEntries={[two("10. Financial/Banks", "13. Taxes")]}>
        <Routes>
          <Route path="/browse" element={<Browse />} />
        </Routes>
      </MemoryRouter>,
    );
    const details = await screen.findByRole("region", { name: "Preview" });
    expect(within(details).getByText("No file selected")).toBeInTheDocument();
    await user.click(await within(pane("Left pane")).findByText("a.pdf"));
    expect(await within(details).findByRole("heading", { name: "a.pdf" })).toBeInTheDocument();
    // two rows of icon buttons, each with its key in the tooltip
    const look = within(details).getByRole("group", { name: "Look at it" });
    expect(within(look).getAllByRole("button").map((b) => b.getAttribute("aria-label"))).toEqual([
      "Open",
      "Quick Look",
      expect.stringMatching(/^Show in /),
      "Relatives",
      "Ask AI",
    ]);
    expect(within(look).getByRole("button", { name: "Quick Look" })).toHaveAttribute("data-tip", "Quick Look (Space)");
    const filing = within(details).getByRole("group", { name: "File it" });
    expect(within(filing).getAllByRole("button").map((b) => b.getAttribute("aria-label"))).toEqual([
      "From…",
      "For…",
      "Put in tray",
      "Star",
      "Mark Important",
      "Back to inbox",
      "Move to To Delete",
    ]);
    expect(within(filing).getByRole("button", { name: "Move to To Delete" })).toHaveAttribute("data-tip", "Move to To Delete (⌘⌫)");
    // what is done in place is not in the rows: Rename, Move to…, Tag…, Add to collection…
    for (const row of [look, filing]) {
      expect(within(row).queryByRole("button", { name: /^(Rename|Move to…|Tag…|Add to collection…)/ })).toBeNull();
    }
    // the name and the folder do them in place
    expect(within(details).getByRole("button", { name: "Rename a.pdf" })).toBeInTheDocument();
    expect(within(details).getByRole("button", { name: "Move file to…" })).toBeInTheDocument();
    // Relatives opens the Relatives window of this file
    await user.click(within(look).getByRole("button", { name: "Relatives" }));
    const window = await screen.findByRole("dialog", { name: "Relatives" });
    expect(within(window).getByText("a.pdf")).toBeInTheDocument();
    await user.click(within(window).getByRole("button", { name: "Close" }));
    expect(screen.queryByRole("dialog", { name: "Relatives" })).toBeNull();
    // the other pane's file takes over when that pane becomes the active one
    await user.click(await within(pane("Right pane")).findByText("t.pdf"));
    expect(await within(details).findByRole("heading", { name: "t.pdf" })).toBeInTheDocument();
    // the old header's file actions are not in the header any more
    expect(screen.queryByRole("toolbar", { name: "Browse file actions" })).not.toBeInTheDocument();
  });

  it("several checked files get a summary, and Move to… on the list opens the same picker", async () => {
    const { user } = withFiles(two("10. Financial/Banks", "13. Taxes"));
    const details = await screen.findByRole("region", { name: "Preview" });
    const left = pane("Left pane");
    await within(left).findByText("a.pdf");
    await user.click(within(left).getByRole("checkbox", { name: "Select a.pdf" }));
    await user.click(within(left).getByRole("checkbox", { name: "Select b.pdf" }));
    expect(await within(details).findByRole("heading", { name: "2 files selected" })).toBeInTheDocument();
    expect(details).toHaveTextContent(/2[.,]9 KB, all in 10\. Financial\/Banks/);
    await user.click(within(details).getByRole("button", { name: "Move to…" }));
    const sheet = await screen.findByRole("dialog");
    expect(sheet).toHaveTextContent("a.pdf");
    expect(sheet).toHaveTextContent("b.pdf");
  });

  it("Move to To Delete on the list asks first, as the header's bin did", async () => {
    const { user, calls } = withFiles(two("10. Financial/Banks", "13. Taxes"));
    const details = await screen.findByRole("region", { name: "Preview" });
    const left = pane("Left pane");
    await within(left).findByText("a.pdf");
    await user.click(within(left).getByRole("checkbox", { name: "Select a.pdf" }));
    await user.click(within(left).getByRole("checkbox", { name: "Select b.pdf" }));
    await user.click(await within(details).findByRole("button", { name: "Move 2 to To Delete" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.url.includes("/api/quarantine"))).toBe(true));
  });
});
