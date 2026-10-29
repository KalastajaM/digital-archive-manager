/** The Index sheet, opened from the status line at the sidebar's foot: how many files
 * are searchable, waiting, not readable or failed, and the files whose text could not
 * be read. Each row can be retried, opened or shown in Finder; "Retry all"
 * queues every listed error again. Unsupported types (no text to read) are listed on
 * request only: nothing is wrong with them. Outcomes show on the sheet's own status
 * line (a toast would sit under the modal sheet). */
import { Check, LoaderCircle, RotateCw } from "lucide-react";
import { type ReactNode, useId, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  errorText,
  type IndexProblem,
  type IndexProblems,
  type IndexSummary,
  useIndexErrors,
  useIndexSummary,
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

/** The four states every file in the archive folder is in, one each: they add up to the
 * total. */
const PARTS: [key: "searchable" | "waiting" | "not_readable" | "errors", label: string, note: string][] = [
  ["searchable", "Searchable", "The text of these files is indexed, so search finds them by their content."],
  ["waiting", "Waiting", "Not read yet, or waiting for Google Drive to download them."],
  [
    "not_readable",
    "Not readable",
    "The app has no reader for this type; the file is still archived and findable by name.",
  ],
  ["errors", "Errors", "Reading these failed. Retrying may help."],
];

/** Whether an index is still reading (a turning circle) or done (a check). */
function ReadingIcon({ done }: { done: boolean }) {
  return done ? (
    <Check size={14} role="img" aria-label="Done" className="index-reading-done" />
  ) : (
    <LoaderCircle size={14} role="img" aria-label="Still reading" className="index-reading" />
  );
}

function SummaryRow({ label, value, note, part }: { label: string; value: ReactNode; note: ReactNode; part?: boolean }) {
  return (
    <div className={part ? "index-summary-row index-summary-part" : "index-summary-row"}>
      <dt>{label}</dt>
      <dd>{value}</dd>
      <dd className="hint">{note}</dd>
    </div>
  );
}

const minutesText = (minutes: number) =>
  minutes < 60 ? `${minutes} min` : minutes < 60 * 48 ? `${Math.round(minutes / 60)} h` : `${Math.round(minutes / 1440)} days`;

/** "about 3 h left at 30 files a minute" (nothing when the rate is not known yet). */
export function timeLeft(remaining: number, perMinute: number | null | undefined): string | null {
  if (!perMinute || perMinute <= 0 || remaining <= 0) return null;
  const left = minutesText(Math.ceil(remaining / perMinute));
  return `about ${left} left at ${perMinute < 10 ? perMinute.toFixed(1) : Math.round(perMinute)} files a minute`;
}

/** The time left for the page-1 pass from what is left of each kind and how fast each is read:
 * "about 40 min left (5 735 PDFs with text at 300 a minute, 12 scans at 30 a minute)". Null
 * when nothing is left or the speeds are not known. */
export function page1TimeLeft(page1: Omit<IndexSummary["page1"], "with_text">): string | null {
  const { text_left: text = 0, scans_left: scans = 0, text_per_min: fast = 0, scans_per_min: slow = 0 } = page1;
  if ((text > 0 && fast <= 0) || (scans > 0 && slow <= 0) || text + scans <= 0) return null;
  const minutes = Math.ceil(text / (fast || 1) + scans / (slow || 1));
  const parts = [
    ...(text > 0 ? [`${groupDigits(text)} PDFs with text at ${groupDigits(fast)} a minute`] : []),
    ...(scans > 0 ? [`${groupDigits(scans)} scans and photos at ${groupDigits(slow)} a minute`] : []),
  ];
  return `about ${minutesText(minutes)} left (${parts.join(", ")})`;
}

/** The page-1 pass as a row of the totals: how far it has come, the time left while it
 * runs, and what waits and why. Its switch and speed are in Settings, Indexing. */
function Page1Row({ page1, onSettings }: { page1: IndexSummary["page1"]; onSettings?: () => void }) {
  const done = page1.read >= page1.total;
  const left = done ? null : (page1TimeLeft(page1) ?? timeLeft(page1.total - page1.read, page1.rate_per_min));
  const blocked = page1.blocked ?? [];
  return (
    <div className="index-summary-row index-summary-part">
      <dt>Page 1</dt>
      <dd>
        {groupDigits(page1.read)} of {groupDigits(page1.total)} <ReadingIcon done={done} />
      </dd>
      <dd className="hint">
        Where the text sits on page 1, for rules by area
        {page1.with_text != null ? `; text on page 1 in ${groupDigits(page1.with_text)} of them` : ""}
        {left ? `; ${left}` : ""}.
        {blocked.map((b) => (
          <span key={b.reason} className="index-page1-blocked">
            {" "}
            {groupDigits(b.count)} waiting: {visible(b.reason)}.
          </span>
        ))}{" "}
        <Link to="/settings/indexing" onClick={onSettings}>
          Reading in the background and its speed: Settings
        </Link>
      </dd>
    </div>
  );
}

function SummaryBlock({ onSettings }: { onSettings?: () => void }) {
  const summary = useIndexSummary();
  const filesId = useId();
  const otherId = useId();
  if (summary.isError) {
    return (
      <p className="error" role="alert">
        Could not load the totals: {visible(errorText(summary.error))}
      </p>
    );
  }
  if (!summary.data) return null;
  const data = summary.data;
  const total = PARTS.reduce((sum, [key]) => sum + data[key], 0);
  const ids = data.identifiers;
  return (
    <>
      <div role="group" aria-labelledby={filesId} className="index-group">
        <h4 id={filesId}>Files in the archive</h4>
        <dl className="index-summary">
          <SummaryRow label="Total" value={groupDigits(total)} note="Every file in the archive folder, in one of these states:" />
          {PARTS.map(([key, label, note]) => (
            <SummaryRow key={key} label={label} value={groupDigits(data[key])} note={note} part />
          ))}
          <SummaryRow
            label="Missing"
            value={groupDigits(data.missing)}
            note="Gone from the archive folder since the last scan, so not in the total."
          />
        </dl>
      </div>
      <div role="group" aria-labelledby={otherId} className="index-group">
        <h4 id={otherId}>Other indexes</h4>
        <dl className="index-summary">
          {data.page1 && <Page1Row page1={data.page1} onSettings={onSettings} />}
          {ids && (
            <SummaryRow
              part
              label="Business IDs"
              value={
                <>
                  {groupDigits(ids.read)} of {groupDigits(ids.total)} <ReadingIcon done={ids.read >= ids.total} />
                </>
              }
              note={
                <>
                  Business IDs, IBANs and domains read from the searchable files&apos; text, for id: search and Relatives.
                  {ids.found.length > 0 &&
                    ` Found: ${ids.found
                      .map((f, i) => `${f.label} in ${groupDigits(f.count)}${i === 0 ? " files" : ""}`)
                      .join(", ")}.`}
                </>
              }
            />
          )}
        </dl>
      </div>
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
        <SummaryBlock onSettings={onClose} />
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
