import { PanelRightClose, PanelRightOpen, Sparkles } from "lucide-react";
import { IconButton } from "../components/ui/IconButton";
import { TipButton } from "../components/ui/TipButton";
import { type ReactNode, type RefObject, useId, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  type CodeHit,
  errorText,
  type FieldDef,
  type FileRequest,
  type FilingSuggestion,
  type InboxEntry,
  type TrayDef,
  useFileLinks,
  useFilingCodes,
  useRules,
  useTrays,
} from "../api/client";
import { AIRejected } from "../components/ai/AIBadge";
import { AIHint, useAISend, useAIState } from "../components/ai/useAI";
import { CollectionPicker, pendingCollection } from "../components/CollectionPicker";
import { DetectedFields } from "../components/DetectedFields";
import { folderOf } from "../components/FileDetails";
import { FilePreview } from "../components/FilePreview";
import { editText } from "../components/FieldInput";
import { FolderPicker } from "../components/FolderPicker";
import { NoteEditor } from "../components/NoteEditor";
import { TagInput } from "../components/TagInput";
import { PlanPreview } from "../components/PlanPreview";
import {
  blankValues,
  prefillValues,
  TrayFields,
  TrayPicker,
  type TrayValues,
} from "../components/TrayPicker";
import { Toolbar } from "../components/ui/Toolbar";
import { fieldWord } from "../format";
import { dialogOpen, isCmdEnter, isShortcut, OWN_ENTER, useKeydown } from "../keyboard";
import { visible } from "../text";
import { LinkBadges } from "./FileActions";
import { type Filing, FILING_BUSY, followUpLines, withFollowUps } from "./useFiling";
import { MarkToggles } from "../components/MarkToggles";
import { TrashButton } from "../components/Trash";
import {
  addTags,
  AI_SOURCE,
  aiNote,
  type CodeLabel,
  FieldChips,
  type Offer,
  offersFor,
  parseTags,
  SuggestionChip,
  tagOffers,
  UseAll,
} from "../components/SuggestionChip";

/** The first missing field and what to tell the user, or null. The API validates
 * everything else. */
export function missingField(name: string, folder: string): { field: "name" | "folder"; message: string } | null {
  if (!name.trim()) return { field: "name", message: "Enter a name." };
  if (!folder.trim()) return { field: "folder", message: "Choose a folder." };
  return null;
}

/** Missing-field message, or null. */
export function missing(name: string, folder: string): string | null {
  return missingField(name, folder)?.message ?? null;
}

/** Card keys: Enter = preview, Cmd+Enter = file it (also in fields), f/n focus fields. */
export function useCardKeys(
  actions: { preview: () => void; fileIt: () => void },
  fields: { folder: RefObject<HTMLInputElement | null>; name?: RefObject<HTMLInputElement | null> },
) {
  useKeydown((e) => {
    if (isCmdEnter(e)) {
      if (dialogOpen()) return; // the dialog's own Cmd+Enter confirms
      e.preventDefault();
      actions.fileIt();
      return;
    }
    if (!isShortcut(e)) return;
    const target = e.target as HTMLElement;
    if (e.key === "Enter") {
      // Enter keeps its own meaning on buttons, links etc., except on the inbox list.
      if (target.closest(OWN_ENTER) && !target.closest("[data-inbox-entry]")) return;
      e.preventDefault();
      actions.preview();
    } else if (e.key === "f" && fields.folder.current) {
      e.preventDefault();
      fields.folder.current.focus();
    } else if (e.key === "n" && fields.name?.current) {
      e.preventDefault();
      fields.name.current.focus();
    }
  });
}

/** The card's own missing-field problem (shown live once the user tried to preview or
 * file, so it disappears as soon as the field is filled in), else the filing error or
 * notice for the files on this card, if any. */
export function FilingMessage({ filing, ids, problem }: { filing: Filing; ids: string[]; problem?: string | null }) {
  if (problem) {
    return (
      <p className="error" role="alert">
        {visible(problem)}
      </p>
    );
  }
  const message = filing.messageFor(ids);
  if (!message) return null;
  return message.kind === "error" ? (
    <p className="error" role="alert">
      {visible(message.text)}
    </p>
  ) : (
    <p className="notice" role="status">
      {visible(message.text)}
    </p>
  );
}

/** The trays (in order) and the tray picked on a card; a tray that vanished from the
 * list on a reload counts as none picked. */
export function useTrayChoice(initialId: string | null = null) {
  const trays = useTrays();
  const list: TrayDef[] = trays.data?.trays ?? [];
  // Starts at Nothing (or the tray a filing code picked). The review card is remounted for every entry, so a choice is
  // never carried over to another file; the batch card keeps its choice while the
  // selection changes (it applies to the whole batch).
  const [trayId, setTrayId] = useState<string | null>(initialId);
  const tray = list.find((t) => t.id === trayId) ?? null;
  const problem = trays.isError ? errorText(trays.error) : null;
  return { list, tray, setTrayId, problem };
}

/** How each code of a file was found, for a chip's "code:P" source: its inbox folder's name
 * ("from folder To pay"), the pen mark or the sticker. */
export function useCodeLabel(hits: CodeHit[]): CodeLabel {
  const codes = useFilingCodes();
  return (code) => {
    const hit = hits.find((h) => h.code === code);
    if (!hit) return `code \`${code}\``;
    if (hit.via === "pen") return `from pen mark \`${code}\``;
    if (hit.via === "qr") return `from sticker \`${code}\``;
    const folder = codes.data?.codes.find((c) => c.code === code)?.inbox_folder;
    return folder ? `from folder ${folder}` : `code \`${code}\``;
  };
}

/** In place of the tray fields when the file already has an open item in that tray:
 * the server would refuse a second one, so none is sent, and the link opens the item. */
function AlreadyIn({ tray, driveId }: { tray: TrayDef; driveId: string }) {
  const links = useFileLinks(driveId);
  const item = links.data?.items.find((i) => i.tray_id === tray.id && i.state === "open");
  const to = `/trays/${encodeURIComponent(tray.id)}${item ? `?item=${item.id}` : ""}`;
  return (
    <p className="notice already-in">
      Already in {visible(tray.name)} — <Link to={to}>open it to change it</Link>
    </p>
  );
}

/** An AI tray field value as the form shows it (the API's text, like the scan's). */
function shownValue(def: FieldDef, value: string): string | boolean {
  if (def.type === "checkbox") return /^(true|yes|1)$/i.test(value.trim());
  return editText(def, value) ?? value;
}

const chipText = (value: string | boolean) => (typeof value === "boolean" ? (value ? "yes" : "no") : value);

/** suggest-filing's summary, offered as the note (never filled in unasked). */
function AISummary({ summary, onUse }: { summary: string; onUse: () => void }) {
  const headingId = useId();
  return (
    <section className="ai-summary" aria-labelledby={headingId}>
      <h3 id={headingId}>AI summary</h3>
      <p>{visible(summary)}</p>
      <button type="button" onClick={onUse}>
        Use as note
      </button>
    </section>
  );
}

/** The tick boxes a sticker has but that could not be read ("star", "important"). */
export const unclearBoxes = (s: InboxEntry["suggestion"]): string[] =>
  s.marks_unclear ? (["star", "important"] as const).filter((k) => s[k] === null) : [];

/** What a QR sticker's tick boxes ask for once the file is filed (sent with the filing):
 * shown only when a sticker set something. A box for a mark the file already has is
 * not offered. */
function StickerMarks(props: {
  star: boolean;
  important: boolean;
  hasStar: boolean;
  hasImportant: boolean;
  unclear: string[];
  onStar: (on: boolean) => void;
  onImportant: (on: boolean) => void;
}) {
  const unclear = props.unclear.filter((k) => (k === "star" ? !props.hasStar : !props.hasImportant));
  return (
    <div className="field sticker-marks" role="group" aria-label="From the sticker">
      <span className="sticker-marks-title">From the sticker</span>
      {props.hasStar ? (
        <span className="hint">already starred</span>
      ) : (
        <label className="check">
          <input type="checkbox" checked={props.star} onChange={(e) => props.onStar(e.target.checked)} />
          Star when filed
        </label>
      )}
      {props.hasImportant ? (
        <span className="hint">already Important</span>
      ) : (
        <label className="check">
          <input type="checkbox" checked={props.important} onChange={(e) => props.onImportant(e.target.checked)} />
          Mark Important when filed
        </label>
      )}
      {unclear.length > 0 && <p className="notice">Tick box unclear: check {unclear.join(" and ")}</p>}
    </div>
  );
}

/** The card's Trash (bin) button: the inbox owns the flow. */
export type CardTrash = { run: () => void; busy: boolean };

type Props = { entry: InboxEntry; filing: Filing; trash?: CardTrash };

/** One inbox file: a toolbar with its name and the actions, the preview, and the
 * editable proposal as a narrow inspector beside it. */
export default function ReviewCard({ entry, filing, trash }: Props) {
  const ids = useId();
  const [name, setName] = useState(entry.suggestion.name);
  const [folder, setFolder] = useState(entry.suggestion.folder ?? "");
  const [tags, setTags] = useState(entry.suggestion.tags.join(", "));
  // A file with a filing code starts with the suggested tray, as File N marked files it (a
  // code's tray, none for "file as suggested", else the rules' tray); on a file without a
  // code a rule's or the heuristic's tray guess is not applied by itself.
  const coded = entry.suggestion.codes.length > 0 || (entry.suggestion.tray_source?.startsWith("code:") ?? false);
  const trays = useTrayChoice(coded ? entry.suggestion.tray : null);
  const tray = trays.tray;
  const codeLabel = useCodeLabel(entry.suggestion.codes);
  // Per tray, the fields the user edited (switching trays back and forth keeps them).
  const [edits, setEdits] = useState<Record<string, TrayValues>>({});
  const [collections, setCollections] = useState<string[]>(() => [...entry.suggestion.collections]);
  const [collectionText, setCollectionText] = useState("");
  const [note, setNote] = useState("");
  // A QR sticker's tick boxes preselect these (an unclear box leaves it off and says so);
  // a mark the file already has is not sent again.
  const [star, setStar] = useState(entry.suggestion.star === true);
  const [important, setImportant] = useState(entry.suggestion.important === true);
  // Set on the first Preview / File it: from then on a missing field is shown live.
  const [tried, setTried] = useState(false);
  // Narrow windows hide the preview pane (the form matters most); this shows it again.
  const [showPreview, setShowPreview] = useState(false);
  const nameRef = useRef<HTMLInputElement>(null);
  const folderRef = useRef<HTMLInputElement>(null);

  // What the fields show is what is sent: the scan's values the user left as they are
  // included (the server would prefill only fields left out), an emptied one as "".
  const scan = tray ? prefillValues(tray, entry.prefill) : {};
  const edited = tray ? (edits[tray.id] ?? {}) : {};
  const trayFields: TrayValues = tray ? { ...blankValues(tray), ...scan, ...edited } : {};
  // A tray the file already has an open item in: shown as such, and no follow-up sent.
  const alreadyIn = tray !== null && entry.open_trays.includes(tray.id);
  const found = new Set(Object.keys(scan).filter((n) => !(n in edited)));
  // "Ask AI": the answer becomes chips (spec §7), never fills the form by itself;
  // filing still goes through Preview / File it with exactly what the form shows.
  const aiState = useAIState();
  const [heldAnswer, setAnswer] = useState<FilingSuggestion | null>(null);
  // AI switched off: its chips, notes and summary are not shown (switched on again,
  // they are back)
  const answer = aiState.on ? heldAnswer : null;
  const ai = useAISend<FilingSuggestion>("suggest-filing", setAnswer);
  const editField = (field: string, value: string | boolean) => {
    if (!tray) return;
    setEdits((old) => ({ ...old, [tray.id]: { ...old[tray.id], [field]: value } }));
  };

  // The chips: the AI's answer first, then the rules' and the scan's (which pre-fill
  // the empty fields of an inbox file, so they show up as a chip once edited away).
  const rules = entry.suggestion;
  const aiOffer = (value: string | null | undefined, confidence?: number): Offer | null =>
    value ? { value, source: AI_SOURCE, note: aiNote(confidence, answer?.reason) } : null;
  // A rule whose suggestions were corrected recently says so on its chips (a failed or
  // missing rules load just means no note).
  const flaggedRules = new Set((useRules().data?.rules ?? []).filter((r) => r.stats.flagged).map((r) => r.id));
  const flagged = (o: Offer): Offer => {
    if (!o.source.split(" · ").some((s) => s.startsWith("rule:") && flaggedRules.has(s.slice(5)))) return o;
    const note = "this rule was corrected recently";
    return { ...o, note: o.note ? `${o.note} · ${note}` : note };
  };
  const nameOffers = offersFor(name, [
    aiOffer(answer?.name, answer?.confidence.name),
    { value: rules.name, source: rules.name_source },
  ]).map(flagged);
  const folderOffers = offersFor(folder, [
    aiOffer(answer?.folder, answer?.confidence.folder),
    rules.folder ? { value: rules.folder, source: rules.folder_source ?? "scan" } : null,
  ]).map(flagged);
  const tagChips = tagOffers(tags, [
    ...(answer?.tags ?? []).map((t) => aiOffer(t, answer?.confidence.tags) as Offer),
    ...rules.tags.map((t) => ({ value: t, source: rules.tag_sources[t] ?? "scan" })),
  ]).map(flagged);
  const aiTray = answer?.tray ? (trays.list.find((t) => t.id === answer.tray) ?? null) : null;
  const trayOffer = aiTray && aiTray.id !== tray?.id ? aiTray : null;
  /** The AI's values for ``t``'s fields that differ from what the form would show. */
  const aiTrayFields = (t: TrayDef): TrayValues => {
    if (!answer || answer.tray !== t.id) return {};
    const shownNow = { ...blankValues(t), ...prefillValues(t, entry.prefill), ...edits[t.id] };
    const out: TrayValues = {};
    for (const [field, value] of Object.entries(answer.tray_fields)) {
      const def = t.fields?.[field];
      if (!def) continue;
      const shown = shownValue(def, value);
      if (shown !== shownNow[field]) out[field] = shown;
    }
    return out;
  };
  const fieldOffers = tray && !alreadyIn ? aiTrayFields(tray) : {};
  const trayChips: Record<string, ReactNode> = {};
  for (const [field, value] of Object.entries(fieldOffers)) {
    trayChips[field] = (
      <SuggestionChip
        field={fieldWord(field)}
        offer={{ value: chipText(value), source: AI_SOURCE, note: aiNote(answer?.confidence.tray_fields, answer?.reason) }}
        disabled={filing.busy}
        onUse={() => editField(field, value)}
      />
    );
  }
  // What Use all does with the AI's tray: picks it, and fills in its fields (none for
  // a tray the file already has an open item in: they would not be sent).
  const allTray = trayOffer ?? (aiTray && aiTray.id === tray?.id ? aiTray : null);
  const allFields = allTray && !entry.open_trays.includes(allTray.id) ? aiTrayFields(allTray) : {};
  const chipCount =
    Math.min(1, nameOffers.length) +
    Math.min(1, folderOffers.length) +
    tagChips.length +
    (trayOffer ? 1 : 0) +
    Object.keys(allFields).length;
  /** Every chip at once: the first suggestion of each field, every tag, and the AI's
   * tray with its fields. */
  const useAll = () => {
    if (filing.busy) return;
    if (nameOffers[0]) setName(nameOffers[0].value);
    if (folderOffers[0]) setFolder(folderOffers[0].value);
    if (tagChips.length > 0) setTags(addTags(tags, tagChips.map((o) => o.value)));
    if (allTray) {
      trays.setTrayId(allTray.id);
      if (Object.keys(allFields).length > 0)
        setEdits((old) => ({ ...old, [allTray.id]: { ...old[allTray.id], ...allFields } }));
    }
  };
  const rejected = (key: string, field: string) => {
    const reason = answer?.rejected[key];
    return reason ? <AIRejected field={field} reason={reason} /> : null;
  };
  const rejectedTrayFields = Object.entries(answer?.rejected ?? {}).filter(([k]) => k.startsWith("tray_fields."));
  const useSummaryAsNote = () => {
    const summary = answer?.summary.trim();
    if (!summary) return;
    setNote((old) => (old.trim() ? `${old.trimEnd()}\n\n${summary}` : summary));
  };

  const fromSticker =
    entry.suggestion.star === true || entry.suggestion.important === true || entry.suggestion.marks_unclear;
  const hasStar = entry.record.marks.includes("starred");
  const hasImportant = entry.record.marks.includes("important");
  const fieldProblem = missingField(name, folder);
  // A missing name or folder is shown on its field; the rest (a half-typed collection)
  // is the card's own message.
  const otherProblem = pendingCollection(collectionText);
  const nameInvalid = tried && fieldProblem?.field === "name";
  const problem = fieldProblem?.message ?? otherProblem;
  const current: FileRequest[] | null = problem
    ? null
    : [
        withFollowUps(
          { drive_id: entry.record.drive_id, name, folder, tags: parseTags(tags) },
          {
            tray: alreadyIn ? null : (tray?.id ?? null),
            trayFields,
            collections,
            note,
            star: star && !hasStar,
            important: important && !hasImportant,
          },
        ),
      ];
  filing.form.current = current; // stale previews are dropped against this
  const plan = filing.planFor(current);

  const requests = (): FileRequest[] | null => {
    setTried(true);
    if (current === null) {
      filing.dismissMessage(); // the live problem says what is wrong
      if (fieldProblem) (fieldProblem.field === "name" ? nameRef : folderRef).current?.focus();
    }
    return current;
  };
  const preview = () => {
    const r = requests();
    if (r) filing.preview(r);
  };
  const fileIt = () => {
    const r = requests();
    if (r) void filing.fileIt(r);
  };
  useCardKeys({ preview, fileIt }, { folder: folderRef, name: nameRef });

  const fileName = entry.record.name ?? entry.record.path;
  return (
    <article className="review-card" aria-label={`Review ${fileName}`}>
      <Toolbar
        title={visible(fileName)}
        subtitle={visible(folderOf(entry.record.path))}
        actions={
          <>
            {/* the app's one order: view, marks, Ask AI, the bin last; then this card's own steps */}
            <IconButton
              className="preview-toggle"
              icon={showPreview ? <PanelRightClose /> : <PanelRightOpen />}
              label={showPreview ? "Hide preview" : "Show preview"}
              pressed={showPreview}
              onClick={() => setShowPreview((v) => !v)}
            />
            <MarkToggles driveId={entry.record.drive_id} name={fileName} marks={entry.record.marks} />
            {aiState.on && (
              <IconButton
                icon={<Sparkles />}
                label="Ask AI"
                tip="Ask AI to suggest a name, folder and tags"
                disabled={filing.busy || ai.busy}
                onClick={() => ai.ask({ drive_id: entry.record.drive_id })}
              />
            )}
            {trash && <TrashButton disabled={filing.busy || trash.busy} onClick={trash.run} />}
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
              tip="Move it to the folder with the new name ⌘↩"
              onClick={fileIt}
              disabled={filing.busy}
              disabledReason={FILING_BUSY}
            >
              File it
            </TipButton>
          </>
        }
      />
      <div className={showPreview ? "review-body show-preview" : "review-body"}>
        <div className="preview-pane preview-fill">
          <FilePreview file={entry.record} />
        </div>
        <div className="proposal inspector">
          <FilingMessage filing={filing} ids={[entry.record.drive_id]} problem={tried && !fieldProblem ? otherProblem : null} />
          {entry.suggestion.conflict && (
            <p className="notice" role="status">
              These filing codes disagree; pick the values here.
            </p>
          )}
          <AIHint what="for filing suggestions" />
          {ai.sheet}
          <LinkBadges driveId={entry.record.drive_id} />
          <UseAll count={chipCount} disabled={filing.busy} onUse={useAll} />
          <div className="field">
            <label htmlFor={`${ids}-name`}>Name</label>
            <input
              ref={nameRef}
              id={`${ids}-name`}
              className={nameInvalid ? "invalid" : undefined}
              aria-invalid={nameInvalid ? true : undefined}
              aria-describedby={nameInvalid ? `${ids}-name-error` : undefined}
              value={name}
              spellCheck={false}
              onChange={(e) => setName(e.target.value)}
            />
            {nameInvalid && fieldProblem && (
              <p id={`${ids}-name-error`} className="error field-error" role="alert">
                {fieldProblem.message}
              </p>
            )}
            <FieldChips field="Name" offers={nameOffers} codeLabel={codeLabel} disabled={filing.busy} onUse={(o) => setName(o.value)} />
            {rejected("name", "name")}
          </div>
          <div className="field">
            <FolderPicker
              ref={folderRef}
              label="Folder"
              value={folder}
              onChange={setFolder}
              error={tried && fieldProblem?.field === "folder" ? fieldProblem.message : null}
            />
            <FieldChips field="Folder" offers={folderOffers} codeLabel={codeLabel} disabled={filing.busy} onUse={(o) => setFolder(o.value)} />
            {rejected("folder", "folder")}
          </div>
          <div className="field">
            <label htmlFor={`${ids}-tags`}>Tags</label>
            <TagInput
              id={`${ids}-tags`}
              value={parseTags(tags)}
              onChange={(next) => setTags(next.join(", "))}
              disabled={filing.busy}
              passCmdEnter
            />
            <FieldChips field="tag" offers={tagChips} codeLabel={codeLabel} disabled={filing.busy} onUse={(o) => setTags(addTags(tags, [o.value]))} />
            {rejected("tags", "tags")}
          </div>
          <hr />
          <TrayPicker trays={trays.list} value={tray?.id ?? null} onChange={trays.setTrayId} problem={trays.problem} />
          {(trayOffer || answer?.rejected.tray) && (
            <div className="suggestion-tray-line">
              {trayOffer && (
                <SuggestionChip
                  field="tray"
                  offer={{ value: trayOffer.id, source: AI_SOURCE, note: aiNote(answer?.confidence.tray, answer?.reason) }}
                  shown={trayOffer.name}
                  disabled={filing.busy}
                  onUse={() => trays.setTrayId(trayOffer.id)}
                />
              )}
              {rejected("tray", "tray")}
            </div>
          )}
          {rejectedTrayFields.map(([key, reason]) => (
            <AIRejected key={key} field={fieldWord(key.slice("tray_fields.".length))} reason={reason} />
          ))}
          {tray &&
            (alreadyIn ? (
              <AlreadyIn tray={tray} driveId={entry.record.drive_id} />
            ) : (
              <TrayFields tray={tray} values={trayFields} found={found} onChange={editField} chips={trayChips} />
            ))}
          <CollectionPicker
            value={collections}
            onChange={setCollections}
            text={collectionText}
            onTextChange={setCollectionText}
          />
          {answer?.summary.trim() && <AISummary summary={answer.summary} onUse={useSummaryAsNote} />}
          <NoteEditor value={note} onChange={setNote} />
          {fromSticker && (
            <StickerMarks
              star={star}
              important={important}
              hasStar={hasStar}
              hasImportant={hasImportant}
              unclear={unclearBoxes(entry.suggestion)}
              onStar={setStar}
              onImportant={setImportant}
            />
          )}
          <hr />
          <DetectedFields entry={entry} />
          {/* After the form, so showing it never pushes the fields down; it sticks to the
              bottom of the inspector while the form scrolls. */}
          {plan && (
            <div className="inbox-plan">
              <PlanPreview
                ops={plan.ops}
                tags={parseTags(tags)}
                followUps={followUpLines(plan.requests, trays.list, entry.prefill)}
              />
            </div>
          )}
        </div>
      </div>
    </article>
  );
}
