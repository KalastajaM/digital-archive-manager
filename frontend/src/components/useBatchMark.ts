/** ★ and ! for several files at once (Browse's checked rows, the Inbox's selection):
 * all of them marked already → unmark them; else mark them all. One request, a toast
 * with Undo (the opposite action). */
import { useRef } from "react";
import { errorText, type MarkAction, useMark } from "../api/client";
import { plural } from "../format";
import { visible } from "../text";
import { useToast } from "./Toasts";

export type Markable = { drive_id: string; name: string; marks?: readonly string[] | null };

const KEY = { star: "starred", important: "important" } as const;

/** Whether every one of ``items`` has the mark (false for none). */
export const allMarked = (items: Markable[], kind: "star" | "important") =>
  items.length > 0 && items.every((it) => it.marks?.includes(KEY[kind]));

export function useBatchMark() {
  const mark = useMark();
  const toast = useToast();
  const inFlight = useRef(false);
  const run = async (kind: "star" | "important", items: Markable[]) => {
    if (inFlight.current || items.length === 0) return;
    const ids = items.map((it) => it.drive_id);
    const all = allMarked(items, kind);
    const action: MarkAction = all ? (kind === "star" ? "unstar" : "unimportant") : kind;
    const opposite: MarkAction = all ? kind : kind === "star" ? "unstar" : "unimportant";
    const what = items.length === 1 ? visible(items[0].name) : plural(items.length, "file");
    const said = {
      star: `Starred ${what}`,
      unstar: `Removed the star from ${what}`,
      important: `Marked ${what} as Important`,
      unimportant: `${what}: no longer Important`,
    };
    const send = async (a: MarkAction, undo: MarkAction | null) => {
      if (inFlight.current) return;
      inFlight.current = true;
      try {
        await mark.mutateAsync({ action: a, ids });
        toast({
          kind: "info",
          text: said[a],
          action: undo ? { label: "Undo", run: () => void send(undo, null) } : undefined,
        });
      } catch (e) {
        toast({ kind: "error", text: `Could not change the marks: ${visible(errorText(e))}` });
      } finally {
        inFlight.current = false;
      }
    };
    await send(action, opposite);
  };
  return { run, busy: mark.isPending };
}
