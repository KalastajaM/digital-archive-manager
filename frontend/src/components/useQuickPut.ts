/** "Put in <tray>" (DB only: an item per file with its scan prefill, the files stay where
 * they are), with its toast: Open, and Undo for what was created. Shared by
 * Today's "Found in the inbox" and a drop on a sidebar tray. */
import { useRef } from "react";
import { useNavigate } from "react-router-dom";
import { errorText, type Item, useDiscardItem, useQuickPutInTray } from "../api/client";
import { plural } from "../format";
import { visible } from "../text";
import { useToast } from "./Toasts";

const enc = encodeURIComponent;

export type QuickPut = {
  tray: string;
  trayName: string;
  ids: string[];
  /** The file's name when one file is put (the toast names it), else null. */
  name: string | null;
  /** One file only: the tray fields to use instead of the scan prefill (an AI
   * suggestion, exactly as shown); the server still skips a file already in the tray. */
  fields?: Record<string, string>;
};

export function useQuickPut() {
  const quick = useQuickPutInTray();
  const discard = useDiscardItem();
  const navigate = useNavigate();
  const toast = useToast();
  // Synchronous guards: a second click (or drop) before React re-renders must not send
  // a second request.
  const putting = useRef(new Set<string>());
  const takingBack = useRef(new Set<number>());

  const takeBack = async (items: Item[], trayName: string) => {
    const mine = items.filter((it) => !takingBack.current.has(it.id));
    if (mine.length === 0) return;
    for (const it of mine) takingBack.current.add(it.id);
    let done = 0;
    try {
      for (const it of mine) {
        try {
          await discard.mutateAsync(it.id);
          done += 1;
        } catch (err) {
          toast({ kind: "error", text: `Could not take back ${visible(it.title)}: ${visible(errorText(err))}` });
        }
      }
    } finally {
      for (const it of mine) takingBack.current.delete(it.id);
    }
    if (done === 0) return;
    toast({
      kind: "info",
      text: mine.length === 1 ? `Taken back: ${visible(mine[0].title)}` : `Taken back ${plural(done, "item")} from ${trayName}`,
    });
  };

  /** Put ``ids`` in the tray; resolves when the toast is shown, with the items created
   * (none: all were in the tray already, or it failed). */
  const put = async ({ tray, trayName: rawTray, ids, name, fields }: QuickPut): Promise<Item[]> => {
    const key = `${tray}\n${ids.join("\n")}`;
    if (putting.current.has(key)) return [];
    putting.current.add(key);
    const trayName = visible(rawTray);
    const what = ids.length === 1 && name !== null ? visible(name) : plural(ids.length, "file");
    const openTray = { label: "Open", run: () => navigate(`/trays/${enc(tray)}`) };
    try {
      const result = await quick.mutateAsync({ tray, drive_ids: ids, ...(fields ? { fields } : {}) });
      const { created, skipped } = result;
      if (created.length === 0) {
        toast({ kind: "info", text: `${what}: already in ${trayName}`, actions: [openTray] });
        return [];
      }
      const back = { label: "Undo", run: () => void takeBack(created, trayName) };
      if (ids.length === 1 && created.length === 1) {
        const item = created[0];
        toast({
          kind: "info",
          text: `Put in ${trayName}: ${visible(item.title)}`,
          actions: [{ label: "Open", run: () => navigate(`/trays/${enc(tray)}?item=${item.id}`) }, back],
        });
        return created;
      }
      const already = skipped.length > 0 ? ` (${skipped.length} already in it)` : "";
      toast({
        kind: "info",
        text: `Put ${plural(created.length, "file")} in ${trayName}${already}`,
        actions: [openTray, back],
      });
      return created;
    } catch (err) {
      toast({ kind: "error", text: `Could not put ${what} in ${trayName}: ${visible(errorText(err))}` });
      return [];
    } finally {
      putting.current.delete(key);
    }
  };

  return {
    put,
    /** Take back the items just put (discard, DB only), with its toasts. */
    takeBack,
    /** The drive ids of the put in flight (for a busy button), or null. */
    pendingIds: quick.isPending ? (quick.variables?.drive_ids ?? null) : null,
  };
}
