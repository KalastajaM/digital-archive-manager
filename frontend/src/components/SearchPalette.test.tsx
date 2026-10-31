/** Search and jump (Cmd+K / Ctrl+K): opens by key in both looks, filters the trays,
 * collections, tags, folders and files (no screens), moves with the arrow keys, opens the
 * chosen thing where it lives and closes on Esc. A last row searches the archive; filters
 * typed in the box (tag:, collection:, ...) list their values to take with Enter or Tab. */
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
const TAG_LIST = [
  { name: "insurance", files: 14 },
  { name: "invoice", files: 3 },
  { name: "Ilmoitus", files: 1 },
  { name: "tax", files: 2 },
];
const HIT = { drive_id: "d9", path: "30. Home/Electricity/bill.pdf", name: "bill.pdf", snippet: "", rank: 1, size: 1, mtime: 1, marks: [], connected: true };

const ROUTES = {
  "GET /api/trays": { body: TRAYS },
  "GET /api/collections": { body: COLLECTIONS },
  "GET /api/tags/all": { body: TAGS },
  "GET /api/tags": (call: Call) => {
    const prefix = (new URL(call.url, "http://x").searchParams.get("prefix") ?? "").toLowerCase();
    return { body: TAG_LIST.filter((t) => t.name.toLowerCase().startsWith(prefix)) };
  },
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
});

describe("Search and jump", () => {
  it("opens on Cmd+K on a Mac, and Ctrl+K does nothing there", async () => {
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

  it("offers the trays and collections before anything is typed, and no screens", async () => {
    const { user } = setup();
    await user.click(screen.getByRole("button", { name: "Open" }));
    expect(await screen.findByRole("option", { name: /^To pay/ })).toBeInTheDocument();
    expect(await screen.findByRole("option", { name: /^2026 House sale/ })).toBeInTheDocument();
    for (const screenName of ["Today", "Inbox", "Browse", "Settings", "Help"]) {
      expect(screen.queryByRole("option", { name: new RegExp(`^${screenName}$`) })).toBeNull();
    }
    expect(screen.queryByRole("group", { name: "Screens" })).toBeNull();
    expect(screen.queryByRole("option", { name: /^insurance/ })).toBeNull(); // tags and folders only when searched
    expect(screen.queryByRole("option", { name: /Search the archive for/ })).toBeNull(); // no query, no search row
  });

  it("filters as you type, best match first, and ends with a row that searches the archive", async () => {
    const { user } = setup();
    await user.click(screen.getByRole("button", { name: "Open" }));
    await user.type(box(), "ho");
    await screen.findByRole("option", { name: /^2026 House sale/ });
    expect(screen.queryByRole("option", { name: /^To pay/ })).toBeNull();
    const folders = within(screen.getByRole("group", { name: "Folders" })).getAllByRole("option");
    expect(folders.map((o) => o.textContent)).toEqual(["30. Home", "Electricity30. Home"]);
    const options = screen.getAllByRole("option");
    expect(options.at(-1)).toHaveTextContent("Search the archive for \u201cho\u201d");
    await user.clear(box());
    await user.type(box(), "zzzz");
    const only = await screen.findAllByRole("option");
    expect(only).toHaveLength(1); // nothing matches, the search row stays
    await user.click(only[0]);
    expect(screen.getByTestId("where")).toHaveTextContent("/browse?q=zzzz");
    expect(dialog()).toBeNull();
  });

  it("the search row opens Browse's search with the words and the filters, as Browse's own box does", async () => {
    const { user } = setup();
    await user.click(screen.getByRole("button", { name: "Open" }));
    await user.type(box(), 'water tag:insurance collection:"House sale" ');
    await user.click(await screen.findByRole("option", { name: /Search the archive for/ }));
    expect(screen.getByTestId("where")).toHaveTextContent(`/browse?q=${encodeURIComponent('water tag:insurance collection:"House sale"').replace(/%20/g, "+")}`);
  });

  it("moves with the arrow keys (wrapping) and opens the chosen row on Enter", async () => {
    const { user } = setup();
    await user.click(screen.getByRole("button", { name: "Open" }));
    await screen.findByRole("option", { name: /^To pay/ });
    await user.keyboard("{ArrowDown}");
    expect(screen.getByRole("option", { name: /^Follow up/ })).toHaveAttribute("aria-selected", "true");
    expect(box()).toHaveAttribute("aria-activedescendant", screen.getByRole("option", { name: /^Follow up/ }).id);
    await user.keyboard("{ArrowUp}{ArrowUp}");
    const options = screen.getAllByRole("option");
    expect(options.at(-1)).toHaveAttribute("aria-selected", "true"); // wrapped to the last
    await user.keyboard("{ArrowDown}{ArrowDown}{Enter}"); // To pay, Follow up
    expect(screen.getByTestId("where")).toHaveTextContent("/trays/follow-up");
    expect(dialog()).toBeNull();
  });

  it("opens a tray, a collection and a tag on their pages", async () => {
    const { user } = setup();
    await user.click(screen.getByRole("button", { name: "Open" }));
    await user.click(await screen.findByRole("option", { name: /^To pay/ }));
    expect(screen.getByTestId("where")).toHaveTextContent("/trays/to-pay");
    await user.click(screen.getByRole("button", { name: "Open" }));
    await user.click(await screen.findByRole("option", { name: /^2026 House sale/ }));
    expect(screen.getByTestId("where")).toHaveTextContent("/browse?tree=collections&q=collection%3A%222026+House+sale%22");
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
    await screen.findByRole("option", { name: /^To pay/ });
    await user.keyboard("{Escape}");
    expect(dialog()).toBeNull();
    await user.click(screen.getByRole("button", { name: "Open" }));
    const d = await screen.findByRole("dialog", { name: "Search and jump" });
    fireEvent.click(d);
    await waitFor(() => expect(dialog()).toBeNull());
  });

  describe("filter suggestions", () => {
    const values = () => within(screen.getByRole("group", { name: "Filters" })).getAllByRole("option").map((o) => o.textContent);

    it("lists the tags that start with what follows tag:, ignoring case and accents, and Enter takes one", async () => {
      const { user } = setup();
      await user.click(screen.getByRole("button", { name: "Open" }));
      await user.type(box(), "tag:i");
      await waitFor(() => expect(values()).toEqual(["tag:insurance14", "tag:invoice3", "tag:Ilmoitus1"]));
      await user.type(box(), "n");
      await waitFor(() => expect(values()).toEqual(["tag:insurance14", "tag:invoice3"]));
      await user.keyboard("{ArrowDown}{Enter}");
      expect(box()).toHaveValue("tag:invoice ");
      expect(dialog()).not.toBeNull(); // the palette stays open
      expect(box()).toHaveFocus();
    });

    it("Tab takes the active value too, quotes it when it has spaces, and later filters still work", async () => {
      const { user } = setup();
      await user.click(screen.getByRole("button", { name: "Open" }));
      await user.type(box(), "tag:insurance coll");
      await waitFor(() => expect(values()).toEqual(["collection:"]));
      await user.keyboard("{Tab}");
      expect(box()).toHaveValue("tag:insurance collection:");
      await user.type(box(), "hou");
      await waitFor(() => expect(values()).toEqual(['collection:"2026 House sale"']));
      await user.keyboard("{Tab}");
      expect(box()).toHaveValue('tag:insurance collection:"2026 House sale" ');
      await user.type(box(), "water");
      expect(screen.getAllByRole("option").at(-1)).toHaveTextContent("Search the archive for \u201cwater tag:insurance collection:\"2026 House sale\"\u201d");
    });

    it("offers a filter name for a few letters (co becomes collection:)", async () => {
      const { user } = setup();
      await user.click(screen.getByRole("button", { name: "Open" }));
      await user.type(box(), "co");
      await waitFor(() => expect(values()).toContain("collection:"));
      await user.keyboard("{Enter}");
      expect(box()).toHaveValue("collection:");
    });

    it("takes the value at the caret and leaves the text after it", async () => {
      const { user } = setup();
      await user.click(screen.getByRole("button", { name: "Open" }));
      await user.type(box(), "tag:ta water");
      await user.keyboard("{Home}{ArrowRight}{ArrowRight}{ArrowRight}{ArrowRight}{ArrowRight}"); // after "tag:t"
      await waitFor(() => expect(values()).toEqual(["tag:tax2"]));
      await user.keyboard("{Enter}");
      expect(box()).toHaveValue("tag:tax water");
    });

    it("Esc closes the suggestions first and the palette on the second press; typing brings them back", async () => {
      const { user } = setup();
      await user.click(screen.getByRole("button", { name: "Open" }));
      await user.type(box(), "tag:in");
      await waitFor(() => expect(values()).toHaveLength(2));
      await user.keyboard("{Escape}");
      expect(dialog()).not.toBeNull();
      expect(screen.queryByRole("group", { name: "Filters" })).toBeNull();
      await user.type(box(), "s");
      await waitFor(() => expect(screen.getByRole("group", { name: "Filters" })).toBeInTheDocument());
      await user.keyboard("{Escape}{Escape}");
      expect(dialog()).toBeNull();
    });

    it("is a combobox over a listbox: the active suggestion is the activedescendant", async () => {
      const { user } = setup();
      await user.click(screen.getByRole("button", { name: "Open" }));
      await user.type(box(), "tag:in");
      const first = (await screen.findAllByRole("option"))[0];
      expect(first).toHaveAttribute("aria-selected", "true");
      expect(box()).toHaveAttribute("aria-activedescendant", first.id);
      expect(box()).toHaveAttribute("aria-expanded", "true");
      expect(screen.getByRole("listbox", { name: "Results" })).toContainElement(first);
    });
  });
});
