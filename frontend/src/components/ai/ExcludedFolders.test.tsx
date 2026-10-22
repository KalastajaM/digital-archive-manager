import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import type { AIStatus } from "../../api/client";
import { type Call, mockFetch, renderWithProviders } from "../../test-utils";
import { ExcludedFolders } from "./ExcludedFolders";
import { STATUS_ON } from "./testData";

const STATUS: AIStatus = { ...STATUS_ON, exclude_folders: ["50. Medical", "70. Work"], exclude_missing: ["70. Work"] };
const puts = (calls: Call[]) => calls.filter((c) => c.method === "PUT" && c.url === "/api/ai/exclude-folders");

function setup(reply: (call: Call) => { status?: number; body: unknown } = (c) => ({ body: { ...STATUS, exclude_folders: (c.body as { folders: string[] }).folders } })) {
  const calls = mockFetch({
    "GET /api/folders": { body: ["10. Financial", "10. Financial/Banks", "50. Medical", "70. Work"] },
    "PUT /api/ai/exclude-folders": reply,
  });
  renderWithProviders(<ExcludedFolders status={STATUS} />);
  return { calls, user: userEvent.setup(), section: screen.getByRole("region", { name: "Excluded folders" }) };
}

describe("Excluded folders (Activity → AI)", () => {
  it("lists the folders, saying which are not in the archive", () => {
    const { section } = setup();
    const items = within(section).getAllByRole("listitem");
    expect(items.map((li) => li.querySelector("code")?.textContent)).toEqual(["50. Medical", "70. Work"]);
    expect(items[0]).not.toHaveTextContent("not in the archive");
    expect(items[1]).toHaveTextContent("not in the archive");
  });

  it("adding a folder saves the whole list at once, with no confirm", async () => {
    const { calls, user, section } = setup();
    const field = within(section).getByRole("combobox", { name: "Exclude a folder" });
    await user.type(field, "10. Financial/Banks");
    await user.click(within(section).getByRole("button", { name: "Exclude" }));
    await waitFor(() => expect(puts(calls)).toHaveLength(1));
    expect(puts(calls)[0].body).toEqual({ folders: ["50. Medical", "70. Work", "10. Financial/Banks"] });
    expect(screen.queryByRole("dialog")).toBeNull();
    await waitFor(() => expect(field).toHaveValue(""));
  });

  it("removing one asks first (its documents can then be sent); Cancel saves nothing", async () => {
    const { calls, user, section } = setup();
    await user.click(within(section).getByRole("button", { name: "Stop excluding 50. Medical" }));
    let dialog = await screen.findByRole("dialog", { name: "Stop excluding 50. Medical?" });
    expect(dialog).toHaveTextContent("can then be sent to AI");
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(puts(calls)).toHaveLength(0);

    await user.click(within(section).getByRole("button", { name: "Stop excluding 50. Medical" }));
    dialog = await screen.findByRole("dialog", { name: "Stop excluding 50. Medical?" });
    await user.click(within(dialog).getByRole("button", { name: "Stop excluding" }));
    await waitFor(() => expect(puts(calls)).toHaveLength(1));
    expect(puts(calls)[0].body).toEqual({ folders: ["70. Work"] });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("a refused save is shown and the field keeps what was typed", async () => {
    const { user, section } = setup(() => ({ status: 400, body: { error: "'../x' is not a folder in the archive" } }));
    const field = within(section).getByRole("combobox", { name: "Exclude a folder" });
    await user.type(field, "../x");
    await user.click(within(section).getByRole("button", { name: "Exclude" }));
    expect(await within(section).findByRole("alert")).toHaveTextContent("is not a folder in the archive");
    expect(field).toHaveValue("../x");
  });
});
