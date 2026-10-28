/** Today's smaller cards and notices, shared by the Classic page and the New look's
 * sections: Collections to do, Reminders, the notices under the header, and "is this tray
 * clear". ``Shell`` is the card chrome (Classic: ``Card``; New: its section). */
import { Bell, Layers } from "lucide-react";
import { Link } from "react-router-dom";
import type { Today as TodayData } from "../../api/client";
import { clockTime, dayWord, localToday, plural, shortDate } from "../../format";
import { visible } from "../../text";
import { Banner } from "../Banner";
import { ImportantBanner } from "../ImportantBanner";
import { Card } from "../ui/Card";
import { Tag } from "../ui/Tag";
import type { CardFrame } from "./frame";
import type { TrayCardInfo } from "./TrayCard";

/** The open collections with something to do: open checklist entries, or files still
 * in the inbox. The rest are in the sidebar; Today leaves them out. */
export function needingAttention(data: TodayData) {
  return data.overview.collections.filter((c) => c.open_checks > 0 || c.in_inbox > 0);
}

/** Shown only while ``needingAttention`` has any (the page leaves the card out). */
export function CollectionsCard({ data, frame, Shell = Card }: { data: TodayData; frame: CardFrame; Shell?: typeof Card }) {
  const collections = needingAttention(data);
  return (
    <Shell
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
    </Shell>
  );
}

function lastChecked(at: string, today: string): string {
  const when = new Date(at);
  if (Number.isNaN(when.getTime())) return visible(at);
  const time = clockTime(when);
  return `${dayWord(localToday(when), today) ?? shortDate(when.getTime() / 1000)} at ${time}`;
}

export function RemindersCard({ data, today, frame, Shell = Card }: { data: TodayData; today: string; frame: CardFrame; Shell?: typeof Card }) {
  const { reminders } = data;
  const problems = Object.keys(reminders.errors).length + (reminders.skipped ? 1 : 0);
  return (
    <Shell
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
    </Shell>
  );
}

export function Notices({ data, traysError, banners = true }: { data: TodayData; traysError: string | null; /** The two Convert banners (the New look shows them as one). */ banners?: boolean }) {
  const { tray_errors, ongoing_sync_failure, unmanaged_ongoing, unmanaged_important } = data;
  return (
    <>
      {banners && unmanaged_ongoing > 0 && (
        <Banner
          label="Ongoing"
          message={`${plural(unmanaged_ongoing, "entry", "entries")} in ##. Ongoing ${unmanaged_ongoing === 1 ? "is" : "are"} not in the app yet.`}
          action={{ label: "Convert", to: "/ongoing" }}
        />
      )}
      {banners && <ImportantBanner count={unmanaged_important} />}
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

/** A tray with nothing open and nothing to show: it joins the one "Clear" card. */
export function isClear(info: TrayCardInfo, data: TodayData): boolean {
  return (
    (info.count?.open ?? 0) === 0 &&
    !data.attention.some((a) => a.tray === info.id) &&
    (data.open_items.find((t) => t.tray_id === info.id)?.items.length ?? 0) === 0
  );
}
