/** A section that can be folded to its heading and a one-line hint (Summary, Checklist,
 * Notes, History). The heading is a disclosure button (``aria-expanded``). The choice is
 * remembered per section ``name`` in localStorage, shared by all items and files; with
 * storage unavailable it still works for the page's lifetime. Folded content stays
 * mounted (hidden), so a half-typed note or an open editor is not lost. */
import { ChevronDown, ChevronRight } from "lucide-react";
import { type ReactNode, useId, useState } from "react";

const KEY = "dam.collapsed.";

/** The sections that remember their state. */
export type CollapsibleName = "summary" | "checklist" | "notes" | "history";

function readCollapsed(name: CollapsibleName): boolean {
  try {
    return window.localStorage.getItem(KEY + name) === "1";
  } catch {
    return false; // blocked or unavailable: expanded
  }
}

function writeCollapsed(name: CollapsibleName, collapsed: boolean) {
  try {
    if (collapsed) window.localStorage.setItem(KEY + name, "1");
    else window.localStorage.removeItem(KEY + name);
  } catch {
    // not remembered; the section still folds
  }
}

export function Collapsible({
  name,
  title,
  hint,
  aside,
  className,
  headingId,
  children,
}: {
  name: CollapsibleName;
  title: string;
  /** One line shown instead of the content while folded. */
  hint?: ReactNode;
  /** Beside the heading, e.g. a tag (kept visible when folded). */
  aside?: ReactNode;
  className?: string;
  /** The heading's id when the caller needs it. */
  headingId?: string;
  children: ReactNode;
}) {
  const ownId = useId();
  const hid = headingId ?? `${ownId}-h`;
  const bodyId = `${ownId}-body`;
  const [collapsed, setCollapsed] = useState(() => readCollapsed(name));
  const toggle = () => {
    writeCollapsed(name, !collapsed);
    setCollapsed(!collapsed);
  };
  return (
    <section className={className ? `collapsible ${className}` : "collapsible"} aria-labelledby={hid}>
      <header className="collapsible-head">
        <h3 id={hid}>
          <button type="button" className="collapsible-toggle" aria-expanded={!collapsed} aria-controls={bodyId} onClick={toggle}>
            {collapsed ? <ChevronRight size={14} aria-hidden="true" /> : <ChevronDown size={14} aria-hidden="true" />}
            {title}
          </button>
        </h3>
        {aside}
        {collapsed && hint !== undefined && hint !== null && <span className="collapsible-hint">{hint}</span>}
      </header>
      <div id={bodyId} className="collapsible-body" hidden={collapsed}>
        {children}
      </div>
    </section>
  );
}

/** The first non-empty line of a text, for a folded hint. */
export const firstLine = (text: string): string => text.split("\n").find((l) => l.trim() !== "")?.trim() ?? "";
