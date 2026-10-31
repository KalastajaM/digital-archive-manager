/** One tray item: its files (preview), title and fields (saved on blur or Enter), note,
 * checklist, history, and Mark done/Reopen. A bill (a tray with an IBAN field) leads with its
 * amount, copy rows and the bank barcode; a dated item with its date and checklist; an
 * undated one with how long it has waited. Everything here changes the database only,
 * through the API: adding or removing a file never moves it. */
import { useQueryClient } from "@tanstack/react-query";
import { CircleMinus, X } from "lucide-react";
import { type ReactNode, useId, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  errorText,
  LOCKED_REASON,
  useIsBlocked,
  itemFilesQuery,
  type FieldDef,
  type Item,
  type ItemEvent,
  type ItemFile,
  type TrayDef,
  useFileLinks,
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
import { Barcode } from "../components/Barcode";
import { paymentNames } from "../components/payFacts";
import { markLabel } from "../components/useMarkDone";
import { Checklist } from "../components/Checklist";
import { Collapsible } from "../components/Collapsible";
import { CopyButton } from "../components/CopyButton";
import { DoneForm } from "../components/DoneForm";
import { EditableTitle } from "../components/EditableTitle";
import { editText, FieldInput } from "../components/FieldInput";
import { FILE_BADGE } from "../components/ItemBadges";
import { RelativeDate } from "../components/RelativeDate";
import { SavedNote, SaveState } from "../components/SavedNote";
import { daysBetween, waited } from "../components/today/time";
import { amountField } from "../components/today/TrayCard";
import { undoAction, useToast } from "../components/Toasts";
import { IconButton } from "../components/ui/IconButton";
import { type FileActionBarProps, useAskAction } from "../components/FileActionBar";
import { useFilingAI } from "../components/ai/useFilingAI";
import { allMarked, useBatchMark } from "../components/useBatchMark";
import { toDeleteReason } from "../toDelete";
import { Popover } from "../components/ui/Popover";
import { Tag } from "../components/ui/Tag";
import { TipButton } from "../components/ui/TipButton";
import { Menu, type MenuEntry } from "../components/ui/Menu";
import { RemoveItemSheet } from "../components/RemoveItemSheet";
import { UrgencyTag } from "../components/UrgencyTag";
import { useAutoSave } from "../components/useAutoSave";
import { dayOf, fieldLabel, fieldWord, formatDate, formatField, formatMoney, groupIban, plural } from "../format";
import { visible } from "../text";
import { AddFile } from "../components/AddFile";
import { browseHref } from "../components/GroupTree";
import { FilePanel } from "./FilePanel";
import { FileActionIcons } from "../components/FileActionIcons";
import { type AssignKind, AssignSheet } from "../components/zones/FromFor";
import { backToInbox, deletionRefusal, inboxRefusal, MOVE_BUSY, useInboxFolder, useMoveFlow } from "../components/MoveTo";
import { isTrashKey, useTrash } from "../components/Trash";
import { MarkIcons } from "../components/MarkIcons";
import { useKeydown } from "../keyboard";
import { readDragFiles, readDragItem, useDropTarget } from "../dnd";
import { baseName } from "../paths";
import { collectionHref } from "../collectionHref";


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
  /** The width class on the fields row: each kind has its own width. */
  size?: "date" | "text" | "money" | "checkbox";
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

/** The item's editable fields on one action row that wraps only when the panel is narrow:
 * the tray's fields in order (a date with its urgency tag after it), then ``trailing``
 * (the done buttons). The file's icon buttons are in the side panel (``FileActionIcons``);
 * the title is edited in the item header. ``part``: a bill shows only the done buttons in
 * its top row and the fields further down. */
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
  part?: "all" | "top" | "rest";
}) {
  const update = useItemUpdate();
  return (
    <div className="item-fields">
      {part !== "top" && tray === undefined && Object.keys(item.fields).length > 0 && (
        <p className="hint">
          The tray of this item was removed from the settings: its fields cannot be edited.{" "}
          {Object.entries(item.fields)
            .map(([n, v]) => `${fieldWord(n)} ${formatField(undefined, v)}`)
            .map(visible)
            .join(" · ")}
        </p>
      )}
      {part !== "top" &&
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

/** The subtitle part "in collection X": the collections of the file shown. */
function InCollection({ driveId }: { driveId: string }) {
  const links = useFileLinks(driveId);
  const found = (links.data?.collections ?? []).filter((c) => c.kind == null);
  if (found.length === 0) return null;
  return (
    <>
      {" · in "}
      {found.length === 1 ? "collection " : "collections "}
      {found.map((c, i) => (
        <span key={c.id}>
          {i > 0 && ", "}
          <Link to={collectionHref(c)}>{visible(c.name)}</Link>
        </span>
      ))}
    </>
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
    case "merged_in": {
      const files = Array.isArray(data.files) ? data.files.length : 0;
      const checks = typeof data.checks === "number" ? data.checks : 0;
      const parts = [
        files > 0 ? plural(files, "file") : null,
        data.note === true ? "a note" : null,
        checks > 0 ? plural(checks, "checklist entry", "checklist entries") : null,
      ].filter(Boolean);
      return `${String(data.title ?? "Another item")} merged in${parts.length > 0 ? `: ${parts.join(", ")}` : ""}`;
    }
    case "moved":
      return `Moved from ${String(data.from_name ?? "another tray")} to ${String(data.to_name ?? "another tray")}`;
  }
}

function History({ item, tray, today }: { item: Item; tray: TrayDef | undefined; today: string }) {
  const history = useItemHistory(item.id);
  const files = useItemFiles(item.id);
  const names = new Map((files.data ?? []).filter((f) => f.path).map((f) => [f.drive_id, baseName(f.path!)]));
  return (
    <Collapsible
      name="history"
      title="History"
      className="history"
      hint={plural(history.data?.length ?? 0, "entry", "entries")}
    >
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
    </Collapsible>
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
  const [doneAnchor, setDoneAnchor] = useState<HTMLButtonElement | null>(null);
  const [fileAnchor, setFileAnchor] = useState<HTMLButtonElement | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  const [removing, setRemoving] = useState(false);
  const moveItem = useMoveItem();
  const undoMove = useUndoMoveItem();
  const actionsRef = useRef<HTMLDivElement>(null);
  const [assigning, setAssigning] = useState<AssignKind | null>(null);
  const update = useItemUpdate();
  const saveTitle = async (title: string) => (await update.mutateAsync({ id: item.id, title })).title;
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
   * link holds nothing but the two ids and its place, so adding it back at that place
   * restores it. The item keeps at least one file (the server refuses otherwise). */
  const takeOff = async (f: ItemFile) => {
    setFileError(null);
    const position = list.findIndex((x) => x.drive_id === f.drive_id);
    try {
      await change.mutateAsync({ id: item.id, driveId: f.drive_id, remove: true });
    } catch (e) {
      setFileError(errorText(e));
      return;
    }
    const name = f.path ? visible(baseName(f.path)) : "the file";
    const putBack = () =>
      change.mutateAsync({ id: item.id, driveId: f.drive_id, position: Math.max(0, position) }).catch((e: unknown) => {
        toast({ kind: "error", text: `Could not put ${name} back: ${visible(errorText(e))}` });
      });
    toast({ kind: "info", text: `Taken off the item: ${name}`, action: undoAction(() => void putBack()) });
  };
  /** Files dropped on the item (dragged from Browse or the search results): attached in
   * order, those it has already skipped; one Undo takes the new ones off again. */
  const attach = async (ids: string[]) => {
    const fresh = ids.filter((d) => !item.files.includes(d));
    const added: string[] = [];
    for (const driveId of fresh) {
      try {
        await change.mutateAsync({ id: item.id, driveId });
        added.push(driveId);
      } catch (e) {
        toast({ kind: "error", text: `Could not add the file to ${visible(item.title)}: ${visible(errorText(e))}` });
        break;
      }
    }
    if (added.length === 0) return;
    const undo = async () => {
      for (const driveId of added) {
        await change.mutateAsync({ id: item.id, driveId, remove: true }).catch((e: unknown) => {
          toast({ kind: "error", text: `Could not take the file off: ${visible(errorText(e))}` });
        });
      }
    };
    toast({
      kind: "info",
      text: `Added ${plural(added.length, "file")} to ${visible(item.title)}`,
      action: undoAction(() => void undo()),
    });
  };
  // Dragging a file from Browse (or the search results) onto the open item attaches it.
  // An item dragged here is no file drop: merging is done on the tray list.
  const fileDrop = useDropTarget<string[]>({
    read: (e) => (readDragItem(e) === null ? readDragFiles(e) : null),
    accept: (ids) => (item.state !== "open" ? false : ids.every((d) => item.files.includes(d)) ? "Already on this item" : true),
    onDrop: (ids) => void attach(ids),
  });

  const tray = trays.get(item.tray_id);
  const kind = itemKind(tray);
  const doneLabel = tray?.done?.label ?? "Done";
  // the same words on the button and on the form's submit ("Mark paid and file…")
  const doneText = markLabel(doneLabel);
  const fileLabel = `${doneText} and file…`;
  const amount = amountField(tray);
  const amountValue = amount ? item.fields[amount] : undefined;
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

  // The confirm opens as a popover under the button that was pressed; pressing it again
  // closes it. The buttons stay while it is open, so the focus has somewhere to return.
  const toggleDone = (mode: DoneMode) => setDone(doneMode === mode ? null : mode);
  const doneButtons =
    open ? (
      <>
        <TipButton
          ref={setDoneAnchor}
          className="primary"
          tip="Mark this item done; it moves to the Done list"
          aria-expanded={doneMode === "done"}
          disabled={tray === undefined}
          disabledReason={TRAYS_LOADING}
          onClick={() => toggleDone("done")}
        >
          {visible(doneText)}
          <kbd aria-hidden="true">d</kbd>
        </TipButton>
        {anyInInbox && (
          <TipButton
            ref={setFileAnchor}
            tip="Mark this item done, then open its file in the Inbox to file it"
            aria-expanded={doneMode === "file"}
            disabled={tray === undefined}
            disabledReason={TRAYS_LOADING}
            onClick={() => toggleDone("file")}
          >
            {visible(fileLabel)}
          </TipButton>
        )}
      </>
    ) : null;

  const moveEntries: MenuEntry[] = [...trays.values()]
    .filter((t) => t.id !== item.tray_id)
    .map((t) => ({ label: visible(t.name), disabled: moveItem.isPending, onSelect: () => void moveTo(t) }));
  if (moveEntries.length === 0) moveEntries.push({ label: "No other trays", disabled: true, onSelect: () => {} });
  // The file actions are one group of icons in the screen's header (the same bar as Browse):
  // Move to tray / Remove from tray act on the item, the rest on the shown file.
  const hasFile = !!shown?.path && shown.state !== "missing";
  const filingAI = useFilingAI();
  const batchMarks = useBatchMark();
  const askBar = useAskAction(
    filingAI,
    hasFile && shown ? { drive_id: shown.drive_id, path: shown.path ?? null } : null,
    "This item has no file",
    trash.busy,
  );
  // Back to inbox moves the shown file (the item stays in its tray), through the move flow:
  // preview, confirm, Undo.
  const fileMove = useMoveFlow();
  const inbox = useInboxFolder();
  const isBlocked = useIsBlocked();
  const inboxWhy =
    hasFile && shown
      ? (inboxRefusal([shown.path!], inbox) ??
        (isBlocked(shown.drive_id, shown.marks, shown.path) ? LOCKED_REASON : null) ??
        (trash.busy || fileMove.busy ? MOVE_BUSY : null))
      : null;
  const markReason = hasFile && shown ? toDeleteReason(shown.path) : null;
  const markable = hasFile && shown ? [{ drive_id: shown.drive_id, name: baseName(shown.path ?? ""), marks: shown.marks }] : [];
  const barProps: FileActionBarProps = {
    barRef: actionsRef,
    removeFromTray: { run: () => setRemoving(true), disabled: moveItem.isPending },
    backToInbox:
      hasFile && shown
        ? {
            run: () => {
              if (inbox && !inboxWhy) fileMove.start(backToInbox([shown.drive_id], inbox, [shown.path!]));
            },
            reason: inboxWhy,
          }
        : undefined,
    // Who sent it / who it is for: the icon rows have them for every context
    sender: hasFile && shown ? { run: () => setAssigning("sender"), disabled: trash.busy, reason: markReason } : undefined,
    person: hasFile && shown ? { run: () => setAssigning("person"), disabled: trash.busy, reason: markReason } : undefined,
    ask: hasFile ? askBar : undefined,
    star: hasFile
      ? {
          on: allMarked(markable, "star"),
          run: () => void batchMarks.run("star", markable),
          disabled: batchMarks.busy,
          reason: markReason,
        }
      : undefined,
    important: hasFile
      ? {
          on: allMarked(markable, "important"),
          run: () => void batchMarks.run("important", markable),
          disabled: batchMarks.busy,
          reason: markReason,
        }
      : undefined,
    trash:
      shown && canTrash(shown)
        ? { run: () => trashFile(shown), disabled: trash.busy, reason: deletionRefusal(shown.path!, shown.marks) }
        : undefined,
  };
  // (Move to tray is also done by dragging the item onto a tray in the sidebar; this is the
  // way without a mouse. Remove from tray is not a bin: it deletes nothing, the bin is To Delete.)
  const { removeFromTray: _item, ...fileIconProps } = barProps;
  void _item;
  const fileIcons = (
    <FileActionIcons
      {...fileIconProps}
      file={
        hasFile && shown
          ? { drive_id: shown.drive_id, path: shown.path ?? null, name: shown.path ? baseName(shown.path) : null, ext: shown.ext }
          : null
      }
      onQuickLook={onQuickLook && hasFile ? onQuickLook : undefined}
      showInFolder={hasFile && shown?.path ? () => navigate(browseHref(shown.path!, shown.drive_id)) : undefined}
    />
  );

  const tag = open && item.date ? <UrgencyTag date={item.date} today={today} /> : null;
  // a bill's fields below the facts are the rest; its top row is the title and the done buttons
  const fields = (
    <Fields
      key={item.id}
      item={item}
      tray={tray}
      tag={tag}
      trailing={doneButtons}
      part={kind === "bill" ? "top" : "all"}
    />
  );

  const filesError = files.isError && (
    <p className="error" role="alert">
      Could not load the files. {visible(errorText(files.error))}
    </p>
  );
  const addPanel = adding && (
    <AddFile
      taken={item.files}
      takenMode="mark"
      takenLabel="already on this item"
      choose={(hit) => change.mutateAsync({ id: item.id, driveId: hit.drive_id })}
      onDone={() => setAdding(false)}
    />
  );
  const removeSheet = removing && (
    <RemoveItemSheet
      item={item}
      onClose={() => setRemoving(false)}
      onRemoved={() => {
        setRemoving(false);
        toast({ kind: "info", text: `Removed from ${visible(item.tray_name)}: ${visible(item.title)}` });
        onClose();
      }}
    />
  );
  const doneNote =
    item.state === "done" ? (
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
    ) : null;
  const donePopover =
    open && doneMode && (doneMode === "file" ? fileAnchor : doneAnchor) ? (
      <Popover
        anchor={doneMode === "file" ? fileAnchor : doneAnchor}
        label={doneMode === "file" ? fileLabel : doneText}
        onClose={() => setDone(null)}
      >
        <DoneForm
          item={item}
          label={doneText}
          submitLabel={doneMode === "file" ? fileLabel : undefined}
          fields={tray?.done?.fields ?? {}}
          today={today}
          onClose={() => setDone(null)}
          onDone={doneMode === "file" ? () => void fileIt() : undefined}
        />
      </Popover>
    ) : null;
  const billFacts = (
    <>
      {kind === "bill" && tray && <PaymentDetails item={item} tray={tray} today={today} />}
      {kind === "bill" && open && <Barcode itemId={item.id} />}
    </>
  );
  const fileProblems =
    files.isSuccess && fileError ? (
      <p className="error" role="alert">
        {visible(fileError)}
      </p>
    ) : null;
  const missingNote = files.isSuccess && shown?.state === "missing" ? <p className="notice">This file is missing from the archive.</p> : null;
  const sheets = (
    <>
      {trash.view}
      {filingAI.sheet}
      {fileMove.view}
      {assigning && shown && <AssignSheet kind={assigning} driveIds={[shown.drive_id]} onClose={() => setAssigning(null)} />}
    </>
  );
  // The title row with Move to tray… and Close, the fields card with Mark done, then one column
  // (as Browse): the files, the one file panel for the file shown, the checklist, note and history.
  const added = formatDate(dayOf(item.created));
  return (
    <div className={`item-detail item-${kind} item-new`} {...fileDrop.props}>
      <header className="item-header">
        <div className="item-heading">
          <EditableTitle key={item.id} value={item.title} save={saveTitle} headingId={headingId} />
          <p className="item-sub">
            {visible(item.tray_name)}
            {item.tray_removed && " (removed tray)"}
            {shown?.path && shown.state !== "missing" && <InCollection driveId={shown.drive_id} />}
            {" · added "}
            {added}
          </p>
        </div>
        <div className="item-actions">
          {kind === "bill" && typeof amountValue === "string" && amountValue !== "" && (
            <div className="bill-amount">
              {item.invalid_fields.includes(amount!) ? visible(amountValue) : visible(formatMoney(amountValue))}
            </div>
          )}
          {open && <Menu label="Move to tray" text="Move to tray…" icon={null} entries={moveEntries} align="end" />}
          <IconButton
            icon={<CircleMinus />}
            label="Remove from tray"
            tip="Remove from this tray (the files stay where they are)"
            disabled={moveItem.isPending}
            onClick={() => setRemoving(true)}
          />
        </div>
        <IconButton icon={<X />} label="Close" onClick={onClose} />
      </header>
      {filesError}
      {removeSheet}
      {fields}
      {kind === "waiting" && open && <p className="item-waited">Waiting {waited(daysBetween(dayOf(item.created), today))}</p>}
      {doneNote}
      {donePopover}
      {fileProblems}
      {missingNote}
      <div className="item-stack">
        {billFacts}
        {kind === "bill" && <Fields key={`rest-${item.id}`} item={item} tray={tray} part="rest" />}
        <section className="item-files-list" aria-label="Files on this item">
          <h3>Files on this item</h3>
          {files.isSuccess && (
            <ul>
              {list.map((f, i) => (
                <li key={f.drive_id} data-shown={f === shown ? "true" : undefined}>
                  <button
                    type="button"
                    className="item-file-pick"
                    aria-pressed={f === shown}
                    title={nameOf(f)}
                    onClick={() => setTab(i)}
                  >
                    <span className="item-file">{nameOf(f)}</span>
                    <MarkIcons marks={f.marks} driveId={f.drive_id} path={f.path} />
                    {FILE_BADGE[f.state] && <Tag tone="red">{FILE_BADGE[f.state]}</Tag>}
                  </button>
                  {f === shown && list.length > 1 && <span className="item-file-shown">shown</span>}
                  {list.length > 1 && (
                    <button
                      type="button"
                      className="tab-close"
                      aria-label={`Remove ${nameOf(f)} from this item`}
                      data-tip="Take this file off the item (the file stays where it is)"
                      disabled={change.isPending}
                      onClick={() => void takeOff(f)}
                    >
                      <X size={12} aria-hidden="true" />
                    </button>
                  )}
                </li>
              ))}
              <li className="item-file-add">{addButton}</li>
            </ul>
          )}
          {addPanel}
        </section>
        <div className="item-file-panel">
          {!files.isPending && shown?.path && shown.state !== "missing" ? (
            <FilePanel
              key={shown.drive_id}
              file={{ drive_id: shown.drive_id, path: shown.path, marks: shown.marks }}
              preview={{ drive_id: shown.drive_id, path: shown.path, ext: shown.ext }}
              disabled={trash.busy}
              headerActions={{ ai: filingAI }}
              actions={fileIcons}
              hideItem={item.id}
              compactRelatives
              boxTool
            />
          ) : (
            <ItemSummary item={item} />
          )}
        </div>
        {checklist}
        <SavedNote kind="item" target={String(item.id)} />
        <History item={item} tray={tray} today={today} />
      </div>
      {sheets}
    </div>
  );
}
