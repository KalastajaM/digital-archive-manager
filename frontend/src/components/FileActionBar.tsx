/** A file's actions as the screens hand them over (``FileActionBarProps``): the panel's
 * icon rows draw them (``FileActionIcons``) and Browse's right-click menu lists them
 * (``fileMenuEntries``), so the labels, the order and the disabled reasons are the same in
 * both. An action the screen leaves out is not shown; a disabled one keeps its reason. The
 * screen decides what each action does and on which files. */
import type { Ref } from "react";
import { fileEditRefusal, type MetaFile } from "./FileMeta";
import { TRASH_LABEL } from "./Trash";
import { useAIState } from "./ai/useAI";
import type { FilingAI } from "./ai/useFilingAI";
import type { MenuEntry } from "./ui/Menu";

/** One button: what it does, whether it is off now and why. */
export type BarAction = {
  run: () => void;
  disabled?: boolean;
  /** Why it is disabled (the tooltip; a disabled button shows none of its own). */
  reason?: string | null;
};

/** ★ and !: ``on`` when the selection has the mark already (the button then unmarks). */
export type BarMark = BarAction & { on: boolean };

export type FileActionBarProps = {
  /** Put in tray (Browse) or Move to tray (a tray): ``entries`` are the pull-down. */
  tray?: { label: "Put in tray" | "Move to tray"; entries: MenuEntry[]; disabled?: boolean; reason?: string | null };
  removeFromTray?: BarAction;
  /** Take the file out of the collection the screen shows (it sits where Remove from tray
   * does in a tray; ``name`` is the file's, which the accessible name carries). */
  removeFromCollection?: BarAction & { name: string };
  backToInbox?: BarAction;
  moveTo?: BarAction & { shortcut?: string };
  sender?: BarAction;
  person?: BarAction;
  ask?: BarAction;
  star?: BarMark;
  important?: BarMark;
  /** Restore from To Delete: the pull-down's entries (shown for files in ##. To Delete only). */
  restore?: { entries: MenuEntry[] };
  /** Move to To Delete: ``count`` names how many files (several selected). */
  trash?: BarAction & { count?: number };
  /** The element around the buttons (a screen finds out whether the focus is on the bar). */
  barRef?: Ref<HTMLDivElement>;
};

const off = (a: BarAction) => a.disabled === true || !!a.reason;
const why = (a: BarAction) => a.reason ?? undefined;

type Entry = Exclude<MenuEntry, "separator">;

/** A right-click menu's entry for one of the bar's actions: off ones say why. */
const entry = (label: string, a: BarAction): Entry => ({ label, onSelect: a.run, disabled: off(a), reason: why(a) });

/** The bar's actions as a right-click menu (a file or selection in a list), in groups:
 * the screen's ``lead`` entries (Quick Look, Open, Show in Finder…), the trays (each
 * named: "Put in To pay"), Move to…, Back to inbox and Remove from tray or collection,
 * From…, For… and Ask AI, ``more``'s Add tag… and Add to collection… (``reason``: why they
 * are off), the marks, then Restore and the bin. Same labels and reasons as the icons. */
export function fileMenuEntries(
  p: FileActionBarProps,
  more?: { addTag: () => void; addTo: () => void; reason: string | null },
  lead: MenuEntry[] = [],
): MenuEntry[] {
  const out: MenuEntry[] = [...lead];
  const group = (...entries: (Entry | Entry[] | false | undefined)[]) => {
    const some = entries.flat().filter((e): e is Entry => !!e);
    if (some.length > 0) out.push(...(out.length > 0 ? ["separator" as const] : []), ...some);
  };
  if (p.tray) {
    const verb = p.tray.label === "Put in tray" ? "Put in" : "Move to";
    group(
      p.tray.disabled || p.tray.reason
        ? { label: p.tray.label, onSelect: () => {}, disabled: true, reason: p.tray.reason ?? undefined }
        : (() => {
            // the trays (named with the verb), then the trays the file is in (Remove from …)
            const at = p.tray.entries.indexOf("separator");
            const trays = (at < 0 ? p.tray.entries : p.tray.entries.slice(0, at)).filter((e): e is Entry => e !== "separator");
            const rest = at < 0 ? [] : p.tray.entries.slice(at + 1).filter((e): e is Entry => e !== "separator");
            return [...trays.map((e) => (e.disabled ? { ...e, label: p.tray!.label, reason: e.reason ?? e.label } : { ...e, label: `${verb} ${e.label}` })), ...rest];
          })(),
    );
  }
  group(
    p.moveTo && entry("Move to…", p.moveTo),
    p.backToInbox && entry("Back to inbox", p.backToInbox),
    p.removeFromTray && entry("Remove from tray…", p.removeFromTray),
    p.removeFromCollection && entry("Remove from collection", p.removeFromCollection),
  );
  group(p.sender && entry("From…", p.sender), p.person && entry("For…", p.person), p.ask && entry("Ask AI", p.ask));
  if (more) {
    const reason = more.reason ?? undefined;
    group({ label: "Add tag…", onSelect: more.addTag, disabled: !!reason, reason }, { label: "Add to collection…", onSelect: more.addTo, disabled: !!reason, reason });
  }
  group(
    p.star && entry(p.star.on ? "Remove the star" : "Star", p.star),
    p.important && entry(p.important.on ? "Unmark Important" : "Mark Important", p.important),
  );
  group(
    p.restore?.entries.filter((e): e is Entry => e !== "separator"),
    p.trash && entry(p.trash.count !== undefined && p.trash.count > 1 ? `Move ${p.trash.count} to To Delete` : TRASH_LABEL, p.trash),
  );
  return out;
}

/** The Ask AI button for one file (``file`` null: none selected, or several, and ``none``
 * says why). Off while AI is off, for a file that cannot be edited, or while a request is
 * under way. */
export function useAskAction(
  ai: FilingAI,
  file: (Pick<MetaFile, "path" | "is_dir" | "is_link"> & { drive_id: string }) | null,
  none: string,
  busy = false,
): BarAction {
  const state = useAIState();
  const refusal = file ? fileEditRefusal(file) : none;
  return {
    run: () => {
      if (file) ai.ask(file.drive_id);
    },
    disabled: file === null || busy || ai.busy || !state.on,
    reason: refusal ?? (state.off ? "AI is off: Activity → AI turns it on" : null),
  };
}
