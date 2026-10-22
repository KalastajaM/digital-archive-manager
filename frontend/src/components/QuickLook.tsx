/** Quick Look: a near full-window look at one document of a list, with the zoomable
 * preview and the document's details beside it. A modal <dialog>, so the page's own
 * shortcuts are off while it is open (``dialogOpen()``); its keys (Space/Esc to close,
 * ←/→ and j/k to move) are handled by ``useQuickLook``. */
import { ChevronLeft, ChevronRight, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { visible } from "../text";
import { FileDetails } from "./FileDetails";
import { DialogStatus, InlineResults, useDialogStatus } from "./FileLaunch";
import { FIT_LEVEL, FilePreview } from "./FilePreview";
import { IconButton } from "./ui/IconButton";
import { MarkToggles } from "./MarkToggles";
import { TrashButton } from "./Trash";

/** A document Quick Look can show; ``scanned`` are the scan's fields when known. */
export type QLFile = {
  drive_id: string;
  name: string | null;
  path: string;
  ext: string | null;
  /** a link previews as its target inside the archive */
  is_link?: boolean;
  /** the record's marks when known: an Important file's bin is disabled up front */
  marks?: readonly string[] | null;
  scanned?: [string, string][];
};

export const qlName = (f: QLFile) => f.name ?? f.path.slice(f.path.lastIndexOf("/") + 1);

type Props = {
  files: QLFile[];
  index: number;
  onIndex: (index: number) => void;
  onClose: () => void;
  /** The status line's state (``useQuickLook`` owns it); its own one otherwise. */
  status?: ReturnType<typeof useDialogStatus>;
  /** Trash for the shown file: ``refusal`` disables the bin, saying why. */
  trash?: { run: () => void; refusal: string | null; busy: boolean };
};

export function QuickLook({ files, index, onIndex, onClose, status: given, trash }: Props) {
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
  const file = files[index];
  // The zoom the user chose stays while paging through documents (a new Quick Look starts at Fit).
  const zoomControl = useState(FIT_LEVEL);
  const name = visible(qlName(file));
  // Open / Show in Finder outcomes: on this line, not as toasts under the modal
  const own = useDialogStatus();
  const status = given ?? own;
  const { clear } = status;
  useEffect(() => clear(), [file.drive_id, clear]); // another document: the old result goes
  return (
    <dialog
      ref={ref}
      className="quicklook"
      aria-label={`Quick Look: ${name}`}
      tabIndex={-1}
      onCancel={(e) => {
        e.preventDefault();
        onClose();
      }}
    >
      <div className="quicklook-bar">
        <IconButton icon={<X />} label="Close" shortcut="Space" onClick={onClose} />
        <div className="quicklook-title">
          <h2>{name}</h2>
          <span className="quicklook-count">
            {index + 1} of {files.length}
          </span>
        </div>
        <div className="quicklook-nav">
          <InlineResults.Provider value={status.report}>
            <MarkToggles driveId={file.drive_id} name={qlName(file)} />
          </InlineResults.Provider>
          {trash && <TrashButton disabled={trash.busy} disabledReason={trash.refusal} onClick={trash.run} />}
          <IconButton
            icon={<ChevronLeft />}
            label="Previous file"
            shortcut="←"
            disabled={index <= 0}
            onClick={() => onIndex(index - 1)}
          />
          <IconButton
            icon={<ChevronRight />}
            label="Next file"
            shortcut="→"
            disabled={index >= files.length - 1}
            onClick={() => onIndex(index + 1)}
          />
        </div>
      </div>
      <DialogStatus status={status} />
      <div className="quicklook-body">
        <div className="quicklook-preview preview-fill">
          <InlineResults.Provider value={status.report}>
            <FilePreview file={file} beforeGoToTarget={onClose} zoomControl={zoomControl} />
          </InlineResults.Provider>
        </div>
        <aside className="quicklook-details">
          <FileDetails file={file} scanned={file.scanned} />
        </aside>
      </div>
    </dialog>
  );
}
