/** Browse in the New look: Split in the header, Swap and Close on the panes' bars, New folder
 * in a pane, the extra controls the stylesheet shows when the room is short (the "View" menu
 * per pane, the Details and folders buttons, the L / R tabs), This folder's columns and the
 * remembered divider between two panes. Classic renders none of them. */
import { cleanup, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import type { DirEntry } from "../api/client";
import { mockFetch, renderWithProviders } from "../test-utils";
import { PANES_WIDTH_KEY } from "./Browse";
import Browse from "./Browse";

const entry = (name: string, id: string, is_dir = false): DirEntry => ({
  name,
  path: name,
  is_dir,
  is_link: false,
  size: 10,
  mtime: 1,
  drive_id: id,
  connected: true,
  marks: [],
});

function setup(url: string, listing: DirEntry[] = [entry("Money", "d1", true), entry("a.pdf", "f1")]) {
  mockFetch({
    "GET /api/browse": { body: listing },
    "GET /api/collections": { body: [] },
    "GET /api/activity": { body: [] },
    "GET /api/status": { body: { special_folders: { inbox: "##. Organize", ongoing: "##. Ongoing", important: "##. Important", quarantine: "##. To Delete" } } },
  });
  const user = userEvent.setup();
  renderWithProviders(
    <MemoryRouter initialEntries={[url]}>
      <Routes>
        <Route path="/browse" element={<Browse />} />
      </Routes>
    </MemoryRouter>,
  );
  return { user };
}

beforeEach(() => {
  localStorage.clear();
});
afterEach(() => {
  cleanup();
  delete document.documentElement.dataset.style;
});

describe("Browse in New, one pane", () => {
  it("offers Details and Split in the header, and View and New folder in the pane header", async () => {
    document.documentElement.dataset.style = "new";
    const { user } = setup("/browse");
    await screen.findByText("a.pdf");
    const details = screen.getByRole("button", { name: "Details" });
    expect(details).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByRole("button", { name: "Split" })).toBeInTheDocument();
    // no layout switch, Swap or New folder in the header any more
    for (const name of ["One pane", "Two panes", "Swap panes", "More: panes and folders"]) {
      expect(screen.queryByRole("button", { name })).not.toBeInTheDocument();
    }
    const pane = screen.getByRole("region", { name: "Browse" });
    expect(within(pane).getByRole("button", { name: "View" })).toBeInTheDocument();
    expect(within(pane).getByRole("button", { name: "New folder" })).toBeInTheDocument();
    expect(within(document.querySelector(".browse-toolbar") as HTMLElement).queryByRole("button", { name: "New folder" })).toBeNull();
    // the Details button opens the panel over the list, and the scrim closes it again
    const body = document.querySelector(".browse-body") as HTMLElement;
    expect(body.dataset.details).toBeUndefined();
    await user.click(details);
    expect(body.dataset.details).toBe("open");
    expect(details).toHaveAttribute("aria-pressed", "true");
    await user.click(document.querySelector(".browse-scrim") as HTMLElement);
    expect(body.dataset.details).toBeUndefined();
    expect(screen.queryByRole("tablist", { name: "Panes" })).not.toBeInTheDocument();
  });

  it("the View menu holds This folder and All files below, and no collection filter", async () => {
    document.documentElement.dataset.style = "new";
    const { user } = setup("/browse");
    await screen.findByText("a.pdf");
    await user.click(within(screen.getByRole("region", { name: "Browse" })).getByRole("button", { name: "View" }));
    const menu = await screen.findByRole("menu", { name: "View" });
    expect(within(menu).getByRole("menuitemcheckbox", { name: "This folder" })).toBeChecked();
    expect(within(menu).getByRole("menuitemcheckbox", { name: "All files below" })).not.toBeChecked();
    expect(within(menu).getByRole("menuitemcheckbox", { name: "This folder" })).toHaveAttribute("data-tip", expect.stringContaining("subfolders and its own files"));
    expect(within(menu).getByRole("menuitemcheckbox", { name: "All files below" })).toHaveAttribute("data-tip", expect.stringContaining("in one list"));
    expect(within(menu).getAllByRole("menuitemcheckbox")).toHaveLength(2);
  });

  it("the view switch says This folder and All files below, with tooltips, and still switches", async () => {
    document.documentElement.dataset.style = "new";
    const { user } = setup("/browse");
    await screen.findByText("a.pdf");
    const view = within(screen.getByRole("group", { name: "View" }));
    const here = view.getByRole("button", { name: "This folder" });
    const below = view.getByRole("button", { name: "All files below" });
    expect(view.queryByRole("button", { name: "Folders" })).not.toBeInTheDocument();
    expect(here).toHaveAttribute("data-tip", "This folder: its subfolders and its own files");
    expect(below).toHaveAttribute("data-tip", "All files below: every file in this folder and its subfolders, in one list");
    expect(here).toHaveAttribute("aria-pressed", "true");
    await user.click(below);
    expect(below).toHaveAttribute("aria-pressed", "true");
    expect(here).toHaveAttribute("aria-pressed", "false");
  });

  it("a file row has a Relatives button beside Quick Look that opens that file's Relatives; folders have none", async () => {
    document.documentElement.dataset.style = "new";
    const { user } = setup("/browse");
    await screen.findByText("a.pdf");
    expect(screen.queryByRole("button", { name: "Relatives of Money" })).not.toBeInTheDocument();
    const rel = screen.getByRole("button", { name: "Relatives of a.pdf" });
    expect(rel).toHaveAttribute("data-tip", "Relatives");
    expect(screen.getByRole("button", { name: "Quick Look a.pdf" })).toBeInTheDocument();
    await user.click(rel);
    expect(await screen.findByRole("dialog", { name: /Relatives/ })).toBeInTheDocument();
  });

  it("Classic has no Relatives button on rows and keeps Folders and Files", async () => {
    setup("/browse");
    await screen.findByText("a.pdf");
    expect(screen.queryByRole("button", { name: "Relatives of a.pdf" })).not.toBeInTheDocument();
    const view = within(screen.getByRole("group", { name: "View" }));
    expect(view.getByRole("button", { name: "Folders" })).toBeInTheDocument();
    expect(view.getByRole("button", { name: "Files" })).toBeInTheDocument();
  });

  it("Classic has none of these", async () => {
    setup("/browse");
    await screen.findByText("a.pdf");
    expect(screen.queryByRole("button", { name: "Details" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "More: panes and folders" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "View" })).not.toBeInTheDocument();
    expect(document.querySelector(".pane-id")).toBeNull();
  });
});

describe("Browse in New, two panes", () => {
  it("has a divider between the panes, L and R tabs, and the L / R marks", async () => {
    document.documentElement.dataset.style = "new";
    const { user } = setup("/browse?left=&right=Money");
    await screen.findAllByText("a.pdf");
    const divider = screen.getByRole("separator", { name: "Resize the two panes" });
    expect(divider).toHaveAttribute("title", "Drag to resize, double-click to reset");
    const tabs = screen.getByRole("tablist", { name: "Panes" });
    const left = within(tabs).getByRole("tab", { name: "L · Archive" });
    const right = within(tabs).getByRole("tab", { name: "R · Money" });
    expect(left).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("region", { name: "Left pane" })).toHaveClass("browse-pane-active");
    await user.click(right);
    expect(right).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("region", { name: "Right pane" })).toHaveClass("browse-pane-active");
    expect(screen.getByRole("region", { name: "Left pane" })).not.toHaveClass("browse-pane-active");
    // Swap on the left pane's bar, Close on the right one's; Split is gone from the header
    expect(within(screen.getByRole("region", { name: "Left pane" })).getByRole("button", { name: "Swap panes" })).toHaveAttribute("data-tip", "Swap the two panes");
    expect(within(screen.getByRole("region", { name: "Right pane" })).getByRole("button", { name: "Close this pane" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Split" })).not.toBeInTheDocument();
    // the details panel sits beside two panes too (a Details button opens it when the room is short)
    expect(screen.getByRole("button", { name: "Details" })).toBeInTheDocument();
  });

  it("Split opens the second pane, its X closes it, and Swap keeps you on your side", async () => {
    document.documentElement.dataset.style = "new";
    const { user } = setup("/browse?path=Money");
    await screen.findByText("a.pdf");
    await user.click(screen.getByRole("button", { name: "Split" }));
    const left = await screen.findByRole("region", { name: "Left pane" });
    const right = screen.getByRole("region", { name: "Right pane" });
    // go to the archive's top on the left, then into the right pane
    await user.click(within(within(left).getByRole("navigation", { name: "Breadcrumb" })).getByRole("link", { name: "Archive" }));
    await user.click(within(right).getByRole("button", { name: /^a\.pdf/ }));
    expect(right).toHaveClass("browse-pane-active");
    await user.click(within(left).getByRole("button", { name: "Swap panes" }));
    // the folders trade places; the right side stays the active one
    await waitFor(() => expect(within(screen.getByRole("region", { name: "Right pane" })).getByRole("navigation", { name: "Breadcrumb" })).not.toHaveTextContent("Money"));
    expect(within(screen.getByRole("region", { name: "Left pane" })).getByRole("navigation", { name: "Breadcrumb" })).toHaveTextContent("Money");
    expect(screen.getByRole("region", { name: "Right pane" })).toHaveClass("browse-pane-active");
    await user.click(within(screen.getByRole("region", { name: "Right pane" })).getByRole("button", { name: "Close this pane" }));
    expect(await screen.findByRole("region", { name: "Browse" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Split" })).toBeInTheDocument();
  });

  it("remembers the divider's place and a double-click resets it", async () => {
    document.documentElement.dataset.style = "new";
    const { user } = setup("/browse?left=&right=Money");
    await screen.findAllByText("a.pdf");
    const divider = screen.getByRole("separator", { name: "Resize the two panes" });
    const main = document.querySelector(".browse-main") as HTMLElement;
    expect(main.style.getPropertyValue("--split")).toBe("50%");
    divider.focus();
    await user.keyboard("{ArrowRight}");
    expect(main.style.getPropertyValue("--split")).toBe("52%");
    const keys = Object.keys(localStorage).filter((k) => k.includes(PANES_WIDTH_KEY));
    expect(keys).toHaveLength(1);
    expect(localStorage.getItem(keys[0])).toBe("52");
    await user.dblClick(divider);
    expect(main.style.getPropertyValue("--split")).toBe("50%");
    expect(localStorage.getItem(keys[0])).toBeNull();
  });

  it("Classic keeps two equal panes with no divider and no tabs", async () => {
    setup("/browse?left=&right=Money");
    await screen.findAllByText("a.pdf");
    expect(screen.queryByRole("separator", { name: "Resize the two panes" })).not.toBeInTheDocument();
    expect(screen.queryByRole("tablist", { name: "Panes" })).not.toBeInTheDocument();
  });
});

describe("Browse in New, a long path", () => {
  const widthOf = Object.getOwnPropertyDescriptor(HTMLElement.prototype, "offsetWidth");
  const clientOf = Object.getOwnPropertyDescriptor(HTMLElement.prototype, "clientWidth");
  afterEach(() => {
    if (widthOf) Object.defineProperty(HTMLElement.prototype, "offsetWidth", widthOf);
    if (clientOf) Object.defineProperty(HTMLElement.prototype, "clientWidth", clientOf);
  });
  /** Every step measures 100px; the path has room for ``room`` px. */
  const squeeze = (room: number) => {
    Object.defineProperty(HTMLElement.prototype, "offsetWidth", { configurable: true, get: () => 100 });
    Object.defineProperty(HTMLElement.prototype, "clientWidth", {
      configurable: true,
      get(this: HTMLElement) {
        return this.classList.contains("breadcrumb") ? room : 0;
      },
    });
  };

  it("folds the parents that do not fit into one menu that names them and goes there", async () => {
    document.documentElement.dataset.style = "new";
    squeeze(330); // Archive, A, B, C is 400px: "..., B, C" fits
    const { user } = setup("/browse?path=A%2FB%2FC", [entry("a.pdf", "f1")]);
    await screen.findByText("a.pdf");
    const crumbs = screen.getByRole("navigation", { name: "Breadcrumb" });
    expect(within(crumbs).getByRole("link", { name: "B" })).toBeInTheDocument();
    expect(crumbs.querySelector("[aria-current=page]")).toHaveTextContent("C");
    expect(within(crumbs).queryByRole("link", { name: "A" })).not.toBeInTheDocument();
    await user.click(within(crumbs).getByRole("button", { name: "Parent folders" }));
    const menu = await screen.findByRole("menu", { name: "Parent folders" });
    expect(within(menu).getAllByRole("menuitem").map((i) => i.textContent)).toEqual(["Archive", "A"]);
    await user.click(within(menu).getByRole("menuitem", { name: "A" }));
    await waitFor(() =>
      expect(screen.getByRole("navigation", { name: "Breadcrumb" }).querySelector("[aria-current=page]")).toHaveTextContent("A"),
    );
  });

  it("keeps only the folder you are in when nothing else fits, and everything when it all fits", async () => {
    document.documentElement.dataset.style = "new";
    squeeze(120);
    setup("/browse?path=A%2FB%2FC", [entry("a.pdf", "f1")]);
    await screen.findByText("a.pdf");
    const crumbs = screen.getByRole("navigation", { name: "Breadcrumb" });
    expect(within(crumbs).queryAllByRole("link")).toHaveLength(0);
    expect(within(crumbs).getByRole("button", { name: "Parent folders" })).toBeInTheDocument();
    cleanup();
    squeeze(900);
    setup("/browse?path=A%2FB%2FC", [entry("a.pdf", "f1")]);
    await screen.findByText("a.pdf");
    const all = screen.getByRole("navigation", { name: "Breadcrumb" });
    expect(within(all).getAllByRole("link")).toHaveLength(3);
    expect(within(all).queryByRole("button", { name: "Parent folders" })).not.toBeInTheDocument();
  });

  it("Classic never folds the path", async () => {
    squeeze(120);
    setup("/browse?path=A%2FB%2FC", [entry("a.pdf", "f1")]);
    await screen.findByText("a.pdf");
    const crumbs = screen.getByRole("navigation", { name: "Breadcrumb" });
    expect(within(crumbs).getAllByRole("link")).toHaveLength(3);
    expect(within(crumbs).queryByRole("button")).not.toBeInTheDocument();
  });
});

describe("This folder's columns (New)", () => {
  const rows = [
    { ...entry("Zeta", "d2", true), mtime: 5 },
    { ...entry("Money", "d1", true), mtime: 9 },
    { ...entry("big.pdf", "f2"), size: 9000, mtime: 2 },
    { ...entry("a.pdf", "f1"), size: 10, mtime: 7 },
  ];
  const names = () =>
    [...(screen.getByRole("list", { name: "Folder contents" }).querySelectorAll(".entry-name"))].map((n) => n.textContent);

  it("has Name, Date and Size to sort by, folders first, and no size for a folder", async () => {
    document.documentElement.dataset.style = "new";
    const { user } = setup("/browse", rows);
    await screen.findByText("a.pdf");
    const head = screen.getByRole("group", { name: "Sort by" });
    expect(within(head).getAllByRole("button").map((b) => b.textContent)).toEqual(["Name ↑", "Date", "Size"]);
    expect(names()).toEqual(["Money", "Zeta", "a.pdf", "big.pdf"]);
    await user.click(within(head).getByRole("button", { name: "Sort by size" }));
    // largest first; the folders stay on top in A-Z
    expect(names()).toEqual(["Money", "Zeta", "big.pdf", "a.pdf"]);
    await user.click(within(head).getByRole("button", { name: "Sort by date" }));
    expect(names()).toEqual(["Money", "Zeta", "a.pdf", "big.pdf"]);
    const folder = screen.getByRole("button", { name: /^Money/ });
    expect(folder.querySelector(".entry-size")).toHaveTextContent("");
    expect(folder.querySelector(".entry-folder")).toBeNull();
  });

  it("Classic keeps its plain list", async () => {
    setup("/browse", rows);
    await screen.findByText("a.pdf");
    expect(screen.queryByRole("group", { name: "Sort by" })).not.toBeInTheDocument();
  });
});
