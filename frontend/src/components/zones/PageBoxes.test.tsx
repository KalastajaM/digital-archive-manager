import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { type Call, mockFetch, renderWithProviders } from "../../test-utils";
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
  when: { text_contains: [], filename_matches: null, folder_is: "##. Organize", zone: { box: [0.05, 0.02, 0.45, 0.14], text_contains: ["pohjola"] }, person: null },
  then: { folder: "Insurance/Pohjola", name: null, tags: [], tray: null, payee: null },
  person_zone: [0.1, 0.2, 0.6, 0.4],
  sender: "Pohjola",
  stats: { suggested: 3, changed: 0, last_used: null, flagged: false },
};
const DRAFT = {
  id: "pohjola",
  words: [{ word: "pohjola", ticked: true }, { word: "vakuutus", ticked: false }],
  folder: "Insurance/Pohjola",
  name: null,
  tags: [],
  tray: null,
  payee: null,
  box: [0.1, 0.1, 0.5, 0.3],
  folder_is: "##. Organize",
  lines: ["Pohjola Vakuutus Oy"],
  sender: "Pohjola",
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
    const panel = await screen.findByRole("region", { name: "The box" });
    expect(await within(panel).findByText("Pohjola Vakuutus Oy")).toBeInTheDocument();
    expect(posts(calls, "/api/files/d1/page1/lines")[0].body).toEqual({ box: [0.1, 0.1, 0.5, 0.3] });
    expect(screen.getByTestId("drawn-box")).toHaveStyle({ left: "10%", top: "10%", width: "40%", height: "20%" });
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
    expect(screen.queryByRole("region", { name: "The box" })).toBeNull();
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
    expect(await screen.findByText("No text found in this box.")).toBeInTheDocument();
  });

  it("Sender… drafts a rule from the box and opens the rule sheet with the area", async () => {
    const { calls, user } = setup({
      "POST /api/rules/draft-zone": { body: DRAFT },
      "POST /api/rules/replay": { body: REPLAY },
      "PUT /api/rules/pohjola": { body: { rules: [], errors: [], state: { offer: true, declined: 0 } } },
    });
    await user.click(screen.getByRole("button", { name: "Draw a box" }));
    await draw();
    const panel = await screen.findByRole("region", { name: "The box" });
    await user.click(within(panel).getByRole("button", { name: "Sender…" }));
    await user.click(await within(panel).findByRole("button", { name: "Pohjola" })); // a sender in use
    await user.click(within(panel).getByRole("button", { name: "Make a rule…" }));
    expect(posts(calls, "/api/rules/draft-zone")[0].body).toEqual({ drive_id: "d1", box: [0.1, 0.1, 0.5, 0.3], sender: "Pohjola" });
    const sheet = await screen.findByRole("dialog", { name: "Make a rule" });
    expect(within(sheet).getByRole("button", { name: "pohjola" })).toHaveAttribute("aria-pressed", "true");
    expect(within(sheet).getByText("Matches only in the area you drew on page 1.")).toBeInTheDocument();
    await within(sheet).findByText(/Matches 2 documents/);
    const sent = posts(calls, "/api/rules/replay")[0].body as { rule: { when: unknown; sender: string } };
    expect(sent.rule.when).toEqual({
      text_contains: [],
      filename_matches: null,
      folder_is: "##. Organize",
      zone: { box: [0.1, 0.1, 0.5, 0.3], text_contains: ["pohjola"] },
    });
    expect(sent.rule.sender).toBe("Pohjola");
    await user.click(within(sheet).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(calls.filter((c) => c.method === "PUT")).toHaveLength(1));
    expect(calls.find((c) => c.method === "PUT")?.body).toMatchObject({
      id: "pohjola",
      when: { zone: { box: [0.1, 0.1, 0.5, 0.3], text_contains: ["pohjola"] } },
      sender: "Pohjola",
    });
  });

  it("shows the server's message when the box cannot make a rule", async () => {
    const { user } = setup({ "POST /api/rules/draft-zone": { status: 400, body: { error: "The box holds no usable word." } } });
    await user.click(screen.getByRole("button", { name: "Draw a box" }));
    await draw();
    const panel = await screen.findByRole("region", { name: "The box" });
    await user.click(within(panel).getByRole("button", { name: "Sender…" }));
    await user.click(within(panel).getByRole("button", { name: "Make a rule…" }));
    expect(await within(panel).findByText("The box holds no usable word.")).toBeInTheDocument();
  });

  it("Address area for all letters saves the box with the people as they are", async () => {
    const { calls, user } = setup({ "PUT /api/settings/people": { body: PEOPLE } });
    await user.click(screen.getByRole("button", { name: "Draw a box" }));
    await draw();
    const panel = await screen.findByRole("region", { name: "The box" });
    expect(within(panel).queryByRole("button", { name: "Address area for this sender" })).toBeNull();
    await waitFor(() => expect(within(panel).getByRole("button", { name: "Address area for all letters" })).toBeEnabled());
    await user.click(within(panel).getByRole("button", { name: "Address area for all letters" }));
    await waitFor(() => expect(calls.filter((c) => c.method === "PUT")).toHaveLength(1));
    expect(calls.find((c) => c.method === "PUT")?.body).toEqual({ people: PEOPLE.people, address_zone: [0.1, 0.1, 0.5, 0.3] });
    expect(await screen.findByText("Address area saved for all letters.")).toBeInTheDocument();
  });

  it("Address area for this sender sets person_zone on the rule behind the suggestion", async () => {
    const { calls, user } = setup(
      { "PUT /api/rules/pohjola": { body: { rules: [RULE], errors: [], state: { offer: true, declined: 0 } } } },
      pdf,
      { suggestion: { name_source: "scan", folder_source: "rule:pohjola" } },
    );
    await user.click(screen.getByRole("button", { name: "Draw a box" }));
    await draw();
    const panel = await screen.findByRole("region", { name: "The box" });
    await user.click(await within(panel).findByRole("button", { name: "Address area for this sender" }));
    await waitFor(() => expect(calls.filter((c) => c.method === "PUT")).toHaveLength(1));
    const put = calls.find((c) => c.method === "PUT") as Call;
    expect(put.url).toBe("/api/rules/pohjola?replaces=pohjola");
    expect(put.body).toEqual({
      id: "pohjola",
      when: { text_contains: [], filename_matches: null, folder_is: "##. Organize", zone: RULE.when.zone, person: null },
      then: RULE.then,
      person_zone: [0.1, 0.1, 0.5, 0.3],
      sender: "Pohjola",
    });
  });

  it("shows the zones of the rule behind the suggestion faintly on page 1", async () => {
    setup({}, pdf, { suggestion: { name_source: "scan", folder_source: "rule:pohjola" } });
    const area = await screen.findByTitle("Rule pohjola looks here");
    expect(area).toHaveStyle({ left: "5%", top: "2%", width: "40%" });
    expect(screen.getByTitle("Rule pohjola looks for the address here")).toHaveStyle({ left: "10%", top: "20%" });
  });

  it("asks for the suggestion itself when the preview was not given one", async () => {
    const { calls } = setup(
      { "GET /api/files/d1/suggestions": { body: { name_source: "scan", folder_source: "rule:pohjola" } } },
      pdf,
      {},
    );
    await screen.findByTitle("Rule pohjola looks here");
    expect(calls.filter((c) => c.url === "/api/files/d1/suggestions")).toHaveLength(1);
  });
});
