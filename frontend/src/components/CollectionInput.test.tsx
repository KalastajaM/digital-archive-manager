import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockFetch, renderWithProviders } from "../test-utils";
import { CollectionInput, CollectionNamesInput } from "./CollectionInput";

afterEach(() => vi.unstubAllGlobals());

const row = (id: number, name: string, path: string[], parent_id: number | null, extra = {}) => ({
  id,
  name,
  state: "open",
  created: 1,
  closed_at: null,
  publish: { ongoing: false },
  ongoing_rel: null,
  members: [],
  ongoing_status: null,
  summary: "",
  groups: [],
  parent_id,
  path,
  kind: null,
  files: 0,
  open_checks: 0,
  ...extra,
});
const COLLECTIONS = [
  row(1, "Houses", ["Houses"], null),
  row(2, "Sauna", ["Houses", "Sauna"], 1),
  row(3, "Car", ["Car"], null),
  row(9, "★ Ongoing", ["★ Ongoing"], null, { kind: "starred" }),
  row(10, "Old", ["Old"], null, { state: "closed" }),
];

/** The names-only field (Inbox, rules) with its value shown, so a test sees what is kept. */
function Names({ start = [] as string[] }) {
  const [value, setValue] = useState(start);
  const [text, setText] = useState("");
  return (
    <>
      <CollectionNamesInput value={value} onChange={setValue} text={text} onTextChange={setText} />
      <output aria-label="kept">{JSON.stringify(value)}</output>
    </>
  );
}

function setup(ui = <Names />) {
  const calls = mockFetch({ "GET /api/collections": { body: COLLECTIONS } });
  const view = renderWithProviders(<MemoryRouter>{ui}</MemoryRouter>);
  return { calls, user: userEvent.setup(), ...view };
}
const kept = () => JSON.parse(screen.getByLabelText("kept").textContent ?? "[]") as string[];
const input = () => screen.getByRole("combobox", { name: "Also add to collection" });

describe("the collections field", () => {
  it("lists the open collections that match what is typed, with their path, without built-ins and closed ones", async () => {
    const { user } = setup();
    await user.type(input(), "sau");
    const list = await screen.findByRole("listbox", { name: "Collections" });
    expect(within(list).getAllByRole("option").map((o) => o.textContent)).toEqual([
      "Houses › Sauna",
      'Create collection "sau"',
    ]);
    await user.clear(input());
    await user.type(input(), "ong");
    expect(screen.queryByRole("option", { name: /Ongoing/ })).toBeNull();
    await user.clear(input());
    await user.type(input(), "old");
    expect(screen.queryByRole("option", { name: "Old" })).toBeNull();
  });

  it("a click adds the collection as a chip; × removes it again", async () => {
    const { user } = setup();
    await user.type(input(), "car");
    await user.click(await screen.findByRole("option", { name: "Car" }));
    expect(kept()).toEqual(["Car"]);
    expect(input()).toHaveValue("");
    // already chosen: no longer offered
    await user.type(input(), "car");
    expect(screen.queryByRole("option", { name: "Car" })).toBeNull();
    await user.clear(input());
    await user.click(screen.getByRole("button", { name: "Remove Car" }));
    expect(kept()).toEqual([]);
  });

  it("a name that is no collection is offered as Create collection and kept as a chip", async () => {
    const { calls, user } = setup();
    await user.type(input(), "Garden shed");
    await user.click(await screen.findByRole("option", { name: 'Create collection "Garden shed"' }));
    expect(kept()).toEqual(["Garden shed"]);
    // nothing is created here: the caller does that when it applies the name
    expect(calls.filter((c) => c.method === "POST")).toHaveLength(0);
  });

  it("an exact name is not offered as new", async () => {
    const { user } = setup();
    await user.type(input(), "sauna");
    await screen.findByRole("option", { name: "Houses › Sauna" });
    expect(screen.queryByRole("option", { name: /Create/ })).toBeNull();
  });

  it("keys: ↓ and Enter choose, Enter alone adds the exact name, ⌫ removes the last chip, Esc closes the list", async () => {
    const { user } = setup();
    await user.type(input(), "ca");
    await screen.findByRole("option", { name: "Car" });
    await user.keyboard("{ArrowDown}{Enter}");
    expect(kept()).toEqual(["Car"]);
    await user.type(input(), "SAUNA{Enter}");
    expect(kept()).toEqual(["Car", "Sauna"]);
    await user.type(input(), "ho");
    expect(screen.getByRole("listbox", { name: "Collections" })).toBeInTheDocument();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("listbox")).toBeNull();
    expect(input()).toHaveValue("ho"); // Esc only closed the list
    await user.clear(input());
    await user.keyboard("{Backspace}");
    expect(kept()).toEqual(["Car"]);
  });

  it("a name longer than the limit is refused with the reason", async () => {
    const { user } = setup();
    await user.click(input());
    await user.paste("x".repeat(121));
    await user.keyboard("{Enter}");
    expect(await screen.findByRole("alert")).toHaveTextContent("A collection name is at most 120 characters.");
    expect(kept()).toEqual([]);
  });

  it("… opens the collection tree; choosing there adds a chip", async () => {
    const { user } = setup();
    await user.click(screen.getByRole("button", { name: "Browse collections…" }));
    const sheet = await screen.findByRole("dialog", { name: "Choose a collection" });
    const tree = within(sheet).getByRole("tree", { name: "Collections" });
    await within(tree).findByRole("treeitem", { name: "Car" });
    await user.click(within(tree).getByRole("treeitem", { name: "Car" }));
    await user.click(within(sheet).getByRole("button", { name: "Choose" }));
    expect(kept()).toEqual(["Car"]);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("a refusal thrown by the caller is shown under the field and keeps the text", async () => {
    const { user } = setup(
      <CollectionInput
        label="Add"
        value={[]}
        onAdd={() => Promise.reject(new Error("a collection named ‮Car exists"))}
        onRemove={() => {}}
      />,
    );
    await user.type(screen.getByRole("combobox", { name: "Add" }), "Car{Enter}");
    expect(await screen.findByRole("alert")).toHaveTextContent("a collection named ⟨U+202E⟩Car exists");
    expect(screen.getByRole("combobox", { name: "Add" })).toHaveValue("Car");
  });

  it("chips that are not removable have no ×; others are links", async () => {
    const onRemove = vi.fn();
    const { user } = setup(
      <CollectionInput
        label="Add"
        value={[
          { key: "1", name: "Houses", to: "/collections/1" },
          { key: "10", name: "Old", to: "/collections/10?state=closed", suffix: " (closed)", removable: false },
        ]}
        onAdd={() => {}}
        onRemove={onRemove}
      />,
    );
    expect(screen.getByRole("link", { name: "Old (closed)" })).toHaveAttribute("href", "/collections/10?state=closed");
    expect(screen.getAllByRole("button").map((b) => b.getAttribute("aria-label"))).toEqual(["Remove Houses", "Browse collections…"]);
    // ⌫ takes out the last chip that can go
    await user.click(screen.getByRole("combobox", { name: "Add" }));
    await user.keyboard("{Backspace}");
    await waitFor(() => expect(onRemove).toHaveBeenCalledTimes(1));
    expect(onRemove.mock.calls[0][0]).toMatchObject({ key: "1" });
  });
});
