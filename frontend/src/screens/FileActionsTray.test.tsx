/** "Put in tray" on the Browse file panel: a pull-down of the trays, one pick files it. */
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Item } from "../api/client";
import { mockFetch, renderWithProviders } from "../test-utils";
import { FileActions } from "./FileActions";

afterEach(() => vi.unstubAllGlobals());

const TRAYS = [
  { id: "to-pay", name: "To pay", order: 1, item_title: "{name}" },
  { id: "to-read", name: "To read", order: 2, item_title: "{name}" },
];
const ITEM = { id: 42, tray_id: "to-pay", tray_name: "To pay", title: "Gas bill", state: "open" } as unknown as Item;

function setup(items: Item[] = []) {
  const calls = mockFetch({
    "GET /api/trays": { body: { trays: TRAYS, errors: [] } },
    "GET /api/files/d7/links": { body: { items, collections: [], note: "" } },
    "GET /api/notes/file/d7": { body: { text: "" } },
    "GET /api/ai/status": { body: { enabled: false } },
    "POST /api/items/quick": { body: { created: [{ ...ITEM, id: 50, tray_id: "to-read", tray_name: "To read" }], skipped: [] } },
    "POST /api/items/42/discard": { status: 204, body: null },
  });
  renderWithProviders(
    <MemoryRouter>
      <FileActions driveId="d7" />
    </MemoryRouter>,
  );
  return { calls, user: userEvent.setup() };
}

describe("Put in tray menu", () => {
  it("lists the trays; choosing one puts the file in it at once", async () => {
    const { calls, user } = setup();
    await user.click(await screen.findByRole("button", { name: "Put in tray" }));
    const menu = await screen.findByRole("menu", { name: "Put in tray" });
    expect(menu).toBeInTheDocument();
    await screen.findByRole("menuitemcheckbox", { name: "To read" });
    expect(screen.getByRole("menuitemcheckbox", { name: "To pay" })).toHaveAttribute("aria-checked", "false");
    await user.click(screen.getByRole("menuitemcheckbox", { name: "To read" }));
    await waitFor(() => expect(calls.filter((c) => c.url === "/api/items/quick")).toHaveLength(1));
    expect(calls.find((c) => c.url === "/api/items/quick")!.body).toEqual({ tray: "to-read", drive_ids: ["d7"] });
    expect(await screen.findByText(/Put in To read/)).toBeInTheDocument();
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });

  it("checks the tray the file is in and offers Remove from tray", async () => {
    const { calls, user } = setup([ITEM]);
    await user.click(await screen.findByRole("button", { name: "Put in tray" }));
    await waitFor(() => expect(screen.getByRole("menuitemcheckbox", { name: "To pay" })).toHaveAttribute("aria-checked", "true"));
    await user.click(screen.getByRole("menuitem", { name: "Remove from To pay" }));
    await waitFor(() => expect(calls.filter((c) => c.url === "/api/items/42/discard")).toHaveLength(1));
  });

  it("works from the keyboard: arrows move, Esc closes and keeps the focus on the button", async () => {
    const { user } = setup();
    const button = await screen.findByRole("button", { name: "Put in tray" });
    await user.click(button);
    const first = await screen.findByRole("menuitemcheckbox", { name: "To pay" });
    await waitFor(() => expect(first).toHaveFocus());
    await user.keyboard("{ArrowDown}");
    expect(screen.getByRole("menuitemcheckbox", { name: "To read" })).toHaveFocus();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    expect(button).toHaveFocus();
  });
});
