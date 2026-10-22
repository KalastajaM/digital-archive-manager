/** Ask: the question goes through the "What will be sent" sheet (question and snippets
 * shown), the answer has numbered citations that open Quick Look, a question with no
 * match is a blocked prepare (nothing can be sent), and answers last for the session. */
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, Link } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { AIStatus } from "../api/client";
import { prepared, STATUS_ON } from "../components/ai/testData";
import { type Call, mockFetch, renderWithProviders } from "../test-utils";
import Ask from "./Ask";

const PAYLOAD =
  "Question:\n<question>\nWhen is the Northpower bill due?\n</question>\n\nSources (the archive's 1 best matches):\n<source>\ndrive_id: b1\nname: northpower.pdf\nfolder: 10. Financial/Banks\n\nNorthpower Oy sähkölasku. Eräpäivä 15.11.2026.\n</source>";
const ANSWER = {
  answer: "It is due on 15.11.2026 [1], says the bill‮ [2].",
  citations: [
    { drive_id: "b1", quote: "Eräpäivä 15.11.2026", name: "northpower.pdf", marks: ["important"] },
    { drive_id: "b2", quote: "84,20 €", name: "northpower2.pdf" },
  ],
  rejected: {},
};
const record = (drive_id: string, name: string) => ({
  record: {
    drive_id,
    path: `10. Financial/Banks/${name}`,
    name,
    ext: "pdf",
    is_dir: false,
    is_link: false,
    link_target: null,
    size: 1000,
    mtime: 1_760_000_000,
    sha256: "x",
    doc_date: null,
    index_state: "indexed",
    retry_at: null,
    attempts: 0,
    missing: false,
    last_seen: null,
    parked_at: null,
  },
  tags: [],
});

const posts = (calls: Call[], url: string) => calls.filter((c) => c.method === "POST" && c.url === url);

function setup(
  status: AIStatus = STATUS_ON,
  prepare = prepared({ task: "ask-archive", payload_text: PAYLOAD }),
  extra: Parameters<typeof mockFetch>[0] = {},
) {
  const calls = mockFetch({
    "GET /api/ai/status": { body: status },
    "POST /api/ai/ask-archive/prepare": { body: prepare },
    "POST /api/ai/ask-archive/run": { body: { data: ANSWER, cost_eur: 0.0123, cached: false } },
    "GET /api/files/b1": { body: record("b1", "northpower.pdf") },
    "GET /api/files/b2": { body: record("b2", "northpower2.pdf") },
    "GET /api/files/b1/text": { body: { text: "Northpower", truncated: false, state: "indexed" } },
    "GET /api/files/b2/text": { body: { text: "Northpower", truncated: false, state: "indexed" } },
    ...extra,
  });
  renderWithProviders(
    <MemoryRouter initialEntries={["/ask"]}>
      <Routes>
        <Route path="/ask" element={<Ask />} />
        <Route path="/other" element={<Link to="/ask">back to Ask</Link>} />
      </Routes>
      <Link to="/other">elsewhere</Link>
    </MemoryRouter>,
  );
  return calls;
}

async function ask(question = "When is the Northpower bill due?") {
  const user = userEvent.setup();
  await user.type(await screen.findByLabelText("Question"), question);
  await user.click(screen.getByRole("button", { name: "Ask…" }));
  const sheet = await screen.findByRole("dialog", { name: "What will be sent" });
  return { user, sheet };
}

afterEach(() => vi.unstubAllGlobals());

describe("Ask", () => {
  it("shows the question and the snippets before sending, then the answer with citations", async () => {
    const calls = setup();
    const { user, sheet } = await ask();
    expect(posts(calls, "/api/ai/ask-archive/prepare")[0].body).toEqual({
      params: { question: "When is the Northpower bill due?" },
    });
    const text = within(sheet).getByLabelText("Text that will be sent");
    expect(text).toHaveTextContent("When is the Northpower bill due?");
    expect(text).toHaveTextContent("Eräpäivä 15.11.2026");
    expect(posts(calls, "/api/ai/ask-archive/run")).toHaveLength(0);
    await user.click(within(sheet).getByRole("button", { name: "Send" }));

    const answer = await screen.findByRole("article", { name: "When is the Northpower bill due?" });
    expect(answer).toHaveTextContent("It is due on 15.11.2026 [1], says the bill⟨U+202E⟩ [2].");
    expect(answer).toHaveTextContent("Cost: 0,01 €");
    const sources = within(answer).getByRole("list", { name: "Sources" });
    expect(within(sources).getAllByRole("listitem")).toHaveLength(2);
    const [cited, other] = within(sources).getAllByRole("listitem");
    expect(within(cited).getByRole("img", { name: "Important" })).toBeInTheDocument(); // the cited file's marks
    expect(within(other).queryByRole("img")).toBeNull();
    expect(screen.getByLabelText("Question")).toHaveValue("");
  });

  it("a citation opens Quick Look on that file", async () => {
    setup();
    const { user, sheet } = await ask();
    await user.click(within(sheet).getByRole("button", { name: "Send" }));
    const answer = await screen.findByRole("article", { name: "When is the Northpower bill due?" });
    await user.click(within(answer).getByRole("button", { name: "Source 2: northpower2.pdf" }));
    const look = await screen.findByRole("dialog", { name: /northpower2\.pdf/ });
    expect(look).toBeInTheDocument();
  });

  it("a source's marks follow a later mark change (unmarking it in Quick Look drops the icon)", async () => {
    const b1 = record("b1", "northpower.pdf");
    const calls = setup(STATUS_ON, undefined, {
      "GET /api/files/b1": { body: { ...b1, record: { ...b1.record, marks: ["important"] } } },
      "POST /api/marks/unimportant": { body: { collection: { id: 2, members: [], groups: [] }, batch: null, problems: [], ongoing_status: null } },
    });
    const { user, sheet } = await ask();
    await user.click(within(sheet).getByRole("button", { name: "Send" }));
    const answer = await screen.findByRole("article", { name: "When is the Northpower bill due?" });
    const [cited] = within(within(answer).getByRole("list", { name: "Sources" })).getAllByRole("listitem");
    expect(within(cited).getByRole("img", { name: "Important" })).toBeInTheDocument();
    await user.click(within(answer).getByRole("button", { name: "Source 1: northpower.pdf" }));
    const look = await screen.findByRole("dialog", { name: /northpower\.pdf/ });
    await user.click(await within(look).findByRole("button", { name: "Important (click to unmark)" }));
    await waitFor(() => expect(posts(calls, "/api/marks/unimportant")).toHaveLength(1));
    await waitFor(() => expect(within(cited).queryByRole("img", { name: "Important" })).toBeNull());
  });

  it("nothing matching is a blocked prepare: nothing can be sent", async () => {
    const calls = setup(
      STATUS_ON,
      prepared({ task: "ask-archive", payload_text: "", files: [], blocked: "Nothing in the archive matches" }),
    );
    const { sheet } = await ask("sauna dragons");
    expect(within(sheet).getByRole("alert")).toHaveTextContent("Can’t send: Nothing in the archive matches");
    expect(within(sheet).getByText("nothing (not sent)")).toBeInTheDocument();
    expect(within(sheet).getByRole("button", { name: "Send" })).toBeDisabled();
    expect(posts(calls, "/api/ai/ask-archive/run")).toHaveLength(0);
  });

  it("answers last for the session: leaving the screen and coming back keeps them", async () => {
    setup();
    const { user, sheet } = await ask();
    await user.click(within(sheet).getByRole("button", { name: "Send" }));
    await screen.findByRole("article", { name: "When is the Northpower bill due?" });
    await user.click(screen.getByRole("link", { name: "elsewhere" }));
    await user.click(await screen.findByRole("link", { name: "back to Ask" }));
    expect(await screen.findByRole("article", { name: "When is the Northpower bill due?" })).toBeInTheDocument();
  });

  it("with AI off there is no question box, only the hint", async () => {
    setup({ ...STATUS_ON, enabled: false, has_key: false });
    expect(await screen.findByText(/Turn on AI/)).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByLabelText("Question")).not.toBeInTheDocument());
  });
});
