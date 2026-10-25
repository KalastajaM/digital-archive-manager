/** The Index sheet, opened from the status line at the sidebar's foot: how many files
 * are searchable, waiting, not readable or failed, and the files whose text could not
 * be read. Each row can be retried, opened or shown in Finder; "Retry all"
 * queues every listed error again. Unsupported types (no text to read) are listed on
 * request only: nothing is wrong with them. Outcomes show on the sheet's own status
 * line (a toast would sit under the modal sheet). */
import { RotateCw } from "lucide-react";
import { useRef, useState } from "react";
import {
  errorText,
  type IndexProblem,
  type IndexProblems,
  type IndexSummary,
  useIndexErrors,
  useIndexSummary,
  usePage1Backfill,
  useRetryIndex,
} from "../api/client";
import { groupDigits, plural } from "../format";
import { visible } from "../text";
import { DialogStatus, InlineResults, LaunchButtons, useDialogStatus, useFileLaunch } from "./FileLaunch";
import { IconButton } from "./ui/IconButton";
import { Sheet } from "./ui/Sheet";
import { Tag } from "./ui/Tag";

export const UNSUPPORTED_HINT = "These can't be read for text; the files themselves are fine";
const RETRY_BUSY = "A retry is still being queued";

function ProblemRow({ problem, retrying, onRetry }: { problem: IndexProblem; retrying: boolean; onRetry: () => void }) {
  const launch = useFileLaunch(problem.drive_id);
  const unsupported = problem.state === "unsupported";
  return (
    <li className="index-problem">
      <div className="index-problem-main">
        <p className="index-problem-name">
          {visible(problem.name)}
          {unsupported && (
            <Tag tone="grey" className="index-problem-tag">
              Not readable
            </Tag>
          )}
        </p>
        <p className="index-problem-path">
          <code>{visible(problem.path)}</code>
        </p>
        <p className={unsupported ? "index-problem-reason hint" : "index-problem-reason"}>
          {problem.reason
            ? visible(problem.reason)
            : unsupported
              ? "No text to read in this type"
              : "No reason was stored"}
        </p>
      </div>
      <div className="index-problem-actions">
        <IconButton
          icon={<RotateCw size={16} strokeWidth={1.75} />}
          label={`Retry ${visible(problem.name)}`}
          disabled={retrying}
          disabledReason={retrying ? RETRY_BUSY : undefined}
          onClick={onRetry}
        />
        <LaunchButtons launch={launch} />
      </div>
    </li>
  );
}

/** "1 240 .heic, 380 .mov, 1 without extension". */
export function typeSummary(byType: IndexProblems["unsupported_by_type"]): string {
  return byType
    .map(({ ext, count }) => `${groupDigits(count)} ${ext ? `.${visible(ext)}` : "without extension"}`)
    .join(", ");
}

const STATE_NOTES: [key: "searchable" | "waiting" | "not_readable" | "errors" | "missing", label: string, note: string][] = [
  ["searchable", "Searchable", "The text of these files is indexed, so search finds them by their content."],
  ["waiting", "Waiting", "Not read yet, or waiting for Google Drive to download them."],
  [
    "not_readable",
    "Not readable",
    "The app has no reader for this type; the file is still archived and findable by name.",
  ],
  ["errors", "Errors", "Reading these failed. Retrying may help."],
  ["missing", "Missing", "Gone from the archive folder since the last scan."],
];

/** "about 3 h left at 30 files a minute" (nothing when the rate is not known yet). */
export function timeLeft(remaining: number, perMinute: number | null | undefined): string | null {
  if (!perMinute || perMinute <= 0 || remaining <= 0) return null;
  const minutes = Math.ceil(remaining / perMinute);
  const left =
    minutes < 60 ? `${minutes} min` : minutes < 60 * 48 ? `${Math.round(minutes / 60)} h` : `${Math.round(minutes / 1440)} days`;
  return `about ${left} left at ${perMinute < 10 ? perMinute.toFixed(1) : Math.round(perMinute)} files a minute`;
}

/** The page-1 pass: how far it has come, what waits and why, the switch for reading older
 * documents in the background, and an estimate of the time left. */
function Page1Block({ page1 }: { page1: IndexSummary["page1"] }) {
  const backfill = usePage1Backfill();
  const left = timeLeft(page1.total - page1.read, page1.rate_per_min);
  const blocked = page1.blocked ?? [];
  return (
    <section className="index-page1" aria-label="Page 1">
      <p>
        Page 1 read for {groupDigits(page1.read)} of {groupDigits(page1.total)} documents
        {left ? `, ${left}` : ""}
      </p>
      {blocked.length > 0 && (
        <div className="index-page1-blocked" role="group" aria-label="Waiting because page 1 cannot be read now">
          {blocked.map((b) => (
            <p key={b.reason} className="hint">
              {groupDigits(b.count)} waiting: {visible(b.reason)}
            </p>
          ))}
        </div>
      )}
      <label className="check">
        <input
          type="checkbox"
          checked={page1.backfill}
          disabled={backfill.isPending}
          onChange={(e) => backfill.mutate(e.target.checked)}
        />
        Read page 1 of older documents in the background
      </label>
      {backfill.isError && (
        <p className="error" role="alert">
          {visible(errorText(backfill.error))}
        </p>
      )}
    </section>
  );
}

function SummaryBlock() {
  const summary = useIndexSummary();
  if (summary.isError) {
    return (
      <p className="error" role="alert">
        Could not load the totals: {visible(errorText(summary.error))}
      </p>
    );
  }
  if (!summary.data) return null;
  const data = summary.data;
  return (
    <>
      <dl className="index-summary" aria-label="Totals">
        {STATE_NOTES.map(([key, label, note]) => (
          <div key={key} className="index-summary-row">
            <dt>{label}</dt>
            <dd>{groupDigits(data[key])}</dd>
            <dd className="hint">{note}</dd>
          </div>
        ))}
      </dl>
      {data.page1 && <Page1Block page1={data.page1} />}
    </>
  );
}

export function IndexErrorsSheet({ onClose }: { onClose: () => void }) {
  const [all, setAll] = useState(false);
  const list = useIndexErrors(all);
  const retry = useRetryIndex();
  const status = useDialogStatus(); // outcomes show here: a toast would sit under the sheet
  const inFlight = useRef(false); // synchronous: a second click in the same batch sees it
  const problems = list.data?.rows ?? [];
  const notShown = Math.max(0, (list.data?.total ?? 0) - problems.length);
  const byType = all ? (list.data?.unsupported_by_type ?? []) : [];
  const errors = problems.filter((p) => p.state === "error");
  const retryAllBlocked = retry.isPending
    ? RETRY_BUSY
    : errors.length === 0
      ? list.isPending
        ? "Loading the list"
        : "No errors to retry: unsupported files have no text to read"
      : null;

  const queue = async (ids: string[]) => {
    if (inFlight.current || ids.length === 0) return;
    inFlight.current = true;
    try {
      const { queued } = await retry.mutateAsync(ids);
      status.report({ kind: "info", text: `Queued ${plural(queued, "file")} for indexing again` });
    } catch (e) {
      status.report({ kind: "error", text: `Could not retry: ${visible(errorText(e))}` });
    } finally {
      inFlight.current = false;
    }
  };

  return (
    <Sheet
      open
      className="index-errors"
      title="Index"
      onClose={onClose}
      footer={
        <>
          <button type="button" onClick={onClose}>
            Close
          </button>
          <span className="button-wrap" data-tip={retryAllBlocked ?? undefined}>
            <button
              type="button"
              className="primary"
              disabled={retryAllBlocked !== null}
              onClick={() => void queue(errors.map((p) => p.drive_id))}
            >
              Retry all
            </button>
          </span>
        </>
      }
    >
      <InlineResults.Provider value={status.report}>
        <SummaryBlock />
        <label className="index-errors-toggle">
          <input type="checkbox" checked={all} onChange={(e) => setAll(e.target.checked)} /> Show not readable files
        </label>
        <p className="hint index-errors-toggle-hint">{UNSUPPORTED_HINT}</p>
        {list.isError ? (
          <p className="error" role="alert">
            Could not load the list: {visible(errorText(list.error))}
          </p>
        ) : list.isPending ? (
          <p className="hint" role="status">
            Loading…
          </p>
        ) : problems.length === 0 ? (
          <p className="placeholder">{all ? "Nothing to list" : "No index errors"}</p>
        ) : (
          <ul className="index-problems" aria-label="Files">
            {problems.map((p) => (
              <ProblemRow
                key={p.drive_id}
                problem={p}
                retrying={retry.isPending}
                onRetry={() => void queue([p.drive_id])}
              />
            ))}
          </ul>
        )}
        {!list.isPending && !list.isError && (notShown > 0 || byType.length > 0) && (
          <div className="index-errors-more">
            {notShown > 0 && <p className="hint">{groupDigits(notShown)} more not shown</p>}
            {byType.length > 0 && <p className="hint">Not readable by type: {typeSummary(byType)}</p>}
          </div>
        )}
        <DialogStatus status={status} />
      </InlineResults.Provider>
    </Sheet>
  );
}

/** The status line is a button that opens the sheet (render ``view`` outside the
 * line's <p>: a dialog may not sit inside a paragraph). */
export function useIndexErrorsSheet() {
  const [open, setOpen] = useState(false);
  return {
    open: () => setOpen(true),
    view: open ? <IndexErrorsSheet onClose={() => setOpen(false)} /> : null,
  };
}
