import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { RowIcons } from "./RowIcons";

const NONE = { has_note: false, checklist_open: 0, checklist_total: 0, summary: null } as const;

describe("RowIcons", () => {
  it("shows nothing without a note, open to-dos or a summary", () => {
    const { container } = render(<RowIcons item={{ ...NONE, checklist_total: 3 }} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("shows the note icon with a Note tooltip", () => {
    render(<RowIcons item={{ ...NONE, has_note: true }} />);
    expect(screen.getByRole("img", { name: "Note" })).toHaveAttribute("title", "Note");
    expect(screen.queryByRole("img", { name: /to-dos/ })).not.toBeInTheDocument();
  });

  it("shows the open to-do count with an 'x of y' tooltip", () => {
    render(<RowIcons item={{ ...NONE, checklist_open: 2, checklist_total: 5 }} />);
    const icon = screen.getByRole("img", { name: "2 of 5 to-dos open" });
    expect(icon).toHaveAttribute("title", "2 of 5 to-dos open");
    expect(icon).toHaveTextContent("2");
  });

  it("tells an AI summary from a written one", () => {
    const { rerender } = render(<RowIcons item={{ ...NONE, summary: "ai" }} />);
    expect(screen.getByRole("img", { name: "AI summary" })).toHaveAttribute("title", "AI summary");
    rerender(<RowIcons item={{ ...NONE, summary: "written" }} />);
    expect(screen.getByRole("img", { name: "Summary" })).toHaveAttribute("title", "Summary");
  });

  it("lists note, to-dos, summary in that order inside one muted group", () => {
    const { container } = render(
      <RowIcons item={{ has_note: true, checklist_open: 1, checklist_total: 1, summary: "ai" }} />,
    );
    expect(container.querySelector(".row-icons")).not.toBeNull();
    expect(screen.getAllByRole("img").map((e) => e.getAttribute("aria-label"))).toEqual([
      "Note",
      "1 of 1 to-dos open",
      "AI summary",
    ]);
  });
});
