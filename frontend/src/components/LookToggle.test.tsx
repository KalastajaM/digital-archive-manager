import { act, fireEvent, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { renderWithProviders } from "../test-utils";
import { useLookShortcut } from "./LookToggle";

function Host() {
  useLookShortcut();
  return <input aria-label="Name" />;
}

const look = () => document.documentElement.dataset.style;
const chord = (target: Element | Document = document) =>
  fireEvent.keyDown(target, { key: "¬", code: "KeyL", ctrlKey: true, altKey: true });

beforeEach(() => {
  localStorage.clear();
  delete document.documentElement.dataset.style;
});

describe("the Look shortcut", () => {
  it("Ctrl+Alt+L toggles the look back and forth", async () => {
    renderWithProviders(<Host />);
    act(() => chord());
    expect(look()).toBe("new");
    expect(await screen.findByText("Look: New")).toBeInTheDocument();
    act(() => chord());
    expect(look()).toBe("classic");
    expect(await screen.findByText("Look: Classic")).toBeInTheDocument();
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
