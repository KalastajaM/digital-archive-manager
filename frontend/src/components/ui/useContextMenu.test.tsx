/** One right-click menu per list: ``open(target)`` on a row's contextmenu, ``view``
 * builds the entries for the row it was opened on (at render, so they follow the state). */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useContextMenu } from "./useContextMenu";

afterEach(cleanup);

function List({ onPick }: { onPick: (name: string) => void }) {
  const menu = useContextMenu<string>();
  return (
    <ul>
      {["a", "b"].map((n) => (
        <li key={n} onContextMenu={(e) => menu.open(n, e)}>
          row {n}
        </li>
      ))}
      {menu.view((n) => ({ label: `Actions for ${n}`, entries: [{ label: `Pick ${n}`, onSelect: () => onPick(n) }] }))}
    </ul>
  );
}

describe("useContextMenu", () => {
  it("opens on the row right-clicked, builds its entries, and closes after a pick", async () => {
    const onPick = vi.fn();
    render(<List onPick={onPick} />);
    const ev = fireEvent.contextMenu(screen.getByText("row b"), { clientX: 20, clientY: 30 });
    expect(ev).toBe(false); // the browser's own menu is kept off
    await userEvent.setup().click(screen.getByRole("menuitem", { name: "Pick b" }));
    expect(onPick).toHaveBeenCalledWith("b");
    expect(screen.queryByRole("menu")).toBeNull();
  });
});
