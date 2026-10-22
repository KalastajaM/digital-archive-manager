/** What Today's layout gives each card: its fold chevron, and the header attributes that let it be dragged. */
import type { HTMLAttributes } from "react";

export type CardFrame = {
  fold: { folded: boolean; onToggle: () => void };
  headerProps: HTMLAttributes<HTMLElement>;
};
