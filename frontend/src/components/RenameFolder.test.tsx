import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { type Call, mockFetch, renderWithProviders } from "../test-utils";
import { followRename, useRenameFolderSheet } from "./RenameFolder";

const FOLDER = { drive_id: "f-2009", name: "2009", path: "20. Home/2009" };
const PREVIEW = {
  old: "2009",
  new: "2010",
  path: "20. Home/2009",
  new_path: "20. Home/2010",
  places: [
    { place: "Folder on disk", how: "renamed", what: "'2009' becomes '2010' in 20. Home, by a journaled rename." },
    { place: "Rules", how: "renamed", what: "2 rules point here and will follow (zz-mine.yaml)." },
    { place: "Collections", how: "unchanged", what: "1 collection holds the folder or files in it." },
    { place: "Ongoing and Important: shortcuts", how: "rebuilt", what: "1 shortcut is rebuilt." },
  ],
  warnings: ["1 shortcut elsewhere in the archive points into '20. Home/2009'."],
  google_drive: false,
  undo: "Undo in Activity puts every one of these back.",
  batch_id: null,
};
const PREVIEW_URL = "/api/browse/folder-rename/preview";
const APPLY_URL = "/api/browse/folder-rename";
const posts = (calls: Call[], url: string) => calls.filter((c) => c.method === "POST" && c.url === url);

function Harness({ onRenamed }: { onRenamed?: (from: string, to: string) => void }) {
  const sheet = useRenameFolderSheet(onRenamed);
  return (
    <>
      <button type="button" onClick={() => sheet.open(FOLDER)}>
        Open
      </button>
      {sheet.view}
    </>
  );
}

function setup(extra: Parameters<typeof mockFetch>[0] = {}, onRenamed?: (from: string, to: string) => void) {
  const calls = mockFetch({
    [`POST ${PREVIEW_URL}`]: { body: PREVIEW },
    [`POST ${APPLY_URL}`]: { body: { ...PREVIEW, batch_id: "batch-1" } },
    ...extra,
  });
  renderWithProviders(<Harness onRenamed={onRenamed} />);
  return { calls, user: userEvent.setup() };
}

describe("Rename folder", () => {
  it("previews what follows the folder, then renames and offers Undo", async () => {
    const onRenamed = vi.fn();
    const { calls, user } = setup({ "POST /api/activity/batch-1/undo": { body: { batch_id: "u1" } } }, onRenamed);
    await user.click(screen.getByRole("button", { name: "Open" }));
    const dialog = await screen.findByRole("dialog", { name: "Rename folder 2009" });
    const input = within(dialog).getByRole("textbox", { name: "New name" });
    expect(input).toHaveValue("2009");
    expect(within(dialog).getByRole("button", { name: "Preview" })).toBeDisabled(); // its own name
    await user.clear(input);
    await user.type(input, "2010");
    await user.click(within(dialog).getByRole("button", { name: "Preview" }));
    const places = await within(dialog).findByRole("list", { name: "What changes" });
    expect(within(places).getAllByRole("listitem")).toHaveLength(4);
    expect(within(places).getByText("2 rules point here and will follow (zz-mine.yaml).")).toBeInTheDocument();
    expect(within(dialog).getByText(/1 shortcut elsewhere/)).toBeInTheDocument();
    expect(posts(calls, PREVIEW_URL)[0].body).toEqual({ drive_id: "f-2009", name: "2010" });
    expect(posts(calls, APPLY_URL)).toHaveLength(0);

    await user.click(within(dialog).getByRole("button", { name: "Rename folder" }));
    await waitFor(() => expect(posts(calls, APPLY_URL)).toHaveLength(1));
    expect(posts(calls, APPLY_URL)[0].body).toEqual({ drive_id: "f-2009", name: "2010" });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(onRenamed).toHaveBeenCalledWith("20. Home/2009", "20. Home/2010");
    const toasts = await screen.findByRole("status");
    expect(within(toasts).getByText("Renamed the folder 2009 to 2010.")).toBeInTheDocument();
    await user.click(within(toasts).getByRole("button", { name: "Undo" }));
    await waitFor(() => expect(calls.some((c) => c.url === "/api/activity/batch-1/undo")).toBe(true));
    expect(await within(toasts).findByText("The folder is called 2009 again.")).toBeInTheDocument();
    expect(onRenamed).toHaveBeenLastCalledWith("20. Home/2010", "20. Home/2009");
  });

  it("changing the name asks for a new preview", async () => {
    const { calls, user } = setup();
    await user.click(screen.getByRole("button", { name: "Open" }));
    const dialog = await screen.findByRole("dialog");
    const input = within(dialog).getByRole("textbox", { name: "New name" });
    await user.type(input, "x");
    await user.click(within(dialog).getByRole("button", { name: "Preview" }));
    await within(dialog).findByRole("list", { name: "What changes" });
    await user.type(input, "y");
    expect(within(dialog).queryByRole("list", { name: "What changes" })).toBeNull();
    expect(within(dialog).getByRole("button", { name: "Preview" })).toBeInTheDocument();
    expect(posts(calls, PREVIEW_URL)).toHaveLength(1);
  });

  it("shows the server's reason when the name is refused", async () => {
    const { calls, user } = setup({
      [`POST ${PREVIEW_URL}`]: { status: 400, body: { error: "There is already a folder or file named 'Sub' in 20. Home. Choose another name." } },
    });
    await user.click(screen.getByRole("button", { name: "Open" }));
    const dialog = await screen.findByRole("dialog");
    await user.type(within(dialog).getByRole("textbox", { name: "New name" }), "x");
    await user.click(within(dialog).getByRole("button", { name: "Preview" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("There is already a folder or file named 'Sub'");
    expect(posts(calls, APPLY_URL)).toHaveLength(0);
  });

  it("Cancel closes the sheet without renaming", async () => {
    const { calls, user } = setup();
    await user.click(screen.getByRole("button", { name: "Open" }));
    await user.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(calls.filter((c) => c.method === "POST")).toHaveLength(0);
  });
});

describe("followRename", () => {
  it("moves a path at or under the renamed folder and leaves the rest", () => {
    expect(followRename("20. Home/2009", "20. Home/2009", "20. Home/2010")).toBe("20. Home/2010");
    expect(followRename("20. Home/2009/sub", "20. Home/2009", "20. Home/2010")).toBe("20. Home/2010/sub");
    expect(followRename("20. Home/2009-old", "20. Home/2009", "20. Home/2010")).toBe("20. Home/2009-old");
    expect(followRename("20. Home", "20. Home/2009", "20. Home/2010")).toBe("20. Home");
  });
});
