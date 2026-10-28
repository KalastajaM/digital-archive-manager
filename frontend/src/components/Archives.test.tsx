import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi, onTestFinished } from "vitest";
import App from "../App";
import { type Archive, getActiveArchive, navigation, setActiveArchive } from "../api/client";
import { type Call, mockFetch, renderWithProviders } from "../test-utils";
import { ArchiveSwitcher } from "./ArchiveSwitcher";
import { Sidebar } from "./ui/Sidebar";

const MAIN: Archive = {
  id: "main",
  name: "Main",
  color: "#3b6fd4",
  data_dir: "/data",
  archive_root: "/Archive",
  extra_folders: [],
  configured: true,
  current: true,
  in_use_elsewhere: false,
  port: null,
};
const TEST: Archive = {
  id: "test",
  name: "Test",
  color: "#d9822b",
  data_dir: "/data/archives/test",
  archive_root: "/TestArchive",
  extra_folders: [],
  configured: true,
  current: false,
  in_use_elsewhere: false,
  port: null,
};
const STATUS = {
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
  archive: { id: "main", name: "Main", color: "#3b6fd4" },
  profiles_count: 2,
};
const listing = (archives: Archive[], can_switch = true) => ({ body: { archives, current: "main", can_switch } });
const posts = (calls: Call[], url: string) => calls.filter((c) => c.method === "POST" && c.url === url);

let leave: ReturnType<typeof vi.fn>;
beforeEach(() => {
  leave = vi.fn();
  vi.spyOn(navigation, "leave").mockImplementation(leave as () => void);
  setActiveArchive(null);
});
afterEach(() => {
  vi.restoreAllMocks();
  setActiveArchive(null);
});

function renderSwitcher(routes: Parameters<typeof mockFetch>[0] = {}) {
  const calls = mockFetch({
    "GET /api/status": { body: STATUS },
    "GET /api/archives": listing([MAIN, TEST]),
    ...routes,
  });
  renderWithProviders(<ArchiveSwitcher />);
  return { calls, user: userEvent.setup() };
}

describe("the archive menu", () => {
  it("shows the archive in use with its colour and lists the archives", async () => {
    const { user } = renderSwitcher();
    const button = await screen.findByRole("button", { name: "Archive: Main" });
    expect(button).toHaveTextContent("Main");
    expect(getComputedStyle(button.querySelector(".archive-dot")!).backgroundColor).toBe("rgb(59, 111, 212)");
    await user.click(button);
    const menu = screen.getByRole("menu", { name: "Archive: Main" });
    expect(within(menu).getByRole("menuitemcheckbox", { name: "Main" })).toHaveAttribute("aria-checked", "true");
    expect(within(menu).getByRole("menuitemcheckbox", { name: "Test" })).toHaveAttribute("aria-checked", "false");
    expect(within(menu).getByRole("menuitem", { name: "Add archive…" })).toBeInTheDocument();
    expect(within(menu).getByRole("menuitem", { name: "Manage archives…" })).toBeInTheDocument();
  });

  it("in the New look shows the archive's initial and, under its name, where the folder is and how many files", async () => {
    document.documentElement.dataset.style = "new";
    try {
      mockFetch({
        "GET /api/status": { body: { ...STATUS, files: 2418 } },
        "GET /api/archives": listing([{ ...MAIN, archive_root: "/Users/a/Library/CloudStorage/GoogleDrive-a@b.fi/My Drive/Archive" }, TEST]),
      });
      renderWithProviders(<ArchiveSwitcher />);
      const button = await screen.findByRole("button", { name: "Archive: Main" });
      await waitFor(() => expect(button).toHaveTextContent("Google Drive · 2 418 files"));
      expect(button.querySelector(".archive-tile")).toHaveTextContent("M");
      expect(button.querySelector(".archive-dot")).toBeNull();
    } finally {
      delete document.documentElement.dataset.style;
    }
  });

  it("is reachable and usable with the keyboard", async () => {
    const { user, calls } = renderSwitcher({ "POST /api/archives/test/switch": { body: { archive: TEST, restart_needed: false } } });
    const button = await screen.findByRole("button", { name: "Archive: Main" });
    button.focus();
    await user.keyboard("{Enter}");
    await screen.findByRole("menu");
    await user.keyboard("{ArrowDown}{Enter}"); // from Main to Test
    await waitFor(() => expect(posts(calls, "/api/archives/test/switch")).toHaveLength(1));
    await waitFor(() => expect(leave).toHaveBeenCalled());
  });

  it("switching opens the other archive and reloads the page", async () => {
    const { user, calls } = renderSwitcher({ "POST /api/archives/test/switch": { body: { archive: TEST, restart_needed: false } } });
    await user.click(await screen.findByRole("button", { name: "Archive: Main" }));
    await user.click(screen.getByRole("menuitemcheckbox", { name: "Test" }));
    await waitFor(() => expect(leave).toHaveBeenCalledTimes(1));
    expect(posts(calls, "/api/archives/test/switch")).toHaveLength(1);
    // the request named the archive the page showed
    expect(posts(calls, "/api/archives/test/switch")[0].headers["X-Dam-Archive"]).toBe("main");
  });

  it("an archive another window has open is listed but cannot be picked", async () => {
    const { user, calls } = renderSwitcher({
      "GET /api/archives": listing([MAIN, { ...TEST, in_use_elsewhere: true, port: 8766 }]),
    });
    await user.click(await screen.findByRole("button", { name: "Archive: Main" }));
    const item = screen.getByRole("menuitemcheckbox", { name: /Test/ });
    expect(item).toBeDisabled();
    expect(item).toHaveTextContent("Open in another window (port 8766)");
    expect(posts(calls, "/api/archives/test/switch")).toHaveLength(0);
  });

  it("a refused switch says why and stays", async () => {
    const { user } = renderSwitcher({
      "POST /api/archives/test/switch": { status: 409, body: { error: "This archive is already open in another dam window (on port 8766)." } },
    });
    await user.click(await screen.findByRole("button", { name: "Archive: Main" }));
    await user.click(screen.getByRole("menuitemcheckbox", { name: "Test" }));
    expect(await screen.findByText(/Could not open Test: .*already open in another dam window/)).toBeInTheDocument();
    expect(leave).not.toHaveBeenCalled();
  });

  it("a window that cannot switch disables the other archives", async () => {
    const { user } = renderSwitcher({ "GET /api/archives": listing([MAIN, TEST], false) });
    await user.click(await screen.findByRole("button", { name: "Archive: Main" }));
    expect(screen.getByRole("menuitemcheckbox", { name: /Test/ })).toBeDisabled();
  });

  it("is the top of the sidebar", async () => {
    mockFetch({
      "GET /api/status": { body: STATUS },
      "GET /api/archives": listing([MAIN, TEST]),
      "GET /api/today": { body: { attention: [], overview: { inbox: 0, trays: [], collections: [] } } },
      "GET /api/trays": { body: { trays: [], errors: [] } },
      "GET /api/collections": { body: [] },
    });
    renderWithProviders(
      <MemoryRouter>
        <Sidebar />
      </MemoryRouter>,
    );
    expect(await screen.findByRole("button", { name: "Archive: Main" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Main");
  });
});

describe("Add archive", () => {
  const open = async (user: ReturnType<typeof userEvent.setup>) => {
    await user.click(await screen.findByRole("button", { name: "Archive: Main" }));
    await user.click(screen.getByRole("menuitem", { name: "Add archive…" }));
    return screen.findByRole("dialog", { name: "Add archive" });
  };

  it("name and colour first; then it adds the archive, opens it and lands in its setup", async () => {
    const { user, calls } = renderSwitcher({
      "POST /api/archives": { body: { ...TEST, id: "scratch", name: "Scratch", archive_root: null, configured: false } },
      "POST /api/archives/scratch/switch": { body: { archive: TEST, restart_needed: false } },
    });
    const dialog = await open(user);
    const add = within(dialog).getByRole("button", { name: "Add and set up" });
    expect(add).toBeDisabled(); // no name yet
    await user.type(within(dialog).getByLabelText("Name"), "Scratch");
    await user.click(within(dialog).getByRole("button", { name: "Purple" }));
    expect(within(dialog).getByRole("button", { name: "Purple" })).toHaveAttribute("aria-pressed", "true");
    await user.click(add);
    await waitFor(() => expect(leave).toHaveBeenCalled());
    expect(posts(calls, "/api/archives")[0].body).toEqual({ name: "Scratch", color: "#8a5cc7" });
    expect(posts(calls, "/api/archives/scratch/switch")).toHaveLength(1);
  });

  it("suggests a colour no archive uses", async () => {
    const { user } = renderSwitcher();
    const dialog = await open(user);
    // Main is blue and Test orange: the suggestion is the next free one
    await waitFor(() => expect(within(dialog).getByRole("button", { name: "Purple" })).toHaveAttribute("aria-pressed", "true"));
  });

  it("offers a demo archive in a folder the user picks", async () => {
    const { user, calls } = renderSwitcher({
      "POST /api/archives": { body: { ...TEST, id: "demo", name: "Demo" } },
      "POST /api/archives/demo/switch": { body: { archive: TEST, restart_needed: false } },
    });
    const dialog = await open(user);
    await user.type(within(dialog).getByLabelText("Name"), "Demo");
    await user.click(within(dialog).getByRole("radio", { name: /Create a demo archive/ }));
    const create = within(dialog).getByRole("button", { name: "Create demo archive" });
    expect(create).toBeDisabled(); // needs a folder
    await user.type(within(dialog).getByLabelText("Folder for the demo archive"), "/tmp/demo-folder");
    await user.click(create);
    await waitFor(() => expect(leave).toHaveBeenCalled());
    expect(posts(calls, "/api/archives")[0].body).toMatchObject({ name: "Demo", demo_folder: "/tmp/demo-folder" });
  });

  it("fills the demo folder from the system folder dialog", async () => {
    document.documentElement.dataset.style = "new";
    onTestFinished(() => {
      delete document.documentElement.dataset.style;
    });
    const { user } = renderSwitcher({
      "POST /api/system/choose-folder": { body: { path: "/Users/me/Demo", cancelled: false, unavailable: null } },
    });
    const dialog = await open(user);
    await user.click(within(dialog).getByRole("radio", { name: /Create a demo archive/ }));
    await user.click(within(dialog).getByRole("button", { name: "Choose…" }));
    await waitFor(() => expect(within(dialog).getByLabelText("Folder for the demo archive")).toHaveValue("/Users/me/Demo"));
  });

  it("shows the server's refusal (a folder that is not empty) and stays", async () => {
    const { user } = renderSwitcher({
      "POST /api/archives": { status: 400, body: { error: "That folder is not empty. Pick a new or empty folder." } },
    });
    const dialog = await open(user);
    await user.type(within(dialog).getByLabelText("Name"), "Demo");
    await user.click(within(dialog).getByRole("radio", { name: /Create a demo archive/ }));
    await user.type(within(dialog).getByLabelText("Folder for the demo archive"), "/tmp/full");
    await user.click(within(dialog).getByRole("button", { name: "Create demo archive" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("not empty");
    expect(leave).not.toHaveBeenCalled();
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});

describe("Manage archives", () => {
  const open = async (user: ReturnType<typeof userEvent.setup>) => {
    await user.click(await screen.findByRole("button", { name: "Archive: Main" }));
    await user.click(screen.getByRole("menuitem", { name: "Manage archives…" }));
    return screen.findByRole("dialog", { name: "Manage archives" });
  };

  it("lists each archive with its paths and shows them in the file manager", async () => {
    const { user, calls } = renderSwitcher({ "POST /api/archives/test/reveal": { status: 204, body: null } });
    const dialog = await open(user);
    const rows = await within(dialog).findAllByRole("listitem");
    expect(rows).toHaveLength(2);
    expect(within(rows[1]).getByText("/data/archives/test")).toBeInTheDocument();
    expect(within(rows[1]).getByText("/TestArchive")).toBeInTheDocument();
    await user.click(within(rows[1]).getByRole("button", { name: /Show archive folder in/ }));
    await waitFor(() => expect(posts(calls, "/api/archives/test/reveal")).toHaveLength(1));
    expect(posts(calls, "/api/archives/test/reveal")[0].body).toEqual({ what: "archive" });
  });

  it("lists an archive's extra folders and shows one in the file manager", async () => {
    const withExtras: Archive = {
      ...TEST,
      extra_folders: [
        { label: "Old years", path: "/Volumes/Disk/Old", attached: true },
        { label: "Scans", path: "/Volumes/Disk/Scans", attached: false },
      ],
    };
    const { user, calls } = renderSwitcher({
      "GET /api/archives": listing([MAIN, withExtras]),
      "POST /api/archives/test/reveal": { status: 204, body: null },
    });
    const dialog = await open(user);
    const rows = await within(dialog).findAllByRole("listitem");
    expect(within(rows[0]).queryByText(/Old years/)).not.toBeInTheDocument();
    expect(within(rows[1]).getByText("/Volumes/Disk/Old")).toBeInTheDocument();
    expect(within(rows[1]).getByText("Archive folder 'Old years'")).toBeInTheDocument();
    expect(within(rows[1]).getByText("Archive folder 'Scans' (detached)")).toBeInTheDocument();
    await user.click(within(rows[1]).getByRole("button", { name: /Show archive folder 'old years' in/ }));
    await waitFor(() => expect(posts(calls, "/api/archives/test/reveal")).toHaveLength(1));
    expect(posts(calls, "/api/archives/test/reveal")[0].body).toEqual({ what: "extra", label: "Old years" });
  });

  it("renames and recolours", async () => {
    const { user, calls } = renderSwitcher({
      "PATCH /api/archives/test": (call) => ({ body: { ...TEST, ...(call.body as object) } }),
    });
    const dialog = await open(user);
    // renamed in place: the pencil opens the field, Enter saves
    await user.click((await within(dialog).findAllByRole("button", { name: "Rename" }))[1]);
    const name = within(dialog).getByLabelText("Name of Test");
    await user.clear(name);
    await user.type(name, "Playground{Enter}");
    await waitFor(() => expect(calls.filter((c) => c.method === "PATCH")).toHaveLength(1));
    expect(calls.find((c) => c.method === "PATCH")?.body).toEqual({ name: "Playground" });
    const swatches = within(dialog).getByRole("group", { name: "Colour of Test" });
    await user.click(within(swatches).getByRole("button", { name: "Teal" }));
    await waitFor(() => expect(calls.filter((c) => c.method === "PATCH")).toHaveLength(2));
    expect(calls.filter((c) => c.method === "PATCH")[1].body).toEqual({ color: "#1f8a8a" });
  });

  it("Esc in the name field keeps the name and the sheet open", async () => {
    const { user, calls } = renderSwitcher({});
    const dialog = await open(user);
    await user.click((await within(dialog).findAllByRole("button", { name: "Rename" }))[1]);
    const name = within(dialog).getByLabelText("Name of Test");
    await user.clear(name);
    await user.type(name, "Scrapped{Escape}");
    expect(within(dialog).queryByLabelText("Name of Test")).not.toBeInTheDocument();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(calls.filter((c) => c.method === "PATCH")).toHaveLength(0);
  });

  it("forgetting explains that nothing is deleted, and then says where the folders are", async () => {
    const { user, calls } = renderSwitcher({
      "POST /api/archives/test/forget": {
        body: { forgotten: TEST, data_dir: "/data/archives/test", archive_root: "/TestArchive" },
      },
    });
    const dialog = await open(user);
    const rows = await within(dialog).findAllByRole("listitem");
    await user.click(within(rows[1]).getByRole("button", { name: "Forget…" }));
    const confirm = within(dialog).getByRole("group", { name: "Forget Test" });
    expect(confirm).toHaveTextContent("Nothing is deleted");
    expect(posts(calls, "/api/archives/test/forget")).toHaveLength(0); // asked first
    await user.click(within(confirm).getByRole("button", { name: "Forget Test" }));
    await waitFor(() => expect(posts(calls, "/api/archives/test/forget")).toHaveLength(1));
    expect(posts(calls, "/api/archives/test/forget")[0].body).toEqual({});
    const note = await within(dialog).findByRole("status");
    expect(note).toHaveTextContent("Nothing was deleted");
    expect(note).toHaveTextContent("/data/archives/test");
    expect(note).toHaveTextContent("/TestArchive");
    expect(leave).not.toHaveBeenCalled(); // it was not the archive in use
  });

  it("forgetting the archive in use needs another to open; the last cannot be forgotten", async () => {
    const { user, calls } = renderSwitcher({
      "POST /api/archives/main/forget": { body: { forgotten: MAIN, data_dir: "/data", archive_root: "/Archive" } },
    });
    const dialog = await open(user);
    const rows = await within(dialog).findAllByRole("listitem");
    await user.click(within(rows[0]).getByRole("button", { name: "Forget…" }));
    const confirm = within(dialog).getByRole("group", { name: "Forget Main" });
    expect(within(confirm).getByLabelText("Open this archive instead")).toHaveValue("test");
    await user.click(within(confirm).getByRole("button", { name: "Forget Main" }));
    await waitFor(() => expect(posts(calls, "/api/archives/main/forget")).toHaveLength(1));
    expect(posts(calls, "/api/archives/main/forget")[0].body).toEqual({ switch_to: "test" });
    await waitFor(() => expect(leave).toHaveBeenCalled());
  });

  it("the only archive has nothing to forget", async () => {
    const { user } = renderSwitcher({ "GET /api/archives": listing([MAIN]) });
    const dialog = await open(user);
    expect(await within(dialog).findByRole("button", { name: "Forget…" })).toBeDisabled();
  });

  it("a server refusal is shown in the row", async () => {
    const { user } = renderSwitcher({
      "POST /api/archives/test/forget": { status: 409, body: { error: "Something is wrong." } },
    });
    const dialog = await open(user);
    const rows = await within(dialog).findAllByRole("listitem");
    await user.click(within(rows[1]).getByRole("button", { name: "Forget…" }));
    await user.click(within(dialog).getByRole("button", { name: "Forget Test" }));
    expect(await within(rows[1]).findByRole("alert")).toHaveTextContent("Something is wrong.");
  });
});

describe("the window shows which archive it is", () => {
  const renderApp = (status: object, archives: { body: unknown } = listing([MAIN, TEST])) => {
    mockFetch({
      "GET /api/status": { body: status },
      "GET /api/archives": archives,
      "GET /api/inbox": { body: [] },
      "GET /api/folders": { body: [] },
      "GET /api/today": {
        body: {
          attention: [],
          overview: { inbox: 0, trays: [], collections: [] },
          unmanaged_ongoing: 0,
          ongoing_sync_failure: null,
          reminders: { last_run: null, errors: {}, skipped: null },
          tray_errors: [],
          inbox_stats: { count: 0, oldest_days: 0, this_week: 0, last_week: 0, older: 0, overdue: 0 },
          found: [],
          open_items: [],
        },
      },
      "GET /api/trays": { body: { trays: [], errors: [] } },
      "GET /api/collections": { body: [] },
    });
    return renderWithProviders(
      <MemoryRouter>
        <App />
      </MemoryRouter>,
    );
  };

  it("another archive gets a colour band and its name in the window title", async () => {
    const { container } = renderApp(
      { ...STATUS, archive: { id: "test", name: "Test", color: "#d9822b" } },
      { body: { archives: [{ ...MAIN, current: false }, { ...TEST, current: true }], current: "test", can_switch: true } },
    );
    await screen.findByRole("button", { name: "Archive: Test" });
    expect(container.querySelector(".archive-band")).not.toBeNull();
    expect(container.querySelector(".app")).toHaveStyle({ "--archive-color": "#d9822b" });
    await waitFor(() => expect(document.title).toBe("Test — Archive"));
    // and every change it asks for names the archive
    expect(getActiveArchive()).toBe("test");
  });

  it("Main has no band; with one archive the title stays plain", async () => {
    const { container } = renderApp({ ...STATUS, profiles_count: 1 });
    await screen.findByRole("button", { name: "Archive: Main" });
    expect(container.querySelector(".archive-band")).toBeNull();
    expect(document.title).toBe("Archive");
  });
});

describe("what a window remembers is kept per archive", () => {
  it("Main keeps the keys older versions used; the others get their own", async () => {
    const { archiveKey } = await import("../api/client");
    expect(archiveKey("dam.today.layout.v1")).toBe("dam.today.layout.v1"); // before the status is known
    setActiveArchive("main");
    expect(archiveKey("dam.today.layout.v1")).toBe("dam.today.layout.v1");
    setActiveArchive("test");
    expect(archiveKey("dam.today.layout.v1")).toBe("dam.today.layout.v1.test");
  });

  it("the sidebar's folded collections of one archive do not fold another's", async () => {
    localStorage.clear();
    localStorage.setItem("dam.sidebar.collections.folded.v1.test", "[7]");
    setActiveArchive("test");
    const parent = { id: 7, name: "Parent", state: "open", parent_id: null, path: ["Parent"], members: [] };
    const child = { id: 8, name: "Child", state: "open", parent_id: 7, path: ["Parent", "Child"], members: [] };
    mockFetch({
      "GET /api/status": { body: STATUS },
      "GET /api/archives": listing([MAIN, TEST]),
      "GET /api/today": { body: { attention: [], overview: { inbox: 0, trays: [], collections: [] } } },
      "GET /api/trays": { body: { trays: [], errors: [] } },
      "GET /api/collections": { body: [parent, child] },
    });
    renderWithProviders(
      <MemoryRouter>
        <Sidebar />
      </MemoryRouter>,
    );
    await screen.findByRole("link", { name: "Parent" });
    expect(screen.queryByRole("link", { name: "Child" })).not.toBeInTheDocument(); // folded in "test"
    localStorage.clear();
  });
});
