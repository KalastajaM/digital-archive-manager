/** The right-click menu: groups between rules, a disabled entry says why, a toggle shows
 * its check, and the browser's own menu is off everywhere but in text fields. Shift+F10
 * (or the ContextMenu key) opens a row's menu from the keyboard. */
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useContextMenuKeys } from "../../contextMenus";
import { ContextMenu } from "./ContextMenu";

afterEach(cleanup);

describe("ContextMenu", () => {
  it("draws rules between groups, and a disabled entry carries its reason", () => {
    render(
      <ContextMenu
        x={10}
        y={10}
        label="Actions"
        entries={[
          { label: "Open", onSelect: () => {} },
          "separator",
          { label: "Star", checked: true, onSelect: () => {} },
          { label: "Move to…", disabled: true, reason: "Files in To Delete stay put", onSelect: () => {} },
        ]}
        onClose={() => {}}
      />,
    );
    const menu = screen.getByRole("menu", { name: "Actions" });
    expect(within(menu).getByRole("separator")).toBeInTheDocument();
    expect(within(menu).getByRole("menuitemcheckbox", { name: "Star" })).toHaveAttribute("aria-checked", "true");
    const move = within(menu).getByRole("menuitem", { name: /Move to…/ });
    expect(move).toBeDisabled();
    expect(move).toHaveAccessibleDescription("Files in To Delete stay put");
    expect(menu).toHaveTextContent("Files in To Delete stay put");
  });

  it("over a modal dialog, it is drawn inside the dialog (the page behind is inert)", () => {
    const dialog = document.createElement("dialog");
    dialog.setAttribute("open", "");
    document.body.append(dialog);
    render(<ContextMenu x={10} y={10} label="In the dialog" entries={[{ label: "Open", onSelect: () => {} }]} onClose={() => {}} />);
    expect(dialog).toContainElement(screen.getByRole("menu", { name: "In the dialog" }));
    dialog.remove();
  });

  it("a leading, trailing or doubled rule is dropped", () => {
    render(
      <ContextMenu
        x={10}
        y={10}
        label="Actions"
        entries={["separator", { label: "Open", onSelect: () => {} }, "separator", "separator", { label: "Close", onSelect: () => {} }, "separator"]}
        onClose={() => {}}
      />,
    );
    expect(screen.getAllByRole("separator")).toHaveLength(1);
  });
});

function Page() {
  useContextMenuKeys();
  const [opened, setOpened] = useState<string | null>(null);
  return (
    <div>
      <button type="button" onContextMenu={(e) => { e.preventDefault(); setOpened(`row at ${e.clientX},${e.clientY}`); }}>
        Row
      </button>
      <p>Plain text</p>
      <input aria-label="Field" />
      <textarea aria-label="Area" />
      <div contentEditable suppressContentEditableWarning aria-label="Editable">
        x
      </div>
      {opened && <output>{opened}</output>}
    </div>
  );
}

describe("useContextMenuKeys", () => {
  it("turns the browser's menu off except in text inputs, textareas and editable text", () => {
    render(<Page />);
    const fire = (el: Element) => !fireEvent.contextMenu(el); // true: default prevented
    expect(fire(screen.getByText("Plain text"))).toBe(true);
    expect(fire(screen.getByRole("textbox", { name: "Field" }))).toBe(false);
    expect(fire(screen.getByRole("textbox", { name: "Area" }))).toBe(false);
    expect(fire(screen.getByText("x"))).toBe(false);
  });

  it("Shift+F10 and the ContextMenu key open the focused element's menu by its edge", async () => {
    render(<Page />);
    const row = screen.getByRole("button", { name: "Row" });
    vi.spyOn(row, "getBoundingClientRect").mockReturnValue({ left: 100, top: 40, right: 300, bottom: 60, width: 200, height: 20, x: 100, y: 40, toJSON: () => ({}) });
    row.focus();
    const user = userEvent.setup();
    await user.keyboard("{Shift>}{F10}{/Shift}");
    expect(screen.getByRole("status")).toHaveTextContent("row at 108,56");
    cleanup();
    render(<Page />);
    const again = screen.getByRole("button", { name: "Row" });
    again.focus();
    const key = new KeyboardEvent("keydown", { key: "ContextMenu", bubbles: true, cancelable: true });
    act(() => {
      again.dispatchEvent(key);
    });
    expect(key.defaultPrevented).toBe(true);
    expect(screen.getByRole("status")).toHaveTextContent(/row at/);
  });

  it("leaves Shift+F10 alone in a text field", async () => {
    render(<Page />);
    const field = screen.getByRole("textbox", { name: "Field" });
    field.focus();
    const key = new KeyboardEvent("keydown", { key: "F10", shiftKey: true, bubbles: true, cancelable: true });
    field.dispatchEvent(key);
    expect(key.defaultPrevented).toBe(false);
  });
});
