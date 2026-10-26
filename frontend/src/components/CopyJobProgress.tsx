/** A move across disks runs in the background on the server (a verified copy of each file,
 * then its original to To Delete). This shows its progress wherever the move was started:
 * a dialog with files, bytes and the file being copied, and Stop (the file in hand is
 * finished first). The dialog can be hidden; a line then stays at the bottom until the
 * move is over, which ends in a toast with Undo. A move still running after a reload is
 * picked up again. Mounted once, in the app shell. */
import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { type CopyJob, errorText, getCopyJob, latestCopyJob, stopCopyJob } from "../api/client";
import { formatSize, plural } from "../format";
import { visible } from "../text";
import { useToast } from "./Toasts";
import { Sheet } from "./ui/Sheet";
import { useUndoConfirm } from "./UndoConfirm";

const STARTED = "dam:copy-job-started";
export const COPY_POLL_MS = 1000;

/** Tell the progress view that the server started the move ``jobId``. */
export function startedCopyJob(jobId: string) {
  window.dispatchEvent(new CustomEvent<string>(STARTED, { detail: jobId }));
}

export function CopyJobProgress() {
  const client = useQueryClient();
  const toast = useToast();
  const undo = useUndoConfirm();
  const [jobId, setJobId] = useState<string | null>(null);
  const [job, setJob] = useState<CopyJob | null>(null);
  const [open, setOpen] = useState(false);
  const [stopping, setStopping] = useState(false);

  const follow = (id: string) => {
    setJobId(id);
    setOpen(true);
    setStopping(false);
  };

  useEffect(() => {
    let live = true;
    latestCopyJob().then(
      (j) => {
        if (live && j && j.state === "running") {
          setJob(j);
          follow(j.job_id);
        }
      },
      () => undefined, // nothing to pick up
    );
    const onStarted = (e: Event) => follow((e as CustomEvent<string>).detail);
    window.addEventListener(STARTED, onStarted);
    return () => {
      live = false;
      window.removeEventListener(STARTED, onStarted);
    };
  }, []);

  useEffect(() => {
    if (jobId === null) return;
    let live = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const finish = (j: CopyJob) => {
      setJobId(null);
      setJob(null);
      setOpen(false);
      void client.invalidateQueries(); // files moved: every list that shows them is stale
      const r = j.result;
      const action = r?.batch_id ? { label: "Undo", run: () => undo.open({ batchId: r.batch_id }) } : undefined;
      if (j.state === "error" || !r) {
        toast({ kind: "error", text: `The move across disks failed: ${visible(j.error ?? "unknown error")}` });
      } else if (r.stopped) {
        toast({ kind: "warning", text: visible(r.message ?? r.error ?? "Stopped."), action });
      } else if (r.failed || r.error) {
        const at = r.failed ? ` (at ${visible(r.failed.src ?? r.failed.dst)})` : "";
        toast({ kind: "error", text: `Stopped: ${visible(r.error ?? "an operation failed")}${at}`, action });
      } else {
        // a folder move says it in the server's words ("Moved folder 2009 (2 files) to …")
        toast({ kind: "info", text: r.message ? visible(r.message) : `Moved ${plural(j.done, "file")} across disks`, action });
      }
    };
    const tick = async () => {
      try {
        const j = await getCopyJob(jobId);
        if (!live) return;
        if (j.state === "running") {
          setJob(j);
          timer = setTimeout(() => void tick(), COPY_POLL_MS);
        } else {
          finish(j);
        }
      } catch (e) {
        if (!live) return;
        setJobId(null);
        setJob(null);
        toast({ kind: "error", text: `Lost track of the move across disks: ${visible(errorText(e))}` });
      }
    };
    void tick();
    return () => {
      live = false;
      clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobId]);

  if (jobId === null || job === null) return null;
  const files = `${job.done} of ${plural(job.total, "file")}`;
  const stop = async () => {
    setStopping(true);
    try {
      await stopCopyJob(job.job_id);
    } catch (e) {
      setStopping(false);
      toast({ kind: "error", text: `Could not stop: ${visible(errorText(e))}` });
    }
  };
  if (!open) {
    return (
      <button type="button" className="copy-job-line" onClick={() => setOpen(true)}>
        {`Moving across disks: ${files}`}
      </button>
    );
  }
  return (
    <Sheet
      open
      title="Moving across disks"
      onClose={() => setOpen(false)}
      footer={
        <>
          <button type="button" onClick={() => setOpen(false)}>
            Hide
          </button>
          <button type="button" onClick={() => void stop()} disabled={stopping}>
            {stopping ? "Stopping…" : "Stop"}
          </button>
        </>
      }
    >
      <p>{`${files} (${formatSize(job.bytes_done)} of ${formatSize(job.bytes_total)})`}</p>
      <progress max={job.bytes_total || job.total || 1} value={job.bytes_total ? job.bytes_done : job.done} aria-label="Copied so far" />
      {job.current && <p className="hint">{`Copying ${visible(job.current)}`}</p>}
      <p className="hint">
        {stopping
          ? "Stopping after the file being copied. The files not reached stay where they are."
          : "Each file is copied and checked, then its original goes to To Delete. You can hide this and keep working."}
      </p>
    </Sheet>
  );
}
