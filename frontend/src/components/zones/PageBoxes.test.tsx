import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { type Call, mockFetch, renderWithProviders, replayJob } from "../../test-utils";
import { FilePreview } from "../FilePreview";

const pdf = { drive_id: "d1", path: "##. Organize/a.pdf", ext: "pdf" };
const jpg = { drive_id: "d2", path: "##. Organize/b.jpg", ext: "jpg" };

const READ = { read: true, lines: [], unavailable: null };
const FOUND = { read: true, lines: [{ text: "Pohjola Vakuutus Oy", box: [0.1, 0.1, 0.5, 0.2] }], unavailable: null };
const PEOPLE = { people: [{ name: "Tiina", match: ["Tiina Visser"] }], address_zone: [0.06, 0.1, 0.52, 0.3], default_address_zone: [0.06, 0.1, 0.52, 0.3] };
const RULE = {
  id: "pohjola",
  file: "learned.yaml",
  learned: true,
  when: { text_contains: [], filename_matches: null, folder_is: "##. Organize", zones: [{ box: [0.05, 0.02, 0.45, 0.14], text_contains: ["pohjola"], image: null }], person: null },
  then: { folder: "Insurance/Pohjola", name: null, tags: [], tray: null, payee: null },
  person_zone: [0.1, 0.2, 0.6, 0.4],
  sender: "Pohjola",
  stats: { suggested: 3, changed: 0, last_used: null, flagged: false },
};
const DRAFT = {
  id: "pohjola",
  folder: "Insurance/Pohjola",
  name: null,
  tags: [],
  tray: null,
  payee: null,
  words: [],
  zones: [{ box: [0.1, 0.1, 0.5, 0.3], words: [{ word: "pohjola", ticked: true }, { word: "vakuutus", ticked: false }], lines: ["Pohjola Vakuutus Oy"] }],
  folder_is: "##. Organize",
  sender: "Pohjola",
  place_above: null,
};
const REPLAY = {
  matched: 2, same: 2, different: [], inbox: 0, shadowed: [], checked: 2, total: 2, truncated: false,
  not_checked: [], reading: 0,
};

const posts = (calls: Call[], url: string) => calls.filter((c) => c.method === "POST" && c.url === url);

function setup(
  extra: Parameters<typeof mockFetch>[0] = {},
  file = pdf,
  tool: { suggestion?: { name_source: string; folder_source: string | null } } = { suggestion: { name_source: "scan", folder_source: null } },
) {
  const calls = mockFetch({
    "GET /api/files/d1/page1": { body: READ },
    "GET /api/files/d2/page1": { body: READ },
    "POST /api/files/d1/page1/lines": { body: FOUND },
    "GET /api/senders": { body: [{ sender: "Pohjola", count: 14 }] },
    "GET /api/settings/people": { body: PEOPLE },
    "GET /api/rules": { body: { rules: [RULE], errors: [], state: { offer: true, declined: 0 } } },
    "GET /api/status": { body: { special_folders: { inbox: "##. Organize" } } },
    "GET /api/trays": { body: { trays: [], errors: [] } },
    "GET /api/tags": { body: [] },
    ...extra,
  });
  renderWithProviders(
    <MemoryRouter>
      <FilePreview file={file} boxTool={tool} />
    </MemoryRouter>,
  );
  return { calls, user: userEvent.setup() };
}

/** Draws from (20, 40) to (100, 120) on a 200 x 400 page: the box [0.1, 0.1, 0.5, 0.3]. */
async function draw() {
  const surface = await screen.findByTestId("box-surface");
  surface.getBoundingClientRect = () => ({ left: 0, top: 0, width: 200, height: 400, right: 200, bottom: 400, x: 0, y: 0 }) as DOMRect;
  fireEvent.pointerDown(surface, { clientX: 20, clientY: 40, button: 0 });
  fireEvent.pointerMove(surface, { clientX: 100, clientY: 120 });
  fireEvent.pointerUp(surface, { clientX: 100, clientY: 120 });
}

describe("Draw a box", () => {
  it("puts the notes and the panel after the page, so the page never moves while drawing", async () => {
    const { user } = setup();
    await user.click(screen.getByRole("button", { name: "Draw a box" }));
    await draw();
    const panel = await screen.findByRole("region", { name: "The boxes" });
    const page = screen.getByAltText("Page 1");
    // nothing that grows with the boxes sits before the page in the preview
    expect(page.compareDocumentPosition(panel) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    const note = screen.getByText(/Drag over page 1 to add the next box/);
    expect(page.compareDocumentPosition(note) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("is off until it is asked for and asks for nothing before that", () => {
    const { calls } = setup();
    expect(screen.getByRole("button", { name: "Draw a box" })).toHaveAttribute("aria-pressed", "false");
    expect(screen.queryByTestId("box-surface")).toBeNull();
    expect(calls.filter((c) => c.url.includes("page1"))).toHaveLength(0);
  });

  it("draws a box as fractions of the page and lists the lines in it", async () => {
    const { calls, user } = setup();
    await user.click(screen.getByRole("button", { name: "Draw a box" }));
    await draw();
    const panel = await screen.findByRole("region", { name: "The boxes" });
    expect(within(panel).getByText("Boxes on page 1")).toBeInTheDocument();
    expect(await within(panel).findByText("Pohjola Vakuutus Oy")).toBeInTheDocument();
    expect(posts(calls, "/api/files/d1/page1/lines")[0].body).toEqual({ box: [0.1, 0.1, 0.5, 0.3] });
    // the box stays on the page, numbered, as soon as it is drawn
    expect(screen.getByTestId("kept-box")).toHaveStyle({ left: "10%", top: "10%", width: "40%", height: "20%" });
    expect(screen.queryByTestId("drawn-box")).toBeNull();
  });

  it("leaves OCR noise out of what a box lists, and says no text when only noise is left", async () => {
    const { user } = setup({
      "POST /api/files/d1/page1/lines": { body: { read: true, lines: [{ text: "•ö Pohjola Vakuutus", box: [0.1, 0.1, 0.5, 0.2] }], unavailable: null } },
    });
    await user.click(screen.getByRole("button", { name: "Draw a box" }));
    await draw();
    const list = await screen.findByRole("list", { name: "Boxes" });
    expect(await within(list).findByText("Pohjola Vakuutus")).toBeInTheDocument();
    expect(within(list).queryByText(/•ö/)).toBeNull();
  });

  it("a box that holds only noise has no text", async () => {
    const { user } = setup({
      "POST /api/files/d1/page1/lines": { body: { read: true, lines: [{ text: "•ö |", box: [0.1, 0.1, 0.5, 0.2] }], unavailable: null } },
    });
    await user.click(screen.getByRole("button", { name: "Draw a box" }));
    await draw();
    expect(await screen.findByText("No text found")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Make a rule…" })).toBeDisabled();
  });

  it("the panel's close control says what it does and drops every box", async () => {
    const { user } = setup();
    await user.click(screen.getByRole("button", { name: "Draw a box" }));
    await draw();
    await screen.findByText("Pohjola Vakuutus Oy");
    const close = screen.getByRole("button", { name: "Close and drop the boxes" });
    expect(close).toHaveAttribute("title", expect.stringMatching(/drop all the boxes/));
    await user.click(close);
    expect(screen.queryByRole("region", { name: "The boxes" })).toBeNull();
    expect(screen.queryByTestId("kept-box")).toBeNull();
    expect(screen.getByTestId("box-surface")).toBeInTheDocument(); // the tool stays on for the next box
  });

  it("works on an image too", async () => {
    const { calls, user } = setup({ "POST /api/files/d2/page1/lines": { body: FOUND } }, jpg);
    await user.click(screen.getByRole("button", { name: "Draw a box" }));
    await draw();
    await screen.findByText("Pohjola Vakuutus Oy");
    expect(posts(calls, "/api/files/d2/page1/lines")).toHaveLength(1);
  });

  it("Esc cancels a box being drawn, and a click draws nothing", async () => {
    const { calls, user } = setup();
    await user.click(screen.getByRole("button", { name: "Draw a box" }));
    const surface = await screen.findByTestId("box-surface");
    surface.getBoundingClientRect = () => ({ left: 0, top: 0, width: 200, height: 400, right: 200, bottom: 400, x: 0, y: 0 }) as DOMRect;
    fireEvent.pointerDown(surface, { clientX: 20, clientY: 40, button: 0 });
    fireEvent.pointerMove(surface, { clientX: 100, clientY: 120 });
    expect(screen.getByTestId("drawn-box")).toBeInTheDocument();
    fireEvent.keyDown(document.body, { key: "Escape" });
    expect(screen.queryByTestId("drawn-box")).toBeNull();
    fireEvent.pointerUp(surface, { clientX: 100, clientY: 120 });
    fireEvent.pointerDown(surface, { clientX: 50, clientY: 50, button: 0 });
    fireEvent.pointerUp(surface, { clientX: 50, clientY: 50 });
    expect(screen.queryByRole("region", { name: "The boxes" })).toBeNull();
    expect(posts(calls, "/api/files/d1/page1/lines")).toHaveLength(0);
    fireEvent.keyDown(document.body, { key: "Escape" }); // a second Esc leaves the tool
    expect(screen.queryByTestId("box-surface")).toBeNull();
  });

  it("says Reading page 1… while it is read, and draws once it is", async () => {
    let reads = 0;
    setup({ "GET /api/files/d1/page1": () => ({ body: ++reads < 2 ? { read: false, lines: [], unavailable: null } : READ }) });
    fireEvent.click(screen.getByRole("button", { name: "Draw a box" }));
    expect(await screen.findByText("Reading page 1…")).toBeInTheDocument();
    expect(screen.queryByTestId("box-surface")).toBeNull();
    expect(await screen.findByTestId("box-surface", {}, { timeout: 4000 })).toBeInTheDocument();
    expect(screen.queryByText("Reading page 1…")).toBeNull();
  });

  it("shows why it cannot be used and is disabled", async () => {
    setup({ "GET /api/files/d1/page1": { body: { read: false, lines: [], unavailable: "No OCR engine for scanned pages" } } });
    fireEvent.click(screen.getByRole("button", { name: "Draw a box" }));
    expect(await screen.findByText("No OCR engine for scanned pages")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("button", { name: "Draw a box" })).toBeDisabled());
    expect(screen.queryByTestId("box-surface")).toBeNull();
  });

  it("says when the box holds no text", async () => {
    const { user } = setup({ "POST /api/files/d1/page1/lines": { body: READ } });
    await user.click(screen.getByRole("button", { name: "Draw a box" }));
    await draw();
    expect(await screen.findByText("No text found")).toBeInTheDocument();
  });

  it("Make a rule… drafts a rule from the box, with From filled in from the draft, and opens the rule sheet", async () => {
    const { calls, user } = setup({
      "POST /api/rules/draft-zone": { body: DRAFT },
      ...replayJob(REPLAY),
      "PUT /api/rules/pohjola": { body: { rules: [], errors: [], state: { offer: true, declined: 0 } } },
    });
    await user.click(screen.getByRole("button", { name: "Draw a box" }));
    await draw();
    const panel = await screen.findByRole("region", { name: "The boxes" });
    expect(within(panel).queryByRole("button", { name: "Sender…" })).toBeNull();
    expect(within(panel).queryByRole("button", { name: "Add another box" })).toBeNull();
    await within(panel).findByText("Pohjola Vakuutus Oy");
    await user.click(within(panel).getByRole("button", { name: "Make a rule…" }));
    expect(posts(calls, "/api/rules/draft-zone")[0].body).toEqual({ drive_id: "d1", boxes: [[0.1, 0.1, 0.5, 0.3]] });
    const sheet = await screen.findByRole("dialog", { name: "Make a rule" });
    expect(within(sheet).getByRole("button", { name: "pohjola" })).toHaveAttribute("aria-pressed", "true");
    expect(within(sheet).getByRole("group", { name: "Area" })).toBeInTheDocument();
    expect(within(sheet).getByLabelText("From (sender)")).toHaveValue("Pohjola");
    await within(sheet).findByText(/Matches 2 documents/);
    const sent = posts(calls, "/api/rules/replay/jobs")[0].body as { rule: { when: unknown; sender: string } };
    expect(sent.rule.when).toEqual({
      text_contains: [],
      filename_matches: null,
      folder_is: "##. Organize",
      zones: [{ box: [0.1, 0.1, 0.5, 0.3], text_contains: ["pohjola"], match: "word_start" }],
    });
    expect(sent.rule.sender).toBe("Pohjola");
    await user.click(within(sheet).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(calls.filter((c) => c.method === "PUT")).toHaveLength(1));
    expect(calls.find((c) => c.method === "PUT")?.body).toMatchObject({
      id: "pohjola",
      when: { zones: [{ box: [0.1, 0.1, 0.5, 0.3], text_contains: ["pohjola"] }] },
      sender: "Pohjola",
    });
  });

  describe("several boxes", () => {
    /** Draws from (20, 160) to (100, 200): the box [0.1, 0.4, 0.5, 0.5]. */
    async function drawSecond() {
      const surface = await screen.findByTestId("box-surface");
      fireEvent.pointerDown(surface, { clientX: 20, clientY: 160, button: 0 });
      fireEvent.pointerMove(surface, { clientX: 100, clientY: 200 });
      fireEvent.pointerUp(surface, { clientX: 100, clientY: 200 });
    }
    const TWO = {
      ...DRAFT,
      zones: [
        DRAFT.zones[0],
        { box: [0.1, 0.4, 0.5, 0.5], words: [{ word: "vakuutuskirja", ticked: true }], lines: ["Vakuutuskirja"] },
      ],
      place_above: "pohjola-old",
    };

    it("keeps every drawn box, numbered, with its words and its own remove button", async () => {
      const { user } = setup();
      await user.click(screen.getByRole("button", { name: "Draw a box" }));
      await draw();
      const panel = await screen.findByRole("region", { name: "The boxes" });
      await within(panel).findByText("Pohjola Vakuutus Oy");
      await drawSecond();
      const list = within(panel).getByRole("list", { name: "Boxes" });
      await waitFor(() => expect(within(list).getAllByText("Pohjola Vakuutus Oy")).toHaveLength(2));
      expect(within(list).getByText("Box 1")).toBeInTheDocument();
      expect(within(list).getByText("Box 2")).toBeInTheDocument();
      expect(screen.getAllByTestId("kept-box")).toHaveLength(2);
      // the address choices are for a single box
      expect(within(panel).queryByRole("button", { name: "Address area for all letters" })).toBeNull();
      await user.click(within(panel).getByRole("button", { name: "Remove box 1" }));
      expect(screen.getAllByTestId("kept-box")).toHaveLength(1);
      expect(within(list).queryByText("Box 2")).toBeNull();
      expect(within(panel).getByRole("button", { name: "Address area for all letters" })).toBeInTheDocument();
    });

    it("reads each box on its own when two are drawn quickly", async () => {
      let n = 0;
      const { user } = setup({
        "POST /api/files/d1/page1/lines": () => ({ body: { read: true, lines: [{ text: n++ === 0 ? "Eka" : "Toka", box: [0.1, 0.1, 0.5, 0.2] }], unavailable: null } }),
      });
      await user.click(screen.getByRole("button", { name: "Draw a box" }));
      await draw();
      await drawSecond();
      const list = await screen.findByRole("list", { name: "Boxes" });
      expect(await within(list).findByText("Eka")).toBeInTheDocument();
      expect(await within(list).findByText("Toka")).toBeInTheDocument();
    });

    it("Make a rule… sends every box, and the sheet has a group per area", async () => {
      const { calls, user } = setup({
        "POST /api/rules/draft-zone": { body: TWO },
        ...replayJob(REPLAY),
        "PUT /api/rules/pohjola": { body: { rules: [], errors: [], state: { offer: true, declined: 0 } } },
      });
      await user.click(screen.getByRole("button", { name: "Draw a box" }));
      await draw();
      const panel = await screen.findByRole("region", { name: "The boxes" });
      await within(panel).findByText("Pohjola Vakuutus Oy");
      await drawSecond();
      const list = within(panel).getByRole("list", { name: "Boxes" });
      await waitFor(() => expect(within(list).getAllByText("Pohjola Vakuutus Oy")).toHaveLength(2));
      await user.click(within(panel).getByRole("button", { name: "Make a rule…" }));
      expect(posts(calls, "/api/rules/draft-zone")[0].body).toEqual({
        drive_id: "d1",
        boxes: [
          [0.1, 0.1, 0.5, 0.3],
          [0.1, 0.4, 0.5, 0.5],
        ],
      });
      const sheet = await screen.findByRole("dialog", { name: "Make a rule" });
      expect(within(sheet).getByRole("group", { name: "Area 1" })).toBeInTheDocument();
      expect(within(sheet).getByRole("group", { name: "Area 2" })).toBeInTheDocument();
      await within(sheet).findByText(/Matches 2 documents/);
      const sent = posts(calls, "/api/rules/replay/jobs")[0].body as { rule: { when: { zones: unknown } }; place_above: string };
      expect(sent.rule.when.zones).toEqual([
        { box: [0.1, 0.1, 0.5, 0.3], text_contains: ["pohjola"], match: "word_start" },
        { box: [0.1, 0.4, 0.5, 0.5], text_contains: ["vakuutuskirja"], match: "word_start" },
      ]);
      expect(sent.place_above).toBe("pohjola-old");
      await user.click(within(sheet).getByRole("button", { name: "Save" }));
      await waitFor(() => expect(calls.filter((c) => c.method === "PUT")).toHaveLength(1));
      expect(calls.find((c) => c.method === "PUT")?.url).toBe("/api/rules/pohjola?place_above=pohjola-old");
    });

    it("Esc drops the box being drawn, then the last box, then closes the tool", async () => {
      const { user } = setup();
      await user.click(screen.getByRole("button", { name: "Draw a box" }));
      await draw();
      const panel = await screen.findByRole("region", { name: "The boxes" });
      await within(panel).findByText("Pohjola Vakuutus Oy");
      await drawSecond();
      expect(screen.getAllByTestId("kept-box")).toHaveLength(2);
      // a third box, still being dragged
      const surface = screen.getByTestId("box-surface");
      fireEvent.pointerDown(surface, { clientX: 20, clientY: 250, button: 0 });
      fireEvent.pointerMove(surface, { clientX: 100, clientY: 300 });
      expect(screen.getByTestId("drawn-box")).toBeInTheDocument();
      fireEvent.keyDown(document.body, { key: "Escape" });
      expect(screen.queryByTestId("drawn-box")).toBeNull();
      expect(screen.getAllByTestId("kept-box")).toHaveLength(2);
      fireEvent.pointerUp(surface, { clientX: 100, clientY: 300 }); // the cancelled drag draws nothing
      expect(screen.getAllByTestId("kept-box")).toHaveLength(2);
      fireEvent.keyDown(document.body, { key: "Escape" });
      expect(screen.getAllByTestId("kept-box")).toHaveLength(1);
      fireEvent.keyDown(document.body, { key: "Escape" });
      expect(screen.queryByTestId("kept-box")).toBeNull();
      expect(screen.getByTestId("box-surface")).toBeInTheDocument();
      fireEvent.keyDown(document.body, { key: "Escape" });
      expect(screen.queryByTestId("box-surface")).toBeNull();
    });
  });

  it("shows the server's message when the box cannot make a rule", async () => {
    const { user } = setup({ "POST /api/rules/draft-zone": { status: 400, body: { error: "The box holds no usable word." } } });
    await user.click(screen.getByRole("button", { name: "Draw a box" }));
    await draw();
    const panel = await screen.findByRole("region", { name: "The boxes" });
    await within(panel).findByText("Pohjola Vakuutus Oy");
    await user.click(within(panel).getByRole("button", { name: "Make a rule…" }));
    expect(await within(panel).findByText("The box holds no usable word.")).toBeInTheDocument();
  });

  it("Address area for all letters saves the box with the people as they are", async () => {
    const { calls, user } = setup({ "PUT /api/settings/people": { body: PEOPLE } });
    await user.click(screen.getByRole("button", { name: "Draw a box" }));
    await draw();
    const panel = await screen.findByRole("region", { name: "The boxes" });
    expect(within(panel).queryByRole("button", { name: "Address area for this rule's letters" })).toBeNull();
    await waitFor(() => expect(within(panel).getByRole("button", { name: "Address area for all letters" })).toBeEnabled());
    await user.click(within(panel).getByRole("button", { name: "Address area for all letters" }));
    await waitFor(() => expect(calls.filter((c) => c.method === "PUT")).toHaveLength(1));
    expect(calls.find((c) => c.method === "PUT")?.body).toEqual({ people: PEOPLE.people, address_zone: [0.1, 0.1, 0.5, 0.3] });
    expect(await screen.findByText("Address area saved for all letters.")).toBeInTheDocument();
  });

  it("Address area for this rule's letters sets person_zone on the rule behind the suggestion", async () => {
    const { calls, user } = setup(
      { "PUT /api/rules/pohjola": { body: { rules: [RULE], errors: [], state: { offer: true, declined: 0 } } } },
      pdf,
      { suggestion: { name_source: "scan", folder_source: "rule:pohjola" } },
    );
    await user.click(screen.getByRole("button", { name: "Draw a box" }));
    await draw();
    const panel = await screen.findByRole("region", { name: "The boxes" });
    await user.click(await within(panel).findByRole("button", { name: "Address area for this rule's letters" }));
    await waitFor(() => expect(calls.filter((c) => c.method === "PUT")).toHaveLength(1));
    const put = calls.find((c) => c.method === "PUT") as Call;
    expect(put.url).toBe("/api/rules/pohjola?replaces=pohjola");
    expect(put.body).toEqual({
      id: "pohjola",
      when: { text_contains: [], filename_matches: null, folder_is: "##. Organize", zones: RULE.when.zones, person: null },
      then: RULE.then,
      person_zone: [0.1, 0.1, 0.5, 0.3],
      sender: "Pohjola",
    });
  });

  describe("Show areas", () => {
    const AREA = {
      rule_id: "pohjola", index: 0, box: [0.05, 0.02, 0.45, 0.14], kind: "text", lines: [[0.08, 0.04, 0.3, 0.07]],
      score: null, matched: true, reason: null, wins: true,
    };
    const OTHER = { ...AREA, rule_id: "plain", index: 0, box: [0.5, 0.5, 0.9, 0.6], lines: [], wins: false };
    const TITLE = { ...AREA, rule_id: "pohjola", index: 1, box: [0.55, 0.05, 0.95, 0.12], lines: [[0.6, 0.07, 0.9, 0.1]] };
    const ADDRESS = { ...AREA, rule_id: "", index: 0, box: [0.06, 0.1, 0.52, 0.3], kind: "address", lines: [[0.08, 0.15, 0.3, 0.17]], wins: false };
    const withAreas = (areas: object[], extra: object = {}) => ({
      suggestion: { name_source: "scan", folder_source: "rule:pohjola", areas, person: "Tiina", person_line: null, ...extra },
    });

    it("draws the areas of every matching rule, the winning one stronger, with the lines that matched", () => {
      setup({}, pdf, withAreas([AREA, OTHER, TITLE]));
      const win = document.querySelector('[data-area="pohjola:0"]') as HTMLElement;
      expect(win).toHaveStyle({ left: "5%", top: "2%", width: "40%" });
      expect(win).toHaveClass("area-wins");
      expect(document.querySelector('[data-area="plain:0"]')).not.toHaveClass("area-wins");
      // a rule with several areas numbers them
      expect(screen.getByTitle("pohjola (area 2)")).toBeInTheDocument();
      expect(screen.getByTitle("plain")).toBeInTheDocument();
      expect(screen.getAllByTestId("area-line")).toHaveLength(2);
      expect(screen.getAllByTestId("area-line")[0]).toHaveStyle({ left: "8%", top: "4%" });
    });

    it("draws the address area and the line where the person was found", () => {
      setup({}, pdf, withAreas([ADDRESS], { person_line: { box: [0.08, 0.15, 0.3, 0.17] } }));
      expect(screen.getByTitle("Address area")).toHaveStyle({ left: "6%", top: "10%" });
      const line = screen.getByTestId("person-line");
      expect(line).toHaveStyle({ left: "8%", top: "15%" });
      expect(line).toHaveTextContent("For: Tiina, found here");
      // the address area's own lines are the person's line: drawn once
      expect(screen.queryAllByTestId("area-line")).toHaveLength(0);
    });

    it("names a rule's own address area", () => {
      setup({}, pdf, withAreas([{ ...ADDRESS, rule_id: "mail" }]));
      expect(screen.getByTitle("Address area of mail")).toBeInTheDocument();
    });

    it("is on by default when there are areas, and the toggle hides and shows them", async () => {
      const { user } = setup({}, pdf, withAreas([AREA]));
      const toggle = screen.getByRole("button", { name: "Show areas" });
      expect(toggle).toHaveAttribute("aria-pressed", "true");
      expect(screen.getByTitle("pohjola")).toBeInTheDocument();
      await user.click(toggle);
      expect(toggle).toHaveAttribute("aria-pressed", "false");
      expect(screen.queryByTitle("pohjola")).toBeNull();
      await user.click(toggle);
      expect(screen.getByTitle("pohjola")).toBeInTheDocument();
    });

    it("has no toggle when the document has no areas", () => {
      setup({}, pdf, withAreas([]));
      expect(screen.queryByRole("button", { name: "Show areas" })).toBeNull();
      expect(screen.getByRole("button", { name: "Draw a box" })).toBeInTheDocument();
    });
  });

  describe("Changing areas", () => {
    const AREA = {
      rule_id: "pohjola", index: 0, box: [0.05, 0.02, 0.45, 0.14], kind: "text", lines: [], score: null, matched: true, reason: null, wins: true,
    };
    const ADDRESS = (rule_id: string) => ({
      ...AREA, rule_id, box: [0.1, 0.2, 0.6, 0.4], kind: "address", wins: false,
    });
    const tool = (areas: object[]) => ({
      suggestion: { name_source: "scan", folder_source: "rule:pohjola", areas, person: null, person_line: null },
    });
    const SAVED = { body: { rules: [RULE], errors: [], state: { offer: true, declined: 0 } } };
    /** The page is 200 x 400; (10, 8) is the top left corner of the area and (90, 56) its bottom right. */
    function layerSize() {
      const layer = document.querySelector(".page-layer") as HTMLElement;
      layer.getBoundingClientRect = () => ({ left: 0, top: 0, width: 200, height: 400, right: 200, bottom: 400, x: 0, y: 0 }) as DOMRect;
    }
    const area = (id: string) => document.querySelector(`[data-area="${id}"]`) as HTMLElement;
    /** Selects the area, then drags it 20 px to the right and 40 px down: 10 % and 10 % of the page. */
    function drag(id: string) {
      layerSize();
      fireEvent.pointerDown(area(id), { clientX: 50, clientY: 20, button: 0 });
      fireEvent.pointerDown(area(id), { clientX: 50, clientY: 20, button: 0 });
      fireEvent.pointerMove(area(id), { clientX: 70, clientY: 60 });
      fireEvent.pointerUp(area(id), { clientX: 70, clientY: 60 });
    }
    const rounded = (box: number[]) => box.map((v) => Math.round(v * 1000) / 1000);

    it("opens the rule with the moved area and tests it against how the rule did before", async () => {
      const { calls, user } = setup(
        {
          ...replayJob((call: Call) => {
            const zones = (call.body as { rule: { when: { zones: { box: number[] }[] } } }).rule.when.zones;
            return { ...REPLAY, matched: zones[0].box[0] === 0.05 ? 14 : 16, same: 14, marked: null };
          }),
          "PUT /api/rules/pohjola": SAVED,
        },
        pdf,
        tool([AREA]),
      );
      await screen.findByTitle("pohjola");
      drag("pohjola:0");
      const sheet = await screen.findByRole("dialog", { name: "Edit rule pohjola" });
      await within(sheet).findByText(/Matches 16 documents/);
      expect(await within(sheet).findByText(/Before the change it matched 14 documents/)).toBeInTheDocument();
      const sent = posts(calls, "/api/rules/replay/jobs").map((c) => (c.body as { rule: { when: { zones: { box: number[] }[] } }; replaces: string }));
      const moved = sent.find((b) => b.rule.when.zones[0].box[0] !== 0.05);
      expect(rounded(moved?.rule.when.zones[0].box ?? [])).toEqual([0.15, 0.12, 0.55, 0.24]);
      expect(moved?.replaces).toBe("pohjola");
      await user.click(within(sheet).getByRole("button", { name: "Save" }));
      await waitFor(() => expect(calls.filter((c) => c.method === "PUT")).toHaveLength(1));
      const put = calls.find((c) => c.method === "PUT") as Call;
      expect(put.url).toBe("/api/rules/pohjola?replaces=pohjola");
      expect(rounded((put.body as { when: { zones: { box: number[] }[] } }).when.zones[0].box)).toEqual([0.15, 0.12, 0.55, 0.24]);
    });

    it("keeps the rule as it was when the sheet is cancelled", async () => {
      const { calls, user } = setup({ ...replayJob(REPLAY) }, pdf, tool([AREA]));
      await screen.findByTitle("pohjola");
      drag("pohjola:0");
      const sheet = await screen.findByRole("dialog", { name: "Edit rule pohjola" });
      await user.click(within(sheet).getByRole("button", { name: "Cancel" }));
      expect(screen.queryByRole("dialog")).toBeNull();
      expect(calls.filter((c) => c.method === "PUT")).toHaveLength(0);
      expect(area("pohjola:0")).toHaveStyle({ left: "5%", top: "2%" }); // drawn where the rule has it
    });

    it("changes a rule's own address area (person_zone) the same way", async () => {
      const { calls, user } = setup({ ...replayJob(REPLAY), "PUT /api/rules/pohjola": SAVED }, pdf, tool([ADDRESS("pohjola")]));
      await screen.findByTitle("Address area of pohjola");
      drag("pohjola:0");
      const sheet = await screen.findByRole("dialog", { name: "Edit rule pohjola" });
      await within(sheet).findByText(/Matches 2 documents/);
      await user.click(within(sheet).getByRole("button", { name: "Save" }));
      await waitFor(() => expect(calls.filter((c) => c.method === "PUT")).toHaveLength(1));
      const body = calls.find((c) => c.method === "PUT")?.body as { person_zone: number[]; when: { zones: { box: number[] }[] } };
      expect(rounded(body.person_zone)).toEqual([0.2, 0.3, 0.7, 0.5]);
      expect(body.when.zones[0].box).toEqual(RULE.when.zones[0].box); // the rule's words area is untouched
    });

    it("saves the archive-wide address area to the settings after asking", async () => {
      const { calls, user } = setup({ "PUT /api/settings/people": { body: PEOPLE } }, pdf, tool([ADDRESS("")]));
      await screen.findByTitle("Address area");
      drag(":0");
      const sheet = await screen.findByRole("dialog", { name: "Change the address area" });
      expect(calls.filter((c) => c.method === "PUT")).toHaveLength(0);
      await waitFor(() => expect(within(sheet).getByRole("button", { name: "Save" })).toBeEnabled());
      await user.click(within(sheet).getByRole("button", { name: "Save" }));
      await waitFor(() => expect(calls.filter((c) => c.method === "PUT")).toHaveLength(1));
      const body = calls.find((c) => c.method === "PUT")?.body as { people: unknown; address_zone: number[] };
      expect(body.people).toEqual(PEOPLE.people);
      expect(rounded(body.address_zone)).toEqual([0.2, 0.3, 0.7, 0.5]);
      expect(await screen.findByText("Address area saved for all letters.")).toBeInTheDocument();
    });

    it("cuts a picture area again from this document when it is moved, and tests the rule with the new crop", async () => {
      const PICTURE_RULE = {
        ...RULE,
        when: { ...RULE.when, zones: [{ box: [0.05, 0.02, 0.45, 0.14], text_contains: null, image: "areas/pohjola-1.png", min_score: 0.9 }] },
      };
      const { calls, user } = setup(
        {
          "GET /api/rules": { body: { rules: [PICTURE_RULE], errors: [], state: { offer: true, declined: 0 }, unused_pictures: [], default_min_score: 0.85 } },
          "POST /api/rules/area-picture": { body: { width: 3, height: 1, png: "iVBORw0KGgo=", image: "areas/pohjola-2.png" } },
          ...replayJob(REPLAY),
          "PUT /api/rules/pohjola": SAVED,
        },
        pdf,
        tool([{ ...AREA, kind: "image", score: 0.93, lines: [[0.06, 0.03, 0.4, 0.1]] }]),
      );
      await screen.findByTitle("pohjola: picture 0.93");
      expect(screen.getByTestId("area-line")).toHaveClass("area-match");
      drag("pohjola:0");
      const sheet = await screen.findByRole("dialog", { name: "Edit rule pohjola" });
      const cut = posts(calls, "/api/rules/area-picture")[0].body as { drive_id: string; box: number[]; save: boolean; rule_id: string };
      expect(cut).toMatchObject({ drive_id: "d1", save: true, rule_id: "pohjola" });
      expect(rounded(cut.box)).toEqual([0.15, 0.12, 0.55, 0.24]);
      await within(sheet).findByText(/Matches 2 documents/);
      expect(within(sheet).getByRole("img", { name: "Picture of area" })).toHaveAttribute("src", "/api/rules/areas/pohjola-2.png");
      await user.click(within(sheet).getByRole("button", { name: "Save" }));
      await waitFor(() => expect(calls.filter((c) => c.method === "PUT")).toHaveLength(1));
      const body = calls.find((c) => c.method === "PUT")?.body as { when: { zones: { box: number[]; image: string; min_score: number }[] } };
      expect(body.when.zones[0]).toMatchObject({ image: "areas/pohjola-2.png", min_score: 0.9 });
      expect(rounded(body.when.zones[0].box)).toEqual([0.15, 0.12, 0.55, 0.24]);
    });

    describe("a picture area moved twice before the first cut comes back", () => {
      const PICTURE_RULE = {
        ...RULE,
        when: { ...RULE.when, zones: [{ box: [0.05, 0.02, 0.45, 0.14], text_contains: null, image: "areas/pohjola-1.png", min_score: 0.9 }] },
      };
      const OTHER_RULE = {
        ...RULE,
        id: "plain",
        when: { ...RULE.when, zones: [{ box: [0.5, 0.5, 0.9, 0.6], text_contains: ["lasku"], image: null }] },
        person_zone: null,
      };
      const PICTURE_AREA = { ...AREA, kind: "image", score: 0.93, lines: [[0.06, 0.03, 0.4, 0.1]] };
      const TEXT_AREA = { ...AREA, rule_id: "plain", box: [0.5, 0.5, 0.9, 0.6], lines: [], wins: false };
      /** Moves area ``id`` by (dx, dy) pixels on the 200 x 400 page. */
      function move(id: string, dx: number, dy: number) {
        layerSize();
        fireEvent.pointerDown(area(id), { clientX: 50, clientY: 20, button: 0 });
        fireEvent.pointerDown(area(id), { clientX: 50, clientY: 20, button: 0 });
        fireEvent.pointerMove(area(id), { clientX: 50 + dx, clientY: 20 + dy });
        fireEvent.pointerUp(area(id), { clientX: 50 + dx, clientY: 20 + dy });
      }
      function pictureSetup(rules: object[], areas: object[]) {
        const waiting: { box: number[]; rule: string; answer: (image: string) => void }[] = [];
        const made = setup(
          {
            "GET /api/rules": { body: { rules, errors: [], state: { offer: true, declined: 0 }, unused_pictures: [], default_min_score: 0.85 } },
            "POST /api/rules/area-picture": (call) => {
              const body = call.body as { box: number[]; rule_id: string };
              return new Promise((resolve) =>
                waiting.push({ box: body.box, rule: body.rule_id, answer: (image) => resolve({ body: { width: 3, height: 1, png: "iVBORw0KGgo=", image } }) }),
              );
            },
            ...replayJob(REPLAY),
            "PUT /api/rules/pohjola": SAVED,
            "PUT /api/rules/plain": SAVED,
          },
          pdf,
          tool(areas),
        );
        return { ...made, waiting };
      }

      it("uses the newer cut for the newer box when the older reply comes back last", async () => {
        const { calls, user, waiting } = pictureSetup([PICTURE_RULE], [PICTURE_AREA]);
        await screen.findByTitle("pohjola: picture 0.93");
        move("pohjola:0", 20, 40);
        await waitFor(() => expect(waiting).toHaveLength(1));
        move("pohjola:0", 40, 80);
        await waitFor(() => expect(waiting).toHaveLength(2));
        waiting[1].answer("areas/pohjola-3.png");
        const sheet = await screen.findByRole("dialog", { name: "Edit rule pohjola" });
        waiting[0].answer("areas/pohjola-2.png"); // the older cut, late: dropped
        await within(sheet).findByText(/Matches 2 documents/);
        expect(within(sheet).getByRole("img", { name: "Picture of area" })).toHaveAttribute("src", "/api/rules/areas/pohjola-3.png");
        await user.click(within(sheet).getByRole("button", { name: "Save" }));
        await waitFor(() => expect(calls.filter((c) => c.method === "PUT")).toHaveLength(1));
        const body = calls.find((c) => c.method === "PUT")?.body as { when: { zones: { box: number[]; image: string }[] } };
        expect(body.when.zones[0].image).toBe("areas/pohjola-3.png");
        expect(rounded(body.when.zones[0].box)).toEqual([0.25, 0.22, 0.65, 0.34]);
      });

      it("never gives a text area of another rule the picture cut for the first one", async () => {
        const { calls, user, waiting } = pictureSetup([PICTURE_RULE, OTHER_RULE], [PICTURE_AREA, TEXT_AREA]);
        await screen.findByTitle("pohjola: picture 0.93");
        move("pohjola:0", 20, 40);
        await waitFor(() => expect(waiting).toHaveLength(1));
        move("plain:0", 20, 40); // another rule's text area, before the cut is back
        const sheet = await screen.findByRole("dialog", { name: "Edit rule plain" });
        waiting[0].answer("areas/pohjola-2.png"); // late, and not for this rule
        await within(sheet).findByText(/Matches 2 documents/);
        await user.click(within(sheet).getByRole("button", { name: "Save" }));
        await waitFor(() => expect(calls.filter((c) => c.method === "PUT")).toHaveLength(1));
        const put = calls.find((c) => c.method === "PUT") as Call;
        expect(put.url).toBe("/api/rules/plain?replaces=plain");
        const zone = (put.body as { when: { zones: Record<string, unknown>[] } }).when.zones[0];
        expect(zone.image ?? null).toBeNull();
        expect(zone.text_contains).toEqual(["lasku"]);
      });
    });

    it("cannot change areas while the Draw a box tool is on", async () => {
      const { user } = setup({}, pdf, tool([AREA]));
      await screen.findByTitle("pohjola");
      await user.click(screen.getByRole("button", { name: "Draw a box" }));
      await screen.findByTestId("box-surface");
      expect(area("pohjola:0")).not.toHaveClass("area-editable");
    });
  });

  it("asks for the suggestion itself when the preview was not given one", async () => {
    const { calls } = setup(
      {
        "GET /api/files/d1/suggestions": {
          body: {
            name_source: "scan",
            folder_source: "rule:pohjola",
            areas: [{ rule_id: "pohjola", index: 0, box: [0.05, 0.02, 0.45, 0.14], kind: "text", lines: [], score: null, matched: true, reason: null, wins: true }],
            person_line: null,
          },
        },
      },
      pdf,
      {},
    );
    await screen.findByTitle("pohjola");
    expect(calls.filter((c) => c.url === "/api/files/d1/suggestions")).toHaveLength(1);
  });
});

describe("Picture areas", () => {
  const CROP = { width: 3, height: 1, png: "iVBORw0KGgo=", image: null };
  const PICTURE_DRAFT = {
    ...DRAFT,
    words: [],
    zones: [],
    pictures: [{ box: [0.1, 0.1, 0.5, 0.3], image: "areas/pohjola-1.png", width: 3, height: 1, png: "iVBORw0KGgo=" }],
  };
  const SAVED = { body: { rules: [], errors: [], state: { offer: true, declined: 0 } } };

  async function drawAndOpen(user: ReturnType<typeof userEvent.setup>) {
    await user.click(screen.getByRole("button", { name: "Draw a box" }));
    await draw();
    return screen.findByRole("region", { name: "The boxes" });
  }

  const row = (panel: HTMLElement, n: number) => within(within(panel).getByRole("list", { name: "Boxes" })).getByText(`Box ${n}`).closest("li") as HTMLElement;

  it("a box that comes back without text switches to its picture by itself, with the crop shown in its row", async () => {
    const { calls, user } = setup({
      "POST /api/files/d1/page1/lines": { body: READ },
      "POST /api/rules/area-picture": { body: CROP },
    });
    const panel = await drawAndOpen(user);
    await within(panel).findByRole("img", { name: "Picture of box 1" });
    expect(posts(calls, "/api/rules/area-picture")[0].body).toEqual({
      drive_id: "d1",
      box: [0.1, 0.1, 0.5, 0.3],
      save: false,
      rule_id: null,
    });
    const kept = within(panel).getByRole("list", { name: "Boxes" });
    expect(await within(kept).findByRole("img", { name: "Picture of box 1" })).toHaveAttribute("src", "data:image/png;base64,iVBORw0KGgo=");
    expect(within(row(panel, 1)).getByRole("button", { name: "Picture" })).toHaveAttribute("aria-pressed", "true");
    // Words / Picture is the same segmented control as the rule sheet's Anyone / Only for
    const group = within(row(panel, 1)).getByRole("group", { name: "What box 1 matches" });
    expect(group).toHaveClass("segmented");
    expect(within(group).getByRole("button", { name: "Picture" })).toHaveClass("segmented-option");
    expect(within(group).getByRole("button", { name: "Words" })).toHaveClass("segmented-option");
    expect(within(group).getByRole("button", { name: "Words" })).toHaveAttribute("aria-pressed", "false");
    expect(screen.getAllByTestId("kept-box")).toHaveLength(1);
    expect(within(panel).getByText(/Add a text box to make this faster and surer/)).toBeInTheDocument();
    expect(within(panel).getByRole("button", { name: "Make a rule…" })).toBeEnabled();
    // back to its words, which can be done at will: no second cut is asked for later
    await user.click(within(row(panel, 1)).getByRole("button", { name: "Words" }));
    expect(within(panel).getByText("No text found")).toBeInTheDocument();
    expect(within(panel).getByRole("button", { name: "Make a rule…" })).toBeDisabled();
    await user.click(within(row(panel, 1)).getByRole("button", { name: "Picture" }));
    expect(posts(calls, "/api/rules/area-picture")).toHaveLength(1);
  });

  it("a box with only OCR noise switches to its picture too, and a box with text stays on its words", async () => {
    const { user } = setup({
      "POST /api/files/d1/page1/lines": { body: { read: true, lines: [{ text: "•ö |", box: [0.1, 0.1, 0.5, 0.2] }], unavailable: null } },
      "POST /api/rules/area-picture": { body: CROP },
    });
    const panel = await drawAndOpen(user);
    await within(panel).findByRole("img", { name: "Picture of box 1" });
    expect(within(row(panel, 1)).getByRole("button", { name: "Picture" })).toHaveAttribute("aria-pressed", "true");
  });

  it("a box with text stays on its words and asks for no picture", async () => {
    const { calls, user } = setup({ "POST /api/rules/area-picture": { body: CROP } });
    const panel = await drawAndOpen(user);
    await within(panel).findByText("Pohjola Vakuutus Oy");
    expect(within(row(panel, 1)).getByRole("button", { name: "Words" })).toHaveAttribute("aria-pressed", "true");
    expect(posts(calls, "/api/rules/area-picture")).toHaveLength(0);
  });

  it("every box has the choice, and the address choices never take a picture", async () => {
    const { user } = setup({ "POST /api/rules/area-picture": { body: CROP } });
    const panel = await drawAndOpen(user);
    await within(panel).findByText("Pohjola Vakuutus Oy");
    expect(within(row(panel, 1)).getByRole("button", { name: "Words" })).toHaveAttribute("aria-pressed", "true");
    expect(within(panel).getByRole("button", { name: "Address area for all letters" })).toBeInTheDocument();
    await user.click(within(row(panel, 1)).getByRole("button", { name: "Picture" }));
    await within(panel).findByRole("img", { name: "Picture of box 1" });
    expect(within(panel).queryByRole("button", { name: /^Address area/ })).toBeNull();
  });

  it("a text box next to a picture box needs no hint, and both are sent to the draft", async () => {
    const { calls, user } = setup({
      "POST /api/rules/area-picture": { body: CROP },
      "POST /api/rules/draft-zone": { body: { ...PICTURE_DRAFT, zones: DRAFT.zones } },
      ...replayJob(REPLAY),
    });
    const panel = await drawAndOpen(user);
    await within(panel).findByText("Pohjola Vakuutus Oy");
    await user.click(within(row(panel, 1)).getByRole("button", { name: "Picture" }));
    await within(panel).findByRole("img", { name: "Picture of box 1" });
    await draw(); // the next box, with text
    await waitFor(() => expect(within(row(panel, 2)).getByText("Pohjola Vakuutus Oy")).toBeInTheDocument());
    expect(within(panel).queryByText(/Add a text box to make this faster and surer/)).toBeNull();
    await user.click(within(panel).getByRole("button", { name: "Make a rule…" }));
    expect(posts(calls, "/api/rules/draft-zone")[0].body).toEqual({
      drive_id: "d1",
      boxes: [[0.1, 0.1, 0.5, 0.3]],
      picture_boxes: [[0.1, 0.1, 0.5, 0.3]],
    });
    const sheet = await screen.findByRole("dialog", { name: "Make a rule" });
    expect(within(sheet).getAllByRole("group", { name: /^Area/ })).toHaveLength(2);
    expect(within(sheet).queryByText(/Add a text box to make this faster and surer/)).toBeNull();
  });

  it("Make a rule… from a picture alone shows the crop and the score, and tests and saves the picture zone", async () => {
    const scores = [
      { path: "Insurance/a.pdf", drive_id: "a", score: 0.93, matched: true },
      { path: "10. Bank/b.pdf", drive_id: "b", score: 0.78, matched: false, needed: 0.85 },
    ];
    const { calls, user } = setup({
      "POST /api/files/d1/page1/lines": { body: READ },
      "POST /api/rules/area-picture": { body: CROP },
      "POST /api/rules/draft-zone": { body: PICTURE_DRAFT },
      ...replayJob({ ...REPLAY, scores }),
      "PUT /api/rules/pohjola": SAVED,
    });
    const panel = await drawAndOpen(user);
    await within(panel).findByRole("img", { name: "Picture of box 1" });
    await user.click(within(panel).getByRole("button", { name: "Make a rule…" }));
    expect(posts(calls, "/api/rules/draft-zone")[0].body).toEqual({
      drive_id: "d1",
      boxes: [],
      picture_boxes: [[0.1, 0.1, 0.5, 0.3]],
    });
    const sheet = await screen.findByRole("dialog", { name: "Make a rule" });
    const group = within(sheet).getByRole("group", { name: "Area" });
    expect(within(group).getByRole("img", { name: "Picture of area" })).toHaveAttribute("src", "/api/rules/areas/pohjola-1.png");
    const slider = within(group).getByRole("slider", { name: "Match needed for area" });
    expect(slider).toHaveValue("0.85");
    expect(within(sheet).getByText(/Add a text box to make this faster and surer/)).toBeInTheDocument();
    // the replay shows how far apart matches and non-matches are
    const result = await within(sheet).findByRole("region", { name: "Picture scores" });
    expect(within(result).getByText(/0\.85 is needed/)).toBeInTheDocument();
    expect(within(within(result).getByRole("list", { name: "Matched documents" })).getByText("0.93")).toBeInTheDocument();
    expect(within(within(result).getByRole("list", { name: "Documents close to matching" })).getByText("0.78")).toBeInTheDocument();
    expect((posts(calls, "/api/rules/replay/jobs")[0].body as { rule: { when: { zones: unknown } } }).rule.when.zones).toEqual([
      { box: [0.1, 0.1, 0.5, 0.3], image: "areas/pohjola-1.png" },
    ]);
    // moving the slider sets min_score and tests again
    fireEvent.change(slider, { target: { value: "0.9" } });
    await waitFor(() => expect(posts(calls, "/api/rules/replay/jobs")).toHaveLength(2));
    expect((posts(calls, "/api/rules/replay/jobs")[1].body as { rule: { when: { zones: unknown } } }).rule.when.zones).toEqual([
      { box: [0.1, 0.1, 0.5, 0.3], image: "areas/pohjola-1.png", min_score: 0.9 },
    ]);
    await within(sheet).findByText(/0\.90 is needed/);
    await waitFor(() => expect(within(sheet).getByRole("button", { name: "Save" })).toBeEnabled());
    await user.click(within(sheet).getByRole("button", { name: "Save" }));
    // the replay lists no differences, so it saves at once
    await waitFor(() => expect(calls.filter((c) => c.method === "PUT")).toHaveLength(1));
    expect((calls.find((c) => c.method === "PUT")?.body as { when: { zones: unknown } }).when.zones).toEqual([
      { box: [0.1, 0.1, 0.5, 0.3], image: "areas/pohjola-1.png", min_score: 0.9 },
    ]);
  });

  it("shows the server's message in the box row when the picture of page 1 is not made yet, and goes back to words", async () => {
    const { user } = setup({
      "POST /api/rules/area-picture": () => ({ status: 400, body: { error: "The picture of page 1 of this document is not made yet. Try again in a moment." } }),
    });
    const panel = await drawAndOpen(user);
    await within(panel).findByText("Pohjola Vakuutus Oy");
    await user.click(within(row(panel, 1)).getByRole("button", { name: "Picture" }));
    expect(await within(panel).findByText(/not made yet/)).toBeInTheDocument();
    expect(within(row(panel, 1)).getByRole("button", { name: "Words" })).toHaveAttribute("aria-pressed", "true");
  });

  it("shows the message for a box with nothing in it on its own line under the box, not inside its text", async () => {
    const { user } = setup({
      "POST /api/rules/area-picture": () => ({ status: 400, body: { error: "There is nothing in that area: no text and no picture." } }),
    });
    const panel = await drawAndOpen(user);
    await within(panel).findByText("Pohjola Vakuutus Oy");
    await user.click(within(row(panel, 1)).getByRole("button", { name: "Picture" }));
    const message = await within(panel).findByText("There is nothing in that area: no text and no picture.");
    expect(message).toHaveClass("box-kept-problem");
    expect(message.closest(".box-kept-text")).toBeNull();
    expect(message.parentElement).toBe(row(panel, 1));
    expect(message.textContent).not.toMatch(/of page 1/);
  });
});

describe("Diagnosing a picture rule on a document", () => {
  const PICTURE_RULE = {
    ...RULE,
    id: "kela",
    when: { ...RULE.when, zones: [{ box: [0.05, 0.03, 0.35, 0.1], text_contains: null, image: "areas/kela-1.png", min_score: null }] },
  };
  const RULES = { rules: [PICTURE_RULE], errors: [], state: { offer: true, declined: 0 }, default_min_score: 0.85 };
  const area = (over: object) => ({
    rule_id: "kela", index: 0, box: [0.05, 0.03, 0.35, 0.1], kind: "image", lines: [], score: null,
    matched: false, reason: null, wins: false, ...over,
  });
  // ``picture_miss``: only the picture held the rule back (a near miss, drawn for diagnosis)
  const explain = (areas: object[], picture_miss = true) => [{ rule_id: "kela", matched: false, why: "x", wins: [], zone_lines: [[]], areas, picture_miss }];

  it("shows where a picture rule that did not match fits best on this page, with its score", async () => {
    setup({
      "GET /api/rules": { body: RULES },
      "POST /api/rules/explain": {
        body: explain([area({ score: 0.71, lines: [[0.06, 0.04, 0.3, 0.09]], reason: "picture 0.71, needs 0.85" })]),
      },
    });
    const shown = await screen.findByTestId("area-line");
    expect(shown).toBeInTheDocument();
    const drawn = document.querySelector('[data-area="kela:0"]') as HTMLElement;
    expect(drawn).toHaveAttribute("data-matched", "false");
    expect(drawn).toHaveAttribute("title", "kela: picture 0.71, needs 0.85");
  });

  it("says why a score could not be worked out", async () => {
    setup({
      "GET /api/rules": { body: RULES },
      "POST /api/rules/explain": { body: explain([area({ reason: "the picture of page 1 is not made yet" })]) },
    });
    await waitFor(() => expect(document.querySelector('[data-area="kela:0"]')).not.toBeNull());
    expect(document.querySelector('[data-area="kela:0"]')).toHaveAttribute("title", "kela: the picture of page 1 is not made yet");
  });

  it("draws nothing for a picture rule whose words do not fit this document", async () => {
    // a new picture rule's areas showed on every other document of the Inbox
    const { calls } = setup({
      "GET /api/rules": { body: RULES },
      "POST /api/rules/explain": { body: explain([area({ reason: "no word found in area 1" })], false) },
    });
    await waitFor(() => expect(posts(calls, "/api/rules/explain")).toHaveLength(1));
    await screen.findByRole("button", { name: "Draw a box" });
    expect(document.querySelector('[data-area="kela:0"]')).toBeNull();
  });

  it("asks for nothing when no rule has a picture area", async () => {
    const { calls } = setup();
    await screen.findByRole("button", { name: "Draw a box" });
    await waitFor(() => expect(calls.some((c) => c.url === "/api/rules")).toBe(true));
    expect(posts(calls, "/api/rules/explain")).toHaveLength(0);
  });

  it("draws the rule being tested instead, from the areas the API gives for this document", async () => {
    const testRule = { id: "kela", when: { text_contains: [], zones: [{ box: [0.05, 0.03, 0.35, 0.1], image: "areas/kela-1.png" }] }, then: {} };
    const { calls } = setup(
      {
        "POST /api/rules/areas-for": {
          body: { areas: [area({ score: 0.93, matched: true, lines: [[0.06, 0.04, 0.3, 0.09]] })] },
        },
      },
      pdf,
      { testRule } as never,
    );
    await screen.findByTestId("area-line");
    expect(posts(calls, "/api/rules/areas-for")[0].body).toEqual({ rule: testRule, drive_id: "d1" });
    expect(posts(calls, "/api/rules/explain")).toHaveLength(0);
    expect(document.querySelector('[data-area="kela:0"]')).toHaveAttribute("title", "kela: picture 0.93");
  });
});
