import { fireEvent, screen, waitFor, within } from "@testing-library/react";
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

function setup(replay: object = REPLAY, props: Partial<Parameters<typeof RuleSheet>[0]> = {}, extra: Record<string, unknown> = {}) {
  const onClose = vi.fn();
  const calls = mockFetch({
    "GET /api/status": { body: { special_folders: { inbox: "##. Organize" } } },
    "GET /api/trays": { body: { trays: [{ id: "to-pay", name: "To pay", order: 1, item_title: "{name}", fields: {} }], errors: [] } },
    "GET /api/tags": { body: [] },
    "POST /api/rules/replay": { body: replay },
    "PUT /api/rules/kotihoito": { body: { rules: [], errors: [], state: { offer: true, declined: 0 } } },
    ...extra,
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
      when: { text_contains: ["kotihoito"], filename_matches: null, folder_is: null, zones: [], person: null },
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
        when: { text_contains: ["kotihoito"], filename_matches: null, folder_is: null, zones: [], person: null },
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
        zones: [{ box: [0.05, 0.02, 0.45, 0.14], text_contains: ["pohjola", "vakuutus"], image: null }],
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
      expect(within(sheet).getByRole("group", { name: "Area" })).toBeInTheDocument();
      await within(sheet).findByText(/Matches 4/);
      await user.click(within(sheet).getByRole("button", { name: "vakuutus" })); // unticked
      await waitFor(() => {
        const sent = posts(calls, "/api/rules/replay").at(-1)?.body as { rule: Record<string, unknown> };
        expect(sent.rule).toMatchObject({
          when: {
            text_contains: [],
            folder_is: "##. Organize",
            zones: [{ box: [0.05, 0.02, 0.45, 0.14], text_contains: ["pohjola"] }],
            person: "Tiina",
          },
          person_zone: [0.1, 0.2, 0.6, 0.4],
          sender: "Pohjola",
        });
      });
    });

    const TWO_AREAS = {
      ...ZONE_RULE,
      when: {
        ...ZONE_RULE.when,
        person: null,
        zones: [
          { box: [0.05, 0.02, 0.45, 0.14], text_contains: ["pohjola"], image: null },
          { box: [0.55, 0.05, 0.95, 0.12], text_contains: ["vakuutuskirja", "policy"], image: null },
        ],
      },
    };

    it("shows one group of word chips per area, each with its own words", async () => {
      setup(REPLAY, { initial: TWO_AREAS, filed: undefined });
      const one = await screen.findByRole("group", { name: "Area 1" });
      const two = screen.getByRole("group", { name: "Area 2" });
      expect(within(one).getByRole("button", { name: "pohjola" })).toBeInTheDocument();
      expect(within(two).getByRole("button", { name: "policy" })).toBeInTheDocument();
      expect(screen.queryByText("When the text contains")).toBeNull();
    });

    it("unticks a word in one area only, adds a word to an area, and removes an area", async () => {
      const { calls, user } = setup(REPLAY, { initial: TWO_AREAS, filed: undefined });
      const two = await screen.findByRole("group", { name: "Area 2" });
      await user.click(within(two).getByRole("button", { name: "policy" }));
      await user.type(within(two).getByLabelText("Add a word to area 2"), "kirja{Enter}");
      await waitFor(() => {
        const sent = posts(calls, "/api/rules/replay").at(-1)?.body as { rule: { when: { zones: { text_contains: string[] }[] } } };
        expect(sent.rule.when.zones.map((z) => z.text_contains)).toEqual([["pohjola"], ["vakuutuskirja", "kirja"]]);
      });
      await user.click(within(screen.getByRole("group", { name: "Area 1" })).getByRole("button", { name: "Remove area 1" }));
      expect(screen.queryByRole("group", { name: "Area 2" })).toBeNull();
      await waitFor(() => {
        const sent = posts(calls, "/api/rules/replay").at(-1)?.body as { rule: { when: { zones: { box: number[] }[] } } };
        expect(sent.rule.when.zones).toHaveLength(1);
        expect(sent.rule.when.zones[0].box).toEqual([0.55, 0.05, 0.95, 0.12]);
      });
    });

    it("needs a condition: no words and no area cannot be saved, and an area without a ticked word is named", async () => {
      const { user } = setup(REPLAY, { initial: TWO_AREAS, filed: undefined });
      const two = await screen.findByRole("group", { name: "Area 2" });
      await screen.findByText(/Matches 4/);
      await user.click(within(two).getByRole("button", { name: "vakuutuskirja" }));
      await user.click(within(two).getByRole("button", { name: "policy" }));
      expect(screen.getByText("Tick a word in area 2")).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
      await user.click(within(two).getByRole("button", { name: "Remove area 2" }));
      await user.click(within(screen.getByRole("group", { name: "Area" })).getByRole("button", { name: "Remove area" }));
      expect(screen.getByText("A rule needs a word or an area")).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
    });

    describe("a sample page", () => {
      const WITH_SAMPLE = { ...TWO_AREAS, sample: { drive_id: "s1", name: "policy.pdf", ext: "pdf" } };
      const INBOX = [{ record: { drive_id: "i1", path: "##. Organize/new.jpg", name: "new.jpg", ext: "jpg" } }];
      const props = { initial: WITH_SAMPLE, filed: undefined, samplePage: true };
      const area = (id: string) => document.querySelector(`[data-area="${id}"]`) as HTMLElement;
      /** Selects area ``id`` and drags it 20 px right and 40 px down on a 200 x 400 page. */
      function drag(id: string) {
        const layer = document.querySelector(".page-layer") as HTMLElement;
        layer.getBoundingClientRect = () => ({ left: 0, top: 0, width: 200, height: 400, right: 200, bottom: 400, x: 0, y: 0 }) as DOMRect;
        fireEvent.pointerDown(area(id), { clientX: 20, clientY: 20, button: 0 });
        fireEvent.pointerDown(area(id), { clientX: 20, clientY: 20, button: 0 });
        fireEvent.pointerMove(area(id), { clientX: 40, clientY: 60 });
        fireEvent.pointerUp(area(id), { clientX: 40, clientY: 60 });
      }

      it("shows the rule's areas on the page of the document it matched last", async () => {
        setup(REPLAY, props, { "GET /api/inbox": { body: INBOX } });
        const page = await screen.findByAltText("Page 1");
        expect(page).toHaveAttribute("src", "/api/files/s1/page/1.png?w=900");
        expect(screen.getByRole("combobox", { name: "Areas on a sample page" })).toHaveValue("s1");
        expect(area("pohjola:0")).toBeInTheDocument();
        expect(area("pohjola:1")).toBeInTheDocument();
        expect(screen.getByRole("option", { name: "Last document it matched: policy.pdf" })).toBeInTheDocument();
      });

      it("lets the owner pick a document from the Inbox when the rule has no last document", async () => {
        const { user } = setup(REPLAY, { ...props, initial: { ...WITH_SAMPLE, sample: null } }, { "GET /api/inbox": { body: INBOX } });
        expect(await screen.findByText("Pick a document to see the areas on its first page.")).toBeInTheDocument();
        expect(screen.queryByAltText("Page 1")).toBeNull();
        await screen.findByRole("option", { name: "new.jpg" });
        await user.selectOptions(screen.getByRole("combobox", { name: "Areas on a sample page" }), "i1");
        expect(await screen.findByAltText("Page 1")).toHaveAttribute("src", "/api/files/i1/raw");
      });

      it("is not shown unless asked for", async () => {
        setup(REPLAY, { initial: WITH_SAMPLE, filed: undefined });
        await screen.findByRole("group", { name: "Area 1" });
        expect(screen.queryByRole("combobox", { name: "Areas on a sample page" })).toBeNull();
      });

      it("dragging an area changes the rule and the test follows", async () => {
        const { calls } = setup(REPLAY, props, { "GET /api/inbox": { body: INBOX } });
        await screen.findByAltText("Page 1");
        await screen.findByText(/Matches 4/);
        const before = posts(calls, "/api/rules/replay").length;
        drag("pohjola:0"); // selects it, then moves it
        await waitFor(() => expect(posts(calls, "/api/rules/replay").length).toBeGreaterThan(before));
        const sent = posts(calls, "/api/rules/replay").at(-1)?.body as { rule: { when: { zones: { box: number[] }[] } } };
        expect(sent.rule.when.zones.map((z) => z.box.map((v) => Math.round(v * 1000) / 1000))).toEqual([
          [0.15, 0.12, 0.55, 0.24],
          [0.55, 0.05, 0.95, 0.12],
        ]);
      });

      it("drops a picture re-cut that comes back after a newer move of the same area", async () => {
        const PICTURE = {
          ...WITH_SAMPLE,
          when: {
            ...WITH_SAMPLE.when,
            zones: [{ box: [0.05, 0.02, 0.45, 0.14], text_contains: null, image: "areas/pohjola-1.png" }, WITH_SAMPLE.when.zones[1]],
          },
        };
        const waiting: ((image: string) => void)[] = [];
        const { calls } = setup(REPLAY, { ...props, initial: PICTURE }, {
          "GET /api/inbox": { body: INBOX },
          "POST /api/rules/area-picture": () =>
            new Promise((resolve) => waiting.push((image) => resolve({ body: { width: 3, height: 1, png: "iVBORw0KGgo=", image } }))),
        });
        await screen.findByAltText("Page 1");
        await screen.findByText(/Matches 4/);
        drag("pohjola:0"); // the first move: box A
        await waitFor(() => expect(waiting).toHaveLength(1));
        fireEvent.pointerDown(area("pohjola:0"), { clientX: 20, clientY: 20, button: 0 });
        fireEvent.pointerMove(area("pohjola:0"), { clientX: 60, clientY: 100 }); // box B
        fireEvent.pointerUp(area("pohjola:0"), { clientX: 60, clientY: 100 });
        await waitFor(() => expect(waiting).toHaveLength(2));
        waiting[1]("areas/pohjola-3.png"); // the newer cut comes back first
        await waitFor(() => expect(screen.getAllByRole("img", { name: /Picture of area/ })[0]).toHaveAttribute("src", "/api/rules/areas/pohjola-3.png"));
        waiting[0]("areas/pohjola-2.png"); // the older one last: must not win
        await new Promise((r) => setTimeout(r, 20));
        expect(screen.getAllByRole("img", { name: /Picture of area/ })[0]).toHaveAttribute("src", "/api/rules/areas/pohjola-3.png");
        await waitFor(() => {
          const sent = posts(calls, "/api/rules/replay").at(-1)?.body as { rule: { when: { zones: { box: number[]; image: string }[] } } };
          expect(sent.rule.when.zones[0].image).toBe("areas/pohjola-3.png");
          expect(sent.rule.when.zones[0].box.map((v) => Math.round(v * 1000) / 1000)).toEqual([0.25, 0.22, 0.65, 0.34]);
        });
      });

      it("changes the rule's own address area too", async () => {
        const { calls } = setup(REPLAY, { ...props, initial: { ...WITH_SAMPLE, person_zone: [0.1, 0.2, 0.6, 0.4] } }, { "GET /api/inbox": { body: INBOX } });
        await screen.findByAltText("Page 1");
        await screen.findByText(/Matches 4/);
        const address = document.querySelector('[data-kind="address"]') as HTMLElement;
        const layer = document.querySelector(".page-layer") as HTMLElement;
        layer.getBoundingClientRect = () => ({ left: 0, top: 0, width: 200, height: 400, right: 200, bottom: 400, x: 0, y: 0 }) as DOMRect;
        fireEvent.pointerDown(address, { clientX: 60, clientY: 120, button: 0 });
        fireEvent.pointerDown(address, { clientX: 60, clientY: 120, button: 0 });
        fireEvent.pointerMove(address, { clientX: 80, clientY: 160 });
        fireEvent.pointerUp(address, { clientX: 80, clientY: 160 });
        await waitFor(() => {
          const sent = posts(calls, "/api/rules/replay").at(-1)?.body as { rule: { person_zone: number[] } };
          expect(sent.rule.person_zone.map((v) => Math.round(v * 1000) / 1000)).toEqual([0.2, 0.3, 0.7, 0.5]);
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

  describe("picture areas", () => {
    const PICTURE_RULE = {
      id: "acme",
      file: "learned.yaml",
      learned: true,
      when: {
        text_contains: [],
        filename_matches: null,
        folder_is: "##. Organize",
        zones: [
          { box: [0.05, 0.03, 0.35, 0.1], text_contains: null, image: "areas/acme-1.png", min_score: 0.9 },
          { box: [0.5, 0.05, 0.9, 0.1], text_contains: ["lasku"], image: null, min_score: null },
        ],
        person: null,
      },
      then: { folder: "Insurance/Acme", name: null, tags: [], tray: null, payee: null },
      person_zone: null,
      sender: null,
      stats: { suggested: 2, changed: 0, last_used: null, flagged: false },
    };
    const RULES = { rules: [PICTURE_RULE], errors: [], state: { offer: true, declined: 0 }, unused_pictures: [], default_min_score: 0.8 };
    const sheetFor = (replay: object = REPLAY) => setup(replay, { initial: PICTURE_RULE, filed: undefined }, { "GET /api/rules": { body: RULES } });

    it("shows the crop of a picture area next to the words of a text area, with its own score", async () => {
      sheetFor();
      const sheet = await screen.findByRole("dialog", { name: "Edit rule acme" });
      const picture = within(sheet).getByRole("group", { name: "Area 1" });
      expect(within(picture).getByRole("img", { name: "Picture of area 1" })).toHaveAttribute("src", "/api/rules/areas/acme-1.png");
      expect(within(picture).getByRole("slider", { name: "Match needed for area 1" })).toHaveValue("0.9");
      expect(within(sheet).getByRole("group", { name: "Area 2" })).toHaveTextContent("lasku");
      // a text area is there: no hint to add one
      expect(within(sheet).queryByText(/Add a text box to make this faster/)).toBeNull();
    });

    it("tests and saves both kinds of area as they are, and a score back at the usual one is left out", async () => {
      const { calls, user } = sheetFor({ ...REPLAY, different: [] });
      const sheet = await screen.findByRole("dialog", { name: "Edit rule acme" });
      await within(sheet).findByText(/Matches 4 documents/);
      const zones = (c: Call) => (c.body as { rule: { when: { zones: unknown[] } } }).rule.when.zones;
      expect(zones(posts(calls, "/api/rules/replay")[0])).toEqual([
        { box: [0.05, 0.03, 0.35, 0.1], image: "areas/acme-1.png", min_score: 0.9 },
        { box: [0.5, 0.05, 0.9, 0.1], text_contains: ["lasku"] },
      ]);
      await user.click(within(sheet).getByRole("button", { name: "Use the usual 0.80" }));
      await waitFor(() => expect(posts(calls, "/api/rules/replay")).toHaveLength(2));
      expect(zones(posts(calls, "/api/rules/replay")[1])[0]).toEqual({ box: [0.05, 0.03, 0.35, 0.1], image: "areas/acme-1.png" });
      expect(within(sheet).getByRole("slider", { name: "Match needed for area 1" })).toHaveValue("0.8");
    });

    it("removing the picture area leaves the words, and a picture alone is told to add a text box", async () => {
      const { user } = sheetFor();
      const sheet = await screen.findByRole("dialog", { name: "Edit rule acme" });
      await user.click(within(sheet).getByRole("button", { name: "Remove area 2" }));
      expect(await within(sheet).findByText(/Add a text box to make this faster and surer/)).toBeInTheDocument();
      await user.click(within(sheet).getByRole("button", { name: "Remove area" }));
      expect(within(sheet).getByText("A rule needs a word or an area")).toBeInTheDocument();
      expect(within(sheet).getByRole("button", { name: "Save" })).toBeDisabled();
    });

    it("lists the scores of the matches and of the best non-matches under the proof", async () => {
      sheetFor({
        ...REPLAY,
        scores: [
          { path: "Insurance/a.pdf", score: 0.91, matched: true },
          { path: "Insurance/b.pdf", score: 0.96, matched: true },
          { path: "10. Bank/c.pdf", score: 0.62, matched: false },
        ],
      });
      const list = await screen.findByRole("region", { name: "Picture scores" });
      expect(within(list).getByText(/0\.90 is needed/)).toBeInTheDocument();
      const matched = within(list).getByRole("list", { name: "Matched documents" });
      expect(within(matched).getAllByRole("listitem").map((li) => li.textContent)).toEqual(["0.91Insurance/a.pdf", "0.96Insurance/b.pdf"]);
      expect(within(within(list).getByRole("list", { name: "Documents not matched" })).getByText("10. Bank/c.pdf", { exact: false })).toBeInTheDocument();
    });
  });
});
