/** The one block order of a file's view, the same in Browse (the file panel), in a
 * collection (the inspector and member file panel) and in a tray (the item view):
 *
 *  1. header       the name (click to rename), the folder, the lock, ★ and !
 *  2. tags
 *  3. collections  the file's collections as removable chips, and Add to collection
 *  4. summary      foldable
 *  5. own          what only this view has (a tray's fields and Mark done, a collection's
 *                  group and Remove, Browse's Put in tray)
 *  6. preview      with its toolbar
 *  7. notes        notes, checklist, history (foldable), where the view has them
 *
 * A screen fills the blocks; it cannot reorder them, and the keyboard order is the DOM
 * order. A block left empty is not rendered. The block wrappers take no space of their
 * own (``display: contents``), so each screen styles its content as before. */
import type { HTMLAttributes, ReactNode } from "react";

export const FILE_VIEW_BLOCKS = ["header", "tags", "collections", "summary", "own", "preview", "notes"] as const;
export type FileViewBlock = (typeof FILE_VIEW_BLOCKS)[number];

export type FileViewBlocks = Partial<Record<FileViewBlock, ReactNode>>;

export function FileView({
  className,
  rootProps,
  ...blocks
}: FileViewBlocks & { className?: string; rootProps?: HTMLAttributes<HTMLDivElement> }) {
  return (
    <div className={className} {...rootProps}>
      {FILE_VIEW_BLOCKS.map((name) => {
        const content = blocks[name];
        return content === undefined || content === null || content === false ? null : (
          <div key={name} className="file-view-block" data-block={name}>
            {content}
          </div>
        );
      })}
    </div>
  );
}
