/** The selected file's side panel, the same in Browse and in a collection: its name and
 * folder (editable), the preview with ★ / ! and Ask AI in its toolbar, the tags, its
 * trays and collections, then Put in tray, Add to collection, the summary and the note.
 * A screen adds its own: ``view`` and ``tools`` in the preview's toolbar, ``intro`` under
 * the name and ``extras`` before the shared actions (a collection's group and Remove).
 * The toolbar keeps the app's one order: view (Open, Show in Finder, ``view``: Quick
 * Look), then ★ / !, then Ask AI, then ``tools`` (the bin last). */
import type { ReactNode } from "react";
import { FileMeta, type MetaFile } from "../components/FileMeta";
import { FilePreview, type PreviewFile } from "../components/FilePreview";
import { Breakable } from "../components/PlanPreview";
import { visible } from "../text";
import { type BackToInbox, FileActions, FolderActions, LinkBadges } from "./FileActions";

export function FilePanel({
  file,
  preview,
  disabled = false,
  view,
  tools,
  intro,
  extras,
  backToInbox,
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
}) {
  return (
    <div className="file-panel">
      <FileMeta key={`meta-${file.drive_id}`} file={file} disabled={disabled}>
        {(meta) => (
          <>
            {meta.header}
            {intro}
            <FilePreview
              file={preview}
              extraTools={
                <>
                  {view}
                  {meta.marks}
                  {meta.ask}
                  {tools}
                </>
              }
            />
            {meta.tags}
          </>
        )}
      </FileMeta>
      <div className="browse-detail-actions">
        <LinkBadges driveId={file.drive_id} />
      </div>
      {extras}
      <FileActions key={file.drive_id} driveId={file.drive_id} backToInbox={backToInbox} />
    </div>
  );
}

/** A selected folder in Browse: its name and path, the collections it is in (× takes
 * it out) and Add to collection. A folder in a collection brings everything in it,
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
      <div className="browse-detail-actions">
        <LinkBadges driveId={folder.drive_id} />
      </div>
      <FolderActions key={folder.drive_id} driveId={folder.drive_id} refusal={refusal} />
    </div>
  );
}
