import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { Area } from "../../api/client";
import { AreaLayer, changedBox } from "./AreaLayer";

const area = (over: Partial<Area> = {}): Area => ({
  rule_id: "pohjola", index: 0, box: [0.1, 0.1, 0.5, 0.3], kind: "text", lines: [], score: null, matched: true, reason: null, wins: true, document: false, ...over,
});

/** A 200 x 400 page with the areas drawn on it. */
function setup(onChange?: (a: Area, box: number[]) => void, areas: Area[] = [area()]) {
  const view = render(
    <span className="page-layer" data-testid="layer">
      <AreaLayer areas={areas} onChange={onChange} />
    </span>,
  );
  const layer = screen.getByTestId("layer");
  layer.getBoundingClientRect = () => ({ left: 0, top: 0, width: 200, height: 400, right: 200, bottom: 400, x: 0, y: 0 }) as DOMRect;
  const el = () => document.querySelector('[data-area="pohjola:0"]') as HTMLElement;
  return { ...view, el };
}

describe("changedBox", () => {
  it("moves a box and keeps it on the page", () => {
    expect(changedBox([0.1, 0.1, 0.5, 0.3], "move", 0.1, 0.2).map((v) => Math.round(v * 1000) / 1000)).toEqual([0.2, 0.3, 0.6, 0.5]);
    const far = changedBox([0.1, 0.1, 0.5, 0.3], "move", 2, -2);
    expect(far[0]).toBeCloseTo(0.6);
    expect(far[2]).toBeCloseTo(1);
    expect(far[1]).toBeCloseTo(0);
    expect(far[3]).toBeCloseTo(0.2);
  });

  it("resizes by the handle's edges and keeps both sides at least a hundredth of the page", () => {
    expect(changedBox([0.1, 0.1, 0.5, 0.3], "se", 0.1, 0.1)).toEqual([0.1, 0.1, 0.6, 0.4]);
    expect(changedBox([0.1, 0.1, 0.5, 0.3], "w", -0.05, 0.3)).toEqual([0.05, 0.1, 0.5, 0.3]);
    const squeezed = changedBox([0.1, 0.1, 0.5, 0.3], "e", -1, 0);
    expect(squeezed[2]).toBeCloseTo(0.11);
    const top = changedBox([0.1, 0.1, 0.5, 0.3], "n", 1, 1);
    expect(top[1]).toBeCloseTo(0.29);
    expect(top[0]).toBe(0.1);
  });
});

describe("AreaLayer picture areas", () => {
  it("names a picture with its score and draws where it fits best", () => {
    setup(undefined, [area({ kind: "image", score: 0.934, lines: [[0.12, 0.12, 0.45, 0.25]] })]);
    expect(screen.getByTitle("pohjola: picture 0.93")).toHaveAttribute("data-kind", "image");
    const line = screen.getByTestId("area-line");
    expect(line).toHaveClass("area-match");
    expect(line).toHaveStyle({ left: "12%", top: "12%" });
  });

  it("says why a picture did not match instead of repeating the score", () => {
    setup(undefined, [area({ kind: "image", score: 0.71, matched: false, reason: "picture 0.71, needs 0.85" })]);
    expect(screen.getByTitle("pohjola: picture 0.71, needs 0.85")).toHaveClass("area-off");
  });

  it("can be changed like a text area", () => {
    const onChange = vi.fn();
    const { el } = setup(onChange, [area({ kind: "image", score: 0.9 })]);
    fireEvent.pointerDown(el(), { clientX: 40, clientY: 80, button: 0 });
    fireEvent.pointerDown(el(), { clientX: 40, clientY: 120, button: 0 });
    fireEvent.pointerMove(el(), { clientX: 60, clientY: 160 });
    fireEvent.pointerUp(el(), { clientX: 60, clientY: 160 });
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange.mock.calls[0][0]).toMatchObject({ kind: "image" });
  });
});

describe("AreaLayer changing areas", () => {
  it("cannot be changed without onChange: no handles, no selection", () => {
    const { el } = setup();
    fireEvent.pointerDown(el(), { clientX: 40, clientY: 80, button: 0 });
    expect(document.querySelector("[data-handle]")).toBeNull();
    expect(el()).not.toHaveClass("area-editable");
  });

  it("a click selects an area and shows its handles; a drag of a selected area moves it", () => {
    const onChange = vi.fn();
    const { el } = setup(onChange);
    fireEvent.pointerDown(el(), { clientX: 40, clientY: 80, button: 0 });
    expect(el()).toHaveClass("area-selected");
    expect(document.querySelectorAll("[data-handle]")).toHaveLength(8);
    expect(onChange).not.toHaveBeenCalled(); // selecting is not a change
    // (40, 120) -> (60, 160): 10 % across, 10 % down
    fireEvent.pointerDown(el(), { clientX: 40, clientY: 120, button: 0 });
    fireEvent.pointerMove(el(), { clientX: 60, clientY: 160 });
    expect(parseFloat(el().style.left)).toBeCloseTo(20); // follows the pointer
    expect(parseFloat(el().style.top)).toBeCloseTo(20);
    expect(onChange).not.toHaveBeenCalled(); // until it is released
    fireEvent.pointerUp(el(), { clientX: 60, clientY: 160 });
    expect(onChange).toHaveBeenCalledTimes(1);
    const [changed, box] = onChange.mock.calls[0] as [Area, number[]];
    expect(changed.rule_id).toBe("pohjola");
    expect(box[0]).toBeCloseTo(0.2);
    expect(box[1]).toBeCloseTo(0.2);
    expect(box[2]).toBeCloseTo(0.6);
    expect(box[3]).toBeCloseTo(0.4);
  });

  it("a handle resizes the area", () => {
    const onChange = vi.fn();
    const { el } = setup(onChange);
    fireEvent.pointerDown(el(), { clientX: 40, clientY: 80, button: 0 });
    const handle = document.querySelector('[data-handle="se"]') as HTMLElement;
    fireEvent.pointerDown(handle, { clientX: 100, clientY: 120, button: 0 });
    fireEvent.pointerMove(handle, { clientX: 140, clientY: 160 });
    fireEvent.pointerUp(handle, { clientX: 140, clientY: 160 });
    const box = onChange.mock.calls[0][1] as number[];
    expect(box.map((v) => Math.round(v * 1000) / 1000)).toEqual([0.1, 0.1, 0.7, 0.4]);
  });

  it("a drag that goes nowhere changes nothing, and Esc deselects", () => {
    const onChange = vi.fn();
    const { el } = setup(onChange);
    fireEvent.pointerDown(el(), { clientX: 40, clientY: 80, button: 0 });
    fireEvent.pointerDown(el(), { clientX: 40, clientY: 120, button: 0 });
    fireEvent.pointerUp(el(), { clientX: 40, clientY: 120 });
    expect(onChange).not.toHaveBeenCalled();
    fireEvent.keyDown(document.body, { key: "Escape" });
    expect(el()).not.toHaveClass("area-selected");
  });

  it("Esc during a drag puts the area back", () => {
    const onChange = vi.fn();
    const { el } = setup(onChange);
    fireEvent.pointerDown(el(), { clientX: 40, clientY: 80, button: 0 });
    fireEvent.pointerDown(el(), { clientX: 40, clientY: 120, button: 0 });
    fireEvent.pointerMove(el(), { clientX: 100, clientY: 200 });
    fireEvent.keyDown(document.body, { key: "Escape" });
    expect(parseFloat(el().style.left)).toBeCloseTo(10);
    fireEvent.pointerUp(el(), { clientX: 100, clientY: 200 });
    expect(onChange).not.toHaveBeenCalled();
  });
});
