/** Relatives in the details panel: the ranked list with its reasons, the ticked files'
 * actions (each previews first and sends the right drive ids), the link buttons that are
 * off with a reason, and Not related with its way back. */
import { cleanup, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it } from "vitest";
import type { Relative } from "../api/client";
import { type Call, mockFetch, renderWithProviders } from "../test-utils";
import { EMPTY_TEXT, RelativesBlock } from "./RelativesBlock";

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
  rel("r4", "20250210_Kotitalousvähennys.pdf", "13. Taxes", [["folder", "13. Taxes"]]),
  rel("r1", "scan_20261001.pdf", "##. Organize", [["sender", "Verohallinto"]], { in_inbox: true }),
  rel("r5", "20250926_Vuokratulot.pdf", "30. Home", [["tag", "Taxes"]], { same_month: true }),
  rel("r6", "receipt.pdf", "40. Misc", [["tag", "Taxes"]]),
];

const body = (relatives: Relative[], hidden = 0) => ({
  drive_id: "d0",
  relatives,
  common: [],
  total: relatives.length,
  hidden,
});
const STATUS = { body: { can_link: true } };
const batch = (ops: unknown[]) => ({
  batch_id: "b1",
  dry_run: false,
  done: ops,
  failed: null,
  error: null,
  index_error: null,
  unchanged: [],
  folder: "",
});
const op = (kind: string, src: string, dst: string, drive_id: string) => ({ kind, src, dst, drive_id, note: null });
const sent = (calls: Call[], method: string, url: string) => calls.filter((c) => c.method === method && c.url === url);

function setup(routes: Parameters<typeof mockFetch>[0] = {}, relatives = RELATIVES, hidden = 0) {
  const calls = mockFetch({
    "GET /api/files/d0/relatives": { body: body(relatives, hidden) },
    "GET /api/status": STATUS,
    "GET /api/folders": { body: ["13. Taxes", "30. Home", "40. Misc"] },
    ...routes,
  });
  renderWithProviders(
    <MemoryRouter>
      <RelativesBlock file={FILE} />
    </MemoryRouter>,
  );
  return { calls, user: userEvent.setup() };
}
const row = (name: string) => screen.getByRole("checkbox", { name: `Select ${name}` }).closest("li") as HTMLElement;
const tick = async (user: ReturnType<typeof userEvent.setup>, ...names: string[]) => {
  for (const n of names) await user.click(screen.getByRole("checkbox", { name: `Select ${n}` }));
};
const tipOf = (label: string) => screen.getByRole("button", { name: label }).closest(".button-wrap") as HTMLElement;

afterEach(cleanup);

describe("the list", () => {
  it("shows the top four, the unfiled one first, and counts the rest", async () => {
    setup();
    await screen.findByRole("checkbox", { name: "Select scan_20261001.pdf" });
    const names = screen.getAllByRole("checkbox").map((c) => c.getAttribute("aria-label"));
    expect(names).toEqual([
      "Select scan_20261001.pdf",
      "Select 20240928_Verohallinto.pdf",
      "Select 20250415_Veroilmoitus 2024.pdf",
      "Select 20250210_Kotitalousvähennys.pdf",
    ]);
    expect(screen.getByRole("button", { name: "2 more with one link in common" })).toBeInTheDocument();
    expect(screen.getByText("6")).toBeInTheDocument(); // the count beside the heading
    const card = row("scan_20261001.pdf");
    expect(card).toHaveClass("unfiled");
    expect(within(card).getByText("Same sender, not filed yet")).toBeInTheDocument();
    expect(within(card).getByText("Inbox")).toBeInTheDocument();
    expect(within(card).getByRole("link", { name: "Go to the inbox" })).toHaveAttribute("href", "/inbox");
  });

  it("names the kinds of link of each row, once each", async () => {
    setup();
    const first = await screen.findByRole("checkbox", { name: "Select 20240928_Verohallinto.pdf" });
    const chips = [...(first.closest("li") as HTMLElement).querySelectorAll(".relative-kinds .tag")].map((t) => t.textContent);
    expect(chips.sort()).toEqual(["collection", "folder", "sender", "tag"]);
  });

  it("More shows the rest, with the same-month booster", async () => {
    const { user } = setup();
    await user.click(await screen.findByRole("button", { name: /2 more/ }));
    const vuokra = row("20250926_Vuokratulot.pdf");
    expect(within(vuokra).getByText("+ same month")).toBeInTheDocument();
    expect(within(vuokra).getByText("30. Home")).toBeInTheDocument();
    expect(screen.getAllByRole("checkbox")).toHaveLength(6);
    expect(screen.queryByRole("button", { name: /more/ })).toBeNull();
  });

  it("says what to do when there are none", async () => {
    setup({}, []);
    expect(await screen.findByText(EMPTY_TEXT)).toBeInTheDocument();
  });

  it("says so when it cannot load", async () => {
    mockFetch({ "GET /api/files/d0/relatives": { status: 500, body: { error: "boom" } } });
    renderWithProviders(
      <MemoryRouter>
        <RelativesBlock file={FILE} />
      </MemoryRouter>,
    );
    expect(await screen.findByText(/Relatives could not be loaded/)).toBeInTheDocument();
  });

  it("Quick Look opens the relative in the existing Quick Look", async () => {
    const { user } = setup({ "GET /api/files/r2": { status: 404, body: { error: "x" } } });
    await user.click(await screen.findByRole("button", { name: "Quick Look 20240928_Verohallinto.pdf" }));
    expect(await screen.findByRole("dialog", { name: "Quick Look: 20240928_Verohallinto.pdf" })).toBeInTheDocument();
  });
});

describe("Show connections", () => {
  it("opens the Relatives dialog for this file", async () => {
    const { user } = setup();
    await user.click(await screen.findByRole("button", { name: "Show connections" }));
    const dialog = await screen.findByRole("dialog", { name: "Relatives" });
    expect(within(dialog).getAllByText("20250930_Verohallinto.pdf").length).toBeGreaterThan(0);
    await user.click(within(dialog).getByRole("button", { name: "Close" }));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Relatives" })).toBeNull());
  });
});

describe("the action bar", () => {
  it("appears when something is ticked, counting this file and the ticked", async () => {
    const { user } = setup();
    await screen.findByRole("checkbox", { name: "Select scan_20261001.pdf" });
    expect(screen.queryByRole("group", { name: "Actions for the ticked files" })).toBeNull();
    await tick(user, "20240928_Verohallinto.pdf", "20250415_Veroilmoitus 2024.pdf");
    const bar = screen.getByRole("group", { name: "Actions for the ticked files" });
    expect(within(bar).getByText("This file and 2 related")).toBeInTheDocument();
    await user.click(within(bar).getByRole("button", { name: "Clear" }));
    expect(screen.queryByRole("group", { name: "Actions for the ticked files" })).toBeNull();
  });

  it("disables both link buttons with their reasons when nothing needs a link", async () => {
    const { user } = setup();
    await screen.findByRole("checkbox", { name: "Select scan_20261001.pdf" });
    await tick(user, "20240928_Verohallinto.pdf", "20250415_Veroilmoitus 2024.pdf");
    expect(screen.getByRole("button", { name: "Link them here" })).toBeDisabled();
    expect(tipOf("Link them here")).toHaveAttribute("data-tip", "No links needed: all 2 are already in 13. Taxes");
    expect(screen.getByRole("button", { name: "Link this file there" })).toBeDisabled();
    expect(tipOf("Link this file there").getAttribute("data-tip")).toMatch(/^No links needed/);
  });

  it("hides the link buttons when links cannot be made here", async () => {
    const { user } = setup({ "GET /api/status": { body: { can_link: false } } });
    await screen.findByRole("checkbox", { name: "Select 20240928_Verohallinto.pdf" });
    await tick(user, "20240928_Verohallinto.pdf");
    await waitFor(() => expect(screen.queryByRole("button", { name: /Link/ })).toBeNull());
    expect(screen.getByRole("button", { name: "Tag…" })).toBeInTheDocument();
  });
});

describe("Link them here", () => {
  it("links only the ticked files that are not in this folder, after a preview", async () => {
    const { calls, user } = setup({
      "POST /api/browse/move/preview": { body: [op("symlink", "30. Home/20250926_Vuokratulot.pdf", "13. Taxes/20250926_Vuokratulot.pdf", "r5")] },
      "POST /api/browse/move": { body: batch([op("symlink", "30. Home/20250926_Vuokratulot.pdf", "13. Taxes/20250926_Vuokratulot.pdf", "r5")]) },
    });
    await user.click(await screen.findByRole("button", { name: /2 more/ }));
    await tick(user, "20240928_Verohallinto.pdf", "20250926_Vuokratulot.pdf");
    await user.click(screen.getByRole("button", { name: "Link it here" }));
    const want = { drive_ids: ["r5"], folder: "13. Taxes", mode: "link" };
    await waitFor(() => expect(sent(calls, "POST", "/api/browse/move/preview")).toHaveLength(1));
    expect(sent(calls, "POST", "/api/browse/move/preview")[0].body).toEqual(want);
    await user.click(await screen.findByRole("button", { name: /Make links/ }));
    await waitFor(() => expect(sent(calls, "POST", "/api/browse/move")).toHaveLength(1));
    expect(sent(calls, "POST", "/api/browse/move")[0].body).toEqual(want);
    expect(await screen.findByText(/Linked 20250926_Vuokratulot.pdf in 13. Taxes/)).toBeInTheDocument();
  });
});

describe("Link this file there", () => {
  const OPS = [
    op("symlink", FILE.path, "30. Home/20250930_Verohallinto.pdf", "d0"),
    op("symlink", FILE.path, "40. Misc/20250930_Verohallinto.pdf", "d0"),
  ];

  it("is one batch with a link in each folder of the ticked files, and one Undo", async () => {
    const { calls, user } = setup({
      "POST /api/browse/link-there/preview": { body: OPS },
      "POST /api/browse/link-there": { body: batch(OPS) },
    });
    await user.click(await screen.findByRole("button", { name: /2 more/ }));
    // two files in "13. Taxes" (here) and the inbox are not folders to link in
    await tick(user, "scan_20261001.pdf", "20240928_Verohallinto.pdf", "20250926_Vuokratulot.pdf", "receipt.pdf");
    await user.click(screen.getByRole("button", { name: "Link this file there" }));
    await waitFor(() => expect(sent(calls, "POST", "/api/browse/link-there/preview")).toHaveLength(1));
    expect(sent(calls, "POST", "/api/browse/link-there/preview")[0].body).toEqual({
      drive_id: "d0",
      folders: ["30. Home", "40. Misc"],
    });
    const dialog = await screen.findByRole("dialog", { name: /Link 20250930_Verohallinto.pdf in 2 folders/ });
    expect(within(dialog).getByText(/One Undo removes all the links/)).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: /Make links/ }));
    await waitFor(() => expect(sent(calls, "POST", "/api/browse/link-there")).toHaveLength(1));
    expect(sent(calls, "POST", "/api/browse/link-there")[0].body).toEqual({
      drive_id: "d0",
      folders: ["30. Home", "40. Misc"],
    });
    expect(await screen.findByText(/Linked 20250930_Verohallinto.pdf in 2 folders/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Undo" })).toBeInTheDocument();
  });

  it("shows a refused preview as an error and sends nothing more", async () => {
    const { calls, user } = setup({
      "POST /api/browse/link-there/preview": { status: 400, body: { error: "Windows needs Developer Mode" } },
    });
    await user.click(await screen.findByRole("button", { name: /2 more/ }));
    await tick(user, "20250926_Vuokratulot.pdf");
    await user.click(screen.getByRole("button", { name: "Link this file there" }));
    expect(await screen.findByText(/Cannot link: Windows needs Developer Mode/)).toBeInTheDocument();
    expect(sent(calls, "POST", "/api/browse/link-there")).toHaveLength(0);
  });
});

describe("Tag, collection and move", () => {
  it("Tag… puts the tag on this file and the ticked ones in one call, and Undo sends its record", async () => {
    const undo = { drop: [], detach: [{ name: "Taxes", drive_ids: ["d0", "r2"] }], restore: [] };
    const { calls, user } = setup({
      "POST /api/tags/apply": { body: { message: "Tagged 2 files 'Taxes'", undo } },
      "POST /api/tags/undo": { body: { message: "Undone", undo: { drop: [], detach: [], restore: [] } } },
      "GET /api/tags": { body: [] },
    });
    await screen.findByRole("checkbox", { name: "Select scan_20261001.pdf" });
    await tick(user, "20240928_Verohallinto.pdf");
    await user.click(screen.getByRole("button", { name: "Tag…" }));
    const sheet = await screen.findByRole("dialog", { name: "Tag 2 files" });
    await user.type(within(sheet).getByRole("combobox", { name: "Tags to add" }), "Taxes{Enter}");
    await user.click(within(sheet).getByRole("button", { name: "Tag 2 files" }));
    await waitFor(() => expect(sent(calls, "POST", "/api/tags/apply")).toHaveLength(1));
    expect(sent(calls, "POST", "/api/tags/apply")[0].body).toEqual({ tag: "Taxes", drive_ids: ["d0", "r2"] });
    await user.click(await screen.findByRole("button", { name: "Undo" }));
    await waitFor(() => expect(sent(calls, "POST", "/api/tags/undo")).toHaveLength(1));
    expect(sent(calls, "POST", "/api/tags/undo")[0].body).toEqual(undo);
  });

  it("Add to collection… adds only the files that are not in it yet", async () => {
    const collection = {
      id: 7, name: "Tax return", state: "open", created: 1, closed_at: null, publish: { ongoing: false },
      ongoing_rel: null, members: [], ongoing_status: null, summary: "", groups: [], parent_id: null,
      path: ["Tax return"], kind: null, files: 0, open_checks: 0,
    };
    const { calls, user } = setup({
      "GET /api/collections": { body: [collection] },
      "GET /api/files/d0/links": { body: { items: [], collections: [], note: "" } },
      "POST /api/collections/7/members": { body: { collection, batch: null, problems: [], ongoing_status: null } },
      "POST /api/collections/7/members/remove": { body: { collection, batch: null, problems: [], ongoing_status: null } },
    });
    await screen.findByRole("checkbox", { name: "Select scan_20261001.pdf" });
    // r2 is in "Tax return" already (one of its links says so)
    await tick(user, "20240928_Verohallinto.pdf", "20250415_Veroilmoitus 2024.pdf");
    await user.click(screen.getByRole("button", { name: "Add to collection…" }));
    const sheet = await screen.findByRole("dialog", { name: "Add 3 files to a collection" });
    await user.type(within(sheet).getByRole("combobox", { name: "Collection" }), "tax");
    await user.click(await screen.findByRole("option", { name: "Tax return" }));
    expect(await within(sheet).findByText("1 file already in Tax return; the other 2 are added.")).toBeInTheDocument();
    await user.click(within(sheet).getByRole("button", { name: "Add 2 files" }));
    await waitFor(() => expect(sent(calls, "POST", "/api/collections/7/members")).toHaveLength(1));
    expect(sent(calls, "POST", "/api/collections/7/members")[0].body).toEqual({ drive_ids: ["d0", "r3"] });
    await user.click(await screen.findByRole("button", { name: "Undo" }));
    await waitFor(() => expect(sent(calls, "POST", "/api/collections/7/members/remove")).toHaveLength(2));
    expect(sent(calls, "POST", "/api/collections/7/members/remove").map((c) => c.body)).toEqual([
      { drive_id: "d0" },
      { drive_id: "r3" },
    ]);
  });

  it("Move to folder… previews moving this file and the ticked ones", async () => {
    const { calls, user } = setup({
      "POST /api/browse/move/preview": { body: [op("move", "30. Home/20250926_Vuokratulot.pdf", "40. Misc/20250926_Vuokratulot.pdf", "r5")] },
    });
    await user.click(await screen.findByRole("button", { name: /2 more/ }));
    await tick(user, "20250926_Vuokratulot.pdf");
    await user.click(screen.getByRole("button", { name: "Move to folder…" }));
    const sheet = await screen.findByRole("dialog", { name: "Move 2 files to…" });
    await user.type(within(sheet).getByRole("combobox", { name: "Folder" }), "40. Misc");
    await user.click(within(sheet).getByRole("button", { name: "Preview move" }));
    await waitFor(() => expect(sent(calls, "POST", "/api/browse/move/preview")).toHaveLength(1));
    expect(sent(calls, "POST", "/api/browse/move/preview")[0].body).toEqual({
      drive_ids: ["d0", "r5"],
      folder: "40. Misc",
    });
    expect(sent(calls, "POST", "/api/browse/move")).toHaveLength(0); // nothing moves before the confirm
  });
});

describe("Not related", () => {
  it("marks the pair, takes the row out, and Undo shows it again", async () => {
    let marked = false;
    const { calls, user } = setup({
      "GET /api/files/d0/relatives": () => ({ body: body(marked ? RELATIVES.filter((r) => r.drive_id !== "r2") : RELATIVES, marked ? 1 : 0) }),
      "POST /api/files/d0/relatives/dismiss": () => {
        marked = true;
        return { body: { dismissed: [] } };
      },
      "POST /api/files/d0/relatives/restore": () => {
        marked = false;
        return { body: { dismissed: [] } };
      },
    });
    await user.click(await screen.findByRole("button", { name: "Not related: 20240928_Verohallinto.pdf" }));
    await waitFor(() => expect(sent(calls, "POST", "/api/files/d0/relatives/dismiss")).toHaveLength(1));
    expect(sent(calls, "POST", "/api/files/d0/relatives/dismiss")[0].body).toEqual({ drive_id: "r2" });
    await waitFor(() => expect(screen.queryByRole("checkbox", { name: "Select 20240928_Verohallinto.pdf" })).toBeNull());
    expect(await screen.findByRole("button", { name: "1 marked not related" })).toBeInTheDocument();
    await user.click(await screen.findByRole("button", { name: "Undo" }));
    await waitFor(() => expect(sent(calls, "POST", "/api/files/d0/relatives/restore")).toHaveLength(1));
    expect(sent(calls, "POST", "/api/files/d0/relatives/restore")[0].body).toEqual({ drive_id: "r2" });
    expect(await screen.findByRole("checkbox", { name: "Select 20240928_Verohallinto.pdf" })).toBeInTheDocument();
  });

  it("lists the marked files with Show again", async () => {
    const { calls, user } = setup(
      {
        "GET /api/files/d0/relatives/dismissed": {
          body: { dismissed: [{ drive_id: "x9", name: "old.pdf", path: "50. Old/old.pdf" }] },
        },
        "POST /api/files/d0/relatives/restore": { body: { dismissed: [] } },
      },
      RELATIVES,
      1,
    );
    await user.click(await screen.findByRole("button", { name: "1 marked not related" }));
    await user.click(await screen.findByRole("button", { name: "Show old.pdf again" }));
    await waitFor(() => expect(sent(calls, "POST", "/api/files/d0/relatives/restore")).toHaveLength(1));
    expect(sent(calls, "POST", "/api/files/d0/relatives/restore")[0].body).toEqual({ drive_id: "x9" });
  });

  it("shows the empty text and the way back when every relative is marked", async () => {
    setup({}, [], 2);
    expect(await screen.findByText(EMPTY_TEXT)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "2 marked not related" })).toBeInTheDocument();
  });
});
