/** Files whose content changed since dam last read them: Today's Changed files card (the
 * newest few; Show all finds them with ``is:changed``) and the line in a file's panel.
 * A click on a name shows the file in Browse; Mark as seen ends the notice, with Undo in
 * the toast. Nothing here touches the file. */
import { Check } from "lucide-react";
import { Link, useNavigate } from "react-router-dom";
import { type ContentChange, errorText, useFileDetail, useSeeContentChanges, useUnseeContentChanges } from "../../api/client";
import { showInLabel } from "../../fileManager";
import { formatSize, plural, shortDate } from "../../format";
import { baseName } from "../../paths";
import { visible } from "../../text";
import { LAUNCH_BUSY, LaunchButtons, useFileLaunch } from "../FileLaunch";
import { browseHref } from "../GroupTree";
import { useToast } from "../Toasts";
import { IconButton } from "../ui/IconButton";
import type { MenuEntry } from "../ui/Menu";
import { useContextMenu } from "../ui/useContextMenu";
import type { CardFrame } from "./frame";
import { TnSection } from "./TnSection";

const ICON = { size: 16, strokeWidth: 1.75 } as const;
const nameOf = (c: ContentChange) => c.name ?? baseName(c.path);

/** "30 Oct, was 1 KB, now 2 KB", or "30 Oct, same size". */
export function changeLine(c: ContentChange): string {
  const when = c.mtime !== null ? `${shortDate(c.mtime)}, ` : "";
  if (c.was_size === null || c.size === null) return when.slice(0, -2);
  if (c.was_size === c.size) return `${when}same size`;
  return `${when}was ${formatSize(c.was_size)}, now ${formatSize(c.size)}`;
}

/** Mark notices as seen (``ids`` null: every open one); the toast offers Undo. */
function useMarkSeen() {
  const see = useSeeContentChanges();
  const unsee = useUnseeContentChanges();
  const toast = useToast();
  const run = async (ids: string[] | null, label: string) => {
    try {
      const done = await see.mutateAsync(ids);
      toast({
        kind: "info",
        text: `Marked ${label} as seen`,
        action: { label: "Undo", run: () => void unsee.mutate(done.drive_ids) },
      });
    } catch (e) {
      toast({ kind: "error", text: `Could not mark ${label} as seen: ${errorText(e)}` });
    }
  };
  return { busy: see.isPending, run };
}

function ChangedRow({ change, onMenu }: { change: ContentChange; onMenu: (e: React.MouseEvent) => void }) {
  const launch = useFileLaunch(change.drive_id);
  const seen = useMarkSeen();
  const name = visible(nameOf(change));
  return (
    <li className="today-row" onContextMenu={onMenu}>
      <div className="today-row-main">
        <p className="today-row-title">
          <Link className="starred-name" to={browseHref(change.path, change.drive_id)} title={`Show ${visible(change.path)} in Browse`}>
            {name}
          </Link>
        </p>
        <p className="today-row-sub">{changeLine(change)}</p>
      </div>
      <span className="starred-actions" role="group" aria-label={`Actions for ${name}`}>
        <LaunchButtons launch={launch} />
        <IconButton
          icon={<Check {...ICON} />}
          label="Mark as seen"
          disabled={seen.busy}
          onClick={() => void seen.run([change.drive_id], name)}
        />
      </span>
    </li>
  );
}

export function ChangedFilesCard({
  rows,
  count,
  frame,
}: {
  rows: ContentChange[];
  count: number;
  frame: CardFrame;
}) {
  const seen = useMarkSeen();
  const menu = useContextMenu<ContentChange>();
  const navigate = useNavigate();
  const launch = useFileLaunch("");
  const entriesFor = (c: ContentChange): MenuEntry[] => {
    const why = launch.busy ? LAUNCH_BUSY : undefined;
    return [
      { label: "Show in Browse", onSelect: () => navigate(browseHref(c.path, c.drive_id)) },
      { label: "Open", onSelect: () => void launch.run("open", c.drive_id), disabled: !!why, reason: why },
      { label: showInLabel(), onSelect: () => void launch.run("reveal", c.drive_id), disabled: !!why, reason: why },
      "separator",
      { label: "Mark as seen", onSelect: () => void seen.run([c.drive_id], visible(nameOf(c))), disabled: seen.busy },
    ];
  };
  const more = count - rows.length;
  const all = `/browse?${new URLSearchParams({ q: "is:changed" })}`;
  return (
    <TnSection
      title="Changed files"
      titleTo={all}
      fold={frame.fold}
      headerProps={frame.headerProps}
      meta={plural(count, "file")}
      actions={
        <>
          <button
            type="button"
            className="link-button"
            disabled={seen.busy}
            onClick={() => void seen.run(null, plural(count, "changed file"))}
          >
            Mark all seen
          </button>
          <Link to={all} aria-label="Show all changed files">
            Show all
          </Link>
        </>
      }
    >
      {!frame.fold.folded && (
        <ul className="tn-rows starred-list" aria-label="Changed files">
          {rows.map((c) => (
            <ChangedRow key={c.drive_id} change={c} onMenu={(e) => menu.open(c, e)} />
          ))}
        </ul>
      )}
      {!frame.fold.folded && more > 0 && (
        <p className="today-more">
          <Link to={all}>{plural(more, "more file")}</Link>
        </p>
      )}
      {menu.view((c) => ({ label: `Actions for ${visible(nameOf(c))}`, entries: entriesFor(c) }))}
    </TnSection>
  );
}

/** The line under a file's name in its panel, while the notice is open. */
export function ChangedNotice({ driveId }: { driveId: string }) {
  const detail = useFileDetail(driveId);
  const seen = useMarkSeen();
  const change = detail.data?.content_change;
  if (!change) return null;
  return (
    <p className="hint content-changed" role="status">
      <span>Content changed: {changeLine(change)}.</span>{" "}
      <button type="button" className="link-button" disabled={seen.busy} onClick={() => void seen.run([driveId], "this change")}>
        Mark as seen
      </button>
    </p>
  );
}
