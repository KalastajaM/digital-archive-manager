/** The rule sheet: the match choice is a segmented control, the name has pattern chips,
 * the proof has a one-line summary (shown by CSS in a narrow sheet) with "Show proof". */
import { cleanup, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { type Call, mockFetch, renderWithProviders, replayJob } from "../../test-utils";
import { RuleSheet } from "./RuleSheet";
import { jobPolling } from "./useReplayJob";

beforeEach(() => {
  jobPolling.ms = 20;
});
afterEach(() => {
  cleanup();
});

const REPLAY = {
  matched: 11,
  same: 10,
  different: [{ drive_id: "x1", path_now: "10. Financial/a.pdf", path_rule: "20. Health/2026/a.pdf" }],
  inbox: 1,
  shadowed: [],
  checked: 11,
  total: 11,
  truncated: false,
  source: { drive_id: "d1", path: "##. Organize/scan.pdf", matched: true, reason: "" },
};
const ZONE_DRAFT = {
  id: "kela",
  words: [],
  folder: "50. Medical/Kela",
  name: "{doc_date:%Y%m%d} Kela",
  tags: [],
  tray: null,
  payee: null,
  zones: [{ box: [0.1, 0.1, 0.5, 0.3], words: [{ word: "kela", ticked: true }], lines: ["Kela"] }],
  pictures: [],
  folder_is: "##. Organize",
  sender: null,
  place_above: null,
  person: null,
  people_found: [],
};

function setup() {
  const calls: Call[] = mockFetch({
    "GET /api/status": { body: { special_folders: { inbox: "##. Organize" } } },
    "GET /api/trays": { body: { trays: [], errors: [] } },
    "GET /api/tags": { body: [] },
    "GET /api/settings/people": { body: { people: [], address_zone: [0.06, 0.1, 0.52, 0.3], default_address_zone: [0.06, 0.1, 0.52, 0.3] } },
    ...replayJob(REPLAY),
  } as never);
  renderWithProviders(<RuleSheet initial={ZONE_DRAFT as never} onClose={vi.fn()} />);
  return { calls, user: userEvent.setup() };
}

describe("RuleSheet", () => {
  it("offers Words match as a segmented control that changes the rule", async () => {
    const { calls, user } = setup();
    const group = await screen.findByRole("group", { name: "How the words match in area" });
    expect(screen.queryByRole("combobox", { name: "How the words match in area" })).toBeNull();
    expect(within(group).getByRole("button", { name: "Starts a word" })).toHaveAttribute("aria-pressed", "true");
    await user.click(within(group).getByRole("button", { name: "Whole word" }));
    expect(within(group).getByRole("button", { name: "Whole word" })).toHaveAttribute("aria-pressed", "true");
    await waitFor(() => {
      const starts = calls.filter((c) => c.method === "POST" && c.url === "/api/rules/replay/jobs");
      const rule = (starts.at(-1)?.body as { rule: { when: { zones: { match?: string }[] } } }).rule;
      expect(rule.when.zones[0].match).toBe("whole_word");
    });
  });

  it("puts a name pattern into the field at the caret when its chip is clicked", async () => {
    const { user } = setup();
    const name = (await screen.findByLabelText("Name")) as HTMLInputElement;
    await user.clear(name);
    await user.type(name, "ab");
    name.setSelectionRange(1, 1);
    const chips = screen.getByRole("group", { name: "Insert into name" });
    await user.click(within(chips).getByRole("button", { name: "{stem}" }));
    expect(name).toHaveValue("a{stem}b");
    expect(within(chips).getAllByRole("button").map((b) => b.textContent)).toEqual(["{year}", "{doc_date:%Y%m%d}", "{stem}", "{person}"]);
  });

  it("summarises the proof in one line and opens it with Show proof", async () => {
    const { user } = setup();
    const show = await screen.findByRole("button", { name: "Show proof" });
    expect(show).toHaveAttribute("aria-expanded", "false");
    expect(show.closest("dialog")).not.toHaveClass("proof-open");
    const line = show.closest(".proof-mini") as HTMLElement;
    await waitFor(() => expect(line).toHaveTextContent("Matches this document10 / 11filed documents land where they are · 1 elsewhere"));
    await user.click(show);
    expect(screen.getByRole("button", { name: "Hide proof" })).toHaveAttribute("aria-expanded", "true");
    expect(show.closest("dialog")).toHaveClass("proof-open");
  });

  it("shows the proof's figure beside the sentence", async () => {
    setup();
    await screen.findByText(/Matches 11 documents you filed before/);
    expect(document.querySelector(".replay-figure")).toHaveTextContent("10 / 11");
  });
});

describe("RuleSheet header and foot", () => {
  it("has a close button, calls its proof The proof and saves with Save rule", async () => {
    const { user } = setup();
    const sheet = await screen.findByRole("dialog", { name: "Make a rule" });
    expect(await within(sheet).findByText("The proof")).toBeInTheDocument();
    expect(within(sheet).getByRole("button", { name: "Save rule" })).toBeInTheDocument();
    await user.click(within(sheet).getByRole("button", { name: "Close" }));
  });
});
