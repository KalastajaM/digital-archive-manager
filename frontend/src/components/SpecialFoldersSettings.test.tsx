import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";
import { type Call, mockFetch, renderWithProviders } from "../test-utils";
import { inToDelete, setQuarantineName } from "../toDelete";
import { ArchiveFoldersSettings } from "./ArchiveFoldersSettings";

const FOLDERS = { folders: [{ label: null, path: "/Archive", attached: true, connected: true, files: 120 }] };
const STATUS = {
  special_folders: { inbox: "##. Organize", ongoing: "##. Ongoing", important: "##. Important", quarantine: "##. To Delete" },
};
const PREVIEW = {
  key: "inbox",
  title: "Inbox",
  old: "##. Organize",
  new: "00. Inbox",
  places: [
    { place: "Folder on disk", how: "renamed", what: "'##. Organize' is renamed to '00. Inbox' (the folder), by a journaled rename on its own disk." },
    { place: "Index", how: "renamed", what: "12 file and folder paths in the index follow the folder." },
    { place: "Rules", how: "unchanged", what: "No rule has a folder that starts with the old name." },
    { place: "Ongoing and Important: shortcuts", how: "rebuilt", what: "2 shortcuts to files in the folder: the sync makes them point at the new path." },
  ],
  warnings: ["The folder is on Google Drive. The rename has to sync to every device before they see it."],
  google_drive: true,
  undo: "Undo in Activity puts every one of these back.",
  batch_id: null,
};
const URL = "/api/special-folders/inbox/rename";
const rename = (calls: Call[]) => calls.filter((c) => c.method === "POST" && c.url === URL);

function setup(extra: Parameters<typeof mockFetch>[0] = {}) {
  const calls = mockFetch({
    "GET /api/archive-folders": { body: FOLDERS },
    "GET /api/status": { body: STATUS },
    [`POST ${URL}`]: (call) => ({ body: { ...PREVIEW, batch_id: (call.body as { dry_run: boolean }).dry_run ? null : "batch-1" } }),
    ...extra,
  });
  renderWithProviders(<ArchiveFoldersSettings />);
  return { calls, user: userEvent.setup() };
}

afterEach(() => {
  setQuarantineName(undefined);
});

describe("Special folders", () => {
  it("lists the four folders with their names and a Rename each", async () => {
    setup();
    const list = await screen.findByRole("list", { name: "Special folders" });
    const rows = within(list).getAllByRole("listitem");
    expect(rows.map((r) => within(r).getByRole("strong", { hidden: true }).textContent)).toEqual(["Inbox", "Ongoing", "Important", "To Delete"]);
    await waitFor(() => expect(within(rows[0]).getByText("##. Organize")).toBeInTheDocument());
    expect(within(rows[3]).getByText("##. To Delete")).toBeInTheDocument();
    for (const title of ["Inbox", "Ongoing", "Important", "To Delete"]) {
      expect(screen.getByRole("button", { name: `Rename the ${title} folder` })).toBeEnabled();
    }
  });

  it("previews every place, then renames and offers Undo in a toast", async () => {
    const { calls, user } = setup({ "POST /api/activity/batch-1/undo": { body: { batch_id: "u1" } } });
    await user.click(await screen.findByRole("button", { name: "Rename the Inbox folder" }));
    const dialog = await screen.findByRole("dialog", { name: "Rename the Inbox folder" });
    const input = within(dialog).getByRole("textbox", { name: "New name" });
    expect(input).toHaveValue("##. Organize");
    await user.clear(input);
    await user.type(input, "00. Inbox");
    await user.click(within(dialog).getByRole("button", { name: "Preview" }));
    const places = await within(dialog).findByRole("list", { name: "What changes" });
    expect(within(places).getAllByRole("listitem")).toHaveLength(4);
    expect(within(places).getByText("Rebuilt")).toBeInTheDocument();
    expect(within(places).getByText("Stays")).toBeInTheDocument();
    expect(within(dialog).getByText(/The folder is on Google Drive/)).toBeInTheDocument();
    expect(rename(calls)).toHaveLength(1);
    expect(rename(calls)[0].body).toEqual({ name: "00. Inbox", dry_run: true });

    await user.click(within(dialog).getByRole("button", { name: "Rename folder" }));
    await waitFor(() => expect(rename(calls)).toHaveLength(2));
    expect(rename(calls)[1].body).toEqual({ name: "00. Inbox", dry_run: false });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    const toasts = await screen.findByRole("status");
    expect(within(toasts).getByText("Renamed the Inbox folder to '00. Inbox'.")).toBeInTheDocument();
    await user.click(within(toasts).getByRole("button", { name: "Undo" }));
    await waitFor(() => expect(calls.some((c) => c.url === "/api/activity/batch-1/undo")).toBe(true));
    expect(await within(toasts).findByText("The Inbox folder is called '##. Organize' again.")).toBeInTheDocument();
  });

  it("changing the name asks for a new preview before renaming", async () => {
    const { calls, user } = setup();
    await user.click(await screen.findByRole("button", { name: "Rename the Inbox folder" }));
    const dialog = await screen.findByRole("dialog");
    const input = within(dialog).getByRole("textbox", { name: "New name" });
    await user.clear(input);
    await user.type(input, "00. Inbox");
    await user.click(within(dialog).getByRole("button", { name: "Preview" }));
    await within(dialog).findByRole("list", { name: "What changes" });
    await user.type(input, "x");
    expect(within(dialog).queryByRole("list", { name: "What changes" })).toBeNull();
    expect(within(dialog).getByRole("button", { name: "Preview" })).toBeInTheDocument();
    expect(rename(calls)).toHaveLength(1);
  });

  it("shows the server's reason when the name or the state refuses", async () => {
    const { user } = setup({
      [`POST ${URL}`]: { status: 409, body: { error: "An operation was interrupted. Run recovery first." } },
    });
    await user.click(await screen.findByRole("button", { name: "Rename the Inbox folder" }));
    const dialog = await screen.findByRole("dialog");
    await user.type(within(dialog).getByRole("textbox", { name: "New name" }), "x");
    await user.click(within(dialog).getByRole("button", { name: "Preview" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("An operation was interrupted. Run recovery first.");
  });

  it("Cancel closes the sheet without renaming", async () => {
    const { calls, user } = setup();
    await user.click(await screen.findByRole("button", { name: "Rename the Ongoing folder" }));
    await user.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(calls.filter((c) => c.method === "POST")).toHaveLength(0);
  });
});

describe("To Delete follows its configured name", () => {
  it("knows the default, and a renamed folder once the status says so", () => {
    expect(inToDelete("##. To Delete/a.pdf")).toBe(true);
    expect(inToDelete("99. Bin/a.pdf")).toBe(false);
    setQuarantineName("99. Bin");
    expect(inToDelete("99. Bin/a.pdf")).toBe(true);
    expect(inToDelete("##. To Delete/a.pdf")).toBe(false);
    setQuarantineName(undefined);
    expect(inToDelete("##. To Delete")).toBe(true);
    // each archive folder has its own To Delete, found while the name starts with ##.
    expect(inToDelete("Old years/##. To Delete/a.pdf")).toBe(true);
    expect(inToDelete("10. Home/##. To Delete")).toBe(true);
    expect(inToDelete("Old years/2009/a.pdf")).toBe(false);
    setQuarantineName("99. Bin");
    expect(inToDelete("Old years/99. Bin/a.pdf")).toBe(false);
  });
});
