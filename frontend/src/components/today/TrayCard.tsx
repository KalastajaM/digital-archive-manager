/** A tray's rows on Today: what needs attention in full (fields, copy buttons), later
 * items compact, each with a round checkbox that marks it done, with urgency tags and amounts. */
import { Link, useNavigate } from "react-router-dom";
import type { AttentionItem, Item, Today as TodayData, TrayCount, TrayDef } from "../../api/client";
import { dayOf, fieldLabel, fieldWord, formatField } from "../../format";
import { visible } from "../../text";
import { CopyButton } from "../CopyButton";
import { DoneForm } from "../DoneForm";
import { ItemBadges } from "../ItemBadges";
import { ItemStar } from "../MarkIcons";
import { renewHref, renewLabel, useMarkDone } from "../useMarkDone";
import { urgency, UrgencyTag } from "../UrgencyTag";
import { daysBetween, waited } from "./time";

const enc = encodeURIComponent;

/** A tray's shape: bills (a money summary), dated items, or items that wait. */
export type Kind = "money" | "dated" | "waiting";
export type TrayCardInfo = { id: string; name: string; def?: TrayDef; count?: TrayCount; kind: Kind };

/** Every tray Today knows of, in tray order: the definitions, then trays only the
 * counts or the attention list name (their definition failed to load). */
export function trayCards(data: TodayData, defs: TrayDef[]): TrayCardInfo[] {
  const counts = new Map(data.overview.trays.map((t) => [t.tray_id, t]));
  const ids = [...defs].sort((a, b) => a.order - b.order).map((d) => d.id);
  for (const id of [
    ...data.overview.trays.map((t) => t.tray_id),
    ...data.open_items.map((t) => t.tray_id),
    ...data.attention.map((a) => a.tray),
  ]) {
    if (!ids.includes(id)) ids.push(id);
  }
  return ids.map((id) => {
    const def = defs.find((d) => d.id === id);
    const count = counts.get(id);
    const listed = data.attention.find((a) => a.tray === id);
    const first = data.open_items.find((t) => t.tray_id === id)?.items[0];
    let kind: Kind;
    if (def?.summary || (count?.sum ?? null) !== null) kind = "money";
    else if (def ? def.date_field : listed || first?.date) kind = "dated";
    else kind = "waiting";
    const name = def?.name ?? count?.name ?? listed?.item.tray_name ?? first?.tray_name ?? id;
    return { id, name, def, count, kind };
  });
}

/** The tray's money field: its summary's field, else its first money field. */
export function amountField(def: TrayDef | undefined): string | null {
  if (!def) return null;
  if (def.summary?.sum) return def.summary.sum;
  return Object.entries(def.fields ?? {}).find(([, f]) => f.type === "money")?.[0] ?? null;
}

const hasValue = (v: unknown) => v != null && v !== "";

/** An attention entry, or an open item dated later (no level) from Today's open items. */
export type Row = Omit<AttentionItem, "level"> & { level: AttentionItem["level"] | null };

/** The checkbox's name: "Mark <title> done", or with the tray's own done label ("Mark
 * paid" gives "Mark <title> paid", "Read" gives "Mark <title> read"). */
export function doneName(title: string, label: string): string {
  const word = label.replace(/^mark\s+/i, "").toLowerCase();
  return `Mark ${title} ${word}`;
}

export function TrayRow({
  entry,
  full,
  kind,
  tray,
  today,
  traysUnknown,
  formOpen,
  setFormOpen,
  onMenu,
}: {
  entry: Row;
  /** It needs attention: fields and copy buttons are shown (later items stay compact). */
  full: boolean;
  kind: Kind;
  tray: TrayDef | undefined;
  today: string;
  /** The tray definitions (done label and fields) are loading or failed to load: the
   * done fields are unknown, so Done is off rather than silently skipping them. */
  traysUnknown: boolean;
  formOpen: boolean;
  setFormOpen: (open: boolean) => void;
  /** The item's right-click menu (Mark done, Move to tray, Remove, its file). */
  onMenu?: (e: React.MouseEvent) => void;
}) {
  const { item, level } = entry;
  const defs = tray?.fields ?? {};
  const names = tray ? Object.keys(defs) : Object.keys(item.fields);
  const invalid = new Set(item.invalid_fields);
  const amount = amountField(tray);
  const payee = typeof item.fields.payee === "string" && item.fields.payee !== "" ? item.fields.payee : null;
  const valued = names.filter((n) => n !== tray?.date_field && hasValue(item.fields[n]));
  const shown = valued.filter((n) => n !== "payee" && n !== amount);
  const copyable = valued.filter((n) => defs[n]?.copy && !invalid.has(n) && typeof item.fields[n] === "string");
  const doneLabel = tray?.done?.label ?? "Done";
  const fieldText = (n: string) =>
    invalid.has(n)
      ? `${visible(formatField(undefined, item.fields[n]))} (invalid)`
      : visible(formatField(defs[n]?.type, item.fields[n]));
  const tone = item.date ? urgency(item.date, today).tone : level === "undated" ? "orange" : "grey";
  const age = daysBetween(dayOf(item.created), today);
  const doneFields = tray?.done?.fields ?? {};
  const done = useMarkDone(item, tray, today);
  const title = visible(item.title);
  const navigate = useNavigate();
  // a Renew item's check opens its Renewed… form: it is renewed, not finished
  const renew = renewLabel(tray);
  const checkName = renew ? `${visible(renew)} ${title}` : doneName(title, visible(doneLabel));
  const onCheck = async () => {
    if (renew) {
      navigate(renewHref(item));
      return;
    }
    if (done.needsForm) {
      setFormOpen(!formOpen);
      return;
    }
    await done.run();
  };

  return (
    <article
      className={`today-row attention attention-${level ?? "later"}${full ? "" : " today-row-compact"}`}
      aria-label={visible(item.title)}
      onContextMenu={onMenu}
    >
      <input
        type="checkbox"
        className={`round-check round-check-${tone}`}
        aria-label={checkName}
        data-tip={checkName}
        checked={done.pending}
        disabled={traysUnknown || done.pending}
        onChange={() => void onCheck()}
      />
      <div className="today-row-main">
        <p className="today-row-title tray-row-title">
          <Link to={`/trays/${enc(entry.tray)}?item=${item.id}`} title={title}>
            {title}
          </Link>
          <ItemStar files={item.files} />
        </p>
        {payee && <p className="today-row-sub">{visible(payee)}</p>}
        {full && shown.length > 0 && (
          <p className="attention-fields">
            {shown.map((n, i) => (
              <span key={n}>
                {i > 0 && " · "}
                {visible(fieldLabel(n))} {fieldText(n)}
              </span>
            ))}
          </p>
        )}
        {entry.note_excerpt && <p className="attention-note">Note: {visible(entry.note_excerpt)}</p>}
        <ItemBadges fileState={entry.file_state} />
        {full && copyable.length > 0 && (
          <div className="attention-actions">
            {copyable.map((n) => (
              <CopyButton key={n} value={item.fields[n] as string} type={defs[n].type} label={fieldWord(n)} />
            ))}
          </div>
        )}
        {formOpen && (
          <DoneForm
            item={item}
            label={doneLabel}
            fields={doneFields}
            today={today}
            onClose={() => setFormOpen(false)}
          />
        )}
      </div>
      <div className="today-row-side">
        {item.date && <UrgencyTag date={item.date} today={today} />}
        {amount && hasValue(item.fields[amount]) && <span className="today-amount">{fieldText(amount)}</span>}
        {kind === "waiting" && <span className="today-age">{waited(age)}</span>}
      </div>
    </article>
  );
}

export const byDate = (a: Item, b: Item) => {
  if (a.date === b.date) return a.created - b.created || a.id - b.id;
  if (a.date === null) return 1;
  if (b.date === null) return -1;
  return a.date < b.date ? -1 : 1;
};
const byCreated = (a: Item, b: Item) => a.created - b.created || a.id - b.id;

/** The tray's rows: its first open items from Today (so later items show too) plus any
 * attention entry beyond them; attention entries carry their level, file state, note. */
export function trayRows(info: TrayCardInfo, attention: AttentionItem[], items: Item[]): Row[] {
  const byId = new Map(attention.map((a) => [a.item.id, a]));
  const listed = new Set(items.map((i) => i.id));
  const rows: Row[] = [
    ...items.map(
      (i): Row =>
        byId.get(i.id) ?? {
          item: i,
          tray: info.id,
          level: null,
          missing_required: i.missing_required,
          file_state: "ok",
          note_excerpt: null,
        },
    ),
    ...attention.filter((a) => !listed.has(a.item.id)),
  ];
  return rows.sort((a, b) => (info.kind === "waiting" ? byCreated : byDate)(a.item, b.item));
}
