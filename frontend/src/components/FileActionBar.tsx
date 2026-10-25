/** The one group of icon buttons for a file's actions, at the right end of a screen's header
 * (over the file pane): Browse and the trays use this same component, so the icons, the
 * order, the labels, the tooltips and the disabled reasons are the same in both.
 *
 * Order: Put in tray (a pull-down of the trays; "Move to tray" in a tray), Remove from
 * tray (in a collection: Remove from collection), Back to inbox, Move to…, From…, For…, Ask AI, Star, Important, Restore, and the
 * bin last (Move to To Delete). An action the screen leaves out is not shown; a disabled
 * one keeps its reason as the tooltip. The screen decides what each button does and on
 * which files; this component only draws them. */
import {
  ArchiveRestore,
  ArrowRightLeft,
  Building2,
  CircleMinus,
  FolderInput,
  Inbox,
  Sparkles,
  User,
} from "lucide-react";
import type { Ref } from "react";
import { fileEditRefusal, type MetaFile } from "./FileMeta";
import { ImportantGlyph, StarGlyph } from "./MarkIcons";
import { TrashButton } from "./Trash";
import { useAIState } from "./ai/useAI";
import type { FilingAI } from "./ai/useFilingAI";
import { IconButton } from "./ui/IconButton";
import { Menu, type MenuEntry } from "./ui/Menu";

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

export function FileActionBar(p: FileActionBarProps) {
  return (
    <div className="file-action-bar" ref={p.barRef}>
      {p.tray &&
        (p.tray.disabled || p.tray.reason ? (
          <IconButton
            icon={<ArrowRightLeft />}
            label={p.tray.label}
            disabled
            disabledReason={p.tray.reason ?? undefined}
          />
        ) : (
          <Menu label={p.tray.label} icon={<ArrowRightLeft />} entries={p.tray.entries} align="end" />
        ))}
      {p.removeFromTray && (
        <IconButton
          icon={<CircleMinus />}
          label="Remove from tray"
          tip="Remove from this tray (the files stay where they are)"
          disabled={off(p.removeFromTray)}
          disabledReason={why(p.removeFromTray)}
          onClick={p.removeFromTray.run}
        />
      )}
      {p.removeFromCollection && (
        <IconButton
          icon={<CircleMinus />}
          label={`Remove ${p.removeFromCollection.name} from the collection`}
          tip="Remove from this collection (the file stays where it is)"
          disabled={off(p.removeFromCollection)}
          disabledReason={why(p.removeFromCollection)}
          onClick={p.removeFromCollection.run}
        />
      )}
      {p.backToInbox && (
        <IconButton
          icon={<Inbox />}
          label="Back to inbox"
          disabled={off(p.backToInbox)}
          disabledReason={why(p.backToInbox)}
          onClick={p.backToInbox.run}
        />
      )}
      {p.moveTo && (
        <IconButton
          icon={<FolderInput />}
          label="Move to…"
          shortcut={p.moveTo.shortcut}
          disabled={off(p.moveTo)}
          disabledReason={why(p.moveTo)}
          onClick={p.moveTo.run}
        />
      )}
      {p.sender && (
        <IconButton
          icon={<Building2 />}
          label="From…"
          tip="Say who sent these documents"
          disabled={off(p.sender)}
          disabledReason={why(p.sender)}
          onClick={p.sender.run}
        />
      )}
      {p.person && (
        <IconButton
          icon={<User />}
          label="For…"
          tip="Say who these documents are for"
          disabled={off(p.person)}
          disabledReason={why(p.person)}
          onClick={p.person.run}
        />
      )}
      {p.ask && (
        <IconButton
          icon={<Sparkles />}
          label="Ask AI"
          tip="Ask AI to suggest a name, folder and tags"
          disabled={off(p.ask)}
          disabledReason={why(p.ask)}
          onClick={p.ask.run}
        />
      )}
      {p.star && (
        <IconButton
          icon={<StarGlyph size={16} filled={p.star.on} />}
          label={p.star.on ? "Remove the star" : "Star"}
          pressed={p.star.on}
          className={p.star.on ? "mark-toggle mark-starred" : "mark-toggle"}
          disabled={off(p.star)}
          disabledReason={why(p.star)}
          onClick={p.star.run}
        />
      )}
      {p.important && (
        <IconButton
          icon={<ImportantGlyph large />}
          label={p.important.on ? "Unmark Important" : "Mark Important"}
          pressed={p.important.on}
          className={p.important.on ? "mark-toggle mark-important" : "mark-toggle"}
          disabled={off(p.important)}
          disabledReason={why(p.important)}
          onClick={p.important.run}
        />
      )}
      {p.restore && <Menu label="Restore from To Delete" icon={<ArchiveRestore />} align="end" entries={p.restore.entries} />}
      {p.trash && (
        <TrashButton
          count={p.trash.count}
          disabled={p.trash.disabled}
          disabledReason={p.trash.reason}
          onClick={p.trash.run}
        />
      )}
    </div>
  );
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
