import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { type Call, mockFetch, renderWithProviders } from "../../test-utils";
import { FilingRules } from "./FilingRules";

const rule = (id: string, extra: Record<string, unknown> = {}, stats: Record<string, unknown> = {}) => ({
  id,
  file: "rules.toml",
  learned: true,
  when: { text_contains: ["fortum", "lasku"], filename_matches: null, folder_is: null },
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
const ENTRY = (id: string, name: string) => ({ record: { drive_id: id, path: `##. Organize/${name}`, name } });

function setup(data: object = DATA(), extra: Record<string, unknown> = {}) {
  const calls = mockFetch({
    "GET /api/rules": { body: data },
    "GET /api/status": { body: { special_folders: { inbox: "##. Organize" } } },
    "GET /api/trays": { body: { trays: [], errors: [] } },
    "GET /api/tags": { body: [] },
    "GET /api/inbox": { body: [ENTRY("d1", "scan001.pdf"), ENTRY("d2", "bill.pdf")] },
    "POST /api/rules/replay": { body: { matched: 0, same: 0, different: [], inbox: 0, shadowed: [], checked: 0, total: 0, truncated: false } },
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
    await waitFor(() => expect(ofMethod(calls, "POST", "/api/rules/replay").length).toBeGreaterThan(0));
    expect((ofMethod(calls, "POST", "/api/rules/replay")[0].body as { rule: { id: string }; replaces: unknown }).replaces).toBeNull();
    await user.click(await within(sheet).findByRole("button", { name: "Save" }));
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
});
