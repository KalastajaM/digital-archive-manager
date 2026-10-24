import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it } from "vitest";
import { APPEARANCE_KEY } from "../appearance";
import { forgetKeptEdits } from "../components/codes/FilingCodes";
import { mockFetch, renderWithProviders } from "../test-utils";
import Settings from "./Settings";

function setup(path: string) {
  mockFetch({
    "GET /api/filing-codes": { body: { codes: [], problems: [], warnings: [] } },
    "GET /api/filing-codes/folders": { body: { missing: [], stray: [] } },
    "GET /api/trays": { body: { trays: [], skipped: [] } },
    "GET /api/archives": { body: { archives: [{ id: "main", name: "Home", color: "#3b6fd4", current: true }], can_switch: true } },
  });
  renderWithProviders(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/settings/:section?" element={<Settings />} />
      </Routes>
    </MemoryRouter>,
  );
  return userEvent.setup();
}

beforeEach(() => {
  forgetKeptEdits();
  localStorage.clear();
});

describe("Settings", () => {
  it("opens Filing codes first, with the sections listed by what they apply to", async () => {
    setup("/settings");
    expect(screen.getByRole("heading", { name: "Settings" })).toBeInTheDocument();
    expect(await screen.findByRole("region", { name: "Filing codes" })).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Appearance" })).toBeNull(); // one section at a time
    const nav = screen.getByRole("navigation", { name: "Settings sections" });
    expect(await within(nav).findByRole("heading", { name: "This archive · Home" })).toBeInTheDocument();
    expect(within(nav).getByRole("heading", { name: "This browser" })).toBeInTheDocument();
    expect(within(nav).getByRole("link", { name: "Filing codes" })).toHaveAttribute("aria-current", "page");
    expect(within(nav).getAllByRole("link").map((l) => l.getAttribute("href"))).toEqual(["/settings/filing-codes", "/settings/filing-rules", "/settings/appearance"]);
  });

  it("an unknown section opens the first", async () => {
    setup("/settings/nonsense");
    expect(await screen.findByRole("region", { name: "Filing codes" })).toBeInTheDocument();
  });

  it("Appearance applies the chosen theme at once and keeps it", async () => {
    const user = setup("/settings/appearance");
    const appearance = await screen.findByRole("region", { name: "Appearance" });
    expect(within(appearance).getByRole("button", { name: "Auto" })).toHaveAttribute("aria-pressed", "true");
    await user.click(within(appearance).getByRole("button", { name: "Dark" }));
    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(within(appearance).getByRole("button", { name: "Dark" })).toHaveAttribute("aria-pressed", "true");
    expect(localStorage.getItem(APPEARANCE_KEY)).toBe("dark");
    await user.click(within(appearance).getByRole("button", { name: "Light" }));
    expect(document.documentElement.dataset.theme).toBe("light");
  });
});
