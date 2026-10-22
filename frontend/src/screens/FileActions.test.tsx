/** The Browse file panel has the selected file's summary box (spec §3). */
import { screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { STATUS_ON } from "../components/ai/testData";
import { mockFetch, renderWithProviders } from "../test-utils";
import { FileActions } from "./FileActions";

afterEach(() => vi.unstubAllGlobals());

describe("FileActions", () => {
  it("shows the file's summary with Summarize with AI", async () => {
    mockFetch({
      "GET /api/ai/status": { body: STATUS_ON },
      "GET /api/files/d7/summary": {
        body: { ai: { summary: "Home insurance policy", key_facts: ["312 €"], outdated: false }, user: null },
      },
      "GET /api/notes/file/d7": { body: { text: "" } },
    });
    renderWithProviders(
      <MemoryRouter>
        <FileActions driveId="d7" />
      </MemoryRouter>,
    );
    const box = await screen.findByRole("region", { name: "Summary" });
    expect(await within(box).findByText("Home insurance policy")).toBeInTheDocument();
    expect(within(box).getByRole("list", { name: "Key facts" })).toHaveTextContent("312 €");
    expect(await within(box).findByRole("button", { name: "Summarize with AI…" })).toBeInTheDocument();
  });
});
