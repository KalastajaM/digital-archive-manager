import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { type Call, mockFetch, renderWithProviders } from "../../test-utils";
import { PrintStickers, sheetSummary } from "./PrintStickers";

const code = (c: string, label: string) => ({
  code: c,
  label,
  tray: null,
  folder: null,
  name: null,
  tags: [],
  collections: [],
  as_suggested: false,
  inbox_folder: null,
});
const GRID = { columns: 5, rows: 13, label_w_mm: 38.1, label_h_mm: 21.2, top_mm: 10.7, left_mm: 4.7, gap_x_mm: 2.5, gap_y_mm: 0 };
const L7651 = { id: "l7651", name: "Avery Zweckform L7651 (65 per sheet, 38.1 x 21.2 mm)", cut_lines: false, ...GRID };
const PLAIN = { id: "plain", name: "Plain paper, cut out (65 per sheet, 38.1 x 21.2 mm)", cut_lines: true, ...GRID };

function setup(over: Record<string, unknown> = {}) {
  const calls = mockFetch({
    "GET /api/filing-codes": { body: { codes: [code("A", "To action"), code("P", "To pay")], problems: [], warnings: [] } },
    "GET /api/filing-codes/sheets": { body: [L7651, PLAIN] },
    ...over,
  } as never);
  renderWithProviders(<PrintStickers />);
  return { calls, user: userEvent.setup() };
}

/** The link that opens the sheet in a new tab: its query, after checking it is one. */
function sheetLink(scope: HTMLElement, name: string): Record<string, string> {
  const link = within(scope).getByRole("link", { name });
  expect(link).toHaveAttribute("target", "_blank");
  expect(link).toHaveAttribute("rel", "noopener");
  const href = link.getAttribute("href") ?? "";
  expect(href).toMatch(/^\/api\/filing-codes\/sheet\?/);
  return Object.fromEntries(new URL(href, "http://x").searchParams);
}
/** A sheet action that cannot be opened now: a disabled button, no link. */
function expectDisabled(scope: HTMLElement, name: string) {
  expect(within(scope).queryByRole("link", { name })).toBeNull();
  expect(within(scope).getByRole("button", { name })).toBeDisabled();
}
const sheetFetches = (calls: Call[]) => calls.filter((c) => c.url.startsWith("/api/filing-codes/sheet?"));

describe("Print stickers (Settings)", () => {
  it("lists the built-in layouts and Custom, with tick boxes on by default", async () => {
    setup();
    const section = await screen.findByRole("region", { name: "Print stickers" });
    const layout = await within(section).findByLabelText("Sheet");
    await waitFor(() => expect(within(layout).getAllByRole("option")).toHaveLength(3));
    expect(within(layout).getAllByRole("option").map((o) => o.textContent)).toEqual([
      "Avery Zweckform L7651 (65 per sheet, 38.1 x 21.2 mm)",
      "Plain paper, cut out (65 per sheet, 38.1 x 21.2 mm)",
      "Custom",
    ]);
    expect(layout).toHaveValue("l7651");
    expect(within(section).getByLabelText("With tick boxes (star, important)")).toBeChecked();
    expect(within(section).getByLabelText("Blank labels (write the label by hand)")).not.toBeChecked();
    expect(within(section).queryByLabelText("Label width (mm)")).toBeNull();
  });

  it("Open sheet links to the sheet with the chosen codes, counts and options", async () => {
    const { calls, user } = setup();
    const section = await screen.findByRole("region", { name: "Print stickers" });
    await user.click(await within(section).findByLabelText("Print P"));
    const count = within(section).getByLabelText("How many P");
    await user.clear(count);
    await user.type(count, "12");
    await user.click(within(section).getByLabelText("Print A"));
    await user.click(within(section).getByLabelText("Blank labels (write the label by hand)"));
    await user.click(within(section).getByLabelText("With tick boxes (star, important)"));
    const start = within(section).getByLabelText("Start at label");
    await user.clear(start);
    await user.type(start, "3");
    expect(
      within(section).getByText("65 labels per sheet (5 × 13). 13 stickers from label 3: 1 sheet, 50 labels left empty on the last."),
    ).toBeInTheDocument();
    expect(sheetLink(section, "Open sheet")).toEqual({
      codes: "P:12,A:1",
      layout: "l7651",
      start_at: "3",
      boxes: "false",
      blank_labels: "true",
      outlines_only: "false",
    });
    expect(sheetFetches(calls)).toHaveLength(0); // the browser opens it; nothing fetched here
  });

  it("Open sheet is disabled without a code, and a count of 0 leaves a code out", async () => {
    const { user } = setup();
    const section = await screen.findByRole("region", { name: "Print stickers" });
    await within(section).findByLabelText("Print P");
    expectDisabled(section, "Open sheet");
    await user.click(within(section).getByLabelText("Print P"));
    await user.click(within(section).getByLabelText("Print A"));
    await user.clear(within(section).getByLabelText("How many A"));
    await user.type(within(section).getByLabelText("How many A"), "0");
    expect(sheetLink(section, "Open sheet").codes).toBe("P:1");
    await user.click(within(section).getByLabelText("Print P"));
    expectDisabled(section, "Open sheet");
  });

  it("Test print links to outlines only on the chosen sheet, without codes", async () => {
    const { user } = setup();
    const section = await screen.findByRole("region", { name: "Print stickers" });
    await user.click(await within(section).findByLabelText("Print A"));
    await user.selectOptions(within(section).getByLabelText("Sheet"), "plain");
    expect(sheetLink(section, "Test print")).toEqual({
      codes: "",
      layout: "plain",
      start_at: "1",
      boxes: "true",
      blank_labels: "false",
      outlines_only: "true",
    });
  });

  it("Custom shows the mm fields, saves them and then prints on it", async () => {
    const saved = { ...GRID, id: "custom", name: "My labels", cut_lines: false, label_h_mm: 25 };
    const { calls, user } = setup({
      "PUT /api/filing-codes/sheets/custom": (c: Call) => ({ body: { ...(c.body as object), id: "custom" } }),
    });
    const section = await screen.findByRole("region", { name: "Print stickers" });
    await within(section).findByLabelText("Print A");
    await user.selectOptions(within(section).getByLabelText("Sheet"), "custom");
    const height = within(section).getByLabelText("Label height (mm)");
    expect(height).toHaveValue(21.2); // starts from the first built-in
    for (const label of ["Name", "Columns", "Rows", "Label width (mm)", "Top margin (mm)", "Left margin (mm)", "Gap across (mm)", "Gap down (mm)"])
      expect(within(section).getByLabelText(label)).toBeInTheDocument();
    await user.clear(within(section).getByLabelText("Name"));
    await user.type(within(section).getByLabelText("Name"), "My labels");
    await user.clear(height);
    await user.type(height, "25");
    await user.click(within(section).getByLabelText("Print A"));
    expectDisabled(section, "Open sheet"); // save first
    expectDisabled(section, "Test print");
    expect(within(section).getByText("Save the custom sheet before printing on it.")).toBeInTheDocument();
    await user.click(within(section).getByRole("button", { name: "Save custom sheet" }));
    await waitFor(() => expect(calls.filter((c) => c.method === "PUT")).toHaveLength(1));
    expect(calls.find((c) => c.method === "PUT")?.body).toEqual({ ...saved, id: undefined });
    await waitFor(() => expect(within(section).getByRole("link", { name: "Open sheet" })).toBeInTheDocument());
    expect(sheetLink(section, "Open sheet")).toMatchObject({ layout: "custom", codes: "A:1" });
    // an edit after saving disables it again until saved
    await user.type(within(section).getByLabelText("Rows"), "0");
    expectDisabled(section, "Open sheet");
  });

  it("a refused custom sheet shows why", async () => {
    const { user } = setup({
      "PUT /api/filing-codes/sheets/custom": { status: 400, body: { error: "a label must be at least 31.7 x 14.0 mm to hold a sticker" } },
    });
    const section = await screen.findByRole("region", { name: "Print stickers" });
    await within(section).findByLabelText("Print A");
    await user.selectOptions(within(section).getByLabelText("Sheet"), "custom");
    await user.click(within(section).getByRole("button", { name: "Save custom sheet" }));
    expect(await within(section).findByRole("alert")).toHaveTextContent("a label must be at least 31.7 x 14.0 mm");
  });
});

describe("the sheet summary", () => {
  it("says how many labels fit, before any sticker is chosen", () => {
    expect(sheetSummary(5, 13, 0, 1)).toBe("65 labels per sheet (5 × 13). No stickers chosen.");
  });

  it("counts the sheets and the empty labels on the last, from the start label on", () => {
    expect(sheetSummary(5, 13, 70, 1)).toBe("65 labels per sheet (5 × 13). 70 stickers: 2 sheets, 60 labels left empty on the last.");
    expect(sheetSummary(5, 13, 65, 1)).toBe("65 labels per sheet (5 × 13). 65 stickers: 1 sheet, no labels left empty on the last.");
    expect(sheetSummary(5, 13, 1, 65)).toBe("65 labels per sheet (5 × 13). 1 sticker from label 65: 1 sheet, no labels left empty on the last.");
    expect(sheetSummary(5, 13, 2, 65)).toBe("65 labels per sheet (5 × 13). 2 stickers from label 65: 2 sheets, 64 labels left empty on the last.");
  });

  it("names a start label past the end of the sheet", () => {
    expect(sheetSummary(5, 13, 3, 70)).toBe("65 labels per sheet (5 × 13). Start at label 70 is past the end of the sheet.");
  });
});
