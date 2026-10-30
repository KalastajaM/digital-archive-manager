/** Browse's left pane in the New look: Folders | Collections | Tags. A collection or tag picked
 * in its tree is a search filter (a chip), so the list shows its files from the whole archive. */
import { cleanup, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import type { CollectionRow } from "../api/client";
import { type Call, mockFetch, renderWithProviders } from "../test-utils";
import css from "../styles-new.css?raw";
import Browse from "./Browse";

const coll = (id: number, name: string): CollectionRow => ({
  id,
  name,
  state: "open",
  created: 1,
  closed_at: null,
  publish: { ongoing: true },
  ongoing_rel: null,
  members: [],
  ongoing_status: null,
  summary: "",
  groups: [],
  parent_id: null,
  path: [name],
  kind: null,
  position: id,
  files: 0,
  open_checks: 0,
});

const queryOf = (call: Call) => new URL(call.url, "http://x").searchParams;
const searches = (calls: Call[]) => calls.filter((c) => c.url.startsWith("/api/search"));
const where = () => screen.getByTestId("where").textContent ?? "";
const chips = () => within(screen.getByRole("list", { name: "Search filters" })).getAllByRole("listitem").map((li) => li.textContent);
function Where() {
  const loc = useLocation();
  return <p data-testid="where">{loc.pathname + loc.search}</p>;
}

function setup(url: string) {
  const calls = mockFetch({
    "GET /api/browse": { body: [] },
    "GET /api/status": {
      body: { special_folders: { inbox: "##. Organize", ongoing: "##. Ongoing", important: "##. Important", quarantine: "##. To Delete" } },
    },
    "GET /api/search": { body: [] },
    "GET /api/activity": { body: [] },
    "GET /api/collections": { body: [coll(1, "Legal"), coll(3, "Car")] },
    "GET /api/tags/all": {
      body: { tags: [{ name: "medical", files: 2, pinned: false, group_id: null }, { name: "dental", files: 1, pinned: false, group_id: null }], groups: [] },
    },
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

const switcher = () => screen.getByRole("group", { name: "Tree" });

beforeEach(() => {
  localStorage.clear();
  document.documentElement.dataset.style = "new";
});
afterEach(() => {
  cleanup();
  delete document.documentElement.dataset.style;
});

describe("Browse's tree switch", () => {
  it("shows the chosen tree and keeps it in the address", async () => {
    const { user } = setup("/browse");
    await waitFor(() => expect(within(switcher()).getByRole("button", { name: "Folders" })).toHaveAttribute("aria-pressed", "true"));
    expect(screen.getByRole("navigation", { name: "Folders" })).toBeInTheDocument();
    await user.click(within(switcher()).getByRole("button", { name: "Collections" }));
    expect(await screen.findByRole("navigation", { name: "Collections" })).toBeInTheDocument();
    expect(where()).toContain("tree=collections");
    cleanup();
    setup("/browse?tree=tags");
    expect(await screen.findByRole("navigation", { name: "Tags" })).toBeInTheDocument();
  });

  it("picking a collection searches it, as a chip", async () => {
    const { calls, user } = setup("/browse?tree=collections");
    await user.click(await screen.findByText("Car"));
    await waitFor(() => expect(queryOf(searches(calls).at(-1) as Call).get("q")).toBe("collection:Car"));
    expect(chips()).toEqual(["collection:Car×"]);
  });

  it("a pick keeps the words and widens This folder to the archive", async () => {
    const { calls, user } = setup("/browse?path=10.%20Financial&tree=collections&q=kela");
    await user.click(within(await screen.findByRole("group", { name: "Search scope" })).getByRole("button", { name: "Folder" }));
    await waitFor(() => expect(queryOf(searches(calls).at(-1) as Call).get("folder")).toBe("10. Financial"));
    await user.click(await screen.findByText("Car"));
    await waitFor(() => expect(queryOf(searches(calls).at(-1) as Call).get("q")).toBe("kela collection:Car"));
    expect(queryOf(searches(calls).at(-1) as Call).get("folder")).toBeNull();
  });

  it("a second pick replaces the first; cmd-click on a tag adds", async () => {
    const { user } = setup("/browse?tree=collections");
    await user.click(await screen.findByText("Car"));
    await user.click(screen.getByText("Legal"));
    await waitFor(() => expect(chips()).toEqual(["collection:Legal×"]));
    await user.click(within(switcher()).getByRole("button", { name: "Tags" }));
    await user.click(await screen.findByText("medical"));
    await user.keyboard("{Meta>}");
    await user.click(screen.getByText("dental"));
    await user.keyboard("{/Meta}");
    await waitFor(() => expect(chips()).toEqual(["tag:medical×", "tag:dental×"]));
  });

  it("the picked collection is highlighted", async () => {
    const { user } = setup("/browse?tree=collections");
    await user.click(await screen.findByText("Car"));
    const tree = screen.getByRole("navigation", { name: "Collections" });
    await waitFor(() => expect(within(tree).getByText("Car").closest('[role="treeitem"]')).toHaveAttribute("aria-current", "true"));
  });

  it("the switch shows only icons, at any width: the names are the tooltips and button names", async () => {
    setup("/browse");
    const buttons = await waitFor(() => within(switcher()).getAllByRole("button"));
    expect(buttons.map((b) => b.getAttribute("data-tip"))).toEqual(["Folders", "Collections", "Tags"]);
    expect(buttons.map((b) => b.getAttribute("aria-label"))).toEqual(["Folders", "Collections", "Tags"]);
    expect(buttons.every((b) => b.querySelector("svg") && b.textContent === "")).toBe(true);
    // each icon centred in its box
    expect(css).toMatch(/\.tree-switch \.segmented-option\s*{[^}]*align-items:\s*center;[^}]*justify-content:\s*center/);
  });
});
