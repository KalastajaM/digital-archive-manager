import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Splitter, type SplitOptions, useSplitWidth } from "./SplitPane";

const KEY = "dam.test.split";

function Host({ opts }: { opts: SplitOptions }) {
  const split = useSplitWidth(KEY, opts);
  return (
    <div ref={split.hostRef} style={split.hostStyle} data-testid="host">
      <Splitter split={split} label="Resize" />
    </div>
  );
}

const PCT: SplitOptions = { min: 25, max: 75, initial: 45 };
const PX_END: SplitOptions = { min: 200, max: 500, initial: 300, unit: "px", edge: "end" };

/** jsdom has no layout: the host is 1000px wide, from x = 100. */
function sized() {
  return vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockReturnValue({
    left: 100,
    right: 1100,
    top: 0,
    bottom: 600,
    width: 1000,
    height: 600,
    x: 100,
    y: 0,
    toJSON: () => ({}),
  });
}

describe("Splitter", () => {
  afterEach(() => {
    localStorage.clear();
    vi.restoreAllMocks();
  });

  it("is a vertical separator with its range and the default width", () => {
    render(<Host opts={PCT} />);
    const bar = screen.getByRole("separator", { name: "Resize" });
    expect(bar).toHaveAttribute("aria-orientation", "vertical");
    expect(bar).toHaveAttribute("aria-valuemin", "25");
    expect(bar).toHaveAttribute("aria-valuemax", "75");
    expect(bar).toHaveAttribute("aria-valuenow", "45");
    expect(screen.getByTestId("host").style.getPropertyValue("--split")).toBe("45%");
  });

  it("the arrow keys move it, within the limits, and the width is remembered", async () => {
    const user = userEvent.setup();
    render(<Host opts={PCT} />);
    const bar = screen.getByRole("separator");
    bar.focus();
    await user.keyboard("{ArrowRight}{ArrowRight}");
    expect(bar).toHaveAttribute("aria-valuenow", "49");
    expect(localStorage.getItem(KEY)).toBe("49");
    await user.keyboard("{ArrowLeft}");
    expect(bar).toHaveAttribute("aria-valuenow", "47");
    await user.keyboard("{ArrowRight}".repeat(40));
    expect(bar).toHaveAttribute("aria-valuenow", "75");
  });

  it("dragging sets the width from the pointer, clamped, and drops it into storage", () => {
    sized();
    render(<Host opts={PCT} />);
    const bar = screen.getByRole("separator");
    fireEvent.pointerDown(bar, { button: 0, clientX: 550 });
    fireEvent.pointerMove(window, { clientX: 700 });
    expect(bar).toHaveAttribute("aria-valuenow", "60");
    expect(localStorage.getItem(KEY)).toBeNull(); // still dragging
    fireEvent.pointerUp(window, { clientX: 1090 });
    expect(bar).toHaveAttribute("aria-valuenow", "75"); // (1090 - 100) / 1000 is past the limit
    expect(localStorage.getItem(KEY)).toBe("75");
    fireEvent.pointerMove(window, { clientX: 200 }); // the drag is over
    expect(bar).toHaveAttribute("aria-valuenow", "75");
  });

  it("ignores a drag started with another button", () => {
    sized();
    render(<Host opts={PCT} />);
    const bar = screen.getByRole("separator");
    fireEvent.pointerDown(bar, { button: 2, clientX: 550 });
    fireEvent.pointerMove(window, { clientX: 700 });
    expect(bar).toHaveAttribute("aria-valuenow", "45");
  });

  it("a double-click restores the default and forgets the remembered width", async () => {
    localStorage.setItem(KEY, "60");
    const user = userEvent.setup();
    render(<Host opts={PCT} />);
    const bar = screen.getByRole("separator");
    expect(bar).toHaveAttribute("aria-valuenow", "60"); // remembered from before
    await user.dblClick(bar);
    expect(bar).toHaveAttribute("aria-valuenow", "45");
    expect(localStorage.getItem(KEY)).toBeNull();
  });

  it("clamps a remembered width that is out of range, and ignores junk", () => {
    localStorage.setItem(KEY, "99");
    const { unmount } = render(<Host opts={PCT} />);
    expect(screen.getByRole("separator")).toHaveAttribute("aria-valuenow", "75");
    unmount();
    localStorage.setItem(KEY, "wide");
    render(<Host opts={PCT} />);
    expect(screen.getByRole("separator")).toHaveAttribute("aria-valuenow", "45");
  });

  it("works without storage", async () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(Storage.prototype, "removeItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    const user = userEvent.setup();
    render(<Host opts={PCT} />);
    const bar = screen.getByRole("separator");
    expect(bar).toHaveAttribute("aria-valuenow", "45");
    bar.focus();
    await user.keyboard("{ArrowRight}");
    expect(bar).toHaveAttribute("aria-valuenow", "47");
    await user.dblClick(bar);
    expect(bar).toHaveAttribute("aria-valuenow", "45");
  });

  it("a pane on the end edge is measured from the right and grows with ArrowLeft", async () => {
    sized();
    const user = userEvent.setup();
    render(<Host opts={PX_END} />);
    const bar = screen.getByRole("separator");
    expect(screen.getByTestId("host").style.getPropertyValue("--split")).toBe("300px");
    expect(bar).toHaveClass("splitter-end");
    fireEvent.pointerDown(bar, { button: 0, clientX: 800 });
    fireEvent.pointerUp(window, { clientX: 800 }); // 1100 - 800
    expect(bar).toHaveAttribute("aria-valuenow", "300");
    fireEvent.pointerDown(bar, { button: 0, clientX: 800 });
    fireEvent.pointerUp(window, { clientX: 700 });
    expect(bar).toHaveAttribute("aria-valuenow", "400");
    bar.focus();
    await user.keyboard("{ArrowLeft}");
    expect(bar).toHaveAttribute("aria-valuenow", "416");
    await user.keyboard("{ArrowRight}{ArrowRight}");
    expect(bar).toHaveAttribute("aria-valuenow", "384");
  });

  it("a px width leaves the other pane room", () => {
    sized(); // 1000px wide: at most 680px for the pane
    render(<Host opts={{ min: 200, max: 900, initial: 300, unit: "px" }} />);
    const bar = screen.getByRole("separator");
    fireEvent.pointerDown(bar, { button: 0, clientX: 300 });
    fireEvent.pointerUp(window, { clientX: 1000 });
    expect(bar).toHaveAttribute("aria-valuenow", "680");
  });
});
