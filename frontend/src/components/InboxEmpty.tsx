import { FolderOpen, Inbox as InboxIcon, Upload } from "lucide-react";
import { errorText, revealFolder } from "../api/client";
import { fileManagerName, inFileManager } from "../fileManager";
import { visible } from "../text";
import { useToast } from "./Toasts";
import { EmptyState } from "./ui/EmptyState";

/** "Show in Finder" / "Show in Explorer" / "Show folder" (other file managers). */
export function showLabel(): string {
  const fm = fileManagerName();
  return fm === null ? "Show folder" : `Show in ${fm}`;
}

type Props = {
  /** The configured inbox folder name. */
  inbox: string;
  /** False in a new archive that has no folders yet. */
  exists: boolean;
  onChoose: () => void;
  choosing: boolean;
  onSetup: () => void;
};

/** What the inbox shows with nothing in it: how documents get in. */
export function InboxEmpty({ inbox, exists, onChoose, choosing, onSetup }: Props) {
  const toast = useToast();
  const name = visible(inbox);
  if (!exists) {
    return (
      <EmptyState
        icon={<InboxIcon size={40} strokeWidth={1.25} />}
        title="The inbox folder is not there yet."
        hint={
          <>
            dam looks for new files in <code>{name}</code>. Set up the folders to make it.
          </>
        }
        action={
          <button type="button" className="primary" onClick={onSetup}>
            Set up folders…
          </button>
        }
      />
    );
  }
  return (
    <EmptyState
      icon={<InboxIcon size={40} strokeWidth={1.25} />}
      title="The inbox is empty."
      hint={
        <>
          Put new files in <code>{name}</code> — drag them there {inFileManager()}, or point your scanner at it.
        </>
      }
      action={
        <span className="inbox-empty-actions">
          <button
            type="button"
            onClick={() => {
              revealFolder(inbox).catch((e: unknown) => toast({ kind: "error", text: `Could not open the folder: ${visible(errorText(e))}` }));
            }}
          >
            <FolderOpen size={14} aria-hidden="true" /> {showLabel()}
          </button>
          <button type="button" disabled={choosing} onClick={onChoose}>
            <Upload size={14} aria-hidden="true" /> Choose files…
          </button>
        </span>
      }
    />
  );
}
