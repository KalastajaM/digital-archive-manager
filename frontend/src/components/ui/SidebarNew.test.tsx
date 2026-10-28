import { cleanup, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockFetch, renderWithProviders } from "../../test-utils";
import { Sidebar } from "./Sidebar";

const nav = () => screen.getByRole("navigation", { name: "Main" });

const SAUNA = { id: 7, name: "Sauna", state: "open", parent_id: null, path: ["Sauna"], kind: null, position: 0, members: [], files: 6 };
const TAGS = [
  { name: "insurance", files: 14, pinned: true },
  { name: "taxes", files: 3, pinned: false },
];

function setup(onSearch?: () => void) {
  mockFetch({
    "GET /api/status": { body: { inbox_count: 7 } },
    "GET /api/today": { body: { attention: [], overview: { inbox: 0, trays: [], collections: [] } } },
    "GET /api/trays": { body: { trays: [], errors: [] } },
    "GET /api/collections": { body: [SAUNA] },
    "GET /api/tags/sidebar": { body: TAGS },
    "GET /api/tags/all": { body: { tags: [...TAGS, { name: "a", files: 0, pinned: false }], groups: [] } },
  });
  renderWithProviders(
    <MemoryRouter initialEntries={["/browse"]}>
      <Sidebar onSearch={onSearch} />
    </MemoryRouter>,
  );
}

afterEach(() => {
  cleanup();
  delete document.documentElement.dataset.style;
});

describe("Sidebar rows and the New look", () => {
  it("name themselves with a tooltip in New (the icon rail has no labels), with the count", async () => {
    document.documentElement.dataset.style = "new";
    setup();
    const inbox = await within(nav()).findByRole("link", { name: "Inbox (7)" });
    expect(inbox).toHaveAttribute("title", "Inbox (7)");
    expect(within(nav()).getByRole("link", { name: "Browse" })).toHaveAttribute("title", "Browse");
    expect(within(nav()).getByRole("link", { name: "Starred" })).toHaveAttribute("title", "Starred");
  });

  it("add no tooltip in Classic", async () => {
    setup();
    const inbox = await within(nav()).findByRole("link", { name: "Inbox (7)" });
    expect(inbox).not.toHaveAttribute("title");
    expect(within(nav()).getByRole("link", { name: "Browse" })).not.toHaveAttribute("title");
  });
});

describe("Sidebar layout in the New look", () => {
  it("has a search field that opens search and jump, with the shortcut on it; Classic has none", async () => {
    document.documentElement.dataset.style = "new";
    const open = vi.fn();
    setup(open);
    const field = await screen.findByRole("button", { name: "Search (⌘K)" });
    expect(field).toHaveAttribute("aria-haspopup", "dialog");
    expect(field).toHaveTextContent("⌘K");
    await userEvent.setup().click(field);
    expect(open).toHaveBeenCalledTimes(1);
    cleanup();
    delete document.documentElement.dataset.style;
    setup(open);
    await within(nav()).findByRole("link", { name: "Inbox (7)" });
    expect(screen.queryByRole("button", { name: /^Search/ })).toBeNull();
  });

  it("draws a grip and a file count on a collection, and a + for a new one", async () => {
    document.documentElement.dataset.style = "new";
    setup(() => {});
    const row = await within(nav()).findByRole("link", { name: "Sauna (6)" });
    expect(row.querySelector(".sidebar-grip")).not.toBeNull();
    expect(row).toHaveAttribute("draggable", "true");
    expect(within(nav()).getByRole("link", { name: "New collection" })).toHaveAttribute("href", "/collections?new=1");
  });

  it("splits the tags into Pinned and Recent tags and puts the Tags screen in Archive", async () => {
    document.documentElement.dataset.style = "new";
    setup(() => {});
    await within(nav()).findByRole("link", { name: "insurance (14)" });
    expect(within(nav()).getByRole("button", { name: "Pinned tags section" })).toBeInTheDocument();
    expect(within(nav()).getByRole("button", { name: "Recent tags section" })).toBeInTheDocument();
    const rows = within(nav()).getAllByRole("link").map((a) => a.getAttribute("aria-label"));
    const archive = rows.slice(rows.indexOf("Tags (3)"));
    expect(archive).toEqual(["Tags (3)", "Activity", "Maintenance", "Ask", "Settings", "Help"]);
  });

  it("keeps the Classic arrangement: no grips, no +, one Tags section, Ask first in Archive", async () => {
    setup();
    await within(nav()).findByRole("link", { name: "taxes (3)" });
    expect(nav().querySelector(".sidebar-grip")).toBeNull();
    expect(within(nav()).queryByRole("link", { name: "New collection" })).toBeNull();
    expect(within(nav()).getByRole("link", { name: "Sauna" })).toBeInTheDocument(); // no count in the name
    expect(within(nav()).getByRole("link", { name: "Tags" })).toHaveAttribute("href", "/tags");
    const rows = within(nav()).getAllByRole("link").map((a) => a.getAttribute("aria-label") ?? a.textContent);
    expect(rows.slice(-5)).toEqual(["Ask", "Activity", "Maintenance", "Settings", "Help"]);
  });
});
