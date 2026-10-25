/** Starred and Important open a clicked file in Browse (its folder, the file selected and
 * previewed); an ordinary collection keeps its page and has "Show in folder" instead. */
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Collection, DirEntry } from "../api/client";
import { mockFetch, renderWithProviders } from "../test-utils";
import Browse from "./Browse";
import Collections from "./Collections";
import Starred from "./Starred";

afterEach(() => vi.unstubAllGlobals());

const DIR = "10. Financial/Banks";
const member = (over: Partial<Collection["members"][number]> = {}): Collection["members"][number] => ({
  drive_id: "f1",
  path: `${DIR}/a.pdf`,
  is_dir: false,
  missing: false,
  quarantined: false,
  is_link: false,
  group_id: null,
  marks: [],
  ...over,
});
const collection = (over: Partial<Collection>): Collection => ({
  id: 7,
  name: "Sauna",
  state: "open",
  created: 1_760_000_000,
  closed_at: null,
  publish: { ongoing: false },
  ongoing_rel: null,
  members: [member()],
  ongoing_status: null,
  summary: "",
  groups: [],
  parent_id: null,
  path: ["Sauna"],
  kind: null,
  position: 0,
  ...over,
});
const row = (name: string, id: string): DirEntry => ({
  name,
  path: `${DIR}/${name}`,
  is_dir: false,
  is_link: false,
  size: 10,
  mtime: 1,
  drive_id: id,
  marks: [],
});

function Where() {
  const location = useLocation();
  return <output data-testid="where">{location.pathname + location.search}</output>;
}

function setup(start: string, c: Collection, kind: "starred" | null) {
  const calls = mockFetch({
    "GET /api/collections": { body: [{ ...c, files: 1, open_checks: 0 }] },
    "GET /api/collections/7": { body: c },
    "GET /api/marks/collection/starred": { body: c },
    "GET /api/notes/collection/7": { body: { text: "" } },
    "GET /api/checklist/collection/7": { body: [] },
    "GET /api/browse": { body: [row("a.pdf", "f1"), row("b.pdf", "f2")] },
    "GET /api/activity": { body: [] },
    "GET /api/status": { body: { special_folders: { inbox: "##. Organize", ongoing: "##. Ongoing", important: "##. Important", quarantine: "##. To Delete" } } },
    "GET /api/files/f1/page/1.png": { body: {} },
  });
  const user = userEvent.setup();
  renderWithProviders(
    <MemoryRouter initialEntries={[start]}>
      <Routes>
        <Route path="/starred" element={<Starred today="2026-10-19" />} />
        <Route path="/collections/:id?" element={<Collections today="2026-10-19" />} />
        <Route path="/browse" element={<Browse />} />
      </Routes>
      <Where />
    </MemoryRouter>,
  );
  void kind;
  return { calls, user };
}

const STARRED = collection({ id: 7, name: "Starred", kind: "starred" });

describe("Starred", () => {
  it("a click on a file shows it in Browse: folder open, file selected, preview shown", async () => {
    const { user } = setup("/starred", STARRED, "starred");
    await user.click(await screen.findByRole("button", { name: /^a\.pdf/ }));
    expect(screen.getByTestId("where")).toHaveTextContent(`/browse?path=${encodeURIComponent(DIR).replace(/%20/g, "+")}&select=f1`);
    const preview = await screen.findByRole("region", { name: "Preview" });
    expect(await within(preview).findByText(`${DIR}/a.pdf`)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "a.pdf" }).closest("li")).toHaveAttribute("aria-current", "true");
  });

  it("Enter on the focused file does the same", async () => {
    const { user } = setup("/starred", STARRED, "starred");
    (await screen.findByRole("button", { name: /^a\.pdf/ })).focus();
    await user.keyboard("{Enter}");
    await waitFor(() => expect(screen.getByTestId("where").textContent).toContain("/browse?path="));
  });

  it("a file that is not in the index stays selected in place", async () => {
    const { user } = setup("/starred", collection({ ...STARRED, members: [member({ path: null, missing: true })] }), "starred");
    await user.click(await screen.findByRole("button", { name: /f1/ }));
    expect(screen.getByTestId("where")).toHaveTextContent("/starred");
  });
});

describe("an ordinary collection", () => {
  it("keeps its page on a click and has Show in folder in the file panel", async () => {
    const { user } = setup("/collections/7", collection({}), null);
    await user.click(await screen.findByRole("button", { name: /^a\.pdf/ }));
    expect(screen.getByTestId("where")).toHaveTextContent("/collections/7");
    const panel = screen.getByRole("complementary", { name: "Selected file" });
    await user.click(await within(panel).findByRole("button", { name: "Show in folder" }));
    expect(screen.getByTestId("where").textContent).toContain("/browse?path=");
    expect(screen.getByTestId("where").textContent).toContain("select=f1");
    expect(await screen.findByRole("button", { name: "a.pdf" })).toBeInTheDocument();
  });
});

describe("Browse ?select=", () => {
  it("a file that is no longer in the folder: the folder opens and a message says so", async () => {
    setup(`/browse?path=${encodeURIComponent(DIR)}&select=gone`, collection({}), null);
    expect(await screen.findByText(/no longer in this folder/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "a.pdf" })).toBeInTheDocument();
    await waitFor(() => expect(screen.getByTestId("where").textContent).not.toContain("select="));
  });
});
