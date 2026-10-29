import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockFetch, renderWithProviders } from "../test-utils";
import { AddressAreaSettings } from "./AddressAreaSettings";

const PEOPLE = {
  people: [{ name: "Tiina", match: ["Tiina Visser"] }],
  address_zone: [0.06, 0.1, 0.52, 0.3],
  default_address_zone: [0.05, 0.12, 0.5, 0.28],
  address_zone_set: true,
};

afterEach(() => vi.restoreAllMocks());

const region = () => screen.findByRole("region", { name: "Address area" });

describe("AddressAreaSettings", () => {
  it("saves a changed area with the people as they are", async () => {
    const user = userEvent.setup();
    const calls = mockFetch({ "GET /api/settings/people": { body: PEOPLE }, "PUT /api/settings/people": { body: PEOPLE } });
    renderWithProviders(<AddressAreaSettings />);
    const area = await region();
    expect(within(area).getByLabelText("Left")).toHaveValue(6);
    expect(within(area).getByText(/Set by you\./)).toBeInTheDocument();
    expect(within(area).getByRole("button", { name: "Save address area" })).toBeDisabled();
    await user.clear(within(area).getByLabelText("Right"));
    await user.type(within(area).getByLabelText("Right"), "60");
    await user.click(within(area).getByRole("button", { name: "Save address area" }));
    await waitFor(() => expect(calls.some((c) => c.method === "PUT")).toBe(true));
    expect(calls.find((c) => c.method === "PUT")?.body).toEqual({ people: PEOPLE.people, address_zone: [0.06, 0.1, 0.6, 0.3] });
    expect(await within(area).findByText("Saved.")).toBeInTheDocument();
  });

  it("goes back to the countries' area by taking the owner's out", async () => {
    const user = userEvent.setup();
    const calls = mockFetch({ "GET /api/settings/people": { body: PEOPLE }, "PUT /api/settings/people": { body: PEOPLE } });
    renderWithProviders(<AddressAreaSettings />);
    const area = await region();
    await user.click(within(area).getByRole("button", { name: "Reset to default" }));
    expect(within(area).getByLabelText("Left")).toHaveValue(5);
    expect(within(area).getByText(/Follows the countries above\./)).toBeInTheDocument();
    await user.click(within(area).getByRole("button", { name: "Save address area" }));
    await waitFor(() => expect(calls.some((c) => c.method === "PUT")).toBe(true));
    expect(calls.find((c) => c.method === "PUT")?.body).toEqual({ people: PEOPLE.people, address_zone: null });
  });

  it("says when the area follows the countries", async () => {
    mockFetch({ "GET /api/settings/people": { body: { ...PEOPLE, address_zone_set: false } } });
    renderWithProviders(<AddressAreaSettings />);
    const area = await region();
    expect(within(area).getByText(/Follows the countries above\./)).toBeInTheDocument();
  });
});
