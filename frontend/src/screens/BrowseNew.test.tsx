/** Browse in the New look: the extra controls the stylesheet shows when the room is short
 * (the "View" menu per pane, the "More" menu, the Details button, the L / R tabs) and the
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
  it("offers Details, the More menu and a View menu in the pane header", async () => {
    document.documentElement.dataset.style = "new";
    const { user } = setup("/browse");
    await screen.findByText("a.pdf");
    const details = screen.getByRole("button", { name: "Details" });
    expect(details).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByRole("button", { name: "More: panes and folders" })).toBeInTheDocument();
    const pane = screen.getByRole("region", { name: "Browse" });
    expect(within(pane).getByRole("button", { name: "View" })).toBeInTheDocument();
    // the Details button opens the panel over the list, and the scrim closes it again
    const main = document.querySelector(".browse-main") as HTMLElement;
    expect(main.dataset.details).toBeUndefined();
    await user.click(details);
    expect(main.dataset.details).toBe("open");
    expect(details).toHaveAttribute("aria-pressed", "true");
    await user.click(document.querySelector(".details-scrim") as HTMLElement);
    expect(main.dataset.details).toBeUndefined();
    expect(screen.queryByRole("tablist", { name: "Panes" })).not.toBeInTheDocument();
  });

  it("the View menu holds Folders, Files and the collection filter", async () => {
    document.documentElement.dataset.style = "new";
    const { user } = setup("/browse");
    await screen.findByText("a.pdf");
    await user.click(within(screen.getByRole("region", { name: "Browse" })).getByRole("button", { name: "View" }));
    const menu = await screen.findByRole("menu", { name: "View" });
    expect(within(menu).getByRole("menuitemcheckbox", { name: "Folders" })).toBeChecked();
    expect(within(menu).getByRole("menuitemcheckbox", { name: "Files" })).not.toBeChecked();
    expect(within(menu).getByRole("menuitemcheckbox", { name: "All files" })).toBeChecked();
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
    expect([...document.querySelectorAll(".pane-id")].map((n) => n.textContent)).toEqual(["L", "R"]);
    // the two panes have no Details button: there is no panel beside them
    expect(screen.queryByRole("button", { name: "Details" })).not.toBeInTheDocument();
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
