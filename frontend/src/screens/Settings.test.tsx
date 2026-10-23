import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { mockFetch, renderWithProviders } from "../test-utils";
import { APPEARANCE_KEY } from "../appearance";
import Settings from "./Settings";

describe("Settings", () => {
  it("has a heading, the Appearance, Filing codes and Print stickers sections", async () => {
    mockFetch({
      "GET /api/filing-codes": { body: { codes: [], problems: [], warnings: [] } },
      "GET /api/filing-codes/folders": { body: { missing: [], stray: [] } },
      "GET /api/trays": { body: { trays: [], skipped: [] } },
      "GET /api/filing-codes/sheets": { body: [] },
    });
    renderWithProviders(
      <MemoryRouter>
        <Settings />
      </MemoryRouter>,
    );
    expect(screen.getByRole("heading", { name: "Settings" })).toBeInTheDocument();
    const appearance = screen.getByRole("region", { name: "Appearance" });
    expect(within(appearance).getByRole("button", { name: "Auto" })).toHaveAttribute("aria-pressed", "true");
    const section = await screen.findByRole("region", { name: "Filing codes" });
    expect(await within(section).findByRole("button", { name: "Save" })).toBeInTheDocument();
    const print = screen.getByRole("region", { name: "Print stickers" });
    expect(await within(print).findByRole("button", { name: "Open sheet" })).toBeInTheDocument();
  });

  it("Appearance applies the chosen theme at once and keeps it", async () => {
    localStorage.clear();
    mockFetch({
      "GET /api/filing-codes": { body: { codes: [], problems: [], warnings: [] } },
      "GET /api/filing-codes/folders": { body: { missing: [], stray: [] } },
      "GET /api/trays": { body: { trays: [], skipped: [] } },
      "GET /api/filing-codes/sheets": { body: [] },
    });
    renderWithProviders(
      <MemoryRouter>
        <Settings />
      </MemoryRouter>,
    );
    const appearance = screen.getByRole("region", { name: "Appearance" });
    await userEvent.click(within(appearance).getByRole("button", { name: "Dark" }));
    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(within(appearance).getByRole("button", { name: "Dark" })).toHaveAttribute("aria-pressed", "true");
    expect(localStorage.getItem(APPEARANCE_KEY)).toBe("dark");
    await userEvent.click(within(appearance).getByRole("button", { name: "Light" }));
    expect(document.documentElement.dataset.theme).toBe("light");
    localStorage.clear();
  });
});
