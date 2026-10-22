/** What Browse offers for the selected file: badges for its open tray items and
 * collections, "Put in tray" (a menu), "Add to collection…" and its own note (a folder:
 * Add to collection only). All of it is
 * database-only (the file stays where it is), except that adding to a published
 * collection adds a link in ##. Ongoing through the Ongoing sync. That needs no
 * preview (app-owned links only, journaled, undone by removing the member again), but
 * the batch that ran is shown under the actions. */
import { X } from "lucide-react";
import { type ReactNode, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  type Collection,
  type CollectionChange,
  errorText,
  useCollectionMembers,
  useCollections,
  useCreateCollection,
  useFileLinks,
  useGroupChange,
  useTrays,
} from "../api/client";
import { SummaryBox } from "../components/ai/SummaryBox";
import { CollectionPicker } from "../components/CollectionPicker";
import { changeToast } from "../components/collectionText";
import { LastChange } from "../components/LastChange";
import { SavedNote } from "../components/SavedNote";
import { useToast } from "../components/Toasts";
import { Menu, type MenuEntry } from "../components/ui/Menu";
import { trayIcon } from "../components/ui/Sidebar";
import { useQuickPut } from "../components/useQuickPut";
import { visible } from "../text";

/** Badges under the file name: its open items (→ the item in its tray) and its
 * collections (→ the collection). A collection the file is itself a member of (not only
 * through a folder), open and not a built-in, has a × that takes the file out of it (as
 * Remove from collection does: the file stays where it is), with Undo in the toast
 * (back in its group too). */
export function LinkBadges({ driveId }: { driveId: string }) {
  const links = useFileLinks(driveId);
  const members = useCollectionMembers();
  const groupChange = useGroupChange();
  const toast = useToast();
  const inFlight = useRef(false);
  if (links.isError) {
    return <p className="hint">Its trays and collections could not be loaded: {visible(errorText(links.error))}</p>;
  }
  const items = links.data?.items ?? [];
  const collections = links.data?.collections ?? [];
  if (items.length === 0 && collections.length === 0) return null;
  const remove = async (c: Collection, groupId: number | null) => {
    if (inFlight.current) return;
    inFlight.current = true;
    const name = visible(c.name);
    try {
      const result = await members.mutateAsync({ id: c.id, remove: driveId });
      const undo = async () => {
        try {
          await members.mutateAsync({ id: c.id, add: [driveId] });
          if (groupId !== null) await groupChange.mutateAsync({ op: "members", id: c.id, drive_ids: [driveId], group_id: groupId });
        } catch (e) {
          toast({ kind: "error", text: `Could not add it back to ${name}: ${visible(errorText(e))}` });
        }
      };
      toast({ ...changeToast(`Removed from ${name}`, result), actions: [{ label: "Undo", run: () => void undo() }] });
    } catch (e) {
      toast({ kind: "error", text: `Could not remove it from ${name}: ${visible(errorText(e))}` });
    } finally {
      inFlight.current = false;
    }
  };
  return (
    <ul className="badges link-badges" aria-label="In trays and collections">
      {items.map((i) => (
        <li key={`i${i.id}`}>
          <Link className="badge" to={`/trays/${encodeURIComponent(i.tray_id)}?item=${i.id}`}>
            {visible(i.tray_name)}: {visible(i.title)}
          </Link>
        </li>
      ))}
      {collections.map((c) => {
        const member = c.members.find((m) => m.drive_id === driveId);
        const removable = member !== undefined && c.state === "open" && c.kind == null;
        return (
          <li key={`c${c.id}`} className={removable ? "badge-removable" : undefined}>
            <Link className="badge" to={`/collections/${c.id}${c.state === "closed" ? "?state=closed" : ""}`}>
              {visible(c.name)}
              {c.state === "closed" && " (closed)"}
            </Link>
            {removable && (
              <button
                type="button"
                className="badge-remove"
                aria-label={`Remove from ${visible(c.name)}`}
                data-tip={`Remove from ${visible(c.name)} (the file stays where it is)`}
                disabled={members.isPending}
                onClick={() => void remove(c, member.group_id)}
              >
                <X size={12} aria-hidden="true" />
              </button>
            )}
          </li>
        );
      })}
    </ul>
  );
}

/** "Put in tray": a pull-down of the trays; choosing one puts the file in it at once
 * (an item with the scan's values, as Today's "Put in" does: DB only, with Open and
 * Undo in the toast). A tray the file already has an open item in is checked, and
 * "Remove from <tray>" takes that item back (while nobody changed it since). */
function PutInTrayMenu({ driveId }: { driveId: string }) {
  const trays = useTrays();
  const links = useFileLinks(driveId);
  const quick = useQuickPut();
  const list = trays.data?.trays ?? [];
  const open = (links.data?.items ?? []).filter((i) => i.state === "open");
  const entries: MenuEntry[] = list.map((t) => {
    const Icon = trayIcon(t);
    return {
      label: visible(t.name),
      icon: <Icon size={14} aria-hidden="true" />,
      checked: open.some((i) => i.tray_id === t.id),
      onSelect: () => void quick.put({ tray: t.id, trayName: t.name, ids: [driveId], name: null }),
    };
  });
  if (list.length === 0) {
    entries.push({
      label: trays.isError ? "Trays could not be loaded" : "No trays",
      disabled: true,
      onSelect: () => {},
    });
  }
  if (open.length > 0) {
    entries.push("separator");
    for (const item of open) {
      entries.push({
        label: `Remove from ${visible(item.tray_name)}`,
        onSelect: () =>
          void quick.takeBack([item], visible(item.tray_name), () =>
            void quick.put({ tray: item.tray_id, trayName: item.tray_name, ids: [driveId], name: null }),
          ),
      });
    }
  }
  return <Menu label="Put in tray" text="Put in tray" icon={null} entries={entries} className="file-action-menu" />;
}

/** Pick an open collection (or type a new name: created first) and add the file. */
function AddToCollection({
  driveId,
  onDone,
  onCancel,
}: {
  driveId: string;
  onDone: (result: CollectionChange) => void;
  onCancel: () => void;
}) {
  const collections = useCollections("open");
  const create = useCreateCollection();
  const members = useCollectionMembers();
  const toast = useToast();
  const [text, setText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const inFlight = useRef(false);

  const add = async (name: string) => {
    if (inFlight.current) return;
    inFlight.current = true;
    setError(null);
    try {
      const existing = (collections.data ?? []).find((c) => c.name === name);
      const id = existing?.id ?? (await create.mutateAsync(name)).id;
      const result = await members.mutateAsync({ id, add: [driveId] });
      onDone(result);
      toast(changeToast(`Added to ${result.collection.name}`, result));
    } catch (e) {
      setError(errorText(e));
    } finally {
      inFlight.current = false;
    }
  };

  return (
    <section className="file-action" aria-label="Add to collection">
      <CollectionPicker
        label="Collection"
        value={[]}
        onChange={(names) => {
          const name = names.at(-1);
          if (name) void add(name);
        }}
        text={text}
        onTextChange={setText}
      />
      <div className="actions">
        <button type="button" onClick={onCancel}>
          Cancel
        </button>
      </div>
      {(create.isPending || members.isPending) && (
        <p className="hint" role="status">
          Adding…
        </p>
      )}
      {error && (
        <p className="error" role="alert">
          {visible(error)}
        </p>
      )}
    </section>
  );
}

/** "Add to collection…" (``button``) and what it opens and leaves (``view``: the picker,
 * then the batch the last add ran in ##. Ongoing): for a file or a folder.
 * ``refusal``: why it cannot be added (the button is off, saying so). */
function useAddToCollectionAction(driveId: string, refusal: string | null = null): { button: ReactNode; view: ReactNode } {
  const [picking, setPicking] = useState(false);
  // The batch the last "Add to collection" ran in ##. Ongoing (links only), as returned.
  const [added, setAdded] = useState<CollectionChange | null>(null);
  const button = refusal ? (
    <span className="button-wrap" data-tip={refusal}>
      <button type="button" disabled>
        Add to collection…
      </button>
    </span>
  ) : (
    <button type="button" aria-expanded={picking} onClick={() => setPicking((p) => !p)}>
      Add to collection…
    </button>
  );
  const view = (
    <>
      {picking && (
        <AddToCollection
          driveId={driveId}
          onDone={(result) => {
            setPicking(false);
            setAdded(result);
          }}
          onCancel={() => setPicking(false)}
        />
      )}
      {added && <LastChange title={`Added to ${added.collection.name}: what happened in ##. Ongoing`} result={added} />}
    </>
  );
  return { button, view };
}

/** A selected folder's one action: Add to collection (everything in it then belongs). */
export function FolderActions({ driveId, refusal }: { driveId: string; refusal: string | null }) {
  const collect = useAddToCollectionAction(driveId, refusal);
  return (
    <div className="file-actions">
      <div className="actions">{collect.button}</div>
      {collect.view}
    </div>
  );
}

/** "Back to inbox": run by the screen's move flow (preview → confirm → Undo);
 * ``refusal`` says why it cannot run now (e.g. "Already in the inbox"). */
export type BackToInbox = { refusal: string | null; run: () => void };

/** The selected file's actions and note (keyed by the file: another file starts afresh). */
export function FileActions({ driveId, backToInbox }: { driveId: string; backToInbox?: BackToInbox }) {
  const collect = useAddToCollectionAction(driveId);
  return (
    <div className="file-actions">
      <div className="actions">
        <PutInTrayMenu driveId={driveId} />
        {collect.button}
        {backToInbox &&
          (backToInbox.refusal ? (
            <span className="button-wrap" data-tip={backToInbox.refusal}>
              <button type="button" disabled>
                Back to inbox
              </button>
            </span>
          ) : (
            <button type="button" onClick={backToInbox.run}>
              Back to inbox
            </button>
          ))}
      </div>
      {collect.view}
      <SummaryBox driveId={driveId} />
      <SavedNote kind="file" target={driveId} label="Note on this file" />
    </div>
  );
}
