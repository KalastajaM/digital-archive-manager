import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { mockFetch, renderWithProviders } from "../test-utils";
import css from "../styles.css?raw";
import { ExpiredFolderSettings } from "./ExpiredFolderSettings";

const URL = "/api/settings/expired-folder";

describe("ExpiredFolderSettings", () => {
  it("shows Expired, saves a new name", async () => {
    const calls = mockFetch({
      [`GET ${URL}`]: { body: { name: "Expired" } },
      [`PUT ${URL}`]: (call) => ({ body: call.body }),
    });
    renderWithProviders(<ExpiredFolderSettings />);
    const input = await screen.findByRole("textbox", { name: "Folder name" });
    await waitFor(() => expect(input).toHaveValue("Expired"));
    const user = userEvent.setup();
    await user.clear(input);
    await user.type(input, "Vanhentuneet");
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(calls.some((c) => c.method === "PUT" && (c.body as { name: string }).name === "Vanhentuneet")).toBe(true));
    // a short confirmation, until the name is edited again
    const section = screen.getByRole("region", { name: "Expired folder" });
    expect(await within(section).findByRole("status")).toHaveTextContent("Saved");
    await user.type(input, "x");
    expect(within(section).queryByRole("status")).not.toBeInTheDocument();
  });

  it("names the section by its heading, and the input by what it holds", async () => {
    mockFetch({ [`GET ${URL}`]: { body: { name: "Expired" } } });
    renderWithProviders(<ExpiredFolderSettings />);
    const section = await screen.findByRole("region", { name: "Expired folder" });
    expect(section).toHaveAttribute("aria-labelledby", screen.getByRole("heading", { name: "Expired folder" }).id);
    expect(section).not.toHaveAttribute("aria-label");
    expect(screen.getAllByText("Expired folder")).toHaveLength(1);
  });

  it("wraps a long refusal inside its box", () => {
    expect(css).toMatch(/^\.error\s*{[^}]*overflow-wrap:\s*anywhere/m);
  });

  it("shows the server's refusal", async () => {
    mockFetch({
      [`GET ${URL}`]: { body: { name: "Expired" } },
      [`PUT ${URL}`]: { status: 400, body: { error: "A folder name cannot contain a slash." } },
    });
    renderWithProviders(<ExpiredFolderSettings />);
    const input = await screen.findByRole("textbox", { name: "Folder name" });
    await waitFor(() => expect(input).toHaveValue("Expired"));
    const user = userEvent.setup();
    await user.type(input, "/");
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("A folder name cannot contain a slash.");
  });
});
