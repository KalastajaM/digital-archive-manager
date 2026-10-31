/** The lists of Today's Inbox section: "Found in the inbox" with a one-click Put in
 * <tray> (toast with Open and Undo), the first ``FOUND_SHOWN`` found files and "Show N
 * more". With AI on, "Not recognised: N files — Ask AI" lists the inbox files without a
 * rule guess, each with its own Ask AI (the "What will be sent" sheet first). */
import { Sparkles } from "lucide-react";
import { IconButton } from "../ui/IconButton";
import { useState } from "react";
import { Link } from "react-router-dom";
import {
  type FilingSuggestion,
  type Found,
  type InboxEntry,
  type TrayDef,
  useInbox,
  useTrays,
} from "../../api/client";
import { fieldWord, formatDate, formatField, formatMoney, plural } from "../../format";
import { visible } from "../../text";
import { AIBadge } from "../ai/AIBadge";
import { useAISend } from "../ai/useAI";
import { type QuickPut, useQuickPut } from "../useQuickPut";
import { Tag } from "../ui/Tag";
import { MarkIcons } from "../MarkIcons";

/** Found files listed before "Show N more"; the rest wait behind "Show N more". */
export const FOUND_SHOWN = 5;

export function FoundRow({ found, onPut, busy }: { found: Found; onPut: () => void; busy: boolean }) {
  const details = [
    found.due_date ? `due date ${formatDate(found.due_date)}` : null,
    found.total ? formatMoney(found.total) : null,
  ].filter(Boolean);
  return (
    <li className="found-row">
      <div className="today-row-main">
        <p className="today-row-title">
          {visible(found.name)}
          <MarkIcons marks={found.marks} />
        </p>
        {(details.length > 0 || found.overdue) && (
          <p className="today-row-sub">
            {visible(details.join(" · "))}
            {found.overdue && (
              <>
                {" "}
                <Tag tone="red">overdue</Tag>
              </>
            )}
          </p>
        )}
      </div>
      <button type="button" className="primary" disabled={busy} onClick={onPut}>
        Put in {visible(found.tray_name)}
      </button>
    </li>
  );
}

/** The suggested fields the row shows (the tray's own, with a value, in its order):
 * exactly these are sent with Put in. */
function shownFields(tray: TrayDef, fields: Record<string, string>): Record<string, string> {
  const out: Record<string, string> = {};
  for (const name of Object.keys(tray.fields ?? {})) {
    const value = fields[name];
    if (value !== undefined && value.trim() !== "") out[name] = value;
  }
  return out;
}

/** The shown fields as a row line ("due date 15.10.2026 · amount 84,20 €"). */
const fieldLine = (tray: TrayDef, fields: Record<string, string>) =>
  Object.entries(fields)
    .map(([name, value]) => `${fieldWord(name)} ${formatField(tray.fields?.[name]?.type, value)}`)
    .join(" · ");

/** One inbox file the rules did not recognise: Ask AI (the sheet first), then the
 * suggested tray and fields with "Put in <tray>" (exactly those values). */
function AskRow({
  entry,
  trays,
  put,
  busy,
}: {
  entry: InboxEntry;
  trays: TrayDef[];
  put: (p: QuickPut) => void;
  busy: boolean;
}) {
  const [answer, setAnswer] = useState<FilingSuggestion | null>(null);
  const ai = useAISend<FilingSuggestion>("suggest-filing", (data) => setAnswer(data));
  const name = entry.record.name ?? entry.record.path;
  const tray = answer?.tray ? trays.find((t) => t.id === answer.tray) : undefined;
  const already = tray !== undefined && entry.open_trays.includes(tray.id);
  const shown = tray && answer ? shownFields(tray, answer.tray_fields) : {};
  const details = tray ? fieldLine(tray, shown) : "";
  return (
    <li className="found-row">
      <div className="today-row-main">
        <p className="today-row-title">{visible(name)}</p>
        {answer &&
          (tray ? (
            <p className="today-row-sub">
              {details ? visible(details) : `${visible(tray.name)}, no fields`}{" "}
              <AIBadge field="tray" confidence={answer.confidence.tray} reason={answer.reason} />
            </p>
          ) : (
            <p className="today-row-sub">
              No tray suggested{answer.folder ? ` · folder ${visible(answer.folder)}` : ""} —{" "}
              <Link to="/inbox">File in the Inbox</Link>
            </p>
          ))}
      </div>
      {!answer ? (
        <IconButton
          icon={<Sparkles />}
          label={`Ask AI about ${visible(name)}`}
          tip="Ask AI to suggest a name, folder and tags"
          className="tip-end"
          disabled={ai.busy}
          onClick={() => ai.ask({ drive_id: entry.record.drive_id })}
        />
      ) : tray && already ? (
        <span className="hint">Already in {visible(tray.name)}</span>
      ) : tray ? (
        <button
          type="button"
          className="primary"
          disabled={busy}
          onClick={() =>
            put({ tray: tray.id, trayName: tray.name, ids: [entry.record.drive_id], name, fields: shown })
          }
        >
          Put in {visible(tray.name)}
        </button>
      ) : null}
      {ai.sheet}
    </li>
  );
}

/** "Not recognised: N files — Ask AI": the inbox files without a rule guess, listed on
 * request. Nothing is prepared or sent until a file's own Ask AI. */
export function NotRecognised({ put, pendingId }: { put: (p: QuickPut) => void; pendingId: string | null }) {
  const inbox = useInbox();
  const trays = useTrays();
  const [open, setOpen] = useState(false);
  const files = (inbox.data ?? []).filter((e) => e.tray_guess === null && !e.record.is_dir);
  if (files.length === 0) return null;
  return (
    <>
      <p className="today-sub ai-unrecognised">
        Not recognised: {plural(files.length, "file")} —{" "}
        <button type="button" className="link-button" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
          Ask AI
        </button>
      </p>
      {open && (
        <ul className="found-list ai-chooser" aria-label="Not recognised">
          {files.map((e) => (
            <AskRow
              key={e.record.drive_id}
              entry={e}
              trays={trays.data?.trays ?? []}
              put={put}
              busy={pendingId === e.record.drive_id}
            />
          ))}
        </ul>
      )}
    </>
  );
}

/** "Found in the inbox": the files the scan rules recognised as a bill or the like, each
 * with a one-click Put in <tray>; the first ``FOUND_SHOWN``, then "Show N more". */
export function FoundList({ found, quick }: { found: Found[]; quick: ReturnType<typeof useQuickPut> }) {
  const [all, setAll] = useState(false);
  const shown = all ? found : found.slice(0, FOUND_SHOWN);
  const putIn = (f: Found) => void quick.put({ tray: f.tray, trayName: f.tray_name, ids: [f.drive_id], name: f.name });
  return (
    <>
      <h4 className="today-subhead">Found in the inbox</h4>
      <ul className="found-list" aria-label="Found in the inbox">
        {shown.map((f) => (
          <FoundRow
            key={`${f.drive_id} ${f.tray}`}
            found={f}
            busy={quick.pendingIds?.[0] === f.drive_id}
            onPut={() => putIn(f)}
          />
        ))}
      </ul>
      {found.length > FOUND_SHOWN && (
        <p className="today-more">
          <button type="button" className="link-button" onClick={() => setAll((a) => !a)}>
            {all ? "Show fewer" : `Show ${found.length - FOUND_SHOWN} more`}
          </button>
        </p>
      )}
      <p className="hint">Found by the scan rules (a due date and an amount, with an IBAN or a reference).</p>
    </>
  );
}
