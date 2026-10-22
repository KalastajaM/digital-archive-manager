/** The ★ and ! toggles of one file, wherever it is shown in detail (the review card,
 * the Browse preview, Quick Look, the viewer, a tray item's files, a collection's
 * selected file). One click marks or unmarks; marking never moves the file. The toast
 * offers the opposite action. One change at a time per file (a synchronous guard). */
import { useContext, useRef, useState } from "react";
import { errorText, type Mark, type MarkAction, marksAfter, useFileDetail, useMark } from "../api/client";
import { visible } from "../text";
import { InlineResults } from "./FileLaunch";
import { ImportantGlyph, StarGlyph } from "./MarkIcons";
import { useToast } from "./Toasts";
import { IconButton } from "./ui/IconButton";

type Props = {
  driveId: string;
  /** For the toasts. */
  name: string;
  /** The file's marks when the caller has them; else they are read from the file's
   * record. */
  marks?: readonly Mark[];
  tipSide?: "below" | "above";
};

const TEXT: Record<MarkAction, { done: string; undo: MarkAction; undoLabel: string; failed: string }> = {
  star: { done: "Starred", undo: "unstar", undoLabel: "Undo", failed: "Could not star" },
  unstar: { done: "Unstarred", undo: "star", undoLabel: "Undo", failed: "Could not unstar" },
  important: { done: "Marked Important:", undo: "unimportant", undoLabel: "Undo", failed: "Could not mark Important" },
  unimportant: { done: "No longer Important:", undo: "important", undoLabel: "Undo", failed: "Could not unmark" },
};

/** Marks from the record when the caller has none (one shared query per file). */
function useMarksOf(driveId: string, given: readonly Mark[] | undefined): readonly Mark[] | undefined {
  const detail = useFileDetail(driveId, given === undefined);
  return given ?? detail.data?.record.marks;
}

export function MarkToggles({ driveId, name, marks: given, tipSide }: Props) {
  const fetched = useMarksOf(driveId, given);
  const mark = useMark();
  const toast = useToast();
  // Inside a modal (Quick Look) a toast would sit under it: the dialog's status line
  // says what happened instead, and the toggle itself is the opposite action.
  const inline = useContext(InlineResults);
  const inFlight = useRef(false);
  const [busy, setBusy] = useState(false);
  // What the last change made, until the caller's data catches up (keyed by the
  // marks it was made on, so newer data wins).
  const [override, setOverride] = useState<{ base: string; marks: Mark[] } | null>(null);
  const base = JSON.stringify([driveId, fetched ?? null]);
  const marks: readonly Mark[] = override?.base === base ? override.marks : (fetched ?? []);
  const shown = visible(name);
  // The newest base and marks, for a change that runs later (the toast's opposite
  // action): it builds on what is shown then, not on what was shown at the click.
  const latest = useRef({ base, marks });
  latest.current = { base, marks };

  const run = async (action: MarkAction) => {
    if (inFlight.current) return;
    inFlight.current = true;
    setBusy(true);
    try {
      await mark.mutateAsync({ action, ids: [driveId] });
      const { base: now, marks: from } = latest.current;
      setOverride({ base: now, marks: marksAfter(from, action) });
      const t = TEXT[action];
      if (inline) {
        inline({ kind: "info", text: `${t.done} ${name}` });
        return;
      }
      toast({
        kind: "info",
        text: `${t.done} ${name}`,
        action: { label: t.undoLabel, run: () => void run(t.undo) },
      });
    } catch (e) {
      const text = `${TEXT[action].failed} ${name}: ${errorText(e)}`;
      if (inline) inline({ kind: "error", text: visible(text) });
      else toast({ kind: "error", text });
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  };

  const starred = marks.includes("starred");
  const important = marks.includes("important");
  const reason = busy ? "Still saving the last change" : undefined;
  return (
    <span className="mark-toggles" role="group" aria-label={`Marks of ${shown}`}>
      <IconButton
        icon={<StarGlyph size={16} filled={starred} />}
        label={starred ? "Remove the star" : "Star"}
        pressed={starred}
        tipSide={tipSide}
        className={starred ? "mark-toggle mark-starred" : "mark-toggle"}
        disabled={busy}
        disabledReason={reason}
        onClick={() => void run(starred ? "unstar" : "star")}
      />
      <IconButton
        icon={<ImportantGlyph large />}
        label={important ? "Unmark Important" : "Mark Important"}
        pressed={important}
        tipSide={tipSide}
        className={important ? "mark-toggle mark-important" : "mark-toggle"}
        disabled={busy}
        disabledReason={reason}
        onClick={() => void run(important ? "unimportant" : "important")}
      />
    </span>
  );
}
