/** The folder browser (stars spec §9): a "…" button on every folder field opens a sheet
 * with the archive's folder tree, to walk instead of typing. */
import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { type FormEvent, useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { deferred, mockFetch, renderWithProviders } from "../test-utils";
import { buildTree, MAX_ROWS } from "./FolderBrowser";
import { FolderPicker } from "./FolderPicker";
import { Sheet } from "./ui/Sheet";

const SPECIAL = { inbox: "##. Organize", ongoing: "##. Ongoing", important: "##. Important", quarantine: "##. To Delete" };
const FOLDERS = [
  "10. Financial",
  "10. Financial/Banks",
  "10. Financial/Bills",
  "13. Taxes",
  "13. Taxes/2025",
  "20. Odd‮name",
  "##. Important",
  "##. Important/Houses",
  "##. Ongoing",
  "##. Ongoing/Project",
];

function Field({ initial, onChange }: { initial: string; onChange?: (v: string) => void }) {
  const [value, setValue] = useState(initial);
  return (
    <FolderPicker
      label="Folder"
      value={value}
      onChange={(v) => {
        setValue(v);
        onChange?.(v);
      }}
    />
  );
}

/** The stacked case: the field sits in a form in a sheet, like Move to…. */
function InSheet({ initial, spies }: { initial: string; spies: { close: () => void; submit: () => void; key: (k: string) => void } }) {
  return (
    <Sheet open title="Move 1 file to…" onClose={spies.close} onKeyDown={(e) => spies.key(e.key)}>
      <form
        onSubmit={(e: FormEvent) => {
          e.preventDefault();
          spies.submit();
        }}
      >
        <Field initial={initial} />
      </form>
    </Sheet>
  );
}

function setup(initial = "", folders: string[] = FOLDERS, stacked = false) {
  mockFetch({
    "GET /api/folders": { body: folders },
    "GET /api/status": { body: { inbox_count: 0, special_folders: SPECIAL } },
  });
  const spies = { close: vi.fn(), submit: vi.fn(), key: vi.fn(), change: vi.fn() };
  renderWithProviders(stacked ? <InSheet initial={initial} spies={spies} /> : <Field initial={initial} onChange={spies.change} />);
  return { user: userEvent.setup(), spies };
}

const field = () => screen.getByRole("combobox", { name: "Folder" }) as HTMLInputElement;
async function openBrowser(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole("button", { name: "Browse folders…" }));
  const sheet = await screen.findByRole("dialog", { name: "Choose a folder" });
  const tree = within(sheet).getByRole("tree", { name: "Folders" });
  await within(tree).findByRole("treeitem", { name: /^10\. Financial/ });
  return { sheet, tree };
}
const item = (tree: HTMLElement, name: RegExp) => within(tree).getByRole("treeitem", { name });
const names = (tree: HTMLElement) =>
  within(tree)
    .queryAllByRole("treeitem")
    .map((li) => li.querySelector(".folder-tree-name")!.textContent);

describe("buildTree", () => {
  it("nests paths under their parents, adding a missing parent", () => {
    const tree = buildTree(["a", "a/b", "c/d"]);
    expect(tree.roots).toEqual(["a", "c"]);
    expect(tree.children.get("a")).toEqual(["a/b"]);
    expect(tree.children.get("c")).toEqual(["c/d"]);
  });
});

describe("the folder browser", () => {
  it("opens from the field's … button with the top level folded", async () => {
    const { user } = setup();
    const { tree } = await openBrowser(user);
    expect(names(tree)).toEqual(["10. Financial", "13. Taxes", "20. Odd⟨U+202E⟩name", "##. Important", "##. Ongoing", "##. To Delete"]);
    expect(item(tree, /^10\. Financial/)).toHaveAttribute("aria-expanded", "false");
    expect(item(tree, /^20\. Odd/)).not.toHaveAttribute("aria-expanded");
  });

  it("pre-selects the field's folder, its parents open", async () => {
    const { user } = setup("10. Financial/Bills");
    const { tree } = await openBrowser(user);
    expect(item(tree, /^10\. Financial/)).toHaveAttribute("aria-expanded", "true");
    expect(item(tree, /^Bills/)).toHaveAttribute("aria-selected", "true");
    expect(tree).toHaveAttribute("aria-activedescendant", item(tree, /^Bills/).id);
    expect(tree).toHaveFocus();
  });

  it("a typed folder that does not exist yet selects its nearest existing parent", async () => {
    const { user } = setup("13. Taxes/2026");
    const { tree } = await openBrowser(user);
    expect(item(tree, /^13\. Taxes/)).toHaveAttribute("aria-selected", "true");
  });

  it("the filter narrows the tree to the matching folders and their parents", async () => {
    const { user, spies } = setup();
    const { sheet, tree } = await openBrowser(user);
    await user.type(within(sheet).getByRole("searchbox", { name: "Filter folders" }), "bill");
    expect(names(tree)).toEqual(["10. Financial", "Bills"]);
    // the first match is selected; ↑ ↓ and Enter work from the filter too
    expect(item(tree, /^Bills/)).toHaveAttribute("aria-selected", "true");
    await user.keyboard("{ArrowUp}");
    expect(item(tree, /^10\. Financial/)).toHaveAttribute("aria-selected", "true");
    await user.keyboard("{ArrowDown}{Enter}");
    expect(field()).toHaveValue("10. Financial/Bills");
    expect(spies.change).toHaveBeenLastCalledWith("10. Financial/Bills");
  });

  it("a filter selects its first match that can be chosen", async () => {
    const { user } = setup("##. Ongoing");
    const { sheet, tree } = await openBrowser(user);
    await user.type(within(sheet).getByRole("searchbox", { name: "Filter folders" }), "ongoing");
    // "##. Ongoing" and "##. Ongoing/Project" match but cannot be chosen: nothing is
    // selected for the filter, the row stays where it was
    expect(item(tree, /^##\. Ongoing/)).toHaveAttribute("aria-selected", "true");
    await user.clear(within(sheet).getByRole("searchbox", { name: "Filter folders" }));
    await user.type(within(sheet).getByRole("searchbox", { name: "Filter folders" }), "o");
    expect(item(tree, /^20\. Odd/)).toHaveAttribute("aria-selected", "true");
    expect(names(tree)).toEqual(["20. Odd⟨U+202E⟩name", "##. Important", "Houses", "##. Ongoing", "Project", "##. To Delete"]);
  });

  it("a filter matching nothing says so", async () => {
    const { user } = setup();
    const { sheet } = await openBrowser(user);
    await user.type(within(sheet).getByRole("searchbox", { name: "Filter folders" }), "zzz");
    expect(within(sheet).getByText("No folder matches “zzz”.")).toBeInTheDocument();
  });

  it("↑ ↓ → ← walk the tree and Enter chooses; focus goes back to the field", async () => {
    const { user } = setup();
    const { sheet, tree } = await openBrowser(user);
    expect(item(tree, /^10\. Financial/)).toHaveAttribute("aria-selected", "true");
    await user.keyboard("{ArrowRight}"); // opens
    expect(item(tree, /^10\. Financial/)).toHaveAttribute("aria-expanded", "true");
    await user.keyboard("{ArrowRight}"); // into the first child
    expect(item(tree, /^Banks/)).toHaveAttribute("aria-selected", "true");
    await user.keyboard("{ArrowDown}");
    expect(item(tree, /^Bills/)).toHaveAttribute("aria-selected", "true");
    await user.keyboard("{ArrowLeft}"); // to the parent
    expect(item(tree, /^10\. Financial/)).toHaveAttribute("aria-selected", "true");
    await user.keyboard("{ArrowLeft}"); // closes it
    expect(item(tree, /^10\. Financial/)).toHaveAttribute("aria-expanded", "false");
    await user.keyboard("{ArrowDown}{ArrowRight}{ArrowRight}{Enter}");
    expect(field()).toHaveValue("13. Taxes/2025");
    expect(sheet).not.toBeInTheDocument();
    await waitFor(() => expect(field()).toHaveFocus());
  });

  it("a click selects, the chevron opens, Choose sets the field", async () => {
    const { user } = setup();
    const { sheet, tree } = await openBrowser(user);
    await user.click(within(item(tree, /^13\. Taxes/)).getByRole("button", { name: "Open 13. Taxes" }));
    await user.click(within(tree).getByText("2025"));
    await user.click(within(sheet).getByRole("button", { name: "Choose" }));
    expect(field()).toHaveValue("13. Taxes/2025");
  });

  it("a double click chooses", async () => {
    const { user } = setup();
    const { tree } = await openBrowser(user);
    await user.dblClick(within(tree).getByText("13. Taxes"));
    expect(field()).toHaveValue("13. Taxes");
  });

  it("##. Ongoing and ##. To Delete are dimmed and cannot be chosen; ##. Important can", async () => {
    const { user, spies } = setup();
    const { sheet, tree } = await openBrowser(user);
    for (const special of [/^##\. Ongoing/, /^##\. To Delete/]) {
      expect(item(tree, special)).toHaveAttribute("aria-disabled", "true");
      expect(item(tree, special)).toHaveClass("folder-tree-dimmed");
    }
    expect(item(tree, /^##\. Important/)).not.toHaveAttribute("aria-disabled");
    await user.click(within(tree).getByText("##. Ongoing"));
    expect(within(sheet).getByRole("button", { name: "Choose" })).toBeDisabled();
    await user.keyboard("{Enter}");
    expect(within(sheet).getByRole("status")).toHaveTextContent("Files can't be filed into ##. Ongoing.");
    // its subfolders too
    await user.keyboard("{ArrowRight}{ArrowRight}{Enter}");
    expect(item(tree, /^Project/)).toHaveAttribute("aria-disabled", "true");
    expect(sheet).toBeInTheDocument();
    expect(spies.change).not.toHaveBeenCalled();
    // ##. Important is a destination like any folder
    await user.dblClick(within(tree).getByText("##. Important"));
    expect(field()).toHaveValue("##. Important");
  });

  it("a convert flow refuses ##. Important and the inbox too (the field's refuse prop), with the reason", async () => {
    mockFetch({
      "GET /api/folders": { body: [...FOLDERS, "##. Organize"] },
      "GET /api/status": { body: { inbox_count: 0, special_folders: SPECIAL } },
    });
    const change = vi.fn();
    renderWithProviders(<FolderPicker label="Folder" value="" onChange={change} refuse={["important", "inbox"]} />);
    const user = userEvent.setup();
    const { sheet, tree } = await openBrowser(user);
    await user.click(within(tree).getByRole("button", { name: "Open ##. Important" }));
    for (const special of [/^##\. Important/, /^Houses/, /^##\. Organize/, /^##\. Ongoing/, /^##\. To Delete/]) {
      expect(item(tree, special)).toHaveAttribute("aria-disabled", "true");
      expect(item(tree, special)).toHaveClass("folder-tree-dimmed");
    }
    expect(item(tree, /^##\. Organize/)).toHaveAccessibleName("##. Organize, Inbox");
    await user.dblClick(within(tree).getByText("##. Important"));
    expect(within(sheet).getByRole("status")).toHaveTextContent("Files can't be filed into ##. Important.");
    await user.dblClick(within(tree).getByText("##. Organize"));
    expect(within(sheet).getByRole("status")).toHaveTextContent("Files can't be filed into ##. Organize.");
    expect(within(sheet).getByRole("button", { name: "Choose" })).toBeDisabled();
    expect(change).not.toHaveBeenCalled();
  });

  it("shows ##. Ongoing dimmed even when /api/folders leaves it out, like the quarantine", async () => {
    const { user } = setup("", FOLDERS.filter((f) => !f.startsWith("##. Ongoing")));
    const { tree } = await openBrowser(user);
    expect(item(tree, /^##\. Ongoing/)).toHaveAttribute("aria-disabled", "true");
    expect(item(tree, /^##\. To Delete/)).toHaveAttribute("aria-disabled", "true");
  });

  it("Choose waits for the special folders (/api/status): nothing can be chosen before they are known", async () => {
    const status = deferred<{ body: unknown }>();
    mockFetch({ "GET /api/folders": { body: FOLDERS }, "GET /api/status": () => status.promise });
    const change = vi.fn();
    renderWithProviders(<Field initial="" onChange={change} />);
    const user = userEvent.setup();
    const { sheet, tree } = await openBrowser(user);
    await user.click(within(tree).getByText("##. Ongoing"));
    expect(within(sheet).getByRole("button", { name: "Choose" })).toBeDisabled();
    await user.keyboard("{Enter}");
    await user.dblClick(within(tree).getByText("##. Ongoing"));
    expect(change).not.toHaveBeenCalled();
    expect(sheet).toBeInTheDocument();
    await act(async () => status.resolve({ body: { inbox_count: 0, special_folders: SPECIAL } }));
    await waitFor(() => expect(item(tree, /^##\. Ongoing/)).toHaveAttribute("aria-disabled", "true"));
    await user.click(within(tree).getByText("13. Taxes"));
    expect(within(sheet).getByRole("button", { name: "Choose" })).toBeEnabled();
    await user.keyboard("{Enter}");
    expect(change).toHaveBeenCalledWith("13. Taxes");
  });

  it("a row whose children are all out of view (the cut) has no chevron, and → stays on it", async () => {
    const tops = Array.from({ length: MAX_ROWS - 1 }, (_, i) => `x${String(i).padStart(4, "0")}`);
    const { user } = setup("", [...tops, "x9999", "x9999/child"]);
    await user.click(screen.getByRole("button", { name: "Browse folders…" }));
    const sheet = await screen.findByRole("dialog", { name: "Choose a folder" });
    await within(sheet).findByRole("treeitem", { name: "x0000" });
    fireEvent.change(within(sheet).getByRole("searchbox", { name: "Filter folders" }), { target: { value: "x" } });
    const tree = within(sheet).getByRole("tree", { name: "Folders" });
    const rows = within(tree).getAllByRole("treeitem");
    expect(rows).toHaveLength(MAX_ROWS);
    const last = rows[MAX_ROWS - 1];
    expect(last).toHaveAccessibleName("x9999");
    expect(last).not.toHaveAttribute("aria-expanded");
    expect(last.querySelector("button.folder-tree-chevron")).toBeNull();
    await user.click(last);
    await user.keyboard("{ArrowRight}");
    expect(tree).toHaveAttribute("aria-activedescendant", last.id);
  });

  it("Esc cancels without changing the field", async () => {
    const { user, spies } = setup("10. Financial");
    const { sheet } = await openBrowser(user);
    await user.keyboard("{ArrowDown}{Escape}");
    expect(sheet).not.toBeInTheDocument();
    expect(field()).toHaveValue("10. Financial");
    expect(spies.change).not.toHaveBeenCalled();
    await waitFor(() => expect(field()).toHaveFocus());
  });

  it("over another sheet: keys stay in the browser, Esc closes only the browser", async () => {
    const { user, spies } = setup("10. Financial", FOLDERS, true);
    const outer = screen.getByRole("dialog", { name: "Move 1 file to…" });
    const { sheet } = await openBrowser(user);
    await user.keyboard("{ArrowRight}{ArrowLeft}{ArrowDown}{ArrowUp}");
    await user.type(within(sheet).getByRole("searchbox", { name: "Filter folders" }), "zzz{Enter}");
    await user.keyboard("{Escape}");
    expect(sheet).not.toBeInTheDocument();
    expect(outer).toBeInTheDocument();
    expect(spies.close).not.toHaveBeenCalled();
    expect(spies.submit).not.toHaveBeenCalled();
    expect(spies.key).not.toHaveBeenCalled();
    await waitFor(() => expect(field()).toHaveFocus());
    expect(field()).toHaveValue("10. Financial");
  });

  it("Enter choosing in the stacked case does not submit the form underneath", async () => {
    const { user, spies } = setup("", FOLDERS, true);
    await openBrowser(user);
    await user.keyboard("{Enter}");
    expect(field()).toHaveValue("10. Financial");
    expect(spies.submit).not.toHaveBeenCalled();
    expect(spies.key).not.toHaveBeenCalled();
    expect(screen.getByRole("dialog", { name: "Move 1 file to…" })).toBeInTheDocument();
  });

  it("a huge filter result is cut, with a hint to type more", async () => {
    const many = Array.from({ length: MAX_ROWS + 20 }, (_, i) => `30. Many/f${String(i).padStart(4, "0")}`);
    const { user } = setup("", ["30. Many", ...many]);
    await user.click(screen.getByRole("button", { name: "Browse folders…" }));
    const sheet = await screen.findByRole("dialog", { name: "Choose a folder" });
    await within(sheet).findByRole("treeitem", { name: "30. Many" });
    fireEvent.change(within(sheet).getByRole("searchbox", { name: "Filter folders" }), { target: { value: "f" } });
    const tree = within(sheet).getByRole("tree", { name: "Folders" });
    expect(within(tree).getAllByRole("treeitem")).toHaveLength(MAX_ROWS);
    expect(within(sheet).getByText(`Showing the first ${MAX_ROWS} folders; type more to narrow it down.`)).toBeInTheDocument();
  });

  it("the field's suggestions show hidden characters", async () => {
    const { user } = setup();
    await act(async () => field().focus());
    await user.keyboard("{ArrowDown}");
    const list = await screen.findByRole("listbox", { name: "Folder suggestions" });
    expect(within(list).getByRole("option", { name: "20. Odd⟨U+202E⟩name" })).toBeInTheDocument();
  });
});
