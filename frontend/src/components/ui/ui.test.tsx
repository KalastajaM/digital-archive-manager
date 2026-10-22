import { fireEvent, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { mockFetch, renderWithProviders } from "../../test-utils";
import { Card } from "./Card";
import { EmptyState } from "./EmptyState";
import { IconButton } from "./IconButton";
import { Menu } from "./Menu";
import { Segmented } from "./Segmented";
import { Sheet } from "./Sheet";
import { Sidebar } from "./Sidebar";
import { Tag } from "./Tag";
import { TipButton } from "./TipButton";
import { Toolbar } from "./Toolbar";

const STATUS = {
  files: 10,
  indexed: 8,
  pending: 0,
  cloud_pending: 0,
  errors: 0,
  unsupported: 0,
  missing: 0,
  inbox_count: 3,
  rule_errors: [],
  tray_errors: [],
  recovery_pending: 0,
  archive_available: true,
};

const tray = (id: string, name: string, order: number) => ({ id, name, order, item_title: "{name}" });
const TRAYS = { trays: [tray("to-pay", "To pay", 1), tray("to-action", "To action", 2), tray("to-read", "To read", 3)], errors: [] };

const collection = (id: number, name: string) => ({
  id, name, state: "open", created: 1, closed_at: null, publish: {}, ongoing_rel: null, members: [], ongoing_status: null,
});
// Not alphabetical on purpose: the sidebar sorts A–Z.
const COLLECTIONS = [collection(2, "Tax 2026"), collection(1, "Legal")];

const item = (id: number, title: string) => ({
  id, tray_id: "to-pay", title, state: "open", fields: {}, created: 1, done_at: null, files: [], collections: [],
});
const attention = (level: string, id: number) => ({
  item: item(id, `Bill ${id}`), tray: "To pay", level, missing_required: [], file_state: "ok", note_excerpt: null,
});
const TODAY = {
  attention: [attention("overdue", 1), attention("overdue", 2), attention("today", 3), attention("soon", 4), attention("undated", 5)],
  overview: {
    inbox: 3,
    trays: [
      { tray_id: "to-pay", name: "To pay", open: 3, overdue: 2, sum: null, waiting_long: 0 },
      { tray_id: "to-action", name: "To action", open: 1, overdue: 0, sum: null, waiting_long: 0 },
      { tray_id: "to-read", name: "To read", open: 4, overdue: 0, sum: null, waiting_long: 0 },
    ],
    collections: [],
  },
  unmanaged_ongoing: 0,
  ongoing_sync_failure: null,
  reminders: { last_run: null, errors: {}, skipped: null },
  tray_errors: [],
};

const renderSidebar = (url = "/") =>
  renderWithProviders(
    <MemoryRouter initialEntries={[url]}>
      <Sidebar footer={<p>foot</p>} />
    </MemoryRouter>,
  );

describe("Sidebar", () => {
  it("lists Today, Inbox, the trays in order, the open collections A–Z and the archive as links", async () => {
    mockFetch({
      "GET /api/status": { body: STATUS },
      "GET /api/trays": { body: TRAYS },
      "GET /api/collections": { body: COLLECTIONS },
      "GET /api/today": { body: TODAY },
    });
    renderSidebar("/inbox");
    const nav = screen.getByRole("navigation", { name: "Main" });
    await within(nav).findByRole("link", { name: "To read (4)" });
    await within(nav).findByRole("link", { name: "Legal" });
    expect(within(nav).getAllByRole("link").map((a) => [a.getAttribute("aria-label") ?? a.textContent, a.getAttribute("href")])).toEqual([
      ["Today (3)", "/"],
      ["Inbox (3)", "/inbox"],
      ["Trays", "/trays"],
      ["To pay (3)", "/trays/to-pay"],
      ["To action (1)", "/trays/to-action"],
      ["To read (4)", "/trays/to-read"],
      ["Collections", "/collections"],
      ["Important", "/important"],
      ["Legal", "/collections/1"],
      ["Tax 2026", "/collections/2"],
      ["Browse", "/browse"],
      ["Ask", "/ask"],
      ["Activity", "/activity"],
    ]);
    expect(within(nav).getByRole("link", { name: "Inbox (3)" })).toHaveAttribute("aria-current", "page");
    expect(within(nav).getByRole("link", { name: "Today (3)" })).not.toHaveAttribute("aria-current");
    expect(screen.getByText("foot")).toBeInTheDocument(); // the status badge slot
  });

  it("the Today badge counts overdue and due-today items, and hides when there are none", async () => {
    mockFetch({
      "GET /api/status": { body: STATUS },
      "GET /api/trays": { body: TRAYS },
      "GET /api/collections": { body: COLLECTIONS },
      "GET /api/today": { body: TODAY },
    });
    const { unmount } = renderSidebar();
    const today = await screen.findByRole("link", { name: "Today (3)" });
    expect(within(today).getByText("3")).toHaveClass("sidebar-badge");
    unmount();
    mockFetch({
      "GET /api/status": { body: { ...STATUS, inbox_count: 0 } },
      "GET /api/trays": { body: { trays: [], errors: [] } },
      "GET /api/collections": { body: [] },
      "GET /api/today": { body: { ...TODAY, attention: [], overview: { inbox: 0, trays: [], collections: [] } } },
    });
    renderSidebar();
    const nav = screen.getByRole("navigation", { name: "Main" });
    await within(nav).findByRole("link", { name: "Browse" });
    expect(within(nav).getByRole("link", { name: "Today" })).toBeInTheDocument();
    expect(within(nav).getByRole("link", { name: "Inbox" })).toBeInTheDocument(); // no "(0)"
    expect(within(nav).queryByText("0")).not.toBeInTheDocument();
  });
});

describe("IconButton", () => {
  it("is named by its label and its tooltip adds the shortcut", async () => {
    const onClick = vi.fn();
    renderWithProviders(<IconButton icon={<svg />} label="New collection" shortcut="⌘N" onClick={onClick} />);
    const button = screen.getByRole("button", { name: "New collection" });
    expect(button).toHaveAttribute("data-tip", "New collection ⌘N");
    expect(button).not.toHaveAttribute("data-tip-side");
    await userEvent.setup().click(button);
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it("can put its tooltip above, for controls near the bottom", () => {
    renderWithProviders(<IconButton icon={<svg />} label="Dismiss" tipSide="above" onClick={() => {}} />);
    expect(screen.getByRole("button", { name: "Dismiss" })).toHaveAttribute("data-tip-side", "above");
  });

  it("can be disabled", () => {
    renderWithProviders(<IconButton icon={<svg />} label="Undo" onClick={() => {}} disabled />);
    expect(screen.getByRole("button", { name: "Undo" })).toBeDisabled();
  });
});

describe("TipButton", () => {
  it("has its tip while usable, and the reason (on a wrap) while disabled", () => {
    const { rerender } = renderWithProviders(
      <TipButton className="primary tip-end" tip="Move it ⌘↩" disabledReason="Still busy">
        File it
      </TipButton>,
    );
    const button = screen.getByRole("button", { name: "File it" });
    expect(button).toHaveAttribute("data-tip", "Move it ⌘↩");
    expect(button.parentElement).not.toHaveClass("button-wrap");
    rerender(
      <TipButton className="primary tip-end" tip="Move it ⌘↩" disabled disabledReason="Still busy">
        File it
      </TipButton>,
    );
    const wrap = screen.getByRole("button", { name: "File it" }).parentElement!;
    expect(wrap).toHaveClass("button-wrap", "tip-end");
    expect(wrap).toHaveAttribute("data-tip", "Still busy");
  });
});

describe("Segmented", () => {
  it("marks the chosen option pressed and reports a change", async () => {
    const onChange = vi.fn();
    renderWithProviders(
      <Segmented
        ariaLabel="Tray"
        options={[{ value: "pay", label: "To pay" }, { value: "read", label: "To read" }, { value: "", label: "—" }]}
        value="pay"
        onChange={onChange}
      />,
    );
    const group = screen.getByRole("group", { name: "Tray" });
    expect(within(group).getByRole("button", { name: "To pay" })).toHaveAttribute("aria-pressed", "true");
    expect(within(group).getByRole("button", { name: "To read" })).toHaveAttribute("aria-pressed", "false");
    await userEvent.setup().click(within(group).getByRole("button", { name: "To read" }));
    expect(onChange).toHaveBeenCalledWith("read");
  });
});

describe("Sheet", () => {
  it("opens a native dialog with its title, and Esc closes it", async () => {
    const onClose = vi.fn();
    renderWithProviders(
      <Sheet open title="Undo these changes?" onClose={onClose}>
        <p>body</p>
      </Sheet>,
    );
    const dialog = screen.getByRole("dialog", { name: "Undo these changes?" });
    expect(dialog).toHaveAttribute("open");
    expect(document.querySelector("dialog[open]")).toBe(dialog);
    expect(within(dialog).getByText("body")).toBeInTheDocument();
    await userEvent.setup().keyboard("{Escape}");
    expect(onClose).toHaveBeenCalled();
  });

  it("a stacked sheet's cancel (Esc) never reaches the sheet underneath", () => {
    const outer = vi.fn();
    const inner = vi.fn();
    renderWithProviders(
      <Sheet open title="Outer" onClose={outer}>
        <Sheet open title="Inner" onClose={inner}>
          <p>inner body</p>
        </Sheet>
      </Sheet>,
    );
    fireEvent(screen.getByRole("dialog", { name: "Inner" }), new Event("cancel", { bubbles: true, cancelable: true }));
    expect(inner).toHaveBeenCalledTimes(1);
    expect(outer).not.toHaveBeenCalled();
  });

  it("keeps the title and the footer outside the scrolling body, in that order", () => {
    const long = Array.from({ length: 200 }, (_, i) => <p key={i}>line {i}</p>);
    renderWithProviders(
      <Sheet open title="Long" onClose={() => {}} footer={<button type="button">Save</button>}>
        {long}
      </Sheet>,
    );
    const dialog = screen.getByRole("dialog", { name: "Long" });
    const parts = [...dialog.children].map((el) => el.className);
    expect(parts).toEqual(["sheet-title", "sheet-body", "sheet-footer"]);
    const footer = dialog.querySelector(".sheet-footer")!;
    expect(within(footer as HTMLElement).getByRole("button", { name: "Save" })).toBeVisible();
    expect(dialog.querySelector(".sheet-body")).not.toContainElement(within(footer as HTMLElement).getByRole("button"));
  });

  it("has no footer when none is given", () => {
    renderWithProviders(
      <Sheet open title="Plain" onClose={() => {}}>
        <p>body</p>
      </Sheet>,
    );
    expect(screen.getByRole("dialog").querySelector(".sheet-footer")).toBeNull();
  });

  it("renders nothing when closed", () => {
    renderWithProviders(
      <Sheet open={false} title="Hidden" onClose={() => {}}>
        <p>body</p>
      </Sheet>,
    );
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(document.querySelector("dialog[open]")).toBeNull();
  });
});

describe("Toolbar, Card, Tag and EmptyState", () => {
  it("the toolbar shows the title, subtitle, actions and search", () => {
    renderWithProviders(
      <Toolbar title="Inbox" subtitle="6 documents" actions={<button type="button">Act</button>} search={<input aria-label="Search" />} />,
    );
    const header = screen.getByRole("heading", { name: "Inbox" }).closest("header")!;
    expect(within(header).getByText("6 documents")).toBeInTheDocument();
    const actions = within(header).getByRole("toolbar", { name: "Inbox actions" });
    expect(within(actions).getByRole("button", { name: "Act" })).toBeInTheDocument();
    expect(within(header).getByRole("textbox", { name: "Search" })).toBeInTheDocument();
  });

  it("a card is a region named by its title", () => {
    renderWithProviders(
      <Card title="To pay" icon={<svg />}>
        <p>content</p>
      </Card>,
    );
    expect(screen.getByRole("region", { name: "To pay" })).toHaveTextContent("content");
  });

  it("a tag carries its tone as a class", () => {
    renderWithProviders(<Tag tone="orange">due in 2 days</Tag>);
    expect(screen.getByText("due in 2 days")).toHaveClass("tag", "tag-orange");
  });

  it("an empty state shows its title and hint", () => {
    renderWithProviders(<EmptyState title="The inbox is empty." hint="Scans land here." />);
    expect(screen.getByText("The inbox is empty.")).toBeInTheDocument();
    expect(screen.getByText("Scans land here.")).toBeInTheDocument();
  });
});

describe("Menu", () => {
  it("escapes a scrolling column and stays inside the window", async () => {
    const user = userEvent.setup();
    renderWithProviders(
      <div style={{ overflow: "auto", width: 120 }} data-testid="column">
        <Menu label="Actions for Quotes" icon="…" entries={[{ label: "Remove group…", onSelect: () => {} }]} />
      </div>,
    );
    const trigger = screen.getByRole("button", { name: "Actions for Quotes" });
    const right = window.innerWidth - 6;
    vi.spyOn(trigger, "getBoundingClientRect").mockReturnValue(DOMRect.fromRect({ x: right - 24, y: 100, width: 24, height: 22 }));
    const width = vi.spyOn(HTMLElement.prototype, "offsetWidth", "get").mockReturnValue(200);
    await user.click(trigger);
    const menu = screen.getByRole("menu", { name: "Actions for Quotes" });
    expect(screen.getByTestId("column")).not.toContainElement(menu);
    expect(menu.style.position).toBe("fixed");
    expect(menu.style.top).toBe("126px");
    // Flipped left so all 200px fit: never past the window's right edge.
    expect(parseFloat(menu.style.left)).toBe(window.innerWidth - 200 - 8);
    width.mockRestore();
  });
});
