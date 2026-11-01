/** Versions of a document, in the file's panel: which file is the latest, a notice on the
 * older ones, and the way to move the older ones into their folder's Archive subfolder.
 *
 * The server works the group out (``GET /api/files/{id}/versions``): editable files in one
 * folder whose names differ only by a date, a number or a word like "final". "Not a version"
 * takes a file out of this file's list for good (Show again brings it back). */
import { Eye, EyeOff } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { errorText, useVersionMark, useVersions, useVersionsDismissed, type VersionFile } from "../api/client";
import { plural, shortDate } from "../format";
import { visible } from "../text";
import { Collapsible } from "./Collapsible";
import { browseTo } from "./maintenance/ShowInBrowse";
import { folderLabel, useMoveFlow } from "./MoveTo";
import { QuickLook } from "./QuickLook";
import { undoAction, useToast } from "./Toasts";
import { IconButton } from "./ui/IconButton";

const dated = (mtime: number | null) => (mtime === null ? "" : shortDate(mtime));

/** Under the file's name: says so when a newer version of this document exists. */
export function VersionsNotice({ driveId }: { driveId: string }) {
  const { data } = useVersions(driveId);
  const latest = data?.files.find((f) => f.latest);
  const self = data?.files.find((f) => f.drive_id === driveId);
  if (!latest || latest.drive_id === driveId) return null;
  // a copy keeps its date: the same time is not newer, though one of them is marked Latest
  if (self?.mtime != null && latest.mtime != null && latest.mtime <= self.mtime) return null;
  const name = visible(latest.name);
  const date = dated(latest.mtime);
  return (
    <p className="versions-notice" role="status">
      Newer version:{" "}
      <Link to={browseTo(latest.path, latest.drive_id)} title={`Show ${name} in Browse`}>
        {name}
      </Link>
      {date && `, ${date}`}
    </p>
  );
}

export function VersionsBlock({ driveId }: { driveId: string }) {
  const { data } = useVersions(driveId);
  const marks = useVersionMark();
  const toast = useToast();
  const move = useMoveFlow();
  const [look, setLook] = useState<number | null>(null);
  const [showHidden, setShowHidden] = useState(false);
  if (!data || (data.files.length === 0 && data.hidden === 0)) return null;
  const others = data.files.filter((f) => f.drive_id !== driveId);
  const where = data.folder ? folderLabel(data.folder) : "";

  const mark = async (files: VersionFile[]) => {
    const results = await Promise.allSettled(
      files.map((f) => marks.mutateAsync({ driveId, other: f.drive_id, mark: "dismiss" })),
    );
    const done = files.filter((_, i) => results[i].status === "fulfilled");
    if (done.length > 0)
      toast({
        kind: "info",
        text: `${done.length === 1 ? visible(done[0].name) : plural(done.length, "file")} marked not a version`,
        action: undoAction(() =>
          done.forEach((f) => marks.mutate({ driveId, other: f.drive_id, mark: "restore" })),
        ),
      });
    const failed = results.find((r): r is PromiseRejectedResult => r.status === "rejected");
    if (failed) toast({ kind: "error", text: `Could not mark them: ${visible(errorText(failed.reason))}` });
  };

  return (
    <>
    <Collapsible
      name="versions"
      title="Versions"
      className="relatives versions"
      aside={data.files.length > 0 ? <span className="relatives-count">{data.files.length}</span> : undefined}
    >
      <div className="relatives-body">
        {data.files.length > 0 && (
          <ul className="relatives-list">
            {data.files.map((f, i) => {
              const name = visible(f.name);
              const self = f.drive_id === driveId;
              return (
                <li key={f.drive_id} className="version-row" data-drive-id={f.drive_id}>
                  {self ? (
                    <span className="version-name" title={name}>
                      {name}
                    </span>
                  ) : (
                    <Link
                      className="version-name"
                      to={browseTo(f.path, f.drive_id)}
                      title={`${name} (show in Browse)`}
                    >
                      {name}
                    </Link>
                  )}
                  {f.latest && <span className="tag tag-blue">Latest</span>}
                  {self && <span className="tag tag-grey">This file</span>}
                  {f.in_archive && <span className="tag tag-grey">Archived</span>}
                  <span className="version-date">{dated(f.mtime)}</span>
                  <span className="version-tools">
                    <IconButton
                      icon={<Eye size={14} />}
                      label={`Quick Look ${name}`}
                      tip="Quick Look"
                      onClick={() => setLook(i)}
                    />
                    {!self && (
                      <IconButton
                        icon={<EyeOff size={14} />}
                        label={`Not a version: ${name}`}
                        tip="Not a version: leave this file out of the list"
                        onClick={() => void mark([f])}
                      />
                    )}
                  </span>
                </li>
              );
            })}
          </ul>
        )}
        {data.files.length > 0 && (
          <div className="version-actions">
            {data.folder !== null && data.movable.length > 0 ? (
              <button
                type="button"
                disabled={move.busy}
                onClick={() => move.start({ ids: data.movable, folder: data.folder! })}
              >
                Move {data.movable.length} older to {baseFolder(where)}…
              </button>
            ) : (
              <span className="button-wrap" data-tip={data.blocked ?? undefined}>
                <button type="button" disabled title={data.blocked ?? undefined}>
                  Move older…
                </button>
              </span>
            )}
            <button type="button" onClick={() => void mark(others)}>
              None of these are versions
            </button>
          </div>
        )}
        {data.staying.length > 0 && (
          <p className="hint version-staying">
            {data.staying.length === 1 ? "1 file stays" : `${data.staying.length} files stay`}:{" "}
            {data.staying.map((s) => `${visible(s.name)} (${s.reason})`).join(", ")}
          </p>
        )}
        {data.hidden > 0 && (
          <button type="button" className="link-button version-hidden" onClick={() => setShowHidden((v) => !v)}>
            {data.hidden} marked not {data.hidden === 1 ? "a version" : "versions"}
          </button>
        )}
        {showHidden && data.hidden > 0 && <Hidden driveId={driveId} />}
      </div>
    </Collapsible>
    {/* outside the block, whose size container would trap a fixed sheet */}
    {move.view}
    {look !== null && data.files[look] && (
        <QuickLook
          files={data.files.map((f) => ({
            drive_id: f.drive_id,
            name: f.name,
            path: f.path,
            ext: f.name.includes(".") ? f.name.slice(f.name.lastIndexOf(".") + 1) : null,
          }))}
          index={look}
          onIndex={setLook}
          onClose={() => setLook(null)}
        />
      )}
    </>
  );
}

/** The last part of a folder's label: "Archive", not the whole way there. */
const baseFolder = (label: string) => label.slice(label.lastIndexOf("/") + 1);

function Hidden({ driveId }: { driveId: string }) {
  const list = useVersionsDismissed(driveId);
  const marks = useVersionMark();
  if (list.isError) return <p className="hint">Could not load them: {visible(errorText(list.error))}</p>;
  return (
    <ul className="relatives-dismissed">
      {(list.data?.dismissed ?? []).map((d) => (
        <li key={d.drive_id}>
          <span className="trunc" title={visible(d.path)}>
            {visible(d.name)}
          </span>
          <button
            type="button"
            className="link-button"
            aria-label={`Show ${visible(d.name)} again`}
            onClick={() => marks.mutate({ driveId, other: d.drive_id, mark: "restore" })}
          >
            Show again
          </button>
        </li>
      ))}
    </ul>
  );
}
