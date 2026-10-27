import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { HowDamWorks } from "./HowDamWorks";

describe("HowDamWorks", () => {
  it("draws the diagrams as figures with text for a screen reader", () => {
    const { container } = render(<HowDamWorks />);
    expect(screen.getAllByRole("figure").length).toBeGreaterThanOrEqual(5);
    for (const figure of screen.getAllByRole("figure")) {
      expect(figure.querySelector("svg")).not.toBeNull();
    }
    expect(container.querySelector(".hdw")).not.toBeNull();
  });

  it("gives each instance its own arrowhead ids, so two on one page do not clash", () => {
    const { container } = render(
      <>
        <HowDamWorks />
        <HowDamWorks />
      </>,
    );
    const ids = Array.from(container.querySelectorAll("marker")).map((m) => m.id);
    expect(ids.length).toBeGreaterThan(0);
    expect(new Set(ids).size).toBe(ids.length);
  });
});
