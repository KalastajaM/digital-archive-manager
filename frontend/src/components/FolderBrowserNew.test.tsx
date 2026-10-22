/** "New folder" in the folder browser: made on disk at once (POST /api/folders), then selected. */
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { mockFetch, renderWithProviders, type Call } from "../test-utils";
import { FolderPicker } from "./FolderPicker";

const SPECIAL = { inbox: "##. Organize", ongoing: "##. Ongoing", important: "##. Important", quarantine: "##. To Delete" };
const FOLDERS = ["10. Financial", "10. Financial/Banks", "13. Taxes", "13. Taxes/2025", "##. Ongoing"];

function Field({ initial, onChange }: { initial: string; onChange: (v: string) => void }) {
  const [value, setValue] = useState(initial);
  return (
    <FolderPicker
      label="Folder"
      value={value}
      onChange={(v) => {
        setValue(v);
        onChange(v);
      }}
    />
  );
}

const MADE = {
  batch_id: "b1",
  dry_run: false,
  done: [{ kind: "mkdir", src: null, dst: "13. Taxes/Receipts", drive_id: null, note: null }],
  failed: null,
  error: null,
  index_error: null,
};

async function setup(initial: string, folderReply: { status?: number; body: unknown } = { body: MADE }) {
  const calls = mockFetch({
    "GET /api/folders": { body: FOLDERS },
    "GET /api/status": { body: { inbox_count: 0, special_folders: SPECIAL } },
    "POST /api/folders/new": folderReply,
  });
  const change = vi.fn();
  renderWithProviders(<Field initial={initial} onChange={change} />);
  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: "Browse folders…" }));
  const sheet = await screen.findByRole("dialog", { name: "Choose a folder" });
  const tree = within(sheet).getByRole("tree", { name: "Folders" });
  await within(tree).findByRole("treeitem", { name: /^10\. Financial/ });
  return { user, change, sheet, tree, calls };
}

const newButton = (sheet: HTMLElement) => within(sheet).getByRole("button", { name: "New folder" });

describe("New folder in the folder browser", () => {
  it("names a folder under the selected one; Enter makes it on disk and selects it", async () => {
    const { user, change, sheet, tree, calls } = await setup("13. Taxes");
    await user.click(newButton(sheet));
    const input = within(tree).getByRole("textbox", { name: "New folder name" });
    expect(input).toHaveFocus();
    expect(within(tree).getByRole("treeitem", { name: /^13\. Taxes/ })).toHaveAttribute("aria-expanded", "true");
    await user.type(input, "Receipts{Enter}");
    const row = await within(tree).findByRole("treeitem", { name: "Receipts" });
    expect(within(tree).queryByRole("textbox")).not.toBeInTheDocument();
    expect(row).toHaveAttribute("aria-selected", "true");
    const posts = calls.filter((c: Call) => c.method === "POST" && c.url === "/api/folders/new");
    expect(posts.map((c) => c.body)).toEqual([{ parent: "13. Taxes", name: "Receipts" }]);
    // no "created when you confirm": it exists; Activity holds the Undo
    expect(within(sheet).getByRole("status")).toHaveTextContent("Made the folder Receipts. Undo it from Activity.");
    await user.click(within(sheet).getByRole("button", { name: "Choose" }));
    expect(change).toHaveBeenLastCalledWith("13. Taxes/Receipts");
  });

  it("shows the server's refusal under the name field and keeps it to fix", async () => {
    const { user, sheet, tree } = await setup("13. Taxes", {
      status: 400,
      body: { error: "Folders cannot be made in ##. Important." },
    });
    await user.click(newButton(sheet));
    const input = within(tree).getByRole("textbox", { name: "New folder name" });
    await user.type(input, "Receipts{Enter}");
    expect(await within(tree).findByRole("alert")).toHaveTextContent("Folders cannot be made in ##. Important.");
    expect(input).toBeInTheDocument();
    expect(within(tree).queryByRole("treeitem", { name: "Receipts" })).not.toBeInTheDocument();
  });

  it("Esc cancels the name field only; the sheet stays", async () => {
    const { user, sheet, tree } = await setup("13. Taxes");
    await user.click(newButton(sheet));
    await user.type(within(tree).getByRole("textbox", { name: "New folder name" }), "x{Escape}");
    expect(within(tree).queryByRole("textbox")).not.toBeInTheDocument();
    expect(within(tree).queryByRole("treeitem", { name: /^x/ })).not.toBeInTheDocument();
    expect(screen.getByRole("dialog", { name: "Choose a folder" })).toBeInTheDocument();
  });

  it("refuses an empty name, a slash and a clash, and says why", async () => {
    const { user, sheet, tree } = await setup("10. Financial");
    await user.click(newButton(sheet));
    const input = within(tree).getByRole("textbox", { name: "New folder name" });
    await user.type(input, "{Enter}");
    expect(within(tree).getByRole("alert")).toHaveTextContent("Enter a name.");
    await user.type(input, "a/b{Enter}");
    expect(within(tree).getByRole("alert")).toHaveTextContent("can't contain");
    await user.clear(input);
    await user.type(input, "banks{Enter}");
    expect(within(tree).getByRole("alert")).toHaveTextContent("already a folder named banks");
    expect(input).toBeInTheDocument();
  });

  it("is off inside a refused folder", async () => {
    const { sheet } = await setup("##. Ongoing");
    expect(newButton(sheet)).toBeDisabled();
  });
});
