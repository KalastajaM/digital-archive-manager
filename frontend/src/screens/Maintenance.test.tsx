/** Maintenance: nothing runs until a button is clicked; the duplicate check says what it
 * will read first, shows progress and can be stopped; a group's copy to keep and the copies
 * to remove are chosen, previewed (with what is carried over) and applied as one batch with
 * Undo; the other checks list what they find and act through the existing flows. */
import { cleanup, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import type { DupFile, DupGroup, MaintenanceJob } from "../api/client";
import { maintenancePolling } from "../components/maintenance/useMaintenanceJob";
import { type Call, mockFetch, renderWithProviders } from "../test-utils";
import Maintenance from "./Maintenance";

const KINDS = ["duplicates", "empty_folders", "broken_links", "references", "names", "waiting"];
const posts = (calls: Call[], url: string) => calls.filter((c) => c.method === "POST" && c.url === url);

const file = (id: string, path: string, over: Partial<DupFile> = {}): DupFile => ({
  drive_id: id,
  path,
  name: path.split("/").pop() ?? path,
  size: 2048,
  mtime: 1_700_000_000,
  place: "numbered",
  locked: null,
  why: null,
  ...over,
});
const GROUP: DupGroup = {
  sha256: "aaa",
  size: 2048,
  keep: "k1",
  files: [
    file("k1", "10. Financial/Banks/20230101_bill.pdf"),
    file("d1", "##. Organize/scan.pdf", { place: "inbox" }),
    file("d2", "20. Home/bill copy.pdf", { place: "numbered" }),
  ],
};
const GROUP2: DupGroup = {
  sha256: "bbb",
  size: 10,
  keep: "k2",
  files: [file("k2", "10. Financial/Banks/b.pdf", { size: 10 }), file("e2", "20. Home/b.pdf", { size: 10 })],
};

function job(kind: string, over: Partial<MaintenanceJob> = {}): MaintenanceJob {
  return {
    job_id: `job-${kind}`,
    kind,
    state: "done",
    version: 1,
    done: 0,
    total: 0,
    bytes_done: 0,
    bytes_total: 0,
    current: null,
    elapsed_s: 0.1,
    error: null,
    ...over,
  };
}

const resolveRoute = (call: Call) => {
  const body = call.body as { groups: { keep: string; others: string[] }[]; action: string; carry_over: boolean; dry_run: boolean };
  const done = body.groups.flatMap((g) =>
    g.others.flatMap((id) => [
      { kind: "quarantine", src: `src/${id}`, dst: `##. To Delete/src/${id}`, drive_id: id, note: null },
      ...(body.action === "link" ? [{ kind: "symlink", src: `keep/${g.keep}`, dst: `src/${id}`, drive_id: null, note: null }] : []),
    ]),
  );
  return {
    body: {
      batch_id: body.dry_run ? "dry" : "r1",
      dry_run: body.dry_run,
      done,
      failed: null,
      error: null,
      index_error: null,
      carry_over: body.carry_over
        ? [{ drive_id: "k1", name: "20230101_bill.pdf", tags: ["tax"], collections: ["Tax 2023", "Starred"], notes: ["paid in June"], checklist: [], items: [], sender: "Pohjola", person: null }]
        : [],
      carry_errors: [],
    },
  };
};

type Routes = Parameters<typeof mockFetch>[0];
function setup(extra: Routes = {}, results: Record<string, Partial<MaintenanceJob>> = {}) {
  const started: string[] = [];
  const routes: Routes = {
    "GET /api/maintenance/duplicates/estimate": {
      body: { files: 40, candidates: 12, known: 2, to_read_files: 10, to_read_bytes: 5 * 1024 * 1024 },
    },
    "POST /api/maintenance/jobs": (call) => {
      const kind = (call.body as { kind: string }).kind;
      started.push(kind);
      return { body: job(kind, { state: "running", total: 10, done: 1 }) };
    },
    "POST /api/maintenance/duplicates/resolve": resolveRoute,
    "GET /api/status": { body: { special_folders: { quarantine: "##. To Delete" } } },
    ...extra,
  };
  for (const kind of KINDS) {
    routes[`GET /api/maintenance/jobs/latest/${kind}`] ??= { body: null };
    routes[`GET /api/maintenance/jobs/job-${kind}`] ??= { body: job(kind, results[kind] ?? {}) };
    routes[`POST /api/maintenance/jobs/job-${kind}/stop`] ??= { body: job(kind, { state: "stopped", ...results[kind] }) };
  }
  const calls = mockFetch(routes);
  const user = userEvent.setup();
  renderWithProviders(
    <MemoryRouter>
      <Maintenance />
    </MemoryRouter>,
  );
  return { calls, user, started };
}

const card = (name: string) => screen.getByRole("region", { name });
const withDuplicates = (...groups: DupGroup[]) => ({
  duplicates: {
    duplicates: {
      groups,
      groups_total: groups.length,
      name_groups: [],
      name_groups_total: 0,
      unreadable: [],
      changed: 0,
      read_files: 3,
      reused: 0,
      complete: true,
    },
  },
});

beforeEach(() => {
  maintenancePolling.ms = 5;
});
afterEach(() => {
  maintenancePolling.ms = 700;
  localStorage.clear();
});

describe("Maintenance screen", () => {
  it("starts nothing by itself: every check waits for its button", async () => {
    const { calls } = setup();
    for (const name of ["Duplicates", "Empty folders", "Broken links", "Collections and trays", "File names", "Waiting in To Delete"]) {
      expect(card(name)).toBeInTheDocument();
    }
    await screen.findByText(/Starting reads/);
    expect(calls.filter((c) => c.method === "POST")).toEqual([]);
    expect(screen.getAllByRole("button", { name: /^(Find duplicates|Check)$/ })).toHaveLength(6);
  });

  it("says how much the duplicate check will read, with the Google Drive warning, before it starts", async () => {
    setup();
    const dup = card("Duplicates");
    expect(await within(dup).findByText(/Starting reads/)).toHaveTextContent("Starting reads 10 files, 5,0 MB in all; 2 more already have a stored fingerprint");
    expect(within(dup).getByRole("note")).toHaveTextContent(/online-only in Google Drive for desktop downloads it/);
  });

  it("says when there is nothing to read", async () => {
    setup({
      "GET /api/maintenance/duplicates/estimate": { body: { files: 5, candidates: 3, known: 3, to_read_files: 0, to_read_bytes: 0 } },
    });
    expect(await screen.findByText(/Nothing needs to be read: all 3 files that share a size were read before/)).toBeInTheDocument();
    expect(screen.queryByRole("note")).not.toBeInTheDocument();
  });

  it("shows progress while it runs and Stop ends it", async () => {
    const { calls, user } = setup(
      {
        "GET /api/maintenance/jobs/job-duplicates": { body: job("duplicates", { state: "running", done: 4, total: 10, bytes_done: 1024, bytes_total: 5 * 1024 * 1024, current: "scan.pdf" }) },
      },
      { duplicates: { state: "stopped" } },
    );
    await user.click(await screen.findByRole("button", { name: "Find duplicates" }));
    const progress = await screen.findByRole("progressbar", { name: "Progress" });
    expect(progress).toHaveAttribute("max", "10");
    await waitFor(() => expect(progress).toHaveAttribute("value", "4"));
    expect(card("Duplicates")).toHaveTextContent(/5 of 10 files \(1,0 KB of 5,0 MB\): scan\.pdf/);
    await user.click(within(card("Duplicates")).getByRole("button", { name: "Stop" }));
    await waitFor(() => expect(posts(calls, "/api/maintenance/jobs/job-duplicates/stop")).toHaveLength(1));
    expect(await screen.findByRole("button", { name: "Find duplicates" })).toBeInTheDocument();
  });

  it("leaving the screen stops a running check, so nothing keeps reading in the background", async () => {
    const { calls, user } = setup({
      "GET /api/maintenance/jobs/job-duplicates": { body: job("duplicates", { state: "running", done: 1, total: 10 }) },
    });
    const view = screen.getByRole("button", { name: "Find duplicates" });
    await user.click(view);
    await screen.findByRole("progressbar");
    cleanup();
    await waitFor(() => expect(posts(calls, "/api/maintenance/jobs/job-duplicates/stop")).toHaveLength(1));
  });

  it("opening the screen again shows the latest result of a check", async () => {
    setup(
      { "GET /api/maintenance/jobs/latest/empty_folders": { body: job("empty_folders", { empty_folders: { items: [{ drive_id: "f1", path: "20. Home/Old" }], total: 1 } }) } },
    );
    expect(await screen.findByText("20. Home/Old")).toBeInTheDocument();
    expect(within(card("Empty folders")).getByRole("button", { name: "Check again" })).toBeInTheDocument();
  });

  it("lists the groups with the suggested copy kept, and why a file stays", async () => {
    const locked = { ...GROUP, files: [...GROUP.files.slice(0, 2), file("d2", "20. Home/bill copy.pdf", { locked: "important", why: "It is marked Important, so it stays" })] };
    const { user } = setup({}, withDuplicates(locked));
    await user.click(await screen.findByRole("button", { name: "Find duplicates" }));
    const keep = (await screen.findAllByRole("radio")) as HTMLInputElement[];
    expect(keep.map((r) => r.checked)).toEqual([true, false, false]);
    // a row shows its folder; its name only where it differs from the group's
    const rows = within(card("Duplicates")).getAllByRole("listitem").filter((li) => li.classList.contains("dup-file"));
    expect(rows[0]).toHaveTextContent(/^Keep10\. Financial\/Banks2,0 KB/);
    expect(rows[1]).toHaveTextContent("##. Organizenamed scan.pdf");
    expect(screen.getByText("Important")).toBeInTheDocument();
    const stays = screen.getByRole("checkbox", { name: "Remove 20. Home/bill copy.pdf" });
    expect(stays).toBeDisabled();
    expect(stays.closest("label")).toHaveAttribute("title", "It is marked Important, so it stays");
    expect(screen.getByText("Stays")).toBeInTheDocument();
    expect(screen.getByText("Inbox")).toBeInTheDocument();
  });

  it("previews a replace-with-links batch, shows what is carried over, applies it and offers Undo", async () => {
    const { calls, user } = setup(
      {
        "POST /api/activity/r1/undo/preview": { body: [{ kind: "unlink_symlink", src: null, dst: "##. Organize/scan.pdf", drive_id: null, note: null }] },
      },
      withDuplicates(GROUP),
    );
    await user.click(await screen.findByRole("button", { name: "Find duplicates" }));
    await screen.findAllByRole("radio");
    await user.click(screen.getByRole("button", { name: /Replace them with a link…/ }));
    const dialog = await screen.findByRole("dialog", { name: "Replace 2 duplicates with links?" });
    expect(posts(calls, "/api/maintenance/duplicates/resolve").map((c) => c.body)).toEqual([
      { groups: [{ keep: "k1", others: ["d1", "d2"] }], action: "link", carry_over: true, dry_run: true },
    ]);
    expect(dialog).toHaveTextContent("Move to To Delete");
    expect(dialog).toHaveTextContent("Link");
    expect(dialog).toHaveTextContent("Tags: tax");
    expect(dialog).toHaveTextContent("Collections: Tax 2023, Starred");
    expect(dialog).toHaveTextContent('Note added: "paid in June"');
    expect(dialog).toHaveTextContent("From: Pohjola");
    expect(dialog).toHaveTextContent(/Nothing is deleted/);
    await user.click(within(dialog).getByRole("button", { name: /Replace with links/ }));
    expect(await screen.findByText("Replaced 2 duplicates with links")).toBeInTheDocument();
    expect(posts(calls, "/api/maintenance/duplicates/resolve").map((c) => (c.body as { dry_run: boolean }).dry_run)).toEqual([true, false]);
    await user.click(screen.getByRole("button", { name: "Undo" }));
    expect(await screen.findByRole("dialog", { name: "Undo these changes?" })).toBeInTheDocument();
  });

  it("a different copy to keep, and a copy left out, change the request", async () => {
    const { calls, user } = setup({}, withDuplicates(GROUP));
    await user.click(await screen.findByRole("button", { name: "Find duplicates" }));
    const radios = await screen.findAllByRole("radio");
    await user.click(radios[2]); // keep the copy in 20. Home
    await user.click(screen.getByRole("checkbox", { name: "Remove ##. Organize/scan.pdf" })); // and leave the inbox one
    await user.click(screen.getByRole("button", { name: /Move the other to To Delete/ }));
    const dialog = await screen.findByRole("dialog", { name: "Move 1 duplicate to To Delete?" });
    expect(posts(calls, "/api/maintenance/duplicates/resolve")[0].body).toEqual({
      groups: [{ keep: "d2", others: ["k1"] }],
      action: "quarantine",
      carry_over: true,
      dry_run: true,
    });
    expect(within(dialog).getByRole("button", { name: /Move to To Delete/ })).toHaveClass("danger");
  });

  it("with carry-over unticked the request says so and the preview carries nothing", async () => {
    const { calls, user } = setup({}, withDuplicates(GROUP));
    await user.click(await screen.findByRole("button", { name: "Find duplicates" }));
    await screen.findAllByRole("radio");
    await user.click(screen.getByRole("checkbox", { name: /Also add what the removed copies had/ }));
    await user.click(screen.getAllByRole("button", { name: /Move the others to To Delete/ })[0]);
    const dialog = await screen.findByRole("dialog", { name: "Move 2 duplicates to To Delete?" });
    expect((posts(calls, "/api/maintenance/duplicates/resolve")[0].body as { carry_over: boolean }).carry_over).toBe(false);
    expect(dialog).toHaveTextContent("Nothing is carried over to the kept copies.");
  });

  it("the bulk action covers the ticked groups only", async () => {
    const { calls, user } = setup({}, withDuplicates(GROUP, GROUP2));
    await user.click(await screen.findByRole("button", { name: "Find duplicates" }));
    await screen.findAllByRole("radio");
    await user.click(screen.getByRole("checkbox", { name: "Include 20230101_bill.pdf in the bulk action" }));
    await user.click(screen.getByRole("button", { name: /Move the other copies of the ticked groups/ }));
    await screen.findByRole("dialog", { name: "Move 1 duplicate to To Delete?" });
    expect((posts(calls, "/api/maintenance/duplicates/resolve")[0].body as { groups: unknown[] }).groups).toEqual([
      { keep: "k2", others: ["e2"] },
    ]);
  });

  it("a refused request says why and changes nothing", async () => {
    const { user } = setup(
      { "POST /api/maintenance/duplicates/resolve": { status: 400, body: { error: "20. Home/bill copy.pdf is marked Important, so it is not removed" } } },
      withDuplicates(GROUP2),
    );
    await user.click(await screen.findByRole("button", { name: "Find duplicates" }));
    await screen.findAllByRole("radio");
    await user.click(screen.getByRole("button", { name: /Move the other to To Delete/ }));
    expect(await screen.findByText(/Nothing was changed: 20\. Home\/bill copy\.pdf is marked Important/)).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("lists the same names with other content as versions, for review only", async () => {
    const result = {
      duplicates: {
        ...withDuplicates().duplicates.duplicates,
        name_groups: [{ name: "Statement.pdf", files: [file("v1", "10. Financial/Banks/Statement.pdf"), file("v2", "20. Home/statement.pdf", { size: 4096 })] }],
        name_groups_total: 1,
      },
    };
    const { user } = setup({}, { duplicates: result });
    await user.click(await screen.findByRole("button", { name: "Find duplicates" }));
    expect(await screen.findByText(/Probably versions of a document, not copies/)).toBeInTheDocument();
    const compare = screen.getByRole("link", { name: "Compare Statement.pdf side by side in Browse" });
    expect(compare).toHaveAttribute(
      "href",
      `/browse?${new URLSearchParams({ left: "10. Financial/Banks", right: "20. Home" })}`,
    );
    expect(screen.getAllByRole("link", { name: "Show in Browse" })).toHaveLength(2);
    expect(screen.queryByRole("button", { name: /^(Move|Replace)/ })).not.toBeInTheDocument();
  });
});

describe("The other checks", () => {
  it("empty folders: marks the ticked ones for deletion through the usual preview", async () => {
    const { calls, user } = setup(
      {
        "POST /api/quarantine": (call) => {
          const { drive_ids, dry_run } = call.body as { drive_ids: string[]; dry_run: boolean };
          return { body: { batch_id: dry_run ? "dry" : "q1", dry_run, done: drive_ids.map((id) => ({ kind: "quarantine", src: `20. Home/${id}`, dst: `##. To Delete/20. Home/${id}`, drive_id: id, note: null })), failed: null, error: null, index_error: null } };
        },
      },
      { empty_folders: { empty_folders: { items: [{ drive_id: "f1", path: "20. Home/Old" }, { drive_id: "f2", path: "20. Home/Older" }], total: 2 } } },
    );
    await user.click(within(card("Empty folders")).getByRole("button", { name: "Check" }));
    await user.click(await screen.findByRole("checkbox", { name: "Select all folders" }));
    await user.click(screen.getByRole("checkbox", { name: "Select all folders" })); // all again
    await user.click(screen.getByText("20. Home/Older")); // unticks the second (its label)
    await user.click(screen.getByRole("button", { name: /Mark 1 folder for deletion/ }));
    await screen.findByRole("dialog", { name: "Move to To Delete?" });
    expect(posts(calls, "/api/quarantine")[0].body).toEqual({ drive_ids: ["f1"], dry_run: true });
  });

  it("empty folders: says when there are none", async () => {
    const { user } = setup({}, { empty_folders: { empty_folders: { items: [], total: 0 } } });
    await user.click(within(card("Empty folders")).getByRole("button", { name: "Check" }));
    expect(await within(card("Empty folders")).findByText("No empty folders.")).toBeInTheDocument();
  });

  it("broken links: a link in Ongoing is removed through a preview; elsewhere it goes to To Delete", async () => {
    const { calls, user } = setup(
      {
        "POST /api/maintenance/links/remove": (call) => {
          const { drive_ids, dry_run } = call.body as { drive_ids: string[]; dry_run: boolean };
          return { body: { batch_id: dry_run ? "dry" : "l1", dry_run, done: drive_ids.map(() => ({ kind: "unlink_symlink", src: null, dst: "##. Ongoing/Sauna/dead.pdf", drive_id: null, note: null })), failed: null, error: null, index_error: null } };
        },
      },
      {
        broken_links: {
          broken_links: {
            items: [
              { drive_id: "l1", path: "##. Ongoing/Sauna/dead.pdf", target: "gone/x.pdf", inside: "##. Ongoing" },
              { drive_id: "l2", path: "20. Home/dead.pdf", target: "gone/y.pdf", inside: null },
            ],
            total: 2,
          },
        },
      },
    );
    await user.click(within(card("Broken links")).getByRole("button", { name: "Check" }));
    expect(await screen.findByText("gone/x.pdf")).toBeInTheDocument();
    expect(screen.getByText("kept by the app")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Remove 1 link in Ongoing or Important/ }));
    const dialog = await screen.findByRole("dialog", { name: "Remove broken links?" });
    expect(posts(calls, "/api/maintenance/links/remove")[0].body).toEqual({ drive_ids: ["l1"], dry_run: true });
    expect(dialog).toHaveTextContent("Remove link");
    expect(screen.getByRole("button", { name: /Mark 1 link for deletion/ })).toBeEnabled();
  });

  it("collections and trays: each entry links to its collection or tray", async () => {
    const { user } = setup(
      {},
      {
        references: {
          references: {
            items: [
              { kind: "collection", owner_id: "3", owner_name: "Trip", item_id: null, drive_id: "a", path: "##. To Delete/x.pdf", reason: "in To Delete" },
              { kind: "tray", owner_id: "to-pay", owner_name: "To pay: Water bill", item_id: 7, drive_id: "b", path: null, reason: "missing" },
            ],
            total: 2,
          },
        },
      },
    );
    await user.click(within(card("Collections and trays")).getByRole("button", { name: "Check" }));
    expect(await screen.findByRole("link", { name: "Trip" })).toHaveAttribute("href", "/collections/3");
    expect(screen.getByRole("link", { name: "To pay: Water bill" })).toHaveAttribute("href", "/trays/to-pay");
    expect(screen.getByText("Missing")).toBeInTheDocument();
  });

  it("collections and trays: a missing member says where it was and can be taken out", async () => {
    const { calls, user } = setup(
      { "POST /api/collections/5/members/remove": { body: { collection: { id: 5, name: "Important" }, batch: null, problems: [] } } },
      {
        references: {
          references: {
            items: [
              { kind: "collection", owner_id: "5", owner_name: "Important", item_id: null, drive_id: "gone", path: "20. Home/deed.pdf", reason: "missing" },
              { kind: "collection", owner_id: "5", owner_name: "Important", item_id: null, drive_id: "lost", path: null, reason: "missing" },
            ],
            total: 2,
          },
        },
      },
    );
    const refs = card("Collections and trays");
    await user.click(within(refs).getByRole("button", { name: "Check" }));
    expect(await within(refs).findByText("20. Home/deed.pdf")).toBeInTheDocument();
    expect(within(refs).queryByText("lost")).not.toBeInTheDocument(); // no raw id
    expect(within(refs).getByText(/the app no longer knows where it was/)).toBeInTheDocument();
    await user.click(within(refs).getAllByRole("button", { name: "Take out" })[0]);
    await waitFor(() => expect(within(refs).queryByText("20. Home/deed.pdf")).not.toBeInTheDocument());
    expect(posts(calls, "/api/collections/5/members/remove")[0].body).toEqual({ drive_id: "gone" });
    expect(within(refs).getByText("1 entry")).toBeInTheDocument();
  });

  it("file names: Rename goes through the previewed rename with the suggestion", async () => {
    const { calls, user } = setup(
      {
        "POST /api/browse/rename/preview": { body: [{ kind: "rename", src: "10. Financial/Banks/bill.pdf", dst: "10. Financial/Banks/20210304_bill.pdf", drive_id: "n1", note: null }] },
      },
      {
        names: {
          names: {
            items: [
              { drive_id: "n1", path: "10. Financial/Banks/bill.pdf", name: "bill.pdf", folder: "10. Financial/Banks", suggestion: "20210304_bill.pdf" },
              { drive_id: "n2", path: "10. Financial/Banks/x.pdf", name: "x.pdf", folder: "10. Financial/Banks", suggestion: null },
            ],
            total: 2,
          },
        },
      },
    );
    await user.click(within(card("File names")).getByRole("button", { name: "Check" }));
    const rename = await screen.findAllByRole("button", { name: "Rename…" });
    expect(rename[1]).toBeDisabled();
    expect(screen.getByText("No date known")).toBeInTheDocument();
    await user.click(rename[0]);
    await screen.findByRole("dialog", { name: /Rename to 20210304_bill\.pdf\?/ });
    expect(posts(calls, "/api/browse/rename/preview")[0].body).toEqual({ drive_id: "n1", name: "20210304_bill.pdf", folder: "10. Financial/Banks" });
  });

  it("waiting in To Delete: the days are editable, the total is shown and the owner empties it himself", async () => {
    const { calls, user } = setup(
      {},
      {
        waiting: {
          waiting: {
            days: 14,
            items: [{ drive_id: "w1", path: "##. To Delete/old.pdf", size: 2048, since: 1_700_000_000, days: 40, approximate: false }],
            total: 1,
            total_size: 2048,
            in_to_delete: 3,
            in_to_delete_size: 9000,
          },
        },
      },
    );
    const waiting = card("Waiting in To Delete");
    expect(waiting).toHaveTextContent(/The app never empties To Delete: when you are sure, empty it yourself in Finder/);
    const days = within(waiting).getByRole("spinbutton", { name: "Days waiting" });
    expect(days).toHaveValue(30);
    await user.clear(days);
    await user.type(days, "14");
    await user.click(within(waiting).getByRole("button", { name: "Check" }));
    expect(posts(calls, "/api/maintenance/jobs").map((c) => c.body)).toEqual([{ kind: "waiting", days: 14 }]);
    expect(await within(waiting).findByText(/has waited longer than 14 days/)).toHaveTextContent(
      "1 file (2,0 KB) has waited longer than 14 days.",
    );
    expect(within(waiting).getByRole("link", { name: "Open To Delete in Browse" })).toHaveAttribute("href", `/browse?${new URLSearchParams({ path: "##. To Delete" })}`);
  });

  it("an invalid number of days starts nothing", async () => {
    const { calls, user } = setup();
    const waiting = card("Waiting in To Delete");
    const days = within(waiting).getByRole("spinbutton", { name: "Days waiting" });
    await user.clear(days);
    await user.click(within(waiting).getByRole("button", { name: "Check" }));
    expect(posts(calls, "/api/maintenance/jobs")).toEqual([]);
  });
});

describe("Maintenance: folding and Reset", () => {
  const found = { empty_folders: { empty_folders: { items: [{ drive_id: "f1", path: "20. Home/Old" }], total: 1 } } };

  it("folds a card to one line, remembered, and Collapse all / Expand all fold every card", async () => {
    const { user } = setup({ "GET /api/maintenance/jobs/latest/empty_folders": { body: job("empty_folders", found.empty_folders) } });
    expect(await within(card("Empty folders")).findByText("20. Home/Old")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Collapse Empty folders" }));
    expect(within(card("Empty folders")).getByText("1 empty folder")).toBeInTheDocument();
    expect(within(card("Empty folders")).queryByText("20. Home/Old")).not.toBeInTheDocument();
    expect(within(card("Broken links")).getByRole("button", { name: "Check" })).toBeInTheDocument();
    expect(localStorage.getItem("dam.maintenance.folded.v1")).toBe('["empty_folders"]');

    await user.click(screen.getByRole("button", { name: "Collapse all" }));
    expect(screen.queryByRole("button", { name: "Check" })).not.toBeInTheDocument();
    expect(within(card("Broken links")).getByText("Not checked yet.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Expand all" }));
    expect(within(card("Empty folders")).getByText("20. Home/Old")).toBeInTheDocument();
    expect(localStorage.getItem("dam.maintenance.folded.v1")).toBeNull();
  });

  it("Reset forgets one check's result; Reset all forgets every one", async () => {
    const { calls, user } = setup({
      "GET /api/maintenance/jobs/latest/empty_folders": { body: job("empty_folders", found.empty_folders) },
      "DELETE /api/maintenance/jobs": { body: { forgotten: 1 } },
    });
    const folders = card("Empty folders");
    expect(await within(folders).findByText("20. Home/Old")).toBeInTheDocument();
    expect(within(card("Broken links")).getByRole("button", { name: "Reset Broken links" })).toBeDisabled();
    await user.click(within(folders).getByRole("button", { name: "Reset Empty folders" }));
    expect(within(folders).queryByText("20. Home/Old")).not.toBeInTheDocument();
    expect(within(folders).getByRole("button", { name: "Check" })).toBeInTheDocument();
    const deletes = () => calls.filter((c) => c.method === "DELETE").map((c) => c.url);
    expect(deletes()).toEqual(["/api/maintenance/jobs?kind=empty_folders"]);

    await user.click(screen.getByRole("button", { name: "Reset all" }));
    await waitFor(() => expect(deletes()).toEqual(["/api/maintenance/jobs?kind=empty_folders", "/api/maintenance/jobs"]));
  });
});
