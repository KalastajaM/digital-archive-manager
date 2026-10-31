import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it } from "vitest";
import type { Collection, ConvertPlan, ConvertResult, OngoingEntry, ResolvedOp } from "../api/client";
import { Sidebar } from "../components/ui/Sidebar";
import { type Call, mockFetch, renderWithProviders, undoButton } from "../test-utils";
import ConvertImportant, { UNDO_HINT } from "./ConvertImportant";
import Important from "./Important";

const IMP = "##. Important";
const base: OngoingEntry = {
  rel: `${IMP}/Houses`,
  kind: "folder",
  target_rel: null,
  managed: false,
  suggested_name: "Houses",
  contents: ["Hillside", "will.pdf"],
  problem: null,
  collection_id: null,
  collection_name: null,
  drive_id: "d-houses",
  is_dir: true,
  real_files: 3,
  items: [
    { name: "Hillside", drive_id: "d-hillside", is_dir: true, is_link: false, unreadable: false, marks: [] },
    { name: "will.pdf", drive_id: "id-will", is_dir: false, is_link: true, unreadable: false, marks: ["starred"] },
  ],
  marks: [],
};
const taxLink: OngoingEntry = {
  ...base,
  rel: `${IMP}/Tax 2025.pdf`,
  kind: "link",
  target_rel: "13. Taxes/2025.pdf",
  suggested_name: "Tax 2025",
  contents: [],
  items: [],
  drive_id: "id-tax",
  is_dir: false,
  real_files: 0,
  marks: ["important"],
};
const outside: OngoingEntry = { ...taxLink, rel: `${IMP}/Bank`, problem: "points outside the archive", drive_id: null, marks: [] };
const OPS: ResolvedOp[] = [
  { kind: "unlink_symlink", src: null, dst: `${IMP}/Houses/will.pdf`, drive_id: null, note: null },
  { kind: "move", src: `${IMP}/Houses/Hillside/survey.pdf`, dst: "40. Family/Papers/Houses/Hillside/survey.pdf", drive_id: "id-survey", note: null },
  { kind: "symlink", src: null, dst: `${IMP}/Houses/Hillside/Survey 2020.pdf`, drive_id: null, note: null },
];
const PLAN: ConvertPlan = {
  ops: OPS,
  members: ["40. Family/will.pdf", "40. Family/Papers/Houses/Hillside/survey.pdf"],
  notes: [`${IMP}/Houses/Hillside/deed 2.pdf is left untouched: same file as ${IMP}/Houses/Hillside/deed.pdf (already in Important)`],
  collection: "Important",
  existing: true,
  existing_members: 2,
  fingerprint: "fp-imp",
  groups: ["Houses", "Houses/Hillside"],
  link_names: ["", "Survey 2020.pdf"],
};
const RESULT: ConvertResult = {
  batch: { batch_id: "b7", dry_run: false, done: OPS, failed: null, error: null, index_error: null },
  collection_id: 2,
  problems: [],
  sync: null,
};

const posts = (calls: Call[], url: string) => calls.filter((c) => c.method === "POST" && c.url === url);
const row = async (title: string) => (await screen.findByRole("heading", { level: 3, name: new RegExp(title) })).closest("li")!;

function setup(entries: OngoingEntry[], routes: Parameters<typeof mockFetch>[0] = {}) {
  const calls = mockFetch({
    "GET /api/important/entries": { body: entries },
    "GET /api/folders": { body: ["40. Family/Papers"] },
    ...routes,
  });
  const user = userEvent.setup();
  renderWithProviders(
    <MemoryRouter>
      <ConvertImportant />
    </MemoryRouter>,
  );
  return { calls, user };
}

describe("ConvertImportant", () => {
  it("lists the entries with their icons, buttons and problems; a folder needs its archive folder", async () => {
    setup([outside, base, taxLink]);
    const houses = await row("Houses");
    const will = within(houses).getByText("will.pdf").closest("li")!;
    expect(within(will).getByRole("img", { name: "Starred" })).toBeInTheDocument();
    for (const name of ["Quick Look", "Open", "Show in Finder"]) expect(within(will).getByRole("button", { name })).toBeInTheDocument();
    expect(within(houses).getByRole("button", { name: "Preview" })).toBeDisabled();
    // the required label says it; there is no second "Choose an archive folder" hint
    expect(within(houses).getByLabelText("Archive folder for its 3 files (required)")).toBeInTheDocument();
    expect(within(houses).queryByText("Choose an archive folder")).toBeNull();
    const tax = await row("Tax 2025");
    expect(within(tax.querySelector("h3")!).getByRole("img", { name: "Important" })).toBeInTheDocument();
    expect(within(tax).getByRole("button", { name: "Preview" })).toBeEnabled(); // a link needs no folder
    const problems = screen.getByRole("list", { name: "Can't be converted" });
    expect(within(problems).getByText("points outside the archive")).toBeInTheDocument();
  });

  it("previews the members with their groups, link names and notes, and applies exactly the preview", async () => {
    const { calls, user } = setup([base], {
      "POST /api/important/preview": { body: PLAN },
      "POST /api/important/convert": { body: RESULT },
    });
    const houses = await row("Houses");
    expect(within(houses).getByRole("button", { name: "Browse folders…" })).toBeInTheDocument();
    await user.type(within(houses).getByLabelText("Archive folder for its 3 files (required)"), "40. Family/Papers");
    await user.click(within(houses).getByRole("button", { name: "Preview" }));
    const d = await screen.findByRole("dialog");
    expect(within(d).getByText(/already in Important/)).toBeInTheDocument();
    const members = within(d).getAllByRole("listitem").filter((li) => li.closest(".important-plan-members"));
    expect(members.map((li) => li.textContent)).toEqual([
      "40. Family/will.pdf → group Houses",
      "40. Family/Papers/Houses/Hillside/survey.pdf → group Houses › Hillside, linked as Survey 2020.pdf",
    ]);
    expect(within(d).queryByText(UNDO_HINT)).toBeNull(); // the hint is where undo is, not in the plan
    await user.click(within(d).getByRole("button", { name: "Convert" }));
    await waitFor(() => expect(posts(calls, "/api/important/convert")).toHaveLength(1));
    const body = { rel: base.rel, destination: "40. Family/Papers" };
    expect(posts(calls, "/api/important/preview")[0].body).toEqual(body);
    expect(posts(calls, "/api/important/convert")[0].body).toEqual({ ...body, fingerprint: "fp-imp" });
    expect(await screen.findByRole("heading", { name: `Converted ${base.rel}` })).toBeInTheDocument();
    expect(screen.getByText(UNDO_HINT)).toBeInTheDocument(); // beside the conversions that can be undone
  });

  it("the toast's Undo confirms and posts the undo of the conversion's batch", async () => {
    const { calls, user } = setup([taxLink], {
      "POST /api/important/preview": { body: { ...PLAN, members: ["13. Taxes/2025.pdf"], groups: [""], link_names: ["Tax 2025.pdf"], notes: [] } },
      "POST /api/important/convert": { body: RESULT },
      "POST /api/activity/b7/undo/preview": { body: OPS },
      "POST /api/activity/b7/undo": { body: { ...RESULT.batch, batch_id: "u1", follow_up_error: null } },
    });
    await user.click(within(await row("Tax 2025")).getByRole("button", { name: "Preview" }));
    const d = await screen.findByRole("dialog");
    expect(d.querySelector(".important-plan-members li")).toHaveTextContent("13. Taxes/2025.pdf → the top of Important, linked as Tax 2025.pdf");
    await user.click(within(d).getByRole("button", { name: "Convert" }));
    await user.click(within(await screen.findByRole("status")).getByRole("button", { name: "Undo" }));
    const confirm = await screen.findByRole("dialog");
    await user.click(await undoButton(confirm));
    await waitFor(() => expect(posts(calls, "/api/activity/b7/undo")).toHaveLength(1));
  });

  it("the converted card has its own Undo, which clears the card once undone", async () => {
    const { calls, user } = setup([taxLink], {
      "POST /api/important/preview": { body: { ...PLAN, members: ["13. Taxes/2025.pdf"], groups: [""], link_names: [""], notes: [] } },
      "POST /api/important/convert": { body: RESULT },
      "POST /api/activity/b7/undo/preview": { body: OPS },
      "POST /api/activity/b7/undo": { body: { ...RESULT.batch, batch_id: "u1", follow_up_error: null } },
    });
    await user.click(within(await row("Tax 2025")).getByRole("button", { name: "Preview" }));
    await user.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Convert" }));
    const card = (await screen.findByRole("heading", { name: `Converted ${taxLink.rel}` })).closest("section")!;
    await user.click(within(card).getByRole("button", { name: "Undo" }));
    await user.click(await undoButton(await screen.findByRole("dialog")));
    await waitFor(() => expect(posts(calls, "/api/activity/b7/undo")).toHaveLength(1));
    await waitFor(() => expect(screen.queryByRole("heading", { name: /^Converted / })).toBeNull());
  });

  it("a folder of shortcuts and subfolders needs no archive folder; one with real files does", async () => {
    const shortcuts: OngoingEntry = { ...base, rel: `${IMP}/Cottages`, suggested_name: "Cottages", real_files: 0 };
    const { calls, user } = setup([shortcuts, base], { "POST /api/important/preview": { body: PLAN } });
    const empty = await row("Cottages");
    expect(within(empty).queryByLabelText(/Archive folder/)).toBeNull();
    const preview = within(empty).getByRole("button", { name: "Preview" });
    expect(preview).toBeEnabled();
    const full = await row("Houses");
    expect(within(full).getByLabelText("Archive folder for its 3 files (required)")).toBeInTheDocument();
    expect(within(full).getByRole("button", { name: "Preview" })).toBeDisabled();
    await user.click(preview);
    await waitFor(() => expect(posts(calls, "/api/important/preview")).toHaveLength(1));
    expect(posts(calls, "/api/important/preview")[0].body).toEqual({ rel: shortcuts.rel, destination: null });
  });

  it("a stale preview offers to preview again", async () => {
    const { user } = setup([taxLink], {
      "POST /api/important/preview": { body: PLAN },
      "POST /api/important/convert": { status: 400, body: { error: "changed since the preview", code: "stale_preview" } },
    });
    await user.click(within(await row("Tax 2025")).getByRole("button", { name: "Preview" }));
    await user.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Convert" }));
    expect(await screen.findByRole("button", { name: "Preview again" })).toBeInTheDocument();
  });
});

const IMPORTANT: Collection = {
  id: 2,
  name: "Important",
  state: "open",
  created: 1,
  closed_at: null,
  publish: {},
  ongoing_rel: null,
  members: [
    { drive_id: "deed", path: "40. Family/deed.pdf", is_dir: false, missing: false, quarantined: false, is_link: false, group_id: 11, connected: true, marks: ["important"] },
  ],
  ongoing_status: null,
  summary: "",
  groups: [{ id: 11, collection_id: 2, parent_id: null, name: "Houses", position: 0, summary: "" }],
  parent_id: null,
  path: ["Important"],
  kind: "important",
  position: 0,
};

describe("the Important page and its sidebar row", () => {
  const routes = {
    "GET /api/marks/collection/important": { body: IMPORTANT },
    "GET /api/collections/2": { body: IMPORTANT },
    "GET /api/collections/2/attention": { body: [] },
    "GET /api/collections": { body: [] },
    "GET /api/notes/collection/2": { body: { text: "" } },
    "GET /api/checklist/collection/2": { body: [] },
    "GET /api/files/deed/links": { body: { items: [], collections: [], note: "" } },
    "GET /api/status": { body: { inbox_count: 0, special_folders: { inbox: "##. Organize", ongoing: "##. Ongoing", important: IMP, quarantine: "##. To Delete" } } },
    "GET /api/today": { body: { attention: [], overview: { inbox: 0, trays: [], collections: [] }, unmanaged_important: 2 } },
    "GET /api/trays": { body: { trays: [], errors: [] } },
  };

  it("a sidebar row above Collections leads to the page: groups, no rename, close or parent actions", async () => {
    mockFetch(routes);
    const user = userEvent.setup();
    renderWithProviders(
      <MemoryRouter initialEntries={["/inbox"]}>
        <Sidebar />
        <Routes>
          <Route path="/important" element={<Important today="2026-10-21" />} />
          <Route path="*" element={null} />
        </Routes>
      </MemoryRouter>,
    );
    const nav = screen.getByRole("navigation", { name: "Main" });
    const link = await within(nav).findByRole("link", { name: "Important (1)" });
    expect(link).toHaveAttribute("href", "/important");
    const names = within(nav).getAllByRole("link").map((a) => a.getAttribute("href"));
    expect(names.indexOf("/important")).toBe(names.indexOf("/browse?tree=collections&new=1") + 1); // first in Collections, after the section's "+"
    await user.click(link);
    const page = await screen.findByRole("region", { name: "Important" });
    expect(await within(page).findByRole("heading", { name: "! Important" })).toBeInTheDocument();
    expect(within(page).getAllByText("Houses").length).toBeGreaterThan(0); // its group
    expect(within(page).getByRole("button", { name: "New group" })).toBeInTheDocument();
    expect(within(page).queryByRole("button", { name: "More actions" })).toBeNull(); // rename, move, close
    expect(within(page).getByRole("link", { name: "Convert" })).toHaveAttribute("href", "/important/convert");
    expect(within(page).getByText("2 entries in ##. Important are not in the app yet.")).toBeInTheDocument();
    expect(within(page).getByText(/2 not in the app yet/)).toBeInTheDocument(); // beside the count
    // the selected file's toggles; its row shows its icon
    const selected = within(page).getByRole("complementary", { name: "Selected file" });
    // (the file's actions are the icon rows of its panel)
    expect(within(selected).getByRole("group", { name: "File it" })).toBeInTheDocument();
    expect(await within(page).findByRole("button", { name: "Unmark Important" })).toBeInTheDocument();
    // the ! toggle is the way out: no second "Remove from Important" button
    expect(within(selected).queryByRole("button", { name: /^Remove from Important/ })).not.toBeInTheDocument();
    const memberRow = within(page).getAllByText("deed.pdf").find((el) => el.closest(".member-row"))!;
    // inside the ! Important page the ! on each row would repeat the page: left out
    expect(within(memberRow.closest(".member-row")! as HTMLElement).queryByRole("img", { name: "Important" })).not.toBeInTheDocument();
  });
});
