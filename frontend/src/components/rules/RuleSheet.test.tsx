import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { type Call, deferred, mockFetch, renderWithProviders } from "../../test-utils";
import { RuleSheet } from "./RuleSheet";

const DRAFT = {
  id: "kotihoito",
  words: [
    { word: "kotihoito", ticked: true },
    { word: "lasku", ticked: false },
  ],
  folder: "20. Health/{year}",
  name: "{doc_date}_{stem}",
  tags: ["invoice"],
  tray: null,
  payee: null,
};
const REPLAY = {
  matched: 4,
  same: 3,
  different: [{ drive_id: "x1", path_now: "10. Financial/a.pdf", path_rule: "20. Health/2026/a.pdf" }],
  inbox: 2,
  shadowed: [{ drive_id: "x2", rule_id: "bank" }],
  checked: 4,
  total: 4,
  truncated: false,
};
const posts = (calls: Call[], url: string) => calls.filter((c) => c.method === "POST" && c.url === url);

function setup(replay: object = REPLAY, props: Partial<Parameters<typeof RuleSheet>[0]> = {}) {
  const onClose = vi.fn();
  const calls = mockFetch({
    "GET /api/status": { body: { special_folders: { inbox: "##. Organize" } } },
    "GET /api/trays": { body: { trays: [{ id: "to-pay", name: "To pay", order: 1, item_title: "{name}", fields: {} }], errors: [] } },
    "GET /api/tags": { body: [] },
    "POST /api/rules/replay": { body: replay },
    "PUT /api/rules/kotihoito": { body: { rules: [], errors: [], state: { offer: true, declined: 0 } } },
  } as never);
  renderWithProviders(
    <RuleSheet initial={DRAFT} filed={{ folder: "20. Health/2026", name: "a.pdf" }} onClose={onClose} {...props} />,
  );
  return { calls, onClose, user: userEvent.setup() };
}

describe("RuleSheet", () => {
  it("shows the words, the filed document and the replay proof", async () => {
    setup();
    const sheet = await screen.findByRole("dialog");
    expect(within(sheet).getByRole("button", { name: "kotihoito" })).toHaveAttribute("aria-pressed", "true");
    expect(within(sheet).getByRole("button", { name: "lasku" })).toHaveAttribute("aria-pressed", "false");
    expect(within(sheet).getByText(/Filed as:/)).toHaveTextContent("20. Health/2026/a.pdf");
    expect(within(sheet).getByText("Any ticked word is enough; more words catch more documents.")).toBeInTheDocument();
    expect(await within(sheet).findByText(/Matches 4 documents you filed before: 3 would land exactly where they are\./)).toBeInTheDocument();
    expect(within(sheet).getByText("10. Financial/a.pdf → 20. Health/2026/a.pdf")).toBeInTheDocument();
    expect(within(sheet).getByText("It also catches 2 documents in the inbox now.")).toBeInTheDocument();
    expect(within(sheet).getByText("For 1 of them rule bank comes first")).toBeInTheDocument();
  });

  it("says when nothing matches, and when only part was checked", async () => {
    setup({ ...REPLAY, matched: 0, same: 0, different: [], inbox: 0, shadowed: [] });
    expect(await screen.findByText("Not tested yet: no filed document matches it")).toBeInTheDocument();
  });

  it("says how many documents were checked when truncated", async () => {
    setup({ ...REPLAY, different: [], truncated: true, checked: 500, total: 900 });
    expect(await screen.findByText("Checked 500 of 900 documents")).toBeInTheDocument();
  });

  it("a pattern that cannot be filled says it would fail", async () => {
    setup({ ...REPLAY, different: [{ drive_id: "x1", path_now: "a/b.pdf", path_rule: "" }] });
    expect(await screen.findByText("a/b.pdf → would fail: the pattern cannot be filled for it")).toBeInTheDocument();
  });

  it("refreshes the replay 400 ms after the last edit with the rule built from the sheet", async () => {
    const { calls, user } = setup();
    await screen.findByText(/Matches 4/);
    const before = posts(calls, "/api/rules/replay").length;
    await user.click(screen.getByRole("button", { name: "lasku" }));
    await waitFor(() => expect(posts(calls, "/api/rules/replay").length).toBe(before + 1));
    const sent = posts(calls, "/api/rules/replay").at(-1)?.body as { rule: { id: string; when: unknown; then: unknown } };
    expect(sent.rule.id).toBe("kotihoito");
    expect(sent.rule.when).toEqual({ text_contains: ["kotihoito", "lasku"], filename_matches: null, folder_is: "##. Organize" });
    expect(sent.rule.then).toEqual({ folder: "20. Health/{year}", name: "{doc_date}_{stem}", tags: ["invoice"], tray: null, payee: null });
  });

  it("Save with differences asks first, then saves", async () => {
    const { calls, user, onClose } = setup();
    await screen.findByText(/Matches 4/);
    await user.click(screen.getByRole("button", { name: "Save" }));
    const ask = await screen.findByText("1 document would land somewhere else. Save anyway?");
    expect(calls.filter((c) => c.method === "PUT")).toHaveLength(0);
    await user.click(within(ask.closest("dialog") as HTMLElement).getByRole("button", { name: "Save anyway" }));
    await waitFor(() => expect(calls.filter((c) => c.method === "PUT")).toHaveLength(1));
    expect(calls.find((c) => c.method === "PUT")?.body).toMatchObject({ id: "kotihoito" });
    await waitFor(() => expect(onClose).toHaveBeenCalled());
  });

  it("Save without differences saves at once, sending replaces when updating", async () => {
    const { calls, user } = setup({ ...REPLAY, different: [] }, { replaces: "kotihoito" });
    await screen.findByText(/Matches 4/);
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(calls.filter((c) => c.method === "PUT")).toHaveLength(1));
    expect(calls.find((c) => c.method === "PUT")?.url).toBe("/api/rules/kotihoito?replaces=kotihoito");
  });

  it("says that saving a rule from a hand-written file rewrites it and keeps a copy", async () => {
    const own = (learned: boolean, file: string) => ({
      id: "kotihoito",
      file,
      learned,
      when: { text_contains: ["kotihoito"], filename_matches: null, folder_is: null, zone: null, person: null },
      then: { folder: "20. Health", name: null, tags: [], tray: null, payee: null },
      person_zone: null,
      sender: null,
      stats: { suggested: 0, changed: 0, last_used: null, flagged: false },
    });
    setup(REPLAY, { initial: own(false, "my-rules.yaml"), filed: undefined });
    const sheet = await screen.findByRole("dialog", { name: "Edit rule kotihoito" });
    expect(within(sheet).getByText(/Saving rewrites my-rules\.yaml/)).toHaveTextContent(
      "Saving rewrites my-rules.yaml, so the comments in it are lost. A copy of the old file is kept next to it (.bak).",
    );
  });

  it("says nothing about rewriting for a learned rule", async () => {
    setup(REPLAY, {
      initial: {
        id: "kotihoito",
        file: "learned.yaml",
        learned: true,
        when: { text_contains: ["kotihoito"], filename_matches: null, folder_is: null, zone: null, person: null },
        then: { folder: "20. Health", name: null, tags: [], tray: null, payee: null },
        person_zone: null,
        sender: null,
        stats: { suggested: 0, changed: 0, last_used: null, flagged: false },
      },
      filed: undefined,
    });
    await screen.findByRole("dialog", { name: "Edit rule kotihoito" });
    expect(screen.queryByText(/rewrites/)).toBeNull();
  });

  it("unticking the only word disables Save and says why", async () => {
    const { user } = setup();
    await screen.findByText(/Matches 4/);
    await user.click(screen.getByRole("button", { name: "kotihoito" }));
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
    expect(screen.getByText("Tick at least one word")).toBeInTheDocument();
  });

  it("adds a word and leaves a field out", async () => {
    const { calls, user } = setup();
    await screen.findByText(/Matches 4/);
    await user.type(screen.getByLabelText("Add a word"), "sähkö{Enter}");
    expect(screen.getByRole("button", { name: "sähkö" })).toHaveAttribute("aria-pressed", "true");
    await user.click(screen.getByLabelText("Leave out folder"));
    await waitFor(() => {
      const sent = posts(calls, "/api/rules/replay").at(-1)?.body as { rule: { then: { folder: unknown }; when: { text_contains: string[] } } };
      expect(sent.rule.then.folder).toBeNull();
      expect(sent.rule.when.text_contains).toEqual(["kotihoito", "sähkö"]);
    });
  });

  it("Save is disabled and reads Testing… until the first replay has finished", async () => {
    setup();
    const save = screen.getByRole("button", { name: "Testing…" });
    expect(save).toBeDisabled();
    expect(await screen.findByRole("button", { name: "Save" })).toBeEnabled();
  });

  it("Save is disabled within the debounce after an edit, and while the replay is in flight", async () => {
    const held = deferred<{ body: object }>();
    let first = true;
    const { user } = setup();
    mockFetch({
      "GET /api/status": { body: { special_folders: { inbox: "##. Organize" } } },
      "GET /api/trays": { body: { trays: [], errors: [] } },
      "POST /api/rules/replay": () => {
        if (first) {
          first = false;
          return { body: REPLAY };
        }
        return held.promise;
      },
    } as never);
    await screen.findByRole("button", { name: "Save" });
    await user.click(screen.getByRole("button", { name: "lasku" })); // an edit: the debounce runs
    expect(screen.getByRole("button", { name: "Testing…" })).toBeDisabled();
    await new Promise((r) => setTimeout(r, 600)); // the replay is in flight, held
    expect(screen.getByRole("button", { name: "Testing…" })).toBeDisabled();
    expect(screen.getByRole("region", { name: "Test result" })).toHaveAttribute("aria-busy", "true"); // the old proof stays
    expect(screen.getByText(/Matches 4/)).toBeInTheDocument();
    held.resolve({ body: { ...REPLAY, different: [] } });
    expect(await screen.findByRole("button", { name: "Save" })).toBeEnabled();
  });

  it("after a failed replay Save stays disabled until Try again succeeds", async () => {
    let fail = true;
    const { user } = setup();
    mockFetch({
      "GET /api/status": { body: { special_folders: { inbox: "##. Organize" } } },
      "GET /api/trays": { body: { trays: [], errors: [] } },
      "POST /api/rules/replay": () => (fail ? { status: 500, body: { error: "boom" } } : { body: REPLAY }),
    } as never);
    await user.click(await screen.findByRole("button", { name: "Try again" }));
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
    fail = false;
    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText(/Matches 4/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save" })).toBeEnabled();
  });
  describe("zones and senders", () => {
    const ZONE_RULE = {
      id: "pohjola",
      file: "learned.yaml",
      learned: true,
      when: {
        text_contains: [],
        filename_matches: null,
        folder_is: "##. Organize",
        zone: { box: [0.05, 0.02, 0.45, 0.14], text_contains: ["pohjola", "vakuutus"] },
        person: "Tiina",
      },
      then: { folder: "Insurance/{person}", name: null, tags: [], tray: null, payee: null },
      person_zone: [0.1, 0.2, 0.6, 0.4],
      sender: "Pohjola",
      stats: { suggested: 2, changed: 0, last_used: null, flagged: false },
    };

    it("edits the words of a rule's area and keeps its area, person, address area and sender", async () => {
      const { calls, user } = setup(REPLAY, { initial: ZONE_RULE, filed: undefined });
      const sheet = await screen.findByRole("dialog", { name: "Edit rule pohjola" });
      expect(within(sheet).getByRole("button", { name: "pohjola" })).toHaveAttribute("aria-pressed", "true");
      expect(within(sheet).getByText("Matches only in the area you drew on page 1.")).toBeInTheDocument();
      await within(sheet).findByText(/Matches 4/);
      await user.click(within(sheet).getByRole("button", { name: "vakuutus" })); // unticked
      await waitFor(() => {
        const sent = posts(calls, "/api/rules/replay").at(-1)?.body as { rule: Record<string, unknown> };
        expect(sent.rule).toMatchObject({
          when: {
            text_contains: [],
            folder_is: "##. Organize",
            zone: { box: [0.05, 0.02, 0.45, 0.14], text_contains: ["pohjola"] },
            person: "Tiina",
          },
          person_zone: [0.1, 0.2, 0.6, 0.4],
          sender: "Pohjola",
        });
      });
    });

    it("says what is not checked, and lists it", async () => {
      const { user } = setup({
        ...REPLAY,
        not_checked: [
          { path: "Insurance/a.pdf", reason: "page 1 not read yet" },
          { path: "Insurance/b.pdf", reason: "no OCR engine" },
        ],
      });
      expect(await screen.findByText(/\(2 not checked yet\)/)).toBeInTheDocument();
      await user.click(screen.getByText("Not checked yet (2)"));
      expect(screen.getByText("Insurance/b.pdf: no OCR engine")).toBeVisible();
    });

    it("asks again while page 1 is being read and shows the count", async () => {
      let reads = 0;
      mockFetch({
        "GET /api/status": { body: { special_folders: { inbox: "##. Organize" } } },
        "GET /api/trays": { body: { trays: [], errors: [] } },
        "GET /api/tags": { body: [] },
        "POST /api/rules/replay": () => ({ body: ++reads < 2 ? { ...REPLAY, reading: 23 } : { ...REPLAY, reading: 0 } }),
      } as never);
      renderWithProviders(<RuleSheet initial={DRAFT} onClose={vi.fn()} />);
      expect(await screen.findByText("Reading page 1 of 23 documents…")).toBeInTheDocument();
      await waitFor(() => expect(screen.queryByText(/Reading page 1 of/)).toBeNull(), { timeout: 4000 });
      expect(reads).toBe(2);
    });

    it("does not poll again once the sheet is closed", async () => {
      vi.useFakeTimers({ shouldAdvanceTime: true });
      try {
        const held = deferred<{ body: object }>();
        const calls = mockFetch({
          "GET /api/status": { body: { special_folders: { inbox: "##. Organize" } } },
          "GET /api/trays": { body: { trays: [], errors: [] } },
          "GET /api/tags": { body: [] },
          "POST /api/rules/replay": () => held.promise,
        } as never);
        const { unmount } = renderWithProviders(<RuleSheet initial={DRAFT} onClose={vi.fn()} />);
        await vi.advanceTimersByTimeAsync(500);
        await waitFor(() => expect(posts(calls, "/api/rules/replay")).toHaveLength(1)); // in flight
        unmount();
        held.resolve({ body: { ...REPLAY, reading: 23 } });
        await vi.advanceTimersByTimeAsync(10000);
        expect(posts(calls, "/api/rules/replay")).toHaveLength(1);
      } finally {
        vi.useRealTimers();
      }
    });

    it("compares a sender rule with the documents marked as from that sender", async () => {
      setup(
        { ...REPLAY, marked: { total: 16, found: 14, missed: ["Insurance/x.pdf", "Insurance/y.pdf"], not_checked: [] } },
        { initial: ZONE_RULE, filed: undefined },
      );
      expect(await screen.findByText("Finds 14 of the 16 documents you set as from Pohjola.")).toBeInTheDocument();
      expect(screen.getByText("Insurance/x.pdf")).toBeInTheDocument();
      expect(screen.getByText("Insurance/y.pdf")).toBeInTheDocument();
    });
  });
});
