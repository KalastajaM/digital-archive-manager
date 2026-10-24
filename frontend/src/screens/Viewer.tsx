/** The viewer window (``/viewer/:driveId``, opened by "Open in window"): one document's
 * zoomable preview and its details, without the sidebar. By default it follows the
 * selection of the window that opened it; the pin keeps it on this document. */
import { Pin, PinOff } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { errorText, useFileDetail, useInbox } from "../api/client";
import { FileDetails, folderOf, scannedFields } from "../components/FileDetails";
import { FilePreview } from "../components/FilePreview";
import { IconButton } from "../components/ui/IconButton";
import { Toolbar } from "../components/ui/Toolbar";
import { useSelectionFollower } from "../selection";
import { visible } from "../text";
import { MarkToggles } from "../components/MarkToggles";
import { deletionRefusal } from "../components/MoveTo";
import { useToast } from "../components/Toasts";
import { isTrashKey, TrashButton, useTrash } from "../components/Trash";
import { useKeydown } from "../keyboard";

export default function Viewer() {
  const { driveId = "" } = useParams();
  const navigate = useNavigate();
  const [follow, setFollow] = useState(true);
  const followed = useSelectionFollower(follow);
  useEffect(() => {
    if (follow && followed && followed !== driveId) {
      navigate(`/viewer/${encodeURIComponent(followed)}`, { replace: true });
    }
  }, [follow, followed, driveId, navigate]);

  const detail = useFileDetail(driveId);
  // The scan's fields are known for inbox documents only.
  const entry = useInbox().data?.find((e) => e.record.drive_id === driveId);
  const record = detail.data?.record;
  const name = record ? (record.name ?? record.path) : "";
  useEffect(() => {
    if (name) document.title = `${name} — dam`;
  }, [name]);

  // Trash (the bin, ⌘⌫): this document; a preview for another one (the window followed
  // the selection meanwhile) is dropped. A refusal known up front is said, never silent.
  const trash = useTrash();
  const toast = useToast();
  const trashRefusal = record ? deletionRefusal(record.path, record.marks) : null;
  const trashIt = () => {
    if (!record) return;
    if (trashRefusal) toast({ kind: "info", text: trashRefusal });
    else trash.start([record.drive_id], { current: () => [driveIdRef.current], links: record.is_link });
  };
  const driveIdRef = useRef(driveId);
  driveIdRef.current = driveId;
  useKeydown((e) => {
    if (!isTrashKey(e)) return;
    e.preventDefault();
    trashIt();
  });

  const toggle = (
    <IconButton
      icon={follow ? <Pin /> : <PinOff />}
      label="Follow selection"
      pressed={follow}
      onClick={() => setFollow((f) => !f)}
    />
  );
  let body;
  if (detail.isPending) body = <p className="placeholder">Loading…</p>;
  else if (detail.isError) {
    body = (
      <p className="error" role="alert">
        Could not load this file. {visible(errorText(detail.error))}
      </p>
    );
  } else {
    const file = detail.data.record;
    body = (
      <div className="viewer-body">
        <div className="viewer-preview preview-fill">
          <FilePreview file={file} windowButton={false} goToTarget={false} boxTool={{}} />
        </div>
        <aside className="viewer-details">
          <FileDetails file={file} scanned={entry ? scannedFields(entry) : []} links={false} />
        </aside>
      </div>
    );
  }
  return (
    <div className="viewer">
      <Toolbar
        title={record ? visible(name) : "Viewer"}
        subtitle={
          record && (
            <>
              {visible(folderOf(record.path))}
              {!follow && <span className="viewer-pinned">Pinned</span>}
            </>
          )
        }
        actions={
          <>
            {toggle}
            {record && <MarkToggles driveId={record.drive_id} name={name} marks={record.marks} />}
            {record && <TrashButton disabled={trash.busy} disabledReason={trashRefusal} onClick={trashIt} />}
          </>
        }
      />
      {body}
      {trash.view}
    </div>
  );
}
