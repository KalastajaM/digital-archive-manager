/** What Browse offers for the selected file: badges for its open tray items and
 * collections, "Put in tray" (a menu), the collections field (a folder: that field
 * only). All of it is
 * database-only (the file stays where it is), except that adding to a published
 * collection adds a link in ##. Ongoing through the Ongoing sync. That needs no
 * preview (app-owned links only, journaled, undone by removing the member again), but
 * the batch that ran is shown under the actions. */
import { X } from "lucide-react";
import { useRef, useState } from "react";
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
import { type CollectionChip, CollectionInput } from "../components/CollectionInput";
import { changeToast } from "../components/collectionText";
import { LastChange } from "../components/LastChange";
import { useToast } from "../components/Toasts";
import { Menu, type MenuEntry } from "../components/ui/Menu";
import { trayIcon } from "../components/ui/Sidebar";
import { useQuickPut } from "../components/useQuickPut";
import { visible } from "../text";

/** Takes a file out of a collection (as Remove from collection does: the file stays where
 * it is), with Undo in the toast (back in its group too). One at a time. */
function useRemoveFromCollection(driveId: string) {
  const members = useCollectionMembers();
  const groupChange = useGroupChange();
  const toast = useToast();
  const inFlight = useRef(false);
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
  return { remove, pending: members.isPending };
}

/** A collection the file is itself a member of (not only through a folder), open and not
 * a built-in, can be taken out. */
const removableMember = (c: Collection, driveId: string) => {
  const member = c.members.find((m) => m.drive_id === driveId);
  return member !== undefined && c.state === "open" && c.kind == null ? member : null;
};

/** Badges under the file name: its open items (→ the item in its tray) and, unless
 * ``collections`` is off, its collections (→ the collection). A collection the file is
 * itself a member of has a × that takes the file out of it. */
export function LinkBadges({ driveId, hideItem, collections: withCollections = true }: { driveId: string; hideItem?: number; collections?: boolean }) {
  const links = useFileLinks(driveId);
  const removal = useRemoveFromCollection(driveId);
  if (links.isError) {
    if (!withCollections) return null; // the collections field says so
    return <p className="hint">Its trays and collections could not be loaded: {visible(errorText(links.error))}</p>;
  }
  // the item whose view this is is not listed as a link to itself
  const items = (links.data?.items ?? []).filter((i) => i.id !== hideItem);
  const collections = withCollections ? (links.data?.collections ?? []) : [];
  if (items.length === 0 && collections.length === 0) return null;
  return (
    <ul className="badges link-badges" aria-label={withCollections ? "In trays and collections" : "In trays"}>
      {items.map((i) => (
        <li key={`i${i.id}`}>
          <Link className="tag tag-grey" to={`/trays/${encodeURIComponent(i.tray_id)}?item=${i.id}`}>
            {visible(i.tray_name)}: {visible(i.title)}
          </Link>
        </li>
      ))}
      {collections.map((c) => {
        const member = removableMember(c, driveId);
        return (
          <li key={`c${c.id}`} className={member ? "badge-removable" : undefined}>
            <Link className="tag tag-grey" to={`/collections/${c.id}${c.state === "closed" ? "?state=closed" : ""}`}>
              {visible(c.name)}
              {c.state === "closed" && " (closed)"}
            </Link>
            {member && (
              <button
                type="button"
                className="badge-remove"
                aria-label={`Remove from ${visible(c.name)}`}
                data-tip={`Remove from ${visible(c.name)} (the file stays where it is)`}
                disabled={removal.pending}
                onClick={() => void removal.remove(c, member.group_id)}
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

/** The file's (or folder's) collections as chips with the field that adds to them, all
 * applied at once: × takes it out and typing a collection adds it (a name that is none
 * yet is created first), each with Undo in the toast. Adding to a published collection
 * adds a link in ##. Ongoing (app-owned, journaled): the batch that ran is shown under
 * the field. ``refusal``: why it cannot be added to (the field is off, saying so). */
function CollectionsField({ driveId, refusal = null }: { driveId: string; refusal?: string | null }) {
  const links = useFileLinks(driveId);
  const open = useCollections("open");
  const create = useCreateCollection();
  const members = useCollectionMembers();
  const removal = useRemoveFromCollection(driveId);
  const toast = useToast();
  // The batch the last add ran in ##. Ongoing (links only), as returned.
  const [added, setAdded] = useState<CollectionChange | null>(null);
  const all = links.data?.collections ?? [];
  const chips: CollectionChip[] = all.map((c) => ({
    key: String(c.id),
    name: c.name,
    to: `/collections/${c.id}${c.state === "closed" ? "?state=closed" : ""}`,
    suffix: c.state === "closed" ? " (closed)" : undefined,
    removable: removableMember(c, driveId) !== null,
  }));
  const add = async (name: string) => {
    const same = (n: string) => n.normalize("NFC").toLowerCase() === name.normalize("NFC").toLowerCase();
    const existing = (open.data ?? []).find((c) => c.kind == null && same(c.name));
    const id = existing?.id ?? (await create.mutateAsync(name)).id;
    const result = await members.mutateAsync({ id, add: [driveId] });
    setAdded(result);
    const undo = async () => {
      try {
        await members.mutateAsync({ id, remove: driveId });
      } catch (e) {
        toast({ kind: "error", text: `Could not take it out of ${visible(result.collection.name)}: ${visible(errorText(e))}` });
      }
    };
    toast({
      ...changeToast(`Added to ${result.collection.name}`, result),
      actions: [{ label: "Undo", run: () => void undo() }],
    });
  };
  const field = (
    <CollectionInput
      label="Add to collection"
      placeholder="Add to collection"
      value={chips}
      removeLabel={(name) => `Remove from ${name}`}
      disabled={refusal !== null}
      onAdd={add}
      onRemove={(chip) => {
        const c = all.find((x) => String(x.id) === chip.key);
        const member = c && removableMember(c, driveId);
        if (c && member) void removal.remove(c, member.group_id);
      }}
    />
  );
  return (
    <>
      {refusal ? (
        <span className="button-wrap" data-tip={refusal}>
          {field}
        </span>
      ) : (
        field
      )}
      {links.isError && (
        <p className="hint">Its collections could not be loaded: {visible(errorText(links.error))}</p>
      )}
      {added && <LastChange title={`Added to ${added.collection.name}: what happened in ##. Ongoing`} result={added} />}
    </>
  );
}

/** A selected folder's one action: add it to a collection (everything in it then belongs). */
export function FolderActions({ driveId, refusal }: { driveId: string; refusal: string | null }) {
  return (
    <div className="file-actions">
      <CollectionsField driveId={driveId} refusal={refusal} />
    </div>
  );
}

/** The collections block of the file view (the same in Browse, a collection and a tray):
 * the file's tray items as badges, and its collections as chips with the field that
 * adds more. ``hideItem``: a tray item that is not listed (it is the item being viewed). */
export function FileCollections({ driveId, hideItem }: { driveId: string; hideItem?: number }) {
  return (
    <section className="file-collections" aria-label="Collections of this file">
      <LinkBadges driveId={driveId} hideItem={hideItem} collections={false} />
      <CollectionsField driveId={driveId} />
    </section>
  );
}

/** "Back to inbox": run by the screen's move flow (preview → confirm → Undo);
 * ``refusal`` says why it cannot run now (e.g. "Already in the inbox"). */
export type BackToInbox = { refusal: string | null; run: () => void };

/** The selected file's own actions in Browse: Put in tray and Back to inbox (the summary,
 * the note and Add to collection are blocks of the shared file view). */
export function FileActions({ driveId, backToInbox }: { driveId: string; backToInbox?: BackToInbox }) {
  return (
    <div className="file-actions">
      <div className="actions">
        <PutInTrayMenu driveId={driveId} />
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
    </div>
  );
}
