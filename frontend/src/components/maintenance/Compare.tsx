/** Compare: two files of a same-name group next to each other, each in the zoomable
 * preview, with a Keep button under each so the choice can be made while looking. A modal
 * <dialog> in Quick Look's frame; Esc closes it. With more than two files each side has a
 * menu to pick which one it shows. One zoom for both sides, so pages line up. */
import { X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type { DupFile } from "../../api/client";
import { formatSize, shortDate } from "../../format";
import { visible } from "../../text";
import { DialogStatus, InlineResults, useDialogStatus } from "../FileLaunch";
import { FIT_LEVEL, FilePreview, type ZoomControl } from "../FilePreview";
import { IconButton } from "../ui/IconButton";
import { extOf } from "../../paths";

const folderOf = (path: string) => (path.includes("/") ? path.slice(0, path.lastIndexOf("/")) : "Top level");

function Side({
  files,
  shown,
  other,
  keep,
  label,
  zoomControl,
  onShow,
  onKeep,
}: {
  files: DupFile[];
  shown: DupFile;
  other: DupFile;
  keep: string;
  label: string;
  zoomControl: ZoomControl;
  onShow: (id: string) => void;
  onKeep: (id: string) => void;
}) {
  const newer = shown.mtime !== null && other.mtime !== null && shown.mtime !== other.mtime;
  return (
    <section className="compare-side" aria-label={label}>
      <div className="compare-head">
        {files.length > 2 ? (
          <select aria-label={`File on the ${label.toLowerCase()}`} value={shown.drive_id} onChange={(e) => onShow(e.target.value)}>
            {files.map((f) => (
              <option key={f.drive_id} value={f.drive_id} disabled={f.drive_id === other.drive_id}>
                {visible(f.path)}
              </option>
            ))}
          </select>
        ) : (
          <code title={visible(shown.path)}>{visible(folderOf(shown.path))}</code>
        )}
        <span className="hint">
          {formatSize(shown.size)}
          {shown.mtime !== null && `, ${shortDate(shown.mtime)}`}
          {newer && (shown.mtime! > other.mtime! ? " (newer)" : " (older)")}
        </span>
        {shown.drive_id === keep ? (
          <span className="compare-kept">Kept</span>
        ) : (
          <button type="button" className="link-button" onClick={() => onKeep(shown.drive_id)}>
            Keep this one
          </button>
        )}
      </div>
      <div className="quicklook-preview preview-fill">
        <FilePreview
          file={{ drive_id: shown.drive_id, path: shown.path, ext: extOf(shown.path) }}
          goToTarget={false}
          zoomControl={zoomControl}
        />
      </div>
    </section>
  );
}

export function Compare({
  name,
  files,
  keep,
  onKeep,
  onClose,
}: {
  name: string;
  files: DupFile[];
  keep: string;
  onKeep: (id: string) => void;
  onClose: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (!dialog.open) dialog.showModal();
    dialog.focus();
    return () => {
      if (dialog.open) dialog.close();
    };
  }, []);
  // the kept file on the left, the first other one on the right
  const [left, setLeft] = useState(keep);
  const [right, setRight] = useState(() => (files.find((f) => f.drive_id !== keep) ?? files[1]).drive_id);
  const zoomControl: ZoomControl = useState(FIT_LEVEL);
  const status = useDialogStatus();
  const byId = (id: string) => files.find((f) => f.drive_id === id) ?? files[0];
  const [a, b] = [byId(left), byId(right)];
  return (
    <dialog
      ref={ref}
      className="quicklook compare"
      aria-label={`Compare: ${visible(name)}`}
      tabIndex={-1}
      onCancel={(e) => {
        e.preventDefault();
        onClose();
      }}
    >
      <div className="quicklook-bar">
        <div className="quicklook-title">
          <h2>{visible(name)}</h2>
          <span className="quicklook-count">{files.length} files with this name</span>
        </div>
        <div className="quicklook-nav">
          <IconButton icon={<X />} label="Close" shortcut="Esc" className="tip-end" onClick={onClose} />
        </div>
      </div>
      <DialogStatus status={status} />
      <InlineResults.Provider value={status.report}>
        <div className="compare-body">
          <Side files={files} shown={a} other={b} keep={keep} label="Left" zoomControl={zoomControl} onShow={setLeft} onKeep={onKeep} />
          <Side files={files} shown={b} other={a} keep={keep} label="Right" zoomControl={zoomControl} onShow={setRight} onKeep={onKeep} />
        </div>
      </InlineResults.Provider>
    </dialog>
  );
}
