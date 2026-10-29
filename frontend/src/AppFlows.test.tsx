import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import App from "./App";
import type { DirEntry, ResolvedOp } from "./api/client";
import { type Call, deferred, mockFetch, renderWithProviders, undoButton } from "./test-utils";

// Undo and recovery state live in app-level providers: they survive navigation.

const STATUS = {
  files: 3, indexed: 3, pending: 0, cloud_pending: 0, errors: 0, unsupported: 0, missing: 0,
  inbox_count: 0, rule_errors: [], tray_errors: [], recovery_pending: 0,
};
const A: DirEntry = {
  name: "a.pdf", path: "X/a.pdf", is_dir: false, is_link: false, size: 1, mtime: 1, drive_id: "f1", connected: true, marks: [], open_items: [],
};
const PLAN: ResolvedOp[] = [
  { kind: "quarantine", src: "X/a.pdf", dst: "##. To Delete/X/a.pdf", drive_id: "f1", note: null },
];
const result = (batch_id: string, done: ResolvedOp[] = PLAN) => ({
  batch_id, dry_run: false, done, failed: null, error: null, index_error: null,
});
const ROW = {
  id: 1, batch_id: "b1", seq: 0, kind: "move", src: "in/b.pdf", dst: "Y/b.pdf", drive_id: "d2",
  size: 1, mtime: 1, is_file: true, state: "done", error: null, origin: "ui", undo_of: null,
  created: 1_760_000_000, finished: 1_760_000_001,
};
const ACTIVITY = [{ batch_id: "b1", created: 1_760_000_000, origin: "ui", ops: [ROW], undone: false, is_undo: false }];

/** POSTs under ``prefix``, leaving out the undo previews the confirm fetches. */
const posts = (calls: Call[], prefix: string) =>
  calls.filter((c) => c.method === "POST" && c.url.startsWith(prefix) && !c.url.endsWith("/undo/preview"));

function renderApp(url: string, extra: Parameters<typeof mockFetch>[0] = {}) {
  const calls = mockFetch({
    "GET /api/status": { body: STATUS },
    "GET /api/inbox": { body: [] },
    "GET /api/folders": { body: [] },
    "GET /api/browse": { body: [A] },
    "GET /api/activity": { body: ACTIVITY },
    "GET /api/recovery": { body: [] },
    "POST /api/quarantine": (call) => ({
      body: { ...result((call.body as { dry_run: boolean }).dry_run ? "dry" : "q1"), dry_run: (call.body as { dry_run: boolean }).dry_run },
    }),
    ...extra,
  });
  const user = userEvent.setup();
  renderWithProviders(
    <MemoryRouter initialEntries={[url]}>
      <App />
    </MemoryRouter>,
  );
  return { calls, user };
}

async function markA(user: ReturnType<typeof userEvent.setup>) {
  await user.click(await screen.findByRole("checkbox", { name: "Select a.pdf" }));
  await user.click(screen.getByRole("button", { name: "Move to To Delete" }));
  await user.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Move to To Delete" }));
  return screen.findByRole("button", { name: "Undo" }); // the toast's
}

const nav = (name: string) => within(screen.getByRole("navigation", { name: "Main" })).getByRole("link", { name });

describe("app-level undo", () => {
  it("the toast's Undo still works after navigating away from Browse", async () => {
    const { calls, user } = renderApp("/browse?path=X", {
      "POST /api/activity/q1/undo/preview": {
        body: [{ kind: "move", src: "##. To Delete/X/a.pdf", dst: "X/a.pdf", drive_id: "a", note: null }],
      },
      "POST /api/activity/q1/undo": { body: result("u1", []) },
    });
    await markA(user);
    await user.click(nav("Activity"));
    await screen.findByRole("article", { name: "Batch b1" });
    const toasts = document.querySelector<HTMLElement>(".toasts")!;
    await user.click(within(toasts).getByRole("button", { name: "Undo" }));
    const dialog = await screen.findByRole("dialog");
    await waitFor(() => expect(dialog).toHaveTextContent("##. To Delete/X/a.pdf → X/a.pdf"));
    await user.click(await undoButton(dialog));
    await waitFor(() => expect(posts(calls, "/api/activity/q1/undo")).toHaveLength(1));
  });

  it("an undo started in Browse blocks a second one after navigating", async () => {
    const held = deferred<{ body: unknown }>();
    const { calls, user } = renderApp("/browse?path=X", {
      "POST /api/activity/q1/undo/preview": { body: [] }, "POST /api/activity/q1/undo": () => held.promise,
      "POST /api/activity/b1/undo/preview": { body: [] }, "POST /api/activity/b1/undo": { body: result("u2", []) },
    });
    const toastUndo = await markA(user);
    await user.click(toastUndo);
    await user.click(await undoButton(await screen.findByRole("dialog")));
    await waitFor(() => expect(posts(calls, "/api/activity/q1/undo")).toHaveLength(1));
    await user.click(nav("Activity"));
    const b1 = await screen.findByRole("article", { name: "Batch b1" });
    const undo = within(b1).getByRole("button", { name: "Undo" });
    expect(undo).toBeDisabled();
    act(() => undo.click()); // even a click that reaches it opens nothing new
    expect(screen.getAllByRole("dialog")).toHaveLength(1);
    await act(async () => held.resolve({ body: result("u1", []) }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(posts(calls, "/api/activity/")).toHaveLength(1);
  });
});

describe("app-level recovery", () => {
  it("the recovery result survives navigation", async () => {
    const pending = { ...ROW, id: 9, batch_id: "b5", state: "planned", finished: null };
    const { calls, user } = renderApp("/activity", {
      "GET /api/recovery": { body: [pending] },
      "POST /api/recovery": { body: { entries: [{ ...pending, state: "done" }], index_errors: ["index locked"] } },
    });
    await user.click(await screen.findByRole("button", { name: "Run recovery" }));
    await user.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Run recovery" }));
    expect(await screen.findByText(/Index error: index locked/)).toBeInTheDocument();
    await user.click(nav("Inbox"));
    expect(await screen.findByText(/Index error: index locked/)).toBeInTheDocument();
    await user.click(nav("Activity"));
    expect(await screen.findByText(/Index error: index locked/)).toBeInTheDocument();
    expect(posts(calls, "/api/recovery")).toHaveLength(1);
  });
});
