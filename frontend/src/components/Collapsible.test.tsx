import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Collapsible, firstLine } from "./Collapsible";

beforeEach(() => window.localStorage.clear());
afterEach(() => vi.restoreAllMocks());

describe("Collapsible", () => {
  it("is open by default, folds on click with a hint, and remembers the choice", async () => {
    const user = userEvent.setup();
    const { unmount } = render(
      <Collapsible name="history" title="History" hint="3 entries">
        <p>body</p>
      </Collapsible>,
    );
    const toggle = screen.getByRole("button", { name: "History" });
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("body")).toBeVisible();
    await user.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByText("3 entries")).toBeInTheDocument();
    expect(screen.getByText("body")).not.toBeVisible();
    unmount();
    render(
      <Collapsible name="history" title="History" hint="3 entries">
        <p>body</p>
      </Collapsible>,
    );
    expect(screen.getByRole("button", { name: "History" })).toHaveAttribute("aria-expanded", "false");
  });

  it("still works when storage throws", async () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    const user = userEvent.setup();
    render(
      <Collapsible name="notes" title="Notes">
        <p>body</p>
      </Collapsible>,
    );
    const toggle = screen.getByRole("button", { name: "Notes" });
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    await user.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "false");
  });

  it("firstLine takes the first non-empty line", () => {
    expect(firstLine("\n  one \ntwo")).toBe("one");
    expect(firstLine("")).toBe("");
  });
});
