/** One tray item: its files (preview), title and fields (saved on blur or Enter), note,
 * checklist, history, and Mark done/Reopen. A bill (a tray with an IBAN field) leads with its
 * amount, copy rows and the bank barcode; a dated item with its date and checklist; an
 * undated one with how long it has waited. Everything here changes the database only,
 * through the API: adding or removing a file never moves it. */
import { useQueryClient } from "@tanstack/react-query";
import { ArrowRightLeft, CircleMinus, Eye, Unlink, X } from "lucide-react";
import { type ReactNode, useId, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  errorText,
  itemFilesQuery,
  type FieldDef,
  type Item,
  type ItemEvent,
  type ItemFile,
  type TrayDef,
  useItem,
  useItemFileChange,
  useItemFiles,
  useItemHistory,
  useItemReopen,
  useItemUpdate,
  useMoveItem,
  useUndoMoveItem,
} from "../api/client";
import { SummaryBox } from "../components/ai/SummaryBox";
import { Barcode, type PayFact } from "../components/Barcode";
import { Checklist } from "../components/Checklist";
import { CopyButton } from "../components/CopyButton";
import { DoneForm } from "../components/DoneForm";
import { editText, FieldInput } from "../components/FieldInput";
import { FilePreview } from "../components/FilePreview";
import { FILE_BADGE } from "../components/ItemBadges";
import { RelativeDate } from "../components/RelativeDate";
import { SavedNote, SaveState } from "../components/SavedNote";
import { daysBetween, waited } from "../components/today/time";
import { amountField } from "../components/today/TrayCard";
import { undoAction, useToast } from "../components/Toasts";
import { IconButton } from "../components/ui/IconButton";
import { TipButton } from "../components/ui/TipButton";
import { Menu, type MenuEntry } from "../components/ui/Menu";
import { RemoveItemSheet } from "../components/RemoveItemSheet";
import { UrgencyTag } from "../components/UrgencyTag";
import { useAutoSave } from "../components/useAutoSave";
import { dayOf, fieldLabel, fieldWord, formatDate, formatField, formatMoney, groupIban, plural } from "../format";
import { visible } from "../text";
import { useSearch } from "./useSearch";
import { FileMeta } from "../components/FileMeta";
import { deletionRefusal } from "../components/MoveTo";
import { isTrashKey, TrashButton, useTrash } from "../components/Trash";
import { MarkIcons } from "../components/MarkIcons";
import { useKeydown } from "../keyboard";

const TITLE_DEF: FieldDef = { type: "text", required: false, copy: false };

const baseName = (path: string) => path.slice(path.lastIndexOf("/") + 1);

/** One field, saved on blur or Enter (a checkbox as soon as it changes). */
function EditableField({
  label,
  def,
  server,
  save,
  hint,
  after,
  size,
}: {
  label: string;
  def: FieldDef;
  server: string | boolean;
  save: (value: string | boolean) => Promise<string | boolean>;
  hint?: ReactNode;
  /** Beside the input, such as a date's urgency tag. */
  after?: ReactNode;
  /** The width class on the fields row: the title grows, the rest have a set width. */
  size?: "title" | "date" | "text" | "money" | "checkbox";
}) {
  const id = useId();
  const auto = useAutoSave(server, save);
  const checkbox = def.type === "checkbox";
  return (
    <div className={size ? `field field-${size}` : "field"}>
      <label htmlFor={id}>{label}</label>
      <div className="field-input">
        <FieldInput
          id={id}
          def={def}
          value={auto.shown}
          onChange={(v) => {
            auto.change(v);
            if (checkbox) void auto.commit(v);
          }}
          onBlur={(e) => {
            if (!checkbox) void auto.commit(e.currentTarget.value);
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !checkbox) {
              e.preventDefault();
              void auto.commit(e.currentTarget.value);
            }
          }}
        />
        {after}
      </div>
      {hint}
      <SaveState status={auto.status} />
    </div>
  );
}

/** What a field's input shows for the stored value: the raw value if it is invalid. */
function fieldText(def: FieldDef, item: Item, name: string): string | boolean {
  const value = item.fields[name];
  if (def.type === "checkbox" && !item.invalid_fields.includes(name)) return value === true;
  if (value === undefined || value === null) return "";
  const raw = typeof value === "string" ? value : JSON.stringify(value);
  if (item.invalid_fields.includes(name)) return raw;
  return editText(def, raw) ?? raw;
}

const fieldSize = (type: string): "date" | "text" | "money" | "checkbox" =>
  type === "date" ? "date" : type === "money" ? "money" : type === "checkbox" ? "checkbox" : "text";

/** The item's editable fields on one row that wraps only when the panel is narrow: the
 * title (grows), then the tray's fields in order (a date with its urgency tag after it),
 * then ``trailing`` (the done buttons) at the end. ``part``: a bill shows only the title
 * in its top row and the other fields further down. */
function Fields({
  item,
  tray,
  tag,
  trailing,
  part = "all",
}: {
  item: Item;
  tray: TrayDef | undefined;
  tag?: ReactNode;
  trailing?: ReactNode;
  part?: "all" | "title" | "rest";
}) {
  const update = useItemUpdate();
  const saveTitle = async (value: string | boolean) =>
    (await update.mutateAsync({ id: item.id, title: String(value) })).title;
  return (
    <div className="item-fields">
      {part !== "rest" && <EditableField label="Title" def={TITLE_DEF} server={item.title} save={saveTitle} size="title" />}
      {part !== "title" && tray === undefined && Object.keys(item.fields).length > 0 && (
        <p className="hint">
          The tray of this item was removed from the settings: its fields cannot be edited.{" "}
          {Object.entries(item.fields)
            .map(([n, v]) => `${fieldWord(n)} ${formatField(undefined, v)}`)
            .map(visible)
            .join(" · ")}
        </p>
      )}
      {part !== "title" &&
        Object.entries(tray?.fields ?? {}).map(([name, def]) => {
          const invalid = item.invalid_fields.includes(name);
          // An invalid stored value is shown as text, so it stays readable until replaced.
          const inputDef = invalid ? { ...def, type: "text" } : def;
          const save = async (value: string | boolean) => {
            const stored = await update.mutateAsync({ id: item.id, fields: { [name]: value } });
            return fieldText(def, stored, name);
          };
          const label = visible(fieldLabel(name));
          return (
            <EditableField
              key={name}
              label={def.required ? `${label} (required)` : label}
              def={inputDef}
              size={fieldSize(inputDef.type)}
              server={fieldText(def, item, name)}
              save={save}
              after={name === tray?.date_field ? tag : null}
              hint={
                invalid ? (
                  <p className="hint">invalid for this field type: kept as stored until you set a new value</p>
                ) : null
              }
            />
          );
        })}
      {trailing && <div className="item-done-buttons">{trailing}</div>}
    </div>
  );
}

/** Search the index and choose a hit (``choose`` does what choosing means: attach the
 * file to an item, or put it in a tray; the file stays put either way). ``taken``: hits
 * to leave out. Esc closes it. */
export function AddFile({
  taken,
  choose,
  onDone,
}: {
  taken: string[];
  choose: (hit: { drive_id: string; name: string }) => Promise<unknown>;
  onDone: () => void;
}) {
  const id = useId();
  const [query, setQuery] = useState("");
  const search = useSearch(query.trim());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const hits = (search.hits ?? []).filter((h) => !taken.includes(h.drive_id));
  const add = async (hit: { drive_id: string; name: string }) => {
    setError(null);
    setBusy(true);
    try {
      await choose(hit);
      onDone();
    } catch (e) {
      setError(errorText(e));
      setBusy(false);
    }
  };
  return (
    <div className="add-file">
      <label htmlFor={id}>Find a file</label>
      <input
        id={id}
        type="search"
        value={query}
        autoFocus
        spellCheck={false}
        onChange={(e) => setQuery(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Escape") {
            e.preventDefault();
            e.stopPropagation();
            onDone();
          }
        }}
      />
      {search.error && (
        <p className="error" role="alert">
          Search failed. {visible(search.error)}
        </p>
      )}
      {query.trim() && search.hits !== null && hits.length === 0 && <p className="hint">No other files match.</p>}
      {hits.length > 0 && (
        <ul className="entries">
          {hits.map((h) => (
            <li key={h.drive_id}>
              <button type="button" className="entry" disabled={busy} onClick={() => void add(h)}>
                <span className="entry-name">Add {visible(h.name)}</span>
                <MarkIcons marks={h.marks} />
                <code className="entry-path">{visible(h.path)}</code>
              </button>
            </li>
          ))}
        </ul>
      )}
      {error && (
        <p className="error" role="alert">
          {visible(error)}
        </p>
      )}
    </div>
  );
}

const TRAYS_LOADING = "The trays are still loading";

const ADD_FILE_TIP =
  "Attach another file to this item, such as a reminder or a reply. They share one title, date and checklist and are marked done together. The file is not moved.";

/** The summary box of the item's first file (spec §7.2), with a file selector when the
 * item has several. With no file there is nothing to summarize (no AI button). */
function ItemSummary({ item }: { item: Item }) {
  const selectId = useId();
  const files = useItemFiles(item.id);
  const list = (files.data ?? []).filter((f) => f.path && f.state !== "missing");
  const [chosen, setChosen] = useState<string | null>(null);
  const file = list.find((f) => f.drive_id === chosen) ?? list[0];
  if (files.isPending || files.isError) return null;
  if (!file) {
    return (
      <section className="summary-box" aria-label="Summary">
        <p className="hint">No file to summarize.</p>
      </section>
    );
  }
  return (
    <div className="item-summary">
      {list.length > 1 && (
        <div className="summary-file">
          <label htmlFor={selectId}>Summary of</label>
          <select id={selectId} value={file.drive_id} onChange={(e) => setChosen(e.target.value)}>
            {list.map((f) => (
              <option key={f.drive_id} value={f.drive_id}>
                {visible(baseName(f.path!))}
              </option>
            ))}
          </select>
        </div>
      )}
      <SummaryBox key={file.drive_id} driveId={file.drive_id} />
    </div>
  );
}

const valueText = (def: FieldDef | undefined, value: unknown) =>
  value === null || value === undefined ? "(none)" : formatField(def?.type, value);

function eventText(event: ItemEvent, tray: TrayDef | undefined, names: Map<string, string>): string {
  const data = event.data;
  // The name recorded with the event; older events have none: the item's current
  // files are the next best source.
  const fileName = () => {
    if (typeof data.name === "string" && data.name) return data.name;
    return names.get(String(data.drive_id ?? "")) ?? "a file no longer on this item";
  };
  switch (event.kind) {
    case "created":
      return "Created";
    case "edited": {
      const changes = (data.changes ?? {}) as Record<string, [unknown, unknown]>;
      const parts = Object.entries(changes).map(([name, [old, now]]) => {
        const def = tray?.fields?.[name];
        return `${fieldWord(name)} ${valueText(def, old)} → ${valueText(def, now)}`;
      });
      return `Edited: ${parts.join("; ")}`;
    }
    case "done": {
      const fields = (data.done_fields ?? {}) as Record<string, unknown>;
      const parts = Object.entries(fields).map(
        ([name, v]) => `${fieldWord(name)} ${valueText(tray?.done?.fields?.[name], v)}`,
      );
      return parts.length > 0 ? `Done: ${parts.join(", ")}` : "Done";
    }
    case "reopened":
      return "Reopened";
    case "file_added":
      return `File added: ${fileName()}`;
    case "file_removed":
      return `File removed: ${fileName()}`;
    case "moved":
      return `Moved from ${String(data.from_name ?? "another tray")} to ${String(data.to_name ?? "another tray")}`;
  }
}

function History({ item, tray, today }: { item: Item; tray: TrayDef | undefined; today: string }) {
  const history = useItemHistory(item.id);
  const files = useItemFiles(item.id);
  const headingId = useId();
  const names = new Map((files.data ?? []).filter((f) => f.path).map((f) => [f.drive_id, baseName(f.path!)]));
  return (
    <section className="history" aria-labelledby={headingId}>
      <h3 id={headingId}>History</h3>
      {history.isError && (
        <p className="error" role="alert">
          Could not load the history. {visible(errorText(history.error))}
        </p>
      )}
      <ul>
        {(history.data ?? []).map((e) => (
          <li key={e.id}>
            {visible(eventText(e, tray, names))} · <RelativeDate date={dayOf(e.at)} today={today} />
          </li>
        ))}
      </ul>
    </section>
  );
}

/** The done fields as stored, e.g. "paid on 17.10.2026". */
export function doneFieldsText(item: Item, tray: TrayDef | undefined): string {
  return Object.entries(item.done_fields ?? {})
    .map(([name, v]) => `${fieldWord(name)} ${valueText(tray?.done?.fields?.[name], v)}`)
    .join(", ");
}

export function ReopenButton({ item }: { item: Item }) {
  const reopen = useItemReopen();
  const toast = useToast();
  return (
    <button
      type="button"
      disabled={reopen.isPending}
      onClick={() =>
        reopen
          .mutateAsync(item.id)
          .then(() => toast({ kind: "info", text: `Reopened: ${item.title}` }))
          .catch((e) => toast({ kind: "error", text: `Could not reopen ${item.title}: ${errorText(e)}` }))
      }
    >
      Reopen
    </button>
  );
}

/** What the item panel leads with: a bill (its tray has an IBAN field), a dated item
 * (the tray has a date field) or one that waits (To read). */
export type ItemKind = "bill" | "dated" | "waiting";

export function itemKind(tray: TrayDef | undefined): ItemKind {
  const fields = Object.values(tray?.fields ?? {});
  if (fields.some((f) => f.type === "iban")) return "bill";
  return tray?.date_field ? "dated" : "waiting";
}

/** Done from the button (``done``) or "<done label> and file…" (``file``). */
export type DoneMode = "done" | "file";

const hasValue = (v: unknown) => v !== undefined && v !== null && v !== "";

/** The bill's copy rows: payee, IBAN, reference, amount and due date (the tray's fields
 * of those kinds, in that order); each copies its raw value. */
function paymentNames(tray: TrayDef): string[] {
  const defs = tray.fields ?? {};
  const byType = (type: string) => Object.keys(defs).find((n) => defs[n].type === type);
  const amount = amountField(tray);
  return [
    "payee" in defs ? "payee" : undefined,
    byType("iban"),
    byType("reference"),
    amount ?? undefined,
    tray.date_field ?? undefined,
  ].filter((n, i, all): n is string => n !== undefined && all.indexOf(n) === i);
}

/** What Pay mode shows next to the large barcode, to check it against the bill: payee,
 * IBAN, reference, amount and due date as text (those with a valid value), in the
 * order of the copy rows. */
function payFacts(item: Item, tray: TrayDef): PayFact[] {
  const defs = tray.fields ?? {};
  const facts: PayFact[] = [];
  for (const name of paymentNames(tray)) {
    const def = defs[name];
    const value = item.fields[name];
    if (typeof value !== "string" || value === "" || item.invalid_fields.includes(name)) continue;
    let text = value;
    if (def.type === "iban" || (def.type === "reference" && /^RF/i.test(value))) text = groupIban(value);
    else if (def.type === "money") text = formatMoney(value);
    else if (def.type === "date") text = formatDate(value);
    facts.push({ label: fieldLabel(name), value: text, copy: { raw: value, type: def.type, label: fieldWord(name) } });
  }
  return facts;
}

function PaymentDetails({ item, tray, today }: { item: Item; tray: TrayDef; today: string }) {
  const defs = tray.fields ?? {};
  const names = paymentNames(tray);
  return (
    <ul className="facts" aria-label="Payment details">
      {names.map((name) => {
        const def = defs[name];
        const value = item.fields[name];
        const invalid = item.invalid_fields.includes(name);
        const text = typeof value === "string" ? value : null;
        let shown: ReactNode = "—";
        if (hasValue(value) && (invalid || text === null)) {
          shown = `${visible(formatField(undefined, value))} (invalid)`;
        } else if (text !== null && text !== "") {
          if (def.type === "iban" || (def.type === "reference" && /^RF/i.test(text))) shown = visible(groupIban(text));
          else if (def.type === "money") shown = visible(formatMoney(text));
          else if (def.type === "date") shown = visible(formatDate(text));
          else shown = visible(text);
        }
        const copyable = text !== null && text !== "" && !invalid;
        return (
          <li key={name} className="fact">
            <span className="fact-label">{visible(fieldLabel(name))}</span>
            <span className="fact-value">
              {shown}
              {copyable && def.type === "date" && item.state === "open" && (
                <>
                  {" "}
                  <UrgencyTag date={text} today={today} />
                </>
              )}
            </span>
            {copyable ? (
              <CopyButton compact value={text} type={def.type} label={fieldWord(name)} />
            ) : (
              <span aria-hidden="true" />
            )}
          </li>
        );
      })}
    </ul>
  );
}

type ItemProps = {
  trays: Map<string, TrayDef>;
  today: string;
  /** The done form is open (and for which button), or not. */
  done: DoneMode | null;
  setDone: (mode: DoneMode | null) => void;
  onClose: () => void;
  /** Opens Quick Look on the item's file (the tray list's). */
  onQuickLook?: () => void;
};

export default function ItemDetail({ id, ...rest }: ItemProps & { id: number }) {
  const query = useItem(id);
  if (query.isPending) return <p>Loading…</p>;
  if (query.isError) {
    return (
      <p className="error" role="alert">
        Could not load this item. {visible(errorText(query.error))}
      </p>
    );
  }
  return <ItemBody item={query.data} {...rest} />;
}

/** "Mark done" unless the tray names its own done label ("Mark paid"). */
const markLabel = (doneLabel: string) => (doneLabel === "Done" ? "Mark done" : doneLabel);

function ItemBody({ item, trays, today, done: doneMode, setDone, onClose, onQuickLook }: ItemProps & { item: Item }) {
  const files = useItemFiles(item.id);
  const change = useItemFileChange();
  const client = useQueryClient();
  const navigate = useNavigate();
  const toast = useToast();
  const filing = useRef(false); // synchronous: one look for the inbox file per done
  const headingId = useId();
  const [tab, setTab] = useState(0);
  const [adding, setAdding] = useState(false);
  const [fileError, setFileError] = useState<string | null>(null);
  const [removing, setRemoving] = useState(false);
  const moveItem = useMoveItem();
  const undoMove = useUndoMoveItem();
  const actionsRef = useRef<HTMLDivElement>(null);
  const list = files.data ?? [];
  const shown: ItemFile | undefined = list[Math.min(tab, list.length - 1)];
  const nameOf = (f: ItemFile) => visible(f.path ? baseName(f.path) : f.drive_id);
  // Trash (the action row's bin, ⌘⌫ with the focus on that row): the shown file. It stays
  // one of the item's files, shown as in ##. To Delete; Undo puts it back.
  const trash = useTrash();
  const canTrash = (f: ItemFile) => !!f.path && f.state === "ok";
  const trashFile = (f: ItemFile) => {
    if (!canTrash(f)) return;
    const refusal = deletionRefusal(f.path!, f.marks);
    if (refusal) toast({ kind: "info", text: refusal });
    else trash.start([f.drive_id]);
  };
  useKeydown((e) => {
    if (!isTrashKey(e) || !(e.target instanceof Element) || !shown) return;
    if (!actionsRef.current?.contains(e.target)) return;
    e.preventDefault();
    trashFile(shown);
  });
  /** Move this item to another tray: it goes on being shown there, with an Undo. */
  const moveTo = async (target: TrayDef) => {
    const from = item.tray_id;
    try {
      const moved = await moveItem.mutateAsync({ id: item.id, tray: target.id });
      navigate(`/trays/${encodeURIComponent(target.id)}?item=${item.id}`);
      toast({
        kind: "info",
        text: `Moved to ${visible(target.name)}: ${visible(moved.title)}`,
        action: {
          label: "Undo",
          run: () =>
            void undoMove.mutateAsync(item.id).then(
              () => navigate(`/trays/${encodeURIComponent(from)}?item=${item.id}`),
              (e) => toast({ kind: "error", text: `Could not move it back: ${visible(errorText(e))}` }),
            ),
        },
      });
    } catch (e) {
      toast({ kind: "error", text: `Could not move ${visible(item.title)}: ${visible(errorText(e))}` });
    }
  };
  /** Take a file off the item (DB only: the file stays where it is), with Undo: the
   * link holds nothing but the two ids, so adding it back restores it. */
  const takeOff = async (f: ItemFile) => {
    setFileError(null);
    try {
      await change.mutateAsync({ id: item.id, driveId: f.drive_id, remove: true });
    } catch (e) {
      setFileError(errorText(e));
      return;
    }
    const name = f.path ? visible(baseName(f.path)) : "the file";
    const putBack = () =>
      change.mutateAsync({ id: item.id, driveId: f.drive_id }).catch((e: unknown) => {
        toast({ kind: "error", text: `Could not put ${name} back: ${visible(errorText(e))}` });
      });
    toast({ kind: "info", text: `Taken off the item: ${name}`, action: undoAction(() => void putBack()) });
  };

  const tray = trays.get(item.tray_id);
  const kind = itemKind(tray);
  const doneLabel = tray?.done?.label ?? "Done";
  // the same words on the button and on the form's submit ("Mark paid and file…")
  const doneText = markLabel(doneLabel);
  const fileLabel = `${doneText} and file…`;
  const amount = amountField(tray);
  const amountValue = amount ? item.fields[amount] : undefined;
  const firstPath = list.find((f) => f.path)?.path;
  const open = item.state === "open";
  const anyInInbox = list.some((f) => f.in_inbox);

  /** After "<done> and file…": the inbox with the item's file selected, if one is still
   * there; else say there is nothing to file. The file is filed from the inbox, not here. */
  const fileIt = async () => {
    if (filing.current) return;
    filing.current = true;
    try {
      const fresh = await client.fetchQuery({ ...itemFilesQuery(item.id), staleTime: 0 });
      const target = fresh.find((f) => f.in_inbox);
      if (target) navigate(`/inbox?file=${encodeURIComponent(target.drive_id)}`);
      else toast({ kind: "info", text: `Nothing to file: ${item.title} has no file left in the inbox.` });
    } catch (e) {
      toast({ kind: "error", text: `Could not look for ${item.title}'s file in the inbox: ${errorText(e)}` });
    } finally {
      filing.current = false;
    }
  };
  const checklist = <Checklist kind="item" target={String(item.id)} />;

  const addLabel = list.length > 0 ? "Add another file…" : "Add a file…";
  const addButton = (
    <button
      type="button"
      className="link-button"
      data-tip={ADD_FILE_TIP}
      aria-expanded={adding}
      onClick={() => setAdding((a) => !a)}
    >
      {addLabel}
    </button>
  );

  const doneButtons =
    open && !doneMode ? (
      <>
        <TipButton
          className="primary"
          tip="Mark this item done; it moves to the Done list"
          disabled={tray === undefined}
          disabledReason={TRAYS_LOADING}
          onClick={() => setDone("done")}
        >
          {visible(doneText)}
        </TipButton>
        {anyInInbox && (
          <TipButton
            tip="Mark this item done, then open its file in the Inbox to file it"
            disabled={tray === undefined}
            disabledReason={TRAYS_LOADING}
            onClick={() => setDone("file")}
          >
            {visible(fileLabel)}
          </TipButton>
        )}
      </>
    ) : null;

  /** Quick Look, Move to / Remove from tray, then the shown file's own actions (``ask`` is
   * its Ask AI): one cluster of icons at the right. */
  const actionRow = (ask?: ReactNode) => (
    <div className="item-actions" ref={actionsRef}>
      <span className="item-tray-actions" role="group" aria-label="This item">
        {onQuickLook && firstPath && <IconButton icon={<Eye />} label="Quick Look" shortcut="Space" onClick={onQuickLook} />}
        {/* also by dragging the item onto a tray in the sidebar; this is the way without a mouse */}
        {open && <Menu label="Move to tray" icon={<ArrowRightLeft />} entries={moveEntries} align="end" />}
        {/* Not a bin: removing from the tray deletes nothing (the bin is To Delete). */}
        <IconButton
          icon={<CircleMinus />}
          label="Remove from tray"
          tip="Remove from this tray (the files stay where they are)"
          disabled={moveItem.isPending}
          onClick={() => setRemoving(true)}
        />
      </span>
      {shown && (
        <span className="item-file-actions" role="group" aria-label="This file">
          {ask}
          {canTrash(shown) && (
            <TrashButton
              disabled={trash.busy}
              disabledReason={deletionRefusal(shown.path!, shown.marks)}
              onClick={() => trashFile(shown)}
            />
          )}
          <IconButton
            icon={<Unlink />}
            label="Take this file off the item (the file stays where it is)"
            disabled={change.isPending}
            onClick={() => void takeOff(shown)}
          />
        </span>
      )}
    </div>
  );

  const tag = open && item.date ? <UrgencyTag date={item.date} today={today} /> : null;
  // a bill's fields below the facts are the rest; its top row is the title and the done buttons
  const fields = (
    <Fields key={item.id} item={item} tray={tray} tag={tag} trailing={doneButtons} part={kind === "bill" ? "title" : "all"} />
  );
  const moveEntries: MenuEntry[] = [...trays.values()]
    .filter((t) => t.id !== item.tray_id)
    .map((t) => ({ label: visible(t.name), disabled: moveItem.isPending, onSelect: () => void moveTo(t) }));
  if (moveEntries.length === 0) moveEntries.push({ label: "No other trays", disabled: true, onSelect: () => {} });

  return (
    <div className={`item-detail item-${kind}`}>
      {removing && (
        <RemoveItemSheet
          item={item}
          onClose={() => setRemoving(false)}
          onRemoved={() => {
            setRemoving(false);
            toast({ kind: "info", text: `Removed from ${visible(item.tray_name)}: ${visible(item.title)}` });
            onClose();
          }}
        />
      )}
      <header className="item-header">
        <div className="item-heading">
          <h2 id={headingId}>{visible(item.title)}</h2>
          <p className="item-sub">
            {visible(item.tray_name)}
            {item.tray_removed && " (removed tray)"}
            {firstPath && (
              <>
                {" · "}
                <span className="item-file">{visible(baseName(firstPath))}</span>
              </>
            )}
          </p>
        </div>
        {kind === "bill" && typeof amountValue === "string" && amountValue !== "" && (
          <div className="bill-amount">
            {item.invalid_fields.includes(amount!) ? visible(amountValue) : visible(formatMoney(amountValue))}
          </div>
        )}
        <IconButton icon={<X />} label="Close" onClick={onClose} />
      </header>
      {files.isError && (
        <p className="error" role="alert">
          Could not load the files. {visible(errorText(files.error))}
        </p>
      )}
      {/* one file: a count and the way to attach another; several: the files as tabs */}
      {list.length > 1 ? (
        <div className="item-files-line">
          <div className="tabs" role="tablist" aria-label="Files">
            {list.map((f, i) => (
              <button key={f.drive_id} type="button" role="tab" aria-selected={f === shown} onClick={() => setTab(i)}>
                {nameOf(f)}
                <MarkIcons marks={f.marks} />
                {FILE_BADGE[f.state] && <span className="badge badge-error">{FILE_BADGE[f.state]}</span>}
              </button>
            ))}
          </div>
          {addButton}
        </div>
      ) : (
        files.isSuccess && (
          <p className="item-files-line">
            <span>{plural(list.length, "file")}</span>
            {list.length === 1 && FILE_BADGE[list[0].state] && <span className="badge badge-error">{FILE_BADGE[list[0].state]}</span>}
            <span aria-hidden="true">·</span>
            {addButton}
          </p>
        )
      )}
      {adding && (
        <AddFile
          taken={item.files}
          choose={(hit) => change.mutateAsync({ id: item.id, driveId: hit.drive_id })}
          onDone={() => setAdding(false)}
        />
      )}
      {fields}
      {kind === "waiting" && open && (
        <p className="item-waited">Waiting {waited(daysBetween(dayOf(item.created), today))}</p>
      )}
      <ItemSummary item={item} />
      {kind === "bill" && tray && <PaymentDetails item={item} tray={tray} today={today} />}
      {kind === "bill" && open && <Barcode itemId={item.id} pay={tray ? payFacts(item, tray) : undefined} />}
      {item.state === "done" ? (
        <p className="item-done">
          Done{item.done_at !== null && (
            <>
              {" "}
              <RelativeDate date={dayOf(item.done_at)} today={today} />
            </>
          )}
          {item.done_fields && Object.keys(item.done_fields).length > 0 && ` · ${visible(doneFieldsText(item, tray))}`}{" "}
          <ReopenButton item={item} />
        </p>
      ) : (
        doneMode && (
          <DoneForm
            item={item}
            label={doneText}
            submitLabel={doneMode === "file" ? fileLabel : undefined}
            fields={tray?.done?.fields ?? {}}
            today={today}
            onClose={() => setDone(null)}
            onDone={doneMode === "file" ? () => void fileIt() : undefined}
          />
        )
      )}
      {/* not before the files are known: the action row is rebuilt when the shown file is first found */}
      <div className="item-files">
        {files.isPending ? null : shown?.path && shown.state !== "missing" ? (
          <FileMeta key={shown.drive_id} file={{ drive_id: shown.drive_id, path: shown.path, marks: shown.marks }} disabled={trash.busy}>
            {(meta) => (
              <>
                {actionRow(meta.ask)}
                {fileError && (
                  <p className="error" role="alert">
                    {visible(fileError)}
                  </p>
                )}
                {kind === "dated" && checklist}
                {meta.header}
                <FilePreview file={{ drive_id: shown.drive_id, path: shown.path ?? "", ext: shown.ext }} extraTools={meta.marks} />
                {meta.tags}
              </>
            )}
          </FileMeta>
        ) : (
          <>
            {actionRow()}
            {fileError && (
              <p className="error" role="alert">
                {visible(fileError)}
              </p>
            )}
            {kind === "dated" && checklist}
            {shown?.state === "missing" && <p className="notice">This file is missing from the archive.</p>}
          </>
        )}
        {trash.view}
      </div>
      {kind === "bill" && <Fields key={`rest-${item.id}`} item={item} tray={tray} part="rest" />}
      <SavedNote kind="item" target={String(item.id)} />
      {kind !== "dated" && checklist}
      <History item={item} tray={tray} today={today} />
    </div>
  );
}
