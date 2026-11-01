/** The one file panel skeleton: its blocks come in one order, a block left empty
 * is not drawn, and the file view keeps its own order. */
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { QueryClientProvider, QueryClient } from "@tanstack/react-query";
import { FILE_VIEW_BLOCKS, FileView, SKELETON_BLOCKS } from "./FileView";
import { FilePanelSkeleton, StaticFileHead } from "./FilePanelSkeleton";
import { mockFetch } from "../test-utils";

const FILLED = Object.fromEntries(SKELETON_BLOCKS.map((b) => [b, <p key={b}>{b}</p>]));
const blocks = (root: HTMLElement) => [...root.querySelectorAll(":scope > [data-block]")].map((b) => (b as HTMLElement).dataset.block);

describe("FilePanelSkeleton", () => {
  it("draws the blocks top to bottom: header, icon rows, the screen's own section, tags, collections, group, summary, own, relatives, preview, notes", () => {
    const { container } = render(<FilePanelSkeleton {...FILLED} />);
    expect(blocks(container.firstElementChild as HTMLElement)).toEqual([
      "header",
      "actions",
      "top",
      "tags",
      "collections",
      "group",
      "summary",
      "own",
      "versions",
      "relatives",
      "preview",
      "notes",
    ]);
    expect(container.firstElementChild).toHaveClass("file-panel", "file-skeleton");
  });

  it("does not draw a block that is left out", () => {
    const { container } = render(<FilePanelSkeleton header={<p>h</p>} actions={<p>a</p>} notes={null} preview={false} />);
    expect(blocks(container.firstElementChild as HTMLElement)).toEqual(["header", "actions"]);
  });

  it("the file view keeps its order and ignores the skeleton's extra blocks", () => {
    const { container } = render(<FileView {...FILLED} />);
    expect(blocks(container.firstElementChild as HTMLElement)).toEqual([...FILE_VIEW_BLOCKS]);
  });
});

describe("StaticFileHead", () => {
  it("shows the name, where the file is now, and nothing to edit", () => {
    mockFetch({ "GET /api/locks": { body: { files: [], folders: [] } } });
    render(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter>
          <StaticFileHead driveId="d1" name="scan001.pdf" folder="##. Organize" path="##. Organize/scan001.pdf" />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    expect(screen.getByRole("heading", { name: "scan001.pdf" })).toHaveAttribute("title", "scan001.pdf");
    expect(screen.getByText("##. Organize")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Rename/ })).toBeNull();
  });
});
