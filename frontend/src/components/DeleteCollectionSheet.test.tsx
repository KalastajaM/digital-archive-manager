/** Delete…: the sheet lists what goes and says plainly that it cannot be undone. */
import { cleanup, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockFetch, renderWithProviders } from "../test-utils";
import { DeleteCollectionSheet } from "./DeleteCollectionSheet";

afterEach(cleanup);

describe("DeleteCollectionSheet", () => {
  it("lists every collection that goes, says it cannot be undone, and deletes on a click", async () => {
    const calls = mockFetch({
      "GET /api/collections/1/delete/preview": {
        body: {
          collections: [
            { id: 1, name: "Legal", state: "open", files: 2 },
            { id: 2, name: "Michiel", state: "open", files: 1 },
            { id: 3, name: "Old", state: "closed", files: 0 },
          ],
        },
      },
      "POST /api/collections/1/delete": { body: { deleted: 3, batch: null, problems: ["Legal/notes.txt is yours, so the folder Legal stays"] } },
    });
    const onDone = vi.fn();
    renderWithProviders(<DeleteCollectionSheet c={{ id: 1, name: "Legal" }} onDone={onDone} onCancel={() => {}} />);
    const sheet = await screen.findByRole("dialog", { name: "Delete Legal?" });
    const rows = await within(sheet).findAllByRole("listitem");
    expect(rows.map((r) => r.textContent)).toEqual(["Legal:\u00a02 files", "Michiel:\u00a01 file", "Old\u00a0(closed):\u00a0no files"]);
    expect(within(sheet).getByText(/This cannot be undone/)).toBeInTheDocument();
    expect(within(sheet).getByText(/Your files are not deleted/)).toBeInTheDocument();
    expect(within(sheet).getByText(/A snapshot is taken first/)).toBeInTheDocument();
    await userEvent.setup().click(within(sheet).getByRole("button", { name: "Delete 3 collections" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.url === "/api/collections/1/delete")).toBe(true));
    // the ones it listed, so a collection made inside since is not deleted unseen
    expect(calls.find((c) => c.url === "/api/collections/1/delete")!.body).toEqual({ ids: [1, 2, 3] });
    // every name that went, so Browse can leave a search on any of them
    expect(onDone).toHaveBeenCalledWith(3, ["Legal", "Michiel", "Old"]);
    // the toast says what went, and what the Ongoing sync could not do
    expect(await screen.findByText("Deleted Legal and the 2 inside it, but: Legal/notes.txt is yours, so the folder Legal stays")).toBeInTheDocument();
  });
});
