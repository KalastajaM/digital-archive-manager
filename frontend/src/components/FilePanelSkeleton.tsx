/** The one skeleton for the file panel on the right of Browse, the Inbox, a tray and a
 * collection. Top to bottom:
 *
 *  1. header       the name (fixed-width face), the folder, the lock
 *  2. actions      the icon row (``FileActionIcons``)
 *  3. top          what a screen puts right under them (the Inbox's filing form)
 *  4. tags         the inline tag box
 *  5. collections  the inline collection box (chips and an input, as the tags)
 *  6. group        a collection's Group
 *  7. summary
 *  8. own          anything else a screen has
 *  9. versions     foldable, only when the document has versions
 * 10. relatives    foldable
 * 11. preview
 * 12. notes
 *
 * A screen fills the blocks it has; a block left empty is not drawn, and a screen cannot
 * reorder them (the keyboard order is the DOM order). */
import type { ReactNode } from "react";
import type { Mark } from "../api/client";
import { visible } from "../text";
import { FileView, type FileViewBlocks, SKELETON_BLOCKS } from "./FileView";
import { LockControl } from "./LockControl";
import { Breakable } from "./PlanPreview";

export function FilePanelSkeleton({ className, ...blocks }: FileViewBlocks & { className?: string }) {
  return <FileView className={["file-panel", "file-skeleton", className].filter(Boolean).join(" ")} order={SKELETON_BLOCKS} {...blocks} />;
}

/** The header of a file whose name and folder are edited elsewhere (the Inbox's form has them
 * as fields): the name, where it is now, and its lock. ``children``: more at the right of the name. */
export function StaticFileHead({
  driveId,
  name,
  folder,
  path,
  marks,
  children,
}: {
  driveId: string;
  name: string;
  /** Where it is now, as a path. */
  folder: string;
  path: string;
  marks?: readonly Mark[];
  children?: ReactNode;
}) {
  return (
    <header className="file-meta-head">
      <div className="file-meta-title">
        <h2 title={visible(name)}>{visible(name)}</h2>
        <LockControl driveId={driveId} marks={marks} path={path} />
        {children}
      </div>
      <p className="current-path">
        <code>
          <Breakable text={folder || "Archive"} />
        </code>
      </p>
    </header>
  );
}
