import { act, screen, waitFor, within } from "@testing-library/react";
import { useState } from "react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, useLocation } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import type { InboxEntry } from "../api/client";
import Inbox from "../screens/Inbox";
import { deferred, mockFetch, renderWithProviders } from "../test-utils";
import type { QLFile } from "./QuickLook";
import { useQuickLook } from "./useQuickLook";

function entry(id: string, name: string, suggested: string): InboxEntry {
  return {
    record: {
      drive_id: id,
      path: `##. Organize/${name}`,
      name,
      ext: "pdf",
      is_dir: false,
      is_link: false,
      link_target: null,
      size: 1000,
      mtime: 1_760_000_000,
      sha256: null,
      doc_date: null,
      index_state: "indexed",
      retry_at: null,
      attempts: 0,
      missing: false,
      last_seen: null,
      parked_at: null,
      connected: true, marks: [],
    },
    suggestion: {
      name: suggested,
      folder: "30. Home/Electricity",
      tags: [],
      fields: { dates: ["2026-10-01"], amounts: ["84.20"], iban: null, reference: null },
      doc_date: "2026-10-01",
      sources: [],
      name_source: "scan",
      folder_source: null,
      tag_sources: {},
      tray: null,
      tray_source: null,
      collections: [],
      collection_sources: {},
      codes: [],
      conflict: false, star: null, important: null, marks_unclear: false, waiting_for_page1: false, people_found: [], areas: [], person_line: null,
    },
    text_excerpt: "",
    prefill: {},
    tray_guess: null,
    open_trays: [],
    fields: [{ kind: "amount", label: null, value: "84.20" }],
    fields_edited: false,
  };
}

const ENTRIES = [
  entry("d1", "scan001.pdf", "2026-10-01 Kotihoito lasku.pdf"),
  entry("d2", "scan002.pdf", "2026-10-02 Sähkölasku.pdf"),
  entry("d3", "scan003.pdf", "2026-10-03 Vesilasku.pdf"),
];

async function setup(extra: Parameters<typeof mockFetch>[0] = {}) {
  mockFetch({
    "GET /api/inbox": { body: ENTRIES },
    "GET /api/folders": { body: [] },
    "GET /api/trays": { body: { trays: [], errors: [] } },
    "GET /api/collections": { body: [] },
    ...extra,
  });
  const user = userEvent.setup();
  renderWithProviders(
    <MemoryRouter>
      <Inbox />
    </MemoryRouter>,
  );
  const name = (await screen.findByLabelText("Name")) as HTMLInputElement;
  (document.activeElement as HTMLElement | null)?.blur();
  return { user, name };
}

const quickLook = () => screen.queryByRole("dialog", { name: /^Quick Look/ });

describe("Quick Look in the inbox", () => {
  it("Space opens it on the selected entry, → shows the next, Esc closes", async () => {
    const { user } = await setup();
    await user.keyboard("j"); // select scan002
    await user.keyboard(" ");
    const ql = screen.getByRole("dialog", { name: "Quick Look: scan002.pdf" });
    expect(within(ql).getByRole("img", { name: "Page 1" })).toHaveAttribute(
      "src",
      expect.stringContaining("/api/files/d2/page/1.png"),
    );
    const details = within(ql).getByRole("region", { name: "Details" });
    expect(within(details).getByText("scan002.pdf")).toBeInTheDocument();
    expect(within(details).getByText("##. Organize")).toBeInTheDocument();
    expect(within(details).getByText("84,20 €")).toBeInTheDocument();
    expect(within(ql).getByText("2 of 3")).toBeInTheDocument();

    await user.keyboard("{ArrowRight}");
    expect(screen.getByRole("dialog", { name: "Quick Look: scan003.pdf" })).toBeInTheDocument();
    // The list moves with it.
    expect(screen.getByLabelText("Name")).toHaveValue("2026-10-03 Vesilasku.pdf");
    await user.keyboard("{ArrowRight}"); // the last one: stays
    expect(screen.getByRole("dialog", { name: "Quick Look: scan003.pdf" })).toBeInTheDocument();

    await user.keyboard("{Escape}");
    expect(quickLook()).not.toBeInTheDocument();
    expect(screen.getByLabelText("Name")).toHaveValue("2026-10-03 Vesilasku.pdf");
  });

  it("has the Draw a box tool on the previewed page", async () => {
    const { user } = await setup();
    await user.keyboard(" ");
    const ql = screen.getByRole("dialog", { name: "Quick Look: scan001.pdf" });
    expect(await within(ql).findByRole("button", { name: "Draw a box" })).toBeInTheDocument();
  });

  it("a refused Open shows its reason inside Quick Look, not as a toast under it", async () => {
    const REFUSED = "Won't open apps or scripts from the archive — use Show in Finder";
    const { user } = await setup({ "POST /api/files/d1/open": { status: 409, body: { error: REFUSED } } });
    await user.keyboard(" ");
    const ql = screen.getByRole("dialog", { name: "Quick Look: scan001.pdf" });
    await user.click(within(ql).getByRole("button", { name: "Open" }));
    const line = await within(ql).findByText(REFUSED);
    expect(line.closest('[role="status"]')).not.toBeNull();
    expect(document.querySelector(".toasts")).not.toHaveTextContent(REFUSED);
    await user.keyboard("j"); // another document: the old result goes
    expect(within(screen.getByRole("dialog")).queryByText(REFUSED)).toBeNull();
  });

  it("j/k and ← move one entry at a time inside; Space closes it", async () => {
    const { user } = await setup();
    await user.keyboard(" ");
    expect(screen.getByRole("dialog", { name: "Quick Look: scan001.pdf" })).toBeInTheDocument();
    await user.keyboard("j");
    // Exactly one step: the inbox's own j is off while Quick Look is open.
    expect(screen.getByRole("dialog", { name: "Quick Look: scan002.pdf" })).toBeInTheDocument();
    await user.keyboard("j");
    expect(screen.getByRole("dialog", { name: "Quick Look: scan003.pdf" })).toBeInTheDocument();
    await user.keyboard("k{ArrowLeft}");
    expect(screen.getByRole("dialog", { name: "Quick Look: scan001.pdf" })).toBeInTheDocument();
    await user.keyboard(" ");
    expect(quickLook()).not.toBeInTheDocument();
  });

  it("Space on one of its own buttons presses that button instead of closing", async () => {
    const { user } = await setup();
    await user.keyboard(" ");
    const next = within(screen.getByRole("dialog")).getByRole("button", { name: "Next file" });
    await user.click(next);
    expect(screen.getByRole("dialog", { name: "Quick Look: scan002.pdf" })).toBeInTheDocument();
    expect(next).toHaveFocus();
    await user.keyboard(" ");
    expect(screen.getByRole("dialog", { name: "Quick Look: scan003.pdf" })).toBeInTheDocument();
    act(() => screen.getByRole("dialog").focus());
    await user.keyboard(" "); // not on a button: closes
    expect(quickLook()).not.toBeInTheDocument();
  });

  it("the buttons move and close too", async () => {
    const { user } = await setup();
    await user.keyboard(" ");
    const ql = screen.getByRole("dialog", { name: "Quick Look: scan001.pdf" });
    expect(within(ql).getByRole("button", { name: "Previous file" })).toBeDisabled();
    // Close is the last control, at the far right
    expect(within(ql.querySelector<HTMLElement>(".quicklook-bar")!).getAllByRole("button").at(-1)).toHaveAccessibleName("Close");
    await user.click(within(ql).getByRole("button", { name: "Next file" }));
    expect(screen.getByRole("dialog", { name: "Quick Look: scan002.pdf" })).toBeInTheDocument();
    await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Close" }));
    expect(quickLook()).not.toBeInTheDocument();
  });

  it("Space in the name field types a space", async () => {
    const { user, name } = await setup();
    await user.click(name);
    await user.keyboard(" ");
    expect(name).toHaveValue("2026-10-01 Kotihoito lasku.pdf ");
    expect(quickLook()).not.toBeInTheDocument();
  });

  it("Space with a modifier or on a checkbox does not open it", async () => {
    const { user } = await setup();
    await user.keyboard("{Meta>} {/Meta}");
    expect(quickLook()).not.toBeInTheDocument();
    const box = screen.getByRole("checkbox", { name: "Select scan001.pdf" });
    box.focus();
    await user.keyboard(" ");
    expect(box).toBeChecked();
    expect(quickLook()).not.toBeInTheDocument();
  });

  it("Space does not open it while the confirm sheet is open", async () => {
    const mkdir = { kind: "mkdir", src: null, dst: "40. New", drive_id: null, note: "create missing folder" };
    const { user } = await setup({ "POST /api/inbox/preview": { body: [mkdir] } });
    await user.click(screen.getByRole("button", { name: "File it" }));
    const confirm = await screen.findByRole("dialog");
    expect(confirm).not.toHaveAccessibleName(/^Quick Look/);
    (document.activeElement as HTMLElement | null)?.blur();
    await user.keyboard(" ");
    expect(quickLook()).not.toBeInTheDocument();
    expect(screen.getByRole("dialog")).toBe(confirm);
  });

  it("Space does not open it while a file call is in flight", async () => {
    const held = deferred<{ body: unknown }>();
    const move = { kind: "move", src: "##. Organize/scan001.pdf", dst: "30. Home/Electricity/x.pdf", drive_id: "d1", note: null };
    const { user } = await setup({
      "POST /api/inbox/preview": { body: [move] },
      "POST /api/inbox/file": () => held.promise,
    });
    await user.click(screen.getByRole("button", { name: "File it" }));
    await waitFor(() => expect(screen.getAllByRole("button", { name: "File it" })[0]).toBeDisabled());
    (document.activeElement as HTMLElement | null)?.blur();
    await user.keyboard(" ");
    expect(quickLook()).not.toBeInTheDocument();
    await act(async () => held.resolve({ body: { batch_id: "b1", dry_run: false, done: [move], failed: null, error: null, index_error: null, tag_error: null, untagged: [], items: [], follow_up_error: null } }));
  });

  it("+ zooms the Quick Look preview, not the one behind it", async () => {
    const { user } = await setup();
    await user.keyboard(" ");
    const ql = screen.getByRole("dialog", { name: /^Quick Look/ });
    await user.keyboard("+");
    expect(within(ql).getByTestId("zoom-level")).toHaveTextContent("150%");
    const behind = screen.getAllByTestId("zoom-level").filter((el) => !ql.contains(el));
    expect(behind).toHaveLength(1);
    expect(behind[0]).toHaveTextContent("Fit");
  });

  it("keeps the zoom while paging through documents; 0 returns to Fit", async () => {
    const { user } = await setup();
    await user.keyboard(" ");
    const ql = screen.getByRole("dialog", { name: /^Quick Look/ });
    expect(within(ql).getByTestId("zoom-level")).toHaveTextContent("Fit"); // opens at Fit, not 100 %
    await user.keyboard("++");
    expect(within(ql).getByTestId("zoom-level")).toHaveTextContent("200%");
    await user.keyboard("{ArrowRight}");
    expect(ql).toHaveAccessibleName("Quick Look: scan002.pdf");
    expect(within(ql).getByTestId("zoom-level")).toHaveTextContent("200%");
    await user.keyboard("0");
    expect(within(ql).getByTestId("zoom-level")).toHaveTextContent("Fit");
    await user.keyboard("{ArrowRight}");
    expect(within(ql).getByTestId("zoom-level")).toHaveTextContent("Fit");
  });

  it("Open in window opens the viewer window on that document", async () => {
    const open = vi.spyOn(window, "open").mockImplementation(() => null);
    const { user } = await setup();
    await user.keyboard(" ");
    const ql = screen.getByRole("dialog", { name: /^Quick Look/ });
    await user.click(within(ql).getByRole("button", { name: "Open in window" }));
    expect(open).toHaveBeenCalledWith("/viewer/d1", "dam-viewer", "width=900,height=1000");
  });

});

function Harness({ files }: { files: QLFile[] }) {
  const [index, setIndex] = useState(0);
  const ql = useQuickLook(files, index, setIndex);
  return (
    <>
      <button type="button" onClick={ql.open}>
        Look
      </button>
      {ql.view}
    </>
  );
}

const FILE = (id: string): QLFile => ({ drive_id: id, name: `${id}.png`, path: `a/${id}.png`, ext: "png" });

describe("useQuickLook", () => {
  it("closes when the list empties under it, and opens on nothing", async () => {
    const user = userEvent.setup();
    const { rerender } = renderWithProviders(
      <MemoryRouter>
        <Harness files={[FILE("a"), FILE("b")]} />
      </MemoryRouter>,
    );
    await user.click(screen.getByRole("button", { name: "Look" }));
    expect(screen.getByRole("dialog", { name: "Quick Look: a.png" })).toBeInTheDocument();
    rerender(
      <MemoryRouter>
        <Harness files={[]} />
      </MemoryRouter>,
    );
    expect(quickLook()).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Look" }));
    expect(quickLook()).not.toBeInTheDocument();
  });

  it("gives the focus back where it was when it closes", async () => {
    const user = userEvent.setup();
    renderWithProviders(
      <MemoryRouter>
        <Harness files={[FILE("a")]} />
      </MemoryRouter>,
    );
    const look = screen.getByRole("button", { name: "Look" });
    await user.click(look);
    expect(look).not.toHaveFocus();
    await user.keyboard("{Escape}");
    expect(quickLook()).not.toBeInTheDocument();
    expect(look).toHaveFocus();
  });

  it("in the New look its Relatives button closes it and opens the Relatives window, then gives the focus back", async () => {
    document.documentElement.dataset.style = "new";
    try {
      mockFetch({ "GET /api/files/a/relatives": { body: { drive_id: "a", relatives: [], common: [], total: 0, hidden: 0 } } });
      const user = userEvent.setup();
      renderWithProviders(
        <MemoryRouter>
          <Harness files={[FILE("a"), { drive_id: "l1", name: "l", path: "a/l", ext: null, is_link: true }]} />
        </MemoryRouter>,
      );
      const look = screen.getByRole("button", { name: "Look" });
      await user.click(look);
      await user.click(within(quickLook()!).getByRole("button", { name: "Relatives" }));
      expect(quickLook()).not.toBeInTheDocument();
      const window = await screen.findByRole("dialog", { name: "Relatives" });
      expect(within(window).getByText("a.png")).toBeInTheDocument();
      await user.click(within(window).getByRole("button", { name: "Close" }));
      expect(screen.queryByRole("dialog", { name: "Relatives" })).toBeNull();
      expect(look).toHaveFocus();
      // a link stands for its target, which has its own: no button on it
      await user.click(look);
      await user.keyboard("{ArrowRight}");
      expect(within(quickLook()!).queryByRole("button", { name: "Relatives" })).toBeNull();
    } finally {
      delete document.documentElement.dataset.style;
    }
  });

  it("has no Relatives button in Classic", async () => {
    const user = userEvent.setup();
    renderWithProviders(
      <MemoryRouter>
        <Harness files={[FILE("a")]} />
      </MemoryRouter>,
    );
    await user.click(screen.getByRole("button", { name: "Look" }));
    expect(within(quickLook()!).queryByRole("button", { name: "Relatives" })).toBeNull();
  });

  it("Go to target on a link closes Quick Look, then opens Browse at the target", async () => {
    mockFetch({
      "GET /api/files/l1": {
        body: { record: {}, tags: [], link_target_id: "t1", link_target_path: "20. Home/t.pdf", link_target_inside: true },
      },
    });
    function Location() {
      const loc = useLocation();
      return <p data-testid="location">{loc.pathname + loc.search}</p>;
    }
    const user = userEvent.setup();
    renderWithProviders(
      <MemoryRouter initialEntries={["/inbox"]}>
        <Harness files={[{ drive_id: "l1", name: "l", path: "a/l", ext: null, is_link: true }]} />
        <Location />
      </MemoryRouter>,
    );
    await user.click(screen.getByRole("button", { name: "Look" }));
    await user.click(await within(quickLook()!).findByRole("button", { name: "Go to target" }));
    expect(quickLook()).not.toBeInTheDocument();
    expect(screen.getByTestId("location").textContent).toBe("/browse?path=20.+Home&select=t1");
  });
});

describe("Inbox ?file=", () => {
  it("selects that entry (Mark paid & file it… links here)", async () => {
    mockFetch({
      "GET /api/inbox": { body: ENTRIES },
      "GET /api/folders": { body: [] },
      "GET /api/trays": { body: { trays: [], errors: [] } },
      "GET /api/collections": { body: [] },
    });
    renderWithProviders(
      <MemoryRouter initialEntries={["/inbox?file=d3"]}>
        <Inbox />
      </MemoryRouter>,
    );
    expect(await screen.findByLabelText("Name")).toHaveValue("2026-10-03 Vesilasku.pdf");
    const current = screen.getByRole("button", { current: true });
    expect(current).toHaveTextContent("scan003.pdf");
  });

  it("an unknown file starts at the top", async () => {
    mockFetch({
      "GET /api/inbox": { body: ENTRIES },
      "GET /api/folders": { body: [] },
      "GET /api/trays": { body: { trays: [], errors: [] } },
      "GET /api/collections": { body: [] },
    });
    renderWithProviders(
      <MemoryRouter initialEntries={["/inbox?file=gone"]}>
        <Inbox />
      </MemoryRouter>,
    );
    expect(await screen.findByLabelText("Name")).toHaveValue("2026-10-01 Kotihoito lasku.pdf");
  });
});
