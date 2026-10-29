/** Browse's file panel in the New look, in its other contexts: a file in To Delete, a file in
 * the inbox, a selection of several, and Classic (which has none of the icon rows). */
import { cleanup, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import type { DirEntry } from "../api/client";
import { mockFetch, renderWithProviders } from "../test-utils";
import Browse from "./Browse";

const entry = (name: string, id: string, path: string): DirEntry => ({
  name,
  path,
  is_dir: false,
  is_link: false,
  size: 10,
  mtime: 1,
  drive_id: id,
  connected: true,
  marks: [],
  open_items: [],
});
const STATUS = { special_folders: { inbox: "##. Organize", ongoing: "##. Ongoing", important: "##. Important", quarantine: "##. To Delete" } };

function setup(folder: string, files: DirEntry[]) {
  const links = Object.fromEntries(files.map((f) => [`GET /api/files/${f.drive_id}/links`, { body: { items: [], collections: [], note: "" } }]));
  const notes = Object.fromEntries(files.map((f) => [`GET /api/notes/file/${f.drive_id}`, { body: { text: "" } }]));
  mockFetch({
    "GET /api/browse": { body: files },
    "GET /api/collections": { body: [] },
    "GET /api/activity": { body: [] },
    "GET /api/status": { body: STATUS },
    "GET /api/trays": { body: { trays: [] } },
    ...links,
    ...notes,
  });
  renderWithProviders(
    <MemoryRouter initialEntries={[`/browse?path=${encodeURIComponent(folder)}`]}>
      <Routes>
        <Route path="/browse" element={<Browse />} />
      </Routes>
    </MemoryRouter>,
  );
  return userEvent.setup();
}
const labels = (group: HTMLElement) => within(group).getAllByRole("button").map((b) => b.getAttribute("aria-label"));

beforeEach(() => {
  localStorage.clear();
  document.documentElement.dataset.style = "new";
});
afterEach(() => {
  cleanup();
  delete document.documentElement.dataset.style;
});

describe("Browse's file panel, other contexts (New)", () => {
  it("a file in To Delete: Restore instead of the bin's work, no relatives", async () => {
    const user = setup("##. To Delete", [entry("old.pdf", "f9", "##. To Delete/old.pdf")]);
    await user.click(await screen.findByText("old.pdf"));
    const details = await screen.findByRole("region", { name: "Preview" });
    const filing = await within(details).findByRole("group", { name: "File it" });
    expect(within(filing).getByRole("button", { name: "Restore from To Delete" })).toBeInTheDocument();
    expect(within(filing).getByRole("button", { name: "Move to To Delete" })).toBeDisabled();
    expect(within(filing).getByRole("button", { name: "Star" })).toBeDisabled();
    expect(within(details).queryByRole("button", { name: "Relatives" })).toBeNull();
  });

  it("a file in the inbox: Back to inbox is there but says why it cannot run", async () => {
    const user = setup("##. Organize", [entry("new.pdf", "f1", "##. Organize/new.pdf")]);
    await user.click(await screen.findByText("new.pdf"));
    const details = await screen.findByRole("region", { name: "Preview" });
    const filing = await within(details).findByRole("group", { name: "File it" });
    const back = within(filing).getByRole("button", { name: "Back to inbox" });
    expect(back).toBeDisabled();
    expect(back.parentElement).toHaveAttribute("data-tip", expect.stringMatching(/inbox/i));
  });

  it("several files: the summary with the rows that apply to many, no look row", async () => {
    const user = setup("10. Financial", [entry("a.pdf", "f1", "10. Financial/a.pdf"), entry("b.pdf", "f2", "10. Financial/b.pdf")]);
    await screen.findByText("a.pdf");
    await user.click(screen.getByRole("checkbox", { name: "Select a.pdf" }));
    await user.click(screen.getByRole("checkbox", { name: "Select b.pdf" }));
    const details = await screen.findByRole("region", { name: "Preview" });
    expect(await within(details).findByRole("heading", { name: "2 files selected" })).toBeInTheDocument();
    expect(within(details).queryByRole("group", { name: "Look at it" })).toBeNull();
    expect(labels(within(details).getByRole("group", { name: "File it" }))).toEqual([
      "From…",
      "For…",
      "Put in tray",
      "Add to collection",
      "Star",
      "Mark Important",
      "Move to…",
      "Back to inbox",
      "Move 2 to To Delete",
    ]);
  });

  it("Classic keeps the old panel: no icon rows", async () => {
    delete document.documentElement.dataset.style;
    const user = setup("10. Financial", [entry("a.pdf", "f1", "10. Financial/a.pdf")]);
    await user.click(await screen.findByText("a.pdf"));
    await screen.findByRole("heading", { name: "a.pdf" });
    expect(document.querySelector(".file-actions-icons")).toBeNull();
    expect(document.querySelector(".file-skeleton")).toBeNull();
  });
});
