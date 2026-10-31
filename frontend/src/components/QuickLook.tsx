/** Quick Look: a near full-window look at one document of a list, with the zoomable
 * preview and the document's details beside it. A modal <dialog>, so the page's own
 * shortcuts are off while it is open (``dialogOpen()``); its keys (Space/Esc to close,
 * ←/→ and j/k to move) are handled by ``useQuickLook``. */
import { ChevronLeft, ChevronRight, Link2, Network, X } from "lucide-react";
import { type KeyboardEvent, useEffect, useMemo, useRef, useState } from "react";
import { isTyping } from "../keyboard";
import { visible } from "../text";
import { FileDetails } from "./FileDetails";
import { DialogStatus, InlineResults, useDialogStatus } from "./FileLaunch";
import { FIT_LEVEL, FilePreview, type ZoomControl, ZoomKeys, ZOOM_LEVELS } from "./FilePreview";
import { IconButton } from "./ui/IconButton";
import { alignPages, alignScroll, MoveLink, newHub } from "./moveTogether";
import { MarkToggles } from "./MarkToggles";
import type { BoxTool } from "./zones/PageBoxes";
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
  /** The box tool of the page-1 preview (``testRule``: draw the rule being tested). */
  boxTool?: BoxTool;
  /** Compare mode (Relatives): ``subject`` is shown in a second pane beside the shown file,
   * with what they share below and the verdict keys: N Not related, → Skip, Y Related and
   * next (which only moves on: being related is computed, never stored). This mode handles
   * its own keys (Space, ←/→, j/k, N, Y, and + / - / 0 for the pane last clicked, or for
   * both while "Zoom together" is on), so the host adds none. */
  /** Relatives of the shown file (``useQuickLook`` closes this and opens them). */
  onRelatives?: () => void;
  compare?: {
    subject: QLFile;
    shared: (file: QLFile) => string[];
    /** Why the AI picked the shown file (a sentence), on its own line above the verdict. */
    reason?: (file: QLFile) => string | null;
    onNotRelated: (file: QLFile) => void;
    /** Show in folder for either pane's file (the caller closes Quick Look and navigates). */
    showInFolder?: (file: QLFile) => void;
  };
};

export function QuickLook({ files, index, onIndex, onClose, status: given, trash, boxTool = {}, onRelatives, compare }: Props) {
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
  const subjectZoom = useState(FIT_LEVEL);
  // Compare mode: each pane zooms, scrolls and turns pages on its own (documents of
  // different sizes need different zooms), unless "Move together" is on; the keys go to
  // the pane last clicked or focused.
  const [together, setTogether] = useState(false);
  const [active, setActive] = useState<"subject" | "file">("file");
  const [hub] = useState(newHub);
  const subjectLink = useMemo(() => ({ hub, pane: "subject" }), [hub]);
  const fileLink = useMemo(() => ({ hub, pane: "file" }), [hub]);
  useEffect(() => {
    hub.on = together;
    // the other pane comes to where the one in use is: its page now, its scroll once the
    // shared zoom has drawn
    if (!together) return;
    alignPages(hub, active);
    const frameId = requestAnimationFrame(() => alignScroll(hub, active));
    return () => cancelAnimationFrame(frameId);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- only when switched on
  }, [hub, together]);
  // the next relative opens on the page this file is on
  const fileId = file.drive_id;
  useEffect(() => {
    if (hub.on) alignPages(hub, "subject");
  }, [hub, fileId]);
  const name = visible(qlName(file));
  // Open / Show in Finder outcomes: on this line, not as toasts under the modal
  const own = useDialogStatus();
  const status = given ?? own;
  const { clear } = status;
  useEffect(() => clear(), [file.drive_id, clear]); // another document: the old result goes
  const last = index >= files.length - 1;
  const related = () => (last ? onClose() : onIndex(index + 1));
  const onCompareKey = (e: KeyboardEvent<HTMLDialogElement>) => {
    if (!compare || e.metaKey || e.ctrlKey || e.altKey || isTyping(e.target)) return;
    // Space on one of Quick Look's own buttons (Close, Skip, zoom…) presses that button
    if (e.key === " " && e.target instanceof Element && e.target.closest("button")) return;
    const key = e.key.toLowerCase();
    const step = e.key === "+" || e.key === "=" ? 1 : e.key === "-" ? -1 : e.key === "0" ? 0 : null;
    if (step !== null) {
      if (!e.repeat) zoomBy(together || active === "file" ? zoomControl : subjectZoom, step);
      e.preventDefault();
      return;
    }
    if (e.key === " ") onClose();
    else if (e.key === "ArrowRight" || key === "j") {
      if (!last) onIndex(index + 1);
    } else if (e.key === "ArrowLeft" || key === "k") {
      if (index > 0) onIndex(index - 1);
    } else if (key === "n") compare.onNotRelated(file);
    else if (key === "y") related();
    else return;
    e.preventDefault();
  };
  const shared = compare?.shared(file) ?? [];
  const reason = compare?.reason?.(file) ?? null;
  const toggleTogether = () => {
    // apart again: this file keeps the shared zoom, so nothing jumps; together: both take
    // the zoom of the pane in use
    if (together) subjectZoom[1](zoomControl[0]);
    else if (active === "subject") zoomControl[1](subjectZoom[0]);
    setTogether(!together);
  };
  const paneClass = (pane: "subject" | "file") =>
    `quicklook-pane${!together && active === pane ? " active" : ""}`;
  return (
    <dialog
      ref={ref}
      className={compare ? "quicklook compare" : "quicklook"}
      aria-label={`Quick Look: ${name}`}
      tabIndex={-1}
      onKeyDown={compare ? onCompareKey : undefined}
      onCancel={(e) => {
        e.preventDefault();
        onClose();
      }}
    >
      <div className="quicklook-bar">
        <div className="quicklook-title">
          <h2>{compare ? "Is this related?" : name}</h2>
          <span className="quicklook-count">
            {index + 1} of {files.length}
          </span>
        </div>
        <div className="quicklook-nav">
          <InlineResults.Provider value={status.report}>
            <MarkToggles driveId={file.drive_id} name={qlName(file)} path={file.path} />
          </InlineResults.Provider>
          {onRelatives && !compare && (
            <IconButton icon={<Network />} label="Relatives" tip="Relatives: the files this one belongs with" onClick={onRelatives} />
          )}
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
          {/* Close at the far right, as in every pane with one */}
          <IconButton icon={<X />} label="Close" shortcut="Space" className="tip-end" onClick={onClose} />
        </div>
      </div>
      <DialogStatus status={status} />
      {compare ? (
        <>
          <ZoomKeys.Provider value={false}>
          <div className="quicklook-body">
            <div
              className={paneClass("subject")}
              onPointerDown={() => setActive("subject")}
              onFocus={() => setActive("subject")}
            >
              <p className="quicklook-pane-label">
                This file: <span className="quicklook-pane-name">{visible(qlName(compare.subject))}</span>
              </p>
              <div className="quicklook-preview preview-fill">
                <MoveLink.Provider value={subjectLink}>
                  <FilePreview
                    file={compare.subject}
                    zoomControl={together ? zoomControl : subjectZoom}
                    showInFolder={compare.showInFolder && (() => compare.showInFolder?.(compare.subject))}
                  />
                </MoveLink.Provider>
              </div>
            </div>
            <div className={paneClass("file")} onPointerDown={() => setActive("file")} onFocus={() => setActive("file")}>
              <p className="quicklook-pane-label">
                <span className="quicklook-pane-name">{name}</span>
              </p>
              <div className="quicklook-preview preview-fill">
                <InlineResults.Provider value={status.report}>
                  <MoveLink.Provider value={fileLink}>
                    <FilePreview
                      file={file}
                      beforeGoToTarget={onClose}
                      zoomControl={zoomControl}
                      boxTool={boxTool}
                      showInFolder={compare.showInFolder && (() => compare.showInFolder?.(file))}
                    />
                  </MoveLink.Provider>
                </InlineResults.Provider>
              </div>
            </div>
          </div>
          </ZoomKeys.Provider>
          {reason && (
            <p className="quicklook-reason">
              <span className="rel-ai-badge">AI</span> {reason}
            </p>
          )}
          <div className="quicklook-verdict">
            <button
              type="button"
              className="quicklook-zoom-together"
              aria-pressed={together}
              title={
                together
                  ? "Both previews zoom, scroll and turn pages as one. Click to move each on its own"
                  : "Each preview moves on its own (+ / - zoom the one last clicked). Click to zoom, scroll and turn pages in both as one"
              }
              onClick={toggleTogether}
            >
              <Link2 size={14} aria-hidden="true" /> Move together
            </button>
            {shared.length > 0 && <span className="quicklook-shared-label">In common</span>}
            <ul className="quicklook-shared" aria-label="In common">
              {shared.map((s) => (
                <li key={s} className="tag tag-grey" title={s}>
                  {s}
                </li>
              ))}
            </ul>
            {/* it marks the pair (with Undo): kept away from Related, next */}
            <button type="button" className="rel-not-related" onClick={() => compare.onNotRelated(file)}>
              Not related <kbd>N</kbd>
            </button>
            <button type="button" disabled={last} onClick={() => onIndex(index + 1)}>
              Skip <kbd>→</kbd>
            </button>
            <button type="button" className="primary" onClick={related}>
              Related, next <kbd>Y</kbd>
            </button>
          </div>
        </>
      ) : (
      <div className="quicklook-body">
        <div className="quicklook-preview preview-fill">
          <InlineResults.Provider value={status.report}>
            <FilePreview file={file} beforeGoToTarget={onClose} zoomControl={zoomControl} boxTool={boxTool} />
          </InlineResults.Provider>
        </div>
        <aside className="quicklook-details">
          <FileDetails file={file} scanned={file.scanned} />
        </aside>
      </div>
      )}
    </dialog>
  );
}

/** One zoom step in (1) or out (-1), or back to Fit (0). */
function zoomBy([, setLevel]: ZoomControl, step: number) {
  setLevel((l) => (step === 0 ? FIT_LEVEL : Math.min(ZOOM_LEVELS.length - 1, Math.max(0, l + step))));
}
