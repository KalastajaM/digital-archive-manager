import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { describe, expect, it } from "vitest";
import type { Collection, CollectionChange, CollectionRow, Group, MemberAttention, ResolvedOp } from "../api/client";
import { type Call, dataTransfer, deferred, IMPORTANT_REFUSED, mockFetch, quarantineRoute, renderWithProviders, undoButton } from "../test-utils";
import { prepared, STATUS_ON } from "../components/ai/testData";
import Collections from "./Collections";
import { UNGROUPED, visibleMembers } from "../components/GroupTree";

const DAY = "2026-10-19";
const ONG = "##. Ongoing";

const SAUNA: Collection = {
  id: 7,
  name: "Sauna",
  state: "open",
  created: 1_760_000_000,
  closed_at: null,
  publish: { ongoing: true },
  ongoing_rel: `${ONG}/Sauna`,
  members: [
    { drive_id: "f1", path: "40. House/Sauna/quote.pdf", is_dir: false, missing: false, quarantined: false, is_link: false, group_id: null, marks: [] },
    { drive_id: "d1", path: "40. House/Sauna/Plans", is_dir: true, missing: false, quarantined: false, is_link: false, group_id: null, marks: [] },
    { drive_id: "f2", path: "10. Financial/Banks/old‮.pdf", is_dir: false, missing: true, quarantined: false, is_link: false, group_id: null, marks: [] },
    { drive_id: "f3", path: "##. To Delete/x.pdf", is_dir: false, missing: false, quarantined: true, is_link: false, group_id: null, marks: [] },
  ],
  ongoing_status: null,
  summary: "",
  groups: [],
  parent_id: null,
  path: ["Sauna"],
  kind: null,
};
const row = (c: Collection, files: number, open_checks: number): CollectionRow => ({ ...c, files, open_checks });
const CLOSED: Collection = { ...SAUNA, id: 8, name: "Old car", path: ["Old car"], state: "closed", closed_at: 1_760_500_000, ongoing_rel: null };

const CLOSE_PLAN: ResolvedOp[] = [
  { kind: "unlink_symlink", src: null, dst: `${ONG}/Sauna/quote.pdf`, drive_id: null, note: null },
  { kind: "remove_empty_dir", src: null, dst: `${ONG}/Sauna`, drive_id: null, note: null },
];
const batch = (done: ResolvedOp[]) => ({
  batch_id: "b1",
  dry_run: false,
  done,
  failed: null,
  error: null,
  index_error: null,
});
const changeOf = (c: Collection, overrides: Partial<CollectionChange> = {}): CollectionChange => ({
  collection: c,
  batch: null,
  problems: [],
  ongoing_status: c.ongoing_status,
  ...overrides,
});

function Where() {
  const location = useLocation();
  return <output data-testid="where">{location.pathname + location.search}</output>;
}

type Routes = Parameters<typeof mockFetch>[0];

function renderCollections(path = "/collections", routes: Routes = {}) {
  const calls = mockFetch({
    "GET /api/collections": (call) => ({
      body: call.url.includes("state=closed")
        ? [row(CLOSED, 1, 0)]
        : [row({ ...SAUNA, name: "Sauna‮x", ongoing_status: "not managed: a user file" }, 3, 2)],
    }),
    "GET /api/collections/7": { body: SAUNA },
    "GET /api/collections/8": { body: CLOSED },
    "GET /api/notes/collection/7": { body: { text: "" } },
    "GET /api/checklist/collection/7": { body: [] },
    "GET /api/notes/collection/8": { body: { text: "" } },
    "GET /api/checklist/collection/8": { body: [] },
    // the selected file's panel (as in Browse): its summary and note
    ...Object.fromEntries(
      ["f1", "f2", "f3", "d1"].flatMap((id) => [
        [`GET /api/files/${id}/summary`, { body: { ai: null, user: null } }],
        [`GET /api/notes/file/${id}`, { body: { text: "" } }],
      ]),
    ),
    ...routes,
  });
  const user = userEvent.setup();
  const { client } = renderWithProviders(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/collections/:id?" element={<Collections today={DAY} />} />
      </Routes>
      <Where />
    </MemoryRouter>,
  );
  return { calls, user, client };
}

const posts = (calls: Call[], url: string) => calls.filter((c) => c.method === "POST" && c.url === url);
const patches = (calls: Call[], url: string) => calls.filter((c) => c.method === "PATCH" && c.url === url);
const where = () => screen.getByTestId("where").textContent;
const panel = () => screen.getByRole("region", { name: "Collection" });
const tree = () => within(panel()).getByRole("region", { name: "Members" });

/** Open the ⋯ menu of the toolbar and pick ``item``. */
async function fromMenu(user: ReturnType<typeof userEvent.setup>, item: string | RegExp) {
  await user.click(await within(panel()).findByRole("button", { name: "More actions" }));
  const menu = await screen.findByRole("menu", { name: "More actions" });
  const entry = within(menu).queryByRole("menuitem", { name: item }) ?? within(menu).getByRole("menuitemcheckbox", { name: item });
  await user.click(entry);
}

const QUOTES: Group = { id: 1, collection_id: 7, parent_id: null, name: "Quotes", position: 0, summary: "Two offers‮" };
const OLD: Group = { id: 2, collection_id: 7, parent_id: 1, name: "Old", position: 0, summary: "" };
const PLANS: Group = { id: 3, collection_id: 7, parent_id: null, name: "Plans", position: 1, summary: "" };
const GROUPED: Collection = {
  ...SAUNA,
  summary: "The sauna build",
  groups: [QUOTES, PLANS, OLD],
  members: SAUNA.members.map((m) => (m.drive_id === "f1" ? { ...m, group_id: 1 } : m.drive_id === "d1" ? { ...m, group_id: 2 } : m)),
};

describe("Collections list", () => {
  it("lists the open collections with file count, open checks and the Ongoing status", async () => {
    const { calls, user } = renderCollections();
    const r = await screen.findByRole("article", { name: "Sauna⟨U+202E⟩x" });
    expect(within(r).getByRole("link", { name: "Sauna⟨U+202E⟩x" })).toHaveAttribute("href", "/collections/7");
    expect(r).toHaveTextContent("3 files · 2 open checks");
    expect(within(r).getByText("Not managed: a user file")).toHaveClass("tag-orange");
    expect(calls.find((c) => c.url.startsWith("/api/collections?"))!.url).toBe("/api/collections?state=open");

    await user.click(screen.getByRole("button", { name: "Closed" }));
    expect(where()).toBe("/collections?state=closed");
    const old = await screen.findByRole("article", { name: "Old car" });
    expect(old).toHaveTextContent("1 file");
    expect(within(old).getByRole("link")).toHaveAttribute("href", "/collections/8?state=closed");
    expect(screen.getByRole("button", { name: "Closed" })).toHaveAttribute("aria-pressed", "true");
  });

  it("New collection creates it and opens it", async () => {
    const { calls, user } = renderCollections("/collections", {
      "POST /api/collections": { body: { ...SAUNA, id: 7, members: [] } },
    });
    await user.type(await screen.findByRole("textbox", { name: "New collection" }), "  Sauna {Enter}");
    await waitFor(() => expect(where()).toBe("/collections/7"));
    expect(posts(calls, "/api/collections").map((c) => c.body)).toEqual([{ name: "Sauna" }]);
    expect(await within(panel()).findByRole("heading", { name: "Sauna" })).toBeInTheDocument();
  });

  it("a double Create makes one collection", async () => {
    const created = deferred<{ body: unknown }>();
    const { calls, user } = renderCollections("/collections", { "POST /api/collections": () => created.promise });
    await user.type(await screen.findByRole("textbox", { name: "New collection" }), "Car");
    const create = screen.getByRole("button", { name: "Create" });
    act(() => {
      create.click();
      create.click();
    });
    await act(async () => created.resolve({ body: { ...SAUNA, id: 7 } }));
    expect(posts(calls, "/api/collections")).toHaveLength(1);
  });

  it("shows a refused name inline", async () => {
    const { user } = renderCollections("/collections", {
      "POST /api/collections": { status: 400, body: { error: "a collection named ‮Sauna exists" } },
    });
    await user.type(await screen.findByRole("textbox", { name: "New collection" }), "sauna");
    await user.click(screen.getByRole("button", { name: "Create" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("⟨U+202E⟩Sauna exists");
  });
});

describe("Collection detail", () => {
  it("lists the members as a plain list (no Ungrouped without groups) with their folder, marks folders, missing and quarantined ones, and removes one", async () => {
    const { calls, user } = renderCollections("/collections/7", {
      "POST /api/collections/7/members/remove": {
        body: changeOf({ ...SAUNA, members: SAUNA.members.slice(1) }, { problems: ["plan refused: x"] }),
      },
    });
    const members = await within(panel()).findByRole("region", { name: "Members" });
    expect(within(members).queryByRole("region", { name: "Ungrouped" })).toBeNull();
    expect(within(members).queryByText("Ungrouped")).toBeNull();
    expect(within(members).getAllByRole("listitem")).toHaveLength(4);
    const quote = within(members).getByText("quote.pdf").closest("li")!;
    expect(quote).toHaveTextContent("40. House/Sauna");
    const plans = within(members).getByText("Plans").closest("li")!;
    expect(within(plans).getByText("folder")).toBeInTheDocument();
    const gone = within(members).getByText("old⟨U+202E⟩.pdf").closest("li")!;
    expect(gone).toHaveClass("member-gone");
    expect(within(gone).getByText("file missing")).toBeInTheDocument();
    const quarantined = within(members).getByText("x.pdf").closest("li")!;
    expect(within(quarantined).getByText("in ##. To Delete")).toBeInTheDocument();
    expect(quote).toHaveAttribute("data-quicklook");
    expect(quote).toHaveAttribute("aria-current", "true"); // the first member is selected

    const inspector = within(panel()).getByRole("complementary", { name: "Selected file" });
    // no groups: nothing to choose, so no Group select (and no "Ungrouped" in it)
    expect(within(inspector).queryByRole("combobox", { name: "Group" })).toBeNull();
    await user.click(within(inspector).getByRole("button", { name: "Remove quote.pdf from the collection" }));
    await waitFor(() => expect(posts(calls, "/api/collections/7/members/remove")).toHaveLength(1));
    expect(posts(calls, "/api/collections/7/members/remove")[0].body).toEqual({ drive_id: "f1" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument(); // no confirm
    expect(await within(panel()).findByText("plan refused: x")).toBeInTheDocument();
  });

  it("the inspector is Browse's file panel (rename, preview, tags, Put in tray, Add to collection, summary, note) plus the collection's own", async () => {
    renderCollections("/collections/7");
    await within(panel()).findByRole("region", { name: "Members" });
    const inspector = within(panel()).getByRole("complementary", { name: "Selected file" });
    expect(within(inspector).getByRole("heading", { level: 2, name: "quote.pdf" })).toBeInTheDocument();
    for (const name of [/^Rename/, "Move file to…", "Put in tray", "Add to collection…", "Quick Look", "Move to To Delete"]) {
      expect(within(inspector).getByRole("button", { name })).toBeInTheDocument();
    }
    expect(within(inspector).getByRole("region", { name: "Tags" })).toBeInTheDocument();
    expect(within(inspector).getByRole("textbox", { name: "Note on this file" })).toBeInTheDocument();
    // the app's one order in the preview's toolbar: view (Quick Look), ★ / !, Ask AI, the bin last
    const order = ["Quick Look", "Star", "Ask AI", "Move to To Delete"].map((name) => within(inspector).getByRole("button", { name }));
    for (let i = 1; i < order.length; i++) {
      expect(order[i - 1].compareDocumentPosition(order[i]) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    }
    const own = within(inspector).getByRole("region", { name: "In this collection" });
    expect(within(own).getByRole("button", { name: "Remove quote.pdf from the collection" })).toBeInTheDocument();
  });

  it("Quick Look is an icon button with a tooltip; the members scroll in their own box; no Ask AI by the name", async () => {
    renderCollections("/collections/7");
    const members = await within(panel()).findByRole("region", { name: "Members" });
    expect(members.closest(".collection-members")).not.toBeNull();
    const inspector = within(panel()).getByRole("complementary", { name: "Selected file" });
    expect(within(inspector).getByRole("button", { name: "Quick Look" })).toHaveAttribute("data-tip", "Quick Look Space");
    // Ask AI is in the preview's toolbar, as in Browse (not by the name)
    expect(await within(inspector).findByRole("button", { name: "Ask AI" })).toHaveAttribute("data-tip", expect.stringContaining("Ask AI to suggest"));
    expect(inspector.querySelector(".file-meta-title")!.querySelector("[aria-label='Ask AI']")).toBeNull();
  });

  it("the file panel of a member has the Draw a box tool, as in Browse", async () => {
    renderCollections("/collections/7");
    const inspector = await within(panel()).findByRole("complementary", { name: "Selected file" });
    expect(await within(inspector).findByRole("button", { name: "Draw a box" })).toBeInTheDocument();
  });

  it("a collection with files but no groups hints at New group, which does what the toolbar icon does", async () => {
    const created: Group = { id: 9, collection_id: 7, parent_id: null, name: "New group", position: 0, summary: "" };
    let now = SAUNA;
    const { calls, user } = renderCollections("/collections/7", {
      "GET /api/collections/7": () => ({ body: now }),
      "POST /api/collections/7/groups": () => {
        now = { ...SAUNA, groups: [created] };
        return { body: changeOf(now) };
      },
    });
    const hint = await within(panel()).findByText(/^Group files:/);
    await user.click(within(hint.closest("p")!).getByRole("button", { name: "New group" }));
    await waitFor(() => expect(posts(calls, "/api/collections/7/groups")).toHaveLength(1));
    await waitFor(() => expect(within(panel()).queryByText(/^Group files:/)).not.toBeInTheDocument());
  });

  it("the toolbar's New group icon says what groups are for", async () => {
    renderCollections("/collections/7");
    await within(panel()).findByRole("region", { name: "Members" });
    const icon = within(panel().querySelector(".toolbar-actions") as HTMLElement).getByRole("button", { name: "New group" });
    expect(icon).toHaveAttribute("data-tip", "New group: sort files into groups");
  });

  it("the inspector has a resizable splitter", async () => {
    renderCollections("/collections/7");
    await within(panel()).findByRole("region", { name: "Members" });
    expect(screen.getByRole("separator", { name: "Resize the inspector" })).toHaveAttribute("aria-valuenow", "380");
  });

  it("the selected file has Rename and Move to… inline; a folder member has them disabled", async () => {
    const { user } = renderCollections("/collections/7");
    await within(panel()).findByRole("region", { name: "Members" });
    const inspector = within(panel()).getByRole("complementary", { name: "Selected file" });
    expect(within(inspector).queryByRole("button", { name: "Edit details…" })).not.toBeInTheDocument();
    expect(within(inspector).getByRole("heading", { name: "quote.pdf" })).toBeInTheDocument();
    expect(within(inspector).getByRole("button", { name: /^Rename/ })).toBeEnabled();
    expect(within(inspector).getByRole("button", { name: "Move file to…" })).toBeEnabled();
    await user.click(within(tree()).getByText("Plans"));
    expect(within(inspector).getByRole("button", { name: /^Rename/ })).toBeDisabled();
    expect(within(inspector).getByRole("button", { name: "Move file to…" })).toBeDisabled();
    await user.keyboard("k");
    await user.click(within(inspector).getByRole("button", { name: /^Rename/ }));
    expect(await within(inspector).findByRole("textbox", { name: "File name" })).toHaveValue("quote");
  });

  it("the subtitle counts files and folders apart", async () => {
    renderCollections("/collections/7");
    await within(panel()).findByRole("region", { name: "Members" });
    const subtitle = panel().querySelector(".toolbar-subtitle")!;
    // one counting rule on every screen: the folders, then every usable file (the list's count)
    expect(subtitle).toHaveTextContent(/^Open · 1 folder · 3 files$/);
  });

  it("without groups a folded Ungrouped (kept from before) hides nobody from j/k", () => {
    expect(visibleMembers(SAUNA, new Set([UNGROUPED])).map((m) => m.drive_id)).toEqual(["f1", "d1", "f2", "f3"]);
    expect(visibleMembers(GROUPED, new Set([UNGROUPED])).map((m) => m.drive_id)).toEqual(["d1", "f1"]);
  });

  it("a collection of one folder says 1 folder and the files in it, as the list does", async () => {
    const one: Collection = { ...SAUNA, members: [SAUNA.members[1]] };
    renderCollections("/collections/7", {
      "GET /api/collections/7": { body: one },
      "GET /api/collections": { body: [row(one, 23, 0)] },
    });
    const members = await within(panel()).findByRole("region", { name: "Members" });
    await waitFor(() => expect(panel().querySelector(".toolbar-subtitle")).toHaveTextContent(/^Open · 1 folder · 23 files$/));
    expect(within(members).queryByText("Ungrouped")).toBeNull();
    expect(within(members).getByText("Plans")).toBeInTheDocument();
  });

  it("selecting a member shows it in the side panel; j/k move the selection", async () => {
    const { user } = renderCollections("/collections/7");
    await within(panel()).findByRole("region", { name: "Members" });
    await user.click(within(tree()).getByText("Plans"));
    const inspector = within(panel()).getByRole("complementary", { name: "Selected file" });
    expect(inspector.querySelector(".current-path")).toHaveTextContent("40. House/Sauna/Plans"); // the path row
    expect(within(inspector).getByRole("button", { name: "Remove Plans from the collection" })).toBeInTheDocument();
    await user.keyboard("k");
    expect(within(inspector).getByRole("button", { name: "Remove quote.pdf from the collection" })).toBeInTheDocument();
  });

  it("close shows the plan from the preview endpoint, applies it, and shows what the apply did", async () => {
    const applied: ResolvedOp[] = [CLOSE_PLAN[0]]; // the apply re-plans: it may differ
    const { calls, user } = renderCollections("/collections/7", {
      "POST /api/collections/7/close/preview": { body: CLOSE_PLAN },
      "POST /api/collections/7/close": {
        body: changeOf(
          { ...SAUNA, state: "closed", ongoing_status: "not managed: mine.txt is not ours" },
          {
            batch: batch(applied),
            problems: ["stopped‮ early"],
            ongoing_status: "not managed: mine.txt is not ours",
          },
        ),
      },
    });
    await fromMenu(user, "Close collection…");
    const dialog = await screen.findByRole("dialog", { name: "Close Sauna?" });
    expect(within(dialog).getAllByRole("listitem").map((li) => li.textContent)).toEqual([
      `Remove link${ONG}/Sauna/quote.pdf`,
      `Remove empty folder${ONG}/Sauna`,
    ]);
    expect(posts(calls, "/api/collections/7/close/preview").map((c) => c.body)).toEqual([{}]);
    expect(posts(calls, "/api/collections/7/close")).toHaveLength(0); // only the preview so far
    await user.click(within(dialog).getByRole("button", { name: "Close" }));
    await waitFor(() => expect(posts(calls, "/api/collections/7/close")).toHaveLength(1));
    expect(posts(calls, "/api/collections/7/close")[0].body).toEqual({}); // apply takes no body
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    const result = await within(panel()).findByRole("region", { name: "What changed in ##. Ongoing" });
    expect(result.querySelectorAll(".plan-op")).toHaveLength(1);
    expect(result).toHaveTextContent(`${ONG}/Sauna/quote.pdf`);
    expect(result).toHaveTextContent("stopped⟨U+202E⟩ early");
    expect(result).toHaveTextContent("not managed: mine.txt is not ours");
  });

  it("Cancel in the confirm applies nothing", async () => {
    const { calls, user } = renderCollections("/collections/7", {
      "POST /api/collections/7/close/preview": { body: CLOSE_PLAN },
    });
    await fromMenu(user, "Close collection…");
    await user.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(posts(calls, "/api/collections/7/close")).toHaveLength(0);
  });

  it("reopen of a closed collection previews and applies", async () => {
    const { calls, user } = renderCollections("/collections/8?state=closed", {
      "POST /api/collections/8/reopen/preview": { body: [] },
      "POST /api/collections/8/reopen": { body: changeOf({ ...CLOSED, state: "open" }) },
    });
    expect(await within(panel()).findByText(/Closed/)).toBeInTheDocument();
    await fromMenu(user, "Reopen collection…");
    const dialog = await screen.findByRole("dialog", { name: "Reopen Old car?" });
    expect(dialog).toHaveTextContent("No file changes.");
    await user.click(within(dialog).getByRole("button", { name: "Reopen" }));
    await waitFor(() => expect(posts(calls, "/api/collections/8/reopen")).toHaveLength(1));
    expect(posts(calls, "/api/collections/8/reopen/preview")[0].body).toEqual({});
    expect(posts(calls, "/api/collections/8/reopen")[0].body).toEqual({}); // apply takes no body
  });

  it("rename previews; with no ops it applies at once, with ops it confirms first", async () => {
    const { calls, user } = renderCollections("/collections/7", {
      "POST /api/collections/7/rename/preview": (call) => ({
        body:
          (call.body as { name: string }).name === "Spa"
            ? [{ kind: "rename", src: `${ONG}/Sauna`, dst: `${ONG}/Spa`, drive_id: null, note: null }]
            : [],
      }),
      "PATCH /api/collections/7": (call) => ({
        body: changeOf({ ...SAUNA, name: (call.body as { name: string }).name }),
      }),
    });
    // the name itself is the click target (no pencil); Enter and Space on it work too
    const nameButton = () => within(panel()).getByRole("button", { name: "Rename Sauna" });
    await within(panel()).findByRole("button", { name: "Rename Sauna" });
    expect(nameButton()).toHaveAttribute("title", "Click to rename");
    expect(within(panel()).queryByRole("button", { name: "Edit name" })).not.toBeInTheDocument();
    for (const key of ["{Enter}", " "]) {
      nameButton().focus();
      await user.keyboard(key);
      await user.type(within(panel()).getByRole("textbox", { name: "Collection name" }), "{Escape}");
      expect(within(panel()).queryByRole("textbox", { name: "Collection name" })).not.toBeInTheDocument();
    }
    await user.click(nameButton());
    const input = within(panel()).getByRole("textbox", { name: "Collection name" });
    await user.clear(input);
    await user.type(input, "Quiet{Enter}");
    await waitFor(() => expect(calls.filter((c) => c.method === "PATCH")).toHaveLength(1));
    expect(posts(calls, "/api/collections/7/rename/preview").map((c) => c.body)).toEqual([{ name: "Quiet" }]);
    expect(calls.filter((c) => c.method === "PATCH")[0].body).toEqual({ name: "Quiet" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

    await fromMenu(user, "Rename");
    const again = within(panel()).getByRole("textbox", { name: "Collection name" });
    await user.clear(again);
    await user.type(again, "Spa{Enter}");
    const dialog = await screen.findByRole("dialog", { name: "Rename Sauna to Spa?" });
    expect(dialog).toHaveTextContent(`${ONG}/Sauna → ${ONG}/Spa`);
    expect(calls.filter((c) => c.method === "PATCH")).toHaveLength(1);
    await user.click(within(dialog).getByRole("button", { name: "Rename" }));
    await waitFor(() => expect(calls.filter((c) => c.method === "PATCH")).toHaveLength(2));
    expect(calls.filter((c) => c.method === "PATCH")[1].body).toEqual({ name: "Spa" });
    expect(posts(calls, "/api/collections/7/rename/preview").at(-1)!.body).toEqual({ name: "Spa" });
  });

  it("the rename field opens with the whole name selected", async () => {
    const { user } = renderCollections("/collections/7");
    await fromMenu(user, "Rename");
    const input = within(panel()).getByRole("textbox", { name: "Collection name" }) as HTMLInputElement;
    expect(input.selectionStart).toBe(0);
    expect(input.selectionEnd).toBe("Sauna".length);
  });

  it("a rename's toast has Undo, which renames back through the same preview; the result can be dismissed", async () => {
    const { calls, user } = renderCollections("/collections/7", {
      "POST /api/collections/7/rename/preview": { body: [] },
      "PATCH /api/collections/7": (call) => ({ body: changeOf({ ...SAUNA, name: (call.body as { name: string }).name }) }),
    });
    await fromMenu(user, "Rename");
    const input = within(panel()).getByRole("textbox", { name: "Collection name" });
    await user.clear(input);
    await user.type(input, "Quiet{Enter}");
    const toast = await screen.findByText("Renamed to Quiet");
    const undo = within(toast.closest(".toast") as HTMLElement).getByRole("button", { name: "Undo" });
    // the result of the rename stays until it is dismissed
    const result = await within(panel()).findByRole("region", { name: "What changed in ##. Ongoing" });
    await user.click(within(result).getByRole("button", { name: "Dismiss" }));
    expect(within(panel()).queryByRole("region", { name: "What changed in ##. Ongoing" })).toBeNull();
    await user.click(undo);
    await waitFor(() => expect(calls.filter((c) => c.method === "PATCH")).toHaveLength(2));
    expect(posts(calls, "/api/collections/7/rename/preview").map((c) => c.body)).toEqual([{ name: "Quiet" }, { name: "Sauna" }]);
    expect(calls.filter((c) => c.method === "PATCH")[1].body).toEqual({ name: "Sauna" });
    expect(await screen.findByText("Renamed back to Sauna")).toBeInTheDocument();
  });

  it("shows a stored Ongoing status as a sentence, starting with a capital", async () => {
    renderCollections("/collections/7", {
      "GET /api/collections/7": { body: { ...SAUNA, ongoing_status: "not managed: a user file" } },
    });
    const banner = await within(panel()).findByRole("region", { name: "Not managed: a user file" });
    expect(banner).toHaveTextContent(/^Not managed: a user file$/);
  });

  it("a refused rename apply (name taken) is shown inline and the form stays", async () => {
    const { user } = renderCollections("/collections/7", {
      "POST /api/collections/7/rename/preview": { body: [] },
      "PATCH /api/collections/7": { status: 400, body: { error: "a collection named ‮Spa exists" } },
    });
    await fromMenu(user, "Rename");
    const input = within(panel()).getByRole("textbox", { name: "Collection name" });
    await user.clear(input);
    await user.type(input, "Spa{Enter}");
    expect(await within(panel()).findByRole("alert")).toHaveTextContent("⟨U+202E⟩Spa exists");
    expect(within(panel()).getByRole("textbox", { name: "Collection name" })).toHaveValue("Spa");
    // Esc gives up: the name stays as it was
    await user.type(within(panel()).getByRole("textbox", { name: "Collection name" }), "{Escape}");
    expect(within(panel()).getByRole("heading", { name: "Sauna" })).toBeInTheDocument();
  });

  it("the publish toggle previews, confirms and applies with the same body", async () => {
    const off = { publisher: "ongoing", on: false };
    const { calls, user } = renderCollections("/collections/7", {
      "POST /api/collections/7/publish/preview": { body: CLOSE_PLAN },
      "POST /api/collections/7/publish": {
        body: changeOf({ ...SAUNA, publish: { ongoing: false }, ongoing_rel: null }, { batch: batch(CLOSE_PLAN) }),
      },
    });
    await user.click((await within(panel()).findAllByRole("button", { name: "Show in Finder" }))[0]); // the toolbar's
    expect(await within(panel()).findByText(`${ONG}/Sauna`)).toBeInTheDocument(); // the Finder hint
    await user.click(within(panel()).getByRole("button", { name: "More actions" }));
    const toggle = within(screen.getByRole("menu")).getByRole("menuitemcheckbox", { name: "Show in ##. Ongoing" });
    expect(toggle).toHaveAttribute("aria-checked", "true");
    await user.click(toggle);
    const dialog = await screen.findByRole("dialog", { name: "Remove Sauna from ##. Ongoing?" });
    expect(posts(calls, "/api/collections/7/publish/preview")[0].body).toEqual(off);
    await user.click(within(dialog).getByRole("button", { name: "Remove" }));
    await waitFor(() => expect(posts(calls, "/api/collections/7/publish")).toHaveLength(1));
    expect(posts(calls, "/api/collections/7/publish")[0].body).toEqual(off);
  });

  it("export: a large one asks first, then the download link uses the token; not included listed", async () => {
    const slow = deferred<{ body: unknown }>();
    const { calls, user } = renderCollections("/collections/7", {
      "POST /api/collections/7/export": (call) =>
        (call.body as { confirm_large: boolean }).confirm_large
          ? slow.promise
          : { body: { token: null, size: 312 * 1024 * 1024, needs_confirm: true, not_included: [] } },
    });
    await user.click(await within(panel()).findByRole("button", { name: "Export…" }));
    const exportBox = within(await screen.findByRole("dialog", { name: "Export Sauna" })).getByRole("region", { name: "Export" });
    await user.click(within(exportBox).getByRole("radio", { name: "One combined PDF" }));
    await user.click(within(exportBox).getByRole("button", { name: "Export" }));
    expect(await within(exportBox).findByText(/about 312 MB/)).toBeInTheDocument();
    expect(within(exportBox).queryByRole("link")).not.toBeInTheDocument();
    await user.click(within(exportBox).getByRole("button", { name: "Export anyway" }));
    expect(await within(exportBox).findByText(/Building the export/)).toBeInTheDocument();
    slow.resolve({
      body: {
        token: "tok/1",
        size: 300 * 1024 * 1024,
        needs_confirm: false,
        not_included: [{ path: "a/b‮.pdf", reason: "not downloaded — open it once in Finder" }],
      },
    });
    const link = await within(exportBox).findByRole("link", { name: "Download the PDF" });
    expect(link).toHaveAttribute("href", "/api/exports/tok%2F1");
    expect(link).toHaveAttribute("download");
    expect(exportBox).toHaveTextContent("(300 MB)");
    const skipped = within(exportBox).getByRole("list", { name: "Not included" });
    expect(skipped).toHaveTextContent("a/b⟨U+202E⟩.pdf — not downloaded — open it once in Finder");
    expect(posts(calls, "/api/collections/7/export").map((c) => c.body)).toEqual([
      { format: "pdf", confirm_large: false },
      { format: "pdf", confirm_large: true },
    ]);
  });

  it("export of a small zip gives the link at once", async () => {
    const { user } = renderCollections("/collections/7", {
      "POST /api/collections/7/export": {
        body: { token: "t2", size: 2048, needs_confirm: false, not_included: [] },
      },
    });
    await user.click(await within(panel()).findByRole("button", { name: "Export…" }));
    const exportBox = within(await screen.findByRole("dialog", { name: "Export Sauna" })).getByRole("region", { name: "Export" });
    await user.click(within(exportBox).getByRole("button", { name: "Export" }));
    expect(await within(exportBox).findByRole("link", { name: "Download the zip" })).toHaveAttribute(
      "href",
      "/api/exports/t2",
    );
    expect(exportBox).toHaveTextContent("(2,0 KB)");
  });

  it("saves the collection note on blur and has a checklist", async () => {
    const { calls, user } = renderCollections("/collections/7", {
      "PUT /api/notes/collection/7": { body: { text: "call Marco" } },
    });
    const note = await within(panel()).findByRole("textbox", { name: "Note" });
    await user.type(note, "call Marco");
    await user.tab();
    await waitFor(() => expect(calls.filter((c) => c.method === "PUT")).toHaveLength(1));
    expect(calls.find((c) => c.method === "PUT")!.body).toEqual({ text: "call Marco" });
    expect(within(panel()).getByRole("heading", { name: "Checklist" })).toBeInTheDocument();
  });

  it("double activations send one request each: remove member, export, export anyway", async () => {
    const removed = deferred<{ body: unknown }>();
    const built = deferred<{ body: unknown }>();
    const { calls, user } = renderCollections("/collections/7", {
      "POST /api/collections/7/members/remove": () => removed.promise,
      "POST /api/collections/7/export": (call) =>
        (call.body as { confirm_large: boolean }).confirm_large
          ? built.promise
          : { body: { token: null, size: 300 * 1024 * 1024, needs_confirm: true, not_included: [] } },
    });
    const remove = await within(panel()).findByRole("button", { name: "Remove quote.pdf from the collection" });
    act(() => {
      remove.click();
      remove.click();
    });
    await user.click(within(panel()).getByRole("button", { name: "Export…" }));
    const exportBox = within(await screen.findByRole("dialog", { name: "Export Sauna" })).getByRole("region", { name: "Export" });
    const exportButton = within(exportBox).getByRole("button", { name: "Export" });
    act(() => {
      exportButton.click();
      exportButton.click();
    });
    const anyway = await within(exportBox).findByRole("button", { name: "Export anyway" });
    act(() => {
      anyway.click();
      anyway.click();
    });
    await waitFor(() => expect(posts(calls, "/api/collections/7/export")).toHaveLength(2));
    expect(posts(calls, "/api/collections/7/members/remove")).toHaveLength(1);
    expect(posts(calls, "/api/collections/7/export").map((c) => c.body)).toEqual([
      { format: "zip", confirm_large: false },
      { format: "zip", confirm_large: true },
    ]);
    await act(async () => {
      removed.resolve({ body: changeOf(SAUNA) });
      built.resolve({ body: { token: "t", size: 1, needs_confirm: false, not_included: [] } });
    });
    expect(await within(exportBox).findByRole("link", { name: "Download the zip" })).toBeInTheDocument();
  });
});

describe("Collection groups, summary and attention", () => {
  const grouped = (routes: Routes = {}) =>
    renderCollections("/collections/7", { "GET /api/collections/7": { body: GROUPED }, ...routes });

  it("hides an empty Ungrouped, and shows it as a drop target only while files are dragged", async () => {
    const allGrouped: Collection = { ...GROUPED, members: GROUPED.members.map((m) => ({ ...m, group_id: m.group_id ?? 1 })) };
    renderCollections("/collections/7", { "GET /api/collections/7": { body: allGrouped } });
    await within(panel()).findByRole("region", { name: "Quotes" });
    expect(within(tree()).queryByRole("region", { name: "Ungrouped" })).toBeNull();
    const drag = new Event("dragstart", { bubbles: true }) as DragEvent;
    Object.defineProperty(drag, "dataTransfer", { value: { types: ["application/x-dam-files"] } });
    act(() => void document.dispatchEvent(drag));
    const target = await within(tree()).findByRole("region", { name: "Ungrouped" });
    expect(target).toHaveTextContent("Drop here to take files out of their group.");
    act(() => void document.dispatchEvent(new Event("dragend")));
    await waitFor(() => expect(within(tree()).queryByRole("region", { name: "Ungrouped" })).toBeNull());
  });

  it("shows the groups as a tree with their file counts and summaries, and Ungrouped last", async () => {
    const { user } = grouped();
    const quotes = await within(panel()).findByRole("region", { name: "Quotes" });
    expect(within(quotes).getByText("Two offers⟨U+202E⟩")).toBeInTheDocument();
    // its own file and its subgroup's folder
    expect(quotes.querySelector(".group-count")).toHaveTextContent(/^1 file, 1 folder$/);
    const old = within(quotes).getByRole("region", { name: "Old" });
    expect(old.querySelector(".group-count")).toHaveTextContent(/^1 folder$/);
    expect(within(old).getByText("Plans")).toBeInTheDocument();
    const regions = within(tree()).getAllByRole("region").map((r) => r.getAttribute("aria-label"));
    expect(regions).toEqual(["Quotes", "Old", "Plans", "Ungrouped"]);
    expect(within(tree()).getByRole("region", { name: "Ungrouped" }).querySelector(".group-count")).toHaveTextContent(/^2 files$/);
    // folding hides the files
    await user.click(within(quotes).getByRole("button", { name: "Quotes", expanded: true }));
    expect(within(quotes).queryByText("quote.pdf")).not.toBeInTheDocument();
  });

  it("+ Group creates a group and puts its name in rename at once", async () => {
    const created: Group = { id: 9, collection_id: 7, parent_id: null, name: "New group", position: 2, summary: "" };
    let now = GROUPED;
    const { calls, user } = grouped({
      "GET /api/collections/7": () => ({ body: now }),
      "POST /api/collections/7/groups": () => {
        now = { ...GROUPED, groups: [...GROUPED.groups, created] };
        return { body: changeOf(now) };
      },
      "PATCH /api/collection-groups/9": { body: changeOf({ ...GROUPED, groups: [...GROUPED.groups, { ...created, name: "Receipts" }] }) },
    });
    await user.click(await within(panel()).findByRole("button", { name: "New group" }));
    await waitFor(() => expect(posts(calls, "/api/collections/7/groups")).toHaveLength(1));
    expect(posts(calls, "/api/collections/7/groups")[0].body).toEqual({ name: "New group", parent_id: null });
    const name = await within(panel()).findByRole("textbox", { name: "Group name" });
    expect(name).toHaveFocus();
    await user.clear(name);
    await user.type(name, "Receipts{Enter}");
    await waitFor(() => expect(patches(calls, "/api/collection-groups/9")).toHaveLength(1));
    expect(patches(calls, "/api/collection-groups/9")[0].body).toEqual({ name: "Receipts" });
  });

  it("groups can be added one after another, while the last one's name is still being edited", async () => {
    let now = GROUPED;
    const { calls, user } = grouped({
      "GET /api/collections/7": () => ({ body: now }),
      "POST /api/collections/7/groups": (req) => {
        const id = 100 + now.groups.length;
        const created: Group = { id, collection_id: 7, parent_id: null, name: (req.body as { name?: string } | undefined)?.name ?? "?", position: now.groups.length, summary: "" };
        now = { ...now, groups: [...now.groups, created] };
        return { body: changeOf(now) };
      },
    });
    await within(panel()).findByRole("region", { name: "Quotes" });
    const add = () => user.click(within(panel().querySelector(".toolbar-actions") as HTMLElement).getByRole("button", { name: "New group" }));
    await add();
    await waitFor(() => expect(posts(calls, "/api/collections/7/groups")).toHaveLength(1));
    expect(await within(panel()).findByRole("textbox", { name: "Group name" })).toHaveFocus();
    // the name is left as it is: the next click must add another group, not just close the input
    await add();
    await waitFor(() => expect(posts(calls, "/api/collections/7/groups")).toHaveLength(2));
    expect(await within(panel()).findByRole("textbox", { name: "Group name" })).toHaveFocus();
    await add();
    await waitFor(() => expect(posts(calls, "/api/collections/7/groups")).toHaveLength(3));
    expect(posts(calls, "/api/collections/7/groups").map((c) => (c.body as { name: string }).name)).toEqual([
      "New group",
      "New group 2",
      "New group 3",
    ]);
  });

  it("typing a name for the new group and then clicking New group adds the next one", async () => {
    let now = GROUPED;
    const { calls, user } = grouped({
      "GET /api/collections/7": () => ({ body: now }),
      "POST /api/collections/7/groups": (req) => {
        const id = 100 + now.groups.length;
        const created: Group = { id, collection_id: 7, parent_id: null, name: (req.body as { name?: string } | undefined)?.name ?? "?", position: now.groups.length, summary: "" };
        now = { ...now, groups: [...now.groups, created] };
        return { body: changeOf(now) };
      },
      "PATCH /api/collection-groups/103": (req) => {
        now = { ...now, groups: now.groups.map((g) => (g.id === 103 ? { ...g, name: (req.body as { name?: string } | undefined)?.name ?? g.name } : g)) };
        return { body: changeOf(now) };
      },
    });
    await within(panel()).findByRole("region", { name: "Quotes" });
    const add = () => user.click(within(panel().querySelector(".toolbar-actions") as HTMLElement).getByRole("button", { name: "New group" }));
    await add();
    const input = await within(panel()).findByRole("textbox", { name: "Group name" });
    await user.clear(input);
    await user.type(input, "Receipts");
    await add(); // the click that blurs the input saves the name, and still adds the next group
    await waitFor(() => expect(patches(calls, "/api/collection-groups/103")).toHaveLength(1));
    await waitFor(() => expect(posts(calls, "/api/collections/7/groups")).toHaveLength(2));
    expect(await within(panel()).findByRole("textbox", { name: "Group name" })).toHaveFocus();
    await add();
    await waitFor(() => expect(posts(calls, "/api/collections/7/groups")).toHaveLength(3));
  });

  it("a group renames inline: Enter on its name, or a double-click; Esc cancels", async () => {
    const { calls, user } = grouped({
      "PATCH /api/collection-groups/3": { body: changeOf(GROUPED) },
    });
    const plans = await within(panel()).findByRole("region", { name: "Plans" });
    within(plans).getByRole("button", { name: "Plans" }).focus();
    await user.keyboard("{Enter}");
    const input = within(plans).getByRole("textbox", { name: "Group name" });
    await user.type(input, " v2{Escape}");
    expect(within(plans).queryByRole("textbox")).not.toBeInTheDocument();
    expect(patches(calls, "/api/collection-groups/3")).toHaveLength(0);

    await user.dblClick(within(plans).getByRole("button", { name: "Plans" }));
    const again = within(plans).getByRole("textbox", { name: "Group name" });
    await user.clear(again);
    await user.type(again, "Drawings{Enter}");
    await waitFor(() => expect(patches(calls, "/api/collection-groups/3")).toHaveLength(1));
    expect(patches(calls, "/api/collection-groups/3")[0].body).toEqual({ name: "Drawings" });
  });

  it("removing a group asks first in a sheet: the files stay in the collection", async () => {
    const { calls, user } = grouped({
      "POST /api/collection-groups/1/remove": { body: changeOf({ ...GROUPED, groups: [PLANS, { ...OLD, parent_id: null }] }) },
    });
    const quotes = await within(panel()).findByRole("region", { name: "Quotes" });
    await user.click(within(quotes).getAllByRole("button", { name: "Actions for Quotes" })[0]);
    await user.click(within(screen.getByRole("menu", { name: "Actions for Quotes" })).getByRole("menuitem", { name: "Remove group…" }));
    const dialog = await screen.findByRole("dialog", { name: "Remove the group Quotes?" });
    expect(dialog).toHaveTextContent("files stay in the collection");
    expect(posts(calls, "/api/collection-groups/1/remove")).toHaveLength(0);
    expect(within(dialog).getByRole("button", { name: "Cancel" })).toHaveFocus();
    await user.click(within(dialog).getByRole("button", { name: "Remove group" }));
    await waitFor(() => expect(posts(calls, "/api/collection-groups/1/remove")).toHaveLength(1));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("only live file members are draggable: not folders, missing or quarantined ones", async () => {
    grouped();
    const ungrouped = await within(panel()).findByRole("region", { name: "Ungrouped" });
    const quotes = within(tree()).getByRole("region", { name: "Quotes" });
    const rowOf = (scope: HTMLElement, name: string) => within(scope).getByText(name).closest("li")!;
    expect(rowOf(quotes, "quote.pdf")).toHaveAttribute("draggable", "true");
    expect(rowOf(quotes, "Plans")).not.toHaveAttribute("draggable", "true"); // a folder, in Old
    expect(rowOf(ungrouped, "old⟨U+202E⟩.pdf")).not.toHaveAttribute("draggable", "true"); // missing
    expect(rowOf(ungrouped, "x.pdf")).not.toHaveAttribute("draggable", "true"); // in ##. To Delete
    const dt = dataTransfer();
    fireEvent.dragStart(rowOf(ungrouped, "x.pdf"), { dataTransfer: dt });
    expect(dt.data["application/x-dam-files"]).toBeUndefined();
  });

  it("dropping a member on a group header calls members/group; on its own group it is refused", async () => {
    const { calls } = grouped({
      "POST /api/collections/7/members/group": { body: changeOf(GROUPED, { batch: batch([]) }) },
    });
    const quotes = await within(panel()).findByRole("region", { name: "Quotes" });
    const row = within(quotes).getByText("quote.pdf").closest("li")!;
    expect(row).toHaveAttribute("draggable", "true");
    const dt = dataTransfer();
    fireEvent.dragStart(row, { dataTransfer: dt });
    expect(JSON.parse(dt.data["application/x-dam-files"])).toEqual({ ids: ["f1"] });

    const ownHeader = within(quotes).getAllByRole("button", { name: "Quotes" })[0].closest(".group-header")!;
    fireEvent.dragEnter(ownHeader, { dataTransfer: dt });
    expect(ownHeader).toHaveAttribute("data-drop", "refused");
    expect(ownHeader).toHaveAttribute("data-tip", "Already in Quotes");
    // refused, but still ours: the drop is cancelled, so the browser never opens it
    expect(fireEvent.drop(ownHeader, { dataTransfer: dt })).toBe(false);
    expect(posts(calls, "/api/collections/7/members/group")).toHaveLength(0);

    const plans = within(tree()).getByRole("region", { name: "Plans" });
    const header = within(plans).getByRole("button", { name: "Plans" }).closest(".group-header")!;
    fireEvent.dragEnter(header, { dataTransfer: dt });
    expect(header).toHaveAttribute("data-drop", "over");
    fireEvent.drop(header, { dataTransfer: dt });
    await waitFor(() => expect(posts(calls, "/api/collections/7/members/group")).toHaveLength(1));
    expect(posts(calls, "/api/collections/7/members/group")[0].body).toEqual({ drive_ids: ["f1"], group_id: 3 });
    expect(header).not.toHaveAttribute("data-drop");
  });

  it("Move to group in the side panel is the keyboard way", async () => {
    const { calls, user } = grouped({
      "POST /api/collections/7/members/group": { body: changeOf(GROUPED) },
    });
    await user.click(await within(panel()).findByText("quote.pdf"));
    const inspector = within(panel()).getByRole("complementary", { name: "Selected file" });
    const select = within(inspector).getByRole("combobox", { name: "Group" });
    expect(select).toHaveValue("1"); // quote.pdf is in Quotes
    expect(within(select).getAllByRole("option").map((o) => o.textContent)).toEqual([
      "Ungrouped",
      "Quotes",
      "Quotes › Old",
      "Plans",
    ]);
    await user.selectOptions(select, "Quotes › Old");
    await waitFor(() => expect(posts(calls, "/api/collections/7/members/group")).toHaveLength(1));
    expect(posts(calls, "/api/collections/7/members/group")[0].body).toEqual({ drive_ids: ["f1"], group_id: 2 });
  });

  it("the attention strip lists the member's tray item and the inbox file, and selects on click", async () => {
    const attention: MemberAttention[] = [
      {
        drive_id: "f2",
        in_inbox: false,
        items: [
          {
            level: "overdue",
            item: {
              id: 41,
              tray_id: "to-pay",
              title: "Heat‮ bill",
              fields: {},
              date: "2026-10-12",
              state: "open",
              created: 1,
              done_at: null,
              done_fields: null,
              files: ["f2"],
              created_by_batch: null,
              missing_required: [],
              invalid_fields: [],
              tray_name: "To pay",
              tray_removed: false,
            },
          },
        ],
      },
      { drive_id: "f1", in_inbox: true, items: [] },
    ];
    const { user } = grouped({ "GET /api/collections/7/attention": { body: attention } });
    const strip = await within(panel()).findByRole("region", { name: "Needs attention" });
    const bill = await within(strip).findByRole("button", { name: /To pay: Heat⟨U\+202E⟩ bill/ });
    expect(bill.querySelector(".tag")).toHaveClass("tag-red");
    expect(within(strip).getByRole("button", { name: /In inbox: quote\.pdf/ })).toBeInTheDocument();
    // the rows carry the same tags
    const row = within(tree()).getByText("old⟨U+202E⟩.pdf").closest("li")!;
    expect(within(row).getByText(/To pay/)).toHaveClass("tag-red");
    await user.click(bill);
    const inspector = within(panel()).getByRole("complementary", { name: "Selected file" });
    expect(within(inspector).getByRole("button", { name: "Remove old⟨U+202E⟩.pdf from the collection" })).toBeInTheDocument();
  });

  it("no attention strip when nothing needs it", async () => {
    grouped({ "GET /api/collections/7/attention": { body: [] } });
    await within(panel()).findByRole("region", { name: "Members" });
    await waitFor(() => expect(within(panel()).queryByRole("region", { name: "Needs attention" })).not.toBeInTheDocument());
  });

  it("the summary auto-saves on blur, and a group summary too", async () => {
    const { calls, user } = grouped({
      "PATCH /api/collections/7/summary": (call) => ({
        body: changeOf({ ...GROUPED, summary: (call.body as { summary: string }).summary }),
      }),
      "PATCH /api/collection-groups/1": (call) => ({
        body: changeOf({
          ...GROUPED,
          groups: [{ ...QUOTES, summary: (call.body as { summary: string }).summary }, PLANS, OLD],
        }),
      }),
    });
    const summary = await within(panel()).findByRole("textbox", { name: "Summary" });
    expect(summary).toHaveValue("The sauna build");
    await user.type(summary, ", done by May");
    await user.tab();
    await waitFor(() => expect(patches(calls, "/api/collections/7/summary")).toHaveLength(1));
    expect(patches(calls, "/api/collections/7/summary")[0].body).toEqual({ summary: "The sauna build, done by May" });
    expect(await within(panel()).findByText("Saved")).toBeInTheDocument();

    const quotes = within(tree()).getByRole("region", { name: "Quotes" });
    await user.click(within(quotes).getByText("Two offers⟨U+202E⟩"));
    const line = within(quotes).getAllByRole("textbox", { name: "Summary of Quotes" })[0];
    expect(line).toHaveValue("Two offers‮"); // the raw text, to edit
    // Esc cancels the edit: nothing is sent and the stored summary stays
    await user.clear(line);
    await user.type(line, "Scrapped{Escape}");
    expect(within(quotes).queryByRole("textbox", { name: "Summary of Quotes" })).not.toBeInTheDocument();
    expect(within(quotes).getByText("Two offers⟨U+202E⟩")).toBeInTheDocument();
    expect(patches(calls, "/api/collection-groups/1")).toHaveLength(0);

    await user.click(within(quotes).getByText("Two offers⟨U+202E⟩"));
    const edit = within(quotes).getAllByRole("textbox", { name: "Summary of Quotes" })[0];
    await user.clear(edit);
    await user.type(edit, "Three offers{Enter}");
    await waitFor(() => expect(patches(calls, "/api/collection-groups/1")).toHaveLength(1));
    expect(patches(calls, "/api/collection-groups/1")[0].body).toEqual({ summary: "Three offers" });
  });

  it("a refused group removal closes the sheet and shows why", async () => {
    const { calls, user } = grouped({
      "POST /api/collection-groups/1/remove": { status: 400, body: { error: "a group named ‮Old exists there" } },
    });
    const quotes = await within(panel()).findByRole("region", { name: "Quotes" });
    await user.click(within(quotes).getAllByRole("button", { name: "Actions for Quotes" })[0]);
    await user.click(within(screen.getByRole("menu")).getByRole("menuitem", { name: "Remove group…" }));
    await user.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Remove group" }));
    await waitFor(() => expect(posts(calls, "/api/collection-groups/1/remove")).toHaveLength(1));
    expect(await within(panel()).findByRole("alert")).toHaveTextContent("⟨U+202E⟩Old exists there");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("a refused group rename keeps the input with the typed name and shows why", async () => {
    const { calls, user } = grouped({
      "PATCH /api/collection-groups/3": { status: 400, body: { error: "a group named Quotes exists there" } },
    });
    const plans = await within(panel()).findByRole("region", { name: "Plans" });
    await user.dblClick(within(plans).getByRole("button", { name: "Plans" }));
    const input = within(plans).getByRole("textbox", { name: "Group name" });
    await user.clear(input);
    await user.type(input, "Quotes{Enter}");
    await waitFor(() => expect(patches(calls, "/api/collection-groups/3")).toHaveLength(1));
    expect(await within(panel()).findByRole("alert")).toHaveTextContent("a group named Quotes exists there");
    expect(within(plans).getByRole("textbox", { name: "Group name" })).toHaveValue("Quotes");
  });

  it("while a change runs, drops are refused and a rename says another change is running", async () => {
    const moving = deferred<{ body: unknown }>();
    const { calls, user } = grouped({
      "POST /api/collections/7/members/group": () => moving.promise,
    });
    const inspector = await within(panel()).findByRole("complementary", { name: "Selected file" });
    await user.selectOptions(within(inspector).getByRole("combobox", { name: "Group" }), "Plans");
    await waitFor(() => expect(posts(calls, "/api/collections/7/members/group")).toHaveLength(1));
    // a drop is refused while it runs
    const quotes = within(tree()).getByRole("region", { name: "Quotes" });
    const dt = dataTransfer();
    fireEvent.dragStart(within(quotes).getByText("quote.pdf").closest("li")!, { dataTransfer: dt });
    const header = within(within(tree()).getByRole("region", { name: "Plans" })).getByRole("button", { name: "Plans" }).closest(".group-header")!;
    fireEvent.dragEnter(header, { dataTransfer: dt });
    expect(header).toHaveAttribute("data-tip", "Another change is still running");
    fireEvent.drop(header, { dataTransfer: dt });
    // a rename is refused with the reason, and its input stays
    const plans = within(tree()).getByRole("region", { name: "Plans" });
    await user.dblClick(within(plans).getByRole("button", { name: "Plans" }));
    const input = within(plans).getByRole("textbox", { name: "Group name" });
    await user.type(input, " 2{Enter}");
    expect(await within(panel()).findByRole("alert")).toHaveTextContent("Another change is still running");
    expect(within(plans).getByRole("textbox", { name: "Group name" })).toHaveValue("Plans 2");
    expect(patches(calls, "/api/collection-groups/3")).toHaveLength(0);
    await act(async () => moving.resolve({ body: changeOf(GROUPED) }));
    expect(posts(calls, "/api/collections/7/members/group")).toHaveLength(1);
  });

  it("a summary auto-save does not disable the Group select", async () => {
    const saving = deferred<{ body: unknown }>();
    const { calls, user } = grouped({ "PATCH /api/collections/7/summary": () => saving.promise });
    const summary = await within(panel()).findByRole("textbox", { name: "Summary" });
    await user.type(summary, "!");
    await user.tab();
    await waitFor(() => expect(patches(calls, "/api/collections/7/summary")).toHaveLength(1));
    const inspector = within(panel()).getByRole("complementary", { name: "Selected file" });
    expect(within(inspector).getByRole("combobox", { name: "Group" })).toBeEnabled();
    await act(async () => saving.resolve({ body: changeOf({ ...GROUPED, summary: "The sauna build!" }) }));
  });

  it("double activations of New group send one request", async () => {
    const made = deferred<{ body: unknown }>();
    const { calls } = grouped({ "POST /api/collections/7/groups": () => made.promise });
    const add = await within(panel()).findByRole("button", { name: "New group" });
    act(() => {
      add.click();
      add.click();
    });
    await act(async () => made.resolve({ body: changeOf(GROUPED) }));
    expect(posts(calls, "/api/collections/7/groups")).toHaveLength(1);
  });
});

describe("Collection AI summaries", () => {
  const ANSWER = {
    summary: "Building a sauna: offers and plans.",
    per_group: { "1": "Offers from two builders.", "3": "The floor plans‮." },
    rejected: {},
  };
  const NOTES = ["not sent, in an excluded folder (50. Medical): lab.pdf"];
  const ai = (collection: Collection, routes: Routes = {}) => {
    let current = collection;
    const result = renderCollections("/collections/7", {
      "GET /api/collections/7": () => ({ body: current }),
      "GET /api/ai/status": { body: STATUS_ON },
      "POST /api/ai/summarize-collection/prepare": {
        body: prepared({ task: "summarize-collection", notes: NOTES, files: ["f1"] }),
      },
      "POST /api/ai/summarize-collection/run": { body: { data: ANSWER, cost_eur: 0.001, cached: false } },
      "PATCH /api/collections/7/summary": (call) => {
        current = { ...current, summary: (call.body as { summary: string }).summary };
        return { body: changeOf(current) };
      },
      "PATCH /api/collection-groups/1": (call) => {
        const summary = (call.body as { summary: string }).summary;
        current = { ...current, groups: current.groups.map((g) => (g.id === 1 ? { ...g, summary } : g)) };
        return { body: changeOf(current) };
      },
      "PATCH /api/collection-groups/3": (call) => {
        const summary = (call.body as { summary: string }).summary;
        current = { ...current, groups: current.groups.map((g) => (g.id === 3 ? { ...g, summary } : g)) };
        return { body: changeOf(current) };
      },
      ...routes,
    });
    return result;
  };

  async function summarize(user: ReturnType<typeof userEvent.setup>) {
    await user.click(await within(panel()).findByRole("button", { name: "Summarize with AI…" }));
    const sheet = await screen.findByRole("dialog", { name: "What will be sent" });
    // the skipped members are shown in the sheet, never sent
    expect(within(sheet).getByRole("list", { name: "Left out" })).toHaveTextContent("lab.pdf");
    await user.click(within(sheet).getByRole("button", { name: "Send" }));
    return within(panel()).findByRole("region", { name: "AI summary of the collection" });
  }

  it("proposes a collection summary and one per group; Use saves, Discard drops", async () => {
    const { calls, user } = ai({ ...GROUPED, summary: "" });
    const line = await summarize(user);
    expect(line).toHaveTextContent(ANSWER.summary);
    const plans = within(tree()).getByRole("region", { name: "Plans" });
    expect(within(plans).getByRole("region", { name: "AI summary of Plans" })).toHaveTextContent("The floor plans⟨U+202E⟩.");
    expect(patches(calls, "/api/collections/7/summary")).toHaveLength(0);

    // an empty summary: Use saves at once
    await user.click(within(line).getByRole("button", { name: "Use" }));
    await waitFor(() => expect(patches(calls, "/api/collections/7/summary")).toHaveLength(1));
    expect(patches(calls, "/api/collections/7/summary")[0].body).toEqual({ summary: ANSWER.summary });
    await waitFor(() =>
      expect(within(panel()).queryByRole("region", { name: "AI summary of the collection" })).not.toBeInTheDocument(),
    );
    expect(await within(panel()).findByRole("textbox", { name: "Summary" })).toHaveValue(ANSWER.summary);

    // the empty group: Use saves the line
    await user.click(within(within(plans).getByRole("region", { name: "AI summary of Plans" })).getByRole("button", { name: "Use" }));
    await waitFor(() => expect(patches(calls, "/api/collection-groups/3")).toHaveLength(1));
    expect(patches(calls, "/api/collection-groups/3")[0].body).toEqual({ summary: "The floor plans‮." });

    // Discard: nothing saved
    const quotes = within(tree()).getByRole("region", { name: "Quotes" });
    await user.click(within(within(quotes).getByRole("region", { name: "AI summary of Quotes" })).getByRole("button", { name: "Discard" }));
    expect(within(quotes).queryByRole("region", { name: "AI summary of Quotes" })).not.toBeInTheDocument();
    expect(patches(calls, "/api/collection-groups/1")).toHaveLength(0);
  });

  it("asks before overwriting a summary already there", async () => {
    const { calls, user } = ai(GROUPED);
    const line = await summarize(user);
    await user.click(within(line).getByRole("button", { name: "Use" }));
    const confirm = await screen.findByRole("dialog", { name: "Replace the summary?" });
    expect(confirm).toHaveTextContent("The current text is not kept.");
    expect(patches(calls, "/api/collections/7/summary")).toHaveLength(0);
    await user.click(within(confirm).getByRole("button", { name: "Cancel" }));
    expect(patches(calls, "/api/collections/7/summary")).toHaveLength(0);

    // the group "Quotes" has a summary: asked too
    const quotes = within(tree()).getByRole("region", { name: "Quotes" });
    await user.click(within(within(quotes).getByRole("region", { name: "AI summary of Quotes" })).getByRole("button", { name: "Use" }));
    const ask = await screen.findByRole("dialog", { name: "Replace the summary of Quotes?" });
    await user.click(within(ask).getByRole("button", { name: "Replace" }));
    await waitFor(() => expect(patches(calls, "/api/collection-groups/1")).toHaveLength(1));
    expect(patches(calls, "/api/collection-groups/1")[0].body).toEqual({ summary: "Offers from two builders." });
  });

  it("switching AI off hides the proposals and their Use and Discard", async () => {
    const { user, client } = ai(GROUPED);
    await summarize(user);
    expect(within(tree()).getByRole("region", { name: "AI summary of Plans" })).toBeInTheDocument();
    act(() => client.setQueryData(["ai", "status"], { ...STATUS_ON, enabled: false, switched_on: false }));
    await waitFor(() =>
      expect(within(panel()).queryByRole("region", { name: "AI summary of the collection" })).not.toBeInTheDocument(),
    );
    expect(within(tree()).queryByRole("region", { name: /^AI summary of/ })).not.toBeInTheDocument();
    expect(within(panel()).queryByRole("button", { name: "Use" })).not.toBeInTheDocument();
    expect(within(panel()).queryByRole("button", { name: "Discard" })).not.toBeInTheDocument();
  });

  it("with AI off there is no Summarize button", async () => {
    ai(GROUPED, { "GET /api/ai/status": { body: { ...STATUS_ON, enabled: false, has_key: false } } });
    expect(await within(panel()).findByText(/Turn on AI/)).toBeInTheDocument();
    expect(within(panel()).queryByRole("button", { name: "Summarize with AI…" })).not.toBeInTheDocument();
  });
});

describe("Parent collections", () => {
  const HOUSES: Collection = { ...SAUNA, id: 1, name: "Houses", path: ["Houses"], members: [], ongoing_rel: `${ONG}/Houses` };
  const IN_HOUSES: Collection = { ...SAUNA, parent_id: 1, path: ["Houses", "Sauna"], ongoing_rel: `${ONG}/Houses/Sauna` };
  // one file and one folder: "1 file, 1 folder", on its own page and on its parent's
  const DECK: Collection = { ...SAUNA, id: 9, name: "Deck", parent_id: 7, path: ["Houses", "Sauna", "Deck"], members: SAUNA.members.slice(0, 2) };
  const OVEN: Collection = { ...SAUNA, id: 10, name: "Oven‮", parent_id: 7, path: ["Houses", "Sauna", "Oven‮"], members: [], groups: [QUOTES] };
  const CAR: Collection = { ...SAUNA, id: 3, name: "Car", path: ["Car"], members: [] };
  const OLD_SHED: Collection = { ...CLOSED, id: 11, name: "Old shed", parent_id: 7, path: ["Houses", "Sauna", "Old shed"] };
  const open = [row(HOUSES, 0, 0), row(IN_HOUSES, 4, 0), row(DECK, 2, 1), row(OVEN, 5, 0), row(CAR, 1, 0)];
  const lists = (call: Call) => ({
    body: call.url.includes("state=closed") ? [row(OLD_SHED, 3, 0)] : call.url.includes("state=all") ? [...open, row(OLD_SHED, 3, 0)] : open,
  });
  const MOVE_OPS: ResolvedOp[] = [{ kind: "move", src: `${ONG}/Houses/Sauna`, dst: `${ONG}/Sauna`, drive_id: null, note: null }];
  const sauna = (routes: Routes = {}) =>
    renderCollections("/collections/7", { "GET /api/collections": lists, "GET /api/collections/7": { body: IN_HOUSES }, ...routes });

  it("Close collection… is disabled while open collections are inside, and says why", async () => {
    const { user } = sauna(); // Deck and Oven are open inside Sauna; Old shed is closed
    await user.click(await within(panel()).findByRole("button", { name: "More actions" }));
    const menu = await screen.findByRole("menu", { name: "More actions" });
    const close = within(menu).getByRole("menuitem", { name: "Close collection…" });
    expect(close).toBeDisabled();
    expect(close).toHaveAccessibleDescription("Close or move its collections first");
    expect(within(menu).getByRole("menuitem", { name: "Move to…" })).toBeEnabled();
  });

  it("Close collection… is enabled once every collection inside is closed", async () => {
    const { user } = renderCollections("/collections/9", {
      "GET /api/collections": lists,
      "GET /api/collections/9": { body: DECK }, // nothing inside Deck
      "GET /api/notes/collection/9": { body: { text: "" } },
      "GET /api/checklist/collection/9": { body: [] },
    });
    await user.click(await within(panel()).findByRole("button", { name: "More actions" }));
    const menu = await screen.findByRole("menu", { name: "More actions" });
    const close = within(menu).getByRole("menuitem", { name: "Close collection…" });
    expect(close).toBeEnabled();
    expect(close).not.toHaveAttribute("aria-describedby");
  });

  it("a collection hidden with its parent says so in the Finder popover instead of advice", async () => {
    const status = `Not shown: its parent collection 'Houses' is not shown in ${ONG}`;
    const { user } = sauna({ "GET /api/collections/7": { body: { ...IN_HOUSES, ongoing_rel: null, ongoing_status: status } } });
    await user.click((await within(panel()).findAllByRole("button", { name: "Show in Finder" }))[0]); // the toolbar's
    const popover = within(panel()).getByRole("group", { name: "Show in Finder" });
    expect(popover).toHaveTextContent(status);
    expect(popover).not.toHaveTextContent("Turn on");
  });

  it("a long move says how many links it recreated, in the toast and the result's title", async () => {
    const links: ResolvedOp[] = Array.from({ length: 51 }, (_, i) => ({
      kind: "symlink",
      src: `40. House/Sauna/f${i}.pdf`,
      dst: `${ONG}/Sauna/f${i}.pdf`,
      drive_id: null,
      note: null,
    }));
    const { user } = sauna({
      "PATCH /api/collections/7/parent": { body: changeOf({ ...IN_HOUSES, parent_id: null, path: ["Sauna"] }, { batch: batch([...MOVE_OPS, ...links]) }) },
    });
    await fromMenu(user, "Move to…");
    const dialog = await screen.findByRole("dialog", { name: "Move Sauna to…" });
    await user.click(within(dialog).getByRole("radio", { name: "Top level" }));
    await user.click(within(dialog).getByRole("button", { name: "Move" }));
    expect(await screen.findByText("Moved Sauna to the top level (recreated 51 links)")).toBeInTheDocument();
    expect(within(panel()).getByRole("region", { name: "What changed in ##. Ongoing (recreated 51 links)" })).toBeInTheDocument();
  });

  it("the collection page lists its child collections with their counts, above the members", async () => {
    sauna();
    const children = await within(panel()).findByRole("region", { name: "Collections" });
    const rows = await within(children).findAllByRole("article");
    expect(rows.map((r) => r.getAttribute("aria-label"))).toEqual(["Deck", "Old shed", "Oven⟨U+202E⟩"]);
    expect(within(rows[0]).getByRole("link", { name: "Deck" })).toHaveAttribute("href", "/collections/9");
    // typed member counts, as each child's own page has them (coordinator ruling)
    expect(rows[0]).toHaveTextContent("1 folder · 2 files · 1 open check");
    expect(rows[1]).toHaveTextContent("Closed");
    expect(rows[2]).toHaveTextContent("5 files · 1 group"); // the list's count
    expect(children.compareDocumentPosition(tree()) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    // the breadcrumb of where it sits
    expect(within(panel()).getByRole("link", { name: "Houses" })).toHaveAttribute("href", "/collections/1");
  });

  it("a child's count on its parent's page is the one on its own page", async () => {
    sauna();
    const children = await within(panel()).findByRole("region", { name: "Collections" });
    const onParent = (await within(children).findAllByRole("article"))[0].querySelector(".collection-row-meta")!.textContent!;
    cleanup();
    renderCollections("/collections/9", { "GET /api/collections": lists, "GET /api/collections/9": { body: DECK } });
    await within(panel()).findByRole("heading", { name: "Deck" });
    const subtitle = await within(panel()).findByText(/^Open · 1 folder · 2 files/); // once the list has loaded
    const own = subtitle.textContent!.replace(/^Open · /, "");
    expect(own).toBe("1 folder · 2 files");
    expect(onParent.split(" · ").slice(0, 2).join(" · ")).toBe(own);
  });

  it("no Collections section without children", async () => {
    renderCollections("/collections/9", { "GET /api/collections": lists, "GET /api/collections/9": { body: DECK } });
    await within(panel()).findByRole("heading", { name: "Deck" });
    await screen.findByRole("region", { name: "Members" });
    expect(within(panel()).queryByRole("region", { name: "Collections" })).not.toBeInTheDocument();
  });

  it("Move to… picks a new parent (never itself or its own collections) and shows what Ongoing did", async () => {
    const { calls, user } = sauna({
      "PATCH /api/collections/7/parent": { body: changeOf({ ...IN_HOUSES, parent_id: null, path: ["Sauna"] }, { batch: batch(MOVE_OPS), problems: ["kept‮ a user file"] }) },
    });
    await fromMenu(user, "Move to…");
    const dialog = await screen.findByRole("dialog", { name: "Move Sauna to…" });
    const options = within(dialog).getAllByRole("radio").map((r) => r.closest("label")!.textContent);
    expect(options).toEqual(["Top level", "Car", "Houses"]); // not Sauna, Deck or Oven (its own)
    expect(within(dialog).getByRole("radio", { name: "Houses" })).toBeChecked(); // where it is now
    expect(within(dialog).getByRole("button", { name: "Move" })).toBeDisabled();
    await user.click(within(dialog).getByRole("radio", { name: "Top level" }));
    await user.click(within(dialog).getByRole("button", { name: "Move" }));
    await waitFor(() => expect(patches(calls, "/api/collections/7/parent")).toHaveLength(1));
    expect(patches(calls, "/api/collections/7/parent")[0].body).toEqual({ parent_id: null });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    const result = await within(panel()).findByRole("region", { name: "What changed in ##. Ongoing" });
    expect(result.querySelectorAll(".plan-op")).toHaveLength(1);
    expect(result).toHaveTextContent(`${ONG}/Houses/Sauna`);
    expect(result).toHaveTextContent("kept⟨U+202E⟩ a user file");
    expect(await screen.findByText("Moved Sauna to the top level, but: kept⟨U+202E⟩ a user file")).toBeInTheDocument();
  });

  it("Move to… filters by name or path, works from the keyboard, and sends one request for a double Move", async () => {
    const held = deferred<{ body: unknown }>();
    const { calls, user } = sauna({ "PATCH /api/collections/7/parent": () => held.promise });
    await fromMenu(user, "Move to…");
    const dialog = await screen.findByRole("dialog", { name: "Move Sauna to…" });
    await user.type(within(dialog).getByRole("searchbox", { name: "Find a collection" }), "car");
    expect(within(dialog).getAllByRole("radio").map((r) => r.closest("label")!.textContent)).toEqual(["Top level", "Car"]);
    await user.click(within(dialog).getByRole("radio", { name: "Car" }));
    const move = within(dialog).getByRole("button", { name: "Move" });
    await user.dblClick(move);
    fireEvent.click(move);
    await act(async () => held.resolve({ body: changeOf({ ...IN_HOUSES, parent_id: 3, path: ["Car", "Sauna"] }) }));
    expect(patches(calls, "/api/collections/7/parent")).toHaveLength(1);
    expect(patches(calls, "/api/collections/7/parent")[0].body).toEqual({ parent_id: 3 });
    expect(await screen.findByText("Moved Sauna into Car")).toBeInTheDocument();
  });

  it("a refused move (a closed parent) closes the sheet and shows why", async () => {
    const { user } = sauna({ "PATCH /api/collections/7/parent": { status: 409, body: { error: "Car is ‮closed" } } });
    await fromMenu(user, "Move to…");
    const dialog = await screen.findByRole("dialog", { name: "Move Sauna to…" });
    await user.click(within(dialog).getByRole("radio", { name: "Car" }));
    await user.click(within(dialog).getByRole("button", { name: "Move" }));
    expect(await within(panel()).findByRole("alert")).toHaveTextContent("Car is ⟨U+202E⟩closed");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("New collection inside… creates a child and opens it", async () => {
    const { calls, user } = sauna({
      "POST /api/collections": { body: { ...DECK, id: 12, name: "Stove", path: ["Houses", "Sauna", "Stove"] } },
    });
    await fromMenu(user, "New collection inside…");
    const dialog = await screen.findByRole("dialog", { name: "New collection inside Sauna" });
    const create = within(dialog).getByRole("button", { name: "Create" });
    expect(create).toBeDisabled();
    await user.type(within(dialog).getByRole("textbox", { name: "Name" }), "  Stove ");
    await user.dblClick(create);
    await waitFor(() => expect(where()).toBe("/collections/12"));
    expect(posts(calls, "/api/collections").map((c) => c.body)).toEqual([{ name: "Stove", parent_id: 7 }]);
    expect(await screen.findByText("Created Stove inside Sauna")).toBeInTheDocument();
  });

  it("a refused new name stays in the sheet with the reason", async () => {
    const { user } = sauna({ "POST /api/collections": { status: 400, body: { error: "a collection named 'Car' already ‮exists" } } });
    await fromMenu(user, "New collection inside…");
    const dialog = await screen.findByRole("dialog", { name: "New collection inside Sauna" });
    await user.type(within(dialog).getByRole("textbox", { name: "Name" }), "Car{Enter}");
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("already ⟨U+202E⟩exists");
    expect(within(dialog).getByRole("textbox", { name: "Name" })).toHaveValue("Car");
  });

  it("a closed collection offers no New collection inside", async () => {
    const { user } = renderCollections("/collections/8", { "GET /api/collections": lists });
    await user.click(await within(panel()).findByRole("button", { name: "More actions" }));
    const menu = await screen.findByRole("menu", { name: "More actions" });
    expect(within(menu).getByRole("menuitem", { name: "New collection inside…" })).toBeDisabled();
    expect(within(menu).getByRole("menuitem", { name: "Move to…" })).toBeEnabled();
  });

  it("the index shows the tree: children nested under their parent, A–Z", async () => {
    renderCollections("/collections", { "GET /api/collections": lists });
    const houses = await screen.findByRole("article", { name: "Houses" });
    const item = houses.closest("li")!;
    const nested = within(item).getAllByRole("article").map((a) => a.getAttribute("aria-label"));
    expect(nested).toEqual(["Houses", "Sauna", "Deck", "Oven⟨U+202E⟩"]);
    const top = within(screen.getByRole("list", { name: "Collections" }))
      .getAllByRole("article")
      .map((a) => a.getAttribute("aria-label"));
    expect(top).toEqual(["Car", "Houses", "Sauna", "Deck", "Oven⟨U+202E⟩"]);
    expect(within(houses).getByText("0 files · 1 collection")).toBeInTheDocument();
  });

  it("the closed list shows where a closed collection sits", async () => {
    const { user } = renderCollections("/collections", { "GET /api/collections": lists });
    await user.click(await screen.findByRole("button", { name: "Closed" }));
    const shed = await screen.findByRole("article", { name: "Old shed" });
    expect(shed).toHaveTextContent("In Houses › Sauna");
  });
});

describe("Trash on collection members", () => {
  const inspector = () => within(panel()).getByRole("complementary", { name: "Selected file" });
  const quarantines = (calls: Call[]) => posts(calls, "/api/quarantine").map((c) => c.body);

  it("the inspector's bin moves the selected file to ##. To Delete through the confirm; Undo restores", async () => {
    const { calls, user } = renderCollections("/collections/7", {
      "POST /api/quarantine": quarantineRoute({ f1: "40. House/Sauna/quote.pdf" }),
      "POST /api/activity/q1/undo/preview": { body: [] },
      "POST /api/activity/q1/undo": { body: { batch_id: "u1", dry_run: false, done: [], failed: null, error: null, index_error: null } },
    });
    await within(panel()).findByRole("region", { name: "Members" });
    await user.click(within(inspector()).getByRole("button", { name: "Move to To Delete" }));
    const dialog = await screen.findByRole("dialog", { name: "Move to To Delete?" });
    expect(dialog).toHaveTextContent("40. House/Sauna/quote.pdf → ##. To Delete/40. House/Sauna/quote.pdf");
    await user.click(within(dialog).getByRole("button", { name: "Move to To Delete" }));
    await user.click(await screen.findByRole("button", { name: "Undo" }));
    await user.click(await undoButton(await screen.findByRole("dialog", { name: "Undo these changes?" })));
    await waitFor(() => expect(posts(calls, "/api/activity/q1/undo")).toHaveLength(1));
    expect(quarantines(calls)).toEqual([
      { drive_ids: ["f1"], dry_run: true },
      { drive_ids: ["f1"], dry_run: false },
    ]);
  });

  it("⌘⌫ on a focused member row trashes that member; a plain ⌫ does not; a quarantined one is refused, saying why", async () => {
    const { calls, user } = renderCollections("/collections/7", {
      "POST /api/quarantine": quarantineRoute({ f1: "40. House/Sauna/quote.pdf" }),
    });
    const members = await within(panel()).findByRole("region", { name: "Members" });
    await user.click(within(within(members).getByText("x.pdf").closest("li")!).getByRole("button"));
    const bin = within(inspector()).getByRole("button", { name: "Move to To Delete" });
    expect(bin).toBeDisabled();
    expect(bin.parentElement).toHaveAttribute("data-tip", "Already in ##. To Delete");
    await user.keyboard("{Meta>}{Backspace}{/Meta}");
    expect(await screen.findByText("Already in ##. To Delete", { selector: ".toast-text" })).toBeInTheDocument();
    expect(quarantines(calls)).toHaveLength(0);
    await user.click(within(within(members).getByText("quote.pdf").closest("li")!).getAllByRole("button")[0]);
    await user.keyboard("{Backspace}");
    await new Promise((r) => setTimeout(r, 10));
    expect(quarantines(calls)).toHaveLength(0);
    await user.keyboard("{Meta>}{Backspace}{/Meta}");
    await screen.findByRole("dialog", { name: "Move to To Delete?" });
    expect(quarantines(calls)).toEqual([{ drive_ids: ["f1"], dry_run: true }]);
  });

  it("for a link member the confirm says the link moves and its target stays", async () => {
    const { calls, user } = renderCollections("/collections/7", {
      "GET /api/collections/7": { body: { ...SAUNA, members: [{ ...SAUNA.members[0], is_link: true }, ...SAUNA.members.slice(1)] } },
      "POST /api/quarantine": quarantineRoute({ f1: "40. House/Sauna/quote.pdf" }),
    });
    await within(panel()).findByRole("region", { name: "Members" });
    await user.click(within(inspector()).getByRole("button", { name: "Move to To Delete" }));
    const dialog = await screen.findByRole("dialog", { name: "Move to To Delete?" });
    expect(dialog).toHaveTextContent("A link moves the link; its target stays.");
    expect(quarantines(calls)).toEqual([{ drive_ids: ["f1"], dry_run: true }]);
  });

  it("a plain file's confirm says nothing about links", async () => {
    const { user } = renderCollections("/collections/7", {
      "POST /api/quarantine": quarantineRoute({ f1: "40. House/Sauna/quote.pdf" }),
    });
    await within(panel()).findByRole("region", { name: "Members" });
    await user.click(within(inspector()).getByRole("button", { name: "Move to To Delete" }));
    const dialog = await screen.findByRole("dialog", { name: "Move to To Delete?" });
    expect(dialog).not.toHaveTextContent(/link/);
  });

  it("a member marked Important has its bin disabled up front with the server's reason (Important page too)", async () => {
    const important = { ...SAUNA, members: [{ ...SAUNA.members[0], marks: ["important"] }, ...SAUNA.members.slice(1)] };
    const { calls, user } = renderCollections("/collections/7", {
      "GET /api/collections/7": { body: important },
      "POST /api/quarantine": quarantineRoute({ f1: "40. House/Sauna/quote.pdf" }),
    });
    await within(panel()).findByRole("region", { name: "Members" });
    const bin = within(inspector()).getByRole("button", { name: "Move to To Delete" });
    expect(bin).toBeDisabled();
    expect(bin.parentElement).toHaveAttribute("data-tip", "This file is marked Important; unmark it first");
    await user.keyboard("{Meta>}{Backspace}{/Meta}");
    expect(
      await screen.findByText("This file is marked Important; unmark it first", { selector: ".toast-text" }),
    ).toBeInTheDocument();
    expect(quarantines(calls)).toHaveLength(0);
  });

  it("a file marked Important is refused with the server's reason", async () => {
    const { user } = renderCollections("/collections/7", {
      "POST /api/quarantine": IMPORTANT_REFUSED("40. House/Sauna/quote.pdf"),
    });
    await within(panel()).findByRole("region", { name: "Members" });
    await user.click(within(inspector()).getByRole("button", { name: "Move to To Delete" }));
    expect(await screen.findByText(/This file is marked Important; unmark it first/)).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});
