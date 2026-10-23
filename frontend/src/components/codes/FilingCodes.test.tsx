import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it } from "vitest";
import { type Call, mockFetch, renderWithProviders } from "../../test-utils";
import { FilingCodes, fixedName, forgetKeptEdits } from "./FilingCodes";

const code = (c: string, label: string, extra: object = {}) => ({
  code: c,
  label,
  tray: null,
  folder: null,
  name: null,
  tags: [],
  collections: [],
  as_suggested: false,
  inbox_folder: null,
  ...extra,
});
const SEEDED = [
  code("A", "To action", { tray: "to-action" }),
  code("P", "To pay", { tray: "to-pay", folder: "11. Bills/{year}", name: "{doc_date:%Y%m%d}_{stem}" }),
  code("D", "File as suggested", { as_suggested: true }),
];
const TRAYS = {
  trays: [
    { id: "to-action", name: "To action" },
    { id: "to-pay", name: "To pay" },
  ],
  skipped: [],
};
const MKDIR = (path: string) => ({ kind: "mkdir", src: null, dst: path });
const ECHO = { "PUT /api/filing-codes": (c: Call) => ({ body: { codes: c.body, problems: [], warnings: [] } }) };

function setup(over: Record<string, unknown> = {}, table: { codes?: unknown[]; problems?: unknown[]; warnings?: unknown[] } = {}) {
  const calls = mockFetch({
    "GET /api/filing-codes": { body: { codes: SEEDED, problems: [], warnings: [], ...table } },
    "GET /api/filing-codes/folders": { body: { missing: [], stray: [] } },
    "GET /api/trays": { body: TRAYS },
    "GET /api/folders": { body: ["10. Financial"] },
    "GET /api/collections": { body: [] },
    "GET /api/filing-codes/sheets": { body: [] },
    ...over,
  } as never);
  const view = renderWithProviders(
    <MemoryRouter>
      <FilingCodes />
    </MemoryRouter>,
  );
  return { calls, user: userEvent.setup(), view };
}
const ofMethod = (calls: Call[], method: string, url: string) => calls.filter((c) => c.method === method && c.url === url);
/** The closed line of a code: the button that opens it. */
const line = (name: RegExp) => screen.getByRole("button", { name });
/** Open a code's editor by its line; returns the editor. */
async function openCode(user: ReturnType<typeof userEvent.setup>, name: RegExp) {
  await user.click(await screen.findByRole("button", { name }));
  return screen.getByRole("group", { name: /^Code / });
}

beforeEach(() => forgetKeptEdits());

describe("Filing codes (Settings)", () => {
  it("lists each code as one line: sticker, code, label and what it does", async () => {
    setup();
    await screen.findByRole("button", { name: /^A To action/ });
    expect(line(/^A To action/)).toHaveTextContent("→ To action");
    expect(line(/^P To pay/)).toHaveTextContent("→ To pay · 11. Bills/{year} · {doc_date:%Y%m%d}_{stem}");
    expect(line(/^D File as suggested/)).toHaveTextContent("File as suggested, no tray");
    expect(screen.queryByRole("group", { name: /^Code / })).toBeNull(); // all closed
    expect(screen.queryByRole("region", { name: "Unsaved changes" })).toBeNull();
    expect(screen.getByRole("link", { name: "More in Help" })).toHaveAttribute("href", "/help#filing-codes");
  });

  it("opens one code at a time, with its fields", async () => {
    const { user } = setup();
    let editor = await openCode(user, /^A To action/);
    expect(within(editor).getByLabelText("Code")).toHaveValue("A");
    expect(within(editor).getByLabelText("Tray")).toHaveValue("to-action");
    expect(within(editor).getByLabelText("Label")).toHaveAttribute("maxLength", "24");
    editor = await openCode(user, /^D File as suggested/);
    expect(within(editor).getByLabelText("File as suggested")).toBeChecked();
    expect(screen.getAllByRole("group", { name: /^Code / })).toHaveLength(1);
    await user.click(within(editor).getByRole("button", { name: "Done" }));
    expect(screen.queryByRole("group", { name: /^Code / })).toBeNull();
  });

  it("warns while editing that a code is easy to confuse, and flags it on the closed lines", async () => {
    const { calls, user } = setup({}, { codes: [...SEEDED, code("0", "Zero")] });
    await screen.findByRole("button", { name: /^A To action/ });
    await user.click(screen.getByRole("button", { name: "Add a code" }));
    const added = screen.getByRole("group", { name: /^Code / }); // a new code opens at once
    const field = within(added).getByLabelText("Code");
    await user.type(field, "O");
    expect(within(added).getByText(/Easy to confuse with/)).toHaveTextContent("Easy to confuse with D, 0 if you write codes by hand.");
    expect(line(/^0 Zero/)).toHaveTextContent("Easy to confuse with D, O"); // D, O and 0 look alike
    await user.clear(field);
    await user.type(field, "K");
    expect(within(added).queryByText(/Easy to confuse with/)).toBeNull();
    expect(line(/^0 Zero/)).toHaveTextContent("Easy to confuse with D");
    expect(ofMethod(calls, "PUT", "/api/filing-codes")).toHaveLength(0);
  });

  it("Name pattern warns when every file would get the same name", async () => {
    const { user } = setup({}, { codes: [code("K", "Kela")] });
    const editor = await openCode(user, /^K Kela/);
    const field = within(editor).getByLabelText("Name pattern");
    expect(field).toHaveAttribute("placeholder", "{doc_date:%Y%m%d}_{stem}");
    await user.type(field, "Kela letter");
    expect(within(editor).getByText(/Every file with this code gets the same name/)).toBeInTheDocument();
    await user.click(within(editor).getByRole("button", { name: "Done" }));
    expect(line(/^K Kela/)).toHaveTextContent("Same name for every file");
    await openCode(user, /^K Kela/);
    const again = within(screen.getByRole("group", { name: /^Code / })).getByLabelText("Name pattern");
    await user.clear(again);
    await user.type(again, "{{doc_date:%Y%m%d}_Kela");
    expect(screen.queryByText(/Every file with this code gets the same name/)).toBeNull();
  });

  it("a name pattern is fixed unless it uses the date or the file's own name", () => {
    expect(fixedName("")).toBe(false);
    expect(fixedName("Kela letter")).toBe(true);
    expect(fixedName("{year}_Kela")).toBe(true);
    expect(fixedName("{doc_date:%Y%m%d}_Kela")).toBe(false);
    expect(fixedName("Kela_{stem}")).toBe(false);
  });

  it("the save bar shows only with unsaved edits; Save sends the whole edited list", async () => {
    const { calls, user } = setup(ECHO);
    let editor = await openCode(user, /^P To pay/);
    await user.click(within(editor).getByRole("button", { name: "Remove code P" }));
    const bar = screen.getByRole("region", { name: "Unsaved changes" });
    await user.click(screen.getByRole("button", { name: "Add a code" }));
    editor = screen.getByRole("group", { name: /^Code / });
    await user.type(within(editor).getByLabelText("Code"), "T");
    await user.type(within(editor).getByLabelText("Label"), "Taxes");
    await user.type(within(editor).getByLabelText("Tags"), "tax, 2026");
    await user.selectOptions(within(editor).getByLabelText("Tray"), "to-pay");
    await user.click(within(bar).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(ofMethod(calls, "PUT", "/api/filing-codes")).toHaveLength(1));
    const body = ofMethod(calls, "PUT", "/api/filing-codes")[0].body as Array<Record<string, unknown>>;
    expect(body.map((c) => c.code)).toEqual(["A", "D", "T"]);
    expect(body[2]).toMatchObject({ label: "Taxes", tags: ["tax", "2026"], tray: "to-pay", folder: null, as_suggested: false });
  });

  it("Discard puts the saved table back", async () => {
    const { calls, user } = setup(ECHO);
    const editor = await openCode(user, /^A To action/);
    await user.clear(within(editor).getByLabelText("Label"));
    await user.type(within(editor).getByLabelText("Label"), "Later");
    await user.click(within(screen.getByRole("region", { name: "Unsaved changes" })).getByRole("button", { name: "Discard" }));
    expect(line(/^A To action/)).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Unsaved changes" })).toBeNull();
    expect(ofMethod(calls, "PUT", "/api/filing-codes")).toHaveLength(0);
  });

  it("keeps unsaved edits when the section goes away and comes back", async () => {
    const first = setup();
    const editor = await openCode(first.user, /^A To action/);
    await first.user.clear(within(editor).getByLabelText("Label"));
    await first.user.type(within(editor).getByLabelText("Label"), "Kept");
    first.view.unmount();
    setup();
    const back = await screen.findByRole("group", { name: "Code A" }); // still open, as left
    expect(within(back).getByLabelText("Label")).toHaveValue("Kept");
    expect(screen.getByRole("region", { name: "Unsaved changes" })).toBeInTheDocument();
  });

  it("asks before the tab closes with unsaved edits", async () => {
    const { user } = setup();
    const event = () => {
      const e = new Event("beforeunload", { cancelable: true });
      window.dispatchEvent(e);
      return e.defaultPrevented;
    };
    const editor = await openCode(user, /^A To action/);
    expect(event()).toBe(false);
    await user.type(within(editor).getByLabelText("Label"), "!");
    expect(event()).toBe(true);
  });

  it("each code shows its sticker, redrawn from the code and label as typed", async () => {
    const { user } = setup();
    const editor = await openCode(user, /^A To action/);
    expect(within(editor).getByRole("img")).toHaveAttribute("src", "/api/filing-codes/sticker?code=A&label=To+action");
    await user.clear(within(editor).getByLabelText("Label"));
    await user.type(within(editor).getByLabelText("Label"), "Do it");
    await waitFor(() => expect(within(editor).getByRole("img")).toHaveAttribute("src", "/api/filing-codes/sticker?code=A&label=Do+it"));
    await user.clear(within(editor).getByLabelText("Code"));
    expect(await within(editor).findByText("No code yet")).toBeInTheDocument();
    await user.type(within(editor).getByLabelText("Code"), "A-1");
    expect(await within(editor).findByText("Not a valid code")).toBeInTheDocument();
  });

  it("collections are picked like folders, and one typed but not added is saved too", async () => {
    const { calls, user } = setup(ECHO);
    const editor = await openCode(user, /^A To action/);
    const field = within(editor).getByLabelText("Collections");
    await user.type(field, "Taxes 2026{Enter}");
    expect(within(editor).getByRole("list", { name: "Collections to add" })).toHaveTextContent("Taxes 2026");
    await user.type(field, "Car");
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(ofMethod(calls, "PUT", "/api/filing-codes")).toHaveLength(1));
    const body = ofMethod(calls, "PUT", "/api/filing-codes")[0].body as Array<Record<string, unknown>>;
    expect(body[0].collections).toEqual(["Taxes 2026", "Car"]);
  });

  it("a refused save shows its message in the bar and keeps the edits", async () => {
    const { user } = setup({ "PUT /api/filing-codes": { status: 400, body: { error: "Code 'A' is repeated" } } });
    const editor = await openCode(user, /^P To pay/);
    await user.clear(within(editor).getByLabelText("Code"));
    await user.type(within(editor).getByLabelText("Code"), "A");
    await user.click(screen.getByRole("button", { name: "Save" }));
    const bar = screen.getByRole("region", { name: "Unsaved changes" });
    expect(await within(bar).findByRole("alert")).toHaveTextContent("Code 'A' is repeated");
    expect(within(screen.getByRole("group", { name: "Code A" })).getByLabelText("Code")).toHaveValue("A");
  });

  it("shows problems at the top, and the bar says that saving drops them", async () => {
    const { user } = setup({}, { problems: [{ code: "Q", message: "names an unknown tray" }] });
    expect(await screen.findByText(/names an unknown tray/)).toBeInTheDocument();
    const editor = await openCode(user, /^A To action/);
    await user.type(within(editor).getByLabelText("Label"), "!");
    expect(screen.getByRole("region", { name: "Unsaved changes" })).toHaveTextContent(
      "Unsaved changes. Saving removes the entries with problems from the file (a backup is kept).",
    );
  });

  it("missing and stray inbox folders are notices; Create inbox folders previews and posts on confirm", async () => {
    const { calls, user } = setup({
      "GET /api/filing-codes/folders": { body: { missing: ["A", "P"], stray: ["Old"] } },
      "POST /api/filing-codes/folders/preview": { body: [MKDIR("00. Inbox"), MKDIR("00. Inbox/A"), MKDIR("00. Inbox/P")] },
      "POST /api/filing-codes/folders": { body: { batch_id: "b1", ops: [] } },
    });
    expect(await screen.findByText(/2 codes' inbox folders are missing/)).toHaveTextContent("A, P");
    expect(screen.getByText(/belongs to no code, so the files in it are not in the Inbox/)).toHaveTextContent("Old");
    await user.click(screen.getByRole("button", { name: "Create inbox folders…" }));
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent("00. Inbox/A");
    expect(dialog).toHaveTextContent("00. Inbox/P");
    expect(within(dialog).getAllByText("New folder")).toHaveLength(3);
    expect(ofMethod(calls, "POST", "/api/filing-codes/folders")).toHaveLength(0);
    await user.click(within(dialog).getByRole("button", { name: "Create folders" }));
    await waitFor(() => expect(ofMethod(calls, "POST", "/api/filing-codes/folders")).toHaveLength(1));
  });

  it("Print stickers opens as a sheet; Print… in a saved code ticks that code", async () => {
    const { user } = setup();
    await user.click(await screen.findByRole("button", { name: "Print stickers…" }));
    let sheet = await screen.findByRole("dialog", { name: "Print stickers" });
    expect(await within(sheet).findByLabelText("Print A")).not.toBeChecked();
    await user.click(within(sheet).getByRole("button", { name: "Close" }));
    const editor = await openCode(user, /^P To pay/);
    await user.click(within(editor).getByRole("button", { name: "Print…" }));
    sheet = await screen.findByRole("dialog", { name: "Print stickers" });
    expect(await within(sheet).findByLabelText("Print P")).toBeChecked();
    await user.click(within(sheet).getByRole("button", { name: "Close" }));
    await user.type(within(editor).getByLabelText("Label"), "!");
    expect(within(editor).getByRole("button", { name: "Print…" })).toBeDisabled(); // stickers print the saved table
  });
});
