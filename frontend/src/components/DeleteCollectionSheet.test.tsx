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
      "POST /api/collections/1/delete": { body: { deleted: 3, batch: null, problems: [] } },
    });
    const onDone = vi.fn();
    renderWithProviders(<DeleteCollectionSheet c={{ id: 1, name: "Legal" }} onDone={onDone} onCancel={() => {}} />);
    const sheet = await screen.findByRole("dialog", { name: "Delete Legal?" });
    const rows = await within(sheet).findAllByRole("listitem");
    expect(rows.map((r) => r.textContent)).toEqual(["Legal: 2 files", "Michiel: 1 file", "Old (closed): no files"]);
    expect(within(sheet).getByText(/This cannot be undone/)).toBeInTheDocument();
    expect(within(sheet).getByText(/Your files are not deleted/)).toBeInTheDocument();
    expect(within(sheet).getByText(/A snapshot is taken first/)).toBeInTheDocument();
    await userEvent.setup().click(within(sheet).getByRole("button", { name: "Delete 3 collections" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.url === "/api/collections/1/delete")).toBe(true));
    // every name that went, so Browse can leave a search on any of them
    expect(onDone).toHaveBeenCalledWith(3, ["Legal", "Michiel", "Old"]);
  });
});
