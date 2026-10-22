import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import type { ConvertPlan, ConvertResult, OngoingEntry, ResolvedOp } from "../api/client";
import { type Call, deferred, mockFetch, renderWithProviders, undoButton } from "../test-utils";
import ConvertOngoing from "./ConvertOngoing";

const ONG = "##. Ongoing";
const base: OngoingEntry = {
  rel: `${ONG}/Sauna`,
  kind: "link",
  target_rel: "40. House/Sauna",
  managed: false,
  suggested_name: "Sauna",
  contents: [],
  problem: null,
  collection_id: null,
  collection_name: null,
  drive_id: null,
  is_dir: false,
  items: [],
  real_files: 0,
  marks: [],
};
// a link to a folder: a collection by default (a link to a single file is starred by default)
const link: OngoingEntry = { ...base, is_dir: true };
const link2: OngoingEntry = { ...base, is_dir: true, rel: `${ONG}/Boat`, suggested_name: "Boat", target_rel: "40. House/Boat" };
const folder: OngoingEntry = { ...base, rel: `${ONG}/Taxes`, kind: "folder", target_rel: null, suggested_name: "Taxes", contents: ["a.pdf", "b‮.pdf"] };
const item = (name: string, drive_id: string | null, is_dir = false, is_link = false, unreadable = false) => ({
  name,
  drive_id,
  is_dir,
  is_link,
  unreadable,
  marks: [] as ("starred" | "important")[],
});
const taxLink: OngoingEntry = { ...base, rel: `${ONG}/Tax 2025.pdf`, suggested_name: "Tax 2025", target_rel: "13. Taxes/2025.pdf", drive_id: "id-tax" };
const legal: OngoingEntry = {
  ...base,
  rel: `${ONG}/Legal`,
  kind: "folder",
  target_rel: null,
  suggested_name: "Legal",
  drive_id: "d-legal",
  is_dir: true,
  contents: ["Deed", "contract.pdf", "new.pdf", "will‮.pdf"],
  items: [item("Deed", "d-deed", true), item("contract.pdf", "id-contract"), item("new.pdf", null), item("will‮.pdf", "id-will", false, true)],
};
const bad: OngoingEntry = { ...base, rel: `${ONG}/Broken`, suggested_name: "Broken", problem: "points outside the archive" };
const managed: OngoingEntry = { ...base, rel: `${ONG}/Legal`, managed: true, suggested_name: "Legal", collection_id: 5, collection_name: "Legal stuff" };

const OPS: ResolvedOp[] = [
  { kind: "unlink_symlink", src: null, dst: `${ONG}/Sauna`, drive_id: null, note: null },
  { kind: "symlink", src: null, dst: `${ONG}/Sauna`, drive_id: null, note: null },
];
const PLAN: ConvertPlan = {
  ops: OPS,
  members: ["40. House/Sauna"],
  notes: [`${ONG}/Sauna is a relative link: after undo the link will be absolute`],
  collection: "Sauna build",
  groups: [""],
  link_names: [""],
  existing: false,
  existing_members: 0,
  fingerprint: "fp1",
};
const RESULT: ConvertResult = {
  batch: { batch_id: "b9", dry_run: false, done: OPS, failed: null, error: null, index_error: null },
  collection_id: 3,
  problems: ["sync problem"],
  sync: null,
};
const STALE = { status: 400, body: { error: "This has changed since the preview. Preview it again.", code: "stale_preview" } };

type Routes = Parameters<typeof mockFetch>[0];

function setup(entries: OngoingEntry[], routes: Routes = {}) {
  const calls = mockFetch({
    "GET /api/ongoing/entries": { body: entries },
    "GET /api/collections": { body: [{ id: 5, name: "Legal Stuff", state: "open", ongoing_rel: null, members: [], files: 4, open_checks: 0 }] },
    "GET /api/folders": { body: ["10. Financial/Taxes"] },
    ...routes,
  });
  const user = userEvent.setup();
  renderWithProviders(
    <MemoryRouter>
      <ConvertOngoing />
    </MemoryRouter>,
  );
  return { calls, user };
}

const posts = (calls: Call[], url: string) => calls.filter((c) => c.method === "POST" && c.url === url);
const row = async (title: string) => (await screen.findByRole("heading", { level: 3, name: new RegExp(title) })).closest("li")!;
const dialog = () => screen.findByRole("dialog");
/** The Undo button of the toast (the converted card has its own). */
const toastUndo = async () => within(await screen.findByRole("status")).findByRole("button", { name: "Undo" });

describe("ConvertOngoing", () => {
  it("lists convertible first, then problems, then managed with a link; those have no actions", async () => {
    setup([managed, bad, link]);
    await screen.findByText(`${ONG}/Sauna`, { exact: false });
    const items = screen.getAllByRole("listitem").filter((li) => li.classList.contains("ongoing-entry"));
    expect(items.map((li) => li.querySelector("h3")?.textContent)).toEqual([
      expect.stringContaining("Sauna"),
      expect.stringContaining("Broken"),
      expect.stringContaining("Legal"),
    ]);
    expect(within(items[1]).getByText(/points outside the archive/)).toBeInTheDocument();
    expect(within(items[2]).getByRole("link", { name: "Legal stuff" })).toHaveAttribute("href", "/collections/5");
    expect(within(items[1]).queryByRole("button")).toBeNull();
    expect(within(items[2]).queryByRole("button")).toBeNull();
  });

  it("a link needs no destination; a folder needs one before Preview enables", async () => {
    const { user } = setup([link, folder]);
    const linkRow = await row("Sauna");
    const folderRow = await row("Taxes");
    expect(within(linkRow).queryByLabelText("Archive folder (required)")).toBeNull();
    expect(within(linkRow).getByRole("button", { name: "Preview" })).toBeEnabled();
    const contents = within(folderRow).getByRole("list", { name: "Contents of Taxes" });
    expect(within(contents).getAllByRole("listitem").map((li) => li.querySelector(".ongoing-item-name")?.textContent)).toEqual([
      "a.pdf",
      "b⟨U+202E⟩.pdf",
    ]);
    const preview = within(folderRow).getByRole("button", { name: "Preview" });
    expect(preview).toBeDisabled();
    expect(preview).toHaveAccessibleDescription("Choose an archive folder");
    expect(within(folderRow).getByLabelText("Or use an existing collection")).toHaveAttribute(
      "placeholder",
      "Type to find a collection",
    );
    expect(within(folderRow).getByRole("button", { name: "Browse folders…" })).toBeInTheDocument();
    await user.type(within(folderRow).getByLabelText("Archive folder (required)"), "10. Financial/Taxes");
    expect(preview).toBeEnabled();
    expect(within(folderRow).queryByText("Choose an archive folder")).toBeNull();
  });

  it("previews a new collection, shows ops, members and notes, and applies exactly the previewed body", async () => {
    const { calls, user } = setup([link], { "POST /api/ongoing/preview": { body: PLAN }, "POST /api/ongoing/convert": { body: RESULT } });
    const name = await screen.findByLabelText("Collection name");
    await user.clear(name);
    await user.type(name, "Sauna build");
    await user.click(screen.getByRole("button", { name: "Preview" }));
    const d = await dialog();
    expect(within(d).getByText("New collection ‘Sauna build’")).toBeInTheDocument();
    expect(within(d).getByText(/after undo the link will be absolute/)).toBeInTheDocument();
    expect(within(d).getByText("40. House/Sauna")).toBeInTheDocument();
    expect(within(d).getByText(/stays; the app now manages this link/)).toBeInTheDocument();
    await user.click(within(d).getByRole("button", { name: "Convert" }));
    await waitFor(() => expect(posts(calls, "/api/ongoing/convert")).toHaveLength(1));
    const body = { rel: link.rel, collection: "Sauna build", destination: null, star: false, to_inbox: false };
    expect(posts(calls, "/api/ongoing/preview")[0].body).toEqual(body);
    expect(posts(calls, "/api/ongoing/convert")[0].body).toEqual({ ...body, fingerprint: "fp1" });
    expect(await screen.findByText(/Converted .*Sauna, but: sync problem/)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: `Converted ${link.rel}` })).toBeInTheDocument();
    await waitFor(() => expect(calls.filter((c) => c.url === "/api/ongoing/entries").length).toBeGreaterThan(1));
  });

  it("says when the name merges into an existing collection, with the resolved name", async () => {
    const merge: ConvertPlan = { ...PLAN, collection: "Legal‮ Stuff", existing: true, existing_members: 4 };
    const { calls, user } = setup([link], { "POST /api/ongoing/preview": { body: merge }, "POST /api/ongoing/convert": { body: RESULT } });
    const name = await screen.findByLabelText("Collection name");
    await user.clear(name);
    await user.type(name, "legal stuff");
    await user.click(screen.getByRole("button", { name: "Preview" }));
    const d = await dialog();
    expect(within(d).getByText("Add to existing collection ‘Legal⟨U+202E⟩ Stuff’ (4 files)")).toBeInTheDocument();
    expect(within(d).queryByText(/New collection/)).toBeNull();
    await user.click(within(d).getByRole("button", { name: "Convert" }));
    await waitFor(() => expect(posts(calls, "/api/ongoing/convert")).toHaveLength(1));
    const body = { rel: link.rel, collection: "legal stuff", destination: null, star: false, to_inbox: false };
    expect(posts(calls, "/api/ongoing/preview")[0].body).toEqual(body);
    expect(posts(calls, "/api/ongoing/convert")[0].body).toEqual({ ...body, fingerprint: "fp1" });
  });

  it("a folder conversion sends its destination in the preview and the apply", async () => {
    const plan = { ...PLAN, collection: "Taxes" };
    const { calls, user } = setup([folder], { "POST /api/ongoing/preview": { body: plan }, "POST /api/ongoing/convert": { body: RESULT } });
    await user.type(await screen.findByLabelText("Archive folder (required)"), "10. Financial/Taxes");
    await user.click(screen.getByRole("button", { name: "Preview" }));
    await user.click(within(await dialog()).getByRole("button", { name: "Convert" }));
    await waitFor(() => expect(posts(calls, "/api/ongoing/convert")).toHaveLength(1));
    const body = { rel: folder.rel, collection: "Taxes", destination: "10. Financial/Taxes", star: false, to_inbox: false };
    expect(posts(calls, "/api/ongoing/preview")[0].body).toEqual(body);
    expect(posts(calls, "/api/ongoing/convert")[0].body).toEqual({ ...body, fingerprint: "fp1" });
  });

  it("choosing an existing collection fills the name and is what gets previewed and applied", async () => {
    const plan = { ...PLAN, collection: "Legal Stuff", existing: true, existing_members: 4 };
    const { calls, user } = setup([link], { "POST /api/ongoing/preview": { body: plan }, "POST /api/ongoing/convert": { body: RESULT } });
    await user.type(await screen.findByLabelText("Or use an existing collection"), "Legal");
    await user.click(await screen.findByRole("option", { name: "Legal Stuff" }));
    expect(screen.getByLabelText("Collection name")).toHaveValue("Legal Stuff");
    await user.click(screen.getByRole("button", { name: "Preview" }));
    await user.click(within(await dialog()).getByRole("button", { name: "Convert" }));
    await waitFor(() => expect(posts(calls, "/api/ongoing/convert")).toHaveLength(1));
    const body = { rel: link.rel, collection: "Legal Stuff", destination: null, star: false, to_inbox: false };
    expect(posts(calls, "/api/ongoing/preview")[0].body).toEqual(body);
    expect(posts(calls, "/api/ongoing/convert")[0].body).toEqual({ ...body, fingerprint: "fp1" });
  });

  it("the existing-collection picker shows the full path; it matches on the last name and on the path", async () => {
    const nested = [
      { id: 1, name: "Houses", state: "open", parent_id: null, path: ["Houses"], ongoing_rel: null, members: [], files: 0, open_checks: 0 },
      { id: 6, name: "2026 Sauna conversion", state: "open", parent_id: 1, path: ["Houses", "2026 Sauna conversion"], ongoing_rel: null, members: [], files: 2, open_checks: 0 },
    ];
    const { user } = setup([link], { "GET /api/collections": { body: nested } });
    const input = await screen.findByLabelText("Or use an existing collection");
    await user.type(input, "sauna conv");
    expect(screen.getAllByRole("option").map((o) => o.textContent)).toEqual(["Houses › 2026 Sauna conversion"]);
    await user.clear(input);
    await user.type(input, "houses");
    expect(screen.getAllByRole("option").map((o) => o.textContent)).toEqual(["Houses", "Houses › 2026 Sauna conversion"]);
    await user.click(screen.getByRole("option", { name: "Houses › 2026 Sauna conversion" }));
    expect(screen.getByLabelText("Collection name")).toHaveValue("2026 Sauna conversion");
  });

  it("Enter in the picker with no exact match says so and changes nothing", async () => {
    const { user } = setup([link]);
    await user.type(await screen.findByLabelText("Or use an existing collection"), "Nope{Enter}");
    expect(screen.getByText("No collection named ‘Nope’")).toBeInTheDocument();
    expect(screen.getByLabelText("Collection name")).toHaveValue("Sauna");
  });

  it("the Undo toast confirms and then posts the undo of the batch that ran, and clears the result", async () => {
    const { calls, user } = setup([link], {
      "POST /api/ongoing/preview": { body: PLAN },
      "POST /api/ongoing/convert": { body: RESULT },
      "POST /api/activity/b9/undo/preview": { body: [] }, "POST /api/activity/b9/undo": { body: { batch_id: "b9", done: OPS, failed: null, error: null, follow_up_error: null } },
    });
    await user.click(await screen.findByRole("button", { name: "Preview" }));
    await user.click(within(await dialog()).getByRole("button", { name: "Convert" }));
    await user.click(await toastUndo());
    const d = await dialog();
    expect(within(d).getByRole("heading", { name: "Undo these changes?" })).toBeInTheDocument();
    expect(posts(calls, "/api/activity/b9/undo")).toHaveLength(0);
    await user.click(await undoButton(d));
    await waitFor(() => expect(posts(calls, "/api/activity/b9/undo")).toHaveLength(1));
    await waitFor(() => expect(screen.queryByRole("heading", { name: `Converted ${link.rel}` })).toBeNull());
  });

  it("a refused undo shows its error and keeps the result", async () => {
    const { user } = setup([link], {
      "POST /api/ongoing/preview": { body: PLAN },
      "POST /api/ongoing/convert": { body: RESULT },
      "POST /api/activity/b9/undo/preview": { body: [] }, "POST /api/activity/b9/undo": { status: 409, body: { error: "changed since the batch ran" } },
    });
    await user.click(await screen.findByRole("button", { name: "Preview" }));
    await user.click(within(await dialog()).getByRole("button", { name: "Convert" }));
    await user.click(await toastUndo());
    await user.click(await undoButton(await dialog()));
    expect(await screen.findByText(/Undo failed: .*changed since the batch ran/)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: `Converted ${link.rel}` })).toBeInTheDocument();
  });

  it("the converted card has its own Undo, which confirms, posts the undo and clears the card", async () => {
    const { calls, user } = setup([link], {
      "POST /api/ongoing/preview": { body: PLAN },
      "POST /api/ongoing/convert": { body: RESULT },
      "POST /api/activity/b9/undo/preview": { body: [] },
      "POST /api/activity/b9/undo": { body: { batch_id: "b9", done: OPS, failed: null, error: null, follow_up_error: null } },
    });
    await user.click(await screen.findByRole("button", { name: "Preview" }));
    await user.click(within(await dialog()).getByRole("button", { name: "Convert" }));
    const card = (await screen.findByRole("heading", { name: `Converted ${link.rel}` })).closest("section")!;
    await user.click(within(card).getByRole("button", { name: "Undo" }));
    const d = await dialog();
    expect(posts(calls, "/api/activity/b9/undo")).toHaveLength(0);
    await user.click(await undoButton(d));
    await waitFor(() => expect(posts(calls, "/api/activity/b9/undo")).toHaveLength(1));
    await waitFor(() => expect(screen.queryByRole("heading", { name: `Converted ${link.rel}` })).toBeNull());
  });

  it("offers no Undo when the batch did nothing", async () => {
    const empty = { ...RESULT, batch: { ...RESULT.batch, done: [] }, problems: [] };
    const { user } = setup([link], { "POST /api/ongoing/preview": { body: PLAN }, "POST /api/ongoing/convert": { body: empty } });
    await user.click(await screen.findByRole("button", { name: "Preview" }));
    await user.click(within(await dialog()).getByRole("button", { name: "Convert" }));
    await screen.findByRole("heading", { name: `Converted ${link.rel}` });
    expect(screen.queryByRole("button", { name: "Undo" })).toBeNull(); // neither toast nor card
  });

  it("a folder can send its files to the inbox instead of one archive folder", async () => {
    const { calls, user } = setup([{ ...folder, real_files: 2 }], {
      "POST /api/ongoing/preview": { body: PLAN },
    });
    const r = await row("Taxes");
    const preview = within(r).getByRole("button", { name: "Preview" });
    expect(within(r).getByLabelText("Move its files to one archive folder")).toBeChecked();
    expect(preview).toBeDisabled();
    await user.click(within(r).getByLabelText("Send its files to the inbox to file one by one"));
    expect(within(r).queryByLabelText("Archive folder (required)")).toBeNull();
    expect(preview).toBeEnabled();
    await user.type(within(r).getByLabelText("Collection name"), "{Control>}a{/Control}Taxes");
    await user.click(preview);
    await waitFor(() => expect(posts(calls, "/api/ongoing/preview")).toHaveLength(1));
    expect(posts(calls, "/api/ongoing/preview")[0].body).toEqual({
      rel: folder.rel,
      collection: "Taxes",
      destination: null,
      star: false,
      to_inbox: true,
    });
  });

  it("a link has no choice of where its files go", async () => {
    setup([link]);
    const r = await row("Sauna");
    expect(within(r).queryByLabelText("Send its files to the inbox to file one by one")).toBeNull();
  });

  it("an edit while the preview is in flight drops that preview", async () => {
    const gate = deferred<void>();
    const { calls, user } = setup([link], {
      "POST /api/ongoing/preview": async () => {
        await gate.promise;
        return { body: PLAN };
      },
    });
    await user.click(await screen.findByRole("button", { name: "Preview" }));
    await waitFor(() => expect(posts(calls, "/api/ongoing/preview")).toHaveLength(1));
    await user.type(screen.getByLabelText("Collection name"), "x");
    gate.resolve();
    await waitFor(() => expect(screen.getByRole("button", { name: "Preview" })).toBeEnabled());
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(posts(calls, "/api/ongoing/convert")).toHaveLength(0);
  });

  it("branches on the stale_preview code (not the text) and offers to preview again", async () => {
    const { calls, user } = setup([link], { "POST /api/ongoing/preview": { body: PLAN }, "POST /api/ongoing/convert": STALE });
    await user.click(await screen.findByRole("button", { name: "Preview" }));
    await user.click(within(await dialog()).getByRole("button", { name: "Convert" }));
    const alert = await screen.findByRole("alert");
    await user.click(within(alert).getByRole("button", { name: "Preview again" }));
    await dialog();
    expect(posts(calls, "/api/ongoing/preview")).toHaveLength(2);
  });

  it("another 400 (even with the same words) does not offer a new preview", async () => {
    const { user } = setup([link], {
      "POST /api/ongoing/preview": { body: PLAN },
      "POST /api/ongoing/convert": { status: 400, body: { error: "changed since preview but not stale" } },
    });
    await user.click(await screen.findByRole("button", { name: "Preview" }));
    await user.click(within(await dialog()).getByRole("button", { name: "Convert" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/not stale/);
    expect(within(alert).queryByRole("button", { name: "Preview again" })).toBeNull();
  });

  it("applies once on a double click", async () => {
    const gate = deferred<void>();
    const { calls, user } = setup([link], {
      "POST /api/ongoing/preview": { body: PLAN },
      "POST /api/ongoing/convert": async () => {
        await gate.promise;
        return { body: RESULT };
      },
    });
    await user.click(await screen.findByRole("button", { name: "Preview" }));
    await user.dblClick(within(await dialog()).getByRole("button", { name: "Convert" }));
    gate.resolve();
    await screen.findByRole("heading", { name: /Converted/ });
    expect(posts(calls, "/api/ongoing/convert")).toHaveLength(1);
  });

  it("while one conversion runs the other rows cannot preview", async () => {
    const gate = deferred<void>();
    const { calls, user } = setup([link, link2], {
      "POST /api/ongoing/preview": { body: PLAN },
      "POST /api/ongoing/convert": async () => {
        await gate.promise;
        return { body: RESULT };
      },
    });
    const first = await row("Sauna");
    const second = await row("Boat");
    await user.click(within(first).getByRole("button", { name: "Preview" }));
    await user.click(within(await dialog()).getByRole("button", { name: "Convert" }));
    await waitFor(() => expect(posts(calls, "/api/ongoing/convert")).toHaveLength(1));
    const other = within(second).getByRole("button", { name: "Preview" });
    expect(other).toBeDisabled();
    await user.click(other);
    expect(posts(calls, "/api/ongoing/preview")).toHaveLength(1);
    gate.resolve();
    await screen.findByRole("heading", { name: /Converted/ });
    await waitFor(() => expect(within(second).getByRole("button", { name: "Preview" })).toBeEnabled());
  });

  it("Skip hides the entry without a request; Show skipped brings it back", async () => {
    const { calls, user } = setup([link, folder]);
    const subtitle = () => document.querySelector(".toolbar-subtitle")?.textContent;
    await user.click(within(await row("Sauna")).getByRole("button", { name: "Skip" }));
    expect(screen.queryByText(link.rel, { exact: false })).toBeNull();
    expect(subtitle()).toBe("1 entry to convert");
    expect(calls.filter((c) => c.method === "POST")).toHaveLength(0);
    await user.click(screen.getByRole("button", { name: "Show skipped (1)" }));
    expect(await screen.findByText(link.rel, { exact: false })).toBeInTheDocument();
    expect(subtitle()).toBe("2 entries to convert"); // the shown skipped entry counts
  });

  it("a failed refetch keeps the list and warns", async () => {
    let n = 0;
    const { user } = setup([link], {
      "GET /api/ongoing/entries": () => (++n === 1 ? { body: [link] } : { status: 500, body: { error: "boom" } }),
      "POST /api/ongoing/preview": { body: PLAN },
      "POST /api/ongoing/convert": { body: RESULT },
    });
    await user.click(await screen.findByRole("button", { name: "Preview" }));
    await user.click(within(await dialog()).getByRole("button", { name: "Convert" }));
    expect(await screen.findByText(/could not be refreshed/i)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: `Converted ${link.rel}` })).toBeInTheDocument();
  });

  it("says which fields are needed: the collection (new or existing) and, for a folder or file, the archive folder", async () => {
    const { user } = setup([link, folder]);
    const linkRow = await row("Sauna");
    const folderRow = await row("Taxes");
    for (const r of [linkRow, folderRow]) {
      expect(within(r).getByRole("group", { name: "Collection: new name or an existing one (one is needed)" })).toBeInTheDocument();
      expect(within(r).getByLabelText("Collection name")).toHaveAttribute("aria-required", "true");
    }
    const destination = within(folderRow).getByLabelText("Archive folder (required)");
    expect(destination).toHaveAttribute("aria-required", "true");
    expect(within(linkRow).queryByText(/\(required\)/)).toBeNull();
    // the reason sits next to the disabled Preview, and names what is missing first
    const name = within(folderRow).getByLabelText("Collection name");
    await user.clear(name);
    const preview = within(folderRow).getByRole("button", { name: "Preview" });
    expect(preview).toBeDisabled();
    expect(preview).toHaveAccessibleDescription("Name the collection or choose an existing one");
    expect(within(folderRow).getByText("Name the collection or choose an existing one")).toBeVisible();
    await user.type(name, "Taxes");
    expect(preview).toHaveAccessibleDescription("Choose an archive folder");
  });

  it("every entry, and every item of a folder entry, has Quick Look, Open and Show in Finder", async () => {
    const { calls, user } = setup([taxLink, legal], {
      "POST /api/files/id-tax/open": { status: 204, body: null },
      "POST /api/files/d-legal/reveal": { status: 204, body: null },
      "POST /api/files/id-will/reveal": { status: 204, body: null },
    });
    const tax = await row("Tax 2025");
    const taxOpen = within(tax).getByRole("group", { name: `Open ${taxLink.rel}` });
    for (const label of ["Quick Look", "Open", "Show in Finder"]) expect(within(taxOpen).getByRole("button", { name: label })).toBeInTheDocument();
    await user.click(within(taxOpen).getByRole("button", { name: "Open" }));
    await waitFor(() => expect(posts(calls, "/api/files/id-tax/open")).toHaveLength(1)); // the link's target

    const folderRow = await row("Legal");
    // a folder is shown in Finder, never opened or looked at
    const legalOpen = within(folderRow).getByRole("group", { name: `Open ${legal.rel}` });
    expect(within(legalOpen).queryByRole("button", { name: "Open" })).toBeNull();
    await user.click(within(legalOpen).getByRole("button", { name: "Show in Finder" }));
    await waitFor(() => expect(posts(calls, "/api/files/d-legal/reveal")).toHaveLength(1));

    const items = within(folderRow).getByRole("list", { name: "Contents of Legal" });
    expect(within(items).getAllByRole("listitem").map((li) => li.querySelector(".ongoing-item-name")?.textContent)).toEqual([
      "Deed",
      "contract.pdf",
      "new.pdf",
      "will⟨U+202E⟩.pdf",
    ]);
    expect(within(within(items).getByRole("group", { name: "Deed" })).queryByRole("button", { name: "Quick Look" })).toBeNull();
    const will = within(items).getByRole("group", { name: "will⟨U+202E⟩.pdf" });
    expect(within(will).getByRole("button", { name: "Open" })).toBeInTheDocument();
    await user.click(within(will).getByRole("button", { name: "Show in Finder" }));
    await waitFor(() => expect(posts(calls, "/api/files/id-will/reveal")).toHaveLength(1));
    // an item that is not in the index yet has no buttons, and says so
    const fresh = within(items).getByText("new.pdf").closest("li")!;
    expect(within(fresh).queryByRole("button")).toBeNull();
    expect(fresh).toHaveTextContent("not indexed yet");

    // Quick Look opens on the item, and moves through every lookable file of the page
    await user.click(within(within(items).getByRole("group", { name: "contract.pdf" })).getByRole("button", { name: "Quick Look" }));
    const look = await screen.findByRole("dialog", { name: "Quick Look: contract.pdf" });
    expect(look).toHaveTextContent("2 of 3");
    await user.keyboard("{ArrowRight}");
    expect(await screen.findByRole("dialog", { name: "Quick Look: will⟨U+202E⟩.pdf" })).toBeInTheDocument();
  });

  it("names the other sections Already managed and Can't be converted", async () => {
    setup([managed, bad, link]);
    expect(await screen.findByRole("heading", { level: 3, name: "Already managed" })).toBeInTheDocument();
    expect(screen.getByText("These are the app's own links and folders; nothing to do")).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 3, name: "Can't be converted" })).toBeInTheDocument();
    expect(screen.queryByText("Not to convert")).toBeNull();
    const managedList = screen.getByRole("list", { name: "Already managed" });
    expect(within(managedList).getByText(managed.rel)).toBeInTheDocument();
    const refused = screen.getByRole("list", { name: "Can't be converted" });
    expect(within(refused).getByText(/points outside the archive/)).toBeInTheDocument();
  });

  it("shows no empty section", async () => {
    setup([link]);
    await row("Sauna");
    expect(screen.queryByRole("heading", { name: "Already managed" })).toBeNull();
    expect(screen.queryByRole("heading", { name: "Can't be converted" })).toBeNull();
  });

  it("lists the first 8 items of a folder, with Show all N and Show fewer", async () => {
    const names = Array.from({ length: 10 }, (_, i) => `n${i}.txt`);
    const big: OngoingEntry = { ...legal, rel: `${ONG}/Big`, suggested_name: "Big", contents: names, items: names.map((n) => item(n, `id-${n}`)) };
    const { user } = setup([big]);
    const r = await row("Big");
    const list = within(r).getByRole("list", { name: "Contents of Big" });
    expect(within(list).getAllByRole("listitem")).toHaveLength(8);
    expect(within(r).getByText("Contains 10 items:")).toBeInTheDocument();
    await user.click(within(r).getByRole("button", { name: "Show all 10" }));
    expect(within(list).getAllByRole("listitem")).toHaveLength(10);
    await user.click(within(r).getByRole("button", { name: "Show fewer" }));
    expect(within(list).getAllByRole("listitem")).toHaveLength(8);
    expect(within(r).getByRole("button", { name: "Show all 10" })).toBeInTheDocument();
  });

  it("an item that cannot be read says so, and has no buttons", async () => {
    const odd: OngoingEntry = { ...legal, contents: ["x.pdf"], items: [item("x.pdf", null, false, false, true)] };
    setup([odd]);
    const x = within(await row("Legal")).getByText("x.pdf").closest("li")!;
    expect(x).toHaveTextContent("can't be read");
    expect(x).not.toHaveTextContent("not indexed yet");
    expect(within(x).queryByRole("button")).toBeNull();
    expect(x).not.toHaveAttribute("data-quicklook");
  });

  it("Space opens Quick Look only on a focused lookable row, never from a button or the page", async () => {
    const { user } = setup([taxLink, legal], { "POST /api/files/id-tax/open": { status: 204, body: null } });
    const folderRow = await row("Legal");
    const items = within(folderRow).getByRole("list", { name: "Contents of Legal" });
    // Space with the focus on the page: nothing
    await user.keyboard(" ");
    expect(screen.queryByRole("dialog")).toBeNull();
    // Space on a row's own button presses that button
    const taxOpen = within(await row("Tax 2025")).getByRole("button", { name: "Open" });
    taxOpen.focus();
    await user.keyboard(" ");
    expect(screen.queryByRole("dialog")).toBeNull();
    // a folder item or a not-indexed one is not a Quick Look row
    expect(within(items).getByText("Deed").closest("li")).not.toHaveAttribute("data-quicklook");
    expect(within(items).getByText("new.pdf").closest("li")).not.toHaveAttribute("tabindex");
    // the focused row: Space looks at that row
    const will = within(items).getByText("will⟨U+202E⟩.pdf").closest("li")!;
    will.focus();
    await user.keyboard(" ");
    expect(await screen.findByRole("dialog", { name: "Quick Look: will⟨U+202E⟩.pdf" })).toHaveTextContent("3 of 3");
  });

  it("Quick Look does not open while a convert call is in flight", async () => {
    const held = deferred<{ body: unknown }>();
    const { user } = setup([taxLink], { "POST /api/ongoing/preview": () => held.promise });
    const r = await row("Tax 2025");
    await user.click(within(r).getByRole("button", { name: "Preview" }));
    await user.click(within(r).getByRole("button", { name: "Quick Look" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    await act(async () => held.resolve({ status: 400, body: { error: "no" } } as never));
    await user.click(within(r).getByRole("button", { name: "Quick Look" }));
    expect(await screen.findByRole("dialog", { name: "Quick Look: 2025.pdf" })).toBeInTheDocument();
  });

  it("a folder (or a link to one) defaults to A collection, a single file to Star it", async () => {
    const file: OngoingEntry = { ...base, rel: `${ONG}/Plan.xlsx`, kind: "file", target_rel: null, suggested_name: "Plan", drive_id: "id-plan" };
    setup([link, folder, taxLink, file]);
    expect(within(await row("Sauna")).getByRole("radio", { name: "A collection" })).toBeChecked();
    expect(within(await row("Taxes")).queryByRole("radio", { name: /Star it/ })).toBeNull();
    expect(within(await row("Tax 2025")).getByRole("radio", { name: /Star it/ })).toBeChecked();
    expect(within(await row("Plan")).getByRole("radio", { name: /Star it/ })).toBeChecked();
  });

  describe("Star it", () => {
    const STAR_PLAN: ConvertPlan = { ...PLAN, collection: "Ongoing", existing: true, notes: [], members: ["13. Taxes/2025.pdf"], link_names: ["Tax 2025.pdf"] };
    const file: OngoingEntry = { ...base, rel: `${ONG}/2026_Plan.xlsx`, kind: "file", target_rel: null, suggested_name: "2026_Plan", drive_id: "id-plan" };

    it("a link is starred: no collection is needed, and the previewed body is applied", async () => {
      const { calls, user } = setup([taxLink], {
        "POST /api/ongoing/preview": { body: STAR_PLAN },
        "POST /api/ongoing/convert": { body: { ...RESULT, problems: [] } },
      });
      const r = await row("Tax 2025");
      // a single file defaults to Star it: no collection form until "A collection" is chosen
      expect(within(r).getByRole("radio", { name: "Star it (★ Starred)" })).toBeChecked();
      expect(within(r).queryByLabelText("Collection name")).toBeNull();
      await user.click(within(r).getByRole("radio", { name: "A collection" }));
      await user.clear(within(r).getByLabelText("Collection name"));
      expect(within(r).getByRole("button", { name: "Preview" })).toBeDisabled(); // a collection needs a name
      await user.click(within(r).getByRole("radio", { name: "Star it (★ Starred)" }));
      expect(within(r).queryByLabelText("Collection name")).toBeNull();
      await user.click(within(r).getByRole("button", { name: "Preview" }));
      const d = await dialog();
      expect(within(d).getByText("Star it: becomes a starred file")).toBeInTheDocument();
      await user.click(within(d).getByRole("button", { name: "Star" }));
      await waitFor(() => expect(posts(calls, "/api/ongoing/convert")).toHaveLength(1));
      const body = { rel: taxLink.rel, collection: "", destination: null, star: true, to_inbox: false };
      expect(posts(calls, "/api/ongoing/preview")[0].body).toEqual(body);
      expect(posts(calls, "/api/ongoing/convert")[0].body).toEqual({ ...body, fingerprint: "fp1" });
    });

    it("a real file needs its archive folder; a real folder cannot be starred", async () => {
      const { calls, user } = setup([file, folder], { "POST /api/ongoing/preview": { body: STAR_PLAN } });
      const f = await row("2026_Plan");
      await user.click(within(f).getByRole("radio", { name: "Star it (★ Starred)" }));
      const preview = within(f).getByRole("button", { name: "Preview" });
      expect(preview).toBeDisabled();
      await user.type(within(f).getByLabelText("Archive folder (required)"), "10. Financial/Taxes");
      await user.click(preview);
      await dialog();
      expect(posts(calls, "/api/ongoing/preview")[0].body).toEqual({
        rel: file.rel,
        collection: "",
        destination: "10. Financial/Taxes",
        star: true,
        to_inbox: false,
      });
      expect(within(await row("Taxes")).queryByRole("radio", { name: /Star it/ })).toBeNull();
    });

    it("a link to a folder can be starred (the server stars its target folder); a real folder cannot", async () => {
      const folderLink: OngoingEntry = { ...base, rel: `${ONG}/Tilly`, suggested_name: "Tilly", target_rel: "40. Family/Tilly", drive_id: "d-tilly", is_dir: true };
      setup([folderLink, folder]);
      expect(within(await row("Tilly")).getByRole("radio", { name: "Star it (★ Starred)" })).toBeInTheDocument();
      expect(within(await row("Taxes")).queryByRole("radio", { name: /Star it/ })).toBeNull();
    });

    it("switching back to a collection after a preview discards it", async () => {
      const { user } = setup([taxLink], { "POST /api/ongoing/preview": { body: STAR_PLAN } });
      const r = await row("Tax 2025");
      await user.click(within(r).getByRole("button", { name: "Preview" })); // starred by default
      await user.click(within(await dialog()).getByRole("button", { name: "Cancel" }));
      await user.click(within(r).getByRole("radio", { name: "A collection" }));
      expect(within(r).getByLabelText("Collection name")).toHaveValue("Tax 2025");
    });
  });

  it("entries and their items show their ★ / ! icons", async () => {
    const starredLink: OngoingEntry = { ...taxLink, marks: ["starred"] };
    const marked: OngoingEntry = { ...legal, items: [{ ...item("contract.pdf", "id-contract"), marks: ["important"] }] , contents: ["contract.pdf"] };
    setup([starredLink, marked]);
    const r = await row("Tax 2025");
    expect(within(r.querySelector("h3")!).getByRole("img", { name: "Starred" })).toBeInTheDocument();
    const l = await row("Legal");
    const contract = within(l).getByText("contract.pdf").closest("li")!;
    expect(within(contract).getByRole("img", { name: "Important" })).toBeInTheDocument();
  });
});
