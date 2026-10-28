/** Today, the front page: a greeting, then a card per tray (what needs attention first,
 * with urgency tags), the inbox's age and what its scans found, and the extras. Each
 * card folds to its headline and can be dragged by its header to another place (or
 * moved with ⌥↑ / ⌥↓ on its header); see ``useCardLayout``. */
import { useState } from "react";
import { errorText, type Today as TodayData, useToday, useTrays } from "../api/client";
import { useStyle } from "../appearance";
import { useLocalClock } from "../components/RelativeDate";
import { balanceColumns } from "../components/today/balance";
import { ClearCard } from "../components/today/ClearCard";
import { FOUND_SHOWN, InboxCard } from "../components/today/InboxCard";
import { CollectionsCard, isClear, needingAttention, Notices, RemindersCard } from "../components/today/pieces";
import { SearchCard } from "../components/today/SearchCard";
import { StarredCard } from "../components/today/StarredCard";
import { type TrayCardInfo, TrayCard, trayCards } from "../components/today/TrayCard";
import { useCardDrag } from "../components/today/useCardDrag";
import { useCardFrames } from "../components/today/useCardFrames";
import { useCardLayout } from "../components/useCardLayout";
import { longDate, plural } from "../format";
import { visible } from "../text";
import TodayNew from "./TodayNew";

/** "Good morning" (5–11), "Good afternoon" (12–17), "Good evening" otherwise. */
export function greeting(hour: number): string {
  if (hour >= 5 && hour < 12) return "Good morning";
  if (hour >= 12 && hour < 18) return "Good afternoon";
  return "Good evening";
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

/** A card's rough height, to deal the cards out between the columns. */
function weigh(info: TrayCardInfo, data: TodayData): number {
  const attention = data.attention.filter((a) => a.tray === info.id).length;
  const items = data.open_items.find((t) => t.tray_id === info.id)?.items.length ?? 0;
  return 2 + attention * 2.5 + Math.max(0, items - attention) * 1.2;
}

/** ``today`` is the local date (kept current) unless given (tests pass a fixed one). */
export default function Today({ today }: { today?: string }) {
  const [look] = useStyle();
  return look === "new" ? <TodayNew today={today} /> : <TodayClassic today={today} />;
}

function TodayClassic({ today: fixed }: { today?: string }) {
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
  // The other cards are dealt out by their heights; Search tops the second column, so it
  // sits by the Inbox without moving any of them.
  const dealt = balanceColumns([
      { id: "inbox", weight: 4 + Math.min(stats?.found.length ?? 0, FOUND_SHOWN) * 1.2 },
      ...busyTrays.map((c) => ({ id: trayId(c), weight: stats ? weigh(c, stats) : 2 })),
      { id: "starred", weight: 3 },
      { id: "collections", weight: hidden.has("collections") ? 0 : 1 + (stats ? needingAttention(stats).length : 0) },
      { id: "clear", weight: hidden.has("clear") ? 0 : 1.5 },
      { id: "reminders", weight: 1.5 },
      ...clearTrays.map((c) => ({ id: trayId(c), weight: 0 })),
    ]);
  dealt[1].unshift("search");
  const layout = useCardLayout(
    dealt,
    { inbox: (data.data?.found.length ?? 0) > FOUND_SHOWN },
    hiddenCards,
  );
  const drag = useCardDrag(layout);
  const { frame, announcement } = useCardFrames(layout, drag);

  if (data.isPending) return <p className="busy today-loading">Loading…</p>;
  if (data.isError) {
    return (
      <p className="error" role="alert">
        Could not load Today. {visible(errorText(data.error))}
      </p>
    );
  }
  const { attention } = data.data;

  const render = (id: string) => {
    if (id === "inbox") return <InboxCard data={data.data} frame={frame(id, "Inbox")} />;
    if (id === "search") return <SearchCard frame={frame(id, "Search")} />;
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
        <p className="today-date">{visible(longDate(today))}</p>
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
