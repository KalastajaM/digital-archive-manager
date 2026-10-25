import type { MaintenanceJob } from "../../api/client";
import { formatSize, groupDigits } from "../../format";
import { visible } from "../../text";

/** How far a running check is: a bar, and in words how many files and how many bytes. */
export function JobProgress({ job, noun = "files" }: { job: MaintenanceJob; noun?: string }) {
  const known = job.total > 0;
  return (
    <div className="job-progress" role="status">
      <progress
        aria-label="Progress"
        value={known ? job.done : undefined}
        max={known ? job.total : undefined}
      />
      <p className="hint">
        {known
          ? `${groupDigits(Math.min(job.done + 1, job.total))} of ${groupDigits(job.total)} ${noun}`
          : "Looking through the index..."}
        {job.bytes_total > 0 && ` (${formatSize(job.bytes_done)} of ${formatSize(job.bytes_total)})`}
        {job.current && <>: <span className="job-current">{visible(job.current)}</span></>}
      </p>
    </div>
  );
}
