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
    const finlandBox = await screen.findByRole("checkbox", { name: /Finland/ });
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
    expect(await screen.findByText("Countries and languages saved.")).toBeInTheDocument();
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
    const region = screen.getByRole("region", { name: "Countries and languages" });
    expect(await within(region).findByRole("alert")).toHaveTextContent("disk full");
  });
});
