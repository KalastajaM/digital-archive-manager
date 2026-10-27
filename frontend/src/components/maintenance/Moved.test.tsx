/** "Moved outside dam": the pairs are listed with what would move, an ambiguous one is only
 * listed, Reconnect previews first and then applies, and Undo in its message puts it back. */
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it } from "vitest";
import type { MaintenanceJob, MovedPair } from "../../api/client";
import { type Call, mockFetch, renderWithProviders } from "../../test-utils";
import { Moved, movesText } from "./Moved";
import { maintenancePolling } from "./useMaintenanceJob";

const pair = (old: string, now: string, over: Partial<MovedPair> = {}): MovedPair => ({
  old_id: `local:${old}`,
  old_path: `10. Financial/${old}.pdf`,
  new_id: `local:${now}`,
  new_path: `20. Home/${now}.pdf`,
  size: 2048,
  same_ext: true,
  ambiguous: false,
  moves: { tags: 2, collections: 1 },
  ...over,
});

const PAIRS = [pair("a", "a2"), pair("b", "b2", { same_ext: false, moves: { note: 1 } }), pair("c", "c2", { ambiguous: true })];

function job(moved: MaintenanceJob["moved"]): MaintenanceJob {
  return {
    job_id: "job-moved",
    kind: "moved",
    state: "done",
    version: 1,
    done: 0,
    total: 0,
    bytes_done: 0,
    bytes_total: 0,
    current: null,
    elapsed_s: 0.1,
    error: null,
    moved,
  };
}

const reconnects = (calls: Call[]) => calls.filter((c) => c.method === "POST" && c.url === "/api/maintenance/moved/reconnect");

function setup(items: MovedPair[] = PAIRS, extra = {}) {
  const calls = mockFetch({
    "GET /api/maintenance/jobs/latest/moved": { body: job({ items, total: items.length, unhashed: 1, unreadable: 0, complete: true }) },
    "GET /api/maintenance/jobs/job-moved": { body: job({ items: [], total: 0, unhashed: 0, unreadable: 0, complete: true }) },
    "GET /api/maintenance/ignored": { body: [] },
    "POST /api/maintenance/moved/reconnect": (call: Call) => {
      const body = call.body as { pairs: { old: string; new: string }[]; dry_run: boolean };
      const chosen = PAIRS.filter((p) => body.pairs.some((c) => c.old === p.old_id));
      return { body: { dry_run: body.dry_run, pairs: chosen, errors: [], undo_id: body.dry_run ? null : "u1" } };
    },
    ...extra,
  });
  const user = userEvent.setup();
  renderWithProviders(
    <MemoryRouter>
      <Moved />
    </MemoryRouter>,
  );
  return { calls, user };
}

beforeEach(() => {
  maintenancePolling.ms = 5;
});

describe("movesText", () => {
  it("names what moves in words", () => {
    expect(movesText({ tags: 1 })).toBe("1 tag");
    expect(movesText({ tags: 2, collections: 1, note: 1 })).toBe("2 tags, 1 collection and the note");
  });
});

describe("Moved outside dam", () => {
  it("lists each pair with what moves; an ambiguous one has no Reconnect and no tick", async () => {
    setup();
    const list = await screen.findByRole("list");
    const rows = within(list).getAllByRole("listitem");
    expect(rows).toHaveLength(3);
    expect(rows[0]).toHaveTextContent("10. Financial/a.pdf is now 20. Home/a2.pdf");
    expect(rows[0]).toHaveTextContent("Moves 2 tags and 1 collection.");
    expect(within(rows[1]).getByText("Extension changed")).toBeInTheDocument();
    expect(within(rows[2]).getByText("More than one match")).toBeInTheDocument();
    expect(within(rows[2]).queryByRole("checkbox")).not.toBeInTheDocument();
    expect(within(rows[2]).queryByRole("button", { name: "Reconnect…" })).not.toBeInTheDocument();
    expect(screen.getByText(/1 missing file with tags or other things was never read/)).toBeInTheDocument();
  });

  it("previews the chosen pairs, applies them, and Undo puts them back", async () => {
    const { calls, user } = setup(PAIRS, {
      "POST /api/maintenance/moved/undo": { body: { dry_run: false, pairs: PAIRS.slice(0, 2), errors: [], undo_id: null } },
    });
    await screen.findByRole("list");
    await user.click(screen.getByRole("button", { name: "Reconnect 2 files…" }));
    const sheet = await screen.findByRole("dialog", { name: "Reconnect 2 files?" });
    expect(within(sheet).getByText(/Undo in\s+the message afterwards/)).toBeInTheDocument();
    expect(within(sheet).getByText("Moves the note.")).toBeInTheDocument();
    expect(reconnects(calls)).toHaveLength(1);
    expect(reconnects(calls)[0].body).toEqual({
      pairs: [
        { old: "local:a", new: "local:a2" },
        { old: "local:b", new: "local:b2" },
      ],
      dry_run: true,
    });
    await user.click(within(sheet).getByRole("button", { name: "Reconnect" }));
    expect(await screen.findByText("Reconnected 2 files")).toBeInTheDocument();
    expect(reconnects(calls)[1].body).toMatchObject({ dry_run: false });
    await user.click(screen.getByRole("button", { name: "Undo" }));
    expect(await screen.findByText("Put 2 files back as they were")).toBeInTheDocument();
    const undos = calls.filter((c) => c.method === "POST" && c.url === "/api/maintenance/moved/undo");
    expect(undos.map((c) => c.body)).toEqual([{ undo_id: "u1" }]);
  });

  it("reconnects one pair from its row, and Cancel changes nothing", async () => {
    const { calls, user } = setup();
    const list = await screen.findByRole("list");
    const [first] = within(list).getAllByRole("listitem");
    await user.click(within(first).getByRole("button", { name: "Reconnect…" }));
    const sheet = await screen.findByRole("dialog", { name: "Reconnect 1 file?" });
    await user.click(within(sheet).getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(reconnects(calls).map((c) => (c.body as { dry_run: boolean }).dry_run)).toEqual([true]);
  });

  it("says why a reconnect was refused", async () => {
    const { user } = setup(PAIRS, {
      "POST /api/maintenance/moved/reconnect": { status: 400, body: { error: "20. Home/a2.pdf has changed since the last scan" } },
    });
    await screen.findByRole("list");
    await user.click(screen.getByRole("button", { name: "Reconnect 2 files…" }));
    expect(await screen.findByText(/Not reconnected: .*has changed since the last scan/)).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("ignores a pair by its two ids", async () => {
    const { calls, user } = setup(PAIRS, {
      "POST /api/maintenance/ignored": { body: { id: 1, kind: "moved", key: "local:a>local:a2", label: "x", created: 1 } },
    });
    await screen.findByRole("list");
    await user.click(screen.getByRole("button", { name: "Ignore 20. Home/a2.pdf" }));
    await waitFor(() => expect(calls.some((c) => c.url === "/api/maintenance/ignored" && c.method === "POST")).toBe(true));
    const sent = calls.find((c) => c.url === "/api/maintenance/ignored" && c.method === "POST");
    expect(sent?.body).toMatchObject({ kind: "moved", key: "local:a>local:a2" });
  });
});
