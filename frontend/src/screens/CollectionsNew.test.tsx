/** A collection in the New look: the "File details" button that opens the side panel over the
 * list when the page is narrow (with the file's actions on top of it), and Show folder and
 * Export in the ... menu. Classic renders none of it. */
import { cleanup, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import type { Collection } from "../api/client";
import { mockFetch, renderWithProviders } from "../test-utils";
import Collections from "./Collections";

const SAUNA: Collection = {
  id: 7,
  name: "Sauna",
  state: "open",
  created: 1_760_000_000,
  closed_at: null,
  publish: { ongoing: false },
  ongoing_rel: null,
  members: [
    { drive_id: "f1", path: "40. House/Sauna/quote.pdf", is_dir: false, missing: false, quarantined: false, is_link: false, group_id: null, connected: true, marks: [] },
  ],
  ongoing_status: null,
  summary: "",
  groups: [],
  parent_id: null,
  path: ["Sauna"],
  kind: null,
  position: 0,
};

function setup() {
  mockFetch({
    "GET /api/collections": { body: [{ ...SAUNA, files: 1, open_checks: 0 }] },
    "GET /api/collections/7": { body: SAUNA },
    "GET /api/notes/collection/7": { body: { text: "" } },
    "GET /api/checklist/collection/7": { body: [] },
    "GET /api/files/f1/links": { body: { items: [], collections: [], note: "" } },
  });
  const user = userEvent.setup();
  renderWithProviders(
    <MemoryRouter initialEntries={["/collections/7"]}>
      <Routes>
        <Route path="/collections/:id?" element={<Collections today="2026-10-19" />} />
      </Routes>
    </MemoryRouter>,
  );
  return { user };
}

beforeEach(() => localStorage.clear());
afterEach(() => {
  cleanup();
  delete document.documentElement.dataset.style;
});

describe("a collection in New", () => {
  it("opens the file details over the list from a button, with the file's actions on top, and closes them again", async () => {
    document.documentElement.dataset.style = "new";
    const { user } = setup();
    const details = await screen.findByRole("button", { name: "File details" });
    expect(details).toHaveAttribute("aria-expanded", "false");
    const cols = document.querySelector(".collection-cols") as HTMLElement;
    expect(cols.dataset.details).toBeUndefined();
    expect(document.querySelector(".inspector-bar")).toBeNull();
    await user.click(details);
    expect(cols.dataset.details).toBe("open");
    expect(details).toHaveAttribute("aria-expanded", "true");
    expect(document.querySelector(".inspector-bar")).not.toBeNull();
    await user.click(document.querySelector(".details-scrim") as HTMLElement);
    expect(cols.dataset.details).toBeUndefined();
    expect(document.querySelector(".inspector-bar")).toBeNull();
  });

  it("puts Show folder and Export in the ... menu, and marks the two buttons that fold away", async () => {
    document.documentElement.dataset.style = "new";
    const { user } = setup();
    await screen.findByRole("button", { name: "File details" });
    expect(document.querySelectorAll(".collection-toolbar .hdr-wide")).toHaveLength(2);
    await user.click(screen.getByRole("button", { name: "More actions" }));
    expect(await screen.findByRole("menuitem", { name: "Show folder" })).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: "Export…" })).toBeInTheDocument();
  });

  it("renders none of it in Classic", async () => {
    setup();
    await screen.findByRole("button", { name: "More actions" });
    expect(screen.queryByRole("button", { name: "File details" })).not.toBeInTheDocument();
    expect(document.querySelector(".hdr-wide")).toBeNull();
  });
});
