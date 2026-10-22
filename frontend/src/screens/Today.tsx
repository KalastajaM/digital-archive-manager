/** Today, the front page: a greeting, then a card per tray (what needs attention first,
 * with urgency tags), the inbox's age and what its scans found, and the extras. Each
 * card folds to its headline and can be dragged by its header to another place (or
 * moved with ⌥↑ / ⌥↓ on its header); see ``useCardLayout``. */
import { Bell, Layers } from "lucide-react";
import { type DragEvent, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { errorText, type Today as TodayData, useToday, useTrays } from "../api/client";
import { useLocalClock } from "../components/RelativeDate";
import type { CardFrame } from "../components/today/frame";
import { balanceColumns } from "../components/today/balance";
import { ClearCard } from "../components/today/ClearCard";
import { FOUND_SHOWN, InboxCard } from "../components/today/InboxCard";
import { StarredCard } from "../components/today/StarredCard";
import { Banner } from "../components/Banner";
import { ImportantBanner } from "../components/ImportantBanner";
import { DAY_MS } from "../components/today/time";
import { type TrayCardInfo, TrayCard, trayCards } from "../components/today/TrayCard";
import { Card } from "../components/ui/Card";
import { Tag } from "../components/ui/Tag";
import { CARD_DRAG_TYPE, type CardLayout, type Place, useCardLayout } from "../components/useCardLayout";
import { DRAG_TYPE } from "../dnd";
import { localToday, plural, shortDate } from "../format";
import { visible } from "../text";

/** "Good morning" (5–11), "Good afternoon" (12–17), "Good evening" otherwise. */
export function greeting(hour: number): string {
  if (hour >= 5 && hour < 12) return "Good morning";
  if (hour >= 12 && hour < 18) return "Good afternoon";
  return "Good evening";
}

const LONG_DATE = new Intl.DateTimeFormat("en-GB", {
  weekday: "long",
  day: "numeric",
  month: "long",
  timeZone: "UTC",
});

/** "2026-10-20" → "Tuesday 20 October". */
export function longDate(iso: string): string {
  const at = /^\d{4}-\d{2}-\d{2}$/.test(iso) ? Date.parse(`${iso}T00:00:00Z`) : Number.NaN;
  return Number.isNaN(at) ? visible(iso) : LONG_DATE.format(new Date(at));
}

/** The open collections with something to do: open checklist entries, or files still
 * in the inbox. The rest are in the sidebar; Today leaves them out. */
function needingAttention(data: TodayData) {
  return data.overview.collections.filter((c) => c.open_checks > 0 || c.in_inbox > 0);
}

/** Shown only while ``needingAttention`` has any (the page leaves the card out). */
function CollectionsCard({ data, frame }: { data: TodayData; frame: CardFrame }) {
  const collections = needingAttention(data);
  return (
    <Card
      title="Collections to do"
      icon={<Layers />}
      className="today-card today-card-compact"
      fold={frame.fold}
      headerProps={frame.headerProps}
      actions={
        <Link className="card-link" to="/collections" aria-label="Show all collections">
          Show all
        </Link>
      }
    >
      {frame.fold.folded ? (
        <p className="today-sub">{plural(collections.length, "collection")}</p>
      ) : (
        <ul className="today-list">
          {collections.map((c) => (
            <li key={c.id}>
              <Link to={`/collections/${c.id}`}>{visible(c.name)}</Link>
              <span className="today-row-sub">
                {plural(c.files, "file")}
                {c.in_inbox > 0 && ` · ${plural(c.in_inbox, "file")} in the inbox`}
                {c.open_checks > 0 && ` · ${plural(c.open_checks, "checklist item")} open`}
                {c.note_excerpt && (
                  <>
                    {" · "}
                    <i>{visible(c.note_excerpt)}</i>
                  </>
                )}
              </span>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function lastChecked(at: string, today: string): string {
  const when = new Date(at);
  if (Number.isNaN(when.getTime())) return visible(at);
  const pad = (n: number) => String(n).padStart(2, "0");
  const time = `${pad(when.getHours())}:${pad(when.getMinutes())}`;
  const day = localToday(when);
  const yesterday = localToday(new Date(Date.parse(`${today}T12:00:00`) - DAY_MS));
  if (day === today) return `today at ${time}`;
  if (day === yesterday) return `yesterday at ${time}`;
  return `${shortDate(when.getTime() / 1000)} at ${time}`;
}

function RemindersCard({ data, today, frame }: { data: TodayData; today: string; frame: CardFrame }) {
  const { reminders } = data;
  const problems = Object.keys(reminders.errors).length + (reminders.skipped ? 1 : 0);
  return (
    <Card
      title="Reminders"
      icon={<Bell />}
      className="today-card today-card-compact"
      fold={frame.fold}
      headerProps={frame.headerProps}
    >
      <p className="today-sub">
        {reminders.last_run ? `Last checked ${lastChecked(reminders.last_run, today)}` : "Not checked yet."}
        {frame.fold.folded && problems > 0 && (
          <>
            {" "}
            <Tag tone="orange">{plural(problems, "problem")}</Tag>
          </>
        )}
      </p>
      {!frame.fold.folded &&
        Object.entries(reminders.errors).map(([channel, message]) => (
          <p key={channel} className="notice">
            {visible(channel)}: {visible(message)}
          </p>
        ))}
      {!frame.fold.folded && reminders.skipped && <p className="notice">Check skipped: {visible(reminders.skipped)}</p>}
    </Card>
  );
}

function Notices({ data, traysError }: { data: TodayData; traysError: string | null }) {
  const { tray_errors, ongoing_sync_failure, unmanaged_ongoing, unmanaged_important } = data;
  return (
    <>
      {unmanaged_ongoing > 0 && (
        <Banner
          label="Ongoing"
          message={`${plural(unmanaged_ongoing, "entry", "entries")} in ##. Ongoing ${unmanaged_ongoing === 1 ? "is" : "are"} not in the app yet.`}
          action={{ label: "Convert", to: "/ongoing" }}
        />
      )}
      <ImportantBanner count={unmanaged_important} />
      {ongoing_sync_failure && (
        <p className="notice">Ongoing sync is failing: {visible(ongoing_sync_failure)}</p>
      )}
      {traysError && <p className="notice">Tray settings could not be loaded: {visible(traysError)}</p>}
      {tray_errors.map((e) => (
        <p key={e.file} className="hint">
          Tray file skipped — {visible(e.file)}: {visible(e.message)}
        </p>
      ))}
    </>
  );
}

/** What is waiting, for the header's hero line. ``dueNoun``: "bill" when every item
 * due soon is in a money tray, else "item". ``overdue`` counts tray items and overdue
 * bills still in the inbox (not tray items yet, so not in ``attention``). */
export type Waiting = { toFile: number; due: number; dueNoun: "bill" | "item"; overdue: number; undated: number };

/** "6 to file · 1 bill due soon · nothing overdue", or "All clear" when nothing waits. */
export function heroLine(w: Waiting): string {
  const parts: string[] = [];
  if (w.toFile > 0) parts.push(`${w.toFile} to file`);
  if (w.due > 0) parts.push(`${plural(w.due, w.dueNoun)} due soon`);
  if (w.undated > 0) parts.push(`${plural(w.undated, "item")} without a due date`);
  if (w.overdue > 0) parts.push(`${w.overdue} overdue`);
  else if (parts.length > 0) parts.push("nothing overdue");
  return parts.length === 0 ? "All clear" : parts.join(" · ");
}

/** What Today's data says is waiting (see ``heroLine``). */
export function waitingOf(data: TodayData, moneyTrays: Set<string>): Waiting {
  const soon = data.attention.filter((a) => a.level === "today" || a.level === "soon");
  return {
    toFile: data.inbox_stats.count,
    due: soon.length,
    dueNoun: soon.length > 0 && soon.every((a) => moneyTrays.has(a.tray)) ? "bill" : "item",
    overdue: data.attention.filter((a) => a.level === "overdue").length + data.inbox_stats.overdue,
    undated: data.attention.filter((a) => a.level === "undated").length,
  };
}

/** A tray with nothing open and nothing to show: it joins the one "Clear" card. */
function isClear(info: TrayCardInfo, data: TodayData): boolean {
  return (
    (info.count?.open ?? 0) === 0 &&
    !data.attention.some((a) => a.tray === info.id) &&
    (data.open_items.find((t) => t.tray_id === info.id)?.items.length ?? 0) === 0
  );
}

/** A card's rough height, to deal the cards out between the columns. */
function weigh(info: TrayCardInfo, data: TodayData): number {
  const attention = data.attention.filter((a) => a.tray === info.id).length;
  const items = data.open_items.find((t) => t.tray_id === info.id)?.items.length ?? 0;
  return 2 + attention * 2.5 + Math.max(0, items - attention) * 1.2;
}

/** Whether a drag is a Today card: it carries ``CARD_DRAG_TYPE`` and no files (a file
 * drag is never taken as a card, even with a card type beside its files). */
function isCardDrag(e: DragEvent): boolean {
  const types = Array.from(e.dataTransfer?.types ?? []);
  return types.includes(CARD_DRAG_TYPE) && !types.includes(DRAG_TYPE);
}

type DropAt = { id: string; side: "before" | "after" } | { column: number };

/** Drag and drop of the cards by their headers, with where a drop would land. */
function useCardDrag(layout: CardLayout) {
  const [dragging, setDragging] = useState<string | null>(null);
  const [dropAt, setDropAt] = useState<DropAt | null>(null);
  const end = () => {
    setDragging(null);
    setDropAt(null);
  };
  const over = (e: DragEvent, at: DropAt) => {
    if (!isCardDrag(e)) return;
    e.preventDefault();
    e.stopPropagation();
    e.dataTransfer.dropEffect = "move";
    setDropAt((now) => (JSON.stringify(now) === JSON.stringify(at) ? now : at));
  };
  const drop = (e: DragEvent, where: Place) => {
    if (!isCardDrag(e)) return;
    e.preventDefault();
    e.stopPropagation();
    const id = e.dataTransfer.getData(CARD_DRAG_TYPE);
    if (id) layout.place(id, where);
    end();
  };
  /** Above or below the middle of the card under the pointer. */
  const side = (e: DragEvent): "before" | "after" => {
    const box = e.currentTarget.getBoundingClientRect();
    return box.height > 0 && e.clientY > box.top + box.height / 2 ? "after" : "before";
  };
  return {
    dragging,
    dropAt,
    header: (id: string) => ({
      draggable: true,
      onDragStart: (e: DragEvent) => {
        // A link or button inside the header keeps its own drag (or none).
        if (e.target !== e.currentTarget) return;
        e.dataTransfer.setData(CARD_DRAG_TYPE, id);
        e.dataTransfer.effectAllowed = "move";
        setDragging(id);
      },
      onDragEnd: end,
    }),
    slot: (id: string) => ({
      onDragOver: (e: DragEvent) => over(e, { id, side: side(e) }),
      onDrop: (e: DragEvent) => {
        const at = side(e);
        drop(e, at === "before" ? { before: id } : { after: id });
      },
    }),
    // Over the column itself (a gap between cards, or under the last one): before the
    // first card whose middle is below the pointer, else at the end of the column.
    column: (column: number) => {
      const gap = (e: DragEvent): string | null => {
        const slots = e.currentTarget.querySelectorAll<HTMLElement>(":scope > .today-slot");
        for (const slot of slots) {
          const box = slot.getBoundingClientRect();
          if (box.height > 0 && e.clientY < box.top + box.height / 2) return slot.dataset.cardId ?? null;
        }
        return null;
      };
      return {
        onDragOver: (e: DragEvent) => {
          const id = gap(e);
          over(e, id === null ? { column } : { id, side: "before" });
        },
        onDrop: (e: DragEvent) => {
          const id = gap(e);
          drop(e, id === null ? { column } : { before: id });
        },
      };
    },
  };
}

/** ``today`` is the local date (kept current) unless given (tests pass a fixed one). */
export default function Today({ today: fixed }: { today?: string }) {
  const clock = useLocalClock();
  const today = fixed ?? clock.today;
  const data = useToday();
  const trays = useTrays();
  const [formFor, setFormFor] = useState<number | null>(null);

  const cards = data.data ? trayCards(data.data, trays.data?.trays ?? []) : [];
  const trayId = (info: TrayCardInfo) => `tray:${info.id}`;
  // Trays with nothing open are folded into one "Clear" card; cards with nothing to
  // show keep their place in the layout but take no slot.
  const clearTrays = data.data ? cards.filter((c) => isClear(c, data.data)) : [];
  const busyTrays = cards.filter((c) => !clearTrays.includes(c));
  const hiddenCards = [
    ...(data.data && needingAttention(data.data).length === 0 ? ["collections"] : []),
    ...(clearTrays.length === 0 ? ["clear"] : []),
    ...clearTrays.map(trayId),
  ];
  const hidden = new Set(hiddenCards);
  const stats = data.data;
  const layout = useCardLayout(
    balanceColumns([
      { id: "inbox", weight: 4 + Math.min(stats?.found.length ?? 0, FOUND_SHOWN) * 1.2 },
      ...busyTrays.map((c) => ({ id: trayId(c), weight: stats ? weigh(c, stats) : 2 })),
      { id: "starred", weight: 3 },
      { id: "collections", weight: hidden.has("collections") ? 0 : 1 + (stats ? needingAttention(stats).length : 0) },
      { id: "clear", weight: hidden.has("clear") ? 0 : 1.5 },
      { id: "reminders", weight: 1.5 },
      ...clearTrays.map((c) => ({ id: trayId(c), weight: 0 })),
    ]),
    { inbox: (data.data?.found.length ?? 0) > FOUND_SHOWN },
    hiddenCards,
  );
  const drag = useCardDrag(layout);
  // After a keyboard move the card may land in another column (a new element): the
  // focus goes back to its header button so the keys can move it on.
  const refocus = useRef<string | null>(null);
  const [announcement, setAnnouncement] = useState("");
  useEffect(() => {
    const id = refocus.current;
    if (id === null) return;
    refocus.current = null;
    const slot = [...document.querySelectorAll<HTMLElement>(".today-slot")].find((el) => el.dataset.cardId === id);
    slot?.querySelector<HTMLButtonElement>(".card-header button")?.focus();
  }, [layout.columns]);

  if (data.isPending) return <p className="busy today-loading">Loading…</p>;
  if (data.isError) {
    return (
      <p className="error" role="alert">
        Could not load Today. {visible(errorText(data.error))}
      </p>
    );
  }
  const { attention } = data.data;

  const frame = (id: string, title: string): CardFrame => ({
    fold: { folded: layout.collapsed(id), onToggle: () => layout.toggle(id) },
    headerProps: {
      ...drag.header(id),
      // Option-Up / Option-Down with the focus in a card's header moves the card on.
      onKeyDown: (e) => {
        if (!e.altKey || e.metaKey || e.ctrlKey || (e.key !== "ArrowUp" && e.key !== "ArrowDown")) return;
        const by = e.key === "ArrowUp" ? -1 : 1;
        e.preventDefault();
        if (!layout.canMove(id, by)) return;
        refocus.current = id;
        layout.move(id, by);
        setAnnouncement(`${title} moved ${by < 0 ? "up" : "down"}`);
      },
    },
  });
  const render = (id: string) => {
    if (id === "inbox") return <InboxCard data={data.data} frame={frame(id, "Inbox")} />;
    if (id === "starred") return <StarredCard frame={frame(id, "Starred")} />;
    if (id === "collections") return <CollectionsCard data={data.data} frame={frame(id, "Collections to do")} />;
    if (id === "reminders") return <RemindersCard data={data.data} today={today} frame={frame(id, "Reminders")} />;
    if (id === "clear") {
      return <ClearCard trays={clearTrays.map((c) => ({ id: c.id, name: c.name }))} frame={frame(id, "Clear")} />;
    }
    const info = cards.find((c) => trayId(c) === id);
    if (!info) return null;
    return (
      <TrayCard
        info={info}
        attention={attention.filter((a) => a.tray === info.id)}
        items={data.data.open_items.find((t) => t.tray_id === info.id)?.items ?? []}
        today={today}
        traysUnknown={!trays.isSuccess}
        formFor={formFor}
        setFormFor={setFormFor}
        frame={frame(id, visible(info.name))}
      />
    );
  };
  const dropMark = (id: string) => {
    const at = drag.dropAt;
    return at && "id" in at && at.id === id && drag.dragging !== id ? at.side : undefined;
  };
  const moneyTrays = new Set(cards.filter((c) => c.kind === "money").map((c) => c.id));
  const waiting = waitingOf(data.data, moneyTrays);
  return (
    <div className="today">
      <header className="today-header">
        <h1>{greeting(clock.hour)}</h1>
        <p className="today-hero">{heroLine(waiting)}</p>
        <p className="today-date">{longDate(today)}</p>
        <button type="button" className="link-button today-reset" onClick={() => layout.reset()}>
          Reset layout
        </button>
        <p className="visually-hidden" role="status">
          {announcement}
        </p>
      </header>
      <Notices data={data.data} traysError={trays.isError ? errorText(trays.error) : null} />
      <div className="today-grid" data-dragging={drag.dragging !== null || undefined}>
        {layout.columns.map((column, i) => (
          <div
            key={i}
            className="today-col"
            data-drop={drag.dropAt && "column" in drag.dropAt && drag.dropAt.column === i ? "end" : undefined}
            {...drag.column(i)}
          >
            {column.filter((id) => !hidden.has(id)).map((id) => (
              <div
                key={id}
                className="today-slot"
                data-card-id={id}
                data-drop={dropMark(id)}
                data-dragged={drag.dragging === id || undefined}
                {...drag.slot(id)}
              >
                {render(id)}
              </div>
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}
