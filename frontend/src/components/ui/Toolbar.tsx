import type { CSSProperties, ReactNode } from "react";
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
  /** A second group of actions after the search, at the far right (Browse: what acts on
   * the selected files, over the file pane). The rest then sits in ``toolbar-lead``. */
  trailing?: ReactNode;
  /** Two rows: the title with its subtitle on the first, the actions right-aligned on the
   * second (a narrow list column). The title is cut with an ellipsis only as a last resort,
   * and then it is whole in the tooltip. */
  stacked?: boolean;
  /** Something before the title (the New look's "Inbox N" button that opens a folded list). */
  lead?: ReactNode;
  /** The search before the actions instead of after them (the New Browse header). */
  searchFirst?: boolean;
  /** Extra class and inline style for the header (a screen that sizes it to a column). */
  className?: string;
  style?: CSSProperties;
};

/** The unified toolbar at the top of a screen: title, subtitle, actions, search. */
export function Toolbar({ title, titleEditor, subtitle, onEditTitle, actions, search, trailing, stacked, lead: before, searchFirst, className, style }: Props) {
  const lead = (
    <>
      {before}
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
      {searchFirst && search && <div className="toolbar-search">{search}</div>}
      {actions && (
        <div className="toolbar-actions" role="toolbar" aria-label={`${title} actions`}>
          {actions}
        </div>
      )}
      {!searchFirst && search && <div className="toolbar-search">{search}</div>}
    </>
  );
  return (
    <header className={[stacked ? "toolbar toolbar-stacked" : "toolbar", className].filter(Boolean).join(" ")} style={style}>
      {trailing ? <div className="toolbar-lead">{lead}</div> : lead}
      {trailing && (
        <div className="toolbar-actions toolbar-trailing" role="toolbar" aria-label={`${title} file actions`}>
          {trailing}
        </div>
      )}
    </header>
  );
}
