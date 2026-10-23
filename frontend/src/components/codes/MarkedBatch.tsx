/** File N marked: every inbox file with a filing code, one row each, filed together in
 * one confirmed batch (one undo). Each row shows exactly the request the server built
 * for it, and exactly that request is sent: nothing is recomputed here. A flagged row
 * (unclear, codes disagree, needs input) starts unticked and says why. */
import { useEffect, useState } from "react";
import {
  type BatchRow,
  type CodeHit,
  errorText,
  type FileRequest,
  type InboxEntry,
  type TrayDef,
  useMarkedBatch,
} from "../../api/client";
import { fieldWord, formatField, plural } from "../../format";
import { visible } from "../../text";
import { type Filing, FILING_BUSY, FORM_CHANGED, followUpLines } from "../../screens/useFiling";
import { Tag } from "../ui/Tag";
import { TipButton } from "../ui/TipButton";
import { Toolbar } from "../ui/Toolbar";
import { Thumb } from "../Thumb";

/** How a code was found, in the words the owner uses. */
const VIA: Record<CodeHit["via"], string> = { folder: "folder", qr: "sticker", pen: "pen" };

/** "P (folder)", "A (sticker)", "D? (pen)" for an unclear reading. */
export const codeText = (hit: CodeHit) => `${hit.code}${hit.unclear ? "?" : ""} (${VIA[hit.via]})`;

/** Said when the rows changed while File was previewing (nothing was filed). */
export const MARKED_CHANGED = "The marked files changed; check the list and press File again";

/** Shown on a needs-input row's checkbox: it cannot be filed from here. */
export const FIX_IN_FORM = "Open it to fix it in the form";

/** A needs-input row would be refused (or file with a value missing): it cannot be
 * ticked. Conflict and unclear rows start unticked but can be ticked on purpose. */
const tickable = (row: BatchRow) => row.flag !== "needs_input";

/** Why a row starts unticked, or null. */
export function flagText(row: BatchRow): string | null {
  if (row.flag === "needs_input") return row.problem ? `Needs input: ${row.problem}` : "Needs input";
  if (row.flag === "conflict") return "Codes disagree";
  if (row.flag === "unclear") return row.problem ? `Unclear: ${row.problem}` : "Unclear";
  return null;
}

/** The row's tray line: "To pay: due date 15.10.2026 · amount 84,20 €", or "no tray". */
function trayLine(row: BatchRow, trays: TrayDef[]): string {
  const id = row.request.tray;
  if (!id) return "no tray";
  const tray = trays.find((t) => t.id === id);
  const values = Object.entries(row.tray_fields)
    .filter(([, value]) => value.trim() !== "")
    .map(([name, value]) => `${fieldWord(name)} ${formatField(tray?.fields?.[name]?.type, value)}`);
  const name = tray?.name ?? id;
  return values.length > 0 ? `${name}: ${values.join(" · ")}` : name;
}

/** The confirm's follow-up lines for a marked batch: one per file, since each row has
 * its own tray, fields, collections and tags ("<name>: Put in To pay: due date
 * 15.10.2026; Tags: bill"). */
export function markedFollowUps(requests: FileRequest[], trays: TrayDef[]): string[] {
  return requests.flatMap((r) => {
    const lines = followUpLines([r], trays);
    if (r.tags?.length) lines.push(`Tags: ${r.tags.join(", ")}`);
    return lines.length > 0 ? [`${r.name}: ${lines.join("; ")}`] : [];
  });
}

type Props = {
  /** The inbox entries, for each row's original name and thumbnail. */
  entries: InboxEntry[];
  trays: TrayDef[];
  filing: Filing;
  /** Show this file in the Inbox form (closes the panel). */
  onOpen: (driveId: string) => void;
  onClose: () => void;
};

function Row({
  row,
  entry,
  trays,
  ticked,
  disabled,
  onTick,
  onOpen,
}: {
  row: BatchRow;
  entry: InboxEntry | undefined;
  trays: TrayDef[];
  ticked: boolean;
  disabled: boolean;
  onTick: () => void;
  onOpen: () => void;
}) {
  const { request } = row;
  const flag = flagText(row);
  const from = entry ? (entry.record.name ?? entry.record.path) : null;
  // a sticker's tick boxes: what is marked once filed (sent as it is)
  const marks = [request.star && "Starred", request.important && "Important"].filter(Boolean);
  return (
    <li className={flag ? "marked-row marked-flagged" : "marked-row"} aria-label={visible(request.name)}>
      <input
        type="checkbox"
        aria-label={`File ${visible(request.name)}`}
        checked={ticked}
        disabled={disabled || !tickable(row)}
        title={tickable(row) ? undefined : FIX_IN_FORM}
        onChange={onTick}
      />
      {entry && <Thumb record={entry.record} />}
      <div className="marked-main">
        <p className="marked-name">
          <span className="marked-to">{visible(request.name)}</span>
          {row.codes.map((hit, i) => (
            <Tag key={i} tone={hit.unclear ? "orange" : "grey"} className="entry-chip" title="Filing code and how it was found">
              {visible(codeText(hit))}
            </Tag>
          ))}
        </p>
        {from && <p className="marked-meta">from {visible(from)}</p>}
        <p className="marked-meta">
          <span className="marked-label">Folder</span> {request.folder ? visible(request.folder) : "none"}
        </p>
        <p className="marked-meta">
          <span className="marked-label">Tray</span> {visible(trayLine(row, trays))}
        </p>
        {request.tags.length > 0 && (
          <p className="marked-meta">
            <span className="marked-label">Tags</span> {visible(request.tags.join(", "))}
          </p>
        )}
        {request.collections.length > 0 && (
          <p className="marked-meta">
            <span className="marked-label">Collections</span> {visible(request.collections.join(", "))}
          </p>
        )}
        {marks.length > 0 && (
          <p className="marked-meta">
            <span className="marked-label">Then</span> {marks.join(", ")}
          </p>
        )}
        {flag && <p className="notice marked-flag">{visible(flag)}</p>}
      </div>
      <button type="button" className="link-button" disabled={disabled} onClick={onOpen} title="Show this file in the Inbox form">
        Open
      </button>
    </li>
  );
}

export function MarkedBatch({ entries, trays, filing, onOpen, onClose }: Props) {
  const batch = useMarkedBatch();
  const rows: BatchRow[] = batch.data ?? [];
  // The owner's own ticks; a row not touched yet is ticked unless it is flagged. Kept
  // by drive id, so a reload (after filing) keeps the choices for the rows still there.
  const [choice, setChoice] = useState<Map<string, boolean>>(new Map());
  const isTicked = (row: BatchRow) => tickable(row) && (choice.get(row.drive_id) ?? row.flag === null);
  const ticked: FileRequest[] = rows.filter(isTicked).map((r) => r.request);
  // Previews and the confirm are dropped unless they match exactly these requests.
  filing.form.current = ticked;
  useEffect(() => {
    filing.clearPlan();
    // once, when the panel opens: a plan from the form does not apply here
  }, []);

  const tick = (row: BatchRow) => {
    if (filing.busy || !tickable(row)) return;
    setChoice((old) => new Map(old).set(row.drive_id, !isTicked(row)));
  };
  const fileThem = () => {
    if (ticked.length > 0) filing.fileIt(ticked, true);
  };
  const byId = new Map(entries.map((e) => [e.record.drive_id, e]));
  const flagged = rows.filter((r) => r.flag !== null).length;
  // the message for these files; a preview dropped because the rows changed says so here
  const message = filing.messageFor(rows.map((r) => r.drive_id));
  const messageText = message?.text === FORM_CHANGED ? MARKED_CHANGED : message?.text;

  return (
    <section className="batch-card marked-batch" aria-label="Marked files">
      <Toolbar
        title="Marked files"
        subtitle={rows.length > 0 ? `${ticked.length} of ${rows.length} ticked` : undefined}
        actions={
          <>
            <button type="button" onClick={onClose} disabled={filing.busy}>
              Close
            </button>
            <TipButton
              className="primary tip-end"
              tip="Show exactly what will move, then file the ticked files"
              onClick={fileThem}
              disabled={filing.busy || ticked.length === 0}
              disabledReason={filing.busy ? FILING_BUSY : "Tick the files to file"}
            >
              File {ticked.length}
            </TipButton>
          </>
        }
      />
      <div className="marked-body">
        {message &&
          (message.kind === "error" ? (
            <p className="error" role="alert">
              {visible(messageText ?? "")}
            </p>
          ) : (
            <p className="notice" role="status">
              {visible(messageText ?? "")}
            </p>
          ))}
        {batch.isPending ? (
          <p className="hint" role="status">
            Checking the marked files…
          </p>
        ) : batch.isError ? (
          <p className="error" role="alert">
            Could not check the marked files. {visible(errorText(batch.error))}
          </p>
        ) : rows.length === 0 ? (
          <p className="hint">No inbox file has a filing code now.</p>
        ) : (
          <>
            <p className="hint">
              Each file is filed exactly as shown.
              {flagged === 1 && " 1 file needs a look and starts unticked."}
              {flagged > 1 && ` ${plural(flagged, "file")} need a look and start unticked.`}
              {rows.some((r) => !tickable(r)) && " A file that needs input cannot be ticked: open it to fix it in the form."}
            </p>
            <ul className="marked-list" aria-label="Marked">
              {rows.map((row) => (
                <Row
                  key={row.drive_id}
                  row={row}
                  entry={byId.get(row.drive_id)}
                  trays={trays}
                  ticked={isTicked(row)}
                  disabled={filing.busy}
                  onTick={() => tick(row)}
                  onOpen={() => onOpen(row.drive_id)}
                />
              ))}
            </ul>
          </>
        )}
      </div>
    </section>
  );
}
