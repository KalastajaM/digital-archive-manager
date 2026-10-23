import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { type Call, mockFetch, renderWithProviders } from "../../test-utils";
import { PrintStickers } from "./PrintStickers";

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
const SHEET =
  '<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Filing code stickers</title>' +
  '<style>.label { position: absolute }</style></head><body><p class="note">Print at 100 %, without fit to page.</p>' +
  '<div class="page"><div class="label" data-code="P" style="left:4.7mm;top:10.7mm;width:38.1mm;height:21.2mm"></div></div></body></html>';
const PLAIN = { id: "plain", name: "Plain paper, cut out", cut_lines: true, ...GRID };

/** A stand-in for the new tab: an empty page the sheet is built into. */
function fakeWindow() {
  return { close: vi.fn(), document: document.implementation.createHTMLDocument("") };
}
let opened: ReturnType<typeof fakeWindow>[] = [];
beforeEach(() => {
  opened = [];
  vi.spyOn(window, "open").mockImplementation(() => {
    const w = fakeWindow();
    opened.push(w);
    return w as unknown as Window;
  });
});
afterEach(() => vi.restoreAllMocks());

function setup(over: Record<string, unknown> = {}) {
  const calls = mockFetch({
    "GET /api/filing-codes": { body: { codes: [code("A", "To action"), code("P", "To pay")], problems: [], warnings: [] } },
    "GET /api/filing-codes/sheets": { body: [L7651, PLAIN] },
    "POST /api/filing-codes/sheet": { html: SHEET },
    ...over,
  } as never);
  renderWithProviders(<PrintStickers />);
  return { calls, user: userEvent.setup() };
}
const sheetPosts = (calls: Call[]) => calls.filter((c) => c.method === "POST" && c.url === "/api/filing-codes/sheet");

describe("Print stickers (Settings)", () => {
  it("lists the built-in layouts and Custom, with tick boxes on by default", async () => {
    setup();
    const section = await screen.findByRole("region", { name: "Print stickers" });
    const layout = await within(section).findByLabelText("Sheet");
    await waitFor(() => expect(within(layout).getAllByRole("option")).toHaveLength(3));
    expect(within(layout).getAllByRole("option").map((o) => o.textContent)).toEqual([
      "Avery Zweckform L7651 (65 per sheet, 38.1 x 21.2 mm)",
      "Plain paper, cut out",
      "Custom",
    ]);
    expect(layout).toHaveValue("l7651");
    expect(within(section).getByLabelText("With tick boxes (star, important)")).toBeChecked();
    expect(within(section).getByLabelText("Blank labels (write the label by hand)")).not.toBeChecked();
    expect(within(section).queryByLabelText("Label width (mm)")).toBeNull();
  });

  it("Open sheet posts the chosen codes and counts and opens the sheet in a new tab", async () => {
    const { calls, user } = setup();
    const section = await screen.findByRole("region", { name: "Print stickers" });
    await user.click(await within(section).findByLabelText("Print P"));
    const count = within(section).getByLabelText("How many P");
    await user.clear(count);
    await user.type(count, "12");
    await user.click(within(section).getByLabelText("Blank labels (write the label by hand)"));
    const start = within(section).getByLabelText("Start at label");
    await user.clear(start);
    await user.type(start, "3");
    expect(within(section).getByText("12 stickers")).toBeInTheDocument();
    await user.click(within(section).getByRole("button", { name: "Open sheet" }));
    await waitFor(() => expect(sheetPosts(calls)).toHaveLength(1));
    expect(sheetPosts(calls)[0].body).toEqual({
      codes: { P: 12 },
      layout: "l7651",
      start_at: 3,
      boxes: true,
      blank_labels: true,
      outlines_only: false,
    });
    expect(window.open).toHaveBeenCalledTimes(1);
    const tab = opened[0].document;
    await waitFor(() => expect(tab.title).toBe("Filing code stickers"));
    expect(tab.body.textContent).toContain("Print at 100 %, without fit to page.");
    // the page's styles are set through the CSSOM (the app's CSP blocks inline style)
    const label = tab.querySelector<HTMLElement>(".label");
    expect(label?.style.width).toBe("38.1mm");
    expect(opened[0].close).not.toHaveBeenCalled();
  });

  it("Open sheet needs at least one code", async () => {
    setup();
    const section = await screen.findByRole("region", { name: "Print stickers" });
    await within(section).findByLabelText("Print P");
    expect(within(section).getByRole("button", { name: "Open sheet" })).toBeDisabled();
  });

  it("Test print posts outlines only for the chosen sheet, without codes", async () => {
    const { calls, user } = setup();
    const section = await screen.findByRole("region", { name: "Print stickers" });
    await user.click(await within(section).findByLabelText("Print A"));
    await user.selectOptions(within(section).getByLabelText("Sheet"), "plain");
    await user.click(within(section).getByRole("button", { name: "Test print" }));
    await waitFor(() => expect(sheetPosts(calls)).toHaveLength(1));
    expect(sheetPosts(calls)[0].body).toEqual({
      codes: {},
      layout: "plain",
      start_at: 1,
      boxes: true,
      blank_labels: false,
      outlines_only: true,
    });
  });

  it("a refused sheet shows the server's reason and closes the empty tab", async () => {
    const { user } = setup({ "POST /api/filing-codes/sheet": { status: 400, body: { error: "start at a label from 1 to 65" } } });
    const section = await screen.findByRole("region", { name: "Print stickers" });
    await user.click(await within(section).findByLabelText("Print A"));
    await user.click(within(section).getByRole("button", { name: "Open sheet" }));
    expect(await within(section).findByRole("alert")).toHaveTextContent("start at a label from 1 to 65");
    expect(opened[0].close).toHaveBeenCalled();
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
    expect(within(section).getByRole("button", { name: "Open sheet" })).toBeDisabled(); // save first
    expect(within(section).getByText("Save the custom sheet before printing on it.")).toBeInTheDocument();
    await user.click(within(section).getByRole("button", { name: "Save custom sheet" }));
    await waitFor(() => expect(calls.filter((c) => c.method === "PUT")).toHaveLength(1));
    expect(calls.find((c) => c.method === "PUT")?.body).toEqual({ ...saved, id: undefined });
    await waitFor(() => expect(within(section).getByRole("button", { name: "Open sheet" })).toBeEnabled());
    await user.click(within(section).getByRole("button", { name: "Open sheet" }));
    await waitFor(() => expect(sheetPosts(calls)).toHaveLength(1));
    expect(sheetPosts(calls)[0].body).toMatchObject({ layout: "custom", codes: { A: 1 } });
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
