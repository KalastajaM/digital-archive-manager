import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockFetch, renderWithProviders } from "../test-utils";
import { SendersSettings } from "./SendersSettings";

const row = (over: Record<string, unknown> = {}) => ({
  kind: "fi.ytunnus",
  label: "Business ID (Y-tunnus)",
  value: "0112038-9",
  files: 14,
  suggested: "Vesilaitos Oy",
  name: null,
  set_at: null,
  filled: 0,
  ...over,
});

afterEach(() => vi.restoreAllMocks());

describe("SendersSettings", () => {
  it("lists each business ID with its suggested name and file count", async () => {
    mockFetch({
      "GET /api/identifier-names": {
        body: { names: [row(), row({ value: "0201256-6", files: 3, suggested: null, name: "Elisa Oyj", set_at: 1, filled: 2 })] },
      },
    });
    renderWithProviders(<SendersSettings />);
    const first = await screen.findByRole("listitem", { name: "Y-tunnus 0112038-9" });
    expect(within(first).getByRole("textbox", { name: "Name for 0112038-9" })).toHaveValue("Vesilaitos Oy");
    expect(within(first).getByText("14 documents")).toBeInTheDocument();
    expect(within(first).getByRole("button", { name: "Confirm" })).toBeEnabled();
    const second = screen.getByRole("listitem", { name: "Y-tunnus 0201256-6" });
    expect(within(second).getByRole("textbox", { name: "Name for 0201256-6" })).toHaveValue("Elisa Oyj");
    expect(within(second).getByText("Confirmed · From on 2 of 3")).toBeInTheDocument();
    expect(within(second).getByRole("button", { name: "Clear" })).toBeInTheDocument();
    expect(within(second).queryByRole("button", { name: "Confirm" })).toBeNull();
  });

  it("confirms a name, says how many documents changed, and Undo clears it", async () => {
    const user = userEvent.setup();
    const calls = mockFetch({
      "GET /api/identifier-names": { body: { names: [row()] } },
      "PUT /api/identifier-names": { body: { changed: 12 } },
    });
    renderWithProviders(<SendersSettings />);
    const item = await screen.findByRole("listitem", { name: "Y-tunnus 0112038-9" });
    await user.click(within(item).getByRole("button", { name: "Confirm" }));
    await waitFor(() => expect(calls.some((c) => c.method === "PUT")).toBe(true));
    expect(calls.find((c) => c.method === "PUT")?.body).toEqual({ kind: "fi.ytunnus", value: "0112038-9", name: "Vesilaitos Oy" });
    expect(await screen.findByText("Vesilaitos Oy is now From on 12 documents.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Undo" }));
    await waitFor(() => expect(calls.filter((c) => c.method === "PUT")).toHaveLength(2));
    expect(calls.filter((c) => c.method === "PUT")[1].body).toEqual({ kind: "fi.ytunnus", value: "0112038-9", name: null });
  });

  it("an edited name of a confirmed ID is saved, and Undo puts the old one back", async () => {
    const user = userEvent.setup();
    const calls = mockFetch({
      "GET /api/identifier-names": { body: { names: [row({ name: "Vesilaitos Oy", set_at: 1, filled: 14 })] } },
      "PUT /api/identifier-names": { body: { changed: 14 } },
    });
    renderWithProviders(<SendersSettings />);
    const item = await screen.findByRole("listitem", { name: "Y-tunnus 0112038-9" });
    const input = within(item).getByRole("textbox", { name: "Name for 0112038-9" });
    await user.clear(input);
    await user.type(input, "Helsingin Vesi{Enter}");
    await waitFor(() => expect(calls.some((c) => c.method === "PUT")).toBe(true));
    expect(calls.find((c) => c.method === "PUT")?.body).toMatchObject({ name: "Helsingin Vesi" });
    await user.click(await screen.findByRole("button", { name: "Undo" }));
    await waitFor(() => expect(calls.filter((c) => c.method === "PUT")).toHaveLength(2));
    expect(calls.filter((c) => c.method === "PUT")[1].body).toMatchObject({ name: "Vesilaitos Oy" });
  });

  it("Confirm waits for a name when none was read", async () => {
    mockFetch({ "GET /api/identifier-names": { body: { names: [row({ suggested: null })] } } });
    renderWithProviders(<SendersSettings />);
    const item = await screen.findByRole("listitem", { name: "Y-tunnus 0112038-9" });
    expect(within(item).getByRole("textbox", { name: "Name for 0112038-9" })).toHaveValue("");
    expect(within(item).getByRole("button", { name: "Confirm" })).toBeDisabled();
  });

  it("filters by name or ID", async () => {
    const user = userEvent.setup();
    mockFetch({
      "GET /api/identifier-names": { body: { names: [row(), row({ value: "0201256-6", suggested: "Elisa Oyj" })] } },
    });
    renderWithProviders(<SendersSettings />);
    await screen.findByRole("listitem", { name: "Y-tunnus 0112038-9" });
    await user.type(screen.getByRole("searchbox", { name: "Find a sender" }), "elisa");
    expect(screen.queryByRole("listitem", { name: "Y-tunnus 0112038-9" })).toBeNull();
    expect(screen.getByRole("listitem", { name: "Y-tunnus 0201256-6" })).toBeInTheDocument();
  });

  it("says when there is nothing to name yet", async () => {
    mockFetch({ "GET /api/identifier-names": { body: { names: [] } } });
    renderWithProviders(<SendersSettings />);
    expect(await screen.findByText(/No business ID is on two or more documents yet/)).toBeInTheDocument();
  });

  it("shows why a save failed", async () => {
    const user = userEvent.setup();
    mockFetch({
      "GET /api/identifier-names": { body: { names: [row()] } },
      "PUT /api/identifier-names": { status: 400, body: { error: "A sender name is at most 80 characters." } },
    });
    renderWithProviders(<SendersSettings />);
    const item = await screen.findByRole("listitem", { name: "Y-tunnus 0112038-9" });
    await user.click(within(item).getByRole("button", { name: "Confirm" }));
    expect(await within(item).findByRole("alert")).toHaveTextContent("at most 80 characters");
  });
});
