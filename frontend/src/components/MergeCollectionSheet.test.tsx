/** Merge into…: pick the collection to merge into, read what happens (and that it cannot be
 * undone), then merge. */
import { cleanup, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { CollectionRow } from "../api/client";
import { mockFetch, renderWithProviders } from "../test-utils";
import { MergeCollectionSheet } from "./MergeCollectionSheet";

const coll = (id: number, name: string, parent_id: number | null = null, state: "open" | "closed" = "open"): CollectionRow => ({
  id,
  name,
  state,
  created: 1,
  closed_at: null,
  publish: { ongoing: true },
  ongoing_rel: null,
  members: [],
  ongoing_status: null,
  summary: "",
  groups: [],
  parent_id,
  path: [name],
  kind: null,
  position: id,
  files: 0,
  open_checks: 0,
});
const OLD = coll(1, "Old house");
const ALL = [OLD, coll(2, "Garden", 1), coll(3, "House"), coll(4, "Shut", null, "closed")];

function setup(problems: string[] = [], all = ALL) {
  const calls = mockFetch({
    "POST /api/collections/1/merge/preview": { body: { problems } },
    "POST /api/collections/1/merge": { body: { collection: ALL[2], batch: null, problems: [], ongoing_status: null } },
  });
  const onDone = vi.fn();
  renderWithProviders(<MergeCollectionSheet c={OLD} all={all} onDone={onDone} onCancel={() => {}} />);
  return { calls, onDone, user: userEvent.setup() };
}

afterEach(cleanup);

describe("MergeCollectionSheet", () => {
  it("offers the open collections outside it, says it cannot be undone, then merges", async () => {
    const { calls, onDone, user } = setup();
    const sheet = await screen.findByRole("dialog", { name: "Merge Old house into…" });
    expect(within(sheet).getAllByRole("option").map((o) => o.textContent)).toEqual(["House"]); // not itself, its own, or a closed one
    await user.click(within(sheet).getByRole("option", { name: "House" }));
    expect(await within(sheet).findByText(/cannot be undone/)).toBeInTheDocument();
    expect(within(sheet).getByText(/A snapshot is taken first/)).toBeInTheDocument();
    await user.click(within(sheet).getByRole("button", { name: "Merge" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.url === "/api/collections/1/merge")).toBe(true));
    expect(onDone).toHaveBeenCalledWith(expect.objectContaining({ id: 3, name: "House" }));
  });

  it("says what happens in ##. Ongoing by whether the target is in it", async () => {
    const { user } = setup();
    let sheet = await screen.findByRole("dialog");
    await user.click(within(sheet).getByRole("option", { name: "House" }));
    expect(await within(sheet).findByText(/its links move into House's folder/)).toBeInTheDocument();
    cleanup();
    const hidden = { ...coll(3, "House"), publish: { ongoing: false } };
    const second = setup([], [OLD, coll(2, "Garden", 1), hidden]);
    sheet = await screen.findByRole("dialog");
    await second.user.click(within(sheet).getByRole("option", { name: "House" }));
    expect(await within(sheet).findByText(/House is not in ##\. Ongoing, so the links of Old house there come down/)).toBeInTheDocument();
    expect(within(sheet).queryByText(/move into House's folder/)).toBeNull();
  });

  it("says why it cannot merge, and offers no Merge button", async () => {
    const { user } = setup(["The note would be 12 characters too long: shorten one first"]);
    const sheet = await screen.findByRole("dialog");
    await user.click(within(sheet).getByRole("option", { name: "House" }));
    expect(await within(sheet).findByText(/12 characters too long/)).toBeInTheDocument();
    expect(within(sheet).queryByRole("button", { name: "Merge" })).toBeNull();
  });
});
