/** Browse's tag tree: tags by group with their counts, a filter box, a click picks a tag and
 * a Cmd-click adds one. */
import { cleanup, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ScopeState } from "../browseScope";
import { type Call, mockFetch, renderWithProviders } from "../test-utils";
import { TagTree } from "./BrowseTagTree";

type Tag = { name: string; files: number; pinned: boolean; group_id: number | null };
const tag = (name: string, files: number, group_id: number | null = null): Tag => ({ name, files, pinned: false, group_id });

const NONE: ScopeState = { collections: [], tags: [], starred: false, important: false };

function setup(reply: (q: string) => { tags: Tag[]; groups: { id: number; name: string }[] }, active: ScopeState = NONE) {
  const calls = mockFetch({
    "GET /api/tags/all": (call: Call) => ({ body: reply(new URL(call.url, "http://x").searchParams.get("query") ?? "") }),
  });
  const onPick = vi.fn();
  renderWithProviders(<TagTree active={active} onPick={onPick} />);
  return { calls, onPick, user: userEvent.setup() };
}

const HEALTH = { tags: [tag("medical", 12, 1), tag("dental", 3, 1), tag("receipt", 40)], groups: [{ id: 1, name: "Health" }] };
const items = () => screen.getAllByRole("treeitem").map((li) => (li.querySelector(".tree-row")?.textContent ?? "").trim());

afterEach(cleanup);

describe("TagTree", () => {
  it("groups the tags as the Tags screen does, with counts", async () => {
    setup(() => HEALTH);
    await screen.findByText("medical");
    expect(items()).toEqual(["Health", "dental3", "medical12", "No group", "receipt40"]);
  });

  it("a click picks, a cmd-click adds", async () => {
    const { onPick, user } = setup(() => HEALTH, { ...NONE, tags: ["medical"] });
    await user.click(await screen.findByText("medical"));
    expect(onPick).toHaveBeenLastCalledWith({ kind: "tag", name: "medical" }, false);
    expect(screen.getByText("medical").closest('[role="treeitem"]')).toHaveAttribute("aria-current", "true");
    await user.keyboard("{Meta>}");
    await user.click(screen.getByText("dental"));
    await user.keyboard("{/Meta}");
    expect(onPick).toHaveBeenLastCalledWith({ kind: "tag", name: "dental" }, true);
  });

  it("the filter box asks the server and says when nothing matches", async () => {
    const { calls, user } = setup((q) => (q ? { tags: [], groups: HEALTH.groups } : HEALTH));
    await screen.findByText("medical");
    await user.type(screen.getByRole("searchbox", { name: "Filter tags" }), "zz");
    await waitFor(() => expect(calls.some((c) => c.url.includes("query=zz"))).toBe(true));
    expect(await screen.findByText("No tag matches")).toBeInTheDocument();
    expect(screen.queryByText("Health")).not.toBeInTheDocument();
  });

  it("no tags says so", async () => {
    setup(() => ({ tags: [], groups: [] }));
    expect(await screen.findByText("No tags yet")).toBeInTheDocument();
  });

  it("a long tag name ends in an ellipsis with the full name on hover", async () => {
    const long = "a-very-long-tag-name-".repeat(6);
    setup(() => ({ tags: [tag(long, 1)], groups: [] }));
    const name = await screen.findByText(long);
    expect(name).toHaveClass("tree-name");
    expect(name).toHaveAttribute("title", long);
  });

  it("stays in the Tab order when the focused tag is filtered away", async () => {
    const { user } = setup((q) => (q ? { tags: [tag("dental", 3, 1)], groups: HEALTH.groups } : HEALTH));
    await user.click(await screen.findByText("medical"));
    expect(document.activeElement).toBe(screen.getByText("medical").closest('[role="treeitem"]'));
    await user.type(screen.getByRole("searchbox", { name: "Filter tags" }), "den");
    await waitFor(() => expect(screen.queryByText("medical")).not.toBeInTheDocument());
    expect(screen.getAllByRole("treeitem").filter((li) => li.tabIndex === 0)).toHaveLength(1);
  });
});

