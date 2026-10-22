import type { ReactNode } from "react";

type Props = {
  /** A Lucide icon, drawn large and muted. */
  icon?: ReactNode;
  title: string;
  hint?: ReactNode;
  /** A button or link under the hint. */
  action?: ReactNode;
  className?: string;
};

/** What a list shows when it has nothing: centred, quiet, with an optional next step. */
export function EmptyState({ icon, title, hint, action, className }: Props) {
  return (
    <div className={className ? `empty-state ${className}` : "empty-state"}>
      {icon && (
        <span className="empty-state-icon" aria-hidden="true">
          {icon}
        </span>
      )}
      <p className="empty-state-title">{title}</p>
      {hint && <p className="empty-state-hint">{hint}</p>}
      {action && <div className="empty-state-action">{action}</div>}
    </div>
  );
}
