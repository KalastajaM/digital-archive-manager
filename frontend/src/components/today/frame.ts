/** What Today's layout gives each card: its fold chevron, its ⋯ menu (Move up, Move
 * down, Reset layout) and the header attributes that let it be dragged. */
import type { HTMLAttributes, ReactNode } from "react";

export type CardFrame = {
  fold: { folded: boolean; onToggle: () => void };
  menu: ReactNode;
  headerProps: HTMLAttributes<HTMLElement>;
};
