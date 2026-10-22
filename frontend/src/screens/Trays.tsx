/** Trays: the sidebar picks the tray; its open (or done) items in a list column, and the
 * selected item beside it (a bill: amount, copy rows and the bank barcode).
 * ``/trays/<tray>?item=<id>`` opens that item (Today links here). Space opens Quick
 * Look on the selected row's file, and the viewer window follows the selection. */
import { Inbox as InboxIcon } from "lucide-react";
import { type ReactNode, useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { archiveKey, errorText, type ItemState, type TrayDef, type TrayItem, useItems, useToday, useTrays } from "../api/client";
import { ItemBadges } from "../components/ItemBadges";
import { TrayDefaultsBanner } from "../components/TrayDefaults";
import { deletionRefusal } from "../components/MoveTo";
import { useTrash } from "../components/Trash";
import { RelativeDate, useLocalToday } from "../components/RelativeDate";
import { daysBetween, waited } from "../components/today/time";
import { amountField } from "../components/today/TrayCard";
import { EmptyState } from "../components/ui/EmptyState";
import { Segmented } from "../components/ui/Segmented";
import { Splitter, useSplitWidth } from "../components/ui/SplitPane";
import { Toolbar } from "../components/ui/Toolbar";
import { UrgencyTag } from "../components/UrgencyTag";
import { useQuickPut } from "../components/useQuickPut";
import { type QLFile, useQuickLook } from "../components/useQuickLook";
import { dayOf, formatField, formatMoney, plural } from "../format";
import { isShortcut, OWN_ENTER, useKeydown } from "../keyboard";
import { setDragFiles } from "../dnd";
import { publishSelection } from "../selection";
import { visible } from "../text";
import ItemDetail, { AddFile, type DoneMode, doneFieldsText, itemKind, ReopenButton } from "./ItemDetail";
import { MarkIcons } from "../components/MarkIcons";

/** Where the done form is open: the item, and which button opened it. */
type DoneAt = { id: number; mode: DoneMode } | null;

const KEYS: [string[], string][] = [
  [["↑", "↓"], "move"],
  [["Enter"], "open"],
  [["d"], "done"],
  [["Space"], "Quick Look"],
];
/** A bill's tray also opens the barcode in Pay mode with one key. */
const BILL_KEYS: [string[], string][] = [[["b"], "large barcode"]];

/** A list row, as Mail lists messages: title and payee, the urgency tag and amount (or
 * how long it has waited) on the right, then any badges. Copying and Done are in the
 * item panel. */
function Row({
  item,
  tray,
  today,
  selected,
  href,
  onOpen,
}: {
  item: TrayItem;
  tray: TrayDef | undefined;
  today: string;
  selected: boolean;
  href: string;
  onOpen: () => void;
}) {
  const kind = itemKind(tray);
  const amount = amountField(tray);
  const amountValue = amount ? item.fields[amount] : undefined;
  // The same guard as the bill view's copy rows: only a tray that has a payee field.
  const payeeValue = tray && "payee" in (tray.fields ?? {}) ? item.fields.payee : undefined;
  const payee = hasText(payeeValue) ? payeeValue : null;
  const open = item.state === "open";
  const cls = ["tray-row", item.level && `tray-row-${item.level}`].filter(Boolean).join(" ");

  return (
    <article className={cls} aria-label={visible(item.title)}>
      <div className="tray-row-main">
        <p className="tray-row-title">
          <Link to={href} onClick={onOpen} aria-current={selected ? "true" : undefined}>
            {visible(item.title)}
          </Link>
          <MarkIcons marks={item.first_file?.marks} />
        </p>
        {payee && <p className="tray-row-sub">{visible(payee)}</p>}
        <ItemBadges
          level={item.level}
          missingRequired={open ? item.missing_required : []}
          dateField={tray?.date_field}
          fileState={item.file_state}
        />
        {!open && (
          <p className="tray-row-done">
            Done{item.done_at !== null && (
              <>
                {" "}
                <RelativeDate date={dayOf(item.done_at)} today={today} />
              </>
            )}
            {item.done_fields && Object.keys(item.done_fields).length > 0 && ` · ${visible(doneFieldsText(item, tray))}`}{" "}
            <ReopenButton item={item} />
          </p>
        )}
      </div>
      <div className="tray-row-side">
        {open && item.date && <UrgencyTag date={item.date} today={today} />}
        {hasText(amountValue) && (
          <span className="tray-row-amount">
            {item.invalid_fields.includes(amount!)
              ? `${visible(formatField(undefined, amountValue))} (invalid)`
              : visible(formatMoney(amountValue))}
          </span>
        )}
        {kind === "waiting" && open && (
          <span className="tray-row-age">{waited(daysBetween(dayOf(item.created), today))}</span>
        )}
        <span className="tray-row-meta">
          {item.has_note && (
            <span className="note-icon" role="img" aria-label="Has a note" title="Has a note">
              ✎
            </span>
          )}
          {plural(item.files.length, "file")}
        </span>
      </div>
    </article>
  );
}

const hasText = (v: unknown): v is string => typeof v === "string" && v !== "";

/** ``today`` is the local date (kept current) unless given (tests pass a fixed one). */
export default function Trays({ today: fixed }: { today?: string }) {
  const local = useLocalToday();
  const today = fixed ?? local;
  const split = useSplitWidth(archiveKey("dam.trays.listwidth"), { min: 220, max: 520, initial: 295, unit: "px" });
  const trays = useTrays();
  const overview = useToday().data?.overview;
  const params = useParams();
  const [search, setSearch] = useSearchParams();
  const defs = trays.data?.trays ?? [];
  const trayId = params.trayId ?? defs[0]?.id ?? "";
  const tray = defs.find((t) => t.id === trayId);
  // The filter is in the URL (?state=done); a sidebar link has none, so it resets.
  const state: ItemState = search.get("state") === "done" ? "done" : "open";
  const items = useItems(trayId, state);
  const list = useMemo(() => (trayId ? (items.data ?? []) : []), [trayId, items.data]);
  const opened = Number(search.get("item")) || null;
  const [doneAt, setDoneAt] = useState<DoneAt>(null);
  // "Add file": search the index and put the chosen file in this tray as a new item
  const [addingFile, setAddingFile] = useState(false);
  const quickPut = useQuickPut();
  const listRef = useRef<HTMLUListElement>(null);
  const focusRow = useRef(false);
  // A done form belongs to the item it was opened on: another item closes it, so coming
  // back never finds it still open. (``d`` sets both at once, so its form stays.)
  useEffect(() => {
    setDoneAt((at) => (at && at.id !== opened ? null : at));
  }, [opened]);

  // The cursor belongs to one list: another tray or filter starts at the opened item
  // (a Today link) or at the top.
  const view = `${trayId}\n${state}`;
  const [cursor, setCursor] = useState<{ view: string; index: number } | null>(null);
  const openedIndex = list.findIndex((i) => i.id === opened);
  const index =
    cursor?.view === view
      ? Math.min(cursor.index, Math.max(0, list.length - 1))
      : Math.max(0, openedIndex);
  const current = list[index] as TrayItem | undefined;
  // The highlighted row is the open item: until the user picks one (a click, a key or a
  // Today link) no row is highlighted, so no row looks selected while the panel is empty.
  const picked = cursor?.view === view || opened !== null;

  useEffect(() => {
    if (!focusRow.current) return;
    focusRow.current = false;
    listRef.current?.querySelectorAll<HTMLAnchorElement>(".tray-row-title a")[index]?.focus();
  }, [index, view]);
  useEffect(() => {
    listRef.current?.querySelector("li[aria-current]")?.scrollIntoView({ block: "nearest" });
  }, [index, view]);

  // The viewer window (if it follows the selection) shows the selected row's file.
  const selectedFile = current?.first_file?.drive_id ?? current?.files[0];
  useEffect(() => {
    if (selectedFile) publishSelection(selectedFile);
  }, [selectedFile]);

  /** The query string for this filter with ``item`` opened (none: the panel is empty). */
  const query = (filter: ItemState, item: number | null) => {
    const q = new URLSearchParams();
    if (filter === "done") q.set("state", "done");
    if (item !== null) q.set("item", String(item));
    return q;
  };
  const open = (item: TrayItem | undefined, replace = false) => {
    if (!item) return;
    setSearch(query(state, item.id), replace ? { replace: true } : undefined);
  };
  /** The cursor moves and the item under it opens in the panel (like Mail). */
  const move = (delta: number) => {
    if (list.length === 0) return;
    focusRow.current = listRef.current?.contains(document.activeElement) ?? false;
    // nothing picked yet: the first step lands on the first (or last) row
    const from = picked ? index : delta > 0 ? -1 : list.length;
    const next = Math.max(0, Math.min(list.length - 1, from + delta));
    setCursor({ view, index: next });
    open(list[next], true);
  };

  // Quick Look: each row's first file (rows without an indexed file are left out).
  const withFile = useMemo(
    () => list.map((item, i) => ({ item, i })).filter((e) => e.item.first_file?.path),
    [list],
  );
  const qlFiles = useMemo<QLFile[]>(
    () =>
      withFile.map(({ item }) => {
        const f = item.first_file!;
        return { drive_id: f.drive_id, name: null, path: f.path!, ext: f.ext, marks: f.marks };
      }),
    [withFile],
  );
  // Trash from Quick Look: the first file it shows (the item keeps it, as in ##. To Delete).
  const trash = useTrash();
  const quickLook = useQuickLook(
    qlFiles,
    Math.max(0, withFile.findIndex((e) => e.i === index)),
    (k) => {
      const target = withFile[k];
      if (!target) return;
      setCursor({ view, index: target.i });
      open(target.item);
    },
    {
      canOpen: () => !!current?.first_file?.path && !trash.running(),
      trashRefusal: (file) => deletionRefusal(file.path, file.marks),
      trashBusy: trash.busy,
      onTrash: (file, ui) =>
        trash.start([file.drive_id], {
          links: !!file.is_link,
          onConfirming: ui.close,
          onRefused: ui.report,
          onCancelled: ui.reopen,
        }),
    },
  );

  useKeydown((e) => {
    if (!isShortcut(e)) return;
    // The list's keys belong to the list: never while the focus is in the item panel.
    if (e.target instanceof Element && e.target.closest(".trays-detail")) return;
    if (e.key === "j" || e.key === "ArrowDown") move(1);
    else if (e.key === "k" || e.key === "ArrowUp") move(-1);
    else if (e.key === "Enter") {
      if ((e.target as HTMLElement).closest?.(OWN_ENTER)) return; // a focused control acts itself
      if (current) setCursor({ view, index });
      open(current);
    } else if (e.key === "d") {
      if (!current || !picked || current.state !== "open" || !tray) return;
      open(current);
      setDoneAt({ id: current.id, mode: "done" });
    } else return;
    e.preventDefault();
  });

  if (trays.isPending) return <p className="placeholder">Loading…</p>;
  if (trays.isError) {
    return (
      <p className="error" role="alert">
        Could not load the trays. {visible(errorText(trays.error))}
      </p>
    );
  }
  const byId = new Map(defs.map((t) => [t.id, t]));

  let body: ReactNode;
  if (!trayId) body = <EmptyState icon={<InboxIcon size={40} strokeWidth={1.25} />} title="No trays are set up." />;
  else if (items.isPending) body = <p className="placeholder tray-loading">Loading…</p>;
  else if (items.isError) {
    body = (
      <p className="error" role="alert">
        Could not load this tray. {visible(errorText(items.error))}
      </p>
    );
  } else if (list.length === 0) {
    body = (
      <EmptyState
        icon={<InboxIcon size={40} strokeWidth={1.25} />}
        title={state === "open" ? "Nothing open in this tray." : "Nothing done yet."}
      />
    );
  } else {
    body = (
      <ul ref={listRef} className="tray-items" aria-label="Items">
        {list.map((item, i) => (
          <li
            key={item.id}
            data-quicklook
            aria-current={picked && i === index ? "true" : undefined}
            draggable={item.files.length > 0 ? true : undefined}
            onDragStart={item.files.length > 0 ? (e) => setDragFiles(e, item.files, visible(item.title)) : undefined}
          >
            <Row
              item={item}
              tray={byId.get(item.tray_id)}
              today={today}
              selected={item.id === opened}
              href={`?${query(state, item.id)}`}
              onOpen={() => setCursor({ view, index: i })}
            />
          </li>
        ))}
      </ul>
    );
  }

  const count = overview?.trays.find((t) => t.tray_id === trayId);
  let subtitle: string | undefined;
  if (state === "open" && tray?.summary && count?.sum != null) subtitle = formatMoney(count.sum);
  else if (items.data) subtitle = `${list.length} ${state}`;

  return (
    <div className="trays" ref={split.hostRef} style={split.hostStyle}>
      <section className="trays-list" aria-label="Tray items">
        <Toolbar
          title={visible(tray?.name ?? trayId)}
          subtitle={subtitle}
          actions={
            <>
            <button
              type="button"
              className="tray-add-file"
              data-tip="Add another file to the tray"
              disabled={!tray}
              aria-expanded={addingFile}
              onClick={() => setAddingFile((a) => !a)}
            >
              Add file
            </button>
            <Segmented
              ariaLabel="Show"
              value={state}
              onChange={(s) => setSearch(query(s, opened))}
              options={[
                { value: "open", label: "Open" },
                { value: "done", label: "Done" },
              ]}
            />
            </>
          }
        />
        {addingFile && tray && (
          <AddFile
            taken={list.flatMap((i) => i.files)}
            choose={async (hit) => {
              const [created] = await quickPut.put({ tray: tray.id, trayName: tray.name, ids: [hit.drive_id], name: hit.name });
              // the new item is open in the panel (it is in the open list, so show that)
              if (created) setSearch(query("open", created.id));
            }}
            onDone={() => setAddingFile(false)}
          />
        )}
        {trays.data.errors.map((e) => (
          <p key={e.file} className="hint tray-error">
            Tray file skipped — {visible(e.file)}: {visible(e.message)}
          </p>
        ))}
        {tray && <TrayDefaultsBanner key={tray.id} tray={tray} />}
        {body}
        <p className="hint inbox-keys">
          {(tray && itemKind(tray) === "bill" ? [...KEYS, ...BILL_KEYS] : KEYS).map(([keys, what]) => (
            <span key={what} className="key-group">
              {keys.map((k) => (
                <kbd key={k}>{k}</kbd>
              ))}{" "}
              {what}
            </span>
          ))}
        </p>
      </section>
      <Splitter split={split} label="Resize the list" />
      <section className="trays-detail" aria-label="Item">
        {opened !== null ? (
          <ItemDetail
            key={opened}
            id={opened}
            trays={byId}
            today={today}
            done={doneAt?.id === opened ? doneAt.mode : null}
            setDone={(mode) => setDoneAt(mode ? { id: opened, mode } : null)}
            onClose={() => setSearch(query(state, null))}
            onQuickLook={current?.id === opened ? quickLook.open : undefined}
          />
        ) : (
          <EmptyState title="No item selected" hint="Select an item to see its details, files, note and history." />
        )}
      </section>
      {quickLook.view}
      {trash.view}
    </div>
  );
}
