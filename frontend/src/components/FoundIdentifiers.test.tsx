import { screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockFetch, renderWithProviders } from "../test-utils";
import { FoundIdentifiers } from "./FoundIdentifiers";

afterEach(() => vi.restoreAllMocks());

const render = () =>
  renderWithProviders(
    <MemoryRouter>
      <FoundIdentifiers driveId="a" />
    </MemoryRouter>,
  );

describe("FoundIdentifiers", () => {
  it("lists what was found, each searchable when other files carry it", async () => {
    mockFetch({
      "GET /api/files/a/identifiers": {
        body: {
          identifiers: [
            { kind: "fi.ytunnus", label: "Business ID (Y-tunnus)", value: "0112038-9", others: 14 },
            { kind: "core.domain", label: "Web or mail domain", value: "a.fi", others: 0 },
          ],
        },
      },
    });
    render();
    expect(await screen.findByRole("heading", { name: "Found in this document" })).toBeInTheDocument();
    expect(screen.getByText("Business ID (Y-tunnus)")).toBeInTheDocument();
    expect(screen.getByText("0112038-9")).toHaveAttribute("title", "0112038-9");
    const link = screen.getByRole("link", { name: "on 14 other files" });
    expect(link).toHaveAttribute("href", "/browse?q=id%3A0112038-9");
    expect(screen.getByText("only here")).toBeInTheDocument();
  });

  it("is left out when nothing was found", async () => {
    const calls = mockFetch({ "GET /api/files/a/identifiers": { body: { identifiers: [] } } });
    render();
    await vi.waitFor(() => expect(calls.length).toBe(1));
    expect(screen.queryByRole("region", { name: "Found in this document" })).toBeNull();
  });
});
