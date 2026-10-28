/** The Inbox in the New look: a second divider (the filing panel's width) and, for a narrow
 * window, an "Inbox N" button that opens the folded list. Classic has neither. */
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

function setup(look: "new" | "classic", list: InboxEntry[] = ENTRIES, more: Record<string, unknown> = {}) {
  if (look === "new") document.documentElement.dataset.style = "new";
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
  delete document.documentElement.dataset.style;
});

describe("Inbox in the New look", () => {
  it("has a divider for the filing panel next to the list's, remembered and reset by a double-click", async () => {
    setup("new");
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
    const user = setup("new");
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
    const user = setup("new");
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

describe("Inbox in Classic", () => {
  it("has no filing panel divider and no Inbox N button", async () => {
    setup("classic");
    await screen.findByLabelText("Name");
    expect(screen.queryByRole("separator", { name: "Resize the filing panel" })).toBeNull();
    expect(screen.queryByRole("button", { name: /^Inbox \d/ })).toBeNull();
    expect(screen.getByRole("separator", { name: "Resize the list" })).toBeInTheDocument();
  });
});

describe("The queue in the New look", () => {
  it("counts the files to file and filters All, Bills and New", async () => {
    const user = setup("new", QUEUE);
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
    setup("new", QUEUE);
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
    const user = setup("new");
    await screen.findByLabelText("Name");
    expect(screen.getByText("None checked")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Shortcuts/ }));
    const popover = screen.getByRole("dialog", { name: "Keyboard shortcuts" });
    expect(popover).toHaveTextContent("skip to the next file");
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog", { name: "Keyboard shortcuts" })).toBeNull();
  });

  it("says what is checked and offers to file it", async () => {
    const user = setup("new", QUEUE);
    await screen.findByLabelText("Name");
    await user.click(screen.getByRole("checkbox", { name: "Select water.pdf" }));
    await user.click(screen.getByRole("checkbox", { name: "Select power.pdf" }));
    const foot = screen.getByRole("navigation", { name: "Inbox" });
    expect(foot.querySelector(".queue-checked")).toHaveTextContent("2 checked · File 2 checked");
    expect(within(foot).getByRole("button", { name: "File 2 checked" })).toBeInTheDocument();
  });
});

describe("The filing panel in the New look", () => {
  it("names the rule behind the suggestion and opens it with Edit rule", async () => {
    const user = setup("new", QUEUE, {
      "GET /api/rules": { body: { rules: [RULE], errors: [], state: { offer: true, declined: 0 }, unused_pictures: [], default_min_score: 0.85 } },
      "GET /api/status": { body: { special_folders: { inbox: "##. Organize" } } },
      "GET /api/tags": { body: [] },
      "GET /api/settings/people": { body: { people: [], address_zone: [0.06, 0.1, 0.52, 0.3], default_address_zone: [0.06, 0.1, 0.52, 0.3] } },
      ...replayJob(REPLAY),
    });
    const panel = await screen.findByRole("complementary", { name: "File this document" });
    expect(panel).toHaveTextContent("Suggested by rule “vesilaitos”");
    expect(within(panel).getByRole("heading", { name: "Vesilaitos water bill" })).toBeInTheDocument();
    await user.click(within(panel).getByRole("button", { name: "Edit rule" }));
    const sheet = await screen.findByRole("dialog", { name: "Edit rule vesilaitos" });
    expect(within(sheet).getByRole("button", { name: "Close" })).toBeInTheDocument();
  });

  it("has no Edit rule when no rule suggested anything", async () => {
    const user = setup("new", QUEUE);
    await screen.findByLabelText("Name");
    await user.click(screen.getByRole("button", { name: /letter\.pdf/ }));
    const panel = await screen.findByRole("complementary", { name: "File this document" });
    expect(panel).toHaveTextContent("No rule matched");
    expect(within(panel).queryByRole("button", { name: "Edit rule" })).toBeNull();
  });

  it("files from its foot: Skip, To Delete and File it, with what filing does in a line", async () => {
    setup("new");
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
    const user = setup("new");
    await screen.findByLabelText("Name");
    expect(screen.getByLabelText("Name")).toHaveValue("scan001.pdf");
    await user.click(screen.getByRole("button", { name: "Skip" }));
    await waitFor(() => expect(screen.getByLabelText("Name")).toHaveValue("scan002.pdf"));
    await user.click(screen.getByRole("button", { name: "Skip" }));
    await waitFor(() => expect(screen.getByLabelText("Name")).toHaveValue("scan001.pdf"));
  });

  it("is the s key in both looks, and never types into a field", async () => {
    for (const look of ["new", "classic"] as const) {
      const user = setup(look);
      await screen.findByLabelText("Name");
      const name = screen.getByLabelText("Name");
      await user.click(name);
      await user.keyboard("s"); // typing: no skip
      expect(name).toHaveValue("scan001.pdfs");
      (document.activeElement as HTMLElement).blur();
      await user.keyboard("s");
      await waitFor(() => expect(screen.getByLabelText("Name")).toHaveValue("scan002.pdf"));
      cleanup();
      delete document.documentElement.dataset.style;
    }
  });

  it("says so when there is no other file to skip to", async () => {
    const user = setup("new", [ENTRIES[0]]);
    await screen.findByLabelText("Name");
    await user.click(screen.getByRole("button", { name: "Skip" }));
    expect(await screen.findByText("There is no other file in the queue to skip to.")).toBeInTheDocument();
  });
});

describe("The document bar in the New look", () => {
  it("has the file's name, zoom, Open and one menu for Open, Print, Open in window and Show in Finder", async () => {
    const user = setup("new");
    await screen.findByLabelText("Name");
    expect(screen.getByRole("toolbar", { name: "Document" })).toHaveTextContent("scan001.pdf");
    expect(screen.getByRole("button", { name: "Open" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Print" })).toBeNull();
    await user.click(screen.getByRole("button", { name: "More: Print, Open in window, Show in Finder" }));
    const menu = screen.getByRole("menu");
    expect(within(menu).getAllByRole("menuitem").map((i) => i.textContent?.trim())).toEqual(["Open", "Print", "Open in window", expect.stringMatching(/^Show in /)]);
  });

  it("keeps Classic's toolbar and icon buttons", async () => {
    setup("classic");
    await screen.findByLabelText("Name");
    expect(screen.queryByRole("toolbar", { name: "Document" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Skip" })).toBeNull();
    expect(screen.getByRole("button", { name: "Print" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "File it" })).toBeInTheDocument();
  });
});
