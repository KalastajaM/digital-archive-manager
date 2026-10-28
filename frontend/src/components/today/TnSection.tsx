/** A section of the New look's Today: a plain heading (name, a figure beside it, links
 * at the right) over its content, with no box. It takes the same props as ``Card`` so
 * Today's cards (Starred, Collections, Reminders, Search, Clear) can wear either as their
 * ``Shell``. While the page is being arranged (Customize) the heading shows the fold
 * chevron and Move up / Move down, and can be dragged; otherwise it is a calm heading. */
import { ArrowDown, ArrowUp, ChevronRight } from "lucide-react";
import { createContext, type HTMLAttributes, type ReactNode, useContext, useId } from "react";
import { Link } from "react-router-dom";
import { IconButton } from "../ui/IconButton";

export type SectionControls = { arranging: boolean; canUp: boolean; canDown: boolean; up: () => void; down: () => void };

export const SectionContext = createContext<SectionControls>({
  arranging: false,
  canUp: false,
  canDown: false,
  up: () => {},
  down: () => {},
});

type Props = {
  title: string;
  icon?: ReactNode;
  /** Links and buttons at the right of the heading. */
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  fold?: { folded: boolean; onToggle: () => void };
  headerProps?: HTMLAttributes<HTMLElement>;
  /** A figure beside the name ("3 open · 186,30 €"). */
  meta?: ReactNode;
  /** Makes the name a link. */
  titleTo?: string;
};

export function TnSection({ title, actions, children, className, fold, headerProps, meta, titleTo }: Props) {
  const headingId = useId();
  const bodyId = useId();
  const { arranging, canUp, canDown, up, down } = useContext(SectionContext);
  // the Classic card classes (today-card, ...) that the cards pass are not this look's
  const own = (className ?? "").split(" ").filter((c) => c.startsWith("tn-"));
  const classes = ["tn-section", ...own, fold?.folded && "tn-folded"].filter(Boolean).join(" ");
  return (
    <section className={classes} aria-labelledby={headingId}>
      <header {...(arranging ? headerProps : {})} className="tn-head" data-arranging={arranging || undefined}>
        {fold && (arranging || fold.folded) && (
          <button
            type="button"
            className="card-fold tn-fold"
            aria-label={`${fold.folded ? "Expand" : "Collapse"} ${title}`}
            aria-expanded={!fold.folded}
            aria-controls={bodyId}
            onClick={fold.onToggle}
          >
            <ChevronRight size={14} aria-hidden="true" />
          </button>
        )}
        <h2 id={headingId} className="tn-title">
          {titleTo ? <Link to={titleTo}>{title}</Link> : title}
        </h2>
        {meta && <span className="tn-meta">{meta}</span>}
        <span className="tn-grow" />
        {actions && <div className="tn-actions">{actions}</div>}
        {arranging && (
          <span className="tn-move" role="group" aria-label={`Move ${title}`}>
            <IconButton icon={<ArrowUp size={14} />} label={`Move ${title} up`} disabled={!canUp} onClick={up} />
            <IconButton icon={<ArrowDown size={14} />} label={`Move ${title} down`} disabled={!canDown} onClick={down} />
          </span>
        )}
      </header>
      <div id={bodyId} className="tn-body">
        {children}
      </div>
    </section>
  );
}
