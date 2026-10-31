import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { type Call, mockFetch, renderWithProviders, replayJob } from "../../test-utils";
import { FilingRules } from "./FilingRules";

const rule = (id: string, extra: Record<string, unknown> = {}, stats: Record<string, unknown> = {}) => ({
  id,
  file: "rules.toml",
  learned: true,
  when: { text_contains: ["fortum", "lasku"], filename_matches: null, folder_is: null, zones: [], person: null },
  then: { folder: "10. Financial/{year}", name: null, tags: [], tray: null, payee: null },
  stats: { suggested: 9, changed: 0, last_used: null, flagged: false, ...stats },
  ...extra,
});
const DATA = (over: Record<string, unknown> = {}) => ({
  rules: [
    rule("fortum"),
    rule("bank", {}, { suggested: 5, changed: 2, flagged: true }),
    rule("manual", { learned: false, file: "my-rules.toml" }, { suggested: 0, changed: 0 }),
  ],
  errors: [],
  state: { offer: true, declined: 2 },
  ...over,
});
const PEOPLE = {
  people: [{ name: "Tiina", match: ["Tiina Visser", "T. Visser"] }],
  address_zone: [0.06, 0.1, 0.52, 0.3],
  default_address_zone: [0.05, 0.12, 0.5, 0.28],
  address_zone_set: true,
};
const ENTRY = (id: string, name: string) => ({ record: { drive_id: id, path: `##. Organize/${name}`, name, ext: "pdf" } });

function setup(data: object = DATA(), extra: Record<string, unknown> = {}) {
  const calls = mockFetch({
    "GET /api/rules": { body: data },
    "GET /api/status": { body: { special_folders: { inbox: "##. Organize" }, page1: { read: 1240, total: 2015, backfill: true } } },
    "GET /api/settings/people": { body: PEOPLE },
    "GET /api/trays": { body: { trays: [], errors: [] } },
    "GET /api/tags": { body: [] },
    "GET /api/inbox": { body: [ENTRY("d1", "scan001.pdf"), ENTRY("d2", "bill.pdf")] },
    ...replayJob({ matched: 0, same: 0, different: [], inbox: 0, shadowed: [], checked: 0, total: 0, truncated: false }),
    ...extra,
  } as never);
  renderWithProviders(
    <MemoryRouter>
      <FilingRules />
    </MemoryRouter>,
  );
  return { calls, user: userEvent.setup() };
}
const ofMethod = (calls: Call[], method: string, url: string) => calls.filter((c) => c.method === method && c.url === url);

describe("FilingRules", () => {
  it("shows every rule with its words, folder and record", async () => {
    setup();
    const fortum = await screen.findByRole("button", { name: /^fortum/ });
    expect(fortum).toHaveTextContent("fortum, lasku");
    expect(fortum).toHaveTextContent("→ 10. Financial/{year}");
    expect(fortum).toHaveTextContent("kept 9 of 9");
    const bank = screen.getByRole("button", { name: /^bank/ });
    expect(bank).toHaveTextContent("changed 2 of 5");
    expect(bank).toHaveTextContent("Corrected recently");
    expect(screen.getByRole("button", { name: /^manual/ })).toHaveTextContent("not used yet");
  });

  it("names the file of a rule that was not learned and gives it no Up or Down", async () => {
    setup();
    const manual = (await screen.findByRole("button", { name: /^manual/ })).closest("li") as HTMLElement;
    expect(manual).toHaveTextContent("my-rules.toml");
    expect(within(manual).queryByRole("button", { name: /^Move/ })).toBeNull();
    const first = screen.getByRole("button", { name: /^fortum/ }).closest("li") as HTMLElement;
    expect(within(first).getByRole("button", { name: "Move fortum up" })).toBeDisabled();
    expect(within(first).getByRole("button", { name: "Move fortum down" })).toBeEnabled();
    const second = screen.getByRole("button", { name: /^bank/ }).closest("li") as HTMLElement;
    expect(within(second).getByRole("button", { name: "Move bank down" })).toBeDisabled(); // the last learned rule
    expect(within(second).getByRole("button", { name: "Move bank up" })).toBeEnabled();
  });

  it("moves a learned rule", async () => {
    const { calls, user } = setup(DATA(), { "POST /api/rules/bank/move": { body: DATA() } });
    await user.click(await screen.findByRole("button", { name: "Move bank up" }));
    await waitFor(() => expect(ofMethod(calls, "POST", "/api/rules/bank/move")).toHaveLength(1));
    expect(ofMethod(calls, "POST", "/api/rules/bank/move")[0].body).toEqual({ delta: -1 });
  });

  it("opens a rule in its sheet", async () => {
    const { user } = setup();
    await user.click(await screen.findByRole("button", { name: /^fortum/ }));
    expect(await screen.findByRole("dialog", { name: "Edit rule fortum" })).toBeInTheDocument();
  });

  it("starts a new rule in the sheet", async () => {
    const { calls, user } = setup(DATA(), { "PUT /api/rules/new-rule": { body: DATA() } });
    await user.click(await screen.findByRole("button", { name: /New rule/ }));
    const sheet = await screen.findByRole("dialog", { name: "Make a rule" });
    await user.type(within(sheet).getByLabelText("Add a word"), "sauna{Enter}");
    await waitFor(() => expect(ofMethod(calls, "POST", "/api/rules/replay/jobs").length).toBeGreaterThan(0));
    expect((ofMethod(calls, "POST", "/api/rules/replay/jobs")[0].body as { rule: { id: string }; replaces: unknown }).replaces).toBeNull();
    await user.click(await within(sheet).findByRole("button", { name: "Save rule" }));
    await waitFor(() => expect(ofMethod(calls, "PUT", "/api/rules/new-rule")).toHaveLength(1));
    expect(calls.find((c) => c.method === "PUT" && c.url === "/api/rules/new-rule")?.body).toMatchObject({ id: "new-rule" });
  });

  it("asks before deleting, then deletes", async () => {
    const { calls, user } = setup(DATA(), { "DELETE /api/rules/bank": { body: DATA({ rules: [] }) } });
    await user.click(await screen.findByRole("button", { name: "Delete rule bank" }));
    expect(ofMethod(calls, "DELETE", "/api/rules/bank")).toHaveLength(0);
    const ask = await screen.findByRole("dialog", { name: /Delete rule bank/ });
    await user.click(within(ask).getByRole("button", { name: "Cancel" }));
    expect(ofMethod(calls, "DELETE", "/api/rules/bank")).toHaveLength(0);
    await user.click(screen.getByRole("button", { name: "Delete rule bank" }));
    await user.click(within(await screen.findByRole("dialog", { name: /Delete rule bank/ })).getByRole("button", { name: "Delete rule" }));
    await waitFor(() => expect(ofMethod(calls, "DELETE", "/api/rules/bank")).toHaveLength(1));
  });

  it("deleting a rule from a hand-written file says the file is rewritten", async () => {
    const { user } = setup();
    await user.click(await screen.findByRole("button", { name: "Delete rule manual" }));
    const ask = await screen.findByRole("dialog", { name: /Delete rule manual/ });
    expect(within(ask).getByText(/Deleting rewrites my-rules\.toml/)).toHaveTextContent(
      "Deleting rewrites my-rules.toml, so the comments in it are lost. A copy of the old file is kept next to it (.bak).",
    );
    await user.click(within(ask).getByRole("button", { name: "Cancel" }));
    await user.click(screen.getByRole("button", { name: "Delete rule bank" }));
    const learned = await screen.findByRole("dialog", { name: /Delete rule bank/ });
    expect(within(learned).queryByText(/rewrites/)).toBeNull();
  });

  it("tests a document against the rules", async () => {
    const { calls, user } = setup(DATA(), {
      "POST /api/rules/explain": {
        body: [
          { rule_id: "fortum", matched: true, why: "contains fortum, lasku", wins: ["folder", "name"] },
          { rule_id: "bank", matched: false, why: "no \"tili\" in the text", wins: [] },
        ],
      },
    });
    await screen.findByRole("option", { name: "bill.pdf" });
    await user.selectOptions(screen.getByLabelText("Test a document"), "d2");
    await waitFor(() => expect(ofMethod(calls, "POST", "/api/rules/explain")).toHaveLength(1));
    expect(ofMethod(calls, "POST", "/api/rules/explain")[0].body).toEqual({ drive_id: "d2" });
    const list = await screen.findByRole("list", { name: "Rules for this document" });
    const rows = within(list).getAllByRole("listitem");
    expect(rows[0]).toHaveTextContent("fortum");
    expect(rows[0]).toHaveTextContent("matches");
    expect(rows[0]).toHaveTextContent("contains fortum, lasku");
    expect(rows[0]).toHaveTextContent("gives the folder, the name");
    expect(rows[1]).toHaveTextContent("no match");
  });

  it("posts the offer switch and forgets declined senders", async () => {
    const { calls, user } = setup(DATA(), { "PUT /api/rules/state": { body: { offer: false, declined: 2 } } });
    const sw = await screen.findByRole("checkbox", { name: "Offer to make a rule after I file a document by hand" });
    expect(sw).toBeChecked();
    await user.click(sw);
    await waitFor(() => expect(ofMethod(calls, "PUT", "/api/rules/state")).toHaveLength(1));
    expect(ofMethod(calls, "PUT", "/api/rules/state")[0].body).toEqual({ offer: false });
    await user.click(screen.getByRole("button", { name: "Forget 2 declined senders" }));
    await waitFor(() => expect(ofMethod(calls, "PUT", "/api/rules/state")).toHaveLength(2));
    expect(ofMethod(calls, "PUT", "/api/rules/state")[1].body).toEqual({ clear_declined: true });
  });

  it("hides the forget button when nothing was declined", async () => {
    setup(DATA({ state: { offer: true, declined: 0 } }));
    await screen.findByRole("checkbox", { name: /Offer to make a rule/ });
    expect(screen.queryByRole("button", { name: /Forget/ })).toBeNull();
  });

  it("lists the files that could not be loaded on top", async () => {
    setup(DATA({ errors: [{ file: "broken.toml", message: "bad line 3" }] }));
    const banner = await screen.findByRole("alert");
    expect(banner).toHaveTextContent("broken.toml");
    expect(banner).toHaveTextContent("bad line 3");
  });
  it("marks a rule that looks in an area of page 1, and lists the area's words", async () => {
    const zoned = rule("pohjola", {
      when: { text_contains: [], filename_matches: null, folder_is: null, zones: [{ box: [0, 0, 0.5, 0.2], text_contains: ["pohjola"], image: null }], person: null },
    });
    setup(DATA({ rules: [zoned] }));
    const line = await screen.findByRole("button", { name: /^pohjola/ });
    expect(line).toHaveTextContent("pohjola · area on page 1");
  });

  it("shows a rule's areas on the document it matched last when the rule is opened, and not for a plain rule", async () => {
    const zoned = rule("pohjola", {
      when: { text_contains: [], filename_matches: null, folder_is: null, zones: [{ box: [0, 0, 0.5, 0.2], text_contains: ["pohjola"], image: null }], person: null },
      sample: { drive_id: "s1", name: "policy.pdf", ext: "pdf" },
    });
    const { user } = setup(DATA({ rules: [zoned, rule("fortum")] }));
    await user.click(await screen.findByRole("button", { name: /^pohjola/ }));
    const sheet = await screen.findByRole("dialog", { name: "Edit rule pohjola" });
    expect(await within(sheet).findByAltText("Page 1")).toHaveAttribute("src", "/api/files/s1/page/1.png?w=900");
    expect(sheet.querySelector('[data-area="pohjola:0"]')).toBeInTheDocument();
    await user.click(within(sheet).getByRole("button", { name: "Cancel" }));
    await user.click(screen.getByRole("button", { name: /^fortum/ }));
    const plain = await screen.findByRole("dialog", { name: "Edit rule fortum" });
    expect(within(plain).queryByRole("combobox", { name: "Areas on a sample page" })).toBeNull();
  });

  it("shows the page-1 lines in a rule's area when testing a document", async () => {
    const { user } = setup(DATA(), {
      "POST /api/rules/explain": {
        body: [{ rule_id: "fortum", matched: false, why: "no pohjola in the area", wins: [], zone_lines: [["Pohjola Oy", "PL 1"]] }],
      },
    });
    await screen.findByRole("option", { name: "bill.pdf" });
    await user.selectOptions(screen.getByLabelText("Test a document"), "d2");
    const list = await screen.findByRole("list", { name: "Rules for this document" });
    expect(list).toHaveTextContent("Page 1 in the area: “Pohjola Oy”, “PL 1”");
  });

  it("draws the areas of every rule on page 1 when testing a document, dashed with the reason for the ones that did not match", async () => {
    const area = (rule_id: string, index: number, box: number[], matched: boolean, reason: string | null) => ({
      rule_id, index, box, kind: "text", lines: matched ? [[0.1, 0.05, 0.3, 0.08]] : [], score: null, matched, reason, wins: matched,
    });
    const { user } = setup(DATA(), {
      "POST /api/rules/explain": {
        body: [
          { rule_id: "pohjola", matched: true, why: "word", wins: ["folder"], zone_lines: [["Pohjola Oy"]], areas: [area("pohjola", 0, [0.05, 0.02, 0.45, 0.14], true, null)] },
          { rule_id: "fortum", matched: false, why: "x", wins: [], zone_lines: [[]], areas: [area("fortum", 0, [0.5, 0.5, 0.9, 0.6], false, "no word found in the area")] },
        ],
      },
      "GET /api/files/d2/suggestions": {
        body: {
          person: "Tiina",
          areas: [{ rule_id: "", index: 0, box: [0.06, 0.1, 0.52, 0.3], kind: "address", lines: [[0.08, 0.15, 0.3, 0.17]], score: null, matched: true, reason: null, wins: false }],
          person_line: { box: [0.08, 0.15, 0.3, 0.17] },
        },
      },
    });
    await screen.findByRole("option", { name: "bill.pdf" });
    await user.selectOptions(screen.getByLabelText("Test a document"), "d2");
    const page = await screen.findByAltText("Page 1");
    expect(page).toHaveAttribute("src", "/api/files/d2/page/1.png?w=900");
    expect(document.querySelector('[data-area="pohjola:0"]')).toHaveAttribute("data-matched", "true");
    const off = document.querySelector('[data-area="fortum:0"]') as HTMLElement;
    expect(off).toHaveClass("area-off");
    expect(off).toHaveAttribute("title", "fortum: no word found in the area");
    expect(await screen.findByTestId("person-line")).toHaveTextContent("For: Tiina, found here");
    expect(document.querySelector('[data-kind="address"]')).toBeInTheDocument();
  });

  describe("People and page 1", () => {
    it("shows how far page 1 is read, and switches the background reading", async () => {
      const { calls, user } = setup(DATA(), { "PUT /api/settings/page1-backfill": { body: { enabled: false } } });
      expect(await screen.findByText("Page 1 read for 1 240 of 2 015 documents")).toBeInTheDocument();
      const sw = screen.getByRole("checkbox", { name: "Read page 1 of older documents in the background" });
      expect(sw).toBeChecked();
      await user.click(sw);
      await waitFor(() => expect(ofMethod(calls, "PUT", "/api/settings/page1-backfill")).toHaveLength(1));
      expect(ofMethod(calls, "PUT", "/api/settings/page1-backfill")[0].body).toEqual({ enabled: false });
    });

    it("edits the people and the address area and saves them together", async () => {
      const { calls, user } = setup(DATA(), { "PUT /api/settings/people": { body: PEOPLE } });
      const people = await screen.findByRole("region", { name: "People" });
      expect(await within(people).findByLabelText("Name")).toHaveValue("Tiina");
      expect(within(people).getByLabelText(/Found in the address area as/)).toHaveValue("Tiina Visser\nT. Visser");
      await user.click(within(people).getByRole("button", { name: "Add a person" }));
      const names = within(people).getAllByLabelText("Name");
      await user.type(names[1], "Michiel");
      await user.type(within(people).getAllByLabelText(/Found in the address area as/)[1], "Michiel Visser");
      await user.click(within(people).getByRole("button", { name: "Save people" }));
      await waitFor(() => expect(ofMethod(calls, "PUT", "/api/settings/people")).toHaveLength(1));
      expect(ofMethod(calls, "PUT", "/api/settings/people")[0].body).toEqual({
        people: [
          { name: "Tiina", match: ["Tiina Visser", "T. Visser"] },
          { name: "Michiel", match: ["Michiel Visser"] },
        ],
      });
      expect(await within(people).findByText("Saved.")).toBeInTheDocument();
    });

    it("removes a person and leaves the address area alone", async () => {
      const { calls, user } = setup(DATA(), { "PUT /api/settings/people": { body: PEOPLE } });
      const people = await screen.findByRole("region", { name: "People" });
      await within(people).findByLabelText("Name");
      expect(within(people).getByText(/is in Settings, Reading documents/)).toBeInTheDocument();
      expect(within(people).queryByLabelText("Left")).toBeNull();
      await user.click(within(people).getByRole("button", { name: "Remove Tiina" }));
      await user.click(within(people).getByRole("button", { name: "Save people" }));
      await waitFor(() => expect(ofMethod(calls, "PUT", "/api/settings/people")).toHaveLength(1));
      expect(ofMethod(calls, "PUT", "/api/settings/people")[0].body).toEqual({ people: [] });
    });

    it("shows the server's message when the list is refused", async () => {
      const { user } = setup(DATA(), { "PUT /api/settings/people": { status: 400, body: { error: "Two people are called Tiina." } } });
      const people = await screen.findByRole("region", { name: "People" });
      await within(people).findByLabelText("Name");
      await user.click(within(people).getByRole("button", { name: "Save people" }));
      expect(await within(people).findByText("Two people are called Tiina.")).toBeInTheDocument();
      expect(within(people).queryByText("Saved.")).toBeNull();
    });
  });

  it("names the pictures of a rule and lists the picture files no rule uses", async () => {
    const withPicture = rule("acme", {
      when: {
        text_contains: [],
        filename_matches: null,
        folder_is: null,
        zones: [{ box: [0.1, 0.1, 0.3, 0.2], text_contains: null, image: "areas/acme-1.png", min_score: null }],
        person: null,
      },
    });
    setup(DATA({ rules: [withPicture], unused_pictures: ["old-1.png", "old-2.png"] }));
    expect(await screen.findByRole("button", { name: /^acme/ })).toHaveTextContent("a picture");
    expect(screen.getByText(/2 picture files in config\/rules\/areas \(old-1.png, old-2.png\) are not used by any rule/)).toBeInTheDocument();
  });

  describe("moving the unused pictures to To Delete", () => {
    const NAMES = ["old-1.png", "old-2.png"];
    const OPS = NAMES.map((n) => ({
      kind: "picture_to_quarantine",
      src: `abs:/home/me/config/rules/areas/${n}`,
      dst: `##. To Delete/dam rule picture ${n}`,
      drive_id: null,
      note: null,
    }));
    const batch = (dry_run: boolean, over: Record<string, unknown> = {}) => ({
      batch_id: "b1",
      dry_run,
      done: OPS,
      failed: null,
      error: null,
      index_error: null,
      ...over,
    });
    const quarantine = (calls: Call[]) => calls.filter((c) => c.url === "/api/rules/unused-pictures/quarantine");

    it("previews the plan, moves on confirm and offers Undo, which asks first", async () => {
      const { calls, user } = setup(DATA({ unused_pictures: NAMES }), {
        "POST /api/rules/unused-pictures/quarantine": (call: Call) => ({
          body: batch((call.body as { dry_run: boolean }).dry_run),
        }),
        "POST /api/activity/b1/undo/preview": {
          body: [
            { kind: "picture_back", src: OPS[0].dst, dst: "abs:/home/me/config/rules/areas/old-1.png", drive_id: null, note: null },
          ],
        },
      });
      await user.click(await screen.findByRole("button", { name: "Move 2 unused pictures to To Delete" }));
      const dialog = await screen.findByRole("dialog");
      expect(quarantine(calls).map((c) => c.body)).toEqual([{ names: NAMES, dry_run: true }]);
      expect(dialog).toHaveTextContent("##. To Delete/dam rule picture old-1.png");
      expect(within(dialog).getAllByText("Move to To Delete")).toHaveLength(2);
      expect(dialog).toHaveTextContent("old-2.png → ##. To Delete/dam rule picture old-2.png"); // source by file name, no computer path
      expect(dialog).not.toHaveTextContent("/home/me");
      await user.click(within(dialog).getByRole("button", { name: /^Move 2/ }));
      expect(await screen.findByText("Moved 2 unused pictures to To Delete")).toBeInTheDocument();
      expect(quarantine(calls).map((c) => c.body)).toEqual([
        { names: NAMES, dry_run: true },
        { names: NAMES, dry_run: false },
      ]);
      await user.click(screen.getByRole("button", { name: "Undo" }));
      const undo = await screen.findByRole("dialog", { name: "Undo these changes?" });
      expect(await within(undo).findByText("Put back")).toBeInTheDocument();
      expect(within(undo).getByText("rules/areas/old-1.png")).toBeInTheDocument();
    });

    it("moves nothing when the plan is cancelled", async () => {
      const { calls, user } = setup(DATA({ unused_pictures: NAMES }), {
        "POST /api/rules/unused-pictures/quarantine": { body: batch(true) },
      });
      await user.click(await screen.findByRole("button", { name: "Move 2 unused pictures to To Delete" }));
      await user.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Cancel" }));
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
      expect(quarantine(calls)).toHaveLength(1); // only the dry run
    });

    it("shows the server's refusal and offers no confirm", async () => {
      const { user } = setup(DATA({ unused_pictures: ["old-1.png"] }), {
        "POST /api/rules/unused-pictures/quarantine": {
          status: 400,
          body: { error: "The picture old-1.png is used by a rule or is not in the rules' picture folder, so it is not moved." },
        },
      });
      await user.click(await screen.findByRole("button", { name: "Move 1 unused picture to To Delete" }));
      expect(await screen.findByRole("alert")).toHaveTextContent("old-1.png is used by a rule");
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });

    it("has no button when every picture is used", async () => {
      setup(DATA({ unused_pictures: [] }));
      await screen.findByRole("button", { name: /^fortum/ });
      expect(screen.queryByRole("button", { name: /to To Delete/ })).not.toBeInTheDocument();
    });
  });
});
