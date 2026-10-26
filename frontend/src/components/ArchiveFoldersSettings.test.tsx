import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { type Call, mockFetch, renderWithProviders } from "../test-utils";
import { ArchiveFoldersSettings } from "./ArchiveFoldersSettings";

const FOLDERS = {
  folders: [
    { label: null, path: "/Archive", attached: true, connected: true, files: 120 },
    { label: "Scans", path: "/Volumes/Scans", attached: true, connected: true, files: 40 },
    { label: "Vault", path: "/Volumes/Vault", attached: true, connected: false, files: 7 },
    { label: "Old", path: "/Volumes/Old", attached: false, connected: true, files: 3 },
  ],
};
const CHANGE = { label: "Scans", path: "/Volumes/Scans", files: 40, restart_needed: false };
const posts = (calls: Call[], url: string) => calls.filter((c) => c.method === "POST" && c.url === url);

function setup(extra: Parameters<typeof mockFetch>[0] = {}) {
  const calls = mockFetch({ "GET /api/archive-folders": { body: FOLDERS }, ...extra });
  renderWithProviders(<ArchiveFoldersSettings />);
  return { calls, user: userEvent.setup() };
}

describe("Archive folders settings", () => {
  it("lists the main folder without actions, then each extra with its status", async () => {
    setup();
    const [main, scans, vault, old] = await screen.findAllByRole("listitem");
    expect(within(main).getByText("Main folder")).toBeInTheDocument();
    expect(within(main).getByText("/Archive")).toBeInTheDocument();
    expect(within(main).queryByRole("button")).toBeNull();
    expect(within(scans).getByText("Connected")).toBeInTheDocument();
    expect(within(vault).getByText("Not connected")).toBeInTheDocument();
    expect(within(old).getByText("Detached")).toBeInTheDocument();
    expect(within(scans).getByRole("button", { name: "Detach" })).toBeInTheDocument();
    expect(within(old).getByRole("button", { name: "Attach again" })).toBeInTheDocument();
    expect(within(old).queryByRole("button", { name: "Detach" })).toBeNull();
  });

  it("Detach asks first, with the file count, and can also forget tags, notes and places", async () => {
    const { calls, user } = setup({ "POST /api/archive-folders/Scans/detach": { body: CHANGE } });
    const scans = (await screen.findAllByRole("listitem"))[1];
    await user.click(within(scans).getByRole("button", { name: "Detach" }));
    const dialog = await screen.findByRole("dialog");
    expect(
      within(dialog).getByText("Detach 'Scans'? Its 40 files leave the archive until you attach it again. Nothing on the disk changes."),
    ).toBeInTheDocument();
    expect(posts(calls, "/api/archive-folders/Scans/detach")).toHaveLength(0);
    await user.click(within(dialog).getByRole("checkbox", { name: "Also forget their tags, notes and collection places" }));
    await user.click(within(dialog).getByRole("button", { name: "Detach" }));
    await waitFor(() => expect(posts(calls, "/api/archive-folders/Scans/detach")).toHaveLength(1));
    expect(posts(calls, "/api/archive-folders/Scans/detach")[0].body).toEqual({ forget: true, dry_run: false });
  });

  it("Attach again attaches the folder", async () => {
    const { calls, user } = setup({ "POST /api/archive-folders/Old/attach": { body: { ...CHANGE, label: "Old" } } });
    const old = (await screen.findAllByRole("listitem"))[3];
    await user.click(within(old).getByRole("button", { name: "Attach again" }));
    await waitFor(() => expect(posts(calls, "/api/archive-folders/Old/attach")).toHaveLength(1));
    expect(posts(calls, "/api/archive-folders/Old/attach")[0].body).toEqual({ dry_run: false });
  });

  it("Add folder checks first (dry run), says dam will index it, then adds it", async () => {
    const { calls, user } = setup({
      "POST /api/archive-folders": (call) => ({ body: { label: "Taxes", path: "/Volumes/Taxes", files: 0, restart_needed: false, dry: (call.body as { dry_run: boolean }).dry_run } }),
    });
    await user.click(await screen.findByRole("button", { name: "Add folder" }));
    const dialog = await screen.findByRole("dialog");
    await user.type(within(dialog).getByLabelText("Label"), "Taxes");
    await user.type(within(dialog).getByLabelText("Folder path"), "/Volumes/Taxes");
    await user.click(within(dialog).getByRole("button", { name: "Check" }));
    expect(await within(dialog).findByText(/dam will index it in the background\./)).toBeInTheDocument();
    expect(posts(calls, "/api/archive-folders").map((c) => c.body)).toEqual([{ label: "Taxes", path: "/Volumes/Taxes", dry_run: true }]);
    await user.click(within(dialog).getByRole("button", { name: "Add folder" }));
    await waitFor(() => expect(posts(calls, "/api/archive-folders")).toHaveLength(2));
    expect(posts(calls, "/api/archive-folders")[1].body).toEqual({ label: "Taxes", path: "/Volumes/Taxes", dry_run: false });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("shows the server's message when the folder is refused", async () => {
    const { user } = setup({
      "POST /api/archive-folders": { status: 400, body: { error: "That folder is already part of this archive ('Scans')." } },
    });
    await user.click(await screen.findByRole("button", { name: "Add folder" }));
    const dialog = await screen.findByRole("dialog");
    await user.type(within(dialog).getByLabelText("Label"), "Again");
    await user.type(within(dialog).getByLabelText("Folder path"), "/Volumes/Scans");
    await user.click(within(dialog).getByRole("button", { name: "Check" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("That folder is already part of this archive ('Scans').");
  });

  it("shows the restart notice when the server cannot reopen the archive itself", async () => {
    const { user } = setup({ "POST /api/archive-folders/Old/attach": { body: { ...CHANGE, label: "Old", restart_needed: true } } });
    const old = (await screen.findAllByRole("listitem"))[3];
    await user.click(within(old).getByRole("button", { name: "Attach again" }));
    expect(await screen.findByText(/stop dam \(Ctrl\+C in the terminal\) and run/)).toBeInTheDocument();
  });
});
