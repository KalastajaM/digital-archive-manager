/** The file panel's icon row: what each context shows, the tooltips with their
 * keys, the groups apart by a rule, and what a disabled button says. */
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockFetch, renderWithProviders } from "../test-utils";
import { FileActionIcons, type FileActionIconsProps } from "./FileActionIcons";

afterEach(() => vi.unstubAllGlobals());

const FILE = { drive_id: "d1", path: "10. Financial/bill.pdf", name: "bill.pdf" };
const act = (extra: object = {}) => ({ run: vi.fn(), ...extra });
const FULL: FileActionIconsProps = {
  file: FILE,
  onQuickLook: vi.fn(),
  ask: act(),
  sender: act(),
  person: act(),
  tray: { label: "Put in tray", entries: [{ label: "To pay", onSelect: vi.fn() }] },
  star: { ...act(), on: false },
  important: { ...act(), on: true },
  backToInbox: act(),
  trash: act(),
};

function setup(props: FileActionIconsProps, routes: Record<string, object> = {}) {
  const calls = mockFetch({ ...routes });
  renderWithProviders(
    <MemoryRouter>
      <FileActionIcons {...props} />
    </MemoryRouter>,
  );
  return { calls, user: userEvent.setup() };
}
const names = (group: HTMLElement) => within(group).getAllByRole("button").map((b) => b.getAttribute("aria-label"));

describe("the two rows", () => {
  it("row 1 looks at the file, row 2 files it, each in a labelled group", () => {
    setup(FULL);
    expect(names(screen.getByRole("group", { name: "Look at it" }))).toEqual([
      "Open",
      "Quick Look",
      expect.stringMatching(/^Show in /),
      "Relatives",
      "Ask AI",
    ]);
    expect(names(screen.getByRole("group", { name: "File it" }))).toEqual([
      "From…",
      "For…",
      "Put in tray",
      "Star",
      "Unmark Important",
      "Back to inbox",
      "Move to To Delete",
    ]);
  });

  it("puts both parts in one row with a rule between them", () => {
    setup(FULL);
    const look = screen.getByRole("group", { name: "Look at it" });
    const fileIt = screen.getByRole("group", { name: "File it" });
    expect(look.parentElement).toBe(fileIt.parentElement);
    expect(look.nextElementSibling).toHaveAttribute("role", "separator");
    expect(look.nextElementSibling?.nextElementSibling).toBe(fileIt);
  });

  it("has Show in folder only where the screen gives it, after Show in Finder", async () => {
    const showInFolder = vi.fn();
    const { user } = setup({ ...FULL, showInFolder });
    const look = names(screen.getByRole("group", { name: "Look at it" }));
    expect(look.indexOf("Show in folder")).toBe(look.findIndex((n) => /^Show in (Finder|Explorer|file manager)/.test(n ?? "")) + 1);
    await user.click(screen.getByRole("button", { name: "Show in folder" }));
    expect(showInFolder).toHaveBeenCalled();
  });

  it("puts a visible rule between the groups of the second part and the red bin last, apart", () => {
    setup(FULL);
    const row = screen.getByRole("group", { name: "File it" });
    const seps = within(row).getAllByRole("separator");
    expect(seps).toHaveLength(3);
    expect(row.lastElementChild).toBe(screen.getByRole("button", { name: "Move to To Delete" }));
    expect(screen.getByRole("button", { name: "Move to To Delete" })).toHaveClass("trash-button");
    // a rule only between groups that exist: no star and no inbox, one rule before the bin
    setup({ file: FILE, sender: act(), person: act(), trash: act() });
    expect(within(screen.getAllByRole("group", { name: "File it" })[1]).queryAllByRole("separator")).toHaveLength(1);
  });

  it("names the key in the tooltip where there is one", () => {
    setup(FULL);
    expect(screen.getByRole("button", { name: "Quick Look" })).toHaveAttribute("data-tip", "Quick Look (Space)");
    expect(screen.getByRole("button", { name: "Move to To Delete" })).toHaveAttribute("data-tip", "Move to To Delete (⌘⌫)");
  });

  it("leaves out what the context does not have: no Back to inbox, no Ask AI, no Quick Look", () => {
    setup({ file: FILE, star: { ...act(), on: false }, important: { ...act(), on: false } });
    expect(names(screen.getByRole("group", { name: "Look at it" }))).toEqual(["Open", expect.stringMatching(/^Show in /), "Relatives"]);
    expect(names(screen.getByRole("group", { name: "File it" }))).toEqual(["Star", "Mark Important"]);
  });

  it("keeps a button that cannot run now, with its reason as the tooltip", () => {
    setup({ file: FILE, backToInbox: act({ reason: "Already in the inbox" }), trash: act({ reason: "It is locked" }) });
    expect(screen.getByRole("button", { name: "Back to inbox" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Back to inbox" }).parentElement).toHaveAttribute("data-tip", "Already in the inbox");
    expect(screen.getByRole("button", { name: "Move to To Delete" })).toBeDisabled();
  });

  it("runs the handlers it is given", async () => {
    const props = { ...FULL, ask: act(), star: { ...act(), on: false }, trash: act() };
    const { user } = setup(props);
    await user.click(screen.getByRole("button", { name: "Quick Look" }));
    await user.click(screen.getByRole("button", { name: "Ask AI" }));
    await user.click(screen.getByRole("button", { name: "Star" }));
    await user.click(screen.getByRole("button", { name: "Move to To Delete" }));
    expect(props.onQuickLook).toHaveBeenCalledTimes(1);
    expect(props.ask.run).toHaveBeenCalledTimes(1);
    expect(props.star.run).toHaveBeenCalledTimes(1);
    expect(props.trash.run).toHaveBeenCalledTimes(1);
  });

  it("Open and Show in Finder ask the server for this file", async () => {
    const { calls, user } = setup(
      { file: FILE },
      { "POST /api/files/d1/open": { body: null, status: 204 }, "POST /api/files/d1/reveal": { body: null, status: 204 } },
    );
    await user.click(screen.getByRole("button", { name: "Open" }));
    await user.click(screen.getByRole("button", { name: /^Show in / }));
    await waitFor(() => expect(calls.map((c) => c.url)).toEqual(["/api/files/d1/open", "/api/files/d1/reveal"]));
  });

  it("is off for a file whose archive folder is away", () => {
    setup({ file: { ...FILE, connected: false } });
    expect(screen.getByRole("button", { name: "Open" })).toBeDisabled();
    expect(screen.getByRole("button", { name: /^Show in / })).toBeDisabled();
  });
});

describe("what is not offered for some files", () => {
  it("no Relatives for a link, a folder or a file in To Delete", () => {
    for (const file of [
      { ...FILE, is_link: true },
      { ...FILE, is_dir: true },
      { ...FILE, path: "##. To Delete/bill.pdf" },
    ]) {
      const { unmount } = (() => {
        mockFetch({});
        return renderWithProviders(
          <MemoryRouter>
            <FileActionIcons file={file} />
          </MemoryRouter>,
        );
      })();
      expect(screen.queryByRole("button", { name: "Relatives" })).toBeNull();
      unmount();
    }
  });

  it("a file in To Delete has Restore, a pull-down, in the second row", async () => {
    const run = vi.fn();
    const { user } = setup({
      file: { ...FILE, path: "##. To Delete/bill.pdf" },
      restore: { entries: [{ label: "To where it was", onSelect: run }] },
    });
    const row = screen.getByRole("group", { name: "File it" });
    await user.click(within(row).getByRole("button", { name: "Restore from To Delete" }));
    await user.click(await screen.findByRole("menuitem", { name: "To where it was" }));
    expect(run).toHaveBeenCalled();
  });

  it("in a collection, Remove from collection is in the second row before the bin", () => {
    setup({ file: FILE, removeFromCollection: { ...act(), name: "bill.pdf" }, trash: act() });
    const row = screen.getByRole("group", { name: "File it" });
    expect(names(row)).toEqual(["Remove bill.pdf from the collection", "Move to To Delete"]);
  });
});

describe("several files", () => {
  it("has no look row; Move to… and Add to collection are icons, and the bin names the count", async () => {
    const run = vi.fn();
    const { user } = setup({
      file: null,
      moveTo: { ...act(), shortcut: "⇧⌘M" },
      addTo: { entries: [{ label: "Sauna", onSelect: run }] },
      sender: act(),
      person: act(),
      star: { ...act(), on: false },
      important: { ...act(), on: false },
      trash: { ...act(), count: 3 },
    });
    expect(screen.queryByRole("group", { name: "Look at it" })).toBeNull();
    expect(names(screen.getByRole("group", { name: "File it" }))).toEqual([
      "From…",
      "For…",
      "Add to collection",
      "Star",
      "Mark Important",
      "Move to…",
      "Move 3 to To Delete",
    ]);
    expect(screen.getByRole("button", { name: "Move to…" })).toHaveAttribute("data-tip", "Move to… (⇧⌘M)");
    await user.click(screen.getByRole("button", { name: "Add to collection" }));
    await user.click(await screen.findByRole("menuitem", { name: "Sauna" }));
    expect(run).toHaveBeenCalled();
  });
});
