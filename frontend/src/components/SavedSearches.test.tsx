/** Saved searches: the sidebar's Searches section, Save search… in Browse's filter row,
 * the ? help's list and the palette's rows. */
import { cleanup, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, describe, expect, it } from "vitest";
import Browse from "../screens/Browse";
import { mockFetch, renderWithProviders } from "../test-utils";
import { SearchHelp } from "./SearchHelp";
import { SearchPalette } from "./SearchPalette";
import { Sidebar } from "./ui/Sidebar";

const LONG = "Bills from the water company that still wait for a decision about the meter";
const SAVED = [
  { id: 1, name: "Sender not set", query: "id:* -from:*", tag_mode: "all", count: 12, more: false, error: null },
  { id: 2, name: "Either tag", query: "tag:a tag:b", tag_mode: "any", count: 500, more: true, error: null },
  { id: 3, name: LONG, query: "date:2026-13", tag_mode: "all", count: null, more: false, error: "'2026-13' is not a real date." },
];

function Where() {
  const l = useLocation();
  return <output aria-label="Address">{l.pathname + l.search}</output>;
}

const nav = () => screen.getByRole("navigation", { name: "Main" });
const address = () => screen.getByRole("status", { name: "Address" }).textContent;

function sidebar(url = "/", extra: Parameters<typeof mockFetch>[0] = {}) {
  const calls = mockFetch({
    "GET /api/status": { body: { inbox_count: 0 } },
    "GET /api/today": { body: { attention: [], overview: { inbox: 0, trays: [], collections: [] } } },
    "GET /api/trays": { body: { trays: [], errors: [] } },
    "GET /api/collections": { body: [] },
    "GET /api/tags/sidebar": { body: [] },
    "GET /api/tags/all": { body: { tags: [], groups: [] } },
    "GET /api/saved-searches": { body: SAVED },
    ...extra,
  });
  renderWithProviders(
    <MemoryRouter initialEntries={[url]}>
      <Sidebar />
      <Where />
    </MemoryRouter>,
  );
  return { calls, user: userEvent.setup() };
}

afterEach(cleanup);

describe("the Searches section", () => {
  it("lists the saved searches by name with their counts, the query in the tooltip", async () => {
    sidebar();
    const row = await within(nav()).findByRole("link", { name: "Sender not set (12)" });
    expect(row).toHaveAttribute("href", "/browse?q=id%3A*+-from%3A*");
    expect(row).toHaveAttribute("title", "Sender not set\nid:* -from:*");
    // past the cap: 500+; Any kept in the address with two tags
    const either = within(nav()).getByRole("link", { name: "Either tag (500+)" });
    expect(either).toHaveAttribute("href", "/browse?q=tag%3Aa+tag%3Ab&tag_mode=any");
    // a query refused now: no count, and why in the tooltip; a long name stays in its box
    const bad = within(nav()).getByRole("link", { name: LONG });
    expect(bad.title).toContain("is not a real date");
    expect(bad.querySelector(".sidebar-label")).toHaveTextContent(LONG);
  });

  it("is hidden while there are none", async () => {
    const { calls } = sidebar("/", { "GET /api/saved-searches": { body: [] } });
    await waitFor(() => expect(calls.some((c) => c.url.includes("/api/saved-searches"))).toBe(true));
    expect(within(nav()).queryByRole("heading", { name: "Searches" })).toBeNull();
  });

  it("marks the row Browse shows now", async () => {
    sidebar("/browse?q=-from%3A*+id%3A*");
    const row = await within(nav()).findByRole("link", { name: "Sender not set (12)" });
    expect(row).toHaveAttribute("aria-current", "page");
    expect(within(nav()).getByRole("link", { name: "Either tag (500+)" })).not.toHaveAttribute("aria-current");
  });

  it("Rename… and Delete with Undo from the right-click menu", async () => {
    const { calls, user } = sidebar("/", {
      "PATCH /api/saved-searches/1": { body: { id: 1, name: "No sender", query: "id:* -from:*", tag_mode: "all" } },
      "DELETE /api/saved-searches/2": { body: { deleted: 2 } },
      "POST /api/saved-searches": { body: { id: 9, name: "Either tag", query: "tag:a tag:b", tag_mode: "any" } },
    });
    const row = await within(nav()).findByRole("link", { name: "Sender not set (12)" });
    await user.pointer({ keys: "[MouseRight]", target: row });
    await user.click(await screen.findByRole("menuitem", { name: "Rename…" }));
    const field = await screen.findByRole("textbox", { name: "Name" });
    await user.clear(field);
    await user.type(field, "No sender");
    await user.click(screen.getByRole("button", { name: "Rename" }));
    await waitFor(() => expect(calls.find((c) => c.method === "PATCH")?.body).toEqual({ name: "No sender" }));

    await user.pointer({ keys: "[MouseRight]", target: within(nav()).getByRole("link", { name: "Either tag (500+)" }) });
    await user.click(await screen.findByRole("menuitem", { name: "Delete" }));
    await waitFor(() => expect(calls.some((c) => c.method === "DELETE" && c.url.endsWith("/api/saved-searches/2"))).toBe(true));
    await user.click(await screen.findByRole("button", { name: "Undo" }));
    await waitFor(() =>
      expect(calls.find((c) => c.method === "POST")?.body).toEqual({ name: "Either tag", query: "tag:a tag:b", tag_mode: "any" }),
    );
  });
});

function browse(url: string, extra: Parameters<typeof mockFetch>[0] = {}) {
  const calls = mockFetch({
    "GET /api/browse": { body: [] },
    "GET /api/status": {
      body: { special_folders: { inbox: "##. Organize", ongoing: "##. Ongoing", important: "##. Important", quarantine: "##. To Delete" } },
    },
    "GET /api/search": { body: [] },
    "GET /api/saved-searches": { body: SAVED },
    ...extra,
  });
  renderWithProviders(
    <MemoryRouter initialEntries={[url]}>
      <Routes>
        <Route path="/browse" element={<Browse />} />
      </Routes>
    </MemoryRouter>,
  );
  return { calls, user: userEvent.setup() };
}

describe("Update to current search", () => {
  it("replaces the query with the search Browse shows, with Undo", async () => {
    const { calls, user } = sidebar("/browse?q=id%3A*+-from%3A*+type%3Apdf", {
      "POST /api/saved-searches": { body: { id: 1, name: "Sender not set", query: "id:* -from:* type:pdf", tag_mode: "all" } },
    });
    const row = await within(nav()).findByRole("link", { name: "Sender not set (12)" });
    await user.pointer({ keys: "[MouseRight]", target: row });
    await user.click(await screen.findByRole("menuitem", { name: "Update to current search" }));
    await waitFor(() =>
      expect(calls.find((c) => c.method === "POST")?.body).toEqual({ name: "Sender not set", query: "id:* -from:* type:pdf", tag_mode: "all", replace: true }),
    );
    await user.click(await screen.findByRole("button", { name: "Undo" }));
    await waitFor(() =>
      expect(calls.filter((c) => c.method === "POST").at(-1)?.body).toEqual({ name: "Sender not set", query: "id:* -from:*", tag_mode: "all", replace: true }),
    );
  });

  it("is greyed when Browse shows no search, or this one", async () => {
    const { user } = sidebar("/browse?q=-from%3A*+id%3A*");
    await user.pointer({ keys: "[MouseRight]", target: await within(nav()).findByRole("link", { name: "Sender not set (12)" }) });
    const same = await screen.findByRole("menuitem", { name: "Update to current search" });
    expect(same).toBeDisabled();
    expect(same).toHaveAccessibleDescription("Browse shows this search already");
    cleanup();
    const again = sidebar("/");
    await again.user.pointer({ keys: "[MouseRight]", target: await within(nav()).findByRole("link", { name: "Sender not set (12)" }) });
    expect(await screen.findByRole("menuitem", { name: "Update to current search" })).toHaveAccessibleDescription("Open a search in Browse first");
  });
});

describe("Save search… in Browse", () => {
  it("saves the search as on screen under a name", async () => {
    const { calls, user } = browse("/browse?q=kela+tag%3Abills", {
      "POST /api/saved-searches": { body: { id: 4, name: "Kela bills", query: "kela tag:bills", tag_mode: "all" } },
    });
    await user.click(await screen.findByRole("button", { name: "Save search…" }));
    await user.type(await screen.findByRole("textbox", { name: "Name" }), "Kela bills");
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(calls.find((c) => c.method === "POST")?.body).toEqual({ name: "Kela bills", query: "kela tag:bills", tag_mode: "all", replace: false }),
    );
    await waitFor(() => expect(screen.queryByRole("textbox", { name: "Name" })).toBeNull());
  });

  it("an open saved search is named already; its name asks to replace it", async () => {
    let posts = 0;
    const { calls, user } = browse("/browse?q=id%3A*+-from%3A*", {
      "POST /api/saved-searches": () =>
        ++posts === 1
          ? { status: 409, body: { error: 'A search named "Sender not set" exists' } }
          : { body: { id: 1, name: "Sender not set", query: "id:* -from:*", tag_mode: "all" } },
    });
    await user.click(await screen.findByRole("button", { name: "Save search…" }));
    await waitFor(() => expect(screen.getByRole("textbox", { name: "Name" })).toHaveValue("Sender not set"));
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByText(/exists\. Replace it with this search\?/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Replace" }));
    await waitFor(() => expect(calls.filter((c) => c.method === "POST").at(-1)?.body).toMatchObject({ replace: true }));
  });
});

describe("the ? help and the palette", () => {
  it("the help lists the saved searches; a click puts the query in the box", async () => {
    mockFetch({ "GET /api/saved-searches": { body: SAVED } });
    let used = "";
    const user = userEvent.setup();
    renderWithProviders(
      <MemoryRouter>
        <SearchHelp onUse={(q) => (used = q)} />
      </MemoryRouter>,
    );
    await user.click(screen.getByRole("button", { name: "Search help" }));
    expect(await screen.findByRole("heading", { name: "Your saved searches" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "id:* -from:*" }));
    expect(used).toBe("id:* -from:*");
  });

  it("the palette finds a saved search by name and opens it", async () => {
    mockFetch({
      "GET /api/saved-searches": { body: SAVED },
      "GET /api/trays": { body: { trays: [], errors: [] } },
      "GET /api/collections": { body: [] },
      "GET /api/tags/all": { body: { tags: [], groups: [] } },
      "GET /api/folders": { body: [] },
      "GET /api/search": { body: [] },
    });
    const user = userEvent.setup();
    renderWithProviders(
      <MemoryRouter>
        <SearchPalette open onClose={() => {}} />
        <Where />
      </MemoryRouter>,
    );
    await user.type(screen.getByRole("combobox"), "sender");
    const option = await screen.findByRole("option", { name: /Sender not set/ });
    await user.click(option);
    expect(address()).toBe("/browse?q=id%3A*+-from%3A*");
  });
});
