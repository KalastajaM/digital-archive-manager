/** The file panel's row of icon buttons (the New look; one component for Browse, the Inbox,
 * the trays and a collection, so the icons, their order, tooltips and disabled reasons are the
 * same everywhere). Every tooltip carries the key where there is one: "Quick Look (Space)".
 * One row, right-aligned, in two parts that wrap as wholes when the panel is narrow:
 *
 *  "look at it":  Open, Quick Look, Show in Finder, Show in folder, Relatives, Ask AI.
 *  "file it":     Who sent it, Who it's for, Put in tray │ Star, Important │
 *                 Back to inbox, Remove from collection, Restore │ Move to To Delete (red, last).
 *
 * What is done in place is not here: Rename (click the name), Move to… (click the folder),
 * Tag…, Add to collection… (the boxes). Only what applies in the screen's context is drawn: a
 * screen leaves an action out (no Back to inbox for a file already in the inbox), and one
 * that cannot run now stays, disabled, with its reason as the tooltip. For several files the
 * look row is left out and the row holds what applies to many (Move to… and Add to collection
 * have no in-place way for a selection, so they are here). The screens' handlers are the ones
 * ``FileActionBar`` (Classic) gets; this only draws them. */
import { ArchiveRestore, Eye, FolderInput, FolderOpen, FolderSearch, Library, Network, Sparkles, ExternalLink, CircleMinus, ArrowRightLeft, Building2, User, Inbox, Trash2 } from "lucide-react";
import { Fragment, type ReactNode, useState } from "react";
import { showInLabel } from "../fileManager";
import { toDeleteReason } from "../toDelete";
import type { FileActionBarProps } from "./FileActionBar";
import { LAUNCH_BUSY, useFileLaunch } from "./FileLaunch";
import { ImportantGlyph, StarGlyph } from "./MarkIcons";
import { RelativesDialog } from "./RelativesDialog";
import { TRASH_KEY, TRASH_LABEL } from "./Trash";
import { IconButton } from "./ui/IconButton";
import { Menu, type MenuEntry } from "./ui/Menu";

const ICON = { size: 16, strokeWidth: 1.75 } as const;

export type IconsFile = {
  drive_id: string;
  path: string | null;
  name?: string | null;
  ext?: string | null;
  is_dir?: boolean;
  is_link?: boolean;
  /** Its archive folder is away (false): Open and Show in Finder are off. */
  connected?: boolean;
};

export type FileActionIconsProps = Omit<FileActionBarProps, "removeFromTray"> & {
  /** The file the look row acts on (none: several files are selected). */
  file?: IconsFile | null;
  /** Show in folder: the file's own folder in Browse, with the file selected (a screen that is
   * not Browse: a collection, a tray). Left out without it. */
  showInFolder?: () => void;
  /** Quick Look (the screen's own): the button is left out without it. */
  onQuickLook?: () => void;
  /** Quick Look cannot open now. */
  quickLookReason?: string | null;
  /** Several files: Add to collection as a pull-down. */
  addTo?: { entries: MenuEntry[]; disabled?: boolean; reason?: string | null };
  /** The Inbox's own name for the group (a screen with its own label). */
  className?: string;
};

const off = (a: { disabled?: boolean; reason?: string | null }) => a.disabled === true || !!a.reason;
const why = (a: { reason?: string | null }) => a.reason ?? undefined;

/** A thin vertical rule between two groups of a row. */
function Sep() {
  return <span className="file-actions-sep" role="separator" aria-orientation="vertical" />;
}

/** Groups side by side with a rule between every two that are not empty. */
function Groups({ groups }: { groups: ReactNode[][] }) {
  const filled = groups.filter((g) => g.length > 0);
  return (
    <>
      {filled.map((g, i) => (
        <Fragment key={i}>
          {i > 0 && <Sep />}
          {g}
        </Fragment>
      ))}
    </>
  );
}

export function FileActionIcons(p: FileActionIconsProps) {
  const file = p.file ?? null;
  const launch = useFileLaunch(file?.drive_id ?? "");
  const [relatives, setRelatives] = useState(false);
  const away = file?.connected === false;
  const launchReason = away ? "Not connected" : launch.busy ? LAUNCH_BUSY : undefined;

  const look: ReactNode[] = [];
  if (file && file.path !== null) {
    look.push(
      <IconButton
        key="open"
        icon={<ExternalLink {...ICON} />}
        label="Open"
        tip="Open it in its app"
        disabled={launch.busy || away}
        disabledReason={launchReason}
        onClick={() => void launch.run("open")}
      />,
    );
  }
  if (p.onQuickLook) {
    look.push(
      <IconButton
        key="ql"
        icon={<Eye {...ICON} />}
        label="Quick Look"
        tip="Quick Look (Space)"
        disabled={!!p.quickLookReason}
        disabledReason={p.quickLookReason ?? undefined}
        onClick={p.onQuickLook}
      />,
    );
  }
  if (file && file.path !== null) {
    look.push(
      <IconButton
        key="reveal"
        icon={<FolderSearch {...ICON} />}
        label={showInLabel()}
        disabled={launch.busy || away}
        disabledReason={launchReason}
        onClick={() => void launch.run("reveal")}
      />,
    );
  }
  if (file && file.path !== null && p.showInFolder) {
    look.push(
      <IconButton
        key="folder"
        icon={<FolderOpen {...ICON} />}
        label="Show in folder"
        tip="Show in folder: its folder in Browse"
        onClick={p.showInFolder}
      />,
    );
  }
  // a link stands for its target and a file in To Delete has no relatives to act on
  const canRelatives = file && file.path !== null && !file.is_dir && !file.is_link && toDeleteReason(file.path) === null;
  if (canRelatives) {
    look.push(
      <IconButton
        key="rel"
        icon={<Network {...ICON} />}
        label="Relatives"
        tip="Relatives: the files this one belongs with"
        onClick={() => setRelatives(true)}
      />,
    );
  }
  if (p.ask) {
    look.push(
      <IconButton
        key="ask"
        icon={<Sparkles {...ICON} />}
        label="Ask AI"
        tip="Ask AI to suggest a name, folder and tags"
        disabled={off(p.ask)}
        disabledReason={why(p.ask)}
        onClick={p.ask.run}
      />,
    );
  }

  const who: ReactNode[] = [];
  if (p.sender) {
    who.push(
      <IconButton
        key="from"
        icon={<Building2 {...ICON} />}
        label="From…"
        tip="Who sent it? Say who sent these documents"
        disabled={off(p.sender)}
        disabledReason={why(p.sender)}
        onClick={p.sender.run}
      />,
    );
  }
  if (p.person) {
    who.push(
      <IconButton
        key="for"
        icon={<User {...ICON} />}
        label="For…"
        tip="Who is it for? Say who these documents are for"
        disabled={off(p.person)}
        disabledReason={why(p.person)}
        onClick={p.person.run}
      />,
    );
  }
  if (p.tray) {
    who.push(
      p.tray.disabled || p.tray.reason ? (
        <IconButton
          key="tray"
          icon={<ArrowRightLeft {...ICON} />}
          label={p.tray.label}
          disabled
          disabledReason={p.tray.reason ?? undefined}
        />
      ) : (
        <Menu key="tray" label={p.tray.label} icon={<ArrowRightLeft {...ICON} />} entries={p.tray.entries} />
      ),
    );
  }
  if (p.addTo) {
    who.push(
      p.addTo.disabled || p.addTo.reason ? (
        <IconButton
          key="addto"
          icon={<Library {...ICON} />}
          label="Add to collection"
          disabled
          disabledReason={p.addTo.reason ?? undefined}
        />
      ) : (
        <Menu key="addto" label="Add to collection" icon={<Library {...ICON} />} entries={p.addTo.entries} />
      ),
    );
  }

  const marks: ReactNode[] = [];
  if (p.star) {
    marks.push(
      <IconButton
        key="star"
        icon={<StarGlyph size={16} filled={p.star.on} />}
        label={p.star.on ? "Remove the star" : "Star"}
        pressed={p.star.on}
        className={p.star.on ? "mark-toggle mark-starred" : "mark-toggle"}
        disabled={off(p.star)}
        disabledReason={why(p.star)}
        onClick={p.star.run}
      />,
    );
  }
  if (p.important) {
    marks.push(
      <IconButton
        key="imp"
        icon={<ImportantGlyph large />}
        label={p.important.on ? "Unmark Important" : "Mark Important"}
        pressed={p.important.on}
        className={p.important.on ? "mark-toggle mark-important" : "mark-toggle"}
        disabled={off(p.important)}
        disabledReason={why(p.important)}
        onClick={p.important.run}
      />,
    );
  }

  const move: ReactNode[] = [];
  if (p.moveTo) {
    move.push(
      <IconButton
        key="move"
        icon={<FolderInput {...ICON} />}
        label="Move to…"
        tip={`Move to… (${p.moveTo.shortcut ?? "⇧⌘M"})`}
        disabled={off(p.moveTo)}
        disabledReason={why(p.moveTo)}
        onClick={p.moveTo.run}
      />,
    );
  }
  if (p.backToInbox) {
    move.push(
      <IconButton
        key="inbox"
        icon={<Inbox {...ICON} />}
        label="Back to inbox"
        disabled={off(p.backToInbox)}
        disabledReason={why(p.backToInbox)}
        onClick={p.backToInbox.run}
      />,
    );
  }
  if (p.removeFromCollection) {
    move.push(
      <IconButton
        key="rmcol"
        icon={<CircleMinus {...ICON} />}
        label={`Remove ${p.removeFromCollection.name} from the collection`}
        tip="Remove from this collection (the file stays where it is)"
        disabled={off(p.removeFromCollection)}
        disabledReason={why(p.removeFromCollection)}
        onClick={p.removeFromCollection.run}
      />,
    );
  }
  if (p.restore) {
    move.push(
      <Menu key="restore" label="Restore from To Delete" icon={<ArchiveRestore {...ICON} />} entries={p.restore.entries} />,
    );
  }

  const trash = p.trash && (
    <IconButton
      key="trash"
      icon={<Trash2 {...ICON} />}
      label={p.trash.count !== undefined && p.trash.count > 1 ? `Move ${p.trash.count} to To Delete` : TRASH_LABEL}
      tip={`${p.trash.count !== undefined && p.trash.count > 1 ? `Move ${p.trash.count} to To Delete` : TRASH_LABEL} (${TRASH_KEY})`}
      className="trash-button"
      disabled={p.trash.disabled || !!p.trash.reason}
      disabledReason={p.trash.reason ?? undefined}
      onClick={p.trash.run}
    />
  );

  const fileIt = <Groups groups={[who, marks, move, trash ? [trash] : []]} />;
  const hasFileIt = who.length + marks.length + move.length > 0 || !!trash;
  return (
    <div className={["file-actions-icons", p.className].filter(Boolean).join(" ")} ref={p.barRef}>
      {look.length > 0 && (
        <div className="file-actions-row" role="group" aria-label="Look at it">
          {look}
        </div>
      )}
      {look.length > 0 && hasFileIt && <Sep />}
      {hasFileIt && (
        <div className="file-actions-row" role="group" aria-label="File it">
          {fileIt}
        </div>
      )}
      {relatives && canRelatives && file && file.path !== null && (
        <RelativesDialog
          file={{ drive_id: file.drive_id, path: file.path, name: file.name ?? null, ext: file.ext }}
          onClose={() => setRelatives(false)}
        />
      )}
    </div>
  );
}
