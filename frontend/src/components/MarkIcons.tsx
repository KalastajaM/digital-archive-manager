/** A file's ★ Ongoing and ! Important icons, after its name in any row (spec §2: the
 * icon follows the file). Nothing for a file with no marks. */
import { Star } from "lucide-react";
import { createContext, useContext } from "react";
import type { Mark } from "../api/client";

export const MARK_LABEL: Record<Mark, string> = { starred: "Starred", important: "Important" };

/** The ! glyph of Important (also the sidebar row's and the toggle's icon): drawn, not
 * text, so it never becomes part of a name's text. */
export function ImportantGlyph({ large = false }: { large?: boolean }) {
  const size = large ? 16 : 12;
  return (
    <svg className="mark-bang" width={size} height={size} viewBox="0 0 24 24" aria-hidden="true">
      <path d="M12 3.5v11" stroke="currentColor" strokeWidth={large ? 3.2 : 3.6} strokeLinecap="round" fill="none" />
      <circle cx="12" cy="20" r={large ? 1.9 : 2.2} fill="currentColor" />
    </svg>
  );
}

export function StarGlyph({ size = 14, filled = true }: { size?: number; filled?: boolean }) {
  return <Star size={size} strokeWidth={1.75} fill={filled ? "currentColor" : "none"} aria-hidden="true" />;
}

/** The mark a whole list is already about (the ★ Ongoing or ! Important collection): its
 * icon would repeat on every row, so rows inside leave it out. */
export const OmitMark = createContext<Mark | null>(null);

export function MarkIcons({ marks, omit }: { marks: readonly Mark[] | null | undefined; omit?: Mark }) {
  const inherited = useContext(OmitMark);
  const skip = omit ?? inherited;
  const shown = marks?.filter((m) => m !== skip);
  if (!shown || shown.length === 0) return null;
  marks = shown;
  return (
    <span className="mark-icons">
      {marks.includes("starred") && (
        <span className="mark-icon mark-starred" role="img" aria-label={MARK_LABEL.starred} title={MARK_LABEL.starred}>
          <StarGlyph size={12} />
        </span>
      )}
      {marks.includes("important") && (
        <span className="mark-icon mark-important" role="img" aria-label={MARK_LABEL.important} title={MARK_LABEL.important}>
          <ImportantGlyph />
        </span>
      )}
    </span>
  );
}
