import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MarkIcons, OmitMark } from "./MarkIcons";

describe("MarkIcons", () => {
  it("shows both marks, or leaves one out where the list is already that mark", () => {
    const { rerender } = render(<MarkIcons marks={["starred", "important"]} />);
    expect(screen.getByRole("img", { name: "Starred" })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Important" })).toBeInTheDocument();
    rerender(<MarkIcons marks={["starred", "important"]} omit="starred" />);
    expect(screen.queryByRole("img", { name: "Starred" })).not.toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Important" })).toBeInTheDocument();
    rerender(
      <OmitMark.Provider value="important">
        <MarkIcons marks={["starred", "important"]} />
      </OmitMark.Provider>,
    );
    expect(screen.getByRole("img", { name: "Starred" })).toBeInTheDocument();
    expect(screen.queryByRole("img", { name: "Important" })).not.toBeInTheDocument();
    rerender(<MarkIcons marks={["starred"]} omit="starred" />);
    expect(document.querySelector(".mark-icons")).toBeNull();
  });
});
