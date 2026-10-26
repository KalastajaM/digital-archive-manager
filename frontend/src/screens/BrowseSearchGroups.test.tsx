import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, describe, expect, it } from "vitest";
import type { SearchHit } from "../api/client";
import { type Call, dataTransfer, mockFetch, renderWithProviders } from "../test-utils";
import Browse from "./Browse";

afterEach(() => {
  cleanup();
  localStorage.clear();
});

const hit = (id: string, path: string, rank = -1): SearchHit => ({
  drive_id: id,
  path,
  name: path.slice(path.lastIndexOf("/") + 1),
  snippet: path.slice(path.lastIndexOf("/") + 1),
  rank,
  size: 10,
  mtime: 1_700_000_000,
  connected: true, marks: [],
});
// best match first; the folders are not in tree order on purpose
const HITS = [
  hit("c", "30. Car/c.pdf", -4),
  hit("b", "10. Financial/Banks/b.pdf", -3),
  hit("a", "10. Financial/a.pdf", -2),
  hit("d", "10. Financial/Banks/d.pdf", -1),
];

const queryOf = (call: Call) => new URL(call.url, "http://x").searchParams;
const searches = (calls: Call[]) => calls.filter((c) => c.url.startsWith("/api/search"));
const where = () => screen.getByTestId("where").textContent;
function Where() {
  const loc = useLocation();
  return <p data-testid="where">{loc.pathname + loc.search}</p>;
}

function setup(url: string, extra: Parameters<typeof mockFetch>[0] = {}) {
  const calls = mockFetch({
    "GET /api/browse": { body: [] },
    "GET /api/status": {
      body: { special_folders: { inbox: "##. Organize", ongoing: "##. Ongoing", important: "##. Important", quarantine: "##. To Delete" } },
    },
    "GET /api/search": { body: HITS },
    "GET /api/tags": (call) => ({
      body: [
        { name: "medical", files: 3 },
        { name: "Medicine", files: 1 },
        { name: "tax", files: 2 },
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

const results = () => screen.getByRole("list", { name: "Search results" });
/** The list as text: a folder header as "[folder] n", a file as its name. */
const outline = () =>
  within(results())
    .getAllByRole("listitem")
    .map((li) =>
      li.classList.contains("group-head")
        ? `[${li.querySelector(".group-name")?.textContent?.trim()}] ${li.querySelector(".group-count")?.textContent}`
        : li.querySelector(".entry-name")?.textContent,
    );
const view = () => screen.getByRole("group", { name: "View" });

describe("Search results by folder", () => {
  it("Folders groups the hits under their folders, in tree order, with counts", async () => {
    setup("/browse?q=pdf");
    await screen.findByRole("list", { name: "Search results" });
    expect(outline()).toEqual([
      "[10. Financial] 1 match",
      "a.pdf",
      "[10. Financial/Banks] 2 matches",
      "b.pdf",
      "d.pdf",
      "[30. Car] 1 match",
      "c.pdf",
    ]);
    // no per-row Folder column, and no Folder sort
    expect(results().querySelector(".entry-folder")).toBeNull();
    const head = screen.getByRole("group", { name: "Sort by" });
    expect(within(head).queryByRole("button", { name: /Sort by folder/ })).not.toBeInTheDocument();
    expect(within(head).getAllByRole("button").map((b) => b.textContent)).toEqual(["Name", "Date", "Size"]);
  });

  it("Files is the flat list with the Folder column", async () => {
    const { user } = setup("/browse?q=pdf");
    await screen.findByRole("list", { name: "Search results" });
    await user.click(within(view()).getByRole("button", { name: "Files" }));
    expect(outline()).toEqual(["c.pdf", "b.pdf", "a.pdf", "d.pdf"]);
    expect(results().querySelectorAll(".entry-folder")).toHaveLength(4);
    expect(within(screen.getByRole("group", { name: "Sort by" })).getByRole("button", { name: "Sort by folder" })).toBeInTheDocument();
    await user.click(within(view()).getByRole("button", { name: "Folders" }));
    expect(outline()[0]).toBe("[10. Financial] 1 match");
  });

  it("a folder header folds and unfolds its files; the fold is forgotten on a new search", async () => {
    const { user } = setup("/browse?q=pdf");
    await screen.findByRole("list", { name: "Search results" });
    const fold = screen.getByRole("button", { name: "Fold 10. Financial/Banks" });
    expect(fold).toHaveAttribute("aria-expanded", "true");
    await user.click(fold);
    expect(outline()).toEqual(["[10. Financial] 1 match", "a.pdf", "[10. Financial/Banks] 2 matches", "[30. Car] 1 match", "c.pdf"]);
    expect(screen.getByRole("button", { name: "Unfold 10. Financial/Banks" })).toHaveAttribute("aria-expanded", "false");
    await user.click(screen.getByRole("button", { name: "Unfold 10. Financial/Banks" }));
    expect(outline()).toHaveLength(7);
    await user.click(screen.getByRole("button", { name: "Fold 30. Car" }));
    await user.type(screen.getByRole("searchbox", { name: "Search" }), "x");
    await waitFor(() => expect(outline()).toHaveLength(7));
  });

  it("clicking the folder name opens that folder in Browse and leaves the search", async () => {
    const { user } = setup("/browse?q=pdf&tag=medical");
    await screen.findByRole("list", { name: "Search results" });
    await user.click(screen.getByRole("button", { name: "Open folder 10. Financial/Banks" }));
    expect(where()).toBe("/browse?path=10.+Financial%2FBanks");
    expect(screen.getByRole("searchbox", { name: "Search" })).toHaveValue("");
    expect(screen.queryByRole("list", { name: "Search results" })).not.toBeInTheDocument();
    expect(screen.queryByRole("list", { name: "Tag filters" })).not.toBeInTheDocument();
  });

  it("file rows select, preview, drag and Quick Look; headers are not files", async () => {
    const { user } = setup("/browse?q=pdf");
    await screen.findByRole("list", { name: "Search results" });
    // a header is no checkbox and no file
    expect(within(results()).getAllByRole("checkbox")).toHaveLength(4);
    expect(screen.getByRole("checkbox", { name: "Select all files" })).toBeInTheDocument();
    await user.click(within(results()).getByRole("button", { name: /^b\.pdf/ }));
    const preview = await screen.findByRole("region", { name: "Preview" });
    expect(within(preview).getByText("10. Financial/Banks/b.pdf")).toBeInTheDocument();
    await user.keyboard("{Meta>}");
    await user.click(within(results()).getByRole("button", { name: /^c\.pdf/ }));
    await user.keyboard("{/Meta}");
    expect(screen.getByRole("checkbox", { name: "Select b.pdf" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Select c.pdf" })).toBeChecked();
    const row = within(results()).getByText("b.pdf").closest("li")!;
    const dt = dataTransfer();
    fireEvent.dragStart(row, { dataTransfer: dt });
    expect(JSON.parse(dt.data["application/x-dam-files"])).toEqual({ ids: ["b", "c"] });
    expect(screen.getByRole("button", { name: "Move to…" })).toBeEnabled();
    await user.keyboard(" ");
    expect(screen.getByRole("dialog", { name: "Quick Look: c.pdf" })).toBeInTheDocument();
    await user.keyboard("{Escape}");
  });

  it("the arrow keys step over the headers, from file to file", async () => {
    const { user } = setup("/browse?q=pdf");
    await screen.findByRole("list", { name: "Search results" });
    await user.click(within(results()).getByRole("button", { name: /^a\.pdf/ }));
    await user.keyboard("j");
    expect(within(results()).getByText("b.pdf").closest("li")).toHaveAttribute("aria-current", "true");
    await user.keyboard("j j");
    expect(within(results()).getByText("c.pdf").closest("li")).toHaveAttribute("aria-current", "true");
    await user.keyboard("k");
    expect(within(results()).getByText("d.pdf").closest("li")).toHaveAttribute("aria-current", "true");
    expect(results().querySelectorAll('[aria-current="true"]')).toHaveLength(1);
  });

  it("folding a folder drops its files from the selection and from the keyboard order", async () => {
    const { user } = setup("/browse?q=pdf");
    await screen.findByRole("list", { name: "Search results" });
    await user.click(screen.getByRole("checkbox", { name: "Select b.pdf" }));
    await user.click(screen.getByRole("checkbox", { name: "Select c.pdf" }));
    await user.click(screen.getByRole("button", { name: "Fold 10. Financial/Banks" }));
    expect(screen.queryByRole("checkbox", { name: "Select b.pdf" })).not.toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "Select c.pdf" })).toBeChecked();
    expect(screen.getByText("1 selected")).toBeInTheDocument();
  });
});

describe("The tags row", () => {
  it("shows the tags as chips under the toolbar, not in the search box", async () => {
    setup("/browse?q=Kela+tag%3Amedical+tag%3A%22tax+return%22");
    await screen.findByRole("list", { name: "Search results" });
    const chips = screen.getByRole("list", { name: "Search filters" });
    expect(chips.closest(".tag-bar")).not.toBeNull();
    expect(chips.closest(".search")).toBeNull();
    expect(within(chips).getAllByRole("listitem").map((li) => li.textContent)).toEqual(["tag:medical×", "tag:tax return×"]);
    expect(screen.getByRole("searchbox", { name: "Search" })).toHaveValue("Kela");
    expect(within(screen.getByRole("searchbox", { name: "Search" }).closest(".search") as HTMLElement).queryByText("medical")).toBeNull();
  });

  it("there is no row without tags", async () => {
    setup("/browse?q=pdf");
    await screen.findByRole("list", { name: "Search results" });
    expect(document.querySelector(".tag-bar")).toBeNull();
  });

  it("a chip's x removes the tag; the last one removes the row", async () => {
    const { user } = setup("/browse?q=tag%3Amedical+tag%3Atax");
    await screen.findByRole("list", { name: "Search results" });
    await user.click(screen.getByRole("button", { name: "Remove filter tag:medical" }));
    expect(where()).toBe("/browse?q=tag%3Atax");
    await user.click(screen.getByRole("button", { name: "Remove filter tag:tax" }));
    expect(where()).toBe("/browse");
    expect(document.querySelector(".tag-bar")).toBeNull();
  });

  it("+ Tag offers suggestions and adds the picked tag to the address and the search", async () => {
    const { calls, user } = setup("/browse?q=tag%3Amedical");
    await screen.findByRole("list", { name: "Search results" });
    await user.click(screen.getByRole("button", { name: "+ Tag" }));
    const box = screen.getByRole("textbox", { name: "Tag to add" });
    await user.type(box, "ta");
    const list = await screen.findByRole("listbox", { name: "Matching tags" });
    expect(within(list).getAllByRole("option").map((o) => o.textContent)).toEqual(["tax2"]);
    await user.click(within(list).getByRole("option", { name: /^tax/ }));
    expect(where()).toBe("/browse?q=tag%3Amedical+tag%3Atax");
    expect(screen.queryByRole("textbox", { name: "Tag to add" })).not.toBeInTheDocument();
    await waitFor(() => expect(queryOf(searches(calls).at(-1) as Call).get("q")).toBe("tag:medical tag:tax"));
  });

  it("+ Tag skips the tags already chosen, takes Enter on the first suggestion and Escape closes", async () => {
    const { user } = setup("/browse?q=tag%3Amedical");
    await screen.findByRole("list", { name: "Search results" });
    await user.click(screen.getByRole("button", { name: "+ Tag" }));
    await user.type(screen.getByRole("textbox", { name: "Tag to add" }), "med");
    const list = await screen.findByRole("listbox", { name: "Matching tags" });
    expect(within(list).getAllByRole("option").map((o) => o.textContent)).toEqual(["Medicine1"]);
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("textbox", { name: "Tag to add" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "+ Tag" }));
    await user.type(screen.getByRole("textbox", { name: "Tag to add" }), "med");
    await screen.findByRole("listbox", { name: "Matching tags" });
    await user.keyboard("{Enter}");
    expect(where()).toBe("/browse?q=tag%3Amedical+tag%3AMedicine");
  });

  it("tag:name typed in the box lands in the row and leaves the box", async () => {
    const { user } = setup("/browse?q=pdf");
    await screen.findByRole("list", { name: "Search results" });
    await user.type(screen.getByRole("searchbox", { name: "Search" }), " tag:medical ");
    expect(where()).toBe("/browse?q=pdf+tag%3Amedical");
    const chips = await screen.findByRole("list", { name: "Search filters" });
    expect(chips.closest(".tag-bar")).not.toBeNull();
    expect((screen.getByRole("searchbox", { name: "Search" }) as HTMLInputElement).value.trim()).toBe("pdf"); // only the words
  });
});

describe("All / Any", () => {
  it("is offered with two or more tags, All by default, and not with one", async () => {
    const { calls } = setup("/browse?q=tag%3Amedical+tag%3Atax");
    await screen.findByRole("list", { name: "Search results" });
    const mode = screen.getByRole("group", { name: "Match tags" });
    expect(within(mode).getByRole("button", { name: "All" })).toHaveAttribute("aria-pressed", "true");
    expect(within(mode).getByRole("button", { name: "Any" })).toHaveAttribute("aria-pressed", "false");
    expect(queryOf(searches(calls)[0]).has("tag_mode")).toBe(false);
  });

  it("not with a single tag", async () => {
    setup("/browse?q=tag%3Amedical");
    await screen.findByRole("list", { name: "Search results" });
    expect(screen.queryByRole("group", { name: "Match tags" })).not.toBeInTheDocument();
  });

  it("Any puts tag_mode=any in the address and the search; All takes it out again", async () => {
    const { calls, user } = setup("/browse?q=tag%3Amedical+tag%3Atax");
    await screen.findByRole("list", { name: "Search results" });
    const mode = screen.getByRole("group", { name: "Match tags" });
    await user.click(within(mode).getByRole("button", { name: "Any" }));
    expect(where()).toBe("/browse?q=tag%3Amedical+tag%3Atax&tag_mode=any");
    await waitFor(() => expect(queryOf(searches(calls).at(-1) as Call).get("tag_mode")).toBe("any"));
    await user.click(within(mode).getByRole("button", { name: "All" }));
    expect(where()).toBe("/browse?q=tag%3Amedical+tag%3Atax");
    await waitFor(() => expect(queryOf(searches(calls).at(-1) as Call).has("tag_mode")).toBe(false));
  });

  it("the address sets Any; dropping to one tag drops the parameter", async () => {
    const { user } = setup("/browse?q=tag%3Amedical+tag%3Atax&tag_mode=any");
    await screen.findByRole("list", { name: "Search results" });
    expect(within(screen.getByRole("group", { name: "Match tags" })).getByRole("button", { name: "Any" })).toHaveAttribute("aria-pressed", "true");
    await user.click(screen.getByRole("button", { name: "Remove filter tag:tax" }));
    expect(where()).toBe("/browse?q=tag%3Amedical");
  });
});
