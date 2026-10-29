/** Browse with a folder of thousands of files: only the rows near the view are rendered,
 * and selection, keys, focus and Go to target still work on every row. jsdom has no
 * layout, so the scroller's height and the rows' heights are stubbed. */
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { DirEntry } from "../api/client";
import { mockFetch, renderWithProviders } from "../test-utils";
import Browse from "./Browse";

const PATH = "10. Financial/Banks";
const COUNT = 2000;
const ROW = 30;
const VIEW = 600;
const name = (k: number) => `file-${String(k).padStart(4, "0")}.pdf`;
const ROWS: DirEntry[] = Array.from({ length: COUNT }, (_, k) => ({
  name: name(k),
  path: `${PATH}/${name(k)}`,
  is_dir: false,
  is_link: false,
  size: 10,
  mtime: 1,
  drive_id: `f${k}`,
  connected: true,
  marks: [],
  open_items: [],
}));

function setup(query = "") {
  mockFetch({
    "GET /api/browse": { body: ROWS },
    "GET /api/activity": { body: [] },
    "GET /api/status": { body: { special_folders: { inbox: "##. Organize", ongoing: "##. Ongoing", important: "##. Important", quarantine: "##. To Delete" } } },
  });
  const user = userEvent.setup();
  renderWithProviders(
    <MemoryRouter initialEntries={[`/browse?path=${encodeURIComponent(PATH)}${query}`]}>
      <Routes>
        <Route path="/browse" element={<Browse />} />
      </Routes>
    </MemoryRouter>,
  );
  return { user };
}

const list = () => screen.getByRole("list", { name: "Folder contents" });
const rendered = () => [...list().querySelectorAll<HTMLLIElement>("li[data-row]")].map((li) => Number(li.dataset.row));
const scroller = () => list().parentElement!;
const scrollTo = (top: number) => {
  scroller().scrollTop = top;
  fireEvent.scroll(scroller());
};

const scrolled = vi.fn();
beforeEach(() => {
  // the pane's body is VIEW px high, each row ROW px; rows stack from the top
  vi.spyOn(HTMLElement.prototype, "clientHeight", "get").mockImplementation(function (this: HTMLElement) {
    return this.classList.contains("pane-body") ? VIEW : 0;
  });
  vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(function (this: HTMLElement) {
    const h = this.tagName === "LI" ? ROW : 0;
    // the list moves up as its scroller scrolls
    const top = this.tagName === "UL" ? -(this.parentElement?.scrollTop ?? 0) : 0;
    return { x: 0, y: top, top, left: 0, right: 0, bottom: top + h, width: 0, height: h, toJSON: () => ({}) } as DOMRect;
  });
  scrolled.mockClear();
  vi.spyOn(HTMLElement.prototype, "scrollIntoView").mockImplementation(scrolled);
});
afterEach(() => {
  vi.restoreAllMocks();
});

describe("A folder of thousands of files", () => {
  it("renders only the rows near the view, with spacers for the rest, and shades every other row", async () => {
    setup();
    await screen.findByText(name(0));
    const shown = rendered();
    expect(shown[0]).toBe(0);
    expect(shown.length).toBeGreaterThan(VIEW / ROW);
    expect(shown.length).toBeLessThan(200);
    const spacer = list().querySelector<HTMLLIElement>("li.entries-spacer")!;
    expect(spacer).toHaveAttribute("aria-hidden", "true");
    expect(parseFloat(spacer.style.height)).toBe((COUNT - shown.length) * ROW);
    expect(list().querySelector('li[data-row="0"]')).not.toHaveClass("stripe");
    expect(list().querySelector('li[data-row="1"]')).toHaveClass("stripe");
  });

  it("scrolling renders the rows that come into view", async () => {
    setup();
    await screen.findByText(name(0));
    scrollTo(1500 * ROW);
    await waitFor(() => expect(rendered()).toContain(1510));
    expect(rendered()).not.toContain(0);
    expect(screen.queryByText(name(0))).not.toBeInTheDocument();
  });

  it("Go to target on a row far down: that row is current, rendered and scrolled to", async () => {
    setup("&select=f1500");
    const row = await waitFor(() => {
      const li = list().querySelector<HTMLLIElement>('li[data-row="1500"]');
      expect(li).not.toBeNull();
      return li!;
    });
    expect(row).toHaveAttribute("aria-current", "true");
    await waitFor(() => expect(scrolled).toHaveBeenCalled());
    expect(scrolled.mock.contexts.at(-1)).toBe(row);
    expect(within(screen.getByRole("region", { name: "Preview" })).getByText(`${PATH}/${name(1500)}`)).toBeInTheDocument();
  });

  it("j and k move the focus by row, also to a row that was scrolled out of view", async () => {
    const { user } = setup();
    await user.click(await screen.findByRole("button", { name: name(0) }));
    await user.keyboard("jjj");
    expect(screen.getByRole("button", { name: name(3) })).toHaveFocus();
    // the current row stays rendered when the view scrolls away from it
    scrollTo(1500 * ROW);
    await waitFor(() => expect(rendered()).toContain(1510));
    expect(rendered()).toContain(3);
    await user.keyboard("j");
    expect(screen.getByRole("button", { name: name(4) })).toHaveFocus();
    await user.keyboard("k");
    expect(screen.getByRole("button", { name: name(3) })).toHaveFocus();
  });

  it("a shift-click selects the whole range, rows out of view included; checkboxes show for all", async () => {
    const { user } = setup();
    await user.click(await screen.findByRole("button", { name: name(0) }));
    scrollTo(1500 * ROW);
    await waitFor(() => expect(rendered()).toContain(1510));
    await user.keyboard("{Shift>}");
    await user.click(screen.getByRole("button", { name: name(1500) }));
    await user.keyboard("{/Shift}");
    expect(screen.getByText("1501 selected")).toBeInTheDocument();
    expect(list()).toHaveClass("entries-checking");
    scrollTo(0);
    await waitFor(() => expect(rendered()).toContain(1));
    expect(screen.getByRole("checkbox", { name: `Select ${name(1)}` })).toBeChecked();
  });
});
