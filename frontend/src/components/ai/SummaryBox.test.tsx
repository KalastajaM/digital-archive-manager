/** The file summary box: the user's own summary while current, else the AI one (marked
 * outdated when the file changed); an AI answer is a proposal until "Use this summary",
 * and a current summary the user wrote is only replaced after the confirm sheet. */
import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { AIStatus, FileSummaries } from "../../api/client";
import { type Call, deferred, mockFetch, renderWithProviders } from "../../test-utils";
import { OUTDATED, REPLACE_QUESTION, SummaryBox } from "./SummaryBox";
import { prepared, STATUS_ON } from "./testData";

const NONE: FileSummaries = { ai: null, user: null };
const USER: FileSummaries = { ai: null, user: { summary: "My own words‮", key_facts: [], outdated: false } };
const STALE: FileSummaries = {
  ai: { summary: "Old AI text", key_facts: ["84,20 €"], outdated: true },
  user: { summary: "Older user text", key_facts: [], outdated: true },
};
const ANSWER = { summary: "An electricity bill from Northpower Oy.", key_facts: ["15.11.2026", "84,20 €"] };

const puts = (calls: Call[]) => calls.filter((c) => c.method === "PUT");

function setup(summary: FileSummaries, status: AIStatus = STATUS_ON) {
  let current = summary;
  const calls = mockFetch({
    "GET /api/ai/status": { body: status },
    "GET /api/files/d1/summary": () => ({ body: current }),
    "PUT /api/files/d1/summary": (call) => {
      const b = call.body as { source: "ai" | "user"; summary: string; key_facts: string[] };
      const row = { summary: b.summary, key_facts: b.key_facts ?? [], outdated: false };
      current = b.source === "ai" ? { ai: row, user: null } : { ...current, user: row };
      return { body: current };
    },
    "POST /api/ai/summarize-document/prepare": { body: prepared({ task: "summarize-document" }) },
    "POST /api/ai/summarize-document/run": { body: { data: ANSWER, cost_eur: 0.0003, cached: false } },
  });
  const { client } = renderWithProviders(<SummaryBox driveId="d1" />);
  return Object.assign(calls, { client });
}

async function summarize() {
  await userEvent.click(await screen.findByRole("button", { name: "Summarize with AI…" }));
  const sheet = await screen.findByRole("dialog", { name: "What will be sent" });
  await userEvent.click(within(sheet).getByRole("button", { name: "Send" }));
  return screen.findByRole("region", { name: "AI summary" });
}

afterEach(() => {
  vi.unstubAllGlobals();
  delete document.documentElement.dataset.style;
});

describe("SummaryBox", () => {
  it("shows the user's current summary, through visible()", async () => {
    setup(USER);
    expect(await screen.findByText("My own words⟨U+202E⟩")).toBeInTheDocument();
    expect(screen.getByText("yours")).toBeInTheDocument();
  });

  it("falls back to the AI summary, marked outdated, with Summarize again", async () => {
    setup(STALE);
    expect(await screen.findByText("Old AI text")).toBeInTheDocument();
    expect(screen.getByText(OUTDATED)).toBeInTheDocument();
    expect(screen.getByText("by AI")).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "Summarize again…" })).toBeInTheDocument();
  });

  it("an AI answer is only a proposal until Use this summary saves it", async () => {
    const calls = setup(NONE);
    const proposal = await summarize();
    expect(within(proposal).getByText(ANSWER.summary)).toBeInTheDocument();
    expect(puts(calls)).toHaveLength(0);
    await userEvent.click(within(proposal).getByRole("button", { name: "Use this summary" }));
    await waitFor(() => expect(puts(calls)).toHaveLength(1));
    expect(puts(calls)[0].body).toEqual({ source: "ai", summary: ANSWER.summary, key_facts: ANSWER.key_facts, replace: false });
    expect(await screen.findByText(ANSWER.summary)).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "AI summary" })).not.toBeInTheDocument();
  });

  it("Discard drops the proposal without saving", async () => {
    const calls = setup(NONE);
    const proposal = await summarize();
    await userEvent.click(within(proposal).getByRole("button", { name: "Discard" }));
    expect(screen.queryByRole("region", { name: "AI summary" })).not.toBeInTheDocument();
    expect(puts(calls)).toHaveLength(0);
  });

  it("asks before replacing a current summary the user wrote", async () => {
    const calls = setup(USER);
    const proposal = await summarize();
    await userEvent.click(within(proposal).getByRole("button", { name: "Use this summary" }));
    const confirm = await screen.findByRole("dialog", { name: "Replace your summary?" });
    expect(within(confirm).getByText(REPLACE_QUESTION)).toBeInTheDocument();
    expect(REPLACE_QUESTION).toBe("Replace your summary with the AI one? Your text is not kept.");
    expect(puts(calls)).toHaveLength(0);
    await userEvent.click(within(confirm).getByRole("button", { name: "Replace" }));
    await waitFor(() => expect(puts(calls)).toHaveLength(1));
    expect(puts(calls)[0].body).toMatchObject({ source: "ai", replace: true });
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Replace your summary?" })).not.toBeInTheDocument());
  });

  it("Cancel on the confirm keeps the user's summary", async () => {
    const calls = setup(USER);
    const proposal = await summarize();
    await userEvent.click(within(proposal).getByRole("button", { name: "Use this summary" }));
    const confirm = await screen.findByRole("dialog", { name: "Replace your summary?" });
    await userEvent.click(within(confirm).getByRole("button", { name: "Cancel" }));
    expect(puts(calls)).toHaveLength(0);
    expect(screen.getByRole("region", { name: "AI summary" })).toBeInTheDocument();
  });

  it("a double click on Use saves once", async () => {
    const hold = deferred<{ body: FileSummaries }>();
    const calls = mockFetch({
      "GET /api/ai/status": { body: STATUS_ON },
      "GET /api/files/d1/summary": { body: NONE },
      "PUT /api/files/d1/summary": () => hold.promise,
      "POST /api/ai/summarize-document/prepare": { body: prepared({ task: "summarize-document" }) },
      "POST /api/ai/summarize-document/run": { body: { data: ANSWER, cost_eur: 0.0003, cached: false } },
    });
    renderWithProviders(<SummaryBox driveId="d1" />);
    const proposal = await summarize();
    const use = within(proposal).getByRole("button", { name: "Use this summary" });
    fireEvent.click(use);
    fireEvent.click(use);
    await waitFor(() => expect(puts(calls)).toHaveLength(1));
    hold.resolve({ body: { ai: { ...ANSWER, outdated: false }, user: null } });
    await waitFor(() => expect(screen.queryByRole("region", { name: "AI summary" })).not.toBeInTheDocument());
    expect(puts(calls)).toHaveLength(1);
  });

  it("Discard is disabled while Use is saving", async () => {
    const hold = deferred<{ body: FileSummaries }>();
    mockFetch({
      "GET /api/ai/status": { body: STATUS_ON },
      "GET /api/files/d1/summary": { body: NONE },
      "PUT /api/files/d1/summary": () => hold.promise,
      "POST /api/ai/summarize-document/prepare": { body: prepared({ task: "summarize-document" }) },
      "POST /api/ai/summarize-document/run": { body: { data: ANSWER, cost_eur: 0.0003, cached: false } },
    });
    renderWithProviders(<SummaryBox driveId="d1" />);
    const proposal = await summarize();
    await userEvent.click(within(proposal).getByRole("button", { name: "Use this summary" }));
    await waitFor(() => expect(within(proposal).getByRole("button", { name: "Discard" })).toBeDisabled());
    hold.resolve({ body: { ai: { ...ANSWER, outdated: false }, user: null } });
    await waitFor(() => expect(screen.queryByRole("region", { name: "AI summary" })).not.toBeInTheDocument());
  });

  it("an error from Replace closes the confirm sheet and shows the error", async () => {
    let attempt = 0;
    const calls = mockFetch({
      "GET /api/ai/status": { body: STATUS_ON },
      "GET /api/files/d1/summary": { body: USER },
      "PUT /api/files/d1/summary": () => {
        attempt += 1;
        return { status: 500, body: { error: "disk full" } };
      },
      "POST /api/ai/summarize-document/prepare": { body: prepared({ task: "summarize-document" }) },
      "POST /api/ai/summarize-document/run": { body: { data: ANSWER, cost_eur: 0.0003, cached: false } },
    });
    renderWithProviders(<SummaryBox driveId="d1" />);
    const proposal = await summarize();
    await userEvent.click(within(proposal).getByRole("button", { name: "Use this summary" }));
    const confirm = await screen.findByRole("dialog", { name: "Replace your summary?" });
    await userEvent.click(within(confirm).getByRole("button", { name: "Replace" }));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Replace your summary?" })).not.toBeInTheDocument());
    expect(await screen.findByRole("alert")).toHaveTextContent("disk full");
    expect(attempt).toBe(1);
    expect(puts(calls)[0].body).toMatchObject({ replace: true });
    // the proposal stays: Use can be tried again
    expect(screen.getByRole("region", { name: "AI summary" })).toBeInTheDocument();
  });

  it("switching AI off hides the proposal and its buttons", async () => {
    const { client } = setup(NONE);
    await summarize();
    act(() => client.setQueryData(["ai", "status"], { ...STATUS_ON, enabled: false, switched_on: false }));
    await waitFor(() => expect(screen.queryByRole("region", { name: "AI summary" })).not.toBeInTheDocument());
    expect(screen.queryByRole("button", { name: "Use this summary" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Discard" })).not.toBeInTheDocument();
  });

  it("Edit saves the user's own text with replace", async () => {
    const calls = setup(USER);
    await userEvent.click(await screen.findByRole("button", { name: "Edit" }));
    const box = screen.getByLabelText("Your summary");
    await userEvent.clear(box);
    await userEvent.type(box, "Paid in November");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(puts(calls)).toHaveLength(1));
    expect(puts(calls)[0].body).toEqual({ source: "user", summary: "Paid in November", key_facts: [], replace: true });
    expect(await screen.findByText("Paid in November")).toBeInTheDocument();
  });

  it("with AI off there is no AI button, only the hint", async () => {
    setup(NONE, { ...STATUS_ON, enabled: false, switched_on: false });
    // switched off (the key is there): the hint points at the switch
    expect(await screen.findByText(/Turn on AI/)).toHaveTextContent("Activity → AI, or dam ai --on");
    expect(screen.queryByRole("button", { name: "Summarize with AI…" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Write a summary" })).toBeInTheDocument();
  });

  describe("New look: edited in place", () => {
    it("a click on the text opens the field; leaving it saves the user's own text, with no Edit button", async () => {
      document.documentElement.dataset.style = "new";
      const calls = setup(USER);
      const text = await screen.findByRole("button", { name: "My own words⟨U+202E⟩" });
      expect(screen.queryByRole("button", { name: "Edit" })).toBeNull();
      await userEvent.click(text);
      const field = screen.getByRole("textbox", { name: "Summary" });
      await userEvent.clear(field);
      await userEvent.type(field, "Paid in November");
      await userEvent.tab();
      await waitFor(() => expect(puts(calls)).toHaveLength(1));
      expect(puts(calls)[0].body).toEqual({ source: "user", summary: "Paid in November", key_facts: [], replace: true });
      expect(await screen.findByRole("button", { name: "Paid in November" })).toBeInTheDocument();
    });

    it("an empty summary is a placeholder to click into, not a Write a summary button; Esc and an empty field save nothing", async () => {
      document.documentElement.dataset.style = "new";
      const calls = setup(NONE);
      await userEvent.click(await screen.findByRole("button", { name: "Add a summary…" }));
      expect(screen.queryByRole("button", { name: "Write a summary" })).toBeNull();
      await userEvent.type(screen.getByRole("textbox", { name: "Summary" }), "Draft");
      await userEvent.keyboard("{Escape}");
      await userEvent.click(await screen.findByRole("button", { name: "Add a summary…" }));
      await userEvent.tab();
      expect(await screen.findByRole("button", { name: "Add a summary…" })).toBeInTheDocument();
      expect(puts(calls)).toHaveLength(0);
    });

    it("read-only: the text is plain and says why", async () => {
      document.documentElement.dataset.style = "new";
      mockFetch({
        "GET /api/ai/status": { body: STATUS_ON },
        "GET /api/files/d1/summary": { body: USER },
      });
      renderWithProviders(<SummaryBox driveId="d1" readOnly="It is in To Delete." />);
      const text = await screen.findByText("My own words⟨U+202E⟩");
      expect(text.tagName).toBe("P");
      expect(text).toHaveAttribute("data-tip", "It is in To Delete.");
    });
  });
});
