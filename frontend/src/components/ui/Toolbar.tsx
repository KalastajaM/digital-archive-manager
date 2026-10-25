import type { ReactNode } from "react";
import { ClickToEdit } from "./ClickToEdit";

type Props = {
  title: string;
  /** Shown in place of the title while it is renamed in place (an input). */
  titleEditor?: ReactNode;
  /** Edits the title in place: a click on it (it is a button, so the keyboard reaches it
   * too) calls this. */
  onEditTitle?: () => void;
  /** Muted text after the title, e.g. "6 documents". */
  subtitle?: ReactNode;
  /** Icon buttons (``IconButton``) and segmented controls. */
  actions?: ReactNode;
  /** A search field, kept at the right edge. */
  search?: ReactNode;
  /** Two rows: the title with its subtitle on the first, the actions right-aligned on the
   * second (a narrow list column). The title is cut with an ellipsis only as a last resort,
   * and then it is whole in the tooltip. */
  stacked?: boolean;
};

/** The unified toolbar at the top of a screen: title, subtitle, actions, search. */
export function Toolbar({ title, titleEditor, subtitle, onEditTitle, actions, search, stacked }: Props) {
  return (
    <header className={stacked ? "toolbar toolbar-stacked" : "toolbar"}>
      <div className="toolbar-title">
        {titleEditor ?? (
          <>
            <h2 aria-label={onEditTitle ? title : undefined} title={stacked ? title : undefined}>
              {onEditTitle ? (
                <ClickToEdit label={`Rename ${title}`} tip="Click to rename" onClick={onEditTitle}>
                  {title}
                </ClickToEdit>
              ) : (
                title
              )}
            </h2>
          </>
        )}
        {!titleEditor && subtitle && <span className="toolbar-subtitle" title={stacked && typeof subtitle === "string" ? subtitle : undefined}>
            {subtitle}
          </span>}
      </div>
      {actions && (
        <div className="toolbar-actions" role="toolbar" aria-label={`${title} actions`}>
          {actions}
        </div>
      )}
      {search && <div className="toolbar-search">{search}</div>}
    </header>
  );
}
