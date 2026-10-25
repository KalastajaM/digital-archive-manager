import { Pencil } from "lucide-react";
import type { ReactNode } from "react";
import { IconButton } from "./IconButton";

type Props = {
  title: string;
  /** Shown in place of the title while it is renamed in place (an input). */
  titleEditor?: ReactNode;
  /** Edits the title in place: a click on it, or the pencil beside it (shown on hover and
   * focus, always there for the keyboard), calls this. */
  onEditTitle?: () => void;
  /** Muted text after the title, e.g. "6 documents". */
  subtitle?: ReactNode;
  /** Icon buttons (``IconButton``) and segmented controls. */
  actions?: ReactNode;
  /** A search field, kept at the right edge. */
  search?: ReactNode;
};

/** The unified toolbar at the top of a screen: title, subtitle, actions, search. */
export function Toolbar({ title, titleEditor, subtitle, onEditTitle, actions, search }: Props) {
  return (
    <header className="toolbar">
      <div className="toolbar-title">
        {titleEditor ?? (
          <>
            <h2 className={onEditTitle ? "toolbar-title-editable" : undefined} onClick={onEditTitle}>
              {title}
            </h2>
            {onEditTitle && <IconButton className="toolbar-title-pencil" icon={<Pencil />} label="Edit name" onClick={onEditTitle} />}
          </>
        )}
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
