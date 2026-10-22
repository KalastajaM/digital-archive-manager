import { ChevronRight } from "lucide-react";
import { type HTMLAttributes, type ReactNode, useId } from "react";

type Props = {
  title: string;
  icon?: ReactNode;
  /** Right of the title: a count, a link, an icon button. */
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  /** A fold chevron before the title: a button (``aria-expanded``) that folds the card
   * down to its headline; the card renders its own folded body. */
  fold?: { folded: boolean; onToggle: () => void };
  /** Extra attributes on the header, e.g. to drag the card by it. */
  headerProps?: HTMLAttributes<HTMLElement>;
};

/** A white card with a muted caption title (Today's cards): a region named by its title. */
export function Card({ title, icon, actions, children, className, fold, headerProps }: Props) {
  const headingId = useId();
  const bodyId = useId();
  const classes = ["card", className, fold?.folded && "card-folded"].filter(Boolean).join(" ");
  return (
    <section className={classes} aria-labelledby={headingId}>
      <header {...headerProps} className="card-header">
        {fold && (
          <button
            type="button"
            className="card-fold"
            aria-label={`${fold.folded ? "Expand" : "Collapse"} ${title}`}
            aria-expanded={!fold.folded}
            aria-controls={bodyId}
            onClick={fold.onToggle}
          >
            <ChevronRight size={14} aria-hidden="true" />
          </button>
        )}
        <h3 id={headingId}>
          {icon && (
            <span className="card-icon" aria-hidden="true">
              {icon}
            </span>
          )}
          {title}
        </h3>
        {actions && <div className="card-actions">{actions}</div>}
      </header>
      <div id={bodyId} className="card-body">
        {children}
      </div>
    </section>
  );
}
