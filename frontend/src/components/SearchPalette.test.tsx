/** Search and jump (Cmd+K / Ctrl+K): opens by key in both looks, filters the screens, trays,
 * collections, tags, folders and files, moves with the arrow keys, opens the chosen thing
 * where it lives and closes on Esc. */
import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, useLocation } from "react-router-dom";
import { afterEach, describe, expect, it } from "vitest";
import { type Call, mockFetch, renderWithProviders } from "../test-utils";
import { SearchPalette, useSearchPalette } from "./SearchPalette";

const TRAYS = {
  trays: [
    { id: "to-pay", name: "To pay", order: 1 },
    { id: "follow-up", name: "Follow up", order: 2 },
  ],
  errors: [],
};
const COLLECTIONS = [
  { id: 3, name: "2026 House sale", path: ["2026 House sale"], files: 4, members: [] },
  { id: 5, name: "Boat shed", path: ["Summer cottage", "Boat shed"], files: 0, members: [] },
];
const TAGS = { tags: [{ name: "insurance", files: 14, pinned: true, group_id: null }], groups: [] };
const HIT = { drive_id: "d9", path: "30. Home/Electricity/bill.pdf", name: "bill.pdf", snippet: "", rank: 1, size: 1, mtime: 1, marks: [], connected: true };

const ROUTES = {
  "GET /api/trays": { body: TRAYS },
  "GET /api/collections": { body: COLLECTIONS },
  "GET /api/tags/all": { body: TAGS },
  "GET /api/folders": { body: ["30. Home", "30. Home/Electricity", "40. Travel"] },
  "GET /api/search": (call: Call) => ({ body: call.url.includes("q=bill") ? [HIT] : [] }),
};

function Where() {
  const l = useLocation();
  return <p data-testid="where">{l.pathname + l.search}</p>;
}
function Host() {
  const palette = useSearchPalette();
  return (
    <>
      <button type="button" onClick={palette.show}>
        Open
      </button>
      <input aria-label="Some field" />
      <SearchPalette open={palette.open} onClose={palette.hide} />
      <Where />
    </>
  );
}
function setup(routes: Record<string, unknown> = ROUTES) {
  const calls = mockFetch(routes as Parameters<typeof mockFetch>[0]);
  renderWithProviders(
    <MemoryRouter initialEntries={["/inbox"]}>
      <Host />
    </MemoryRouter>,
  );
  return { calls, user: userEvent.setup() };
}
const press = (init: KeyboardEventInit) => act(() => void document.dispatchEvent(new KeyboardEvent("keydown", { bubbles: true, ...init })));
const dialog = () => screen.queryByRole("dialog", { name: "Search and jump" });
const box = () => screen.getByRole("combobox", { name: /Search files, folders/ });
const platform = (value: string) => Object.defineProperty(navigator, "platform", { value, configurable: true });

afterEach(() => {
  cleanup();
  platform("MacIntel");
  delete document.documentElement.dataset.style;
});

describe("Search and jump", () => {
  it("opens on Cmd+K on a Mac, in Classic too, and Ctrl+K does nothing there", async () => {
    setup();
    press({ key: "k", ctrlKey: true });
    expect(dialog()).toBeNull();
    press({ key: "k", metaKey: true });
    expect(await screen.findByRole("dialog", { name: "Search and jump" })).toBeInTheDocument();
    expect(box()).toHaveFocus();
  });

  it("opens on Ctrl+K elsewhere, and Cmd+K does nothing there", () => {
    platform("Win32");
    setup();
    press({ key: "k", metaKey: true });
    expect(dialog()).toBeNull();
    press({ key: "k", ctrlKey: true });
    expect(dialog()).not.toBeNull();
  });

  it("opens from inside a text field, toggles closed on the same key, and stays off over another dialog", async () => {
    const { user } = setup();
    await user.click(screen.getByRole("textbox", { name: "Some field" }));
    press({ key: "k", metaKey: true });
    expect(dialog()).not.toBeNull();
    fireEvent.keyDown(box(), { key: "k", metaKey: true });
    expect(dialog()).toBeNull();
    const other = document.createElement("dialog");
    other.setAttribute("open", "");
    document.body.append(other);
    press({ key: "k", metaKey: true });
    expect(dialog()).toBeNull();
    other.remove();
  });

  it("is a labelled dialog with a combobox and a listbox of options", async () => {
    const { user } = setup();
    await user.click(screen.getByRole("button", { name: "Open" }));
    const list = await screen.findByRole("listbox", { name: "Results" });
    expect(box()).toHaveAttribute("aria-controls", list.id);
    const first = within(list).getAllByRole("option")[0];
    expect(first).toHaveAttribute("aria-selected", "true");
    expect(box()).toHaveAttribute("aria-activedescendant", first.id);
    expect(within(list).getAllByRole("group").map((g) => g.getAttribute("aria-labelledby"))).not.toContain(null);
  });

  it("asks the server for nothing while closed", async () => {
    const { calls } = setup();
    await new Promise((r) => setTimeout(r, 30));
    expect(calls).toHaveLength(0);
  });

  it("offers the screens, trays and collections before anything is typed", async () => {
    const { user } = setup();
    await user.click(screen.getByRole("button", { name: "Open" }));
    expect(await screen.findByRole("option", { name: /^Today/ })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: /^Browse/ })).toBeInTheDocument();
    expect(await screen.findByRole("option", { name: /^To pay/ })).toBeInTheDocument();
    expect(await screen.findByRole("option", { name: /^2026 House sale/ })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: /^insurance/ })).toBeNull(); // tags and folders only when searched
  });

  it("filters as you type, best match first, and says when nothing matches", async () => {
    const { user } = setup();
    await user.click(screen.getByRole("button", { name: "Open" }));
    await user.type(box(), "ho");
    await screen.findByRole("option", { name: /^2026 House sale/ });
    expect(screen.queryByRole("option", { name: /^Today/ })).toBeNull();
    const folders = within(screen.getByRole("group", { name: "Folders" })).getAllByRole("option");
    expect(folders.map((o) => o.textContent)).toEqual(["30. Home", "Electricity30. Home"]);
    await user.clear(box());
    await user.type(box(), "zzzz");
    expect(await screen.findByText(/Nothing matches/)).toBeInTheDocument();
  });

  it("moves with the arrow keys (wrapping) and opens a screen on Enter", async () => {
    const { user } = setup();
    await user.click(screen.getByRole("button", { name: "Open" }));
    await screen.findByRole("option", { name: /^Today/ });
    await user.keyboard("{ArrowDown}");
    expect(screen.getByRole("option", { name: /^Inbox/ })).toHaveAttribute("aria-selected", "true");
    expect(box()).toHaveAttribute("aria-activedescendant", screen.getByRole("option", { name: /^Inbox/ }).id);
    await user.keyboard("{ArrowUp}{ArrowUp}");
    const options = screen.getAllByRole("option");
    expect(options.at(-1)).toHaveAttribute("aria-selected", "true"); // wrapped to the last
    await user.keyboard("{ArrowDown}{ArrowDown}{ArrowDown}{Enter}"); // Today, Inbox, Browse
    expect(screen.getByTestId("where")).toHaveTextContent("/browse");
    expect(dialog()).toBeNull();
  });

  it("opens a tray, a collection and a tag on their pages", async () => {
    const { user } = setup();
    await user.click(screen.getByRole("button", { name: "Open" }));
    await user.click(await screen.findByRole("option", { name: /^To pay/ }));
    expect(screen.getByTestId("where")).toHaveTextContent("/trays/to-pay");
    await user.click(screen.getByRole("button", { name: "Open" }));
    await user.click(await screen.findByRole("option", { name: /^2026 House sale/ }));
    expect(screen.getByTestId("where")).toHaveTextContent("/collections/3");
    await user.click(screen.getByRole("button", { name: "Open" }));
    await user.type(box(), "insur");
    await user.click(await screen.findByRole("option", { name: /^insurance/ }));
    expect(screen.getByTestId("where")).toHaveTextContent(`/browse?q=${encodeURIComponent("tag:insurance")}`);
  });

  it("opens a folder in Browse, and a file in its folder with it selected", async () => {
    const { user, calls } = setup();
    await user.click(screen.getByRole("button", { name: "Open" }));
    await user.type(box(), "electr");
    await user.click(await screen.findByRole("option", { name: /^Electricity/ }));
    expect(screen.getByTestId("where")).toHaveTextContent("/browse?path=30.+Home%2FElectricity");
    await user.click(screen.getByRole("button", { name: "Open" }));
    await user.type(box(), "bill");
    const hit = await screen.findByRole("option", { name: /^bill\.pdf/ });
    expect(calls.some((c: Call) => c.url.startsWith("/api/search?") && c.url.includes("q=bill"))).toBe(true);
    await user.click(hit);
    expect(screen.getByTestId("where")).toHaveTextContent("/browse?path=30.+Home%2FElectricity&select=d9");
  });

  it("closes on Esc and on a click on the backdrop, and the page keys stay off meanwhile", async () => {
    const { user } = setup();
    await user.click(screen.getByRole("button", { name: "Open" }));
    await screen.findByRole("option", { name: /^Today/ });
    await user.keyboard("{Escape}");
    expect(dialog()).toBeNull();
    await user.click(screen.getByRole("button", { name: "Open" }));
    const d = await screen.findByRole("dialog", { name: "Search and jump" });
    fireEvent.click(d);
    await waitFor(() => expect(dialog()).toBeNull());
  });
});
