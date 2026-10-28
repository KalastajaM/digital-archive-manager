/** Today's Starred card: the ★ Ongoing files, A–Z; a click on a name shows the file in
 * Browse (its folder, selected and previewed), and each has one-click Open and Quick
 * Look (Space on a focused row too). Its Quick Look has Trash like every Quick Look
 * (spec §8). It folds and moves like every Today card. */
import { Eye, Star } from "lucide-react";
import { useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { errorText, type Member, useBuiltin, useMark } from "../../api/client";
import { plural } from "../../format";
import { visible } from "../../text";
import { LaunchButtons, useFileLaunch } from "../FileLaunch";
import { browseHref } from "../GroupTree";
import { MarkIcons, StarGlyph } from "../MarkIcons";
import { deletionRefusal } from "../MoveTo";
import { useToast } from "../Toasts";
import { useTrash } from "../Trash";
import { type QLFile, useQuickLook } from "../useQuickLook";
import { Card } from "../ui/Card";
import { IconButton } from "../ui/IconButton";
import type { CardFrame } from "./frame";
import { baseName } from "../../paths";

const ICON = { size: 16, strokeWidth: 1.75 } as const;
// Differs from paths.ts: takes a bare name, so a "/" in the input is not stripped first.
const extOf = (name: string) => (name.includes(".") ? name.slice(name.lastIndexOf(".") + 1).toLowerCase() : null);
const nameOf = (m: Member) => (m.path ? baseName(m.path) : m.drive_id);
/** A member Quick Look and Open can act on: an indexed file that is there. */
const usable = (m: Member) => !!m.path && !m.is_dir && !m.missing && !m.quarantined;

/** Unstar from the card in one click (☆); the toast offers Undo. One request at
 * a time per row. */
function useUnstar(m: Member) {
  const mark = useMark();
  const toast = useToast();
  const inFlight = useRef(false);
  const run = async (action: "unstar" | "star") => {
    if (inFlight.current) return;
    inFlight.current = true;
    const name = nameOf(m);
    try {
      await mark.mutateAsync({ action, ids: [m.drive_id] });
      toast(
        action === "unstar"
          ? { kind: "info", text: `Unstarred ${name}`, action: { label: "Undo", run: () => void run("star") } }
          : { kind: "info", text: `Starred ${name}` },
      );
    } catch (e) {
      toast({ kind: "error", text: `Could not ${action} ${name}: ${errorText(e)}` });
    } finally {
      inFlight.current = false;
    }
  };
  return { busy: mark.isPending, unstar: () => void run("unstar") };
}

function StarredRow({ m, onLook }: { m: Member; onLook?: () => void }) {
  const launch = useFileLaunch(m.drive_id);
  const unstar = useUnstar(m);
  const name = visible(nameOf(m));
  return (
    <li>
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
          <MarkIcons marks={m.marks} omit="starred" />
        </Link>
      ) : (
        <span
          className="starred-name"
          tabIndex={onLook ? 0 : undefined}
          data-quicklook={onLook ? true : undefined}
          data-look={m.drive_id}
          title={m.path ? visible(m.path) : undefined}
        >
          {name}
          <MarkIcons marks={m.marks} omit="starred" />
        </span>
      )}
      {m.missing && <span className="hint">missing</span>}
      {!m.missing && m.quarantined && <span className="hint">in ##. To Delete</span>}
      <span className="starred-actions" role="group" aria-label={`Open ${name}`}>
        {onLook && <IconButton icon={<Eye {...ICON} />} label="Quick Look" shortcut="Space" onClick={onLook} />}
        {(usable(m) || (m.is_dir && !m.missing)) && <LaunchButtons launch={launch} only={m.is_dir ? "reveal" : undefined} />}
        <IconButton
          icon={<StarGlyph size={16} filled={false} />}
          label="Remove the star"
          disabled={unstar.busy}
          onClick={unstar.unstar}
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
          {starred.data && <Link to={`/collections/${starred.data.id}`}>★ Ongoing</Link>}
        </p>
      ) : (
        <ul className="today-list starred-list" aria-label="Starred files">
          {members.map((m) => (
            <StarredRow key={m.drive_id} m={m} onLook={lookAt(m)} />
          ))}
        </ul>
      )}
      {quickLook.view}
      {trash.view}
    </Shell>
  );
}
