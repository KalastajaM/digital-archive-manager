/** The Relatives dialog: the outline by folder, the arcs, the In common strip, the hover
 * and focus card, the quick selections, the shared actions, the keys and the folding. */
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, useLocation } from "react-router-dom";
import { afterEach, describe, expect, it } from "vitest";
import type { Relative } from "../api/client";
import { type Call, mockFetch, renderWithProviders } from "../test-utils";
import { buildOutline, RelativesDialog } from "./RelativesDialog";

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

function Where() {
  const location = useLocation();
  return <output data-testid="where">{location.pathname + location.search}</output>;
}

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
      <Where />
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
    // 13. Taxes holds this file; the Inbox comes last; 30. Home is only a way to Property, so one row
    expect(rows).toEqual([
      "13. Taxes",
      "20250930_Verohallinto.pdf",
      "20240928_Verohallinto.pdf",
      "20250415_Veroilmoitus 2024.pdf",
      "30. Home / Property",
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

  it("gives a folder its own row only where it holds files or the paths below it part", () => {
    const labels = (rs: Relative[]) =>
      buildOutline(FILE, rs, new Set()).flatMap((r) => (r.t === "folder" ? [`${r.depth}:${r.label}`] : []));
    expect(
      labels([
        rel("a", "a.pdf", "12. Insurance/01. Pohjola/Claims", [["tag", "x"]]),
        rel("b", "b.pdf", "12. Insurance/02. If/Claims", [["tag", "x"]]),
        rel("c", "c.pdf", "11. Bills/2026", [["tag", "x"]]),
        rel("d", "d.pdf", "11. Bills", [["tag", "x"]]),
      ]),
    ).toEqual(["0:11. Bills", "1:2026", "0:12. Insurance", "1:01. Pohjola / Claims", "1:02. If / Claims", "0:13. Taxes"]);
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
    // opened, the nine are a bundle: one arc to the folder and a branch to each file
    expect(document.querySelectorAll("svg.rel-arcs .rel-arc:not(.branch)")).toHaveLength(6);
    expect(document.querySelectorAll("svg.rel-arcs .rel-arc.branch")).toHaveLength(9);
  });

  it("bundles a folder's relatives into one arc to its heading, but not this file's own folder", async () => {
    const two = [rel("p1", "a.pdf", "30. Home/Property", [["tag", "Taxes"]]), rel("p2", "b.pdf", "30. Home/Property", [["sender", "x"], ["tag", "Taxes"], ["reference", "1"]])];
    setup({}, [...RELATIVES.filter((r) => r.drive_id !== "r5"), ...two]);
    await screen.findByRole("checkbox", { name: "Select a.pdf" });
    const trunk = document.querySelector('.rel-arc[data-target="folder:30. home/property"]');
    expect(trunk).not.toBeNull();
    expect(trunk).not.toHaveClass("branch");
    expect(document.querySelector('.rel-arc[data-target="p1"]')).toHaveClass("branch");
    expect(document.querySelector('.rel-arc[data-target="p2"]')).toHaveClass("branch");
    // thick as its best relative
    const width = (el: Element | null) => Number(el?.querySelector("path")?.getAttribute("stroke-width"));
    expect(width(trunk)).toBeGreaterThan(width(document.querySelector('.rel-arc[data-target="r6"]')));
    // the two in this file's own folder keep an arc each
    expect(document.querySelector('.rel-arc[data-target="r2"]')).not.toHaveClass("branch");
    expect(document.querySelector('.rel-arc[data-target="r3"]')).not.toHaveClass("branch");
  });

  it("pointing at a file outlines its branch and its folder's arc and steps the rest back", async () => {
    const two = [rel("p1", "a.pdf", "30. Home/Property", [["tag", "Taxes"]]), rel("p2", "b.pdf", "30. Home/Property", [["tag", "Taxes"]])];
    setup({}, [...RELATIVES, ...two]);
    await screen.findByRole("checkbox", { name: "Select a.pdf" });
    fireEvent.mouseEnter(rowOf("a.pdf"));
    expect(document.querySelector("svg.rel-arcs")).toHaveClass("pointing");
    expect(document.querySelector('.rel-arc[data-target="p1"]')).toHaveClass("on");
    expect(document.querySelector('.rel-arc[data-target="folder:30. home/property"]')).toHaveClass("on");
    expect(document.querySelector('.rel-arc[data-target="p2"]')).not.toHaveClass("on");
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

  it("has Show in folder, and Not related as a button of its own, last and set apart", async () => {
    const { user } = setup();
    await screen.findByRole("checkbox", { name: "Select receipt.pdf" });
    await user.hover(rowOf("20240928_Verohallinto.pdf"));
    const card = await screen.findByRole("group", { name: "What 20240928_Verohallinto.pdf shares" });
    const buttons = within(card).getAllByRole("button");
    // two by two: Quick look and Show in folder above, Relatives and Not related below
    expect(buttons.map((b) => b.textContent)).toEqual(["Quick look Space", "Show in folder", "Relatives Enter", "Not related"]);
    expect(buttons[0].closest(".rel-card-actions")).toHaveClass("rel-card-grid");
    // it changes data (with Undo): a button like the others, not a link
    const notRelated = within(card).getByRole("button", { name: "Not related" });
    expect(notRelated).not.toHaveClass("link-button");
    expect(notRelated).toHaveClass("rel-not-related");
  });

  it("Show in folder closes the dialog and opens the file's folder in Browse with it selected", async () => {
    const { user } = setup();
    await screen.findByRole("checkbox", { name: "Select receipt.pdf" });
    await user.hover(rowOf("20250926_Vuokratulot.pdf"));
    const card = await screen.findByRole("group", { name: "What 20250926_Vuokratulot.pdf shares" });
    await user.click(within(card).getByRole("button", { name: "Show in folder" }));
    expect(closed).toBe(1);
    expect(screen.getByTestId("where")).toHaveTextContent(
      `/browse?${new URLSearchParams({ path: "30. Home/Property", select: "r5" })}`,
    );
  });

  it("Show in folder in its Quick Look closes both and opens that pane's file in Browse", async () => {
    const { user } = setup({ "GET /api/files/r2": { status: 404, body: { error: "x" } } });
    await screen.findByRole("checkbox", { name: "Select receipt.pdf" });
    rowOf("20240928_Verohallinto.pdf").focus();
    await user.keyboard(" ");
    const ql = await screen.findByRole("dialog", { name: "Quick Look: 20240928_Verohallinto.pdf" });
    const [subject, relative] = within(ql).getAllByRole("button", { name: "Show in folder" });
    expect(subject).toBeDefined();
    await user.click(relative);
    expect(screen.queryByRole("dialog", { name: /Quick Look/ })).toBeNull();
    expect(closed).toBe(1);
    expect(screen.getByTestId("where")).toHaveTextContent(
      `/browse?${new URLSearchParams({ path: "13. Taxes", select: "r2" })}`,
    );
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

describe("walking the family tree", () => {
  const BACK_TO_FILE = [
    rel("d0", "20250930_Verohallinto.pdf", "13. Taxes", [["sender", "Verohallinto"]]),
    rel("r7", "20230930_Verohallinto.pdf", "13. Taxes/Old", [["sender", "Verohallinto"]]),
  ];
  const walkRoutes = {
    "GET /api/files/r2/relatives": { body: { ...body(BACK_TO_FILE), drive_id: "r2", common: [] } },
  };

  it("a relative's name shows its own relatives, marks the file it came from, and Back returns", async () => {
    const { user } = setup(walkRoutes);
    await user.click(await screen.findByRole("button", { name: "20240928_Verohallinto.pdf" }));
    await screen.findByRole("checkbox", { name: "Select 20230930_Verohallinto.pdf" });
    const trail = screen.getByRole("navigation", { name: "Files walked through" });
    expect(within(trail).getByRole("button", { name: "20250930_Verohallinto.pdf" })).toBeInTheDocument();
    expect(within(trail).getByText("20240928_Verohallinto.pdf")).toHaveAttribute("aria-current", "page");
    expect(within(rowOf("20250930_Verohallinto.pdf")).getByText("came from")).toBeInTheDocument();
    // the In common strip and the side panel belong to the new file
    expect(screen.queryByRole("group", { name: "In common" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /^Back/ }));
    await screen.findByRole("checkbox", { name: "Select receipt.pdf" });
    expect(screen.queryByRole("button", { name: /^Back/ })).not.toBeInTheDocument();
  });

  it("Enter on a row walks, the card offers Relatives, and Backspace or a crumb goes back", async () => {
    const { user } = setup(walkRoutes);
    await screen.findByRole("checkbox", { name: "Select receipt.pdf" });
    rowOf("20240928_Verohallinto.pdf").focus();
    await user.keyboard("{Enter}");
    await screen.findByRole("checkbox", { name: "Select 20230930_Verohallinto.pdf" });
    // the keys stay with the dialog after the outline changed
    await user.keyboard("{Backspace}");
    await screen.findByRole("checkbox", { name: "Select receipt.pdf" });
    fireEvent.mouseEnter(rowOf("20240928_Verohallinto.pdf"));
    await user.click(within(screen.getByRole("group", { name: /What .* shares/ })).getByRole("button", { name: /^Relatives/ }));
    await screen.findByRole("checkbox", { name: "Select 20230930_Verohallinto.pdf" });
    const trail = screen.getByRole("navigation", { name: "Files walked through" });
    await user.click(within(trail).getByRole("button", { name: "20250930_Verohallinto.pdf" }));
    await screen.findByRole("checkbox", { name: "Select receipt.pdf" });
  });

  it("forgets ticks when it moves to another file", async () => {
    const { user } = setup(walkRoutes);
    await user.click(await screen.findByRole("checkbox", { name: "Select receipt.pdf" }));
    await user.click(screen.getByRole("button", { name: "20240928_Verohallinto.pdf" }));
    await screen.findByRole("checkbox", { name: "Select 20230930_Verohallinto.pdf" });
    await user.click(screen.getByRole("button", { name: /^Back/ }));
    expect(await screen.findByRole("checkbox", { name: "Select receipt.pdf" })).not.toBeChecked();
  });
});
