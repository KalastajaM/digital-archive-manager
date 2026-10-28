/** The Relatives dialog: the outline by folder, the arcs, the In common strip, the hover
 * and focus card, the quick selections, the shared actions, the keys and the folding. */
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it } from "vitest";
import type { Relative } from "../api/client";
import { type Call, mockFetch, renderWithProviders } from "../test-utils";
import { RelativesDialog } from "./RelativesDialog";

const FILE = { drive_id: "d0", path: "13. Taxes/20250930_Verohallinto.pdf", name: "20250930_Verohallinto.pdf" };

const rel = (
  drive_id: string,
  name: string,
  folder: string,
  links: [Relative["links"][number]["kind"], string][],
  extra: Partial<Relative> = {},
): Relative => ({
  drive_id,
  name,
  folder,
  path: `${folder}/${name}`,
  ext: "pdf",
  score: links.length * 2,
  links: links.map(([kind, value]) => ({ kind, value, weight: 2 })),
  same_month: false,
  in_inbox: false,
  ...extra,
});

const RELATIVES: Relative[] = [
  rel("r2", "20240928_Verohallinto.pdf", "13. Taxes", [["folder", "13. Taxes"], ["sender", "Verohallinto"], ["tag", "Taxes"], ["collection", "Tax return"]]),
  rel("r3", "20250415_Veroilmoitus 2024.pdf", "13. Taxes", [["folder", "13. Taxes"], ["tag", "Taxes"]]),
  rel("r1", "scan_20261001.pdf", "##. Organize", [["sender", "Verohallinto"]], { in_inbox: true }),
  rel("r5", "20250926_Vuokratulot.pdf", "30. Home/Property", [["tag", "Taxes"]], { same_month: true }),
  rel("r6", "receipt.pdf", "40. Misc", [["reference", "123"]]),
];
const COMMON = [
  { kind: "tag", value: "Taxes", count: 3 },
  { kind: "sender", value: "Verohallinto", count: 2 },
];
const body = (relatives: Relative[], hidden = 0) => ({
  drive_id: "d0",
  relatives,
  common: COMMON,
  total: relatives.length,
  hidden,
});
const sent = (calls: Call[], method: string, url: string) => calls.filter((c) => c.method === method && c.url === url);

let closed = 0;
function setup(routes: Parameters<typeof mockFetch>[0] = {}, relatives = RELATIVES, hidden = 0) {
  closed = 0;
  const calls = mockFetch({
    "GET /api/files/d0/relatives": { body: body(relatives, hidden) },
    "GET /api/status": { body: { can_link: true } },
    "GET /api/folders": { body: ["13. Taxes", "30. Home"] },
    ...routes,
  });
  renderWithProviders(
    <MemoryRouter>
      <RelativesDialog file={FILE} onClose={() => (closed += 1)} />
    </MemoryRouter>,
  );
  return { calls, user: userEvent.setup() };
}
const rowOf = (name: string) => screen.getByRole("checkbox", { name: `Select ${name}` }).closest("li") as HTMLElement;
const chip = (text: RegExp) => screen.getByRole("button", { name: text });

afterEach(cleanup);

describe("the outline", () => {
  it("cuts the folders down to those with a relative, nested by path, with this file in its folder", async () => {
    setup();
    await screen.findByRole("checkbox", { name: "Select receipt.pdf" });
    const list = screen.getByRole("list", { name: "Folders with relatives" });
    const rows = [...list.children].map((li) => li.querySelector(".rel-name, .rel-folder-name")?.textContent);
    // 13. Taxes holds this file; the Inbox comes last; 30. Home is only a way to Property
    expect(rows).toEqual([
      "13. Taxes",
      "20250930_Verohallinto.pdf",
      "20240928_Verohallinto.pdf",
      "20250415_Veroilmoitus 2024.pdf",
      "30. Home",
      "Property",
      "20250926_Vuokratulot.pdf",
      "40. Misc",
      "receipt.pdf",
      "Inbox",
      "scan_20261001.pdf",
    ]);
    const own = list.querySelector(".self") as HTMLElement;
    expect(own).toHaveTextContent("this file");
    expect(rowOf("scan_20261001.pdf")).toHaveClass("unfiled");
    expect(within(rowOf("20240928_Verohallinto.pdf")).getByText("sender")).toBeInTheDocument();
    expect(within(rowOf("20250926_Vuokratulot.pdf")).getByText("+ same month")).toBeInTheDocument();
  });

  it("draws one arc per relative, dashed orange for the unfiled one", async () => {
    setup();
    await screen.findByRole("checkbox", { name: "Select receipt.pdf" });
    const arcs = document.querySelectorAll("svg.rel-arcs .rel-arc");
    expect(arcs).toHaveLength(5);
    const inbox = document.querySelectorAll("svg.rel-arcs .rel-arc.inbox");
    expect(inbox).toHaveLength(1);
    expect(inbox[0]).toHaveAttribute("data-target", "r1");
    // thicker for a higher score
    const width = (id: string) => Number(document.querySelector(`.rel-arc[data-target="${id}"] path`)?.getAttribute("stroke-width"));
    expect(width("r2")).toBeGreaterThan(width("r6"));
  });

  it("folds a folder with more than eight relatives to a count and opens it on click", async () => {
    const many = Array.from({ length: 9 }, (_, i) => rel(`m${i}`, `doc${i}.pdf`, "50. Many", [["tag", "Taxes"]]));
    const { user } = setup({}, [...RELATIVES, ...many]);
    await screen.findByRole("checkbox", { name: "Select receipt.pdf" });
    expect(screen.queryByRole("checkbox", { name: "Select doc0.pdf" })).toBeNull();
    // arcs of the folded files end at the folder's row: one arc for the nine
    expect(document.querySelectorAll("svg.rel-arcs .rel-arc")).toHaveLength(6);
    const fold = screen.getByRole("button", { name: /50\. Many/ });
    expect(fold).toHaveAttribute("aria-expanded", "false");
    expect(fold).toHaveTextContent("9 files");
    await user.click(fold);
    expect(screen.getByRole("checkbox", { name: "Select doc0.pdf" })).toBeInTheDocument();
    expect(document.querySelectorAll("svg.rel-arcs .rel-arc")).toHaveLength(14);
  });

  it("says what to do when there are none", async () => {
    setup({}, []);
    expect(await screen.findByText(/No relatives yet/)).toBeInTheDocument();
  });
});

describe("the In common strip", () => {
  it("lights the files that share a value, fades the rest, one at a time, and clears on a second press", async () => {
    const { user } = setup();
    await screen.findByRole("checkbox", { name: "Select receipt.pdf" });
    const tag = chip(/^Tag: Taxes 3$/);
    const sender = chip(/^Sender: Verohallinto 2$/);
    expect(tag).toHaveAttribute("aria-pressed", "false");
    await user.click(tag);
    expect(tag).toHaveAttribute("aria-pressed", "true");
    expect(rowOf("20240928_Verohallinto.pdf")).toHaveClass("lit");
    expect(rowOf("receipt.pdf")).toHaveClass("faded");
    expect(rowOf("scan_20261001.pdf")).toHaveClass("faded");
    expect(document.querySelector('.rel-arc[data-target="r6"]')).toHaveClass("faded");
    expect(document.querySelector('.rel-arc[data-target="r3"]')).not.toHaveClass("faded");
    await user.click(sender);
    expect(tag).toHaveAttribute("aria-pressed", "false");
    expect(sender).toHaveAttribute("aria-pressed", "true");
    expect(rowOf("20250415_Veroilmoitus 2024.pdf")).toHaveClass("faded");
    expect(rowOf("scan_20261001.pdf")).not.toHaveClass("faded");
    await user.click(sender);
    expect(document.querySelectorAll(".faded")).toHaveLength(0);
  });
});

describe("the card", () => {
  it("shows the exact shared values on hover in the side panel, with Quick look and Not related", async () => {
    const { user } = setup();
    await screen.findByRole("checkbox", { name: "Select receipt.pdf" });
    expect(screen.queryByRole("group", { name: /What .* shares/ })).toBeNull();
    expect(screen.getByText(/Point at a file/)).toBeInTheDocument();
    await user.hover(rowOf("20240928_Verohallinto.pdf"));
    const card = await screen.findByRole("group", { name: "What 20240928_Verohallinto.pdf shares" });
    for (const [k, v] of [["Folder", "13. Taxes"], ["Sender", "Verohallinto"], ["Tag", "Taxes"], ["Collection", "Tax return"]]) {
      expect(within(card).getByText(k)).toBeInTheDocument();
      expect(within(card).getByText(v)).toBeInTheDocument();
    }
    expect(within(card).getByRole("button", { name: /Quick look/ })).toBeInTheDocument();
    expect(within(card).getByRole("button", { name: "Not related" })).toBeInTheDocument();
    // beside the outline, never over it
    expect(card.closest(".rel-side")).not.toBeNull();
    expect(card.closest(".rel-rows")).toBeNull();
    expect(rowOf("20240928_Verohallinto.pdf")).toHaveClass("carded");
    // it stays when the pointer leaves, so its buttons can be reached
    await user.unhover(rowOf("20240928_Verohallinto.pdf"));
    expect(screen.getByRole("group", { name: "What 20240928_Verohallinto.pdf shares" })).toBeInTheDocument();
    await user.hover(rowOf("receipt.pdf"));
    expect(await screen.findByRole("group", { name: "What receipt.pdf shares" })).toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "What 20240928_Verohallinto.pdf shares" })).toBeNull();
    expect(rowOf("20240928_Verohallinto.pdf")).not.toHaveClass("carded");
  });

  it("shows on keyboard focus too, and Not related there marks the pair", async () => {
    const { calls, user } = setup({ "POST /api/files/d0/relatives/dismiss": { body: { dismissed: [] } } });
    await screen.findByRole("checkbox", { name: "Select receipt.pdf" });
    rowOf("receipt.pdf").focus();
    const card = await screen.findByRole("group", { name: "What receipt.pdf shares" });
    expect(within(card).getByText("123")).toBeInTheDocument();
    await user.click(within(card).getByRole("button", { name: "Not related" }));
    await waitFor(() => expect(sent(calls, "POST", "/api/files/d0/relatives/dismiss")).toHaveLength(1));
    expect(sent(calls, "POST", "/api/files/d0/relatives/dismiss")[0].body).toEqual({ drive_id: "r6" });
  });
});

describe("selecting and acting", () => {
  it("quick selections tick the matching relatives", async () => {
    const { user } = setup();
    await screen.findByRole("checkbox", { name: "Select receipt.pdf" });
    await user.click(screen.getByRole("button", { name: "2+ links" }));
    expect(screen.getByRole("checkbox", { name: "Select 20240928_Verohallinto.pdf" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Select 20250415_Veroilmoitus 2024.pdf" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Select receipt.pdf" })).not.toBeChecked();
    await user.click(screen.getByRole("button", { name: "Same sender" }));
    expect(screen.getByRole("checkbox", { name: "Select scan_20261001.pdf" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Select 20250415_Veroilmoitus 2024.pdf" })).not.toBeChecked();
    await user.click(screen.getByRole("button", { name: "Outside this folder" }));
    expect(screen.getByRole("checkbox", { name: "Select receipt.pdf" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Select 20240928_Verohallinto.pdf" })).not.toBeChecked();
    expect(screen.getByText("This file and 3 related")).toBeInTheDocument();
  });

  it("uses the block's actions: the link buttons are off with their reason when nothing needs a link", async () => {
    const { user } = setup();
    await screen.findByRole("checkbox", { name: "Select receipt.pdf" });
    await user.click(screen.getByRole("checkbox", { name: "Select 20240928_Verohallinto.pdf" }));
    expect(screen.getByRole("button", { name: "Tag…" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add to collection…" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Move to folder…" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Link them here" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Link them here" }).closest(".button-wrap")).toHaveAttribute(
      "data-tip",
      "No links needed: all 1 are already in 13. Taxes",
    );
  });

  it("Link them here sends the ticked drive ids and this file's folder", async () => {
    const op = { kind: "symlink", src: "40. Misc/receipt.pdf", dst: "13. Taxes/receipt.pdf", drive_id: "r6", note: null };
    const { calls, user } = setup({ "POST /api/browse/move/preview": { body: [op] } });
    await screen.findByRole("checkbox", { name: "Select receipt.pdf" });
    await user.click(screen.getByRole("checkbox", { name: "Select receipt.pdf" }));
    await user.click(screen.getByRole("button", { name: "Link it here" }));
    await waitFor(() => expect(sent(calls, "POST", "/api/browse/move/preview")).toHaveLength(1));
    expect(sent(calls, "POST", "/api/browse/move/preview")[0].body).toEqual({
      drive_ids: ["r6"],
      folder: "13. Taxes",
      mode: "link",
    });
  });

  it("hides the link buttons when links cannot be made here", async () => {
    const { user } = setup({ "GET /api/status": { body: { can_link: false } } });
    await screen.findByRole("checkbox", { name: "Select receipt.pdf" });
    await user.click(screen.getByRole("checkbox", { name: "Select receipt.pdf" }));
    await waitFor(() => expect(screen.queryByRole("button", { name: /Link/ })).toBeNull());
    expect(screen.getByRole("button", { name: "Tag…" })).toBeInTheDocument();
  });

  it("lists the marked-not-related files with Show again", async () => {
    const { calls, user } = setup(
      {
        "GET /api/files/d0/relatives/dismissed": { body: { dismissed: [{ drive_id: "x9", name: "old.pdf", path: "50. Old/old.pdf" }] } },
        "POST /api/files/d0/relatives/restore": { body: { dismissed: [] } },
      },
      RELATIVES,
      1,
    );
    await user.click(await screen.findByRole("button", { name: "1 marked not related" }));
    await user.click(await screen.findByRole("button", { name: "Show old.pdf again" }));
    await waitFor(() => expect(sent(calls, "POST", "/api/files/d0/relatives/restore")).toHaveLength(1));
  });
});

describe("the keys", () => {
  it("moves between rows with the arrows, ticks with X and marks with N", async () => {
    const { calls, user } = setup({ "POST /api/files/d0/relatives/dismiss": { body: { dismissed: [] } } });
    await screen.findByRole("checkbox", { name: "Select receipt.pdf" });
    const first = rowOf("20240928_Verohallinto.pdf");
    first.focus();
    await user.keyboard("{ArrowDown}");
    expect(rowOf("20250415_Veroilmoitus 2024.pdf")).toHaveFocus();
    await user.keyboard("{ArrowUp}");
    expect(first).toHaveFocus();
    await user.keyboard("x");
    expect(screen.getByRole("checkbox", { name: "Select 20240928_Verohallinto.pdf" })).toBeChecked();
    await user.keyboard("x");
    expect(screen.getByRole("checkbox", { name: "Select 20240928_Verohallinto.pdf" })).not.toBeChecked();
    await user.keyboard("n");
    await waitFor(() => expect(sent(calls, "POST", "/api/files/d0/relatives/dismiss")).toHaveLength(1));
    expect(sent(calls, "POST", "/api/files/d0/relatives/dismiss")[0].body).toEqual({ drive_id: "r2" });
  });

  it("Space opens Quick Look in compare mode on that row, without reaching the page", async () => {
    const { user } = setup({ "GET /api/files/r2": { status: 404, body: { error: "x" } } });
    await screen.findByRole("checkbox", { name: "Select receipt.pdf" });
    rowOf("20240928_Verohallinto.pdf").focus();
    await user.keyboard(" ");
    const ql = await screen.findByRole("dialog", { name: "Quick Look: 20240928_Verohallinto.pdf" });
    expect(within(ql).getByText("Is this related?")).toBeInTheDocument();
  });

  it("Esc closes the dialog", async () => {
    setup();
    await screen.findByRole("checkbox", { name: "Select receipt.pdf" });
    fireEvent.keyDown(rowOf("receipt.pdf"), { key: "Escape" });
    expect(closed).toBe(1);
  });
});
