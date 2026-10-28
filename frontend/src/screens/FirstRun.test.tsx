import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, onTestFinished } from "vitest";
import App from "../App";
import type { SetupCheck, SetupResult } from "../api/client";
import { mockFetch, renderWithProviders } from "../test-utils";
import FirstRun from "./FirstRun";

const FOLDERS = [
  { role: "inbox", title: "Inbox", name: "##. Organize", purpose: "New files to sort wait here." },
  { role: "ongoing", title: "Ongoing", name: "##. Ongoing", purpose: "Links to what you are working on now." },
];
const CANDIDATES = {
  candidates: [
    { provider: "Dropbox", label: "Dropbox", path: "/home/me/Dropbox" },
    { provider: "Google Drive", label: "Google Drive (GoogleDrive-me)", path: "/home/me/gd/My Drive" },
  ],
  special_folders: FOLDERS,
};
const ok = (path: string, subfolders: string[] = [], empty = false, item_count = empty ? 0 : 3): SetupCheck => ({
  ok: true,
  path,
  message: "",
  exists: true,
  can_create: false,
  subfolders,
  empty,
  item_count,
});
const RUNNING_STATUS = {
  configured: true,
  files: 0,
  indexed: 0,
  pending: 0,
  cloud_pending: 0,
  errors: 0,
  unsupported: 0,
  missing: 0,
  inbox_count: 0,
  rule_errors: [],
  tray_errors: [],
  recovery_pending: 0,
  archive_available: true,
  inbox_exists: true,
  special_folders: { inbox: "##. Organize", ongoing: "##. Ongoing", important: "##. Important", quarantine: "##. To Delete" },
};
const SAVED: SetupResult = {
  archive_root: "/home/me/Dropbox/Papers",
  restart_needed: false,
  special_folders: FOLDERS.map((f, i) => ({ ...f, exists: i === 0 })),
};

/** The Use button, once the typed path has been checked and passed. */
async function useButton(name = "Use this folder") {
  const button = await screen.findByRole("button", { name });
  await waitFor(() => expect(button).toBeEnabled());
  return button;
}

const renderScreen = () => renderWithProviders(<FirstRun />);

describe("FirstRun", () => {
  it("explains dam, makes the safety promise and lists the places found", async () => {
    mockFetch({ "GET /api/setup/candidates": { body: CANDIDATES } });
    renderScreen();
    expect(screen.getByRole("heading", { name: "Welcome to Digital Archive Manager" })).toBeInTheDocument();
    expect(screen.getByText(/never deletes anything/)).toBeInTheDocument();
    expect(screen.getByText(/every change\s+can be undone/)).toBeInTheDocument();
    const list = await screen.findByRole("list", { name: "Folders found on this computer" });
    expect(within(list).getByText("Google Drive (GoogleDrive-me)")).toBeInTheDocument();
    expect(within(list).getByText("/home/me/Dropbox")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Use this folder" })).toBeDisabled();
  });

  it("says when nothing was found and still lets you type a path", async () => {
    mockFetch({ "GET /api/setup/candidates": { body: { candidates: [], special_folders: FOLDERS } } });
    renderScreen();
    expect(await screen.findByText(/No cloud-drive folders were found/)).toBeInTheDocument();
    expect(screen.getByLabelText("Folder path")).toBeInTheDocument();
  });

  it("picks a place, descends into a folder and saves it", async () => {
    const user = userEvent.setup();
    const calls = mockFetch({
      "GET /api/setup/candidates": { body: CANDIDATES },
      "POST /api/setup/validate": (call) => {
        const { path } = call.body as { path: string };
        return { body: path.endsWith("Papers") ? ok(path) : ok(path, ["Papers", "Photos"]) };
      },
      "POST /api/setup": { body: SAVED },
    });
    renderScreen();
    await user.click(await screen.findByRole("button", { name: /^Dropbox/ }));
    expect(screen.getByLabelText("Folder path")).toHaveValue("/home/me/Dropbox");
    await user.click(await screen.findByRole("button", { name: "Papers" }));
    expect(screen.getByLabelText("Folder path")).toHaveValue("/home/me/Dropbox/Papers");
    expect(await screen.findByText("This folder can be used.")).toBeInTheDocument();
    await user.click(await useButton());
    expect(await screen.findByRole("heading", { name: "All set" })).toBeInTheDocument();
    const save = calls.find((c) => c.method === "POST" && c.url === "/api/setup");
    expect(save?.body).toEqual({ archive_root: "/home/me/Dropbox/Papers", create: false });
    const folders = screen.getByRole("list", { name: "Folders dam looks for" });
    expect(within(folders).getByText("##. Organize")).toBeInTheDocument();
    expect(within(folders).getByText("found")).toBeInTheDocument();
    expect(within(folders).getByText("not there yet")).toBeInTheDocument();
    expect(screen.getByText(/did not create any of these/)).toBeInTheDocument();
  });

  it("fills the path from the system folder dialog and checks it", async () => {
    document.documentElement.dataset.style = "new";
    onTestFinished(() => {
      delete document.documentElement.dataset.style;
    });
    const user = userEvent.setup();
    mockFetch({
      "GET /api/setup/candidates": { body: CANDIDATES },
      "POST /api/system/choose-folder": { body: { path: "/Users/me/Drive/Papers", cancelled: false, unavailable: null } },
      "POST /api/setup/validate": (call) => ({ body: ok((call.body as { path: string }).path) }),
    });
    renderScreen();
    await user.click(await screen.findByRole("button", { name: "Choose…" }));
    await waitFor(() => expect(screen.getByLabelText("Folder path")).toHaveValue("/Users/me/Drive/Papers"));
    expect(await screen.findByText("This folder can be used.")).toBeInTheDocument();
  });

  it("shows why a typed folder cannot be used and keeps the button off", async () => {
    const user = userEvent.setup();
    mockFetch({
      "GET /api/setup/candidates": { body: CANDIDATES },
      "POST /api/setup/validate": {
        body: { ok: false, path: "/home/me", message: "That is your whole home folder. Choose or create a folder inside it.", exists: true, can_create: false, subfolders: [] },
      },
    });
    renderScreen();
    await user.type(await screen.findByLabelText("Folder path"), "/home/me");
    expect(await screen.findByText(/whole home folder/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Use this folder" })).toBeDisabled();
  });

  it("creates a missing folder only through the explicit button", async () => {
    const user = userEvent.setup();
    const calls = mockFetch({
      "GET /api/setup/candidates": { body: CANDIDATES },
      "POST /api/setup/validate": {
        body: { ok: false, path: "/home/me/New", message: "That folder does not exist yet.", exists: false, can_create: true, subfolders: [] },
      },
      "POST /api/setup": { body: { ...SAVED, archive_root: "/home/me/New" } },
    });
    renderScreen();
    await user.type(await screen.findByLabelText("Folder path"), "/home/me/New");
    const button = await useButton("Create this folder and use it");
    expect(calls.some((c) => c.url === "/api/setup")).toBe(false);
    await user.click(button);
    await screen.findByRole("heading", { name: "All set" });
    expect(calls.find((c) => c.url === "/api/setup")?.body).toEqual({ archive_root: "/home/me/New", create: true });
  });

  it("shows the server's refusal and stays on the screen", async () => {
    const user = userEvent.setup();
    mockFetch({
      "GET /api/setup/candidates": { body: CANDIDATES },
      "POST /api/setup/validate": { body: ok("/home/me/Dropbox") },
      "POST /api/setup": { status: 400, body: { error: "This app cannot write to that folder (it is read-only)." } },
    });
    renderScreen();
    await user.type(await screen.findByLabelText("Folder path"), "/home/me/Dropbox");
    await user.click(await useButton());
    expect(await screen.findByRole("alert")).toHaveTextContent("read-only");
    expect(screen.queryByRole("heading", { name: "All set" })).not.toBeInTheDocument();
  });

  it("tells you to restart when the server could not switch itself on", async () => {
    const user = userEvent.setup();
    mockFetch({
      "GET /api/setup/candidates": { body: CANDIDATES },
      "POST /api/setup/validate": { body: ok("/home/me/Dropbox") },
      "POST /api/setup": { body: { ...SAVED, restart_needed: true } },
    });
    renderScreen();
    await user.type(await screen.findByLabelText("Folder path"), "/home/me/Dropbox");
    await user.click(await useButton());
    expect(await screen.findByText("dam serve")).toBeInTheDocument();
    expect(screen.getByText(/stop dam/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Open dam" })).not.toBeInTheDocument();
  });
});

describe("App gate", () => {
  it("shows the first-run screen instead of the app while unconfigured, then the app", async () => {
    const user = userEvent.setup();
    let configured = false;
    mockFetch({
      "GET /api/status": () => ({ body: configured ? RUNNING_STATUS : { configured: false } }),
      "GET /api/setup/candidates": { body: CANDIDATES },
      "POST /api/setup/validate": { body: ok("/home/me/Dropbox") },
      "POST /api/setup": () => {
        configured = true;
        return { body: SAVED };
      },
    });
    renderWithProviders(
      <MemoryRouter initialEntries={["/"]}>
        <App />
      </MemoryRouter>,
    );
    expect(await screen.findByRole("heading", { name: "Welcome to Digital Archive Manager" })).toBeInTheDocument();
    expect(screen.queryByRole("navigation")).not.toBeInTheDocument();
    await user.type(screen.getByLabelText("Folder path"), "/home/me/Dropbox");
    await user.click(await useButton());
    await user.click(await screen.findByRole("button", { name: "Open dam" }));
    await waitFor(() => expect(screen.queryByRole("heading", { name: "All set" })).not.toBeInTheDocument());
    await waitFor(() => expect(screen.queryByText("Welcome to Digital Archive Manager")).not.toBeInTheDocument());
  });
});

// -- starting a new archive ---------------------------------------------------------

const FOUR = [
  { role: "inbox", title: "Inbox", name: "##. Organize", purpose: "New documents wait here until you file them." },
  { role: "ongoing", title: "Ongoing", name: "##. Ongoing", purpose: "Shortcuts to the collections you are working on now." },
  { role: "important", title: "Important", name: "##. Important", purpose: "Shortcuts to the key documents you must not lose." },
  { role: "quarantine", title: "To delete", name: "##. To Delete", purpose: "Files you mark for deletion wait here instead." },
];
const TEMPLATES = [
  {
    id: "household",
    title: "Household",
    description: "Finance, bills and more.",
    folders: [
      { key: "finance", name: "Finance" },
      { key: "bills", name: "Bills & Receipts" },
    ],
  },
  { id: "empty", title: "Empty", description: "Only the special folders.", folders: [] },
];
const NEW_CANDIDATES = { candidates: [], special_folders: FOUR, layouts: TEMPLATES };
const PREVIEW = {
  folders: [
    ...FOUR.map((f) => ({ path: f.name, role: f.role, title: f.title, exists: false })),
    { path: "10. Finance", role: "layout", title: "Finance", exists: false },
    { path: "11. Bills & Receipts", role: "layout", title: "Bills & Receipts", exists: false },
  ],
  to_create: 6,
  label: "Created the archive layout (6 folders)",
  ops: [],
  rule_ids: ["receipts-and-invoices"],
  rules_seedable: true,
};
const MADE: SetupResult = {
  archive_root: "/home/me/Archive",
  restart_needed: false,
  special_folders: FOUR.map((f) => ({ ...f, exists: true })),
  layout: {
    batch: { batch_id: "b1", dry_run: false, done: [], failed: null, error: null, index_error: null },
    created: 6,
    rules_written: true,
    rule_ids: ["receipts-and-invoices"],
    rules_error: null,
    error: null,
  },
};

function newArchiveApi(check: SetupCheck, extra: Parameters<typeof mockFetch>[0] = {}) {
  return mockFetch({
    "GET /api/setup/candidates": { body: NEW_CANDIDATES },
    "POST /api/setup/validate": { body: check },
    "POST /api/setup/layout-preview": { body: PREVIEW },
    "POST /api/setup": { body: MADE },
    ...extra,
  });
}
const saveCall = (calls: Awaited<ReturnType<typeof mockFetch>>) => calls.find((c) => c.method === "POST" && c.url === "/api/setup");

describe("FirstRun: start a new archive", () => {
  it("offers a new archive in an empty folder, with the layout editable and previewed", async () => {
    const user = userEvent.setup();
    const calls = newArchiveApi(ok("/home/me/Archive", [], true));
    renderScreen();
    await user.type(await screen.findByLabelText("Folder path"), "/home/me/Archive");
    expect(await screen.findByRole("radio", { name: /Start a new archive here/ })).toBeChecked();
    expect(screen.getByRole("radio", { name: /Household/ })).toBeChecked();
    // the four special folders, each explained in one line, with editable names
    const specials = screen.getByRole("list", { name: "Special folders" });
    expect(within(specials).getByText("New documents wait here until you file them.")).toBeInTheDocument();
    expect(within(specials).getByLabelText(/Inbox/)).toHaveValue("##. Organize");
    // every folder is previewed before anything is made
    const preview = await screen.findByRole("region", { name: "Folders that will be made" });
    expect(within(preview).getByText("6 folders will be made")).toBeInTheDocument();
    expect(within(preview).getByText("11. Bills & Receipts")).toBeInTheDocument();
    expect(calls.some((c) => c.url === "/api/setup" && c.method === "POST")).toBe(false);

    // edit: rename the first, remove the second, add one, rename the inbox
    await user.clear(screen.getByLabelText("Folder 1 name"));
    await user.type(screen.getByLabelText("Folder 1 name"), "Money");
    await user.click(screen.getByRole("button", { name: "Remove Bills & Receipts" }));
    await user.click(screen.getByRole("button", { name: "Add a folder" }));
    await user.type(screen.getByLabelText("Folder 2 name"), "Pets");
    await user.clear(within(specials).getByLabelText(/Inbox/));
    await user.type(within(specials).getByLabelText(/Inbox/), "In");
    await user.click(screen.getByRole("checkbox", { name: /Number the folders/ }));

    const expected = {
      template: "household",
      numbered: false,
      folders: [
        { key: "finance", name: "Money" },
        { key: null, name: "Pets" },
      ],
      special: { inbox: "In", ongoing: "##. Ongoing", important: "##. Important", quarantine: "##. To Delete" },
    };
    await waitFor(() => {
      const last = calls.filter((c) => c.url === "/api/setup/layout-preview").at(-1);
      expect(last?.body).toEqual({ path: "/home/me/Archive", layout: expected });
    });
    await user.click(await useButton("Make the folders and use this folder"));
    expect(await screen.findByRole("heading", { name: "All set" })).toBeInTheDocument();
    expect(saveCall(calls)?.body).toEqual({ archive_root: "/home/me/Archive", create: false, layout: expected });
    expect(screen.getByText(/dam made 6 folders/)).toBeInTheDocument();
    expect(screen.getByText(/Undo it from Activity/)).toBeInTheDocument();
    expect(screen.queryByText(/did not create any of these/)).not.toBeInTheDocument();
  });

  it("an empty folder can still be used as it is", async () => {
    const user = userEvent.setup();
    const calls = newArchiveApi(ok("/home/me/Archive", [], true));
    renderScreen();
    await user.type(await screen.findByLabelText("Folder path"), "/home/me/Archive");
    await user.click(await screen.findByRole("radio", { name: /Use this folder as it is/ }));
    expect(screen.queryByRole("list", { name: "Special folders" })).not.toBeInTheDocument();
    await user.click(await useButton());
    await screen.findByRole("heading", { name: "All set" });
    expect(saveCall(calls)?.body).toEqual({ archive_root: "/home/me/Archive", create: false });
  });

  it("a folder with content defaults to use as is, and can still get a layout", async () => {
    const user = userEvent.setup();
    const calls = newArchiveApi(ok("/home/me/Archive", [], false, 7));
    renderScreen();
    await user.type(await screen.findByLabelText("Folder path"), "/home/me/Archive");
    expect(await screen.findByRole("radio", { name: /^Use this folder as it is/ })).toBeChecked();
    expect(screen.getByText(/holds 7 items/)).toBeInTheDocument();
    expect(screen.queryByRole("list", { name: "Special folders" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("radio", { name: /also add a folder layout/ }));
    expect(await screen.findByRole("list", { name: "Special folders" })).toBeInTheDocument();
    expect(screen.getByText(/Only folders that do not exist yet are made/)).toBeInTheDocument();
    await user.click(await useButton("Make the folders and use this folder"));
    await screen.findByRole("heading", { name: "All set" });
    expect((saveCall(calls)?.body as { layout?: unknown }).layout).toBeDefined();
  });

  it("a folder that does not exist yet is created, then filled with the layout", async () => {
    const user = userEvent.setup();
    const missing: SetupCheck = { ok: false, path: "/home/me/New", message: "That folder does not exist yet.", exists: false, can_create: true, subfolders: [], empty: false, item_count: 0 };
    const calls = newArchiveApi(missing);
    renderScreen();
    await user.type(await screen.findByLabelText("Folder path"), "/home/me/New");
    await user.click(await useButton("Create the folder, make the folders and use it"));
    await screen.findByRole("heading", { name: "All set" });
    expect(saveCall(calls)?.body).toMatchObject({ archive_root: "/home/me/New", create: true });
  });

  it("shows a refused name and keeps the button off", async () => {
    const user = userEvent.setup();
    newArchiveApi(ok("/home/me/Archive", [], true), {
      "POST /api/setup/layout-preview": { status: 400, body: { error: "'CON': 'CON' is a reserved name on Windows. Choose another." } },
    });
    renderScreen();
    await user.type(await screen.findByLabelText("Folder path"), "/home/me/Archive");
    expect(await screen.findByRole("alert")).toHaveTextContent("reserved name");
    expect(screen.getByRole("button", { name: "Make the folders and use this folder" })).toBeDisabled();
  });

  it("reports a layout that could not be made, after the folder was saved", async () => {
    const user = userEvent.setup();
    newArchiveApi(ok("/home/me/Archive", [], true), {
      "POST /api/setup": { body: { ...MADE, layout: { error: "dam has to be restarted before the folders can be made. After restarting, choose Set up folders in Browse.", created: 0, rules_written: false, rule_ids: [] } } },
    });
    renderScreen();
    await user.type(await screen.findByLabelText("Folder path"), "/home/me/Archive");
    await user.click(await useButton("Make the folders and use this folder"));
    expect(await screen.findByText(/has to be restarted/)).toBeInTheDocument();
  });
});

describe("FirstRun for an extra archive", () => {
  it("offers the archive menu, so an abandoned setup can be left", async () => {
    mockFetch({
      "GET /api/status": { body: { configured: false, archive: { id: "scratch", name: "Scratch", color: "#d9822b" }, profiles_count: 2 } },
      "GET /api/archives": {
        body: {
          archives: [
            { id: "main", name: "Main", color: "#3b6fd4", data_dir: "/d", archive_root: "/a", configured: true, current: false, in_use_elsewhere: false, port: null },
            { id: "scratch", name: "Scratch", color: "#d9822b", data_dir: "/d/s", archive_root: null, configured: false, current: true, in_use_elsewhere: false, port: null },
          ],
          current: "scratch",
          can_switch: true,
        },
      },
      "GET /api/setup/candidates": { body: CANDIDATES },
    });
    renderWithProviders(
      <MemoryRouter>
        <FirstRun />
      </MemoryRouter>,
    );
    expect(await screen.findByRole("button", { name: "Archive: Scratch" })).toBeInTheDocument();
    await userEvent.setup().click(screen.getByRole("button", { name: "Archive: Scratch" }));
    expect(screen.getByRole("menuitemcheckbox", { name: "Main" })).toBeInTheDocument();
  });
});
