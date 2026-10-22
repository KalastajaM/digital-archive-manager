/** Today's Inbox card: the count, the oldest age and the age bar, and "Found in the
 * inbox" with a one-click Put in <tray> (toast with Open and Undo). Folded, only
 * the count, age and bar show; open, the first ``FOUND_SHOWN`` found files and "Show N
 * more". With AI on, "Not recognised: N files — Ask AI" lists the inbox files without a
 * rule guess, each with its own Ask AI (the "What will be sent" sheet first). */
import { Inbox as InboxIcon } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import {
  type FilingSuggestion,
  type Found,
  type InboxEntry,
  type Today as TodayData,
  type TrayDef,
  useInbox,
  useTrays,
} from "../../api/client";
import { fieldWord, formatDate, formatField, formatMoney, plural } from "../../format";
import { visible } from "../../text";
import { AIBadge } from "../ai/AIBadge";
import { AIHint, useAISend, useAIState } from "../ai/useAI";
import { AgeBar } from "../AgeBar";
import { type QuickPut, useQuickPut } from "../useQuickPut";
import { Card } from "../ui/Card";
import { Tag } from "../ui/Tag";
import type { CardFrame } from "./frame";
import { waited } from "./time";
import { MarkIcons } from "../MarkIcons";

/** Found files listed before "Show N more"; more than this and the card starts folded. */
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
        <button
          type="button"
          aria-label={`Ask AI about ${visible(name)}`}
          disabled={ai.busy}
          onClick={() => ai.ask({ drive_id: entry.record.drive_id })}
        >
          Ask AI
        </button>
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
function NotRecognised({ put, pendingId }: { put: (p: QuickPut) => void; pendingId: string | null }) {
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

export function InboxCard({ data, frame }: { data: TodayData; frame?: CardFrame }) {
  const { inbox_stats: stats, found } = data;
  const folded = frame?.fold.folded ?? false;
  const [all, setAll] = useState(false);
  const shown = all ? found : found.slice(0, FOUND_SHOWN);
  const quick = useQuickPut();
  const aiState = useAIState();
  const putIn = (f: Found) => void quick.put({ tray: f.tray, trayName: f.tray_name, ids: [f.drive_id], name: f.name });

  return (
    <Card
      title="Inbox"
      icon={<InboxIcon />}
      className="today-card"
      fold={frame?.fold}
      headerProps={frame?.headerProps}
      actions={
        stats.count > 0 && (
          <Link className="card-link" to="/inbox">
            Start filing
          </Link>
        )
      }
    >
      {stats.count === 0 ? (
        <p className="today-empty">The inbox is empty.</p>
      ) : (
        <>
          <p className="today-figure">
            <span className="today-big">{stats.count}</span>{" "}
            <span className="today-sub">
              {stats.count === 1 ? "file" : "files"}
              {stats.oldest_days !== null && ` · oldest ${waited(stats.oldest_days)}`}
            </span>
            {stats.overdue > 0 && (
              <>
                {" "}
                <Tag tone="red">{`${stats.overdue} overdue`}</Tag>
              </>
            )}
          </p>
          <AgeBar thisWeek={stats.this_week} lastWeek={stats.last_week} older={stats.older} />
        </>
      )}
      {folded && found.length > 0 && (
        <p className="today-sub today-found-count">{plural(found.length, "file")} found by the scan rules</p>
      )}
      {!folded && found.length > 0 && (
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
      )}
      {!folded && stats.count > 0 && aiState.on && (
        <NotRecognised put={(p) => void quick.put(p)} pendingId={quick.pendingIds?.[0] ?? null} />
      )}
      {!folded && stats.count > 0 && <AIHint what="to ask about files the rules don’t recognise" />}
    </Card>
  );
}
