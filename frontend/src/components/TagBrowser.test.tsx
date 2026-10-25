import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockFetch, renderWithProviders } from "../test-utils";
import { TagInput } from "./TagInput";

afterEach(() => vi.unstubAllGlobals());

const ALL = {
  tags: [
    { name: "medical", files: 3, pinned: false, group_id: null },
    { name: "kela", files: 1, pinned: false, group_id: 5 },
    { name: "tax", files: 12, pinned: true, group_id: 5 },
  ],
  groups: [{ id: 5, name: "Authorities" }],
};

function Harness() {
  const [tags, setTags] = useState<string[]>(["medical"]);
  return (
    <>
      <TagInput value={tags} onChange={setTags} label="Tags" />
      <output aria-label="kept">{JSON.stringify(tags)}</output>
    </>
  );
}

function setup() {
  const calls = mockFetch({
    "GET /api/tags/all": (call) => ({
      body: call.url.includes("query=ke") ? { ...ALL, tags: [ALL.tags[1]] } : ALL,
    }),
    "GET /api/tags": { body: [] },
  });
  renderWithProviders(<Harness />);
  return { calls, user: userEvent.setup() };
}

describe("the tag browser behind the … of the tags field", () => {
  it("shows every tag by group with its count; a tag already on the file is greyed out", async () => {
    const { user } = setup();
    await user.click(screen.getByRole("button", { name: "Browse tags…" }));
    const sheet = await screen.findByRole("dialog", { name: "Choose a tag" });
    const group = await within(sheet).findByRole("region", { name: "Authorities" });
    expect(within(group).getAllByRole("button").map((b) => b.textContent)).toEqual(["kela1 file", "tax12 files"]);
    const other = within(sheet).getByRole("region", { name: "Other tags" });
    expect(within(other).getByRole("button", { name: /medical/ })).toBeDisabled();
  });

  it("choosing a tag adds it as a chip and closes the browser", async () => {
    const { user } = setup();
    await user.click(screen.getByRole("button", { name: "Browse tags…" }));
    await user.click(await screen.findByRole("button", { name: /tax/ }));
    expect(JSON.parse(screen.getByLabelText("kept").textContent ?? "[]")).toEqual(["medical", "tax"]);
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.getByRole("button", { name: "Remove tag tax" })).toBeInTheDocument();
  });

  it("the filter narrows the list; Esc cancels without adding", async () => {
    const { calls, user } = setup();
    await user.click(screen.getByRole("button", { name: "Browse tags…" }));
    await screen.findByRole("button", { name: /tax/ });
    await user.type(screen.getByRole("searchbox", { name: "Filter tags" }), "ke");
    await screen.findByRole("button", { name: /kela/ });
    expect(calls.some((c) => c.url === "/api/tags/all?query=ke")).toBe(true);
    expect(screen.queryByRole("button", { name: /tax/ })).toBeNull();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(JSON.parse(screen.getByLabelText("kept").textContent ?? "[]")).toEqual(["medical"]);
  });
});
