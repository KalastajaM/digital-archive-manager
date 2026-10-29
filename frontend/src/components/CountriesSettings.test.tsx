import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockFetch, renderWithProviders } from "../test-utils";
import { CountriesSettings } from "./CountriesSettings";

const finland = {
  code: "fi",
  name: "Finland",
  enabled: true,
  adds: ["Payment reference (viitenumero)", "Finland example rules"],
  languages: ["fi", "sv"],
};
const langs = [
  { code: "fi", name: "Finnish", enabled: true, always: false },
  { code: "sv", name: "Swedish", enabled: true, always: false },
  { code: "en", name: "English", enabled: true, always: true },
];
const state = { chosen: false, countries: [finland], languages: langs };

afterEach(() => vi.restoreAllMocks());

describe("CountriesSettings", () => {
  it("lists Finland with what it adds, and English always on", async () => {
    mockFetch({ "GET /api/settings/countries": { body: state } });
    renderWithProviders(<CountriesSettings />);
    expect(await screen.findByRole("heading", { name: "Reading documents" })).toBeInTheDocument();
    expect(await screen.findByRole("group", { name: "Where your post comes from" })).toBeInTheDocument();
    expect(screen.getByRole("group", { name: "Languages your documents are written in" })).toBeInTheDocument();
    expect(screen.getByText("always on (dam itself is in English)")).toBeInTheDocument();
    const finlandBox = screen.getByRole("checkbox", { name: /Finland/ });
    expect(finlandBox).toBeChecked();
    expect(screen.getByText("Payment reference (viitenumero)")).toBeInTheDocument();
    expect(screen.getByText("Finland example rules")).toBeInTheDocument();
    const english = screen.getByRole("checkbox", { name: /English/ });
    expect(english).toBeChecked();
    expect(english).toBeDisabled();
    expect(screen.getByRole("button", { name: "Save countries and languages" })).toBeDisabled();
  });

  it("saves the choice and says so", async () => {
    const user = userEvent.setup();
    const calls = mockFetch({
      "GET /api/settings/countries": { body: state },
      "PUT /api/settings/countries": { body: { ...state, chosen: true, countries: [{ ...finland, enabled: false }] } },
    });
    renderWithProviders(<CountriesSettings />);
    await user.click(await screen.findByRole("checkbox", { name: /Finland/ }));
    await user.click(screen.getByRole("checkbox", { name: /Swedish/ }));
    await user.click(screen.getByRole("button", { name: "Save countries and languages" }));
    await waitFor(() => expect(calls.some((c) => c.method === "PUT")).toBe(true));
    const put = calls.find((c) => c.method === "PUT");
    expect(put?.body).toEqual({ countries: [], languages: ["fi", "en"] });
    expect(await screen.findByText("Saved. dam reads your documents with these from now on.")).toBeInTheDocument();
  });

  it("shows why a save failed", async () => {
    const user = userEvent.setup();
    mockFetch({
      "GET /api/settings/countries": { body: state },
      "PUT /api/settings/countries": { status: 400, body: { error: "the setting could not be saved: disk full" } },
    });
    renderWithProviders(<CountriesSettings />);
    await user.click(await screen.findByRole("checkbox", { name: /Swedish/ }));
    await user.click(screen.getByRole("button", { name: "Save countries and languages" }));
    const region = screen.getByRole("region", { name: "Reading documents" });
    expect(await within(region).findByRole("alert")).toHaveTextContent("disk full");
  });
});
