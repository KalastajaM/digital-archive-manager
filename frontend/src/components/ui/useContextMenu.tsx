/** One right-click menu for a list of rows: ``open(row, e)`` from a row's contextmenu (or
 * Shift+F10 on it), and ``view(build)`` where the menu goes; ``build`` makes the label and
 * entries for the row it was opened on, at render, so they follow the screen's state (a
 * selection the right-click just changed, say). */
import { type MouseEvent, type ReactNode, useState } from "react";
import { ContextMenu } from "./ContextMenu";
import type { MenuEntry } from "./Menu";

export function useContextMenu<T>() {
  const [menu, setMenu] = useState<{ x: number; y: number; target: T } | null>(null);
  return {
    /** The row the menu is open on (null: closed). */
    target: menu?.target ?? null,
    open: (target: T, e: MouseEvent) => {
      e.preventDefault();
      e.stopPropagation(); // a nested row's menu, not its parent's
      setMenu({ x: e.clientX, y: e.clientY, target });
    },
    close: () => setMenu(null),
    view: (build: (target: T) => { label: string; entries: MenuEntry[] } | null): ReactNode => {
      if (!menu) return null;
      const built = build(menu.target);
      return built && <ContextMenu x={menu.x} y={menu.y} label={built.label} entries={built.entries} onClose={() => setMenu(null)} />;
    },
  };
}
