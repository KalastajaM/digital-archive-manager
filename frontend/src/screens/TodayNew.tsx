/** Today, laid out as drawn: the date and a headline built from the real
 * counts with Customize and Start filing, the Convert notice, four stat tiles, then two
 * columns. Left: the "To pay" table (Pay opens Pay mode on that bill, Paid marks it paid;
 * a bill that is overdue or due today opens up with its copy buttons and note) and the
 * other trays as compact lists. Right: the Inbox summary, Collections to do, Starred,
 * Reminders (search lives in the palette and Browse).
 *
 * Customize turns the page into an arrange mode: each section gets its fold chevron and
 * Move up / Move down and can be dragged by its heading, and Reset layout puts them back
 * (kept per archive in this browser). */
import { type CSSProperties, useState } from "react";
import { Link } from "react-router-dom";
import { type AttentionItem, errorText, type Item, type Today as TodayData, useInbox, useToday, useTrays } from "../api/client";
import { AgeBar } from "../components/AgeBar";
import { AIHint, useAIState } from "../components/ai/useAI";
import { DoneForm } from "../components/DoneForm";
import { CopyButton } from "../components/CopyButton";
import { ItemBadges } from "../components/ItemBadges";
import { useLocalClock } from "../components/RelativeDate";
import { FoundList, NotRecognised } from "../components/today/InboxCard";
import { CollectionsCard, needingAttention, Notices, RemindersCard } from "../components/today/pieces";
import { StarredCard } from "../components/today/StarredCard";
import { countsOf, headlineOf, openLine, tilesOf } from "../components/today/summary";
import { waited } from "../components/today/time";
import { amountField, doneName, TrayRow, trayCards, type TrayCardInfo, trayRows } from "../components/today/TrayCard";
import { useTrayItemMenu } from "../components/useTrayItemMenu";
import { SectionContext, TnSection } from "../components/today/TnSection";
import { useCardDrag } from "../components/today/useCardDrag";
import { useCardFrames } from "../components/today/useCardFrames";
import { useCardLayout } from "../components/useCardLayout";
import { useMarkDone } from "../components/useMarkDone";
import { isBillTray, type PayBill, sumOfBills, useOpenBills } from "../components/usePayBills";
import { usePayMode } from "../components/payModeContext";
import { UrgencyTag } from "../components/UrgencyTag";
import { useQuickPut } from "../components/useQuickPut";
import { fieldWord, formatField, longDate, plural } from "../format";
import { visible } from "../text";

const enc = encodeURIComponent;
/** Bills shown in the table before "N more bills"; other trays show fewer. */
const BILL_ROWS = 8;
const LIST_ROWS = 4;

/** The two Convert notices as one line, as drawn. */
function ConvertNotice({ data }: { data: TodayData }) {
  const { unmanaged_ongoing: ongoing, unmanaged_important: important } = data;
  if (ongoing <= 0 && important <= 0) return null;
  const parts = [
    ongoing > 0 ? `${plural(ongoing, "entry", "entries")} in ##. Ongoing` : null,
    important > 0 ? `${plural(important, "entry", "entries")} in ##. Important` : null,
  ].filter((p): p is string => p !== null);
  return (
    <section className="banner page-banner tn-convert" aria-label="Not in the app yet">
      <p>
        {parts.join(" and ")} {ongoing + important === 1 ? "is" : "are"} not in the app yet.
      </p>
      {ongoing > 0 && (
        <Link className="banner-action" to="/ongoing">
          Convert Ongoing
        </Link>
      )}
      {important > 0 && (
        <Link className="banner-action" to="/important/convert">
          Convert Important
        </Link>
      )}
    </section>
  );
}

/** One bill in the table. A bill that is overdue or due today opens up under its row:
 * the copy buttons, the note and the file badge (and the done form, when the tray asks
 * for a value). */
function BillRow({
  bill,
  entry,
  today,
  traysUnknown,
  formOpen,
  setFormOpen,
  onMenu,
}: {
  bill: PayBill;
  entry: AttentionItem | undefined;
  today: string;
  traysUnknown: boolean;
  formOpen: boolean;
  setFormOpen: (open: boolean) => void;
  /** The bill's right-click menu (the tray item's). */
  onMenu: (e: React.MouseEvent) => void;
}) {
  const { item, tray } = bill;
  const payMode = usePayMode();
  const done = useMarkDone(item, tray, today);
  const defs = tray.fields ?? {};
  const invalid = new Set(item.invalid_fields);
  const amount = amountField(tray);
  const payee = typeof item.fields.payee === "string" && item.fields.payee !== "" ? item.fields.payee : null;
  const title = visible(item.title);
  const label = visible(tray.done?.label ?? "Done");
  const paid = label.replace(/^mark\s+/i, "");
  const open = item.date !== null && item.date <= today;
  const copyable = Object.keys(defs).filter(
    (n) => defs[n].copy && !invalid.has(n) && typeof item.fields[n] === "string" && item.fields[n] !== "",
  );
  const note = entry?.note_excerpt ?? null;
  const badges = entry?.file_state ?? "ok";
  const details = open || formOpen;
  return (
    <>
      <tr className="tn-bill" data-open={details || undefined} data-level={entry?.level} onContextMenu={onMenu}>
        <td className="tn-bill-name">
          <Link to={`/trays/${enc(tray.id)}?item=${item.id}`} title={title}>
            {title}
          </Link>
          {payee && (
            <span className="tn-sub" title={visible(payee)}>
              {visible(payee)}
            </span>
          )}
          {note && !open && <span className="tn-sub tn-note" title={visible(note)}>Note: {visible(note)}</span>}
          <ItemBadges fileState={badges} />
        </td>
        <td className="tn-bill-due">
          {item.date ? <UrgencyTag date={item.date} today={today} /> : <span className="tn-sub">No due date</span>}
        </td>
        <td className="tn-bill-amount">
          {amount && item.fields[amount] != null && item.fields[amount] !== ""
            ? visible(formatField(defs[amount]?.type, item.fields[amount]))
            : ""}
        </td>
        <td className="tn-bill-actions">
          <button type="button" className="tn-pay" aria-label={`Open Pay mode for ${title}`} onClick={() => payMode.open(item.id)}>
            Pay
          </button>
          <button
            type="button"
            className="tn-paid"
            aria-label={doneName(title, label)}
            disabled={traysUnknown || done.pending}
            onClick={() => (done.needsForm ? setFormOpen(!formOpen) : void done.run())}
          >
            {paid.charAt(0).toUpperCase() + paid.slice(1)}
          </button>
        </td>
      </tr>
      {details && (
        <tr className="tn-bill-detail" data-open>
          <td colSpan={4}>
            {copyable.length > 0 && open && (
              <div className="tn-copies">
                {copyable.map((n) => (
                  <CopyButton key={n} value={item.fields[n] as string} type={defs[n].type} label={fieldWord(n)} />
                ))}
              </div>
            )}
            {note && open && <p className="tn-note-full">Note: {visible(note)}</p>}
            {formOpen && (
              <DoneForm
                item={item}
                label={tray.done?.label ?? "Done"}
                fields={tray.done?.fields ?? {}}
                today={today}
                onClose={() => setFormOpen(false)}
              />
            )}
          </td>
        </tr>
      )}
    </>
  );
}

function PaySection({
  data,
  billTrays,
  bills,
  loaded,
  today,
  traysUnknown,
  formFor,
  setFormFor,
  frame,
  onMenu,
}: {
  data: TodayData;
  billTrays: TrayCardInfo[];
  bills: PayBill[];
  loaded: boolean;
  today: string;
  traysUnknown: boolean;
  formFor: number | null;
  setFormFor: (id: number | null) => void;
  frame: { fold: { folded: boolean; onToggle: () => void }; headerProps: React.HTMLAttributes<HTMLElement> };
  onMenu: (item: Item) => (e: React.MouseEvent) => void;
}) {
  const payMode = usePayMode();
  const first = billTrays[0];
  const name = billTrays.length === 1 ? visible(first.name) : "To pay";
  const shown = bills.slice(0, BILL_ROWS);
  const hidden = bills.length - shown.length;
  const entries = new Map(data.attention.map((a) => [a.item.id, a]));
  return (
    <TnSection
      title={name}
      titleTo={`/trays/${enc(first.id)}`}
      className="tn-pay-section"
      fold={frame.fold}
      headerProps={frame.headerProps}
      meta={loaded ? openLine(bills.length, bills.length > 0 ? sumOfBills(bills) : null) : undefined}
      actions={
        <>
          {bills.length > 0 && (
            <button type="button" className="link-button" onClick={() => payMode.open(bills[0].item.id)}>
              Pay mode
            </button>
          )}
          <Link to={`/trays/${enc(first.id)}`} aria-label={`Show all in ${name}`}>
            Show all
          </Link>
        </>
      }
    >
      {frame.fold.folded ? null : !loaded ? (
        <p className="busy">Loading…</p>
      ) : bills.length === 0 ? (
        <p className="today-empty">Nothing open.</p>
      ) : (
        <div className="tn-table-wrap">
          <table className="tn-table">
            <thead>
              <tr>
                <th scope="col">Bill</th>
                <th scope="col">Due</th>
                <th scope="col" className="tn-num">
                  Amount
                </th>
                <th scope="col">
                  <span className="visually-hidden">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {shown.map((b) => (
                <BillRow
                  key={b.item.id}
                  bill={b}
                  entry={entries.get(b.item.id)}
                  today={today}
                  traysUnknown={traysUnknown}
                  formOpen={formFor === b.item.id}
                  setFormOpen={(open) => setFormFor(open ? b.item.id : null)}
                  onMenu={onMenu(b.item)}
                />
              ))}
              {hidden > 0 && (
                <tr className="tn-more-row">
                  <td colSpan={4}>
                    <Link to={`/trays/${enc(first.id)}`}>{plural(hidden, "more bill")}</Link>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </TnSection>
  );
}

/** A tray that is not a bill tray: a compact list of its first items. The rows have a done
 * checkbox, urgency tag, note and copy buttons for what needs attention. */
function TrayList({
  info,
  data,
  today,
  traysUnknown,
  formFor,
  setFormFor,
  frame,
  onMenu,
}: {
  info: TrayCardInfo;
  data: TodayData;
  today: string;
  traysUnknown: boolean;
  formFor: number | null;
  setFormFor: (id: number | null) => void;
  frame: { fold: { folded: boolean; onToggle: () => void }; headerProps: React.HTMLAttributes<HTMLElement> };
  onMenu: (item: Item) => (e: React.MouseEvent) => void;
}) {
  const attention = data.attention.filter((a) => a.tray === info.id);
  const items: Item[] = data.open_items.find((t) => t.tray_id === info.id)?.items ?? [];
  const rows = trayRows(info, attention, items);
  const full = new Set(attention.map((a) => a.item.id));
  const name = visible(info.name);
  const open = info.count?.open ?? rows.length;
  const shown = rows.slice(0, LIST_ROWS);
  const more = Math.max(0, open - shown.length);
  return (
    <TnSection
      title={name}
      titleTo={`/trays/${enc(info.id)}`}
      fold={frame.fold}
      headerProps={frame.headerProps}
      meta={`${open} open`}
      actions={
        <Link to={`/trays/${enc(info.id)}`} aria-label={`Show all in ${name}`}>
          Show all
        </Link>
      }
    >
      {frame.fold.folded ? null : shown.length === 0 ? (
        <p className="today-empty">Nothing open.</p>
      ) : (
        <div className="tn-rows">
          {shown.map((entry) => (
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
              onMenu={onMenu(entry.item)}
            />
          ))}
          {more > 0 && (
            <p className="today-more">
              <Link to={`/trays/${enc(info.id)}`}>{plural(more, "more item", "more items")}</Link>
            </p>
          )}
        </div>
      )}
    </TnSection>
  );
}

/** The Inbox summary: how many, the oldest, which files the rules recognised, and the
 * age bar; the files found by the scan rules (one click each into their tray) and Ask AI. */
function InboxSection({
  data,
  frame,
}: {
  data: TodayData;
  frame: { fold: { folded: boolean; onToggle: () => void }; headerProps: React.HTMLAttributes<HTMLElement> };
}) {
  const { inbox_stats: stats, found } = data;
  const inbox = useInbox();
  const quick = useQuickPut();
  const ai = useAIState();
  const folded = frame.fold.folded;
  const files = (inbox.data ?? []).filter((e) => !e.record.is_dir);
  const recognised = files.filter((e) => e.tray_guess !== null).length;
  const unrecognised = files.length - recognised;
  const meta =
    stats.count === 0
      ? undefined
      : `${plural(stats.count, "file")}${stats.oldest_days !== null ? `, oldest ${waited(stats.oldest_days)}` : ""}`;
  return (
    <TnSection
      title="Inbox"
      titleTo="/inbox"
      fold={frame.fold}
      headerProps={frame.headerProps}
      meta={meta}
      actions={
        stats.count > 0 && (
          <>
            {data.reading_codes > 0 && (
              <span className="reading-codes" role="status">
                Reading filing codes…
              </span>
            )}
            {data.marked > 0 && (
              <Link to="/inbox?marked=1" title="File every inbox file with a filing code, in one batch">
                File {data.marked} marked
              </Link>
            )}
            <Link to="/inbox">Open</Link>
          </>
        )
      }
    >
      {stats.count === 0 ? (
        <p className="today-empty">The inbox is empty.</p>
      ) : (
        <>
          {files.length > 0 && (
            <>
              <div
                className="tn-recog"
                role="img"
                aria-label={`${recognised} recognised by a rule, ${unrecognised} not recognised`}
              >
                <span className="tn-recog-yes" style={{ width: `${(recognised / files.length) * 100}%` }} />
                <span className="tn-recog-no" style={{ width: `${(unrecognised / files.length) * 100}%` }} />
              </div>
              <p className="tn-legend">
                <span>{recognised} recognised by a rule</span>
                {!ai.on && unrecognised > 0 && <span>{unrecognised} not recognised</span>}
              </p>
            </>
          )}
          {stats.overdue > 0 && <p className="tn-legend tn-late">{stats.overdue} overdue</p>}
          {!folded && <AgeBar thisWeek={stats.this_week} lastWeek={stats.last_week} older={stats.older} />}
        </>
      )}
      {!folded && found.length > 0 && <FoundList found={found} quick={quick} />}
      {!folded && stats.count > 0 && ai.on && (
        <NotRecognised put={(p) => void quick.put(p)} pendingId={quick.pendingIds?.[0] ?? null} />
      )}
      {!folded && stats.count > 0 && <AIHint what="to ask about files the rules don’t recognise" />}
    </TnSection>
  );
}

/** ``today`` is the local date (kept current) unless given (tests pass a fixed one). */
export default function TodayNew({ today: fixed }: { today?: string }) {
  const clock = useLocalClock();
  const today = fixed ?? clock.today;
  const data = useToday();
  const trays = useTrays();
  const open = useOpenBills();
  const [formFor, setFormFor] = useState<number | null>(null);
  const [arranging, setArranging] = useState(false);
  // a tray item's right-click menu (the bill table's rows and the tray lists' rows)
  const itemMenu = useTrayItemMenu({ trays: trays.data?.trays ?? [], today, openItem: true });

  const cards = data.data ? trayCards(data.data, trays.data?.trays ?? []) : [];
  const trayId = (info: TrayCardInfo) => `tray:${info.id}`;
  const isBill = (info: TrayCardInfo) => isBillTray(info.def);
  const billTrayIds = new Set(cards.filter(isBill).map((c) => c.id));
  // Every tray keeps its place, empty or not (an empty one says so), so the left column is
  // there with no data too; this is why there is no Clear section.
  const billTrays = cards.filter(isBill);
  const otherTrays = cards.filter((c) => !isBill(c));
  const hiddenCards = [
    ...(billTrays.length === 0 ? ["pay"] : []),
    ...(data.data && needingAttention(data.data).length === 0 ? ["collections"] : []),
  ];
  const hidden = new Set(hiddenCards);
  const layout = useCardLayout(
    [
      ["pay", ...otherTrays.map(trayId)],
      ["inbox", "collections", "starred", "reminders"],
    ],
    {},
    hiddenCards,
  );
  const drag = useCardDrag(layout);
  const frames = useCardFrames(layout, drag);

  if (data.isPending) return <p className="busy today-loading">Loading…</p>;
  if (data.isError) {
    return (
      <p className="error" role="alert">
        Could not load Today. {visible(errorText(data.error))}
      </p>
    );
  }
  const d = data.data;
  const traysUnknown = !trays.isSuccess;
  const titles: Record<string, string> = {
    pay: billsTitle(billTrays),
    inbox: "Inbox",
    collections: "Collections to do",
    starred: "Starred",
    reminders: "Reminders",
    ...Object.fromEntries(cards.map((c) => [trayId(c), visible(c.name)])),
  };
  const render = (id: string) => {
    const frame = frames.frame(id, titles[id] ?? id);
    if (id === "pay") {
      return (
        <PaySection
          data={d}
          billTrays={billTrays}
          bills={open.bills}
          loaded={open.loaded}
          today={today}
          traysUnknown={traysUnknown}
          formFor={formFor}
          setFormFor={setFormFor}
          frame={frame}
          onMenu={itemMenu.open}
        />
      );
    }
    if (id === "inbox") return <InboxSection data={d} frame={frame} />;
    if (id === "starred") return <StarredCard frame={frame} Shell={TnSection} />;
    if (id === "collections") return <CollectionsCard data={d} frame={frame} Shell={TnSection} />;
    if (id === "reminders") return <RemindersCard data={d} today={today} frame={frame} Shell={TnSection} />;
    const info = cards.find((c) => trayId(c) === id);
    if (!info) return null;
    return (
      <TrayList
        info={info}
        data={d}
        today={today}
        traysUnknown={traysUnknown}
        formFor={formFor}
        setFormFor={setFormFor}
        frame={frame}
        onMenu={itemMenu.open}
      />
    );
  };
  const dropMark = (id: string) => {
    const at = drag.dropAt;
    return at && "id" in at && at.id === id && drag.dragging !== id ? at.side : undefined;
  };

  const counts = countsOf(d, billTrayIds);
  const tiles = tilesOf({ data: d, bills: open.bills, billsLoaded: open.loaded, trays: cards, billTrayIds, today });
  return (
    <div className="today today-new">
      <header className="tn-header">
        <div className="tn-header-text">
          <p className="tn-date">
            {visible(longDate(today))} {today.slice(0, 4)}
          </p>
          <h1>{headlineOf(counts)}</h1>
        </div>
        <button
          type="button"
          className="tn-customize"
          aria-pressed={arranging}
          title="Drag sections to rearrange, fold the ones you don't need, Reset layout puts them back"
          onClick={() => setArranging((a) => !a)}
        >
          {arranging ? "Done arranging" : "Customize"}
        </button>
        {d.inbox_stats.count > 0 && (
          <Link className="tn-start primary" to="/inbox">
            Start filing <span className="tn-start-count">{d.inbox_stats.count}</span>
          </Link>
        )}
        <p className="visually-hidden" role="status">
          {frames.announcement}
        </p>
      </header>
      {arranging && (
        <div className="tn-arrange" role="group" aria-label="Arrange the sections">
          <p>Drag a section by its heading, or use Move up and Move down. Fold the ones you don't need.</p>
          <button type="button" className="tn-reset" onClick={() => layout.reset()}>
            Reset layout
          </button>
        </div>
      )}
      <ConvertNotice data={d} />
      <Notices data={d} traysError={trays.isError ? errorText(trays.error) : null} />
      {tiles.length > 0 && (
        <div className="tn-tiles" role="group" aria-label="At a glance">
          {tiles.map((t) => (
            <Link key={t.id} to={t.to} className="tn-tile" data-tone={t.tone}>
              <span className="tn-tile-label">{t.label}</span>
              <span className="tn-tile-value" style={{ "--chars": String(t.value.length) } as CSSProperties}>
                {t.value}
              </span>
              <span className="tn-tile-note" title={t.note}>
                {t.note}
              </span>
            </Link>
          ))}
        </div>
      )}
      <div className="tn-body-grid" data-dragging={drag.dragging !== null || undefined}>
        {layout.columns.map((column, i) => (
          <div
            key={i}
            className={`today-col ${i === 0 ? "tn-left" : "tn-right"}`}
            data-drop={drag.dropAt && "column" in drag.dropAt && drag.dropAt.column === i ? "end" : undefined}
            {...(arranging ? drag.column(i) : {})}
          >
            {column
              .filter((id) => !hidden.has(id))
              .map((id) => (
                <div
                  key={id}
                  className="today-slot"
                  data-card-id={id}
                  data-kind={id.startsWith("tray:") ? "tray" : undefined}
                  data-drop={dropMark(id)}
                  data-dragged={drag.dragging === id || undefined}
                  {...(arranging ? drag.slot(id) : {})}
                >
                  <SectionContext.Provider
                    value={{
                      arranging,
                      canUp: layout.canMove(id, -1),
                      canDown: layout.canMove(id, 1),
                      up: () => frames.shift(id, titles[id] ?? id, -1),
                      down: () => frames.shift(id, titles[id] ?? id, 1),
                    }}
                  >
                    {render(id)}
                  </SectionContext.Provider>
                </div>
              ))}
          </div>
        ))}
      </div>
      {itemMenu.view}
    </div>
  );
}

/** The bill table's name: its tray's name, or "To pay" when several trays share it. */
function billsTitle(trays: TrayCardInfo[]): string {
  return trays.length === 1 ? visible(trays[0].name) : "To pay";
}
