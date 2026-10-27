/** "Left alone after a Drive restart": when Google Drive for desktop is restarted, the
 * links and folders dam made in ##. Ongoing and ##. Important can come back with a new
 * device number, and dam leaves them alone because they look different from before. When
 * only the device number changed, the same way for every changed entry under a folder,
 * Take over records the new number after a preview, so dam keeps them up to date again.
 * It changes only the app's own records, so it is not in Activity; Undo in the message
 * afterwards puts the old numbers back. */
import { HardDrive } from "lucide-react";
import { useState } from "react";
import { type RemountedRoot, useReadoptRemounted, useUndoReadopt } from "../../api/client";
import { plural } from "../../format";
import { visible } from "../../text";
import { undoAction, useBlockToastActions, useToast } from "../Toasts";
import { Sheet } from "../ui/Sheet";
import { Tag } from "../ui/Tag";
import { CheckCard, refusal } from "./ListChecks";
import { useMaintenanceJob } from "./useMaintenanceJob";

const entries = (roots: RemountedRoot[]) => roots.reduce((n, r) => n + r.entries.length, 0);

export function Remounted() {
  const check = useMaintenanceJob("remounted");
  const readopt = useReadoptRemounted();
  const undoReadopt = useUndoReadopt();
  const toast = useToast();
  const [preview, setPreview] = useState<RemountedRoot[] | null>(null);
  useBlockToastActions(readopt.isPending || undoReadopt.isPending || preview !== null);
  const roots = check.job?.remounted?.roots ?? [];

  const showPreview = (root: string) => {
    if (readopt.isPending) return;
    readopt
      .mutateAsync({ roots: [root], dry_run: true })
      .then((dry) => setPreview(dry.roots))
      .catch((e) => toast({ kind: "error", text: `Not taken over: ${visible(refusal(e))}` }));
  };
  const undo = (undoId: string) => {
    undoReadopt
      .mutateAsync(undoId)
      .then((back) => {
        if (back.roots.length > 0) toast({ kind: "info", text: `Put back the old number of ${plural(entries(back.roots), "entry", "entries")}` });
        if (back.errors.length > 0) toast({ kind: "error", text: visible(back.errors.join("; ")) });
        check.reload();
      })
      .catch((e) => toast({ kind: "error", text: `Not undone: ${visible(refusal(e))}` }));
  };
  const apply = (chosen: RemountedRoot[]) => {
    setPreview(null);
    readopt
      .mutateAsync({ roots: chosen.map((r) => r.root), dry_run: false })
      .then((done) => {
        const undoId = done.undo_id;
        if (done.roots.length > 0)
          toast({
            kind: "info",
            text: `Took over ${plural(entries(done.roots), "entry", "entries")}`,
            action: undoId ? undoAction(() => undo(undoId)) : undefined,
          });
        if (done.errors.length > 0) toast({ kind: "error", text: visible(done.errors.join("; ")) });
        check.reload();
      })
      .catch((e) => toast({ kind: "error", text: `Not taken over: ${visible(refusal(e))}` }));
  };

  return (
    <CheckCard
      title="Left alone after a Drive restart"
      icon={<HardDrive />}
      kind="remounted"
      intro="After Google Drive for desktop restarts, the links and folders dam made in ##. Ongoing and ##. Important can come back with a new device number. dam then leaves them alone, because they look different from before. When only the device number changed, the same way for every one of them, Take over lets dam keep them up to date again. Nothing on disk changes."
      check={check}
      empty="Every link and folder dam made is as it recorded it."
      found={roots.length > 0}
      summary={plural(entries(roots), "entry left alone", "entries left alone")}
    >
      {roots.length > 0 && (
        <ul className="check-list">
          {roots.map((r) => (
            <li key={r.root}>
              <span className="ref-entry">
                <span>
                  <code>{visible(r.root)}</code>: {plural(r.entries.length, "entry", "entries")}
                </span>
                <span className="hint">
                  {r.offered
                    ? `Only the device number changed (${visible(r.entries[0]?.old_dev ?? "")} → ${visible(r.entries[0]?.new_dev ?? "")}).`
                    : `Left alone: ${visible(r.reason ?? "")}.`}
                </span>
              </span>
              <span className="dup-actions">
                {r.offered ? (
                  <button type="button" disabled={readopt.isPending} onClick={() => showPreview(r.root)}>
                    Take over…
                  </button>
                ) : (
                  <Tag tone="orange">Needs a look</Tag>
                )}
              </span>
            </li>
          ))}
        </ul>
      )}
      {preview && (
        <Sheet
          open
          title={`Take over ${plural(entries(preview), "entry", "entries")}?`}
          onClose={() => setPreview(null)}
          footer={
            <>
              <button type="button" onClick={() => setPreview(null)}>
                Cancel
              </button>
              <button type="button" className="primary" disabled={readopt.isPending} onClick={() => apply(preview)}>
                Take over
              </button>
            </>
          }
        >
          <ul className="check-list">
            {preview.flatMap((r) =>
              r.entries.map((e) => (
                <li key={e.id}>
                  <span className="ref-entry">
                    <code>{visible(e.rel)}</code>
                    <span className="hint">
                      {e.kind === "link" ? "Link" : "Folder"}, device {visible(e.old_dev)} → {visible(e.new_dev)}
                    </span>
                  </span>
                </li>
              )),
            )}
          </ul>
          <p>
            This changes only the app&apos;s own records: nothing on disk changes, and dam keeps these entries up to date again.
            It is not listed in Activity; Undo in the message afterwards puts the old numbers back.
          </p>
        </Sheet>
      )}
    </CheckCard>
  );
}
