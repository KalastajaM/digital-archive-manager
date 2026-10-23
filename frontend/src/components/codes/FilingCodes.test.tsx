import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { type Call, mockFetch, renderWithProviders } from "../../test-utils";
import { FilingCodes } from "./FilingCodes";

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
  code("P", "To pay", { tray: "to-pay" }),
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

function setup(over: Record<string, unknown> = {}, table: { codes?: unknown[]; problems?: unknown[]; warnings?: unknown[] } = {}) {
  const calls = mockFetch({
    "GET /api/filing-codes": { body: { codes: SEEDED, problems: [], warnings: [], ...table } },
    "GET /api/filing-codes/folders": { body: { missing: [], stray: [] } },
    "GET /api/trays": { body: TRAYS },
    "GET /api/folders": { body: ["10. Financial"] },
    ...over,
  } as never);
  renderWithProviders(<FilingCodes />);
  return { calls, user: userEvent.setup() };
}
const ofMethod = (calls: Call[], method: string, url: string) => calls.filter((c) => c.method === method && c.url === url);

describe("Filing codes (Settings)", () => {
  it("lists the seeded codes with their tray", async () => {
    setup();
    const section = await screen.findByRole("region", { name: "Filing codes" });
    const rows = await within(section).findAllByRole("group");
    expect(rows.map((r) => within(r).getAllByRole("textbox")[0])).toHaveLength(3);
    expect(within(rows[0]).getByLabelText("Code")).toHaveValue("A");
    expect(within(rows[0]).getByLabelText("Tray")).toHaveValue("to-action");
    expect(within(rows[2]).getByLabelText("File as suggested")).toBeChecked();
  });

  it("shows the confusable warning the server gives for a code", async () => {
    let table: unknown = { codes: SEEDED, problems: [], warnings: [] };
    const { user } = setup({
      "GET /api/filing-codes": () => ({ body: table }),
      "PUT /api/filing-codes": () => {
        table = {
          codes: [...SEEDED, code("O", ""), code("0", "")],
          problems: [],
          warnings: [{ code: "O", confusable_with: ["0"] }],
        };
        return { body: table };
      },
    });
    await screen.findAllByRole("group");
    await user.click(screen.getByRole("button", { name: "Add a code" }));
    await user.click(screen.getByRole("button", { name: "Add a code" }));
    const rows = screen.getAllByRole("group");
    await user.type(within(rows[3]).getByLabelText("Code"), "O");
    await user.type(within(rows[4]).getByLabelText("Code"), "0");
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByText(/Easy to confuse with/)).toHaveTextContent("Easy to confuse with 0 when written by hand.");
  });

  it("Save sends the whole edited list", async () => {
    const { calls, user } = setup({ "PUT /api/filing-codes": (c: Call) => ({ body: { codes: c.body, problems: [], warnings: [] } }) });
    const rows = await screen.findAllByRole("group");
    await user.click(within(rows[1]).getByRole("button", { name: "Remove code P" }));
    await user.click(screen.getByRole("button", { name: "Add a code" }));
    const added = screen.getAllByRole("group")[2];
    await user.type(within(added).getByLabelText("Code"), "T");
    await user.type(within(added).getByLabelText("Label"), "Taxes");
    await user.type(within(added).getByLabelText("Tags"), "tax, 2026");
    await user.selectOptions(within(added).getByLabelText("Tray"), "to-pay");
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(ofMethod(calls, "PUT", "/api/filing-codes")).toHaveLength(1));
    const body = ofMethod(calls, "PUT", "/api/filing-codes")[0].body as Array<Record<string, unknown>>;
    expect(body.map((c) => c.code)).toEqual(["A", "D", "T"]);
    expect(body[2]).toMatchObject({ label: "Taxes", tags: ["tax", "2026"], tray: "to-pay", folder: null, as_suggested: false });
  });

  it("a refused save shows its message and keeps the edits", async () => {
    const { user } = setup({ "PUT /api/filing-codes": { status: 400, body: { error: "Code 'A' is repeated" } } });
    await screen.findAllByRole("group");
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Code 'A' is repeated");
    expect(screen.getAllByRole("group")).toHaveLength(3);
  });

  it("shows problems at the top and warns that saving drops them", async () => {
    setup({}, { problems: [{ code: "Q", message: "names an unknown tray" }] });
    expect(await screen.findByText(/names an unknown tray/)).toBeInTheDocument();
    expect(
      screen.getByText(
        "Saving keeps only the codes listed here; the entries with problems above are removed from the file (a backup is kept).",
      ),
    ).toBeInTheDocument();
  });

  it("Create inbox folders previews every folder (the inbox too) and posts on confirm", async () => {
    const { calls, user } = setup({
      "GET /api/filing-codes/folders": { body: { missing: ["A", "P"], stray: ["Old"] } },
      "POST /api/filing-codes/folders/preview": { body: [MKDIR("00. Inbox"), MKDIR("00. Inbox/A"), MKDIR("00. Inbox/P")] },
      "POST /api/filing-codes/folders": { body: { batch_id: "b1", ops: [] } },
    });
    expect(await screen.findByText(/Not a filing code folder: its files are not in the Inbox\./)).toBeInTheDocument();
    await user.click(await screen.findByRole("button", { name: "Create inbox folders" }));
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent("00. Inbox/A");
    expect(dialog).toHaveTextContent("00. Inbox/P");
    expect(within(dialog).getAllByText("New folder")).toHaveLength(3);
    expect(ofMethod(calls, "POST", "/api/filing-codes/folders")).toHaveLength(0);
    await user.click(within(dialog).getByRole("button", { name: "Create folders" }));
    await waitFor(() => expect(ofMethod(calls, "POST", "/api/filing-codes/folders")).toHaveLength(1));
  });
});
