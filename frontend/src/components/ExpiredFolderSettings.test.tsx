import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { mockFetch, renderWithProviders } from "../test-utils";
import { ExpiredFolderSettings } from "./ExpiredFolderSettings";

const URL = "/api/settings/expired-folder";

describe("ExpiredFolderSettings", () => {
  it("shows Expired, saves a new name", async () => {
    const calls = mockFetch({
      [`GET ${URL}`]: { body: { name: "Expired" } },
      [`PUT ${URL}`]: (call) => ({ body: call.body }),
    });
    renderWithProviders(<ExpiredFolderSettings />);
    const input = await screen.findByRole("textbox", { name: "Expired folder" });
    await waitFor(() => expect(input).toHaveValue("Expired"));
    const user = userEvent.setup();
    await user.clear(input);
    await user.type(input, "Vanhentuneet");
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(calls.some((c) => c.method === "PUT" && (c.body as { name: string }).name === "Vanhentuneet")).toBe(true));
  });

  it("shows the server's refusal", async () => {
    mockFetch({
      [`GET ${URL}`]: { body: { name: "Expired" } },
      [`PUT ${URL}`]: { status: 400, body: { error: "A folder name cannot contain a slash." } },
    });
    renderWithProviders(<ExpiredFolderSettings />);
    const input = await screen.findByRole("textbox", { name: "Expired folder" });
    await waitFor(() => expect(input).toHaveValue("Expired"));
    const user = userEvent.setup();
    await user.type(input, "/");
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("A folder name cannot contain a slash.");
  });
});
