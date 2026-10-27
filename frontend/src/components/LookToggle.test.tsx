import { act, fireEvent, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";
import { STYLE_KEY } from "../appearance";
import { renderWithProviders } from "../test-utils";
import { LookToggle, useLookShortcut } from "./LookToggle";

function Host() {
  useLookShortcut();
  return (
    <>
      <LookToggle />
      <input aria-label="Name" />
    </>
  );
}

const look = () => document.documentElement.dataset.style;
const chord = (target: Element | Document = document) =>
  fireEvent.keyDown(target, { key: "¬", code: "KeyL", ctrlKey: true, altKey: true });

beforeEach(() => {
  localStorage.clear();
  delete document.documentElement.dataset.style;
});

describe("the temporary Look switch", () => {
  it("the sidebar toggle switches the look and says so", async () => {
    const user = userEvent.setup();
    renderWithProviders(<Host />);
    expect(screen.getByRole("button", { name: "Classic" })).toHaveAttribute("aria-pressed", "true");
    await user.click(screen.getByRole("button", { name: "New" }));
    expect(look()).toBe("new");
    expect(localStorage.getItem(STYLE_KEY)).toBe("new");
    expect(screen.getByRole("button", { name: "New" })).toHaveAttribute("aria-pressed", "true");
    expect(await screen.findByText("Look: New")).toBeInTheDocument();
  });

  it("Ctrl+Alt+L toggles the look back and forth", async () => {
    renderWithProviders(<Host />);
    act(() => chord());
    expect(look()).toBe("new");
    expect(await screen.findByText("Look: New")).toBeInTheDocument();
    act(() => chord());
    expect(look()).toBe("classic");
    expect(await screen.findByText("Look: Classic")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Classic" })).toHaveAttribute("aria-pressed", "true");
  });

  it("the shortcut needs both modifiers and stays quiet while typing", () => {
    renderWithProviders(<Host />);
    fireEvent.keyDown(document, { key: "l", code: "KeyL" });
    fireEvent.keyDown(document, { key: "l", code: "KeyL", ctrlKey: true });
    fireEvent.keyDown(document, { key: "¬", code: "KeyL", altKey: true });
    chord(screen.getByRole("textbox", { name: "Name" }));
    expect(look()).not.toBe("new");
  });
});
