/** Relatives sit in the file panel in the New look only (Classic is unchanged), between
 * the file's own blocks and its preview, and not for a file marked for deletion. */
import { cleanup, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it } from "vitest";
import { mockFetch, renderWithProviders } from "../test-utils";
import { FilePanel } from "./FilePanel";

const PATH = "13. Taxes/a.pdf";
const file = (path = PATH) => ({ drive_id: "d1", path, name: "a.pdf", is_dir: false, is_link: false, marks: [] });

function setup(path = PATH) {
  const calls = mockFetch({
    "GET /api/files/d1/relatives": { body: { drive_id: "d1", relatives: [], common: [], total: 0, hidden: 0 } },
  });
  renderWithProviders(
    <MemoryRouter>
      <FilePanel file={file(path)} preview={{ drive_id: "d1", path, ext: "pdf" }} />
    </MemoryRouter>,
  );
  return calls;
}

afterEach(() => {
  cleanup();
  delete document.documentElement.dataset.style;
});

describe("the file panel and Relatives", () => {
  it("shows the block in the New look, after the own blocks and before the preview", async () => {
    document.documentElement.dataset.style = "new";
    const calls = setup();
    expect(await screen.findByRole("heading", { name: "Relatives" })).toBeInTheDocument();
    const blocks = [...document.querySelectorAll("[data-block]")].map((b) => b.getAttribute("data-block"));
    expect(blocks.indexOf("relatives")).toBeGreaterThan(blocks.indexOf("collections"));
    expect(blocks.indexOf("relatives")).toBeLessThan(blocks.indexOf("preview"));
    expect(calls.some((c) => c.url === "/api/files/d1/relatives")).toBe(true);
  });

  it("shows nothing and asks nothing in Classic", async () => {
    const calls = setup();
    await screen.findByText("a.pdf");
    expect(screen.queryByRole("heading", { name: "Relatives" })).toBeNull();
    expect(document.querySelector('[data-block="relatives"]')).toBeNull();
    expect(calls.some((c) => c.url.includes("/relatives"))).toBe(false);
  });

  it("is left out for a file marked for deletion", async () => {
    document.documentElement.dataset.style = "new";
    const calls = setup("##. To Delete/a.pdf");
    await screen.findByText("a.pdf");
    expect(screen.queryByRole("heading", { name: "Relatives" })).toBeNull();
    expect(calls.some((c) => c.url.includes("/relatives"))).toBe(false);
  });
});
