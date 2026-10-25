/** The selected file's side panel, the same in Browse and in a collection, laid out in the
 * file view's one block order (``FileView``): name and folder (editable), tags, the
 * file's collections, the summary, the screen's own block (``extras``: a collection's
 * group and Remove; then Put in tray and Back to inbox), the preview with ★ / ! and Ask AI
 * in its toolbar, and the note. A screen adds its own: ``view`` and ``tools`` in the
 * preview's toolbar and ``intro`` under the name. The toolbar keeps the app's one order:
 * view (Open, Show in Finder, ``view``: Quick Look), then ★ / !, then Ask AI, then
 * ``tools`` (the bin last). */
import type { ReactNode } from "react";
import { SummaryBox } from "../components/ai/SummaryBox";
import { FileMeta, type MetaFile } from "../components/FileMeta";
import { FileView } from "../components/FileView";
import { FilePreview, type PreviewFile } from "../components/FilePreview";
import { Breakable } from "../components/PlanPreview";
import { SavedNote } from "../components/SavedNote";
import { visible } from "../text";
import { type BackToInbox, FileActions, FileCollections, FolderActions } from "./FileActions";

export function FilePanel({
  file,
  preview,
  disabled = false,
  view,
  tools,
  intro,
  extras,
  backToInbox,
  boxTool = true,
}: {
  file: MetaFile;
  /** What the preview shows (Browse: a link's target). */
  preview: PreviewFile;
  /** Another change is under way: editing is off. */
  disabled?: boolean;
  view?: ReactNode;
  tools?: ReactNode;
  intro?: ReactNode;
  extras?: ReactNode;
  backToInbox?: BackToInbox;
  /** The "Draw a box" tool on page 1 (on unless turned off). */
  boxTool?: boolean;
}) {
  return (
    <FileMeta key={`meta-${file.drive_id}`} file={file} disabled={disabled}>
      {(meta) => (
        <FileView
          className="file-panel"
          header={
            <>
              {meta.header}
              {intro}
            </>
          }
          tags={meta.tags}
          collections={<FileCollections driveId={file.drive_id} />}
          summary={<SummaryBox driveId={file.drive_id} />}
          own={
            <>
              {extras}
              <FileActions driveId={file.drive_id} backToInbox={backToInbox} />
            </>
          }
          preview={
            <FilePreview
              file={preview}
              boxTool={boxTool ? {} : undefined}
              extraTools={
                <>
                  {view}
                  {meta.marks}
                  {meta.ask}
                  {tools}
                </>
              }
            />
          }
          notes={<SavedNote kind="file" target={file.drive_id} label="Note on this file" />}
        />
      )}
    </FileMeta>
  );
}

/** A selected folder in Browse: its name and path, the collections it is in (× takes
 * it out) and the field that adds it to more. A folder in a collection brings everything in it,
 * including what is added later. ``refusal``: why it cannot be added (the app's areas). */
export function FolderPanel({ folder, refusal }: { folder: { drive_id: string; name: string; path: string }; refusal: string | null }) {
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
      <FolderActions key={folder.drive_id} driveId={folder.drive_id} refusal={refusal} />
    </div>
  );
}
