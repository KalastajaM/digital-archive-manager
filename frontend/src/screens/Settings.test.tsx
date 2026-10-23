import { screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { mockFetch, renderWithProviders } from "../test-utils";
import Settings from "./Settings";

describe("Settings", () => {
  it("has a heading and the Filing codes section", async () => {
    mockFetch({
      "GET /api/filing-codes": { body: { codes: [], problems: [], warnings: [] } },
      "GET /api/filing-codes/folders": { body: { missing: [], stray: [] } },
      "GET /api/trays": { body: { trays: [], skipped: [] } },
    });
    renderWithProviders(
      <MemoryRouter>
        <Settings />
      </MemoryRouter>,
    );
    expect(screen.getByRole("heading", { name: "Settings" })).toBeInTheDocument();
    const section = await screen.findByRole("region", { name: "Filing codes" });
    expect(await within(section).findByRole("button", { name: "Save" })).toBeInTheDocument();
  });
});
