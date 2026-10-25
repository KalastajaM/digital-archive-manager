/** The lock on a file: the icon in lists, the controls that go off with the reason, Unlock
 * (for now / for good), Lock, and locking again when the file is left. */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it } from "vitest";
import { forgetUnlocks, type FileDetail, type Mark } from "../api/client";
import { type Call, mockFetch, renderWithProviders } from "../test-utils";
import { FileMeta, type MetaFile } from "./FileMeta";
import { MarkIcons } from "./MarkIcons";

const PATH = "10. Financial/Banks/scan.pdf";
const REASON = "This file is locked. Unlock it to change it.";
const record = (marks: Mark[]): FileDetail["record"] => ({
  drive_id: "d1",
  path: PATH,
  name: "scan.pdf",
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
  marks,
});
const detail = (marks: Mark[]): FileDetail => ({
  record: record(marks),
  tags: ["bank"],
  link_target_id: null,
  link_target_path: null,
  link_target_inside: false,
});
const state = (over: object) => ({
  drive_id: "d1",
  locked: true,
  reason: "file",
  unlocked_now: false,
  token: null,
  expires_after_idle_seconds: null,
  ...over,
});

afterEach(forgetUnlocks);

/** A server with one file whose lock the test controls. */
function server(opts: { locked?: boolean; marks?: Mark[] } = {}) {
  const s = { locked: opts.locked ?? true, marks: opts.marks ?? [] };
  const routes = {
    "GET /api/locks": () => ({
      body: {
        files: s.locked || s.marks.includes("important") ? [{ drive_id: "d1", reason: s.marks.includes("important") ? "important" : "file" }] : [],
        folders: [],
      },
    }),
    "GET /api/files/d1": () => ({ body: detail(s.marks) }),
    "GET /api/folders": { body: ["10. Financial/Banks"] },
    "PUT /api/files/d1/tags": (call: Call) => ({ body: { tags: (call.body as { tags: string[] }).tags } }),
    "POST /api/files/d1/unlock": (call: Call) => {
      const mode = (call.body as { mode: string }).mode;
      if (mode === "for_good") {
        s.locked = false;
        return { body: state({ locked: false, reason: null }) };
      }
      return { body: state({ unlocked_now: true, token: "tok-1", expires_after_idle_seconds: 900 }) };
    },
    "POST /api/files/d1/lock": () => {
      s.locked = true;
      return { body: state({}) };
    },
    "DELETE /api/files/d1/unlock": { body: state({}) },
    "POST /api/browse/rename/preview": { status: 400, body: { error: "stop here" } },
  };
  return { s, routes };
}

function Harness({ file }: { file: MetaFile }) {
  return (
    <FileMeta file={file}>
      {(meta) => (
        <>
          {meta.header}
          {meta.tags}
        </>
      )}
    </FileMeta>
  );
}

const FILE = (marks: Mark[] = []): MetaFile => ({ drive_id: "d1", path: PATH, is_dir: false, is_link: false, marks });
const show = (file: MetaFile) =>
  renderWithProviders(
    <MemoryRouter>
      <Harness file={file} />
    </MemoryRouter>,
  );
const sent = (calls: Call[], method: string, url: string) => calls.filter((c) => c.method === method && c.url === url);

describe("the lock icon in lists", () => {
  it("shows for a locked file, for an Important one, and not for another", async () => {
    mockFetch({ "GET /api/locks": { body: { files: [{ drive_id: "a", reason: "file" }], folders: ["20. Home/Deeds"] } } });
    renderWithProviders(
      <>
        <p>
          one <MarkIcons marks={[]} driveId="a" />
        </p>
        <p>
          two <MarkIcons marks={["important"]} driveId="b" />
        </p>
        <p>
          three <MarkIcons marks={[]} driveId="c" />
        </p>
        <p>
          four <MarkIcons marks={[]} driveId="d" path="20. Home/Deeds/deed.pdf" />
        </p>
      </>,
    );
    await waitFor(() => expect(screen.getAllByRole("img", { name: "Locked" })).toHaveLength(3));
    const rows = screen.getAllByRole("img", { name: "Locked" }).map((i) => i.closest("p")?.textContent);
    expect(rows.map((t) => t?.trim().split(" ")[0])).toEqual(["one", "two", "four"]);
  });
});

describe("a locked file", () => {
  it("cannot be renamed or moved (the reason is the tooltip) but its tags still change", async () => {
    const { routes } = server();
    const calls = mockFetch(routes);
    const user = userEvent.setup();
    show(FILE());
    await waitFor(() => expect(screen.getByRole("button", { name: "Rename" })).toBeDisabled());
    expect(screen.getByRole("button", { name: "Rename" }).parentElement).toHaveAttribute("data-tip", REASON);
    const move = screen.getByRole("button", { name: "Move file to…" });
    expect(move).toBeDisabled();
    expect(move.parentElement).toHaveAttribute("data-tip", REASON);
    expect(screen.getByRole("button", { name: "Unlock" })).toBeInTheDocument();
    // tags are the app's own data: still editable
    const box = await screen.findByRole("combobox", { name: "Add a tag to scan.pdf" });
    await waitFor(() => expect(box).toBeEnabled());
    await user.type(box, "tax{Enter}");
    await waitFor(() => expect(sent(calls, "PUT", "/api/files/d1/tags")).toHaveLength(1));
  });

  it("asks For now or For good; for now unlocks until it is locked again", async () => {
    const { routes } = server();
    const calls = mockFetch(routes);
    const user = userEvent.setup();
    show(FILE());
    await user.click(await screen.findByRole("button", { name: "Unlock" }));
    expect(screen.getByRole("button", { name: "For now" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "For good" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "For now" }));
    expect(await screen.findByText("Unlocked until you leave this file")).toBeInTheDocument();
    expect(sent(calls, "POST", "/api/files/d1/unlock")[0].body).toEqual({ mode: "now" });
    expect(screen.getByRole("button", { name: "Rename" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Move file to…" })).toBeEnabled();
    // the page now sends the token with every call
    await user.click(screen.getByRole("button", { name: "Rename" }));
    await user.type(await screen.findByRole("textbox", { name: "File name" }), "x{Enter}");
    await waitFor(() => expect(sent(calls, "POST", "/api/browse/rename/preview")).toHaveLength(1));
    expect(sent(calls, "POST", "/api/browse/rename/preview")[0].headers["X-Dam-Unlock"]).toBe("tok-1");
    await user.keyboard("{Escape}");
    await user.click(await screen.findByRole("button", { name: "Lock again" }));
    await waitFor(() => expect(sent(calls, "DELETE", "/api/files/d1/unlock")).toHaveLength(1));
    expect(screen.getByRole("button", { name: "Rename" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Unlock" })).toBeInTheDocument();
    // once locked again, nothing carries the token
    await user.click(screen.getByRole("button", { name: "Unlock" }));
    expect(sent(calls, "DELETE", "/api/files/d1/unlock")[0].headers["X-Dam-Unlock"]).toBeUndefined();
  });

  it("for good removes the lock, and Lock puts it back", async () => {
    const { routes } = server();
    const calls = mockFetch(routes);
    const user = userEvent.setup();
    show(FILE());
    await user.click(await screen.findByRole("button", { name: "Unlock" }));
    await user.click(screen.getByRole("button", { name: "For good" }));
    expect(sent(calls, "POST", "/api/files/d1/unlock")[0].body).toEqual({ mode: "for_good" });
    const lock = await screen.findByRole("button", { name: "Lock" });
    expect(screen.getByRole("button", { name: "Rename" })).toBeEnabled();
    await user.click(lock);
    await waitFor(() => expect(sent(calls, "POST", "/api/files/d1/lock")).toHaveLength(1));
    expect(await screen.findByRole("button", { name: "Unlock" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Rename" })).toBeDisabled();
  });

  it("an Important file only unlocks for now, and says it locks again", async () => {
    const { routes } = server({ locked: false, marks: ["important"] });
    const calls = mockFetch(routes);
    const user = userEvent.setup();
    show(FILE(["important"]));
    const unlock = await screen.findByRole("button", { name: "Unlock" });
    expect(unlock.getAttribute("data-tip")).toMatch(
      /locks again when you leave this file/,
    );
    await user.click(unlock);
    expect(screen.queryByRole("button", { name: "For good" })).toBeNull();
    expect(await screen.findByText("Unlocked until you leave this file")).toBeInTheDocument();
    expect(sent(calls, "POST", "/api/files/d1/unlock")[0].body).toEqual({ mode: "now" });
  });

  it("locks again when the file is left", async () => {
    const { routes } = server();
    const calls = mockFetch(routes);
    const user = userEvent.setup();
    const view = show(FILE());
    await user.click(await screen.findByRole("button", { name: "Unlock" }));
    await user.click(screen.getByRole("button", { name: "For now" }));
    await screen.findByText("Unlocked until you leave this file");
    view.unmount(); // another file selected, the panel closed, another page
    await waitFor(() => expect(sent(calls, "DELETE", "/api/files/d1/unlock")).toHaveLength(1));
    // a fresh view of the same file is locked again
    render(
      <MemoryRouter>
        <p>gone</p>
      </MemoryRouter>,
    );
    const again = renderWithProviders(
      <MemoryRouter>
        <Harness file={FILE()} />
      </MemoryRouter>,
    );
    expect(await screen.findByRole("button", { name: "Unlock" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Rename" })).toBeDisabled();
    again.unmount();
  });
});
