import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { mockFetch, renderWithProviders } from "../test-utils";
import { FolderPathInput } from "./FolderPathInput";

function Field({ initial = "" }: { initial?: string }) {
  const [path, setPath] = useState(initial);
  return (
    <>
      <label htmlFor="p">Folder path</label>
      <FolderPathInput id="p" value={path} onChange={setPath} />
    </>
  );
}
const URL = "POST /api/system/choose-folder";

beforeEach(() => {
});
afterEach(() => {
});

describe("FolderPathInput", () => {

  it("fills the field with the chosen folder and opens the dialog where the field points", async () => {
    const user = userEvent.setup();
    const calls = mockFetch({ [URL]: { body: { path: "/Users/me/Drive/Archive", cancelled: false, unavailable: null } } });
    renderWithProviders(<Field initial="/Users/me/Drive" />);
    await user.click(screen.getByRole("button", { name: "Choose…" }));
    await waitFor(() => expect(screen.getByLabelText("Folder path")).toHaveValue("/Users/me/Drive/Archive"));
    expect(calls.find((c) => c.url === "/api/system/choose-folder")?.body).toEqual({ start: "/Users/me/Drive" });
  });

  it("sends no start folder for an empty field and keeps typing working", async () => {
    const user = userEvent.setup();
    const calls = mockFetch({ [URL]: { body: { path: null, cancelled: true, unavailable: null } } });
    renderWithProviders(<Field />);
    await user.type(screen.getByLabelText("Folder path"), "/a");
    await user.clear(screen.getByLabelText("Folder path"));
    await user.click(screen.getByRole("button", { name: "Choose…" }));
    await waitFor(() => expect(calls.filter((c) => c.url === "/api/system/choose-folder")).toHaveLength(1));
    expect(calls.find((c) => c.url === "/api/system/choose-folder")?.body).toEqual({});
    await user.type(screen.getByLabelText("Folder path"), "/typed");
    expect(screen.getByLabelText("Folder path")).toHaveValue("/typed");
  });

  it("leaves the field alone when the dialog is cancelled", async () => {
    const user = userEvent.setup();
    mockFetch({ [URL]: { body: { path: null, cancelled: true, unavailable: null } } });
    renderWithProviders(<Field initial="/keep" />);
    await user.click(screen.getByRole("button", { name: "Choose…" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Choose…" })).toBeEnabled());
    expect(screen.getByLabelText("Folder path")).toHaveValue("/keep");
    expect(document.querySelector(".path-message")).toBeNull();
  });

  it("is disabled and says Choosing… while the dialog is open", async () => {
    const user = userEvent.setup();
    let release: () => void = () => {};
    const gate = new Promise<void>((r) => (release = r));
    mockFetch({
      [URL]: async () => {
        await gate;
        return { body: { path: "/x", cancelled: false, unavailable: null } };
      },
    });
    renderWithProviders(<Field />);
    await user.click(screen.getByRole("button", { name: "Choose…" }));
    expect(await screen.findByRole("button", { name: "Choosing…" })).toBeDisabled();
    release();
    await waitFor(() => expect(screen.getByLabelText("Folder path")).toHaveValue("/x"));
    expect(screen.getByRole("button", { name: "Choose…" })).toBeEnabled();
  });

  it("shows the plain message when no dialog is available", async () => {
    const user = userEvent.setup();
    mockFetch({ [URL]: { body: { path: null, cancelled: false, unavailable: "No desktop session. Type the path instead." } } });
    renderWithProviders(<Field initial="/keep" />);
    await user.click(screen.getByRole("button", { name: "Choose…" }));
    expect(await screen.findByText("No desktop session. Type the path instead.")).toBeInTheDocument();
    expect(screen.getByLabelText("Folder path")).toHaveValue("/keep");
  });

  it("tells the user to type the path when the request fails", async () => {
    const user = userEvent.setup();
    mockFetch({ [URL]: { status: 500, body: { error: "Something broke." } } });
    renderWithProviders(<Field />);
    await user.click(screen.getByRole("button", { name: "Choose…" }));
    expect(await screen.findByText(/Type the path instead/)).toBeInTheDocument();
  });
});
