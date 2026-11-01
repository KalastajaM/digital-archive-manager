/** Today's Starred card: the ★ Ongoing files, A–Z; a click on a name shows the file in
 * Browse (its folder, selected and previewed), and each has one-click Open and Quick
 * Look (Space on a focused row too). Its Quick Look has Trash like every Quick Look
 * (spec §8). A right-click on a row: Show in Browse, Quick Look, Open, Show in Finder,
 * Remove the star and Move to To Delete. It folds and moves like every Today card. */
import { Eye, Star } from "lucide-react";
import { useMemo, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { errorText, type Member, useBuiltin } from "../../api/client";
import { plural } from "../../format";
import { visible } from "../../text";
import { LAUNCH_BUSY, LaunchButtons, useFileLaunch } from "../FileLaunch";
import { showInLabel } from "../../fileManager";
import type { MenuEntry } from "../ui/Menu";
import { useContextMenu } from "../ui/useContextMenu";
import { browseHref } from "../GroupTree";
import { MarkIcons, StarGlyph } from "../MarkIcons";
import { deletionRefusal } from "../MoveTo";
import { TRASH_LABEL, useTrash } from "../Trash";
import { memberName as nameOf, useUnstar } from "../useStarredFiles";
import { type QLFile, useQuickLook } from "../useQuickLook";
import { Card } from "../ui/Card";
import { IconButton } from "../ui/IconButton";
import type { CardFrame } from "./frame";
import { collectionHref } from "../../collectionHref";

const ICON = { size: 16, strokeWidth: 1.75 } as const;
// Differs from paths.ts: takes a bare name, so a "/" in the input is not stripped first.
const extOf = (name: string) => (name.includes(".") ? name.slice(name.lastIndexOf(".") + 1).toLowerCase() : null);
/** A member Quick Look and Open can act on: an indexed file that is there. */
const usable = (m: Member) => !!m.path && !m.is_dir && !m.missing && !m.quarantined;

function StarredRow({ m, onLook, onMenu }: { m: Member; onLook?: () => void; onMenu: (e: React.MouseEvent) => void }) {
  const launch = useFileLaunch(m.drive_id);
  const unstar = useUnstar();
  const name = visible(nameOf(m));
  return (
    <li className="today-row" onContextMenu={onMenu}>
      <div className="today-row-main">
        <p className="today-row-title">
          {/* a click opens Browse at the file's folder with the file selected and previewed;
              Space on it is Quick Look, as before */}
          {m.path && !m.is_dir && !m.missing ? (
            <Link
              className="starred-name"
              to={browseHref(m.path, m.drive_id)}
              data-quicklook={onLook ? true : undefined}
              data-look={m.drive_id}
              title={`Show ${visible(m.path)} in Browse`}
            >
              {name}
            </Link>
          ) : (
            <span
              className="starred-name"
              tabIndex={onLook ? 0 : undefined}
              data-quicklook={onLook ? true : undefined}
              data-look={m.drive_id}
              title={m.path ? visible(m.path) : name}
            >
              {name}
            </span>
          )}
          <MarkIcons marks={m.marks} omit="starred" />
        </p>
        {m.missing && <p className="today-row-sub">missing</p>}
        {!m.missing && m.quarantined && <p className="today-row-sub">in ##. To Delete</p>}
      </div>
      <span className="starred-actions" role="group" aria-label={`Open ${name}`}>
        {onLook && <IconButton icon={<Eye {...ICON} />} label="Quick Look" shortcut="Space" onClick={onLook} />}
        {(usable(m) || (m.is_dir && !m.missing)) && <LaunchButtons launch={launch} only={m.is_dir ? "reveal" : undefined} />}
        <IconButton
          icon={<StarGlyph size={16} filled={false} />}
          label="Remove the star"
          disabled={unstar.busy}
          onClick={() => unstar.unstar(m)}
        />
      </span>
    </li>
  );
}

export function StarredCard({ frame, Shell = Card }: { frame: CardFrame; Shell?: typeof Card }) {
  const starred = useBuiltin("starred");
  const members = useMemo(
    () =>
      [...(starred.data?.members ?? [])].sort((a, b) =>
        nameOf(a).localeCompare(nameOf(b), undefined, { sensitivity: "base", numeric: true }),
      ),
    [starred.data],
  );
  const looks = useMemo(() => members.filter(usable), [members]);
  const files = useMemo<QLFile[]>(
    () =>
      looks.map((m) => ({
        drive_id: m.drive_id,
        name: null,
        path: m.path!,
        ext: extOf(nameOf(m)),
        is_link: m.is_link,
        marks: m.marks,
      })),
    [looks],
  );
  const [at, setAt] = useState(0);
  const byButton = useRef(false); // a row's Quick Look button, not Space
  // Trash from Quick Look (the bin, ⌘⌫): the shown file; the card's list reloads
  // with the marks (a trashed file stays starred, shown "in ##. To Delete").
  const trash = useTrash();
  const quickLook = useQuickLook(files, at, setAt, {
    trashRefusal: (file) => deletionRefusal(file.path, file.marks),
    trashBusy: trash.busy,
    onTrash: (file, ui) =>
      trash.start([file.drive_id], {
        links: !!file.is_link,
        onConfirming: ui.close,
        onRefused: ui.report,
        onCancelled: ui.reopen,
      }),
    canOpen: () => {
      if (trash.running()) return false;
      if (byButton.current) return true;
      // Space opens it on a focused row of this card only
      const el = document.activeElement;
      const id = el instanceof HTMLElement && el.closest(".starred-list") ? el.dataset.look : undefined;
      const i = id === undefined ? -1 : looks.findIndex((m) => m.drive_id === id);
      if (i < 0) return false;
      setAt(i);
      return true;
    },
  });
  const lookAt = (m: Member) => {
    const i = looks.indexOf(m);
    if (i < 0) return undefined;
    return () => {
      setAt(i);
      byButton.current = true;
      try {
        quickLook.open();
      } finally {
        byButton.current = false;
      }
    };
  };
  // a row's right-click menu: the row's buttons and link, plus Move to To Delete
  const menu = useContextMenu<Member>();
  const navigate = useNavigate();
  const launch = useFileLaunch("");
  const unstar = useUnstar();
  const entriesFor = (m: Member): MenuEntry[] => {
    const look = lookAt(m);
    const there = !m.missing && (usable(m) || m.is_dir);
    const launchWhy = m.connected === false ? "Not connected" : launch.busy ? LAUNCH_BUSY : null;
    const launchOff = { disabled: !!launchWhy, reason: launchWhy ?? undefined };
    const trashWhy = m.path ? deletionRefusal(m.path, m.marks) : "The file is not in the index";
    return [
      ...(m.path && !m.is_dir && !m.missing ? [{ label: "Show in Browse", onSelect: () => navigate(browseHref(m.path!, m.drive_id)) }] : []),
      ...(look ? [{ label: "Quick Look", onSelect: look }] : []),
      ...(usable(m) ? [{ label: "Open", onSelect: () => void launch.run("open", m.drive_id), ...launchOff }] : []),
      ...(there ? [{ label: showInLabel(), onSelect: () => void launch.run("reveal", m.drive_id), ...launchOff }] : []),
      "separator",
      { label: "Remove the star", onSelect: () => unstar.unstar(m), disabled: unstar.busy },
      ...(!m.missing && !m.quarantined
        ? [
            {
              label: TRASH_LABEL,
              onSelect: () => trash.start([m.drive_id], { links: m.is_link }),
              disabled: !!trashWhy || trash.busy,
              reason: trashWhy ?? undefined,
            },
          ]
        : []),
    ];
  };
  const n = members.length;
  return (
    <Shell
      title="Starred"
      icon={<Star />}
      className="today-card today-card-compact"
      fold={frame.fold}
      headerProps={frame.headerProps}
    >
      {starred.isError ? (
        <p className="error">Could not load the starred files. {visible(errorText(starred.error))}</p>
      ) : frame.fold.folded ? (
        <p className="today-sub">{n === 0 ? "No starred files." : plural(n, "starred file")}</p>
      ) : n === 0 ? (
        <p className="today-empty">
          No starred files. Click ★ on a file to keep it here for quick access.{" "}
          {starred.data && <Link to={collectionHref({ id: starred.data.id, name: starred.data.name, kind: "starred" })}>★ Ongoing</Link>}
        </p>
      ) : (
        <ul className="tn-rows starred-list" aria-label="Starred files">
          {members.map((m) => (
            <StarredRow key={m.drive_id} m={m} onLook={lookAt(m)} onMenu={(e) => menu.open(m, e)} />
          ))}
        </ul>
      )}
      {quickLook.view}
      {trash.view}
      {menu.view((m) => ({ label: `Actions for ${visible(nameOf(m))}`, entries: entriesFor(m) }))}
    </Shell>
  );
}
