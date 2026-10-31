/** Renewed… on a Renew item: the new date, optionally the new file with the old one's move
 * to Expired previewed, Unlock and move for a locked old file, and Undo. */
import { cleanup, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ItemFile } from "../api/client";
import { deferred, mockFetch, renderWithProviders } from "../test-utils";
import { RenewForm } from "./RenewForm";

const OLD: ItemFile = {
  drive_id: "old",
  path: "10. Financial/Banks/passport-old.pdf",
  ext: "pdf",
  state: "ok",
  in_inbox: false,
  connected: true,
  marks: [],
};
const ITEM = { id: 7, title: "Passport Michiel" };
const HIT = { drive_id: "new", path: "10. Financial/Banks/passport-new.pdf", name: "passport-new.pdf", snippet: "", rank: 1, marks: [] };
const MOVE_OPS = [
  { kind: "mkdir", src: null, dst: "10. Financial/Banks/Expired", drive_id: null, note: null },
  { kind: "move", src: OLD.path, dst: "10. Financial/Banks/Expired/passport-old.pdf", drive_id: "old", note: null },
];
const RENEWED = { item: { id: 7 }, batch_id: "b1", undo: "renewal", skipped: null };

function setup(routes: Parameters<typeof mockFetch>[0] = {}, old: ItemFile = OLD, item = ITEM) {
  const calls = mockFetch({
    "GET /api/locks": { body: { files: [], folders: [] } },
    "GET /api/search": { body: [HIT] },
    "POST /api/items/7/renew/preview": { body: { ops: MOVE_OPS, skipped: null, locked: [] } },
    "POST /api/items/7/renew": { body: RENEWED },
    "POST /api/renewals/undo": { body: { id: 7 } },
    ...routes,
  });
  const onClose = vi.fn();
  renderWithProviders(<RenewForm item={item} files={[old]} label="Renewed" onClose={onClose} />);
  return { calls, onClose, user: userEvent.setup() };
}

const sent = (calls: ReturnType<typeof mockFetch>, method: string, path: string) =>
  calls.filter((c) => c.method === method && c.url.split("?")[0] === path);

async function pickNewFile(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole("button", { name: "Attach the new file (optional)" }));
  await user.type(screen.getByLabelText("Find a file"), "passport");
  await user.click(await screen.findByRole("button", { name: /Add passport-new\.pdf/ }));
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("RenewForm", () => {
  it("renew without a file posts expires only and shows the toast", async () => {
    const { calls, onClose, user } = setup();
    const date = screen.getByLabelText("New expiry date");
    expect(date).toHaveFocus();
    expect(date).toBeRequired();
    await user.type(date, "2036-10-31");
    await user.click(screen.getByRole("button", { name: "Renewed" }));
    await waitFor(() => expect(sent(calls, "POST", "/api/items/7/renew")).toHaveLength(1));
    expect(sent(calls, "POST", "/api/items/7/renew")[0].body).toEqual({ expires: "2036-10-31" });
    expect(sent(calls, "POST", "/api/items/7/renew/preview")).toHaveLength(0);
    expect(onClose).toHaveBeenCalled();
    const toast = (await screen.findByText("Renewed: Passport Michiel")).closest(".toast") as HTMLElement;
    // a renewal that moved no file is undone by its own call
    await user.click(within(toast).getByRole("button", { name: "Undo" }));
    await waitFor(() => expect(sent(calls, "POST", "/api/renewals/undo")).toHaveLength(1));
    expect(sent(calls, "POST", "/api/renewals/undo")[0].body).toEqual({ batch_id: "b1" });
  });

  it("a picked file shows the move preview with the Expired folder", async () => {
    const { calls, user } = setup({
      "POST /api/items/7/renew": { body: { ...RENEWED, undo: "activity" } },
      "POST /api/activity/b1/undo/preview": { body: [] },
    });
    await user.type(screen.getByLabelText("New expiry date"), "2036-10-31");
    await pickNewFile(user);
    expect(screen.getByText("passport-new.pdf")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Preview…" }));
    const plan = await screen.findByRole("region", { name: "Planned changes" });
    expect(plan).toHaveTextContent("10. Financial/Banks/Expired");
    expect(sent(calls, "POST", "/api/items/7/renew/preview")[0].body).toEqual({ expires: "2036-10-31", drive_id: "new" });
    await user.click(screen.getByRole("button", { name: "Renewed" }));
    await waitFor(() => expect(sent(calls, "POST", "/api/items/7/renew")).toHaveLength(1));
    expect(sent(calls, "POST", "/api/items/7/renew")[0].body).toEqual({ expires: "2036-10-31", drive_id: "new" });
    // a renewal that moved the old file is undone from Activity, behind its confirm
    const toast = (await screen.findByText("Renewed: Passport Michiel")).closest(".toast") as HTMLElement;
    await user.click(within(toast).getByRole("button", { name: "Undo" }));
    expect(await screen.findByRole("dialog", { name: "Undo these changes?" })).toBeInTheDocument();
    expect(sent(calls, "POST", "/api/renewals/undo")).toHaveLength(0);
  });

  const LOCKED_OLD = { ...OLD, marks: ["important" as const] };
  const LOCKED_ROUTES = {
    // locked without the grant; under it, the move
    "POST /api/items/7/renew/preview": (call: { headers: Record<string, string> }) =>
      call.headers["X-Dam-Unlock"] === "tok-1"
        ? { body: { ops: MOVE_OPS, skipped: null, locked: [] } }
        : { body: { ops: [], skipped: null, locked: [{ drive_id: "old", name: "passport-old.pdf" }] } },
    "POST /api/files/old/unlock": { body: { token: "tok-1" } },
    "DELETE /api/files/old/unlock": { status: 204, body: null },
    "POST /api/items/7/renew": { body: { ...RENEWED, undo: "activity" } },
  };

  async function previewLocked(user: ReturnType<typeof userEvent.setup>) {
    await user.type(screen.getByLabelText("New expiry date"), "2036-10-31");
    await pickNewFile(user);
    await user.click(screen.getByRole("button", { name: "Preview…" }));
    expect(await screen.findByText("passport-old.pdf is locked.")).toBeInTheDocument();
    // without the deliberate click there is no way to apply
    expect(screen.queryByRole("button", { name: "Renewed" })).toBeNull();
    await user.click(screen.getByRole("button", { name: "Unlock and move" }));
  }

  it("Unlock and move shows the move under the grant, and Renewed applies it, then locks again", async () => {
    const { calls, user } = setup(LOCKED_ROUTES, LOCKED_OLD);
    await previewLocked(user);
    const plan = await screen.findByRole("region", { name: "Planned changes" });
    expect(plan).toHaveTextContent("10. Financial/Banks/Expired");
    expect(sent(calls, "POST", "/api/files/old/unlock")[0].body).toEqual({ mode: "now" });
    const previews = sent(calls, "POST", "/api/items/7/renew/preview");
    expect(previews).toHaveLength(2);
    expect(previews[1].headers["X-Dam-Unlock"]).toBe("tok-1");
    expect(screen.queryByText("passport-old.pdf is locked.")).toBeNull();
    // shown, not applied: nothing is posted until the confirm
    expect(sent(calls, "POST", "/api/items/7/renew")).toHaveLength(0);
    expect(sent(calls, "DELETE", "/api/files/old/unlock")).toHaveLength(0);
    await user.click(screen.getByRole("button", { name: "Renewed" }));
    await waitFor(() => expect(sent(calls, "DELETE", "/api/files/old/unlock")).toHaveLength(1));
    const renew = sent(calls, "POST", "/api/items/7/renew");
    expect(renew).toHaveLength(1);
    expect(renew[0].headers["X-Dam-Unlock"]).toBe("tok-1");
    const order = calls.map((c) => `${c.method} ${c.url}`);
    expect(order.indexOf("POST /api/files/old/unlock")).toBeLessThan(order.indexOf("POST /api/items/7/renew"));
    expect(order.indexOf("POST /api/items/7/renew")).toBeLessThan(order.indexOf("DELETE /api/files/old/unlock"));
    expect(await screen.findByText("Renewed: Passport Michiel")).toBeInTheDocument();
  });

  it("Cancel after Unlock and move locks the file again and renews nothing", async () => {
    const { calls, onClose, user } = setup(LOCKED_ROUTES, LOCKED_OLD);
    await previewLocked(user);
    await screen.findByRole("region", { name: "Planned changes" });
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onClose).toHaveBeenCalled();
    await waitFor(() => expect(sent(calls, "DELETE", "/api/files/old/unlock")).toHaveLength(1));
    expect(sent(calls, "POST", "/api/items/7/renew")).toHaveLength(0);
  });

  it("a failed renewal after Unlock and move locks the file again", async () => {
    const { calls, user } = setup(
      { ...LOCKED_ROUTES, "POST /api/items/7/renew": { status: 400, body: { error: "Refused." } } },
      LOCKED_OLD,
    );
    await previewLocked(user);
    await screen.findByRole("region", { name: "Planned changes" });
    await user.click(screen.getByRole("button", { name: "Renewed" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Refused.");
    await waitFor(() => expect(sent(calls, "DELETE", "/api/files/old/unlock")).toHaveLength(1));
    // the grant is gone, so the move is previewed again before it can apply
    expect(screen.getByRole("button", { name: "Preview…" })).toBeInTheDocument();
  });

  it("skipped reason is shown and Renew still applies", async () => {
    const { calls, user } = setup({
      "POST /api/items/7/renew/preview": {
        body: { ops: [], skipped: "The old file is no longer in the archive", locked: [] },
      },
      "POST /api/items/7/renew": { body: { ...RENEWED, skipped: "The old file is no longer in the archive" } },
    });
    await user.type(screen.getByLabelText("New expiry date"), "2036-10-31");
    await pickNewFile(user);
    await user.click(screen.getByRole("button", { name: "Preview…" }));
    expect(await screen.findByText("The old file is no longer in the archive, so it is not moved.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Renewed" }));
    await waitFor(() => expect(sent(calls, "POST", "/api/items/7/renew")).toHaveLength(1));
    expect(await screen.findByText(/Renewed: Passport Michiel/)).toBeInTheDocument();
  });

  it("a changed date or file asks for a new preview", async () => {
    const { user } = setup();
    await user.type(screen.getByLabelText("New expiry date"), "2036-10-31");
    await pickNewFile(user);
    await user.click(screen.getByRole("button", { name: "Preview…" }));
    await screen.findByRole("region", { name: "Planned changes" });
    await user.clear(screen.getByLabelText("New expiry date"));
    await user.type(screen.getByLabelText("New expiry date"), "2036-11-30");
    expect(screen.queryByRole("region", { name: "Planned changes" })).toBeNull();
    expect(screen.getByRole("button", { name: "Preview…" })).toBeInTheDocument();
  });

  it("a preview that returns after the date changed is dropped", async () => {
    const slow = deferred<{ body: unknown }>();
    const { user } = setup({ "POST /api/items/7/renew/preview": () => slow.promise });
    await user.type(screen.getByLabelText("New expiry date"), "2036-10-31");
    await pickNewFile(user);
    await user.click(screen.getByRole("button", { name: "Preview…" }));
    await user.clear(screen.getByLabelText("New expiry date"));
    await user.type(screen.getByLabelText("New expiry date"), "2036-11-30");
    slow.resolve({ body: { ops: MOVE_OPS, skipped: null, locked: [] } });
    await waitFor(() => expect(screen.getByRole("button", { name: "Preview…" })).toBeEnabled());
    expect(screen.queryByRole("region", { name: "Planned changes" })).toBeNull();
    expect(screen.getByRole("button", { name: "Preview…" })).toBeInTheDocument();
  });

  it("the success toast shows hidden characters in the title", async () => {
    const { user } = setup({}, OLD, { id: 7, title: "Passport\u202Efdp" });
    await user.type(screen.getByLabelText("New expiry date"), "2036-10-31");
    await user.click(screen.getByRole("button", { name: "Renewed" }));
    expect(await screen.findByText("Renewed: Passport⟨U+202E⟩fdp")).toBeInTheDocument();
  });

  it("shows the server's refusal and stays open", async () => {
    const { onClose, user } = setup({
      "POST /api/items/7/renew": { status: 400, body: { error: "This file is locked. Unlock it to change it." } },
    });
    await user.type(screen.getByLabelText("New expiry date"), "2036-10-31");
    await user.click(screen.getByRole("button", { name: "Renewed" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("This file is locked.");
    expect(onClose).not.toHaveBeenCalled();
  });
});
