/** The ★ Ongoing files as a tray item sees them, and the one-click unstar that Today's
 * Starred card and the tray item's menu share. */
import { useRef } from "react";
import { errorText, type Member, useBuiltin, useMark } from "../api/client";
import { baseName } from "../paths";
import { useToast } from "./Toasts";

export const memberName = (m: Member) => (m.path ? baseName(m.path) : m.drive_id);

/** Which of the given files are starred (one shared query, however many rows ask). */
export function useStarredOf() {
  const members = useBuiltin("starred").data?.members;
  return (files: readonly string[]) => members?.filter((m) => files.includes(m.drive_id)) ?? [];
}

/** Unstar in one click; the toast offers Undo. One request at a time. */
export function useUnstar() {
  const mark = useMark();
  const toast = useToast();
  const inFlight = useRef(false);
  const run = async (m: Member, action: "unstar" | "star") => {
    if (inFlight.current) return;
    inFlight.current = true;
    const name = memberName(m);
    try {
      await mark.mutateAsync({ action, ids: [m.drive_id] });
      toast(
        action === "unstar"
          ? { kind: "info", text: `Unstarred ${name}`, action: { label: "Undo", run: () => void run(m, "star") } }
          : { kind: "info", text: `Starred ${name}` },
      );
    } catch (e) {
      toast({ kind: "error", text: `Could not ${action} ${name}: ${errorText(e)}` });
    } finally {
      inFlight.current = false;
    }
  };
  return { busy: mark.isPending, unstar: (m: Member) => void run(m, "unstar") };
}
