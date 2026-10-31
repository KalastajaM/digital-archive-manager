/** The Inbox: a second divider (the filing panel's width) and, for a narrow window, an
 * "Inbox N" button that opens the folded list. */
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import type { InboxEntry } from "../api/client";
import { mockFetch, renderWithProviders, replayJob } from "../test-utils";
import Inbox from "./Inbox";

function entry(id: string, name: string, over: { prefill?: Record<string, string>; suggestion?: object } = {}): InboxEntry {
  const base = {
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
      connected: true,
      marks: [],
    },
    suggestion: {
      name,
      folder: null,
      tags: [],
      fields: { dates: [], amounts: [], iban: null, reference: null },
      doc_date: null,
      sources: [],
      name_source: "scan",
      folder_source: null,
      tag_sources: {},
      tray: null,
      tray_source: null,
      collections: [],
      collection_sources: {},
      codes: [],
      conflict: false,
      star: null,
      important: null,
      marks_unclear: false,
      waiting_for_page1: false,
      people_found: [],
      areas: [],
      person_line: null,
    },
    text_excerpt: "",
    prefill: {},
    tray_guess: null,
    open_trays: [],
    fields: [],
    fields_edited: false,
    person_follows_folder: false,
  };
  return { ...base, prefill: over.prefill ?? {}, suggestion: { ...base.suggestion, ...over.suggestion } } as InboxEntry;
}

const ENTRIES = [entry("d1", "scan001.pdf"), entry("d2", "scan002.pdf")];

const RULE = {
  id: "vesilaitos",
  file: "learned.yaml",
  learned: true,
  when: { text_contains: ["vesilaitos"], filename_matches: null, folder_is: "##. Organize", zones: [], person: null },
  then: { folder: "30. Home/Water", name: null, tags: [], tray: null, payee: null, collections: [] },
  person_zone: null,
  sender: null,
  stats: { suggested: 2, changed: 0, last_used: null, flagged: false },
};
const REPLAY = { matched: 0, same: 0, different: [], inbox: 0, shadowed: [], checked: 0, total: 0, truncated: false };

// a bill the water rule suggests for, an overdue bill, and a letter nothing is known about
const QUEUE = [
  entry("b1", "water.pdf", {
    prefill: { due_date: "2099-11-05", total: "47.90" },
    suggestion: { name: "20991105 Vesilaitos water bill.pdf", folder: "30. Home/Water", folder_source: "rule:vesilaitos", name_source: "rule:vesilaitos" },
  }),
  entry("b2", "power.pdf", { prefill: { due_date: "2020-01-02", total: "84.20" } }),
  entry("n1", "letter.pdf"),
];

function setup(list: InboxEntry[] = ENTRIES, more: Record<string, unknown> = {}) {
  mockFetch({
    "GET /api/inbox": { body: list },
    "GET /api/folders": { body: [] },
    "GET /api/trays": { body: { trays: [], errors: [] } },
    "GET /api/collections": { body: [] },
    ...more,
  } as never);
  renderWithProviders(
    <MemoryRouter>
      <Inbox />
    </MemoryRouter>,
  );
  return userEvent.setup();
}

beforeEach(() => localStorage.clear());
afterEach(() => {
  cleanup();
});

describe("Inbox", () => {
  it("has a divider for the filing panel next to the list's, remembered and reset by a double-click", async () => {
    setup();
    await screen.findByLabelText("Name");
    const panel = screen.getByRole("separator", { name: "Resize the filing panel" });
    expect(panel).toHaveAttribute("aria-valuenow", "360");
    expect(panel).toHaveClass("splitter-end");
    expect(screen.getByRole("separator", { name: "Resize the list" })).toHaveAttribute("aria-valuenow", "280");
    fireEvent.keyDown(panel, { key: "ArrowLeft" }); // the divider moves left: the panel grows
    expect(panel).toHaveAttribute("aria-valuenow", "376");
    expect(Object.values(localStorage).length).toBeGreaterThan(0);
    fireEvent.doubleClick(panel);
    expect(panel).toHaveAttribute("aria-valuenow", "360");
  });

  it("folds the list behind an Inbox N button: it opens, takes the focus, and Esc closes it", async () => {
    const user = setup();
    const button = await screen.findByRole("button", { name: "Inbox 2" });
    const list = screen.getByRole("navigation", { name: "Inbox" });
    expect(button).toHaveAttribute("aria-expanded", "false");
    expect(button).toHaveAttribute("aria-controls", list.id);
    await user.click(button);
    expect(button).toHaveAttribute("aria-expanded", "true");
    expect(list.closest(".inbox")).toHaveAttribute("data-queue", "open");
    await waitFor(() => expect(document.activeElement).toHaveAttribute("data-inbox-entry"));
    await user.keyboard("{Escape}");
    expect(button).toHaveAttribute("aria-expanded", "false");
    expect(list.closest(".inbox")).not.toHaveAttribute("data-queue");
    expect(button).toHaveFocus();
  });

  it("closes the folded list when a file is picked in it", async () => {
    const user = setup();
    const button = await screen.findByRole("button", { name: "Inbox 2" });
    await user.click(button);
    await user.click(screen.getByRole("button", { name: /scan002\.pdf/ }));
    // the card is made again for the other file, with its own button
    await waitFor(() => expect(screen.getByLabelText("Name")).toHaveValue("scan002.pdf"));
    expect(screen.getByRole("button", { name: "Inbox 2" })).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByRole("navigation", { name: "Inbox" }).closest(".inbox")).not.toHaveAttribute("data-queue");
    expect(screen.getByRole("button", { name: "Inbox 2" })).toHaveFocus();
  });
});

describe("The queue", () => {
  it("counts the files to file and filters All, Bills and New", async () => {
    const user = setup(QUEUE);
    await screen.findByLabelText("Name");
    expect(screen.getByText("3 to file")).toBeInTheDocument();
    const filter = screen.getByRole("group", { name: "Show" });
    expect(within(filter).getAllByRole("button").map((b) => b.textContent)).toEqual(["All 3", "Bills 2", "New 2"]);
    expect(within(filter).getByRole("button", { name: "All 3" })).toHaveAttribute("aria-pressed", "true");
    await user.click(within(filter).getByRole("button", { name: "Bills 2" }));
    const list = screen.getByRole("navigation", { name: "Inbox" });
    expect(within(list).getAllByRole("button", { name: /\.pdf/ })).toHaveLength(2);
    expect(within(list).queryByRole("button", { name: /letter\.pdf/ })).toBeNull();
    await user.click(within(filter).getByRole("button", { name: "New 2" }));
    expect(within(list).getAllByRole("button", { name: /\.pdf/ })).toHaveLength(2);
    expect(within(list).queryByRole("button", { name: /water\.pdf/ })).toBeNull();
  });

  it("gives a row its title, the file's name and date, and a status pill", async () => {
    setup(QUEUE);
    await screen.findByLabelText("Name");
    const list = screen.getByRole("navigation", { name: "Inbox" });
    const water = within(list).getByRole("button", { name: /Vesilaitos water bill/ });
    expect(water).toHaveTextContent("water.pdf");
    expect(water.querySelector(".pill-orange")).toHaveTextContent("Due 5 Nov 2099 · 47,90 €");
    const power = within(list).getByRole("button", { name: /power\.pdf/ });
    expect(power.querySelector(".pill-red")?.textContent).toMatch(/^Overdue \d+ days · 84,20 €$/);
    expect(within(list).getByRole("button", { name: /letter\.pdf/ }).querySelector(".entry-pill")).toBe(
      within(list).getByRole("button", { name: /letter\.pdf/ }).querySelector(".pill-grey"),
    );
  });

  it("lists the shortcuts, with Skip, in a popover from the foot", async () => {
    const user = setup();
    await screen.findByLabelText("Name");
    expect(screen.getByText("None checked")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Shortcuts/ }));
    const popover = screen.getByRole("dialog", { name: "Keyboard shortcuts" });
    expect(popover).toHaveTextContent("skip to the next file");
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog", { name: "Keyboard shortcuts" })).toBeNull();
  });

  it("says what is checked and offers to file it", async () => {
    const user = setup(QUEUE);
    await screen.findByLabelText("Name");
    await user.click(screen.getByRole("checkbox", { name: "Select water.pdf" }));
    await user.click(screen.getByRole("checkbox", { name: "Select power.pdf" }));
    const foot = screen.getByRole("navigation", { name: "Inbox" });
    expect(foot.querySelector(".queue-checked")).toHaveTextContent("2 checked · File 2 checked");
    expect(within(foot).getByRole("button", { name: "File 2 checked" })).toBeInTheDocument();
  });
});

describe("The filing panel", () => {
  it("names the rule behind the suggestion and opens it with Edit rule", async () => {
    const user = setup(QUEUE, {
      "GET /api/rules": { body: { rules: [RULE], errors: [], state: { offer: true, declined: 0 }, unused_pictures: [], default_min_score: 0.85 } },
      "GET /api/status": { body: { special_folders: { inbox: "##. Organize" } } },
      "GET /api/tags": { body: [] },
      "GET /api/settings/people": { body: { people: [], address_zone: [0.06, 0.1, 0.52, 0.3], default_address_zone: [0.06, 0.1, 0.52, 0.3] } },
      ...replayJob(REPLAY),
    });
    const panel = await screen.findByRole("complementary", { name: "File this document" });
    expect(panel).toHaveTextContent("Suggested by rule “vesilaitos”");
    expect(within(panel).getByRole("heading", { name: "Vesilaitos water bill" })).toBeInTheDocument();
    // where its relatives were filed: a hint for this one, folded until opened
    expect(within(panel).getByRole("button", { name: /^Relatives/, expanded: false })).toBeInTheDocument();
    await user.click(within(panel).getByRole("button", { name: "Edit rule" }));
    const sheet = await screen.findByRole("dialog", { name: "Edit rule vesilaitos" });
    expect(within(sheet).getByRole("button", { name: "Close" })).toBeInTheDocument();
  });

  it("is the one file panel: the file's header, the icon rows, then the form, with Relatives after it", async () => {
    setup();
    const panel = await screen.findByRole("complementary", { name: "File this document" });
    await within(panel).findByLabelText("Name");
    const blocks = [...panel.querySelectorAll(".file-skeleton > [data-block]")].map((b) => (b as HTMLElement).dataset.block);
    expect(blocks).toEqual(["header", "actions", "top", "relatives"]);
    // header: the file's name and where it is now
    expect(within(panel.querySelector(".file-meta-head") as HTMLElement).getByRole("heading", { name: "scan001.pdf" })).toBeInTheDocument();
    // row 1: look at it; row 2 only has what applies here: no Back to inbox (it is in the inbox),
    // no From, For or Put in tray (the form has them), no bin (the foot has To Delete)
    const look = within(panel).getByRole("group", { name: "Look at it" });
    expect(within(look).getAllByRole("button").map((b) => b.getAttribute("aria-label"))).toEqual([
      "Open",
      "Quick Look",
      expect.stringMatching(/^Show in /),
      "Relatives",
    ]);
    const filing = within(panel).getByRole("group", { name: "File it" });
    expect(within(filing).getAllByRole("button").map((b) => b.getAttribute("aria-label"))).toEqual(["Star", "Mark Important"]);
    expect(within(panel).queryByRole("button", { name: "Back to inbox" })).toBeNull();
    // the suggestion header stays above, with Ask AI there (not repeated in the icon row)
    expect(within(look).queryByRole("button", { name: "Ask AI" })).toBeNull();
  });

  it("several selected: the same skeleton with From, For, the marks and the bin in the icon rows, no Who field", async () => {
    const user = setup();
    await screen.findByLabelText("Name");
    await user.click(screen.getByRole("checkbox", { name: "Select scan001.pdf" }));
    await user.click(screen.getByRole("checkbox", { name: "Select scan002.pdf" }));
    const card = await screen.findByRole("article", { name: "Batch of 2 files" });
    const blocks = [...card.querySelectorAll(".file-skeleton > [data-block]")].map((b) => (b as HTMLElement).dataset.block);
    expect(blocks).toEqual(["header", "actions", "top"]);
    const filing = within(card).getByRole("group", { name: "File it" });
    expect(within(filing).getAllByRole("button").map((b) => b.getAttribute("aria-label"))).toEqual([
      "From…",
      "For…",
      "Star",
      "Mark Important",
      "Move 2 to To Delete",
    ]);
    // the toolbar keeps Preview and File 2 files, and no longer repeats the marks and the bin
    expect(within(card).getAllByRole("button", { name: "Star" })).toHaveLength(1);
    expect(within(card).queryByRole("group", { name: "Who" })).toBeNull();
    await user.click(within(filing).getByRole("button", { name: "From…" }));
    expect(await screen.findByRole("dialog", { name: "From (2 documents)" })).toBeInTheDocument();
  });

  it("has no Edit rule when no rule suggested anything", async () => {
    const user = setup(QUEUE);
    await screen.findByLabelText("Name");
    await user.click(screen.getByRole("button", { name: /letter\.pdf/ }));
    const panel = await screen.findByRole("complementary", { name: "File this document" });
    expect(panel).toHaveTextContent("No rule matched");
    expect(within(panel).queryByRole("button", { name: "Edit rule" })).toBeNull();
  });

  it("files from its foot: Skip, To Delete and File it, with what filing does in a line", async () => {
    setup();
    const panel = await screen.findByRole("complementary", { name: "File this document" });
    expect(within(panel).getByRole("button", { name: "Skip" })).toBeEnabled();
    expect(within(panel).getByRole("button", { name: "File it" })).toBeInTheDocument();
    // the file's name and folder are not set: the line says what is missing, then what will happen
    expect(panel).toHaveTextContent("Choose a folder.");
    expect(within(panel).getByRole("button", { name: "Preview" })).toBeInTheDocument();
  });
});

describe("Skip", () => {
  it("moves on to the next file without filing, round to the first from the last", async () => {
    const user = setup();
    await screen.findByLabelText("Name");
    expect(screen.getByLabelText("Name")).toHaveValue("scan001.pdf");
    await user.click(screen.getByRole("button", { name: "Skip" }));
    await waitFor(() => expect(screen.getByLabelText("Name")).toHaveValue("scan002.pdf"));
    await user.click(screen.getByRole("button", { name: "Skip" }));
    await waitFor(() => expect(screen.getByLabelText("Name")).toHaveValue("scan001.pdf"));
  });

  it("is the s key, and never types into a field", async () => {
    const user = setup();
    await screen.findByLabelText("Name");
    const name = screen.getByLabelText("Name");
    await user.click(name);
    await user.keyboard("s"); // typing: no skip
    expect(name).toHaveValue("scan001.pdfs");
    (document.activeElement as HTMLElement).blur();
    await user.keyboard("s");
    await waitFor(() => expect(screen.getByLabelText("Name")).toHaveValue("scan002.pdf"));
  });

  it("says so when there is no other file to skip to", async () => {
    const user = setup([ENTRIES[0]]);
    await screen.findByLabelText("Name");
    await user.click(screen.getByRole("button", { name: "Skip" }));
    expect(await screen.findByText("There is no other file in the queue to skip to.")).toBeInTheDocument();
  });
});

describe("The document bar", () => {
  it("has the file's name, zoom, Open and one menu for Open, Print, Open in window and Show in Finder", async () => {
    const user = setup();
    await screen.findByLabelText("Name");
    const bar = screen.getByRole("toolbar", { name: "Document" });
    expect(bar).toHaveTextContent("scan001.pdf");
    expect(within(bar).getByRole("button", { name: "Open" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Print" })).toBeNull();
    await user.click(screen.getByRole("button", { name: "More: Print, Open in window, Show in Finder" }));
    const menu = screen.getByRole("menu");
    expect(within(menu).getAllByRole("menuitem").map((i) => i.textContent?.trim())).toEqual(["Open", "Print", "Open in window", expect.stringMatching(/^Show in /)]);
  });
});

describe("An inbox row's right-click menu", () => {
  const names = (menu: HTMLElement) =>
    Array.from(menu.querySelectorAll('[role^="menuitem"]')).map((b) => b.querySelector(".menu-item-text")?.firstChild?.textContent);
  const row = (name: string) => screen.getAllByText(name).map((n) => n.closest("li")).find((li) => li?.closest(".inbox-entries")) as HTMLElement;

  it("selects the row it is on, then offers a look, the trays, a filing code, Skip, tags and collections, the marks and the bin", async () => {
    const user = setup(ENTRIES, { "GET /api/trays": { body: { trays: [{ id: "pay", name: "To pay", order: 1, item_title: "{name}", fields: {}, date_field: null, done: { label: "Done", fields: {} } }], errors: [] } } });
    await screen.findByLabelText("Name");
    fireEvent.contextMenu(row("scan002.pdf"), { clientX: 30, clientY: 30 });
    const menu = await screen.findByRole("menu", { name: "Actions for scan002.pdf" });
    expect(row("scan002.pdf").querySelector("[data-inbox-entry]")).toHaveAttribute("aria-current", "true");
    expect(names(menu)).toEqual([
      "Quick Look",
      "Open",
      "Show in Finder",
      "Skip",
      "Assign a filing code…",
      "Put in To pay",
      "Add tag…",
      "Add to collection…",
      "Star",
      "Mark Important",
      "Move to To Delete",
    ]);
    await user.click(within(menu).getByRole("menuitem", { name: "Add tag…" }));
    expect(await screen.findByRole("dialog", { name: "Add a tag to scan002.pdf" })).toBeInTheDocument();
  });

  it("on a row in a selection acts on all of it; Skip and the look need one file", async () => {
    const user = setup();
    await screen.findByLabelText("Name");
    await user.click(screen.getByRole("checkbox", { name: "Select scan001.pdf" }));
    await user.click(screen.getByRole("checkbox", { name: "Select scan002.pdf" }));
    fireEvent.contextMenu(row("scan001.pdf"));
    const menu = await screen.findByRole("menu", { name: "Actions for 2 selected files" });
    expect(names(menu)).not.toContain("Skip");
    expect(names(menu)).not.toContain("Quick Look");
    expect(names(menu)).toContain("Move 2 to To Delete");
  });
});
