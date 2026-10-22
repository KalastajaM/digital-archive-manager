import { act, renderHook, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import { openViewer, publishSelection, resetSelectionChannel, useSelectionFollower } from "../selection";
import { type Call, IMPORTANT_REFUSED, mockFetch, quarantineRoute, renderWithProviders, undoButton } from "../test-utils";

/** An in-memory BroadcastChannel (jsdom has none): a message reaches every other open
 * channel of the same name, never the sender. */
class FakeChannel {
  static open: FakeChannel[] = [];
  onmessage: ((e: MessageEvent) => void) | null = null;
  constructor(public name: string) {
    FakeChannel.open.push(this);
  }
  postMessage(data: unknown) {
    for (const c of FakeChannel.open) {
      if (c !== this && c.name === this.name) c.onmessage?.(new MessageEvent("message", { data }));
    }
  }
  close() {
    FakeChannel.open = FakeChannel.open.filter((c) => c !== this);
  }
}

// Each test is a fresh page: the main window's channel and its selection are reset, and
// no channel of an earlier test is still open.
beforeEach(() => {
  resetSelectionChannel();
  FakeChannel.open = [];
  vi.stubGlobal("BroadcastChannel", FakeChannel);
});
afterEach(() => {
  resetSelectionChannel();
  FakeChannel.open = [];
});

function record(id: string, name: string) {
  return {
    drive_id: id,
    path: `20. Health/${name}`,
    name,
    ext: "pdf",
    is_dir: false,
    is_link: false,
    link_target: null,
    size: 1,
    mtime: 1,
    sha256: null,
    doc_date: null,
    index_state: "indexed",
    retry_at: null,
    attempts: 0,
    missing: false,
    last_seen: null,
    parked_at: null,
  };
}

const NO_LINKS = { body: { items: [], collections: [], note: "" } };

function api() {
  return mockFetch({
    "GET /api/files/d1": { body: { record: record("d1", "Kotihoito.pdf"), tags: [] } },
    "GET /api/files/d2": { body: { record: record("d2", "Sähkö.pdf"), tags: [] } },
    "GET /api/files/d3": { body: { record: record("d3", "Vesi.pdf"), tags: [] } },
    "GET /api/files/d1/links": NO_LINKS,
    "GET /api/files/d2/links": NO_LINKS,
    "GET /api/files/d3/links": NO_LINKS,
    "GET /api/inbox": { body: [] },
  });
}

const renderViewer = (url = "/viewer/d1") =>
  renderWithProviders(
    <MemoryRouter initialEntries={[url]}>
      <App />
    </MemoryRouter>,
  );

const title = () => screen.getByRole("banner").querySelector("h2")?.textContent;

describe("viewer window", () => {
  it("shows the document without the sidebar: preview, details and the follow toggle", async () => {
    const calls = api();
    renderViewer();
    await waitFor(() => expect(title()).toBe("Kotihoito.pdf"));
    expect(screen.queryByRole("navigation", { name: "Main" })).not.toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Page 1" })).toHaveAttribute(
      "src",
      expect.stringContaining("/api/files/d1/page/1.png"),
    );
    const details = screen.getByRole("region", { name: "Details" });
    expect(within(details).getByText("20. Health")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Follow selection", pressed: true })).toBeInTheDocument();
    // No "Open in window" inside the window itself, and no status polling.
    expect(screen.queryByRole("button", { name: "Open in window" })).not.toBeInTheDocument();
    expect(calls.some((c) => c.url.startsWith("/api/status"))).toBe(false);
  });

  it("a link shows what it links to, without Go to target (this window has no Browse)", async () => {
    const link = { ...record("l1", "deed"), ext: null, is_link: true };
    mockFetch({
      "GET /api/files/l1": {
        body: { record: link, tags: [], link_target_id: "t1", link_target_path: "20. Home/deed.pdf", link_target_inside: true },
      },
      "GET /api/files/l1/links": NO_LINKS,
      "GET /api/inbox": { body: [] },
    });
    renderViewer("/viewer/l1");
    expect(await screen.findByText("20. Home/deed.pdf")).toBeInTheDocument();
    expect(await screen.findByRole("img", { name: "Page 1" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Go to target" })).not.toBeInTheDocument();
  });

  it("follows the selection published by the main window until pinned", async () => {
    api();
    const user = userEvent.setup();
    renderViewer();
    await waitFor(() => expect(title()).toBe("Kotihoito.pdf"));
    act(() => publishSelection("d2"));
    await waitFor(() => expect(title()).toBe("Sähkö.pdf"));

    await user.click(screen.getByRole("button", { name: "Follow selection" }));
    expect(screen.getByRole("button", { name: "Follow selection", pressed: false })).toBeInTheDocument();
    expect(screen.getByText("Pinned")).toBeInTheDocument();
    act(() => publishSelection("d3"));
    await new Promise((r) => setTimeout(r, 20));
    expect(title()).toBe("Sähkö.pdf");

    // Following again catches up with the main window's current selection.
    await user.click(screen.getByRole("button", { name: "Follow selection" }));
    await waitFor(() => expect(title()).toBe("Vesi.pdf"));
  });

  it("says so when the file is not known", async () => {
    vi.stubGlobal("BroadcastChannel", undefined); // nothing to follow: it stays on zz
    mockFetch({ "GET /api/files/zz": { status: 404, body: { error: "unknown file" } } });
    renderViewer("/viewer/zz");
    expect(await screen.findByRole("alert")).toHaveTextContent("unknown file");
  });

  it("has the ★ and ! toggles of its document (marks from its record)", async () => {
    mockFetch({
      "GET /api/files/d1": { body: { record: { ...record("d1", "Kotihoito.pdf"), marks: ["important"] }, tags: [] } },
      "GET /api/files/d1/links": NO_LINKS,
      "GET /api/inbox": { body: [] },
      "POST /api/marks/star": { body: { collection: { id: 1, members: [], groups: [] }, batch: null, problems: [], ongoing_status: null } },
    });
    const user = userEvent.setup();
    renderViewer();
    const bar = screen.getByRole("banner");
    expect(await within(bar).findByRole("button", { name: "Important (click to unmark)" })).toBeInTheDocument();
    await user.click(within(bar).getByRole("button", { name: "Star" }));
    expect(await within(bar).findByRole("button", { name: "Starred (click to unstar)" })).toBeInTheDocument();
  });
});

describe("Trash in the viewer", () => {
  const quarantines = (calls: Call[]) => calls.filter((c) => c.url === "/api/quarantine").map((c) => c.body);
  const routes = () => ({
    "GET /api/files/d1": { body: { record: record("d1", "Kotihoito.pdf"), tags: [] } },
    "GET /api/files/d1/links": NO_LINKS,
    "GET /api/inbox": { body: [] },
  });

  it("the bin (and ⌘⌫, never a plain ⌫) move this document to ##. To Delete through the confirm; Undo restores", async () => {
    const calls = mockFetch({
      ...routes(),
      "POST /api/quarantine": quarantineRoute({ d1: "20. Health/Kotihoito.pdf" }),
      "POST /api/activity/q1/undo/preview": { body: [] },
      "POST /api/activity/q1/undo": { body: { batch_id: "u1", dry_run: false, done: [], failed: null, error: null, index_error: null } },
    });
    const user = userEvent.setup();
    renderViewer();
    const bar = screen.getByRole("banner");
    const bin = await within(bar).findByRole("button", { name: "Move to To Delete" });
    (document.activeElement as HTMLElement | null)?.blur();
    await user.keyboard("{Backspace}");
    await new Promise((r) => setTimeout(r, 10));
    expect(quarantines(calls)).toHaveLength(0);
    await user.keyboard("{Meta>}{Backspace}{/Meta}");
    const dialog = await screen.findByRole("dialog", { name: "Move to To Delete?" });
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await user.click(bin);
    await user.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Move to To Delete" }));
    await user.click(await screen.findByRole("button", { name: "Undo" }));
    await user.click(await undoButton(await screen.findByRole("dialog", { name: "Undo these changes?" })));
    await waitFor(() => expect(calls.filter((c) => c.url === "/api/activity/q1/undo")).toHaveLength(1));
    expect(quarantines(calls)).toEqual([
      { drive_ids: ["d1"], dry_run: true },
      { drive_ids: ["d1"], dry_run: true },
      { drive_ids: ["d1"], dry_run: false },
    ]);
  });

  it("a file in ##. Important is refused up front, and ⌘⌫ says why", async () => {
    const calls = mockFetch({
      ...routes(),
      "GET /api/files/d1": { body: { record: { ...record("d1", "Kotihoito.pdf"), path: "##. Important/Kotihoito.pdf" }, tags: [] } },
    });
    const user = userEvent.setup();
    renderViewer();
    const bin = await within(screen.getByRole("banner")).findByRole("button", { name: "Move to To Delete" });
    expect(bin).toBeDisabled();
    expect(bin.parentElement).toHaveAttribute("data-tip", "Files in ##. Important are protected");
    await user.keyboard("{Meta>}{Backspace}{/Meta}");
    expect(await screen.findByText("Files in ##. Important are protected", { selector: ".toast-text" })).toBeInTheDocument();
    expect(quarantines(calls)).toHaveLength(0);
  });

  it("a record marked Important disables the bin up front with the server's reason; ⌘⌫ says it", async () => {
    const calls = mockFetch({
      ...routes(),
      "GET /api/files/d1": { body: { record: { ...record("d1", "Kotihoito.pdf"), marks: ["important"] }, tags: [] } },
    });
    const user = userEvent.setup();
    renderViewer();
    const bin = await within(screen.getByRole("banner")).findByRole("button", { name: "Move to To Delete" });
    expect(bin).toBeDisabled();
    expect(bin.parentElement).toHaveAttribute("data-tip", "This file is marked Important; unmark it first");
    await user.keyboard("{Meta>}{Backspace}{/Meta}");
    expect(
      await screen.findByText("This file is marked Important; unmark it first", { selector: ".toast-text" }),
    ).toBeInTheDocument();
    expect(quarantines(calls)).toHaveLength(0);
  });

  it("shows the server's reason for a file marked Important", async () => {
    mockFetch({ ...routes(), "POST /api/quarantine": IMPORTANT_REFUSED("20. Health/Kotihoito.pdf") });
    const user = userEvent.setup();
    renderViewer();
    await user.click(await within(screen.getByRole("banner")).findByRole("button", { name: "Move to To Delete" }));
    expect(await screen.findByText(/This file is marked Important; unmark it first: 20\. Health\/Kotihoito\.pdf/)).toBeInTheDocument();
  });
});

describe("selection helpers", () => {
  it("openViewer opens the one viewer window and tells it what to show", () => {
    const open = vi.spyOn(window, "open").mockImplementation(() => null);
    openViewer("a b");
    expect(open).toHaveBeenCalledWith("/viewer/a%20b", "dam-viewer", "width=900,height=1000");
  });

  it("works without BroadcastChannel: publishing is a no-op, following yields nothing", () => {
    vi.stubGlobal("BroadcastChannel", undefined);
    expect(() => publishSelection("d1")).not.toThrow();
    const { result } = renderHook(() => useSelectionFollower(true));
    expect(result.current).toBeNull();
  });

  it("a follower that is off hears nothing", () => {
    const { result } = renderHook(() => useSelectionFollower(false));
    act(() => publishSelection("d9"));
    expect(result.current).toBeNull();
  });

});
