/** The sidebar's right-click menus: the same entries, wording and sheets as Browse's
 * collection and tag trees. */
import { cleanup, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, useLocation } from "react-router-dom";
import { afterEach, describe, expect, it } from "vitest";
import { useContextMenuKeys } from "../../contextMenus";
import { mockFetch, renderWithProviders } from "../../test-utils";
import { Sidebar } from "./Sidebar";

const nav = () => screen.getByRole("navigation", { name: "Main" });
const coll = (id: number, name: string, position: number) => ({
  id,
  name,
  state: "open",
  parent_id: null,
  path: [name],
  kind: null,
  position,
  members: [],
  files: 0,
  open_checks: 0,
  groups: [],
});
const TAGS = [
  { name: "insurance", files: 14, pinned: true },
  { name: "taxes", files: 3, pinned: false },
];

function Where() {
  const l = useLocation();
  return <output aria-label="Address">{l.pathname + l.search}</output>;
}

function Keys() {
  useContextMenuKeys();
  return null;
}

function setup() {
  const calls = mockFetch({
    "GET /api/status": { body: { inbox_count: 0 } },
    "GET /api/today": { body: { attention: [], overview: { inbox: 0, trays: [], collections: [] } } },
    "GET /api/trays": { body: { trays: [], errors: [] } },
    "GET /api/collections": { body: [coll(7, "Sauna", 0), coll(8, "Car", 1)] },
    "GET /api/tags/sidebar": { body: TAGS },
    "GET /api/tags/all": { body: { tags: TAGS.map((t) => ({ ...t, group_id: null })), groups: [] } },
    "POST /api/tags/pin": { body: { message: "Unpinned insurance", undo: null } },
  });
  renderWithProviders(
    <MemoryRouter initialEntries={["/"]}>
      <Keys />
      <Sidebar />
      <Where />
    </MemoryRouter>,
  );
  return { calls, user: userEvent.setup() };
}

const items = (menu: HTMLElement) => Array.from(menu.querySelectorAll('[role^="menuitem"]')).map((b) => b.querySelector(".menu-item-text")?.firstChild?.textContent);

afterEach(() => {
  cleanup();
  delete document.documentElement.dataset.style;
});

describe("Sidebar right-click menus", () => {
  it("a collection row has Browse's entries: Open, New collection inside…, Merge into…, Delete…, then its order", async () => {
    const { user } = setup();
    const sauna = await within(nav()).findByRole("link", { name: "Sauna" });
    await user.pointer({ keys: "[MouseRight]", target: sauna });
    const menu = await screen.findByRole("menu", { name: "Order of Sauna" });
    expect(items(menu)).toEqual(["Open", "New collection inside…", "Merge into…", "Delete…", "Move up", "Move down"]);
    await user.click(within(menu).getByRole("menuitem", { name: "Delete…" }));
    expect(await screen.findByRole("dialog", { name: "Delete Sauna?" })).toBeInTheDocument();
  });

  it("Open goes to the collection, New collection inside… opens its sheet", async () => {
    const { user } = setup();
    await user.pointer({ keys: "[MouseRight]", target: await within(nav()).findByRole("link", { name: "Car" }) });
    await user.click(await screen.findByRole("menuitem", { name: "Open" }));
    expect(screen.getByRole("status", { name: "Address" })).toHaveTextContent("/browse?tree=collections&q=collection%3ACar");
    await user.pointer({ keys: "[MouseRight]", target: within(nav()).getByRole("link", { name: "Car" }) });
    await user.click(await screen.findByRole("menuitem", { name: "New collection inside…" }));
    expect(await screen.findByRole("dialog", { name: "New collection inside Car" })).toBeInTheDocument();
  });

  it("the Collections caption offers New collection", async () => {
    const { user } = setup();
    await within(nav()).findByRole("link", { name: "Sauna" });
    await user.pointer({ keys: "[MouseRight]", target: within(nav()).getByRole("link", { name: "Collections" }) });
    const menu = await screen.findByRole("menu", { name: "Collections" });
    await user.click(within(menu).getByRole("menuitem", { name: "New collection" }));
    expect(await screen.findByRole("dialog", { name: "New collection" })).toBeInTheDocument();
  });

  it("Shift+F10 on a focused collection opens the same menu", async () => {
    const { user } = setup();
    (await within(nav()).findByRole("link", { name: "Sauna" })).focus();
    await user.keyboard("{Shift>}{F10}{/Shift}");
    expect(await screen.findByRole("menu", { name: "Order of Sauna" })).toBeInTheDocument();
  });

  it("a tag row: Rename…, Merge into…, Pin or Unpin, Delete…", async () => {
    const { calls, user } = setup();
    const tag = await within(nav()).findByRole("link", { name: "insurance (14)" });
    await user.pointer({ keys: "[MouseRight]", target: tag });
    const menu = await screen.findByRole("menu", { name: "Actions for insurance" });
    expect(items(menu)).toEqual(["Rename…", "Merge into…", "Unpin from the sidebar", "Delete…"]);
    await user.click(within(menu).getByRole("menuitem", { name: "Unpin from the sidebar" }));
    await waitFor(() => expect(calls.filter((c) => c.url === "/api/tags/pin")).toHaveLength(1));
    expect(calls.find((c) => c.url === "/api/tags/pin")!.body).toEqual({ names: ["insurance"], pinned: false });
    await user.pointer({ keys: "[MouseRight]", target: within(nav()).getByRole("link", { name: "taxes (3)" }) });
    expect(items(await screen.findByRole("menu", { name: "Actions for taxes" }))).toContain("Pin to the sidebar");
    await user.click(screen.getByRole("menuitem", { name: "Rename…" }));
    expect(await screen.findByRole("dialog", { name: "Rename taxes" })).toBeInTheDocument();
  });

  it("the Tags caption offers New tag (Classic), as do the Pinned and Recent tags captions (New)", async () => {
    const { user } = setup();
    await within(nav()).findByRole("link", { name: "insurance (14)" });
    await user.pointer({ keys: "[MouseRight]", target: within(nav()).getByRole("link", { name: "Tags" }) });
    await user.click(await screen.findByRole("menuitem", { name: "New tag" }));
    expect(await screen.findByRole("dialog", { name: "New tag" })).toBeInTheDocument();
    cleanup();
    document.documentElement.dataset.style = "new";
    const again = setup();
    await within(nav()).findByRole("link", { name: "insurance (14)" });
    await again.user.pointer({ keys: "[MouseRight]", target: within(nav()).getByRole("heading", { name: "Recent tags" }) });
    await again.user.click(await screen.findByRole("menuitem", { name: "New tag" }));
    expect(await screen.findByRole("dialog", { name: "New tag" })).toBeInTheDocument();
  });
});
