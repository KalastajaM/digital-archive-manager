/** The selected file's side panel, the same in Browse and in a collection, laid out in the
 * file view's one block order (``FileView``): name and folder (editable), tags, the
 * file's collections, the summary, the screen's own block (``extras``: a collection's
 * group and Remove; then Put in tray and Back to inbox), the preview with ★ / ! and Ask AI
 * in its toolbar (Browse puts all of those in its header: ``headerActions``), and the note. A screen adds its own: ``view`` and ``tools`` in the
 * preview's toolbar and ``intro`` under the name. The toolbar keeps the app's one order:
 * view (Open, Show in Finder, ``view``: Quick Look), then ★ / !, then Ask AI, then
 * ``tools`` (the bin last). */
import type { ReactNode } from "react";
import type { FilingAI } from "../components/ai/useFilingAI";
import { SummaryBox } from "../components/ai/SummaryBox";
import { FileMeta, type MetaFile } from "../components/FileMeta";
import { FilePanelSkeleton } from "../components/FilePanelSkeleton";
import { ChangedNotice } from "../components/today/ChangedFiles";
import { FoundIdentifiers } from "../components/FoundIdentifiers";
import { RelativesBlock } from "../components/RelativesBlock";
import { FilePreview, type PreviewFile } from "../components/FilePreview";
import { Breakable } from "../components/PlanPreview";
import type { RestoreTo } from "../components/Restore";
import { SavedNote } from "../components/SavedNote";
import { inToDelete, toDeleteReason } from "../toDelete";
import { visible } from "../text";
import { FileCollections, FolderActions, type FolderMoveTo } from "./FileActions";

export function FilePanel({
  file,
  preview,
  disabled = false,
  tools,
  intro,
  extras,
  boxTool = true,
  headerActions,
  compactRelatives = false,
  actions,
  summary,
  hideItem,
}: {
  file: MetaFile;
  /** What the preview shows (Browse: a link's target). */
  preview: PreviewFile;
  /** Another change is under way: editing is off. */
  disabled?: boolean;
  tools?: ReactNode;
  intro?: ReactNode;
  extras?: ReactNode;
  /** The "Draw a box" tool on page 1 (on unless turned off). */
  boxTool?: boolean;
  /** ``ai`` is the screen's Ask AI, whose answer shows in the file's details. */
  headerActions?: { ai: FilingAI };
  /** A narrow panel (a collection): Relatives starts folded. */
  compactRelatives?: boolean;
  /** The icon row (``FileActionIcons``), under the header. Its blocks in
   * the skeleton's order: ``extras`` (a collection's Group) sits under the collections, and
   * Restore, Put in tray and Back to inbox are in the icon rows. */
  actions?: ReactNode;
  /** The summary block, where the screen has its own (a tray's file picker). */
  summary?: ReactNode;
  /** A tray item that is not listed among the file's items (the one being viewed). */
  hideItem?: number;
}) {
  // A file in ##. To Delete is read-only until it is restored
  const readOnly = toDeleteReason(file.path);
  // A link stands for its target, which has its own panel
  const relatives = !readOnly && !file.is_link && !file.is_dir && file.path !== null;
  return (
    <FileMeta key={`meta-${file.drive_id}`} file={file} disabled={disabled} ai={headerActions?.ai}>
      {(meta) => {
        return (
        <FilePanelSkeleton
          header={
            <>
              {meta.header}
              {!readOnly && <ChangedNotice driveId={file.drive_id} />}
              {intro}
            </>
          }
          actions={actions}
          tags={meta.tags}
          collections={<FileCollections driveId={file.drive_id} hideItem={hideItem} readOnly={readOnly} />}
          group={extras}
          summary={summary ?? <SummaryBox driveId={file.drive_id} readOnly={readOnly} />}
          relatives={
            relatives && file.path !== null ? (
              <>
                <FoundIdentifiers driveId={file.drive_id} />
                <RelativesBlock compact={compactRelatives} file={{ ...file, path: file.path, name: file.name ?? null }} />
              </>
            ) : undefined
          }
          preview={
            <FilePreview
              file={preview}
              boxTool={boxTool ? {} : undefined}
              extraTools={tools}
            />
          }
          notes={<SavedNote kind="file" target={file.drive_id} label="Note on this file" readOnly={readOnly} />}
        />
        );
      }}
    </FileMeta>
  );
}

/** A selected folder in Browse: its name and path, the collections it is in (× takes
 * it out) and the field that adds it to more. A folder in a collection brings everything in it,
 * including what is added later. ``refusal``: why it cannot be added (the app's areas). */
export function FolderPanel({
  folder,
  refusal,
  restore,
  moveTo,
  rename,
}: {
  folder: { drive_id: string; name: string; path: string };
  refusal: string | null;
  /** A folder in To Delete: Restore it to where it was or to the inbox. */
  restore?: (to: RestoreTo) => void;
  /** Move to… for this folder (Browse). */
  moveTo?: FolderMoveTo;
  /** Rename… for this folder, in place (Browse). */
  rename?: FolderMoveTo;
}) {
  return (
    <div className="file-panel folder-panel">
      <header className="file-meta-head">
        <div className="file-meta-title">
          <h2>{visible(folder.name)}</h2>
        </div>
        <p className="current-path">
          <code>
            <Breakable text={folder.path} />
          </code>
        </p>
      </header>
      <p className="hint">
        Added to a collection, a folder brings everything in it, also what is put in it later. Enter opens it.
      </p>
      <FolderActions
        key={folder.drive_id}
        driveId={folder.drive_id}
        refusal={refusal}
        restore={inToDelete(folder.path) ? restore : undefined}
        moveTo={moveTo}
        rename={rename}
      />
    </div>
  );
}
