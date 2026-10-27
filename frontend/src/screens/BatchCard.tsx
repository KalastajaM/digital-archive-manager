import { type ReactNode, useEffect, useId, useRef, useState } from "react";
import {
  errorText,
  type FileRequest,
  type InboxEntry,
  useCollectionMembers,
  useCollections,
  useCreateCollection,
} from "../api/client";
import { CollectionNamesInput } from "../components/CollectionInput";
import { pendingCollection } from "../components/CollectionPicker";
import { changeToast } from "../components/collectionText";
import { useToast } from "../components/Toasts";
import { TrashButton } from "../components/Trash";
import { FolderPicker } from "../components/FolderPicker";
import { PlanPreview } from "../components/PlanPreview";
import { TagInput } from "../components/TagInput";
import { TrayPicker } from "../components/TrayPicker";
import { type AssignKind, AssignSheet } from "../components/zones/FromFor";
import { Toolbar } from "../components/ui/Toolbar";
import { ImportantGlyph, MarkIcons, StarGlyph } from "../components/MarkIcons";
import { IconButton } from "../components/ui/IconButton";
import { TipButton } from "../components/ui/TipButton";
import { allMarked, type Markable, useBatchMark } from "../components/useBatchMark";
import { addTags, FieldChips, type Offer, offersFor, parseTags, tagOffers, UseAll } from "../components/SuggestionChip";
import { visible } from "../text";
import { type CardTrash, FilingMessage, missing, useCardKeys, useTrayChoice } from "./ReviewCard";
import { type Filing, FILING_BUSY, followUpLines, withFollowUps } from "./useFiling";

type Props = {
  entries: InboxEntry[];
  filing: Filing;
  /** Called after "Add to collection only" added these files (they stay in the inbox). */
  onAdded?: (driveIds: string[]) => void;
  /** Trash for the whole batch (the inbox owns the flow). */
  trash?: CardTrash;
  /** The New look's "Inbox N" button (the list is folded in a narrow window). */
  lead?: ReactNode;
};

const ADDING_BUSY = "Still adding the files to the collections";

/** Add files to collections by name (creating the ones that do not exist yet) without
 * filing them: the files stay in the inbox, to be filed one by one later. */
function useAddToCollections() {
  const open = useCollections("open");
  const create = useCreateCollection();
  const members = useCollectionMembers();
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inFlight = useRef(false); // a double click adds once

  const add = async (names: string[], driveIds: string[]): Promise<boolean> => {
    if (inFlight.current) return false;
    inFlight.current = true;
    setBusy(true);
    setError(null);
    try {
      for (const name of names) {
        const fold = name.toLocaleLowerCase();
        const existing = (open.data ?? []).find((c) => c.name.toLocaleLowerCase() === fold);
        const id = existing?.id ?? (await create.mutateAsync(name)).id;
        const result = await members.mutateAsync({ id, add: driveIds });
        const files = `${driveIds.length} file${driveIds.length === 1 ? "" : "s"}`;
        toast(changeToast(`Added ${files} to ${result.collection.name} (still in the inbox)`, result));
      }
      return true;
    } catch (e) {
      setError(errorText(e));
      return false;
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  };
  return { add, busy, error };
}

/** The suggested folder when every file shares one, else empty. */
function commonFolder(entries: InboxEntry[]): string {
  const folders = new Set(entries.map((e) => e.suggestion.folder ?? ""));
  return folders.size === 1 ? [...folders][0] : "";
}

/** Several files to one folder with shared tags, tray and collections; each keeps its
 * suggested name. No tray fields: each file's item is prefilled from its own scan by
 * the server (``tray_fields: {}``). No note. */
export default function BatchCard({ entries, filing, onAdded, trash, lead }: Props) {
  const ids = useId();
  const [folder, setFolder] = useState(() => commonFolder(entries));
  const [folderEdited, setFolderEdited] = useState(false);
  const [tags, setTags] = useState("");
  const trays = useTrayChoice();
  const [collections, setCollections] = useState<string[]>([]);
  const [collectionText, setCollectionText] = useState("");
  const folderRef = useRef<HTMLInputElement>(null);
  const adding = useAddToCollections();
  const [assigning, setAssigning] = useState<AssignKind | null>(null);
  // Set on the first Preview / File: from then on a missing field is shown live.
  const [tried, setTried] = useState(false);

  const selection = entries.map((e) => e.record.drive_id).join("\n");
  // A different selection refreshes the default folder while rendering, so no frame
  // shows the old selection's folder next to the new files (an effect would, once).
  const [folderFor, setFolderFor] = useState(selection);
  if (folderFor !== selection) {
    setFolderFor(selection);
    setTried(false);
    if (!folderEdited) setFolder(commonFolder(entries));
  }
  const { clearPlan } = filing;
  useEffect(() => {
    // A different selection: the old plan no longer applies (clearPlan is stable).
    clearPlan();
  }, [selection, clearPlan]);

  // The chips: each file's suggested folder (when they differ, one each) and every
  // suggested tag; the batch shares one folder and one tag list.
  const folderOffers = offersFor(
    folder,
    entries.map((e) => (e.suggestion.folder ? { value: e.suggestion.folder, source: e.suggestion.folder_source ?? "scan" } : null)),
  );
  const tagChips = tagOffers(
    tags,
    entries.flatMap((e) => e.suggestion.tags.map((t): Offer => ({ value: t, source: e.suggestion.tag_sources[t] ?? "scan" }))),
  );
  const chooseFolder = (value: string) => {
    setFolder(value);
    setFolderEdited(true);
  };
  // Files suggesting different folders: Use all cannot choose for you, so it leaves it.
  const foldersConflict = folderOffers.length > 1;
  const useAll = () => {
    if (filing.busy || adding.busy) return;
    if (folderOffers.length === 1) chooseFolder(folderOffers[0].value);
    if (tagChips.length > 0) setTags(addTags(tags, tagChips.map((o) => o.value)));
  };

  const cardIds = entries.map((e) => e.record.drive_id);
  // A missing folder is shown on the Folder field; other problems are the card's message.
  const folderProblem = folder.trim() ? null : "Choose a folder.";
  const otherProblem =
    entries.map((e) => missing(e.suggestion.name, "x")).find(Boolean) ?? pendingCollection(collectionText);
  const problem = folderProblem ?? otherProblem;
  const current: FileRequest[] | null = problem
    ? null
    : entries.map((e) =>
        withFollowUps(
          { drive_id: e.record.drive_id, name: e.suggestion.name, folder, tags: parseTags(tags) },
          {
            // A file already in the tray gets no second item (the server would refuse it).
            tray: trays.tray && !e.open_trays.includes(trays.tray.id) ? trays.tray.id : null,
            trayFields: {},
            collections,
            note: "",
          },
        ),
      );
  filing.form.current = current; // stale previews are dropped against this
  const plan = filing.planFor(current);

  const requests = (): FileRequest[] | null => {
    setTried(true);
    if (current === null) {
      filing.dismissMessage(); // the live problem says what is wrong
      if (folderProblem) folderRef.current?.focus();
    }
    return current;
  };
  const collectionProblem = pendingCollection(collectionText);
  const addOnly = async () => {
    if (collections.length === 0 || collectionProblem || filing.busy) return;
    if (await adding.add(collections, cardIds)) {
      setCollections([]);
      onAdded?.(cardIds);
    }
  };
  const preview = () => {
    const r = requests();
    if (r) filing.preview(r);
  };
  const fileIt = () => {
    const r = requests();
    if (r) filing.fileIt(r, true);
  };
  useCardKeys({ preview, fileIt }, { folder: folderRef });

  const count = `${entries.length} file${entries.length === 1 ? "" : "s"}`;
  const tray = trays.tray;
  const alreadyIn = tray ? entries.filter((e) => e.open_trays.includes(tray.id)).length : 0;
  // ★ and ! for the selection now, before filing (marks follow the file when it moves).
  const marks = useBatchMark();
  const markable: Markable[] = entries.map((e) => ({
    drive_id: e.record.drive_id,
    name: e.record.name ?? e.record.path,
    marks: e.record.marks,
  }));
  const starAll = allMarked(markable, "star");
  const importantAll = allMarked(markable, "important");
  return (
    <article className="batch-card" aria-label={`Batch of ${count}`}>
      <Toolbar
        lead={lead}
        title={`${count} selected`}
        subtitle="each keeps its suggested name"
        actions={
          <>
            <IconButton
              icon={<StarGlyph size={16} filled={starAll} />}
              label={starAll ? "Remove the star" : "Star"}
              pressed={starAll}
              disabled={marks.busy}
              onClick={() => void marks.run("star", markable)}
            />
            <IconButton
              icon={<ImportantGlyph large />}
              label={importantAll ? "Unmark Important" : "Mark Important"}
              pressed={importantAll}
              disabled={marks.busy}
              onClick={() => void marks.run("important", markable)}
            />
            {trash && (
              <TrashButton count={entries.length} disabled={filing.busy || adding.busy || trash.busy} onClick={trash.run} />
            )}
            <TipButton
              className="tip-end"
              tip="Show exactly what will move, before anything changes ↩"
              onClick={preview}
              disabled={filing.busy}
              disabledReason={FILING_BUSY}
            >
              Preview
            </TipButton>
            <TipButton
              className="primary tip-end"
              tip="Move them to the folder with their new names ⌘↩"
              onClick={fileIt}
              disabled={filing.busy || adding.busy}
              disabledReason={filing.busy ? FILING_BUSY : ADDING_BUSY}
            >
              File {count}
            </TipButton>
          </>
        }
      />
      <div className="batch-body">
        <ul className="batch-names" aria-label="Files">
          {entries.map((e) => (
            <li key={e.record.drive_id}>
              <span className="batch-from">
                {visible(e.record.name ?? e.record.path)}
                <MarkIcons marks={e.record.marks} driveId={e.record.drive_id} path={e.record.path} />
              </span>
              <span className="batch-arrow" aria-hidden="true">
                →
              </span>
              <span className="batch-to">{visible(e.suggestion.name)}</span>
            </li>
          ))}
        </ul>
        <div className="inspector batch-form">
          <FilingMessage filing={filing} ids={cardIds} problem={tried && !folderProblem ? otherProblem : null} />
          <UseAll
            count={(folderOffers.length === 1 ? 1 : 0) + tagChips.length}
            disabled={filing.busy || adding.busy}
            onUse={useAll}
          />
          <div className="field">
            <FolderPicker
              ref={folderRef}
              label="Folder"
              value={folder}
              onChange={chooseFolder}
              error={tried ? folderProblem : null}
            />
            <FieldChips
              field="Folder"
              offers={folderOffers}
              disabled={filing.busy || adding.busy}
              onUse={(o) => chooseFolder(o.value)}
            />
            {foldersConflict && (
              <p className="hint">The files suggest different folders: pick one. Use all leaves the folder as it is.</p>
            )}
          </div>
          <div className="field">
            <label htmlFor={`${ids}-tags`}>Tags</label>
            <TagInput
              id={`${ids}-tags`}
              value={parseTags(tags)}
              onChange={(next) => setTags(next.join(", "))}
              placeholder="Add a tag (added to every file)"
              disabled={filing.busy || adding.busy}
              passCmdEnter
            />
            <FieldChips field="tag" offers={tagChips} disabled={filing.busy || adding.busy} onUse={(o) => setTags(addTags(tags, [o.value]))} />
          </div>
          <div className="field from-for-batch" role="group" aria-label="Who">
            <span className="field-label">Who</span>
            <div className="actions">
              <button type="button" disabled={filing.busy || adding.busy} onClick={() => setAssigning("sender")}>
                From…
              </button>
              <button type="button" disabled={filing.busy || adding.busy} onClick={() => setAssigning("person")}>
                For…
              </button>
            </div>
          </div>
          <hr />
          <TrayPicker
            trays={trays.list}
            value={tray?.id ?? null}
            onChange={trays.setTrayId}
            problem={trays.problem}
          />
          {tray && <p className="hint">Each file’s item is filled in from its own scan.</p>}
          {tray && alreadyIn > 0 && (
            <p className="notice">
              {alreadyIn === 1
                ? `1 file is already in ${visible(tray.name)}: no new item for it.`
                : `${alreadyIn} files are already in ${visible(tray.name)}: no new item for them.`}
            </p>
          )}
          <CollectionNamesInput
            value={collections}
            onChange={setCollections}
            text={collectionText}
            onTextChange={setCollectionText}
          />
          <div className="actions">
            <button
              type="button"
              onClick={() => void addOnly()}
              disabled={collections.length === 0 || !!collectionProblem || filing.busy || adding.busy}
              title="Add the files to the collections above and leave them in the inbox, to file them one by one later"
            >
              Add to collection only
            </button>
          </div>
          {collections.length === 0 && (
            <p className="hint">
              Collection only? Choose it, then “Add to collection only”. No folder needed.
            </p>
          )}
          {adding.busy && (
            <p className="hint" role="status">
              Adding…
            </p>
          )}
          {adding.error && (
            <p className="error" role="alert">
              {visible(adding.error)}
            </p>
          )}
          {assigning && <AssignSheet kind={assigning} driveIds={cardIds} onClose={() => setAssigning(null)} />}
          {plan && (
            <div className="inbox-plan">
              <PlanPreview
                ops={plan.ops}
                tags={parseTags(tags)}
                followUps={followUpLines(plan.requests, trays.list)}
                onClose={filing.clearPlan}
                action={
                  <button type="button" className="primary" onClick={fileIt} disabled={filing.busy || adding.busy}>
                    File {count}
                  </button>
                }
              />
            </div>
          )}
        </div>
      </div>
    </article>
  );
}
