/** "Find more with AI…" in Relatives: the button only when AI is on, the sheet with what
 * is sent before any run call, the AI picks as extra rows with their reason, the same
 * actions on them, Not related hiding a pick, and Hide. The API is mocked (no AI call). */
import { cleanup, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it } from "vitest";
import type { AIStatus, Relative } from "../api/client";
import { type Call, mockFetch, renderWithProviders } from "../test-utils";
import { prepared, STATUS_ON } from "./ai/testData";
import { RelativesBlock } from "./RelativesBlock";
import { RelativesDialog } from "./RelativesDialog";

const FILE = { drive_id: "d0", path: "13. Taxes/20250930_Verohallinto.pdf", name: "20250930_Verohallinto.pdf" };
const REGULAR: Relative = {
  drive_id: "r2",
  name: "20240928_Verohallinto.pdf",
  folder: "13. Taxes",
  path: "13. Taxes/20240928_Verohallinto.pdf",
  ext: "pdf",
  score: 2,
  links: [{ kind: "folder", value: "13. Taxes", weight: 2 }],
  same_month: false,
  in_inbox: false,
};
const PAYLOAD = [
  "The document:",
  "<subject>\nname: 20250930_Verohallinto.pdf\nfolder: 13. Taxes\n\nVeropäätös 2024 päätöksen numero 77\n</subject>",
  "Shortlist (2 files):",
  "<candidate>\nid: c1\nname: 20240115_Vuokrasopimus.pdf\nfolder: 30. Home\n\nVuokrasopimus vuokra 850 € kuukaudessa\n</candidate>",
  "<candidate>\nid: c2\nname: scan_0007.pdf\nfolder: ##. Organize\n\nLiite päätökseen päätöksen numero 77\n</candidate>",
].join("\n");
const PREPARED = prepared({
  task: "find-relatives",
  payload_text: PAYLOAD,
  files: ["d0", "x1", "x2"],
  notes: ["Not sent: files in excluded folders, whole files (only the excerpts above), tags, notes and checklists."],
});
const match = (drive_id: string, name: string, folder: string, reason: string, in_inbox = false) => ({
  drive_id,
  reason,
  confidence: 0.8,
  name,
  path: `${folder}/${name}`,
  folder,
  ext: "pdf",
  in_inbox,
});
const ANSWER = {
  drive_id: "d0",
  candidates: 28,
  hidden: 0,
  rejected: {},
  matches: [
    match("x1", "20240115_Vuokrasopimus.pdf", "30. Home", "the lease behind the rental income"),
    match("x2", "scan_0007.pdf", "##. Organize", "appendix: same decision number", true),
  ],
};

const OFF: AIStatus = { ...STATUS_ON, has_key: false, enabled: false };
const sent = (calls: Call[], method: string, url: string) => calls.filter((c) => c.method === method && c.url === url);

function setup(status: AIStatus = STATUS_ON, routes: Parameters<typeof mockFetch>[0] = {}, dialog = false) {
  const calls = mockFetch({
    "GET /api/files/d0/relatives": {
      body: { drive_id: "d0", relatives: [REGULAR], common: [], total: 1, hidden: 0 },
    },
    "GET /api/status": { body: { can_link: true } },
    "GET /api/ai/status": { body: status },
    "POST /api/ai/find-relatives/prepare": { body: PREPARED },
    "POST /api/ai/find-relatives/run": { body: { data: ANSWER, cost_eur: 0.0004, cached: false } },
    "POST /api/files/d0/relatives/dismiss": { body: { dismissed: [] } },
    ...routes,
  });
  renderWithProviders(
    <MemoryRouter>{dialog ? <RelativesDialog file={FILE} onClose={() => {}} /> : <RelativesBlock file={FILE} />}</MemoryRouter>,
  );
  return { calls, user: userEvent.setup() };
}

async function findMore(user: ReturnType<typeof userEvent.setup>) {
  await user.click(await screen.findByRole("button", { name: "Find more with AI…" }));
  return screen.findByRole("dialog", { name: "What will be sent" });
}

afterEach(cleanup);

describe("the button", () => {
  it("is not there while AI is off", async () => {
    setup(OFF);
    await screen.findByRole("checkbox", { name: "Select 20240928_Verohallinto.pdf" });
    expect(screen.queryByRole("button", { name: "Find more with AI…" })).not.toBeInTheDocument();
  });

  it("is there when AI is on, in the block and in the dialog", async () => {
    setup();
    expect(await screen.findByRole("button", { name: "Find more with AI…" })).toBeInTheDocument();
    cleanup();
    setup(STATUS_ON, {}, true);
    expect(await screen.findByRole("button", { name: "Find more with AI…" })).toBeInTheDocument();
  });
});

describe("the preview", () => {
  it("shows what is sent and what is not, and makes no run call before Send", async () => {
    const { calls, user } = setup();
    const sheet = await findMore(user);
    expect(sent(calls, "POST", "/api/ai/find-relatives/prepare")[0].body).toEqual({ params: { drive_id: "d0" } });
    expect(within(sheet).getByText(/This document: its name, folder/)).toBeInTheDocument();
    expect(within(sheet).getByText(/2 candidates/)).toBeInTheDocument();
    const list = within(sheet).getByRole("list", { name: "Candidates" });
    expect(within(list).getByText("20240115_Vuokrasopimus.pdf")).toBeInTheDocument();
    expect(within(sheet).getByRole("list", { name: "Left out" })).toHaveTextContent("Not sent: files in excluded folders");
    expect(within(sheet).getByText("claude-haiku-5-5")).toBeInTheDocument();
    expect(within(sheet).getByText(/at most/)).toBeInTheDocument();
    expect(within(sheet).getByText(/of .* this month/)).toBeInTheDocument();
    expect(sent(calls, "POST", "/api/ai/find-relatives/run")).toHaveLength(0);
  });

  it("Cancel sends nothing", async () => {
    const { calls, user } = setup();
    const sheet = await findMore(user);
    await user.click(within(sheet).getByRole("button", { name: "Cancel" }));
    expect(sent(calls, "POST", "/api/ai/find-relatives/run")).toHaveLength(0);
  });
});

describe("the picks", () => {
  async function ask(user: ReturnType<typeof userEvent.setup>) {
    const sheet = await findMore(user);
    await user.click(within(sheet).getByRole("button", { name: "Send" }));
    await screen.findByRole("checkbox", { name: "Select 20240115_Vuokrasopimus.pdf" });
  }

  it("shows AI rows with their reasons after the regular relatives, and the line", async () => {
    const { calls, user } = setup();
    await ask(user);
    expect(sent(calls, "POST", "/api/ai/find-relatives/run")[0].body).toEqual({ token: "tok-1" });
    const list = screen.getByRole("list", { name: "Found by AI" });
    expect(within(list).getAllByText("AI")).toHaveLength(2);
    expect(within(list).getByText("the lease behind the rental income")).toBeInTheDocument();
    expect(within(list).getByText("appendix: same decision number")).toBeInTheDocument();
    expect(screen.getByRole("status", { name: "AI result" })).toHaveTextContent("AI found 2 more out of 28 candidates · 0,0004 €");
    expect(screen.queryByRole("button", { name: "Find more with AI…" })).not.toBeInTheDocument();
    // nothing was stored as a relative
    expect(calls.filter((c) => c.method !== "GET" && !c.url.startsWith("/api/ai/"))).toHaveLength(0);
  });

  it("works with the same actions as the regular relatives", async () => {
    const { user } = setup();
    await ask(user);
    await user.click(screen.getByRole("checkbox", { name: "Select 20240115_Vuokrasopimus.pdf" }));
    const bar = screen.getByRole("group", { name: "Actions for the ticked files" });
    expect(within(bar).getByText("This file and 1 related")).toBeInTheDocument();
    expect(within(bar).getByRole("button", { name: "Tag…" })).toBeInTheDocument();
  });

  it("Not related marks the pair and hides an AI pick", async () => {
    const { calls, user } = setup();
    await ask(user);
    await user.click(screen.getByRole("button", { name: "Not related: 20240115_Vuokrasopimus.pdf" }));
    await waitFor(() => expect(sent(calls, "POST", "/api/files/d0/relatives/dismiss")).toHaveLength(1));
    expect(sent(calls, "POST", "/api/files/d0/relatives/dismiss")[0].body).toEqual({ drive_id: "x1" });
    await waitFor(() =>
      expect(screen.queryByRole("checkbox", { name: "Select 20240115_Vuokrasopimus.pdf" })).not.toBeInTheDocument(),
    );
    expect(screen.getByRole("checkbox", { name: "Select scan_0007.pdf" })).toBeInTheDocument();
  });

  it("Hide takes the AI rows and the line away, and the button comes back", async () => {
    const { user } = setup();
    await ask(user);
    await user.click(screen.getByRole("button", { name: "Hide" }));
    expect(screen.queryByRole("list", { name: "Found by AI" })).not.toBeInTheDocument();
    expect(screen.queryByRole("status", { name: "AI result" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Find more with AI…" })).toBeInTheDocument();
  });

  it("an answer from earlier is used for free and says so", async () => {
    const { calls, user } = setup(STATUS_ON, {
      "POST /api/ai/find-relatives/prepare": { body: { ...PREPARED, cached: ANSWER } },
      "POST /api/ai/find-relatives/run": { body: { data: ANSWER, cost_eur: 0, cached: true } },
    });
    const sheet = await findMore(user);
    expect(within(sheet).getByText("nothing (from earlier)")).toBeInTheDocument();
    await user.click(within(sheet).getByRole("button", { name: "Use this" }));
    await screen.findByRole("list", { name: "Found by AI" });
    expect(screen.getByRole("status", { name: "AI result" })).toHaveTextContent("from earlier");
    expect(sent(calls, "POST", "/api/ai/find-relatives/run")).toHaveLength(1);
  });

  it("says so when the AI found nothing more", async () => {
    const { user } = setup(STATUS_ON, {
      "POST /api/ai/find-relatives/run": { body: { data: { ...ANSWER, matches: [] }, cost_eur: 0.0003, cached: false } },
    });
    const sheet = await findMore(user);
    await user.click(within(sheet).getByRole("button", { name: "Send" }));
    expect(await screen.findByRole("status", { name: "AI result" })).toHaveTextContent("AI found nothing more out of 28 candidates");
    expect(screen.queryByRole("list", { name: "Found by AI" })).not.toBeInTheDocument();
  });

  it("shows the picks in the dialog outline with a dotted arc", async () => {
    const { user } = setup(STATUS_ON, {}, true);
    await findMore(user).then((s) => user.click(within(s).getByRole("button", { name: "Send" })));
    const row = await screen.findByLabelText("20240115_Vuokrasopimus.pdf, found by AI: the lease behind the rental income");
    expect(within(row).getByText("AI")).toBeInTheDocument();
    expect(document.querySelectorAll(".rel-arc.ai").length).toBeGreaterThan(0);
    expect(screen.getByRole("status", { name: "AI result" })).toHaveTextContent("AI found 2 more out of 28 candidates");
  });
});
