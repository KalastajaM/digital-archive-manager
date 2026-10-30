/** Several files selected in Browse: add or remove a tag, add to, remove from or move between
 * collections, each with Undo in its toast. */
import { cleanup, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { CollectionRow, Member } from "../api/client";
import { type Call, mockFetch, renderWithProviders } from "../test-utils";
import { SelectionActions } from "./SelectionActions";

const member = (drive_id: string): Member => ({ drive_id, path: `x/${drive_id}.pdf`, is_dir: false, missing: false, quarantined: false, is_link: false, group_id: null, connected: true, marks: [] });
const coll = (id: number, name: string, parent_id: number | null, members: string[]): CollectionRow => ({
  id,
  name,
  state: "open",
  created: 1,
  closed_at: null,
  publish: { ongoing: true },
  ongoing_rel: null,
  members: members.map(member),
  ongoing_status: null,
  summary: "",
  groups: [],
  parent_id,
  path: [name],
  kind: null,
  position: id,
  files: members.length,
  open_checks: 0,
});
const LEGAL = coll(1, "Legal", null, ["a"]);
const MICHIEL = coll(2, "Michiel", 1, ["b"]);
const CAR = coll(3, "Car", null, ["b"]);
const ALL = [LEGAL, MICHIEL, CAR];
const FILES = [
  { drive_id: "a", name: "a.pdf" },
  { drive_id: "b", name: "b.pdf" },
];
const change = (c: CollectionRow) => ({ body: { collection: c, batch: null, problems: [], ongoing_status: null } });
const posts = (calls: Call[], url: string) => calls.filter((c) => c.method === "POST" && c.url === url).map((c) => c.body);

function setup(scope: CollectionRow | null = null) {
  const calls = mockFetch({
    "GET /api/tags/all": { body: { tags: [{ name: "house", files: 2, pinned: false, group_id: null }], groups: [] } },
    "GET /api/files/a": { body: { record: { drive_id: "a" }, tags: ["house"] } },
    "GET /api/files/b": { body: { record: { drive_id: "b" }, tags: ["house", "Kela"] } },
    "POST /api/tags/apply": { body: { message: "Tagged 2 files 'house 1'", undo: { drop: ["house 1"], detach: [], restore: [] } } },
    "POST /api/tags/remove-from": { body: { message: "Removed 'house' from 2 files", undo: { drop: [], detach: [], restore: [] } } },
    "POST /api/tags/undo": { body: { message: "Undone", undo: null } },
    "POST /api/collections/3/members": change(CAR),
    "POST /api/collections/3/members/remove-many": change(CAR),
    "POST /api/collections/1/members/remove-many": change(LEGAL),
    "POST /api/collections/2/members/remove-many": change(MICHIEL),
    "POST /api/collections/1/members/move": change(CAR),
    "POST /api/collections/2/members/move": change(CAR),
  });
  const onDone = vi.fn();
  renderWithProviders(<SelectionActions files={FILES} scope={scope} all={ALL} onDone={onDone} />);
  return { calls, onDone, user: userEvent.setup() };
}

const open = async (user: ReturnType<typeof userEvent.setup>, label: string) => {
  await user.click(screen.getByRole("button", { name: "Actions for 2 selected files" }));
  await user.click(await screen.findByRole("menuitem", { name: label }));
  return screen.findByRole("dialog");
};
const undo = async (user: ReturnType<typeof userEvent.setup>) => user.click(await screen.findByRole("button", { name: "Undo" }));

afterEach(cleanup);

describe("SelectionActions", () => {
  it("adds a new tag to every selected file, and Undo takes it off", async () => {
    const { calls, user } = setup();
    const sheet = await open(user, "Add tag…");
    await user.type(within(sheet).getByRole("combobox"), "house 1{Enter}");
    await waitFor(() => expect(posts(calls, "/api/tags/apply")).toEqual([{ tag: "house 1", drive_ids: ["a", "b"] }]));
    await undo(user);
    await waitFor(() => expect(posts(calls, "/api/tags/undo")).toHaveLength(1));
  });

  it("removes a tag the files carry; only those tags are offered", async () => {
    const { calls, user } = setup();
    const sheet = await open(user, "Remove tag…");
    const options = await within(sheet).findAllByRole("option");
    expect(options.map((o) => o.textContent)).toEqual(["house", "Kela"]);
    await user.click(options[0]);
    await waitFor(() => expect(posts(calls, "/api/tags/remove-from")).toEqual([{ tag: "house", drive_ids: ["a", "b"] }]));
  });

  it("adds the files to a collection, and Undo removes only the ones it added", async () => {
    const { calls, user } = setup();
    const sheet = await open(user, "Add to collection…");
    await user.click(within(sheet).getByRole("option", { name: "Car" }));
    await waitFor(() => expect(posts(calls, "/api/collections/3/members")).toEqual([{ drive_ids: ["a", "b"] }]));
    await undo(user);
    await waitFor(() => expect(posts(calls, "/api/collections/3/members/remove-many")).toEqual([{ drive_ids: ["a"] }])); // b was in Car already
  });

  it("with a collection shown, removes each file from its own collection in that tree", async () => {
    const { calls, user } = setup(LEGAL);
    const sheet = await open(user, "Remove from collection…");
    await user.click(within(sheet).getByRole("button", { name: "Remove from Legal" }));
    await waitFor(() => expect(posts(calls, "/api/collections/1/members/remove-many")).toEqual([{ drive_ids: ["a"] }]));
    expect(posts(calls, "/api/collections/2/members/remove-many")).toEqual([{ drive_ids: ["b"] }]); // b comes from Michiel
  });

  it("with a collection shown, moves the files out of it (and its children) into another", async () => {
    const { calls, user } = setup(LEGAL);
    const sheet = await open(user, "Move to collection…");
    expect(within(sheet).queryByRole("option", { name: "Legal" })).toBeNull();
    await user.click(within(sheet).getByRole("option", { name: "Car" }));
    await waitFor(() => expect(posts(calls, "/api/collections/1/members/move")).toEqual([{ to: 3, drive_ids: ["a"] }]));
    expect(posts(calls, "/api/collections/2/members/move")).toEqual([{ to: 3, drive_ids: ["b"] }]);
  });

  it("offers Move to collection only while a collection is shown", async () => {
    const { user } = setup();
    await user.click(screen.getByRole("button", { name: "Actions for 2 selected files" }));
    expect(await screen.findByRole("menuitem", { name: "Add tag…" })).toBeInTheDocument();
    expect(screen.queryByRole("menuitem", { name: "Move to collection…" })).toBeNull();
  });
});
