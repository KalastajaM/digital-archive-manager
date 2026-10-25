import { cleanup, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, describe, expect, it } from "vitest";
import type { SearchHit } from "../api/client";
import { Sidebar } from "../components/ui/Sidebar";
import { type Call, mockFetch, renderWithProviders } from "../test-utils";
import Browse from "./Browse";
import Tags from "./Tags";
import Today from "./Today";

afterEach(() => {
  cleanup();
  localStorage.clear();
});

const where = () => screen.getByTestId("where").textContent;
function Where() {
  const loc = useLocation();
  return <p data-testid="where">{loc.pathname + loc.search}</p>;
}
const hit = (id: string, name: string): SearchHit => ({
  drive_id: id,
  path: `X/${name}`,
  name,
  snippet: name,
  rank: 0,
  size: 1,
  mtime: 1,
  marks: [],
});
const queryOf = (call: Call) => new URL(call.url, "http://x").searchParams;
const searches = (calls: Call[]) => calls.filter((c) => c.url.startsWith("/api/search"));
const posts = (calls: Call[], url: string) => calls.filter((c) => c.method === "POST" && c.url === url);

const UNDO = { drop: [], detach: [], restore: [] };
const TAGS = {
  tags: [
    { name: "medical", files: 3, pinned: false, group_id: null },
    { name: "health", files: 1, pinned: true, group_id: 1 },
    { name: "Kela", files: 2, pinned: false, group_id: null },
  ],
  groups: [{ id: 1, name: "Care" }],
};

describe("Today's Search card", () => {
  it("Enter opens Browse with the words and the finished tag:name as a filter", async () => {
    mockFetch({
      "GET /api/today": {
        body: {
          attention: [],
          inbox_stats: { count: 0, overdue: 0, oldest_days: null, buckets: [] },
          found: [],
          open_items: [],
          overview: { inbox: 0, trays: [], collections: [] },
          reminders: { last_run: null, errors: {}, skipped: null },
          tray_errors: [],
          ongoing_sync_failure: null,
          unmanaged_ongoing: 0,
          unmanaged_important: 0,
        },
      },
      "GET /api/trays": { body: { trays: [], errors: [] } },
    });
    const user = userEvent.setup();
    renderWithProviders(
      <MemoryRouter>
        <Routes>
          <Route path="/" element={<Today today="2026-10-19" />} />
          <Route path="*" element={null} />
        </Routes>
        <Where />
      </MemoryRouter>,
    );
    const card = await screen.findByRole("region", { name: "Search" });
    await user.type(within(card).getByRole("searchbox", { name: "Search the archive" }), "Kela tag:medical{Enter}");
    expect(where()).toBe("/browse?q=Kela&tag=medical");
  });
});

describe("Browse with tags", () => {
  function setup(url: string, extra: Parameters<typeof mockFetch>[0] = {}) {
    const calls = mockFetch({
      "GET /api/browse": { body: [] },
      "GET /api/status": {
        body: { special_folders: { inbox: "##. Organize", ongoing: "##. Ongoing", important: "##. Important", quarantine: "##. To Delete" } },
      },
      "GET /api/search": { body: [hit("a", "one.pdf")] },
      "GET /api/tags": (call) => ({
        body: [
          { name: "medical", files: 3 },
          { name: "Medicine", files: 1 },
        ].filter((t) => t.name.toLowerCase().startsWith((queryOf(call).get("prefix") ?? "").toLowerCase())),
      }),
      ...extra,
    });
    const user = userEvent.setup();
    renderWithProviders(
      <MemoryRouter initialEntries={[url]}>
        <Routes>
          <Route
            path="/browse"
            element={
              <>
                <Browse />
                <Where />
              </>
            }
          />
        </Routes>
      </MemoryRouter>,
    );
    return { calls, user };
  }

  it("the address sets the words and the tag chips, and the search sends them all", async () => {
    const { calls } = setup("/browse?q=Kela&tag=medical&tag=tax%20return");
    expect(await screen.findByText("one.pdf")).toBeInTheDocument();
    const chips = screen.getByRole("list", { name: "Tag filters" });
    expect(within(chips).getAllByRole("listitem").map((li) => li.textContent)).toEqual(["medical×", "tax return×"]);
    expect(screen.getByRole("searchbox", { name: "Search" })).toHaveValue("Kela");
    const q = queryOf(searches(calls)[0]);
    expect(q.get("q")).toBe("Kela");
    expect(q.getAll("tag")).toEqual(["medical", "tax return"]);
  });

  it("tags alone search with no words, and a chip's x removes the filter", async () => {
    const { calls, user } = setup("/browse?tag=medical");
    await screen.findByText("one.pdf");
    expect(queryOf(searches(calls)[0]).get("q")).toBe("");
    await user.click(screen.getByRole("button", { name: "Remove tag medical" }));
    expect(where()).toBe("/browse");
    expect(screen.queryByRole("list", { name: "Tag filters" })).not.toBeInTheDocument();
    await waitFor(() => expect(screen.queryByText("one.pdf")).not.toBeInTheDocument());
  });

  it("typing tag:name and a space makes a chip; the words stay in the box", async () => {
    const { calls, user } = setup("/browse");
    await user.type(screen.getByRole("searchbox", { name: "Search" }), "Kela tag:medical ");
    expect(where()).toBe("/browse?tag=medical");
    expect(screen.getByRole("searchbox", { name: "Search" })).toHaveValue("Kela ");
    await waitFor(() => expect(searches(calls).some((c) => queryOf(c).get("q") === "Kela" && queryOf(c).getAll("tag")[0] === "medical")).toBe(true));
  });

  it("suggests matching tags while typing; picking one makes a chip and removes the word", async () => {
    const { user } = setup("/browse");
    const box = screen.getByRole("searchbox", { name: "Search" });
    await user.type(box, "Kela med");
    const list = await screen.findByRole("listbox", { name: "Matching tags" });
    expect(within(list).getAllByRole("option").map((o) => o.textContent)).toEqual(["medical3", "Medicine1"]);
    await user.click(within(list).getByRole("option", { name: /^medical/ }));
    expect(where()).toBe("/browse?tag=medical");
    expect(box).toHaveValue("Kela ");
  });

  it("Enter finishes a tag being typed with the matching suggestion", async () => {
    const { user } = setup("/browse");
    const box = screen.getByRole("searchbox", { name: "Search" });
    await user.type(box, "tag:medi");
    await screen.findByRole("listbox", { name: "Matching tags" });
    await user.type(box, "{Enter}");
    expect(where()).toBe("/browse?tag=medical");
    expect(box).toHaveValue("");
  });
});

describe("Tags screen", () => {
  function setup(extra: Parameters<typeof mockFetch>[0] = {}, tags = TAGS) {
    const calls = mockFetch({
      "GET /api/tags/all": { body: tags },
      "POST /api/tags/undo": { body: { message: "Undone", undo: UNDO } },
      ...extra,
    });
    const user = userEvent.setup();
    renderWithProviders(
      <MemoryRouter initialEntries={["/tags"]}>
        <Tags />
        <Where />
      </MemoryRouter>,
    );
    return { calls, user };
  }
  const menu = async (user: ReturnType<typeof userEvent.setup>, name: string, item: string) => {
    await user.click(await screen.findByRole("button", { name: `Actions for ${name}` }));
    await user.click(await screen.findByRole("menuitem", { name: item }));
  };

  it("lists every tag with its count under its group, each linking to its files", async () => {
    setup();
    const care = await screen.findByRole("region", { name: "Group Care" });
    expect(within(care).getByRole("link", { name: "health" })).toHaveAttribute("href", "/browse?tag=health&q=");
    expect(within(care).getByText("1 file")).toBeInTheDocument();
    const rest = screen.getByRole("region", { name: "Tags in no group" });
    expect(within(rest).getAllByRole("link").map((a) => a.textContent)).toEqual(["Kela", "medical"]);
    expect(within(rest).getByText("3 files")).toBeInTheDocument();
  });

  it("filters through the API", async () => {
    const { calls, user } = setup();
    await screen.findByRole("region", { name: "Group Care" });
    await user.type(screen.getByRole("searchbox", { name: "Filter tags" }), "ke");
    await waitFor(() => expect(calls.some((c) => c.url === "/api/tags/all?query=ke")).toBe(true));
  });

  it("creates a tag; the toast offers Undo", async () => {
    const created = { message: "Created 'later'", undo: { ...UNDO, drop: ["later"] } };
    const { calls, user } = setup({ "POST /api/tags": { body: created } });
    await user.click(await screen.findByRole("button", { name: "New tag" }));
    await user.type(screen.getByRole("textbox", { name: "Name" }), "later");
    await user.click(screen.getByRole("button", { name: "Create" }));
    expect(posts(calls, "/api/tags")[0].body).toEqual({ name: "later" });
    expect(await screen.findByText("Created 'later'")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Undo" }));
    await waitFor(() => expect(posts(calls, "/api/tags/undo")[0].body).toEqual(created.undo));
  });

  it("renames; a name another tag has offers to merge instead", async () => {
    const { calls, user } = setup({
      "POST /api/tags/rename": { body: { message: "Renamed 'Kela' to 'Kelaa'", undo: UNDO } },
      "POST /api/tags/merge": (call) => ({
        body: {
          into: "medical",
          gains: 2,
          removes: ["Kela"],
          message: "2 files get 'medical'; 'Kela' is removed",
          undo: call.body && (call.body as { dry_run?: boolean }).dry_run ? null : UNDO,
        },
      }),
    });
    await menu(user, "Kela", "Rename…");
    const name = screen.getByRole("textbox", { name: "New name" });
    await user.clear(name);
    await user.type(name, "Medical");
    expect(screen.getByText(/already exists/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Rename" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Merge instead" }));
    expect(await screen.findByText("2 files get 'medical'; 'Kela' is removed.")).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Into" })).toHaveValue("medical");
    await user.click(screen.getByRole("button", { name: "Merge" }));
    await waitFor(() => expect(posts(calls, "/api/tags/merge").at(-1)?.body).toEqual({ sources: ["Kela"], into: "medical", dry_run: false }));
    expect(posts(calls, "/api/tags/merge")[0].body).toEqual({ sources: ["Kela"], into: "medical", dry_run: true });
    expect(await screen.findByText("Merged: 2 files get 'medical'; 'Kela' is removed")).toBeInTheDocument();
  });

  it("a plain rename sends the new name and offers Undo", async () => {
    const { calls, user } = setup({ "POST /api/tags/rename": { body: { message: "Renamed 'Kela' to 'Kelaa'", undo: UNDO } } });
    await menu(user, "Kela", "Rename…");
    const name = screen.getByRole("textbox", { name: "New name" });
    await user.clear(name);
    await user.type(name, "Kelaa");
    await user.click(screen.getByRole("button", { name: "Rename" }));
    expect(posts(calls, "/api/tags/rename")[0].body).toEqual({ name: "Kela", new_name: "Kelaa" });
    expect(await screen.findByRole("button", { name: "Undo" })).toBeInTheDocument();
  });

  it("merges the ticked tags after a preview", async () => {
    const { calls, user } = setup({
      "POST /api/tags/merge": { body: { into: "medical", gains: 1, removes: ["Kela", "health"], message: "1 file gets 'medical'; 'Kela', 'health' are removed", undo: UNDO } },
    });
    await user.click(await screen.findByRole("checkbox", { name: "Select Kela" }));
    await user.click(screen.getByRole("checkbox", { name: "Select health" }));
    await user.click(screen.getByRole("button", { name: "Merge selected" }));
    await user.selectOptions(screen.getByRole("combobox", { name: "Into" }), "medical");
    expect(await screen.findByText("1 file gets 'medical'; 'Kela', 'health' are removed.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Merge" }));
    await waitFor(() => expect(posts(calls, "/api/tags/merge").at(-1)?.body).toMatchObject({ sources: ["Kela", "health"], into: "medical", dry_run: false }));
  });

  it("delete confirms with the count, then Undo puts it back", async () => {
    const undo = { ...UNDO, restore: [{ name: "medical", drive_ids: ["a"] }] };
    const { calls, user } = setup({ "POST /api/tags/delete": { body: { message: "Deleted 'medical' (on 3 files)", undo } } });
    await menu(user, "medical", "Delete…");
    expect(screen.getByText(/is removed from 3 files/)).toBeInTheDocument();
    expect(posts(calls, "/api/tags/delete")).toHaveLength(0);
    await user.click(screen.getByRole("button", { name: "Delete tag" }));
    expect(posts(calls, "/api/tags/delete")[0].body).toEqual({ name: "medical" });
    await user.click(await screen.findByRole("button", { name: "Undo" }));
    await waitFor(() => expect(posts(calls, "/api/tags/undo")[0].body).toEqual(undo));
  });

  it("pins and unpins from the menu", async () => {
    const { calls, user } = setup({ "POST /api/tags/pin": { body: { message: "Pinned 'medical'", undo: UNDO } } });
    await menu(user, "medical", "Pin to the sidebar");
    expect(posts(calls, "/api/tags/pin")[0].body).toEqual({ names: ["medical"], pinned: true });
    await menu(user, "health", "Unpin from the sidebar");
    expect(posts(calls, "/api/tags/pin")[1].body).toEqual({ names: ["health"], pinned: false });
  });

  it("moves a tag into a group and out of it", async () => {
    const { calls, user } = setup({ "POST /api/tags/group": { body: { message: "Moved 'Kela'", undo: UNDO } } });
    await menu(user, "Kela", "Move to Care");
    expect(posts(calls, "/api/tags/group")[0].body).toEqual({ names: ["Kela"], group_id: 1 });
    await menu(user, "health", "Move out of the group");
    expect(posts(calls, "/api/tags/group")[1].body).toEqual({ names: ["health"], group_id: null });
  });

  it("creates, renames and deletes a group; deleting keeps the tags and Undo restores it", async () => {
    const { calls, user } = setup({
      "POST /api/tags/groups": { body: { id: 2, name: "Money" } },
      "POST /api/tags/groups/1/rename": { body: { id: 1, name: "Health" } },
      "POST /api/tags/groups/1/delete": { body: { name: "Care", members: ["health"], message: "Deleted the group 'Care'" } },
      "POST /api/tags/groups/restore": { body: { id: 3, name: "Care" } },
    });
    await user.click(await screen.findByRole("button", { name: "New group" }));
    await user.type(screen.getByRole("textbox", { name: "Name" }), "Money");
    await user.click(screen.getByRole("button", { name: "Create" }));
    expect(posts(calls, "/api/tags/groups")[0].body).toEqual({ name: "Money" });

    await menu(user, "the group Care", "Rename group…");
    const name = screen.getByRole("textbox", { name: "Name" });
    await user.clear(name);
    await user.type(name, "Health");
    await user.click(screen.getByRole("button", { name: "Rename" }));
    expect(posts(calls, "/api/tags/groups/1/rename")[0].body).toEqual({ name: "Health" });

    await menu(user, "the group Care", "Delete group");
    expect(await screen.findByText(/its tags stay, ungrouped/)).toBeInTheDocument();
    const undo = screen.getAllByRole("button", { name: "Undo" }).at(-1)!;
    await user.click(undo);
    await waitFor(() => expect(posts(calls, "/api/tags/groups/restore")[0].body).toEqual({ name: "Care", members: ["health"] }));
  });

  it("says so when there are no tags", async () => {
    setup({}, { tags: [], groups: [] });
    expect(await screen.findByText("No tags yet")).toBeInTheDocument();
  });
});

describe("Sidebar Tags section", () => {
  function setup(sidebar: unknown[] = [], start = "/") {
    mockFetch({
      "GET /api/status": { body: { inbox_count: 0 } },
      "GET /api/today": { body: { attention: [], overview: { inbox: 0, trays: [], collections: [] } } },
      "GET /api/trays": { body: { trays: [], errors: [] } },
      "GET /api/collections": { body: [] },
      "GET /api/tags/sidebar": { body: sidebar },
    });
    const user = userEvent.setup();
    const view = renderWithProviders(
      <MemoryRouter initialEntries={[start]}>
        <Sidebar />
        <Where />
      </MemoryRouter>,
    );
    return { user, view };
  }
  const SIDEBAR = [
    { name: "health", files: 1, pinned: true },
    { name: "Kela", files: 2, pinned: false },
  ];

  it("lists the tags it is given in order, each opening its files; the caption opens the Tags screen", async () => {
    const { user } = setup(SIDEBAR);
    const nav = screen.getByRole("navigation", { name: "Main" });
    const links = await within(nav).findByRole("link", { name: "health (1)" });
    expect(links).toHaveAttribute("href", "/browse?tag=health&q=");
    expect(within(nav).getByRole("link", { name: "Kela (2)" })).toHaveAttribute("href", "/browse?tag=Kela&q=");
    const all = within(nav).getAllByRole("link").map((a) => a.getAttribute("aria-label") ?? a.textContent);
    expect(all.indexOf("health (1)")).toBeLessThan(all.indexOf("Kela (2)"));
    expect(within(nav).getByRole("link", { name: "Tags" })).toHaveAttribute("href", "/tags");
    await user.click(within(nav).getByRole("link", { name: "Kela (2)" }));
    expect(where()).toBe("/browse?tag=Kela&q=");
  });

  it("marks only the tag Browse filters by as current, none on Browse without a tag", async () => {
    setup(SIDEBAR, "/browse?tag=Kela&q=");
    const nav = screen.getByRole("navigation", { name: "Main" });
    const kela = await within(nav).findByRole("link", { name: "Kela (2)" });
    const health = within(nav).getByRole("link", { name: "health (1)" });
    expect(kela).toHaveAttribute("aria-current", "page");
    expect(kela).toHaveClass("active");
    expect(health).not.toHaveAttribute("aria-current");
    expect(health).not.toHaveClass("active");
  });

  it("marks no tag current on Browse without a tag filter", async () => {
    setup(SIDEBAR, "/browse?path=10.+Financial");
    const nav = screen.getByRole("navigation", { name: "Main" });
    await within(nav).findByRole("link", { name: "Kela (2)" });
    for (const name of ["Kela (2)", "health (1)"]) {
      expect(within(nav).getByRole("link", { name })).not.toHaveAttribute("aria-current");
    }
  });

  it("folds like the other sections and remembers it", async () => {
    const { user, view } = setup(SIDEBAR);
    const nav = screen.getByRole("navigation", { name: "Main" });
    await within(nav).findByRole("link", { name: "Kela (2)" });
    await user.click(within(nav).getByRole("button", { name: "Tags section" }));
    expect(within(nav).queryByRole("link", { name: "Kela (2)" })).toBeNull();
    view.unmount();
    setup(SIDEBAR);
    const again = screen.getByRole("navigation", { name: "Main" });
    await within(again).findByRole("link", { name: "Tags" });
    expect(within(again).queryByRole("link", { name: "Kela (2)" })).toBeNull();
    expect(within(again).getByRole("button", { name: "Tags section" })).toHaveAttribute("aria-expanded", "false");
  });
});
