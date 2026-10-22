import type { ReactNode } from "react";

type Props = {
  title: string;
  /** Shown in place of the title while it is renamed in place (an input). */
  titleEditor?: ReactNode;
  /** Muted text after the title, e.g. "6 documents". */
  subtitle?: ReactNode;
  /** Icon buttons (``IconButton``) and segmented controls. */
  actions?: ReactNode;
  /** A search field, kept at the right edge. */
  search?: ReactNode;
};

/** The unified toolbar at the top of a screen: title, subtitle, actions, search. */
export function Toolbar({ title, titleEditor, subtitle, actions, search }: Props) {
  return (
    <header className="toolbar">
      <div className="toolbar-title">
        {titleEditor ?? <h2>{title}</h2>}
        {!titleEditor && subtitle && <span className="toolbar-subtitle">{subtitle}</span>}
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
