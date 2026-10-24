/** A folder that is a member of a collection opens in place: its files and subfolders,
 * a file selectable for the side panel, "Show in Browse" on the folder. */
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Collection, DirEntry } from "../api/client";
import { mockFetch, renderWithProviders } from "../test-utils";
import Collections from "./Collections";

afterEach(() => vi.unstubAllGlobals());

const PLANS = "40. House/Sauna/Plans";
const SAUNA: Collection = {
  id: 7,
  name: "Sauna",
  state: "open",
  created: 1_760_000_000,
  closed_at: null,
  publish: { ongoing: false },
  ongoing_rel: null,
  members: [
    { drive_id: "f1", path: "40. House/Sauna/quote.pdf", is_dir: false, missing: false, quarantined: false, is_link: false, group_id: null, marks: [] },
    { drive_id: "d1", path: PLANS, is_dir: true, missing: false, quarantined: false, is_link: false, group_id: null, marks: [] },
  ],
  ongoing_status: null,
  summary: "",
  groups: [],
  parent_id: null,
  path: ["Sauna"],
  kind: null,
};
const entry = (name: string, dir: string, is_dir: boolean, drive_id: string): DirEntry => ({
  name,
  path: `${dir}/${name}`,
  is_dir,
  is_link: false,
  size: is_dir ? null : 10,
  mtime: 1,
  drive_id,
  marks: [],
});

function Where() {
  const location = useLocation();
  return <output data-testid="where">{location.pathname + location.search}</output>;
}

function setup() {
  const calls = mockFetch({
    "GET /api/collections": { body: [{ ...SAUNA, files: 2, open_checks: 0 }] },
    "GET /api/collections/7": { body: SAUNA },
    "GET /api/notes/collection/7": { body: { text: "" } },
    "GET /api/checklist/collection/7": { body: [] },
    "GET /api/browse": (call) => ({
      body: decodeURIComponent(call.url).endsWith(`path=${PLANS}/Old`)
        ? [entry("sketch.png", `${PLANS}/Old`, false, "e3")]
        : [entry("Old", PLANS, true, "e1"), entry("plan.pdf", PLANS, false, "e2")],
    }),
    "GET /api/files/e2/links": { body: { items: [], collections: [], note: "" } },
    "GET /api/files/e3/links": { body: { items: [], collections: [], note: "" } },
  });
  const user = userEvent.setup();
  renderWithProviders(
    <MemoryRouter initialEntries={["/collections/7"]}>
      <Routes>
        <Route path="/collections/:id?" element={<Collections today="2026-10-19" />} />
      </Routes>
      <Where />
    </MemoryRouter>,
  );
  return { calls, user };
}

const members = async () => within(await screen.findByRole("region", { name: "Members" }));

describe("a folder member of a collection", () => {
  it("opens in place: files and subfolders, listed when opened, subfolders opening in turn", async () => {
    const { calls, user } = setup();
    const list = await members();
    await user.click(await list.findByRole("button", { name: "Expand Plans" }));
    expect(await list.findByRole("button", { name: /^plan\.pdf/ })).toBeInTheDocument();
    expect(list.getByRole("button", { name: "Expand Old" })).toBeInTheDocument();
    expect(calls.filter((c) => c.url.startsWith("/api/browse"))).toHaveLength(1);
    await user.click(list.getByRole("button", { name: "Expand Old" }));
    expect(await list.findByRole("button", { name: /^sketch\.png/ })).toBeInTheDocument();
    await user.click(list.getByRole("button", { name: "Collapse Plans" }));
    expect(list.queryByRole("button", { name: /^plan\.pdf/ })).not.toBeInTheDocument();
  });

  it("a file inside shows in the side panel with its details", async () => {
    const { user } = setup();
    const list = await members();
    await user.click(await list.findByRole("button", { name: "Expand Plans" }));
    await user.click(await list.findByRole("button", { name: /^plan\.pdf/ }));
    const panel = screen.getByRole("complementary", { name: "Selected file" });
    expect(await within(panel).findByText("plan.pdf")).toBeInTheDocument();
    expect(within(panel).getByRole("button", { name: "Show in Finder" })).toBeInTheDocument();
    expect(await within(panel).findByRole("button", { name: "Draw a box" })).toBeInTheDocument();
    // not a member: no way to remove it from the collection
    expect(within(panel).queryByRole("button", { name: /Remove/ })).not.toBeInTheDocument();
  });

  it("→ opens and ← closes the focused folder row", async () => {
    const { user } = setup();
    const list = await members();
    const row = await list.findByRole("button", { name: /^Plans/ });
    row.focus();
    await user.keyboard("{ArrowRight}");
    expect(await list.findByRole("button", { name: /^plan\.pdf/ })).toBeInTheDocument();
    await user.keyboard("{ArrowLeft}");
    await waitFor(() => expect(list.queryByRole("button", { name: /^plan\.pdf/ })).not.toBeInTheDocument());
  });

  it("Show in Browse in the folder's menu goes to Browse at that folder", async () => {
    const { user } = setup();
    await user.click(await screen.findByRole("button", { name: "Actions for Plans" }));
    await user.click(screen.getByRole("menuitem", { name: "Show in Browse" }));
    expect(screen.getByTestId("where")).toHaveTextContent(`/browse?path=${encodeURIComponent(PLANS)}`);
  });
});
