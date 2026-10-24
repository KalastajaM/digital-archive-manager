/** Page 1 of a document as a picture with areas drawn over it, outside the preview (Settings:
 * Test a document, and a rule's areas on a sample page). */
import { useState } from "react";
import { type Area, type PageBox, pageUrl, rawUrl } from "../../api/client";
import { AreaLayer } from "./AreaLayer";

/** A PDF is shown as its first page; anything else as the file itself (an image). */
export const sampleUrl = (driveId: string, ext: string | null | undefined) =>
  (ext ?? "").toLowerCase() === "pdf" ? pageUrl(driveId, 1, 900) : rawUrl(driveId);

export function SamplePage({
  driveId,
  ext,
  areas,
  person = null,
  personLine = null,
}: {
  driveId: string;
  ext: string | null | undefined;
  areas: readonly Area[];
  person?: string | null;
  personLine?: { box: PageBox } | null;
}) {
  const [failed, setFailed] = useState(false);
  if (failed) return <p className="hint">There is no picture of page 1 to show.</p>;
  return (
    <div className="sample-page">
      <span className="page-layer">
        <img src={sampleUrl(driveId, ext)} alt="Page 1" draggable={false} onError={() => setFailed(true)} />
        <AreaLayer areas={areas} person={person} personLine={personLine} />
      </span>
    </div>
  );
}
