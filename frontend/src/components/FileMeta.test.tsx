/** The inline details of a file (stars spec §7): the Rename pencil, Move file to…, the
 * tags as chips, Ask AI, and the rules that disable them. */
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import type { FileDetail } from "../api/client";
import { type Call, mockFetch, renderWithProviders, undoButton } from "../test-utils";
import { prepared, STATUS_ON } from "./ai/testData";
import { FileMeta, type MetaFile } from "./FileMeta";

const PATH = "10. Financial/Banks/scan‮.pdf";
const FILE: MetaFile = { drive_id: "d1", path: PATH, is_dir: false, is_link: false, marks: [] };
const DETAIL: FileDetail = {
  record: {
    drive_id: "d1",
    path: PATH,
    name: "scan‮.pdf",
    ext: "pdf",
    is_dir: false,
    is_link: false,
    link_target: null,
    size: 10,
    mtime: 1_760_000_000,
    sha256: null,
    doc_date: null,
    index_state: "indexed",
    retry_at: null,
    attempts: 0,
    missing: false,
    last_seen: null,
    parked_at: null,
    marks: [],
  },
  tags: ["bank", "power"],
  link_target_id: null,
  link_target_path: null,
  link_target_inside: false,
};
const FOLDERS = ["10. Financial/Banks", "10. Financial/Bills"];

const rename = (dst: string) => ({ kind: "rename", src: PATH, dst, drive_id: "d1", note: null });
const moved = (dst: string) => ({ kind: "move", src: PATH, dst, drive_id: "d1", note: null });
const result = (ops: unknown[]) => ({
  batch_id: "r1", dry_run: false, done: ops, failed: null, error: null, index_error: null, unchanged: [], folder: "",
});
const sent = (calls: Call[], method: string, url: string) => calls.filter((c) => c.method === method && c.url === url);

function Harness({ file = FILE, disabled }: { file?: MetaFile; disabled?: boolean }) {
  return (
    <FileMeta file={file} disabled={disabled}>
      {(meta) => (
        <>
          {meta.header}
          <div data-testid="toolbar">{meta.marks}</div>
          {meta.tags}
        </>
      )}
    </FileMeta>
  );
}

function setup(extra: Parameters<typeof mockFetch>[0] = {}, props: Parameters<typeof Harness>[0] = {}) {
  const calls = mockFetch({
    "GET /api/files/d1": { body: DETAIL },
    "GET /api/folders": { body: FOLDERS },
    "PUT /api/files/d1/tags": (call) => ({ body: { tags: (call.body as { tags: string[] }).tags } }),
    ...extra,
  });
  renderWithProviders(
    <MemoryRouter>
      <Harness {...props} />
    </MemoryRouter>,
  );
  return { calls, user: userEvent.setup() };
}

// enabled once the file's record (and so its tags) has loaded
const tagBox = async () => {
  const box = await screen.findByRole("textbox", { name: "Add a tag to scan⟨U+202E⟩.pdf" });
  await waitFor(() => expect(box).toBeEnabled());
  return box;
};
const nameBox = () => screen.findByRole("textbox", { name: "File name" });

describe("layout", () => {
  it("shows the name, the path, Rename, Move file to…, Ask AI, and ★ / ! as their own group", async () => {
    setup();
    expect(screen.getByRole("heading", { name: "scan⟨U+202E⟩.pdf" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Rename" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Move file to…" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Ask AI" })).toBeInTheDocument();
    expect(within(screen.getByTestId("toolbar")).getByRole("button", { name: "Star" })).toBeInTheDocument();
    expect(within(screen.getByTestId("toolbar")).getByRole("button", { name: "Mark Important" })).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "Remove tag bank" })).toBeInTheDocument();
  });
});

describe("Rename", () => {
  it("turns the name into a field with the extension kept; Enter previews, confirms, applies exactly that, and Undo works", async () => {
    const op = rename("10. Financial/Banks/20261001_Northpower.pdf");
    const { user, calls } = setup({
      "POST /api/browse/rename/preview": { body: [op] },
      "POST /api/browse/rename": { body: result([op]) },
      "POST /api/activity/r1/undo/preview": { body: [{ ...op, src: op.dst, dst: PATH }] },
      "POST /api/activity/r1/undo": { body: result([{ ...op, src: op.dst, dst: PATH }]) },
    });
    const user_ = user;
    await user_.click(screen.getByRole("button", { name: "Rename" }));
    const box = await nameBox();
    expect(box).toHaveValue("scan‮"); // the stem; ".pdf" is shown beside it, not editable
    expect(screen.getByText(".pdf")).toBeInTheDocument();
    await user_.clear(box);
    await user_.type(box, "20261001_Northpower{Enter}");

    const confirm = await screen.findByRole("dialog", { name: "Rename to 20261001_Northpower.pdf?" });
    const request = { drive_id: "d1", name: "20261001_Northpower.pdf", folder: "10. Financial/Banks" };
    expect(sent(calls, "POST", "/api/browse/rename/preview")[0].body).toEqual(request);
    expect(sent(calls, "POST", "/api/browse/rename")).toHaveLength(0);
    const apply = within(confirm).getByRole("button", { name: "Rename" });
    fireEvent.click(apply);
    fireEvent.click(apply); // a second click in the same tick applies nothing more
    await waitFor(() => expect(sent(calls, "POST", "/api/browse/rename")).toHaveLength(1));
    expect(sent(calls, "POST", "/api/browse/rename")[0].body).toEqual(request);
    expect(await screen.findByText("Renamed to 20261001_Northpower.pdf")).toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: "File name" })).not.toBeInTheDocument(); // back to the heading
    await user_.click(screen.getByRole("button", { name: "Undo" }));
    const undo = await screen.findByRole("dialog", { name: "Undo these changes?" });
    await user_.click(await undoButton(undo));
    await waitFor(() => expect(sent(calls, "POST", "/api/activity/r1/undo")).toHaveLength(1));
  });

  it("Esc cancels without asking the server anything", async () => {
    const { user, calls } = setup();
    await user.click(screen.getByRole("button", { name: "Rename" }));
    await user.type(await nameBox(), "x{Escape}");
    expect(screen.queryByRole("textbox", { name: "File name" })).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "scan⟨U+202E⟩.pdf" })).toBeInTheDocument();
    expect(calls.filter((c) => c.method === "POST")).toHaveLength(0);
  });

  it("an unchanged name just closes the field; an empty one is refused", async () => {
    const { user, calls } = setup();
    await user.click(screen.getByRole("button", { name: "Rename" }));
    await user.clear(await nameBox());
    await user.keyboard("{Enter}");
    expect(screen.getByRole("alert")).toHaveTextContent("Enter a name.");
    await user.type(await nameBox(), "scan‮{Enter}");
    expect(screen.queryByRole("textbox", { name: "File name" })).not.toBeInTheDocument();
    expect(calls.filter((c) => c.method === "POST")).toHaveLength(0);
  });

  it("Cancel on the confirm changes nothing and keeps the typed name", async () => {
    const op = rename("10. Financial/Banks/x.pdf");
    const { user, calls } = setup({ "POST /api/browse/rename/preview": { body: [op] } });
    await user.click(screen.getByRole("button", { name: "Rename" }));
    const box = await nameBox();
    await user.clear(box);
    await user.type(box, "x{Enter}");
    const confirm = await screen.findByRole("dialog", { name: "Rename to x.pdf?" });
    await user.click(within(confirm).getByRole("button", { name: "Cancel" }));
    expect(sent(calls, "POST", "/api/browse/rename")).toHaveLength(0);
    expect(await nameBox()).toHaveValue("x");
  });

  it("a refused preview is said under the name, which stays editable", async () => {
    const { user } = setup({
      "POST /api/browse/rename/preview": { status: 400, body: { error: "the name is longer than 255 bytes" } },
    });
    await user.click(screen.getByRole("button", { name: "Rename" }));
    const box = await nameBox();
    await user.clear(box);
    await user.type(box, "long{Enter}");
    expect(await screen.findByRole("alert")).toHaveTextContent("the name is longer than 255 bytes");
    expect(await nameBox()).toHaveValue("long");
  });
});

describe("Move file to…", () => {
  it("opens the folder picker, then the same preview and confirm; the name is kept", async () => {
    const op = moved("10. Financial/Bills/scan‮.pdf");
    const { user, calls } = setup({
      "POST /api/browse/move/preview": { body: [op] },
      "POST /api/browse/move": { body: result([op]) },
    });
    await user.click(screen.getByRole("button", { name: "Move file to…" }));
    const sheet = await screen.findByRole("dialog", { name: "Move 1 file to…" });
    const field = within(sheet).getByRole("combobox");
    await user.clear(field);
    await user.type(field, "10. Financial/Bills");
    await user.click(within(sheet).getByRole("button", { name: "Preview move" }));
    const confirm = await screen.findByRole("dialog", { name: "Move 1 file to 10. Financial/Bills?" });
    expect(sent(calls, "POST", "/api/browse/move/preview")[0].body).toEqual({ drive_ids: ["d1"], folder: "10. Financial/Bills" });
    await user.click(within(confirm).getByRole("button", { name: "Move" }));
    await waitFor(() => expect(sent(calls, "POST", "/api/browse/move")).toHaveLength(1));
    expect(sent(calls, "POST", "/api/browse/move")[0].body).toEqual({ drive_ids: ["d1"], folder: "10. Financial/Bills" });
  });
});

describe("Tags", () => {
  it("Enter and a comma add a tag, written at once with the whole list", async () => {
    const { user, calls } = setup();
    const box = await tagBox();
    await user.type(box, "bill{Enter}");
    await waitFor(() => expect(sent(calls, "PUT", "/api/files/d1/tags")).toHaveLength(1));
    expect(sent(calls, "PUT", "/api/files/d1/tags")[0].body).toEqual({ tags: ["bank", "power", "bill"] });
    expect(box).toHaveValue("");
    await user.type(box, "tax,");
    await waitFor(() => expect(sent(calls, "PUT", "/api/files/d1/tags")).toHaveLength(2));
    expect(sent(calls, "PUT", "/api/files/d1/tags")[1].body).toEqual({ tags: ["bank", "power", "bill", "tax"] });
    // no preview and no journal: nothing but the tags request goes out
    expect(calls.filter((c) => c.method === "POST")).toHaveLength(0);
  });

  it("× removes a tag; ⌫ in the empty input removes the last one", async () => {
    const { user, calls } = setup();
    await user.click(await screen.findByRole("button", { name: "Remove tag bank" }));
    await waitFor(() => expect(sent(calls, "PUT", "/api/files/d1/tags")).toHaveLength(1));
    expect(sent(calls, "PUT", "/api/files/d1/tags")[0].body).toEqual({ tags: ["power"] });
    await waitFor(() => expect(screen.queryByRole("button", { name: "Remove tag bank" })).not.toBeInTheDocument());
    const box = await tagBox();
    await user.click(box);
    await user.keyboard("{Backspace}");
    await waitFor(() => expect(sent(calls, "PUT", "/api/files/d1/tags")).toHaveLength(2));
    expect(sent(calls, "PUT", "/api/files/d1/tags")[1].body).toEqual({ tags: [] });
  });

  it("⌫ with text in the input edits the text and removes no tag", async () => {
    const { user, calls } = setup();
    const box = await tagBox();
    await user.type(box, "ab{Backspace}");
    expect(box).toHaveValue("a");
    expect(sent(calls, "PUT", "/api/files/d1/tags")).toHaveLength(0);
  });

  it("a tag the file has already (any case) and an empty entry add nothing", async () => {
    const { user, calls } = setup();
    const box = await tagBox();
    await user.type(box, "BANK{Enter}");
    await user.type(box, "   {Enter}");
    expect(sent(calls, "PUT", "/api/files/d1/tags")).toHaveLength(0);
  });

  it("a failed save is said and the chips go back", async () => {
    const { user } = setup({ "PUT /api/files/d1/tags": { status: 500, body: { error: "disk full" } } });
    await user.type(await tagBox(), "bill{Enter}");
    expect(await screen.findByRole("alert")).toHaveTextContent(/^Tags not saved: .*disk full/);
    expect(screen.queryByRole("button", { name: "Remove tag bill" })).not.toBeInTheDocument();
  });
});

describe("what cannot be edited", () => {
  it.each([
    [{ drive_id: "x", path: "a/l", is_link: true }, "Links cannot be renamed or moved"],
    [{ drive_id: "x", path: "##. Ongoing/l.pdf" }, "Files in ##. Ongoing cannot be moved: the app keeps them"],
    [{ drive_id: "x", path: "##. To Delete/l.pdf" }, "Files in ##. To Delete cannot be moved: Undo puts them back"],
    [{ drive_id: "x", path: "a/b", is_dir: true }, "Folders have no details to edit"],
    [{ drive_id: "x", path: null }, "The file is not in the index"],
  ])("Rename, Move file to…, Ask AI and the tag field are disabled, saying why, for %o", (file, why) => {
    setup({ "GET /api/files/x": { body: { ...DETAIL, record: { ...DETAIL.record, drive_id: "x" } } } }, { file });
    const rename = screen.getByRole("button", { name: "Rename" });
    expect(rename).toBeDisabled();
    expect(rename.closest("span")).toHaveAttribute("data-tip", why);
    const move = screen.getByRole("button", { name: "Move file to…" });
    expect(move).toBeDisabled();
    expect(move.closest("span")).toHaveAttribute("data-tip", why);
    expect(screen.getByRole("button", { name: "Ask AI" })).toBeDisabled();
    expect(screen.getByRole("region", { name: "Tags" })).toHaveAttribute("title", why);
    expect(screen.getByRole("textbox", { name: /^Add a tag to/ })).toBeDisabled();
  });

  it("everything waits while another change is under way", async () => {
    setup({}, { disabled: true });
    expect(screen.getByRole("button", { name: "Rename" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Move file to…" })).toBeDisabled();
  });
});

describe("Ask AI", () => {
  const answer = {
    name: "20261001_Northpower bill.pdf",
    folder: "10. Financial/Bills",
    tags: ["bank", "ai-tag"],
    tray: null,
    tray_fields: {},
    summary: "",
    confidence: {},
    reason: "r",
    rejected: {},
  };
  const ai = {
    "GET /api/ai/status": { body: STATUS_ON },
    "POST /api/ai/suggest-filing/prepare": { body: prepared() },
    "POST /api/ai/suggest-filing/run": { body: { data: answer, cost_eur: 0, cached: false } },
  };

  it("is off, saying how to turn it on, while AI is off", async () => {
    setup({ "GET /api/ai/status": { body: { ...STATUS_ON, enabled: false } } });
    await waitFor(() => expect(screen.getByRole("button", { name: "Ask AI" })).toHaveAttribute("title", expect.stringContaining("AI is off")));
    expect(screen.getByRole("button", { name: "Ask AI" })).toBeDisabled();
  });

  it("sends this file only after the sheet's Send; the answer becomes chips, nothing is applied", async () => {
    const { user, calls } = setup(ai);
    await waitFor(() => expect(screen.getByRole("button", { name: "Ask AI" })).toBeEnabled());
    await user.click(screen.getByRole("button", { name: "Ask AI" }));
    const send = await screen.findByRole("dialog", { name: "What will be sent" });
    expect(sent(calls, "POST", "/api/ai/suggest-filing/run")).toHaveLength(0);
    await user.click(within(send).getByRole("button", { name: "Send" }));
    expect(sent(calls, "POST", "/api/ai/suggest-filing/prepare")[0].body).toEqual({ params: { drive_id: "d1" } });
    expect(await screen.findByRole("group", { name: "Suggested Name: 20261001_Northpower bill.pdf (AI)" })).toBeInTheDocument();
    expect(screen.getByRole("group", { name: "Suggested Folder: 10. Financial/Bills (AI)" })).toBeInTheDocument();
    // a tag the file has already gets no chip
    expect(screen.getByRole("group", { name: "Suggested tag: ai-tag (AI)" })).toBeInTheDocument();
    expect(screen.queryByRole("group", { name: /^Suggested tag: bank/ })).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "scan⟨U+202E⟩.pdf" })).toBeInTheDocument();
    expect(sent(calls, "PUT", "/api/files/d1/tags")).toHaveLength(0);
  });

  it("Use on the name opens the rename field, Use on a tag adds it, Use on the folder previews a move", async () => {
    const op = moved("10. Financial/Bills/scan‮.pdf");
    const { user, calls } = setup({ ...ai, "POST /api/browse/move/preview": { body: [op] } });
    await waitFor(() => expect(screen.getByRole("button", { name: "Ask AI" })).toBeEnabled());
    await user.click(screen.getByRole("button", { name: "Ask AI" }));
    await user.click(within(await screen.findByRole("dialog", { name: "What will be sent" })).getByRole("button", { name: "Send" }));
    await user.click(within(await screen.findByRole("group", { name: /^Suggested tag: ai-tag/ })).getByRole("button", { name: "Use" }));
    await waitFor(() => expect(sent(calls, "PUT", "/api/files/d1/tags")).toHaveLength(1));
    expect(sent(calls, "PUT", "/api/files/d1/tags")[0].body).toEqual({ tags: ["bank", "power", "ai-tag"] });
    await user.click(within(screen.getByRole("group", { name: /^Suggested Name/ })).getByRole("button", { name: "Use" }));
    expect(await nameBox()).toHaveValue("20261001_Northpower bill");
    await user.keyboard("{Escape}");
    await user.click(within(screen.getByRole("group", { name: /^Suggested Folder/ })).getByRole("button", { name: "Use" }));
    await screen.findByRole("dialog", { name: "Move 1 file to 10. Financial/Bills?" });
    expect(sent(calls, "POST", "/api/browse/move/preview")[0].body).toEqual({ drive_ids: ["d1"], folder: "10. Financial/Bills" });
  });
});
