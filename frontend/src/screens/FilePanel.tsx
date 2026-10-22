/** The selected file's side panel, the same in Browse and in a collection: its name and
 * folder (editable), the preview with ★ / ! and Ask AI in its toolbar, the tags, its
 * trays and collections, then Put in tray, Add to collection, the summary and the note.
 * A screen adds its own: ``tools`` in the preview's toolbar, ``intro`` under the name
 * and ``extras`` before the shared actions (a collection's group and Remove). */
import type { ReactNode } from "react";
import { FileMeta, type MetaFile } from "../components/FileMeta";
import { FilePreview, type PreviewFile } from "../components/FilePreview";
import { type BackToInbox, FileActions, LinkBadges } from "./FileActions";

export function FilePanel({
  file,
  preview,
  disabled = false,
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
