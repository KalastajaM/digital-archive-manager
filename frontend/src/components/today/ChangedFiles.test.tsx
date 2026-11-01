/** The line a changed file has in its panel, and how a change reads. */
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { type ContentChange, SEARCH_STALE } from "../../api/client";
import { mockFetch, renderWithProviders } from "../../test-utils";
import { ChangedNotice, changeLine } from "./ChangedFiles";

const CHANGE: ContentChange = {
  drive_id: "a",
  path: "10. Home/Lease.docx",
  name: "Lease.docx",
  was_size: 2048,
  was_mtime: 1_760_000_000,
  size: 4096,
  mtime: Date.UTC(2020, 2, 5, 12) / 1000,
  detected_at: 1_761_000_100,
};

describe("changeLine", () => {
  it("gives the date and both sizes, or that the size is the same", () => {
    expect(changeLine(CHANGE)).toBe("5 Mar 2020, was 2,0 KB, now 4,0 KB");
    expect(changeLine({ ...CHANGE, size: 2048 })).toBe("5 Mar 2020, same size");
    expect(changeLine({ ...CHANGE, size: null })).toBe("5 Mar 2020");
  });
});

describe("ChangedNotice", () => {
  it("shows nothing for a file with no notice", async () => {
    const calls = mockFetch({ "GET /api/files/a": { body: { content_change: null } } });
    renderWithProviders(<ChangedNotice driveId="a" />);
    await waitFor(() => expect(calls.length).toBeGreaterThan(0));
    expect(screen.queryByText(/Content changed/)).not.toBeInTheDocument();
  });

  it("says what changed and marks it as seen", async () => {
    const calls = mockFetch({
      "GET /api/files/a": { body: { content_change: CHANGE } },
      "POST /api/content-changes/seen": { body: { drive_ids: ["a"] } },
    });
    const stale = vi.fn();
    window.addEventListener(SEARCH_STALE, stale);
    renderWithProviders(<ChangedNotice driveId="a" />);
    expect(await screen.findByText(/Content changed: 5 Mar 2020, was 2,0 KB, now 4,0 KB/)).toBeInTheDocument();
    await userEvent.setup().click(screen.getByRole("button", { name: "Mark as seen" }));
    await waitFor(() => expect(calls.find((c) => c.method === "POST")?.body).toEqual({ drive_ids: ["a"] }));
    await waitFor(() => expect(stale).toHaveBeenCalled()); // an is:changed search on screen follows
    window.removeEventListener(SEARCH_STALE, stale);
  });
});
