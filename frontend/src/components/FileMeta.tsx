/** The inline details of a file already in the archive (stars spec §7, replacing the
 * "Edit details…" dialog): the name (click it to rename), the folder with Move to…,
 * the ★ / ! toggles and Ask AI for the screen's action row, and the tags as removable chips.
 *
 * Tags are written at once (nothing is previewed or journaled). A new name or folder
 * goes through the move flow: preview → confirm → apply → Undo, with exactly the
 * request that was previewed (the snapshot rule). A file that cannot be renamed or
 * moved (a link, a folder, one in ##. To Delete) gets the same controls disabled, the
 * reason as their tooltip. */
import { FolderInput, Sparkles } from "lucide-react";
import { type FormEvent, type KeyboardEvent, type ReactNode, useEffect, useRef, useState } from "react";
import { errorText, LOCKED_REASON, type Mark, useFileDetail, useFileLock, usePutFileTags } from "../api/client";
import { visible } from "../text";
import { useAIState } from "./ai/useAI";
import { type FilingAI, useFilingAI } from "./ai/useFilingAI";
import { LockControl } from "./LockControl";
import { MarkToggles } from "./MarkToggles";
import { MoveToSheet, sourceRefusal, useMoveFlow } from "./MoveTo";
import { Breakable } from "./PlanPreview";
import { AI_SOURCE, aiNote, FieldChips, type Offer, offersFor, tagOffers } from "./SuggestionChip";
import { TagInput } from "./TagInput";
import { useBlockToastActions } from "./Toasts";
import { ClickToEdit } from "./ui/ClickToEdit";
import { IconButton } from "./ui/IconButton";
import { baseName } from "../paths";

export type MetaFile = {
  drive_id: string;
  path: string | null;
  /** The name as listed, when the caller has it (else the path's last part). */
  name?: string | null;
  is_dir?: boolean;
  is_link?: boolean;
  /** For the ★ / ! toggles; else they read the file's record. */
  marks?: readonly Mark[];
};

const folderOf = (path: string) => (path.includes("/") ? path.slice(0, path.lastIndexOf("/")) : "");
const fold = (s: string) => s.normalize("NFC").toLocaleLowerCase();
const sameTags = (a: string[], b: string[]) => JSON.stringify([...a].sort()) === JSON.stringify([...b].sort());
/** "scan.pdf" → ["scan", ".pdf"]; a name with no extension (or a dotfile) keeps it all. */
const splitName = (name: string): [string, string] => {
  const dot = name.lastIndexOf(".");
  return dot > 0 ? [name.slice(0, dot), name.slice(dot)] : [name, ""];
};

/** Why renaming, moving and tagging are not offered for this entry (null: they are). */
export function fileEditRefusal(entry: Pick<MetaFile, "path" | "is_dir" | "is_link">): string | null {
  if (!entry.path) return "The file is not in the index";
  if (entry.is_dir) return "Folders have no details to edit";
  if (entry.is_link) return "Links cannot be renamed or moved";
  return sourceRefusal(entry.path);
}

export type MetaParts = {
  /** Name and folder rows with their buttons. */
  header: ReactNode;
  /** The ★ and ! toggles, for the preview's toolbar. */
  marks: ReactNode;
  /** The Ask AI button, for the screen's action row (its answer shows as chips in ``header``). */
  ask: ReactNode;
  /** The tags field (and the AI's tag suggestions). */
  tags: ReactNode;
};

/** The state of one file's inline details; render the ``parts`` where they belong (the
 * confirm and the folder picker are rendered by this component itself). Remounts for a
 * different file (``key`` it by its id). ``disabled``: another change is under way. */
export function FileMeta({
  file,
  disabled = false,
  ai: given,
  children,
}: {
  file: MetaFile;
  disabled?: boolean;
  /** The screen's own "Ask AI" (its header button): this file's answer shows here as chips,
   * and the screen renders the "What will be sent" sheet. Else this component has its own. */
  ai?: FilingAI;
  children: (parts: MetaParts) => ReactNode;
}) {
  const id = file.drive_id;
  const path = file.path ?? "";
  const name = file.name ?? baseName(path);
  const refusal = fileEditRefusal(file);
  // A locked file's name and folder cannot change (its tags, marks and notes still can)
  const lock = useFileLock(id, file.marks, file.path);
  const changeRefusal = refusal ?? (lock.blocked ? LOCKED_REASON : null);
  const [editing, setEditing] = useState(false);
  const [picking, setPicking] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const move = useMoveFlow(
    () => setEditing(false), // applied: the new name is the file's
    undefined,
    setProblem, // a refused preview is said here, the typed name kept
  );
  useBlockToastActions(move.confirming || picking);
  const busy = disabled || move.busy || move.confirming;

  const aiState = useAIState();
  const own = useFilingAI();
  const ai = given ?? own;
  const answer = aiState.on ? ai.answerFor(id) : null;
  const aiOffer = (value: string | null | undefined, confidence?: number): Offer | null =>
    value ? { value, source: AI_SOURCE, note: aiNote(confidence, answer?.reason) } : null;
  const nameOffers = offersFor(name, [aiOffer(answer?.name, answer?.confidence.name)]);
  const folderOffers = offersFor(folderOf(path), [aiOffer(answer?.folder, answer?.confidence.folder)]);

  const [draft, setDraft] = useState("");
  const [ext, setExt] = useState("");
  const startRename = (suggested?: string) => {
    if (changeRefusal || busy) return;
    const [stem, e] = splitName(name);
    // the extension stays: a suggestion that carries it is taken without it
    setDraft(suggested === undefined ? stem : suggested.endsWith(e) ? suggested.slice(0, suggested.length - e.length) : suggested);
    setExt(e);
    setProblem(null);
    setEditing(true);
  };
  const submitRename = (e: FormEvent) => {
    e.preventDefault();
    if (busy) return;
    const stem = draft.trim();
    if (!stem) return setProblem("Enter a name.");
    const next = stem + ext;
    if (next === name) return setEditing(false);
    setProblem(null);
    move.start({ ids: [id], folder: folderOf(path), name: next });
  };
  const renameKeys = (e: KeyboardEvent) => {
    e.stopPropagation(); // page shortcuts never see keys typed here
    if (e.key === "Escape") {
      setEditing(false);
      setProblem(null);
    }
  };
  const renameRef = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (editing) renameRef.current?.select();
  }, [editing]);

  const header = (
    <header className="file-meta-head">
      <div className="file-meta-title">
        {editing ? (
          <form className="file-meta-rename" onSubmit={submitRename}>
            <input
              ref={renameRef}
              aria-label="File name"
              value={draft}
              spellCheck={false}
              disabled={busy}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={renameKeys}
              autoFocus
            />
            {ext && <span className="file-meta-ext">{visible(ext)}</span>}
          </form>
        ) : (
          <h2 aria-label={visible(name)}>
            <ClickToEdit
              label={`Rename ${visible(name)}`}
              tip={changeRefusal ?? "Click to rename"}
              disabled={changeRefusal !== null || busy}
              onClick={() => startRename()}
            >
              {visible(name)}
            </ClickToEdit>
          </h2>
        )}
        {refusal === null && <LockControl driveId={id} marks={file.marks} path={file.path} />}
      </div>
      <p className="current-path">
        <code>
          <Breakable text={path} />
        </code>
        <IconButton
          icon={<FolderInput />}
          label="Move file to…"
          disabled={changeRefusal !== null || busy}
          disabledReason={changeRefusal ?? undefined}
          onClick={() => setPicking(true)}
        />
      </p>
      {problem && (
        <p className="error" role="alert">
          {visible(problem)}
        </p>
      )}
      <FieldChips field="Name" offers={nameOffers} disabled={changeRefusal !== null || busy} onUse={(o) => startRename(o.value)} />
      <FieldChips
        field="Folder"
        offers={folderOffers}
        disabled={changeRefusal !== null || busy}
        onUse={(o) => {
          setProblem(null);
          move.start({ ids: [id], folder: o.value });
        }}
      />
    </header>
  );

  const ask = (
    <IconButton
      icon={<Sparkles />}
      label="Ask AI"
      tip="Ask AI to suggest a name, folder and tags"
      disabled={refusal !== null || busy || ai.busy || !aiState.on}
      disabledReason={refusal ?? (aiState.off ? "AI is off: Activity → AI turns it on" : undefined)}
      onClick={() => ai.ask(id)}
    />
  );
  const marks = <MarkToggles driveId={id} name={name} marks={file.marks} path={file.path} />;
  const tags = (
    <TagsField
      driveId={id}
      name={name}
      reason={refusal}
      busy={disabled}
      offers={(answer?.tags ?? []).map((t) => aiOffer(t, answer?.confidence.tags) as Offer)}
    />
  );

  return (
    <>
      {children({ header, marks, ask, tags })}
      {own.sheet}
      {move.view}
      {picking && (
        <MoveToSheet
          names={[name]}
          initial={folderOf(path)}
          onCancel={() => setPicking(false)}
          onChoose={(dest) => {
            setPicking(false);
            setProblem(null);
            move.start({ ids: [id], folder: dest });
          }}
        />
      )}
    </>
  );
}

/** A file's tags as a tag input; each change is written at once. */
function TagsField({
  driveId,
  name,
  reason,
  busy,
  offers,
}: {
  driveId: string;
  name: string;
  /** Why tags cannot be changed (null: they can). */
  reason: string | null;
  busy: boolean;
  offers: Offer[];
}) {
  const detail = useFileDetail(driveId);
  const put = usePutFileTags();
  const [problem, setProblem] = useState<string | null>(null);
  // what was last written, until the file's record shows it
  const [pending, setPending] = useState<string[] | null>(null);
  const saved = detail.data?.tags;
  const tags = pending ?? saved ?? [];
  const latest = useRef(tags);
  latest.current = tags;
  useEffect(() => {
    if (pending && saved && sameTags(saved, pending)) setPending(null);
  }, [saved, pending]);

  const write = async (next: string[]) => {
    const before = latest.current;
    latest.current = next;
    setPending(next);
    setProblem(null);
    try {
      await put.mutateAsync({ driveId, tags: next });
    } catch (e) {
      latest.current = before;
      setPending(null);
      setProblem(`Tags not saved: ${errorText(e)}`);
    }
  };
  const add = (raw: string[]) => {
    const have = new Set(latest.current.map(fold));
    const added: string[] = [];
    for (const t of raw.map((x) => x.trim()).filter(Boolean)) {
      if (!have.has(fold(t))) {
        have.add(fold(t));
        added.push(t);
      }
    }
    if (added.length > 0) void write([...latest.current, ...added]);
  };
  const off = reason !== null || busy || saved === undefined;
  const chips = tagOffers(tags.join(", "), offers);
  return (
    <section className="file-tags" aria-label="Tags" title={reason ?? undefined}>
      <TagInput value={tags} onChange={(next) => void write(next)} label={`Add a tag to ${visible(name)}`} disabled={off} disabledReason={reason} />
      {problem && (
        <p className="error" role="alert">
          {visible(problem)}
        </p>
      )}
      <FieldChips field="tag" offers={chips} disabled={off} onUse={(o) => add([o.value])} />
    </section>
  );
}
