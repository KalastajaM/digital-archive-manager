import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import App from "./App";
import { mockFetch, renderWithProviders } from "./test-utils";

const STATUS = {
  files: 10,
  indexed: 8,
  pending: 1,
  cloud_pending: 0,
  errors: 1,
  unsupported: 0,
  missing: 0,
  inbox_count: 3,
  rule_errors: [],
  tray_errors: [],
  recovery_pending: 0,
  archive_available: true,
};

const TODAY = {
  attention: [],
  overview: { inbox: 3, trays: [], collections: [] },
  unmanaged_ongoing: 0,
  ongoing_sync_failure: null,
  reminders: { last_run: null, errors: {}, skipped: null },
  tray_errors: [],
  inbox_stats: { count: 3, oldest_days: 2, this_week: 3, last_week: 0, older: 0, overdue: 0 },
  found: [],
  open_items: [],
};

const renderApp = (url = "/") =>
  renderWithProviders(
    <MemoryRouter initialEntries={[url]}>
      <App />
    </MemoryRouter>,
  );

const BASE = {
  "GET /api/inbox": { body: [] },
  "GET /api/folders": { body: [] },
  "GET /api/today": { body: TODAY },
  "GET /api/trays": { body: { trays: [], errors: [] } },
  "GET /api/collections": { body: [] },
};

describe("App shell", () => {
  it("the error count in the status foot is a button that opens the index errors sheet", async () => {
    mockFetch({
      "GET /api/status": { body: STATUS },
      "GET /api/index/errors": {
        body: {
          rows: [{ drive_id: "e1", path: "X/bad.pdf", name: "bad.pdf", state: "error", reason: "damaged", retry_at: null }],
          total: 1,
          unsupported_by_type: [],
        },
      },
      ...BASE,
    });
    renderApp();
    const user = userEvent.setup();
    const foot = await screen.findByTestId("status-line");
    await user.click(await within(foot).findByRole("button", { name: /1 error/ }));
    const dialog = await screen.findByRole("dialog", { name: "Index" });
    expect(dialog.closest("p")).toBeNull(); // a sibling of the status line, not inside it
    expect(await within(dialog).findByText("damaged")).toBeInTheDocument();
  });

  it("shows the page 1 progress in the status line while it is not complete, and hides it when it is", async () => {
    const page1 = (read: number) => ({ read, total: 10875, backfill: true, blocked: [], rate_per_min: null });
    mockFetch({ "GET /api/status": { body: { ...STATUS, page1: page1(1240) } }, ...BASE });
    const first = renderApp();
    await waitFor(() =>
      expect(screen.getByTestId("status-line")).toHaveTextContent(
        "3 in inbox · 8 searchable · page 1 read 1 240 of 10 875 · 1 waiting · 1 error",
      ),
    );
    first.unmount();
    mockFetch({ "GET /api/status": { body: { ...STATUS, page1: page1(10875) } }, ...BASE });
    renderApp();
    await waitFor(() => expect(screen.getByTestId("status-line")).toHaveTextContent("3 in inbox · 8 searchable · 1 waiting"));
    expect(screen.getByTestId("status-line")).not.toHaveTextContent("page 1");
  });

  it("shows the sidebar and the status line in its foot, no recovery banner", async () => {
    mockFetch({
      "GET /api/status": { body: STATUS },
      ...BASE,
    });
    renderApp();
    await waitFor(() =>
      expect(screen.getByTestId("status-line")).toHaveTextContent("3 in inbox · 8 searchable · 1 waiting · 1 error"),
    );
    const nav = screen.getByRole("navigation", { name: "Main" });
    await within(nav).findByRole("link", { name: "Inbox (3)" });
    const name = (a: HTMLElement) => a.getAttribute("aria-label") ?? a.textContent;
    expect(within(nav).getAllByRole("link").map((a) => [name(a), a.getAttribute("href")])).toEqual([
      ["Today", "/"],
      ["Inbox (3)", "/inbox"],
      ["Browse", "/browse"],
      ["Trays", "/trays"],
      ["Collections", "/collections"],
      ["Important", "/important"],
      ["Starred", "/starred"],
      ["Tags", "/tags"],
      ["Ask", "/ask"],
      ["Activity", "/activity"],
      ["Settings", "/settings"],
      ["Help", "/help"],
    ]);
    expect(within(nav).getByRole("link", { name: "Today" })).toHaveAttribute("aria-current", "page");
    expect(await screen.findByRole("heading", { level: 1, name: /^Good (morning|afternoon|evening)$/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Run recovery" })).not.toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Archive unavailable" })).not.toBeInTheDocument();
  });

  it("routes /settings to the Filing codes section", async () => {
    mockFetch({
      "GET /api/status": { body: STATUS },
      ...BASE,
      "GET /api/filing-codes": { body: { codes: [], problems: [], warnings: [] } },
      "GET /api/filing-codes/folders": { body: { missing: [], stray: [] } },
    });
    renderApp("/settings");
    expect(await screen.findByRole("region", { name: "Filing codes" })).toBeInTheDocument();
  });

  it("keeps the inbox at /inbox, routes the screens", async () => {
    mockFetch({ "GET /api/status": { body: STATUS }, ...BASE });
    const { unmount } = renderApp("/inbox");
    expect(await screen.findByText("The inbox is empty.")).toBeInTheDocument();
    unmount();
    const trays = renderApp("/trays");
    expect(await screen.findByText("No trays are set up.")).toBeInTheDocument();
    trays.unmount();
    const collections = renderApp("/collections");
    expect(await screen.findByText("No open collections.")).toBeInTheDocument();
    collections.unmount();
    mockFetch({ "GET /api/status": { body: STATUS }, "GET /api/ongoing/entries": { body: [] }, ...BASE });
    renderApp("/ongoing");
    expect(await screen.findByRole("heading", { name: "Convert ##. Ongoing" })).toBeInTheDocument();
    expect(await screen.findByText("Nothing left to convert.")).toBeInTheDocument();
  });

  it("the status badge counts skipped tray files", async () => {
    mockFetch({
      "GET /api/status": { body: { ...STATUS, tray_errors: [{ file: "bad.yaml", message: "line 1: id: required" }] } },
      ...BASE,
    });
    renderApp();
    await screen.findByText(/1 tray file errors/);
    const badge = screen.getByTestId("status-line");
    expect(badge).toHaveAttribute("title", "bad.yaml: line 1: id: required");
  });

  it("shows a banner when the archive folder is not available", async () => {
    mockFetch({
      "GET /api/status": { body: { ...STATUS, archive_available: false } },
      ...BASE,
    });
    renderApp();
    const banner = await screen.findByRole("region", { name: "Archive unavailable" });
    expect(banner).toHaveTextContent(/archive folder is not available/i);
    expect(banner).toHaveTextContent(/Google Drive/);
  });

  it("offers recovery behind a confirm when operations were interrupted and shows the result", async () => {
    const calls = mockFetch({
      "GET /api/status": { body: { ...STATUS, recovery_pending: 2 } },
      ...BASE,
      "POST /api/recovery": {
        body: {
          entries: [
            {
              id: 1, batch_id: "b", seq: 0, kind: "move", src: "a.pdf", dst: "X/a.pdf",
              drive_id: "d", size: 1, mtime: 1, is_file: true, state: "done", error: null,
              origin: "ui", undo_of: null, created: 1, finished: 2,
            },
          ],
          index_errors: ["index locked"],
        },
      },
    });
    const user = userEvent.setup();
    renderApp();
    await user.click(await screen.findByRole("button", { name: "Run recovery" }));
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent(/moves, renames or deletes no files/);
    expect(calls.filter((c) => c.url === "/api/recovery")).toHaveLength(0);
    await user.click(within(dialog).getByRole("button", { name: "Run recovery" }));
    expect(await screen.findByText(/Index error: index locked/)).toBeInTheDocument();
    expect(screen.getByText(/done move/)).toBeInTheDocument();
    await waitFor(() =>
      expect(calls.filter((c) => c.method === "POST" && c.url === "/api/recovery")).toHaveLength(1),
    );
    const post = calls.find((c) => c.url === "/api/recovery")!;
    expect(post.headers["Content-Type"]).toBe("application/json");
    expect(post.credentials).toBe("same-origin");
  });
});
