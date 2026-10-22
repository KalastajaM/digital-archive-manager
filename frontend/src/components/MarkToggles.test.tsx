import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { MemoryRouter } from "react-router-dom";
import type { Mark } from "../api/client";
import { describe, expect, it } from "vitest";
import { type Call, deferred, mockFetch, renderWithProviders } from "../test-utils";
import { CollectionPicker } from "./CollectionPicker";
import { MarkIcons } from "./MarkIcons";
import { MarkToggles } from "./MarkToggles";
import { QuickLook } from "./QuickLook";

const CHANGE = {
  collection: { id: 1, name: "Ongoing", kind: "starred", members: [], groups: [] },
  batch: null,
  problems: [],
  ongoing_status: null,
};
const posts = (calls: Call[], url: string) => calls.filter((c) => c.method === "POST" && c.url === url);
const record = (marks: string[]) => ({
  record: { drive_id: "d1", path: "10. Financial/a.pdf", name: "a.pdf", ext: "pdf", marks },
  tags: [],
  link_target_id: null,
  link_target_path: null,
  link_target_inside: false,
});

describe("MarkIcons", () => {
  it("renders ★ and ! from marks, nothing without", () => {
    const { container, rerender } = render(<MarkIcons marks={["starred", "important"]} />);
    expect(screen.getByRole("img", { name: "Starred" })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Important" })).toBeInTheDocument();
    rerender(<MarkIcons marks={["important"]} />);
    expect(screen.queryByRole("img", { name: "Starred" })).toBeNull();
    rerender(<MarkIcons marks={[]} />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("MarkToggles", () => {
  it("★ calls the marks API, shows the star, and the toast offers Unstar", async () => {
    const calls = mockFetch({ "POST /api/marks/star": { body: CHANGE }, "POST /api/marks/unstar": { body: CHANGE } });
    const user = userEvent.setup();
    renderWithProviders(<MarkToggles driveId="d1" name="a‮.pdf" marks={[]} />);
    const star = screen.getByRole("button", { name: "Star" });
    expect(star).toHaveAttribute("aria-pressed", "false");
    await user.click(star);
    await waitFor(() => expect(posts(calls, "/api/marks/star")).toHaveLength(1));
    expect(posts(calls, "/api/marks/star")[0].body).toEqual({ drive_ids: ["d1"] });
    const on = await screen.findByRole("button", { name: "Remove the star" });
    expect(on).toHaveAttribute("aria-pressed", "true");
    expect(await screen.findByText("Starred a⟨U+202E⟩.pdf")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Undo" }));
    await waitFor(() => expect(posts(calls, "/api/marks/unstar")).toHaveLength(1));
    expect(await screen.findByRole("button", { name: "Star" })).toHaveAttribute("aria-pressed", "false");
  });

  it("two clicks in the same tick send one request (the inFlight guard, not the disabled state)", async () => {
    const held = deferred<{ body: unknown }>();
    const calls = mockFetch({ "POST /api/marks/important": () => held.promise });
    renderWithProviders(<MarkToggles driveId="d1" name="a.pdf" marks={["starred"]} />);
    const bang = screen.getByRole("button", { name: "Mark Important" });
    act(() => {
      // both clicks land before React re-renders: the button is still enabled for the second
      bang.click();
      expect(bang).toBeEnabled();
      bang.click();
    });
    await waitFor(() => expect(posts(calls, "/api/marks/important")).toHaveLength(1));
    held.resolve({ body: CHANGE });
    expect(await screen.findByRole("button", { name: "Unmark Important" })).toBeInTheDocument();
    expect(posts(calls, "/api/marks/important")).toHaveLength(1);
    expect(posts(calls, "/api/marks/important")[0].body).toEqual({ drive_ids: ["d1"] });
    expect(screen.getByRole("button", { name: "Remove the star" })).toBeInTheDocument();
  });

  it("! marks Important (ungrouped) and the toast's Unmark unmarks it again", async () => {
    const calls = mockFetch({ "POST /api/marks/important": { body: CHANGE }, "POST /api/marks/unimportant": { body: CHANGE } });
    const user = userEvent.setup();
    renderWithProviders(<MarkToggles driveId="d1" name="a.pdf" marks={[]} />);
    await user.click(screen.getByRole("button", { name: "Mark Important" }));
    await user.click(await screen.findByRole("button", { name: "Undo" }));
    await waitFor(() => expect(posts(calls, "/api/marks/unimportant")).toHaveLength(1));
    expect(await screen.findByRole("button", { name: "Mark Important" })).toHaveAttribute("aria-pressed", "false");
  });

  it("the toast's opposite action builds on the marks shown then, not at the click", async () => {
    mockFetch({ "POST /api/marks/star": { body: CHANGE }, "POST /api/marks/unstar": { body: CHANGE } });
    const user = userEvent.setup();
    function Harness() {
      const [marks, setMarks] = useState<Mark[]>([]);
      return (
        <>
          <MarkToggles driveId="d1" name="a.pdf" marks={marks} />
          <button type="button" onClick={() => setMarks(["starred", "important"])}>
            refresh
          </button>
        </>
      );
    }
    renderWithProviders(<Harness />);
    await user.click(screen.getByRole("button", { name: "Star" }));
    const undo = await screen.findByRole("button", { name: "Undo" });
    // meanwhile the caller's data caught up, and the file was marked Important elsewhere
    await user.click(screen.getByRole("button", { name: "refresh" }));
    await user.click(undo);
    expect(await screen.findByRole("button", { name: "Star" })).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByRole("button", { name: "Unmark Important" })).toHaveAttribute("aria-pressed", "true");
  });

  it("without marks from the caller it reads them from the file's record", async () => {
    mockFetch({ "GET /api/files/d1": { body: record(["important"]) } });
    renderWithProviders(<MarkToggles driveId="d1" name="a.pdf" />);
    expect(await screen.findByRole("button", { name: "Unmark Important" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Star" })).toBeInTheDocument();
  });

  it("a refusal is a toast with the server's reason", async () => {
    mockFetch({ "POST /api/marks/star": { status: 404, body: { error: "file x" } } });
    const user = userEvent.setup();
    renderWithProviders(<MarkToggles driveId="d1" name="a.pdf" marks={[]} />);
    await user.click(screen.getByRole("button", { name: "Star" }));
    expect(await screen.findByText(/Could not star a.pdf: file x/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Star" })).toHaveAttribute("aria-pressed", "false");
  });

  it("in Quick Look the toggles are there and say what happened on its status line", async () => {
    mockFetch({
      "GET /api/files/d1": { body: record([]) },
      "GET /api/files/d1/links": { body: { items: [], collections: [], note: "" } },
      "POST /api/marks/star": { body: CHANGE },
    });
    const user = userEvent.setup();
    renderWithProviders(
      <MemoryRouter>
        <QuickLook files={[{ drive_id: "d1", name: "a.pdf", path: "10. Financial/a.pdf", ext: "txt" }]} index={0} onIndex={() => {}} onClose={() => {}} />
      </MemoryRouter>,
    );
    const ql = screen.getByRole("dialog", { name: "Quick Look: a.pdf" });
    await user.click(await within(ql).findByRole("button", { name: "Star" }));
    expect(await within(ql).findByText("Starred a.pdf")).toBeInTheDocument();
    expect(within(ql).getByRole("button", { name: "Remove the star" })).toBeInTheDocument();
  });
});

describe("the built-ins in pickers", () => {
  const ROWS = [
    { id: 1, name: "Ongoing", kind: "starred", state: "open", path: ["Ongoing"], parent_id: null, members: [] },
    { id: 2, name: "Important", kind: "important", state: "open", path: ["Important"], parent_id: null, members: [] },
    { id: 3, name: "Sauna", kind: null, state: "open", path: ["Sauna"], parent_id: null, members: [] },
  ];

  it("an ordinary picker never offers them, even if a list carried them", async () => {
    mockFetch({ "GET /api/collections": { body: ROWS } });
    const user = userEvent.setup();
    renderWithProviders(<CollectionPicker value={[]} onChange={() => {}} text="" onTextChange={() => {}} single label="Collection" />);
    await user.click(screen.getByRole("combobox", { name: "Collection" }));
    await user.keyboard("{ArrowDown}");
    const options = await screen.findAllByRole("option");
    expect(options.map((o) => o.textContent)).toEqual(["Sauna"]);
    expect(screen.queryByText("Marked")).toBeNull();
  });

  it("the Browse filter (marked) lists them under Marked and picks them by name", async () => {
    mockFetch({ "GET /api/collections": { body: ROWS } });
    const user = userEvent.setup();
    const chosen: string[][] = [];
    renderWithProviders(
      <CollectionPicker value={[]} onChange={(n) => chosen.push(n)} text="" onTextChange={() => {}} single marked label="Collection" />,
    );
    await user.click(screen.getByRole("combobox", { name: "Collection" }));
    await user.keyboard("{ArrowDown}");
    await waitFor(() => expect(screen.getAllByRole("option").map((o) => o.textContent)).toEqual(["Sauna", "★ Starred", "! Important"]));
    // the heading sits right before the first built-in, and is not an option
    const texts = [...screen.getByRole("listbox").children].map((li) => li.textContent);
    expect(texts).toEqual(["Sauna", "Marked", "★ Starred", "! Important"]);
    expect(screen.getByText("Marked")).toHaveAttribute("role", "presentation");
    await user.keyboard("{ArrowDown}{ArrowDown}{ArrowDown}{Enter}");
    expect(chosen).toEqual([["Important"]]);
  });
});
