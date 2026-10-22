/** A tray's card on Today and its rows: what needs attention in full (fields, copy
 * buttons), later items compact, each with a round checkbox that marks it done, with urgency tags and amounts. */
import { BookOpen, CircleCheck, Euro, Hourglass, ListTodo, type LucideIcon } from "lucide-react";
import { Link } from "react-router-dom";
import { type AttentionItem, errorText, type Item, type Today as TodayData, type TrayCount, type TrayDef, useItemDone, useItemReopen } from "../../api/client";
import { dayOf, fieldLabel, fieldWord, formatField, formatMoney, plural } from "../../format";
import { visible } from "../../text";
import { CopyButton } from "../CopyButton";
import { DoneForm } from "../DoneForm";
import { ItemBadges } from "../ItemBadges";
import { useToast } from "../Toasts";
import { Card } from "../ui/Card";
import { urgency, UrgencyTag } from "../UrgencyTag";
import type { CardFrame } from "./frame";
import { daysBetween, waited } from "./time";

const enc = encodeURIComponent;

/** A tray card's shape: bills (a money summary), dated items, or items that wait. */
export type Kind = "money" | "dated" | "waiting";
export type TrayCardInfo = { id: string; name: string; def?: TrayDef; count?: TrayCount; kind: Kind };

const KIND_ICON: Record<Kind, LucideIcon> = { money: Euro, dated: CircleCheck, waiting: BookOpen };

function trayIcon(info: TrayCardInfo): LucideIcon {
  const key = `${info.id} ${info.name}`.toLowerCase();
  if (/follow|waiting|odota|seuranta/.test(key)) return Hourglass;
  if (/read|lue|luettava/.test(key)) return BookOpen;
  if (info.kind !== "dated" || /action|task|todo|tee|hoida/.test(key)) return KIND_ICON[info.kind];
  return ListTodo;
}

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
  const markDone = useItemDone();
  const reopen = useItemReopen();
  const toast = useToast();
  const title = visible(item.title);
  const checkName = doneName(title, visible(doneLabel));
  const doneWord = visible(doneLabel).replace(/^mark\s+/i, "").toLowerCase();
  // Completes at once, sending each done field's default (paid_on: today); only a done
  // field that is required and has no default opens the small form.
  const needsForm = Object.values(doneFields).some((f) => f.required && f.type !== "checkbox" && !f.default);
  const defaults = Object.fromEntries(
    Object.entries(doneFields).flatMap(([n, f]): [string, string | boolean][] =>
      f.type === "checkbox" ? [[n, false]] : f.default === "today" ? [[n, today]] : [],
    ),
  );
  const onCheck = async () => {
    if (needsForm) {
      setFormOpen(!formOpen);
      return;
    }
    try {
      await markDone.mutateAsync({ id: item.id, fields: defaults });
    } catch (err) {
      toast({ kind: "error", text: `Could not mark ${title} ${doneWord}: ${visible(errorText(err))}` });
      return;
    }
    toast({
      kind: "info",
      text: `Marked ${doneWord}: ${title}`,
      action: {
        label: "Undo",
        run: () =>
          void reopen.mutateAsync(item.id).then(
            () => toast({ kind: "info", text: `Reopened: ${title}` }),
            (err) => toast({ kind: "error", text: `Could not reopen ${title}: ${visible(errorText(err))}` }),
          ),
      },
    });
  };

  return (
    <article
      className={`today-row attention attention-${level ?? "later"}${full ? "" : " today-row-compact"}`}
      aria-label={visible(item.title)}
    >
      <input
        type="checkbox"
        className={`round-check round-check-${tone}`}
        aria-label={checkName}
        data-tip={checkName}
        checked={markDone.isPending}
        disabled={traysUnknown || markDone.isPending}
        onChange={() => void onCheck()}
      />
      <div className="today-row-main">
        <p className="today-row-title">
          <Link to={`/trays/${enc(entry.tray)}?item=${item.id}`}>{visible(item.title)}</Link>
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

const byDate = (a: Item, b: Item) => {
  if (a.date === b.date) return a.created - b.created || a.id - b.id;
  if (a.date === null) return 1;
  if (b.date === null) return -1;
  return a.date < b.date ? -1 : 1;
};
const byCreated = (a: Item, b: Item) => a.created - b.created || a.id - b.id;

/** The tray's rows: its first open items from Today (so later items show too) plus any
 * attention entry beyond them; attention entries carry their level, file state, note. */
function trayRows(info: TrayCardInfo, attention: AttentionItem[], items: Item[]): Row[] {
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

export function TrayCard({
  info,
  attention,
  items,
  today,
  traysUnknown,
  formFor,
  setFormFor,
  frame,
}: {
  info: TrayCardInfo;
  /** The tray's attention entries (shown in full). */
  attention: AttentionItem[];
  /** The tray's first open items, as Today sends them. */
  items: Item[];
  today: string;
  traysUnknown: boolean;
  formFor: number | null;
  setFormFor: (id: number | null) => void;
  /** Today's layout: folding, dragging (none when shown on its own). */
  frame?: CardFrame;
}) {
  const folded = frame?.fold.folded ?? false;
  const rows = trayRows(info, attention, items);
  const full = new Set(attention.map((a) => a.item.id));
  const name = visible(info.name);
  const Icon = trayIcon(info);
  const { count } = info;
  const open = count?.open ?? rows.length;
  const hidden = Math.max(0, open - rows.length);
  const oldest = rows.length > 0 ? Math.min(...rows.map((r) => r.item.created)) : null;
  /** The headline of a folded dated card: its next dated item (rows go by date). */
  const next = rows.find((r) => r.item.date);

  // Every card leads with one big figure: a money tray's total, otherwise the open
  // count (then just "open" beside it). An empty tray has no figure: "Nothing open."
  const total = info.kind === "money" && count?.sum != null ? formatMoney(count.sum) : null;
  const big = open === 0 ? null : (total ?? String(open));
  const parts: string[] = [];
  if (open > 0) parts.push(total ? `${open} open` : "open");
  if (count && count.overdue > 0) parts.push(`${count.overdue} overdue`);
  if (info.kind === "waiting" && oldest !== null) parts.push(`oldest ${waited(daysBetween(dayOf(oldest), today))}`);
  if (count && count.waiting_long > 0) parts.push(`${count.waiting_long} waiting long`);

  return (
    <Card
      title={name}
      icon={<Icon />}
      className="today-card"
      fold={frame?.fold}
      headerProps={frame?.headerProps}
      actions={
        <Link className="card-link" to={`/trays/${enc(info.id)}`} aria-label={`Show all in ${name}`}>
          Show all
        </Link>
      }
    >
      {(big || parts.length > 0) && (
        <p className="today-figure">
          {big && <span className="today-big">{big}</span>}
          {big && parts.length > 0 && " "}
          {parts.map((p, i) => (
            <span key={p} className="today-sub">
              {i > 0 && " · "}
              <span>{p}</span>
            </span>
          ))}
        </p>
      )}
      {open === 0 && rows.length === 0 ? (
        <p className="today-empty">Nothing open.</p>
      ) : folded ? (
        info.kind === "dated" && next?.item.date && (
          <p className="today-next">
            Next: <Link to={`/trays/${enc(info.id)}?item=${next.item.id}`}>{visible(next.item.title)}</Link>{" "}
            <UrgencyTag date={next.item.date} today={today} />
          </p>
        )
      ) : rows.length === 0 ? (
        <p className="today-empty">Nothing open.</p>
      ) : (
        <div className="today-rows">
          {rows.map((entry) => (
            <TrayRow
              key={entry.item.id}
              entry={entry}
              full={full.has(entry.item.id)}
              kind={info.kind}
              tray={info.def}
              today={today}
              traysUnknown={traysUnknown}
              formOpen={formFor === entry.item.id}
              setFormOpen={(isOpen) => setFormFor(isOpen ? entry.item.id : null)}
            />
          ))}
        </div>
      )}
      {!folded && hidden > 0 && (
        <p className="today-more">
          <Link to={`/trays/${enc(info.id)}`}>{plural(hidden, "more item", "more items")}</Link>
        </p>
      )}
    </Card>
  );
}
