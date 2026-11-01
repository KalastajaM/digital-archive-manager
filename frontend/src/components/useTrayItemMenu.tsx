/** A tray item's right-click menu: Mark done (the tray's own label; Reopen for a done
 * item; a Renew item has Renewed… first, then its done label), Move to each other tray, Remove from tray…, then Open item and the item's file
 * (Open file, Show in folder, Show in Finder), and Remove the star for a starred file. One place for the Trays list and Today's
 * tray rows and bill table, so all say and do the same. Done and Move say what happened in
 * a toast with Undo; Remove asks first (it has no Undo). */
import { type MouseEvent, type ReactNode, useState } from "react";
import { useNavigate } from "react-router-dom";
import { errorText, type Item, type TrayDef, type TrayItem, useMoveItem, useUndoMoveItem } from "../api/client";
import { showInLabel } from "../fileManager";
import { visible } from "../text";
import { LAUNCH_BUSY, useFileLaunch } from "./FileLaunch";
import { browseHref } from "./GroupTree";
import { RemoveItemSheet } from "./RemoveItemSheet";
import { memberName, useStarredOf, useUnstar } from "./useStarredFiles";
import { useToast } from "./Toasts";
import type { MenuEntry } from "./ui/Menu";
import { useContextMenu } from "./ui/useContextMenu";
import { doneOf, markLabel, renewHref, renewLabel, useDoneFlow } from "./useMarkDone";

type AnyItem = Item | TrayItem;
const itemHref = (item: AnyItem) => `/trays/${encodeURIComponent(item.tray_id)}?item=${item.id}`;

/** Move an item to another tray, with Undo in the toast. ``moved`` / ``back``: after the
 * move and after its undo (the item's page follows it there). */
export function useMoveItemFlow(after: { moved?: (item: AnyItem, to: TrayDef) => void; back?: (item: AnyItem, from: string) => void } = {}) {
  const moveItem = useMoveItem();
  const undoMove = useUndoMoveItem();
  const toast = useToast();
  const move = async (item: AnyItem, target: TrayDef) => {
    const from = item.tray_id;
    try {
      const moved = await moveItem.mutateAsync({ id: item.id, tray: target.id });
      after.moved?.(item, target);
      toast({
        kind: "info",
        text: `Moved to ${visible(target.name)}: ${visible(moved.title)}`,
        action: {
          label: "Undo",
          run: () =>
            void undoMove.mutateAsync(item.id).then(
              () => after.back?.(item, from),
              (e) => toast({ kind: "error", text: `Could not move it back: ${visible(errorText(e))}` }),
            ),
        },
      });
    } catch (e) {
      toast({ kind: "error", text: `Could not move ${visible(item.title)}: ${visible(errorText(e))}` });
    }
  };
  return { move, pending: moveItem.isPending };
}

/** Why the item's file cannot be opened or shown (null: it can). */
function fileWhy(first: TrayItem["first_file"] | null): string | null {
  if (!first) return null;
  if (first.state === "missing") return "The file is missing";
  if (first.connected === false) return "Not connected";
  return null;
}

/** ``trays``: every tray (Move to offers the others; empty while they load). ``openItem``:
 * the menu has Open item (a list whose click does not open the item already). ``onOpen``:
 * a right-click first selects the row (the Trays list opens it, as a click does).
 * ``onRemoved``: after Remove from tray. */
export function useTrayItemMenu({
  trays,
  today,
  openItem = false,
  onOpen,
  onRemoved,
}: {
  trays: TrayDef[];
  today: string;
  openItem?: boolean;
  onOpen?: (item: AnyItem) => void;
  onRemoved?: (item: AnyItem) => void;
}) {
  const menu = useContextMenu<AnyItem>();
  const done = useDoneFlow();
  const mover = useMoveItemFlow();
  const launch = useFileLaunch("");
  const starredOf = useStarredOf();
  const stars = useUnstar();
  const navigate = useNavigate();
  const [removing, setRemoving] = useState<AnyItem | null>(null);

  const entries = (item: AnyItem): MenuEntry[] => {
    const tray = trays.find((t) => t.id === item.tray_id);
    const how = doneOf(tray, today);
    const loading = tray === undefined && trays.length === 0 ? "The trays are still loading" : null;
    const open = item.state === "open";
    const first = "first_file" in item ? item.first_file : null;
    const file = first?.drive_id ?? item.files[0] ?? null;
    const away = fileWhy(first);
    const launchWhy = away ?? (launch.busy ? LAUNCH_BUSY : null);
    const launchOff = { disabled: !!launchWhy, reason: launchWhy ?? undefined };
    const renew = renewLabel(tray);
    const starred = starredOf(item.files);
    return [
      ...(open && renew ? [{ label: renew, onSelect: () => navigate(renewHref(item)) }] : []),
      open
        ? {
            // a done field that must be filled first: the item's page has the form
            label: how.needsForm ? `${markLabel(how.label)}…` : markLabel(how.label),
            onSelect: () => (how.needsForm ? navigate(itemHref(item)) : void done.run(item, tray, today)),
            disabled: !!loading || done.pending,
            reason: loading ?? undefined,
          }
        : { label: "Reopen", onSelect: () => void done.reopen(item) },
      "separator",
      ...(open
        ? trays
            .filter((t) => t.id !== item.tray_id)
            .map((t): MenuEntry => ({ label: `Move to ${visible(t.name)}`, onSelect: () => void mover.move(item, t), disabled: mover.pending }))
        : []),
      { label: "Remove from tray…", onSelect: () => setRemoving(item) },
      "separator",
      ...(openItem ? [{ label: "Open item", onSelect: () => navigate(itemHref(item)) }] : []),
      ...(file ? [{ label: "Open file", onSelect: () => void launch.run("open", file), ...launchOff }] : []),
      ...(first?.path && !away ? [{ label: "Show in folder", onSelect: () => navigate(browseHref(first.path!, first.drive_id)) }] : []),
      ...(file ? [{ label: showInLabel(), onSelect: () => void launch.run("reveal", file), ...launchOff }] : []),
      ...(starred.length > 0 ? (["separator"] as const) : []),
      // an item may hold several files: then each starred one is named
      ...starred.map((m) => ({
        label: starred.length === 1 ? "Remove the star" : `Remove the star from ${visible(memberName(m))}`,
        onSelect: () => stars.unstar(m),
        disabled: stars.busy,
      })),
    ];
  };

  const view: ReactNode = (
    <>
      {menu.view((item) => ({ label: `Actions for ${visible(item.title)}`, entries: entries(item) }))}
      {removing && (
        <RemoveItemSheet
          item={removing}
          onClose={() => setRemoving(null)}
          onRemoved={() => {
            setRemoving(null);
            onRemoved?.(removing);
          }}
        />
      )}
    </>
  );
  return {
    /** The row's contextmenu handler. */
    open: (item: AnyItem) => (e: MouseEvent) => {
      onOpen?.(item);
      menu.open(item, e);
    },
    view,
  };
}
