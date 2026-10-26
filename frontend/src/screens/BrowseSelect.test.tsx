/** Browse: the select-all checkbox, ⌘A, the "N selected" count and the batch ★ / !. */
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it } from "vitest";
import type { DirEntry } from "../api/client";
import { type Call, mockFetch, renderWithProviders } from "../test-utils";
import Browse from "./Browse";

const PATH = "10. Financial/Banks";
const entry = (name: string, id: string, marks: DirEntry["marks"] = [], is_dir = false): DirEntry => ({
  name,
  path: `${PATH}/${name}`,
  is_dir,
  is_link: false,
  size: 10,
  mtime: 1,
  drive_id: id,
  connected: true,
  marks,
});
const CHANGE = { collection: { id: 1, name: "Ongoing", kind: "starred", members: [], groups: [] }, batch: null, problems: [], ongoing_status: null };
const posts = (calls: Call[], url: string) => calls.filter((c) => c.method === "POST" && c.url === url);

function setup(rows: DirEntry[], extra: Parameters<typeof mockFetch>[0] = {}) {
  const calls = mockFetch({
    "GET /api/browse": { body: rows },
    "GET /api/activity": { body: [] },
    "GET /api/status": { body: { special_folders: { inbox: "##. Organize", ongoing: "##. Ongoing", important: "##. Important", quarantine: "##. To Delete" } } },
    ...extra,
  });
  const user = userEvent.setup();
  renderWithProviders(
    <MemoryRouter initialEntries={[`/browse?path=${encodeURIComponent(PATH)}`]}>
      <Routes>
        <Route path="/browse" element={<Browse />} />
      </Routes>
    </MemoryRouter>,
  );
  return { calls, user };
}

const FILES = [entry("a.pdf", "f1"), entry("b.pdf", "f2")];
const allBox = () => screen.getByRole("checkbox", { name: "Select all files" }) as HTMLInputElement;

describe("Select all", () => {
  it("the header checkbox checks every file, is mixed for some, and clears; the toolbar counts them", async () => {
    const { user } = setup([entry("sub", "d1", [], true), ...FILES]);
    await screen.findByText("a.pdf");
    expect(allBox()).not.toBeChecked();
    await user.click(screen.getByRole("checkbox", { name: "Select a.pdf" }));
    expect(allBox()).not.toBeChecked();
    expect(allBox().indeterminate).toBe(true);
    expect(screen.getByText("1 selected")).toBeInTheDocument();
    await user.click(allBox()); // mixed → all
    expect(screen.getByRole("checkbox", { name: "Select b.pdf" })).toBeChecked();
    expect(allBox()).toBeChecked();
    expect(screen.getByText("2 selected")).toBeInTheDocument(); // the folder is not counted
    await user.click(allBox()); // all → none
    expect(screen.queryByText(/^\d+ selected$/)).not.toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "Select a.pdf" })).not.toBeChecked();
  });

  it("⌘A checks all files, again clears them", async () => {
    const { user } = setup(FILES);
    await screen.findByText("a.pdf");
    await user.keyboard("{Meta>}a{/Meta}");
    expect(allBox()).toBeChecked();
    expect(screen.getByText("2 selected")).toBeInTheDocument();
    await user.keyboard("{Meta>}a{/Meta}");
    expect(screen.queryByText(/^\d+ selected$/)).not.toBeInTheDocument();
  });

  it("⌘A in the search box is the text field's own select all", async () => {
    const { user } = setup(FILES, { "GET /api/search": { body: [] } });
    await screen.findByText("a.pdf");
    await user.type(screen.getByRole("searchbox", { name: "Search" }), "x");
    await user.keyboard("{Meta>}a{/Meta}");
    expect(screen.queryByText(/^\d+ selected$/)).not.toBeInTheDocument();
  });
});

describe("Star and Important for the checked files", () => {
  it("Star marks the checked files in one request when not all are starred", async () => {
    const { calls, user } = setup([entry("a.pdf", "f1", ["starred"]), entry("b.pdf", "f2")], {
      "POST /api/marks/star": { body: CHANGE },
    });
    await screen.findByText("a.pdf");
    await user.click(allBox());
    await user.click(screen.getByRole("button", { name: "Star" }));
    await waitFor(() => expect(posts(calls, "/api/marks/star")).toHaveLength(1));
    expect(posts(calls, "/api/marks/star")[0].body).toEqual({ drive_ids: ["f1", "f2"] });
    expect(await screen.findByText("Starred 2 files")).toBeInTheDocument();
    expect(posts(calls, "/api/marks/unstar")).toHaveLength(0);
  });

  it("with every checked file starred the button unstars them, and the toast undoes it", async () => {
    const { calls, user } = setup([entry("a.pdf", "f1", ["starred"]), entry("b.pdf", "f2", ["starred"])], {
      "POST /api/marks/unstar": { body: CHANGE },
      "POST /api/marks/star": { body: CHANGE },
    });
    await screen.findByText("a.pdf");
    await user.click(allBox());
    await user.click(screen.getByRole("button", { name: "Remove the star" }));
    await waitFor(() => expect(posts(calls, "/api/marks/unstar")).toHaveLength(1));
    expect(posts(calls, "/api/marks/unstar")[0].body).toEqual({ drive_ids: ["f1", "f2"] });
    await user.click(await screen.findByRole("button", { name: "Undo" }));
    await waitFor(() => expect(posts(calls, "/api/marks/star")).toHaveLength(1));
    expect(posts(calls, "/api/marks/star")[0].body).toEqual({ drive_ids: ["f1", "f2"] });
  });

  it("Mark Important marks the checked files", async () => {
    const { calls, user } = setup(FILES, { "POST /api/marks/important": { body: CHANGE } });
    await screen.findByText("a.pdf");
    await user.click(screen.getByRole("checkbox", { name: "Select a.pdf" }));
    await user.click(screen.getByRole("checkbox", { name: "Select b.pdf" }));
    await user.click(screen.getByRole("button", { name: "Mark Important" }));
    await waitFor(() => expect(posts(calls, "/api/marks/important")).toHaveLength(1));
    expect(posts(calls, "/api/marks/important")[0].body).toEqual({ drive_ids: ["f1", "f2"] });
  });

  it("are in the header for one file too (not in the preview's toolbar), off with nothing selected", async () => {
    const { user } = setup(FILES);
    await screen.findByText("a.pdf");
    const header = () => screen.getByRole("toolbar", { name: "Browse file actions" });
    expect(within(header()).getByRole("button", { name: "Star" })).toBeDisabled();
    await user.click(screen.getByRole("checkbox", { name: "Select a.pdf" }));
    expect(within(header()).getByRole("button", { name: "Star" })).toBeEnabled();
    expect(within(header()).getByRole("button", { name: "Mark Important" })).toBeEnabled();
    await user.click(screen.getByRole("checkbox", { name: "Select b.pdf" }));
    expect(within(header()).getByRole("button", { name: "Star" })).toBeEnabled();
    expect(within(header()).getByRole("button", { name: "Mark Important" })).toBeEnabled();
  });
});

describe("The header's file actions", () => {
  const bar = () => within(screen.getByRole("toolbar", { name: "Browse file actions" }));
  const names = () => bar().getAllByRole("button").map((b) => b.getAttribute("aria-label"));

  it("are one group in the shared order, over the file pane; the preview's toolbar keeps only viewing tools", async () => {
    const { user } = setup(FILES);
    await screen.findByText("a.pdf");
    await user.click(screen.getByRole("checkbox", { name: "Select a.pdf" }));
    expect(names()).toEqual([
      "Put in tray",
      "Back to inbox",
      "Move to…",
      "From…",
      "For…",
      "Ask AI",
      "Star",
      "Mark Important",
      "Move to To Delete",
    ]);
    const preview = screen.getByRole("region", { name: "Preview" });
    for (const name of ["Star", "Mark Important", "Ask AI", "Put in tray", "Back to inbox"]) {
      expect(within(preview).queryByRole("button", { name })).toBeNull();
    }
  });

  it("with several files checked Ask AI is off and says to pick one", async () => {
    const { user } = setup(FILES);
    await screen.findByText("a.pdf");
    await user.click(screen.getByRole("checkbox", { name: "Select a.pdf" }));
    await user.click(screen.getByRole("checkbox", { name: "Select b.pdf" }));
    const ask = bar().getByRole("button", { name: "Ask AI" });
    expect(ask).toBeDisabled();
    expect(ask.parentElement).toHaveAttribute("data-tip", "Select one file to ask AI");
  });
});

describe("From and For for the checked files", () => {
  const PEOPLE = { people: [{ name: "Tiina", match: ["Tiina Visser"] }], address_zone: [0, 0, 1, 1], default_address_zone: [0, 0, 1, 1] };

  it("From… sets the sender of every checked file in one request", async () => {
    const { calls, user } = setup(FILES, {
      "GET /api/senders": { body: [] },
      "PUT /api/assignments": { body: [] },
    });
    await screen.findByText("a.pdf");
    expect(screen.getByRole("button", { name: "From…" })).toBeDisabled();
    await user.click(allBox());
    await user.click(screen.getByRole("button", { name: "From…" }));
    const sheet = await screen.findByRole("dialog", { name: "From (2 documents)" });
    await user.type(within(sheet).getByLabelText("Sender"), "Pohjola");
    await user.click(within(sheet).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(calls.filter((c) => c.method === "PUT")).toHaveLength(1));
    expect(calls.find((c) => c.method === "PUT")?.body).toEqual({ drive_ids: ["f1", "f2"], sender: "Pohjola" });
  });

  it("For… sets the person of the checked file", async () => {
    const { calls, user } = setup(FILES, {
      "GET /api/settings/people": { body: PEOPLE },
      "PUT /api/assignments": { body: [] },
    });
    await screen.findByText("a.pdf");
    await user.click(screen.getByRole("checkbox", { name: "Select b.pdf" }));
    await user.click(screen.getByRole("button", { name: "For…" }));
    const sheet = await screen.findByRole("dialog", { name: "For" });
    await user.click(await within(sheet).findByRole("button", { name: "Tiina" }));
    await user.click(within(sheet).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(calls.filter((c) => c.method === "PUT")).toHaveLength(1));
    expect(calls.find((c) => c.method === "PUT")?.body).toEqual({ drive_ids: ["f2"], person: "Tiina" });
  });
});

describe("Draw a box in the Browse preview", () => {
  it("is offered on the previewed PDF", async () => {
    const { user } = setup([{ ...entry("a.pdf", "f1") }]);
    await user.click(await screen.findByText("a.pdf"));
    expect(await screen.findByRole("button", { name: "Draw a box" })).toBeInTheDocument();
  });
});
