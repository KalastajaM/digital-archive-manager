import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import type { IndexProblem } from "../api/client";
import { type Call, deferred, mockFetch, renderWithProviders } from "../test-utils";
import { useIndexErrorsSheet } from "./IndexErrors";

/** As the status line uses it: the button in a <p>, the sheet beside it. */
function IndexErrorsButton({ count }: { count: number }) {
  const sheet = useIndexErrorsSheet();
  return (
    <>
      <p>
        <button type="button" onClick={sheet.open}>
          {count} errors
        </button>
      </p>
      {sheet.view}
    </>
  );
}

const problem = (over: Partial<IndexProblem> = {}): IndexProblem => ({
  drive_id: "e1",
  path: "10. Financial/broken.pdf",
  name: "broken.pdf",
  state: "error",
  reason: "PDF is damaged",
  retry_at: null,
  ...over,
});

const ERRORS = [
  problem(),
  problem({ drive_id: "e2", path: "13. Taxes/odd‮fdp.docx", name: "odd‮fdp.docx", reason: "bad ‮zip" }),
];
const UNSUPPORTED = problem({ drive_id: "u1", path: "X/song.mp3", name: "song.mp3", state: "unsupported", reason: null });

const page = (rows: IndexProblem[], total = rows.length, byType: { ext: string | null; count: number }[] = []) => ({
  rows,
  total,
  unsupported_by_type: byType,
});

const posts = (calls: Call[], url: string) => calls.filter((c) => c.method === "POST" && c.url === url);

function setup(extra: Parameters<typeof mockFetch>[0] = {}) {
  const calls = mockFetch({
    "GET /api/index/errors": (call) => ({
      body: call.url.includes("all=1")
        ? page([...ERRORS, UNSUPPORTED], 3, [{ ext: "mp3", count: 1 }])
        : page(ERRORS),
    }),
    "GET /api/index/summary": {
      body: {
        searchable: 10220,
        waiting: 0,
        not_readable: 816,
        errors: 2,
        missing: 3,
        not_readable_by_type: [{ ext: "xlsx", count: 207 }],
        rows: [],
        offset: 0,
      },
    },
    "POST /api/index/retry": (call) => ({ body: { queued: (call.body as { drive_ids: string[] }).drive_ids.length } }),
    ...extra,
  });
  renderWithProviders(<IndexErrorsButton count={2} />);
  return { calls, user: userEvent.setup() };
}

const open = async (user: ReturnType<typeof userEvent.setup>) => {
  await user.click(screen.getByRole("button", { name: "2 errors" }));
  return screen.findByRole("dialog", { name: "Index" });
};
const rows = (dialog: HTMLElement) => within(dialog).getAllByRole("listitem");

describe("Index errors sheet", () => {
  it("shows the totals per state with plain explanations", async () => {
    const { user } = setup();
    const dialog = await open(user);
    const totals = await within(dialog).findByLabelText("Totals");
    expect(totals).toHaveTextContent("Searchable");
    expect(totals).toHaveTextContent("10 220");
    expect(totals).toHaveTextContent("findable by name");
    expect(totals).toHaveTextContent("Missing3");
  });

  it("the sheet is not inside the status line's paragraph", async () => {
    const { user } = setup();
    const dialog = await open(user);
    expect(dialog.closest("p")).toBeNull();
  });

  it("the error count opens a list of the failing files: name, path and reason, no attempts", async () => {
    const { calls, user } = setup();
    const dialog = await open(user);
    await waitFor(() => expect(rows(dialog)).toHaveLength(2));
    expect(calls.find((c) => c.url.startsWith("/api/index/errors"))?.url).toBe("/api/index/errors?limit=200");
    const [first, second] = rows(dialog);
    expect(first).toHaveTextContent("broken.pdf");
    expect(first).toHaveTextContent("10. Financial/broken.pdf");
    expect(first).toHaveTextContent("PDF is damaged");
    expect(second).toHaveTextContent("odd⟨U+202E⟩fdp.docx");
    expect(second).toHaveTextContent("13. Taxes/odd⟨U+202E⟩fdp.docx");
    expect(second).toHaveTextContent("bad ⟨U+202E⟩zip");
    expect(dialog).not.toHaveTextContent(/attempt|tries/i);
    for (const row of rows(dialog)) {
      expect(within(row).getByRole("button", { name: /^Retry/ })).toBeInTheDocument();
      expect(within(row).getByRole("button", { name: "Open" })).toBeInTheDocument();
      expect(within(row).getByRole("button", { name: "Show in Finder" })).toBeInTheDocument();
    }
  });

  it("Retry queues one file; Retry all queues every listed error", async () => {
    const { calls, user } = setup();
    const dialog = await open(user);
    await waitFor(() => expect(rows(dialog)).toHaveLength(2));
    await user.click(within(rows(dialog)[1]).getByRole("button", { name: /^Retry/ }));
    await waitFor(() => expect(posts(calls, "/api/index/retry")).toHaveLength(1));
    expect(posts(calls, "/api/index/retry")[0].body).toEqual({ drive_ids: ["e2"] });
    expect(await screen.findByText("Queued 1 file for indexing again")).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "Retry all" }));
    await waitFor(() => expect(posts(calls, "/api/index/retry")).toHaveLength(2));
    expect(posts(calls, "/api/index/retry")[1].body).toEqual({ drive_ids: ["e1", "e2"] });
  });

  it("Open and Show in Finder act on the row's file", async () => {
    const { calls, user } = setup({
      "POST /api/files/e2/open": { status: 204, body: null },
      "POST /api/files/e2/reveal": { status: 204, body: null },
    });
    const dialog = await open(user);
    await waitFor(() => expect(rows(dialog)).toHaveLength(2));
    await user.click(within(rows(dialog)[1]).getByRole("button", { name: "Open" }));
    await waitFor(() => expect(posts(calls, "/api/files/e2/open")).toHaveLength(1));
    await user.click(within(rows(dialog)[1]).getByRole("button", { name: "Show in Finder" }));
    await waitFor(() => expect(posts(calls, "/api/files/e2/reveal")).toHaveLength(1));
  });

  it("the toggle shows the unsupported files, explained", async () => {
    const { calls, user } = setup();
    const dialog = await open(user);
    await waitFor(() => expect(rows(dialog)).toHaveLength(2));
    const toggle = within(dialog).getByRole("checkbox", { name: /Show not readable files/ });
    expect(dialog).toHaveTextContent("These can't be read for text; the files themselves are fine");
    await user.click(toggle);
    await waitFor(() => expect(rows(dialog)).toHaveLength(3));
    expect(calls.some((c) => c.url === "/api/index/errors?all=1&limit=200")).toBe(true);
    expect(rows(dialog)[2]).toHaveTextContent("song.mp3");
    expect(rows(dialog)[2]).toHaveTextContent("Not readable");
    // Retry all still retries the errors only
    await user.click(within(dialog).getByRole("button", { name: "Retry all" }));
    await waitFor(() => expect(posts(calls, "/api/index/retry")).toHaveLength(1));
    expect(posts(calls, "/api/index/retry")[0].body).toEqual({ drive_ids: ["e1", "e2"] });
  });

  it("two clicks in one batch retry once; a failed retry says why", async () => {
    const held = deferred<{ status: number; body: unknown }>();
    const { calls, user } = setup({ "POST /api/index/retry": () => held.promise });
    const dialog = await open(user);
    await waitFor(() => expect(rows(dialog)).toHaveLength(2));
    const all = within(dialog).getByRole("button", { name: "Retry all" });
    fireEvent.click(all);
    fireEvent.click(all);
    await act(async () => held.resolve({ status: 400, body: { error: "index ‮locked" } }));
    expect(posts(calls, "/api/index/retry")).toHaveLength(1);
    expect(await screen.findByText("Could not retry: Invalid request: index ⟨U+202E⟩locked")).toBeInTheDocument();
  });

  it("an empty list says so; Esc closes the sheet", async () => {
    const { user } = setup({ "GET /api/index/errors": { body: page([]) } });
    const dialog = await open(user);
    expect(await within(dialog).findByText("No index errors")).toBeInTheDocument();
    const all = within(dialog).getByRole("button", { name: "Retry all" });
    expect(all).toBeDisabled();
    expect(all.parentElement).toHaveAttribute("data-tip", "No errors to retry: unsupported files have no text to read");
    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("a long list says how many more are not shown, and sums the unsupported files by type", async () => {
    const { user } = setup({
      "GET /api/index/errors": (call) => ({
        body: call.url.includes("all=1")
          ? page([...ERRORS, UNSUPPORTED], 1_623, [
              { ext: "heic", count: 1_240 },
              { ext: "mov", count: 380 },
              { ext: null, count: 1 },
            ])
          : page(ERRORS, 2),
      }),
    });
    const dialog = await open(user);
    await waitFor(() => expect(rows(dialog)).toHaveLength(2));
    expect(dialog).not.toHaveTextContent(/not shown/);
    await user.click(within(dialog).getByRole("checkbox", { name: /Show not readable files/ }));
    await waitFor(() => expect(rows(dialog)).toHaveLength(3));
    const exact = { normalizer: (text: string) => text }; // keep the narrow no-break spaces
    expect(within(dialog).getByText("1\u202f620 more not shown", exact)).toBeInTheDocument();
    expect(
      within(dialog).getByText("Not readable by type: 1\u202f240 .heic, 380 .mov, 1 without extension", exact),
    ).toBeInTheDocument();
  });

  it("Open, Show in Finder and Retry report inside the sheet (a toast would sit under the modal)", async () => {
    const REFUSED = "Won't open apps or scripts from the archive — use Show in Finder";
    const { user } = setup({
      "POST /api/files/e2/open": { status: 409, body: { error: REFUSED } },
      "POST /api/files/e2/reveal": { status: 204, body: null },
    });
    const dialog = await open(user);
    await waitFor(() => expect(rows(dialog)).toHaveLength(2));
    const toasts = document.querySelector(".toasts") as HTMLElement;
    const inline = (text: string) => {
      const line = within(dialog).getByText(text, { exact: false }).closest('[role="status"]');
      expect(line).not.toBeNull();
      expect(dialog.contains(line)).toBe(true);
      expect(toasts).not.toHaveTextContent(text);
    };
    await user.click(within(rows(dialog)[1]).getByRole("button", { name: "Open" }));
    await waitFor(() => inline(REFUSED));
    await user.click(within(rows(dialog)[1]).getByRole("button", { name: "Show in Finder" }));
    await waitFor(() => inline("Shown in Finder"));
    await user.click(within(rows(dialog)[0]).getByRole("button", { name: /^Retry/ }));
    await waitFor(() => inline("Queued 1 file for indexing again"));
  });
});
