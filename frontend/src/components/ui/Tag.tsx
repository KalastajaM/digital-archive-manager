import type { MouseEvent, ReactNode } from "react";

export type TagTone = "red" | "orange" | "grey" | "blue" | "green";

type Props = { tone: TagTone; children: ReactNode; title?: string; className?: string; onClick?: (e: MouseEvent<HTMLSpanElement>) => void };

/** A small coloured label: red overdue, orange soon, grey neutral, blue info, green done. */
export function Tag({ tone, children, title, className, onClick }: Props) {
  const classes = ["tag", `tag-${tone}`, className].filter(Boolean).join(" ");
  return (
    <span className={classes} title={title} onClick={onClick}>
      {children}
    </span>
  );
}
