/** Make, update or edit a filing rule: the words a document must contain, what the rule
 * then does, and the proof (a replay over the documents filed so far) below, refreshed
 * 400 ms after the last edit. Saving asks first when the rule would have filed some
 * document somewhere else. */
import { useEffect, useId, useMemo, useRef, useState } from "react";
import {
  type Area,
  areaPictureUrl,
  errorText,
  type PageBox,
  type Rule,
  type RuleDraft,
  type RuleIn,
  type RuleOffer,
  useAreaPicture,
  useInbox,
  usePeople,
  useRules,
  useSaveRule,
  useSenders,
  useTrays,
  type ZoneDraft,
} from "../../api/client";
import { plural } from "../../format";
import { isWordToken, visible } from "../../text";
import { useInboxFolder } from "../MoveTo";
import { TagInput } from "../TagInput";
import { useToast } from "../Toasts";
import { SamplePage } from "../zones/SamplePage";
import { Sheet } from "../ui/Sheet";
import { ReplayResult } from "./ReplayResult";
import { useReplayJob } from "./useReplayJob";

type Word = { word: string; ticked: boolean };
/** An area of page 1: the words of which any one is enough, or (``image``) a picture that
 * has to appear in it with at least ``minScore`` (null: the default). */
type RuleArea = { box: PageBox; words: Word[]; image?: string; minScore?: number | null; match?: Match };

/** How an area's words match a line: at the start of a word (any ending), as a whole word, or anywhere. */
type Match = "word_start" | "whole_word" | "anywhere";
const MATCH_CHOICES: { value: Match; label: string }[] = [
  { value: "word_start", label: "Starts a word" },
  { value: "whole_word", label: "Whole word" },
  { value: "anywhere", label: "Anywhere" },
];
const MATCH_TIP =
  "Starts a word: the word must begin a word but may have an ending, so Kela finds Kela, Kelan and Kelalta, but vakuutus does not find Henkivakuutus. Whole word: only the word itself, so Kela finds Kela but not Kelan. Anywhere: the letters anywhere in a word, so vakuutus also finds Henkivakuutus.";
/** An area's choice as the API takes it: left out for "anywhere", which is what a rule without it means. */
const matchField = (m: Match | undefined) => (m && m !== "anywhere" ? { match: m } : {});

/** The folder with ``{person}`` where the person's name is a part of it already, else on the
 * end. A folder that has ``{person}`` is left as it is. */
export function folderWithPerson(folder: string, name: string | null): string {
  const f = folder.trim();
  if (f.includes("{person}")) return f;
  const parts = f.split("/").filter((p) => p !== "");
  const who = name?.normalize("NFC").toLowerCase();
  const at = who ? parts.findIndex((p) => p.normalize("NFC").toLowerCase() === who) : -1;
  if (at >= 0) return parts.map((p, i) => (i === at ? "{person}" : p)).join("/");
  return [...parts, "{person}"].join("/");
}

/** Who the address area found, in words. */
function foundText(found: string[], person: string | null): string {
  if (found.length === 0) return person ? `${person}, set on the document` : "Nobody found in the address area";
  const names = found.length === 1 ? found[0] : `${found.slice(0, -1).join(", ")} and ${found[found.length - 1]}`;
  return `${names}${found.length === 1 ? ", found" : " found"} in the address area`;
}

/** The score a picture area needs when the rule names none (the API says; this is the
 * value until it has answered). */
const DEFAULT_MIN_SCORE = 0.85;

/** An info mark after a label: the explanation is its tooltip, and the field it explains
 * points at it with aria-describedby. */
function InfoTip({ id, tip }: { id: string; tip: string }) {
  return (
    <>
      <span className="info-tip" role="img" tabIndex={0} aria-label={tip} data-tip={tip}>
        ?
      </span>
      <span id={id} className="visually-hidden">{tip}</span>
    </>
  );
}

const FILENAME_TIP =
  "A regular expression searched anywhere in the file name, not wildcards. It is case-sensitive unless it starts with (?i). Examples: (?i)scan finds Scan and SCAN anywhere in the name; ^IMG_\\d+ finds names that start with IMG_ and a number.";
const FOLDER_TIP =
  "Leave it empty and the rule does not set the folder. Patterns are filled in for each document: {year}, {doc_date:%Y%m%d}, {stem} (the file name without its ending) and {person}.";
const NAME_TIP =
  "Leave it empty and the rule does not set the name. Patterns are filled in for each document: {year}, {doc_date:%Y%m%d}, {stem} (the file name without its ending) and {person}.";
const FOR_TIP =
  "Optional. Only for: the rule applies to letters for that person, as set on the document or found in its address area. {person} in the Folder or Name is filled in with the person of each letter.";
const FROM_TIP =
  "Optional. Who these letters are from. If you have set From on documents, the test below also shows how many of them this rule finds.";

const isDraft = (r: RuleDraft | Rule): r is RuleDraft => "words" in r;
const isZoneDraft = (r: RuleDraft | ZoneDraft | Rule): r is ZoneDraft => "zones" in r && "words" in r;

/** What saving or deleting a rule kept in a file written by hand does to that file. */
export const rewriteNote = (doing: "Saving" | "Deleting", file: string) =>
  `${doing} rewrites ${file}, so the comments in it are lost. A copy of the old file is kept next to it (.bak).`;

/** The sheet an offer on the filed toast opens. "Make a rule…" starts from the draft;
 * "Update rule …" starts from that rule as it is (its id, words and other conditions)
 * with only the folder and name patterns of the filing just done. A rule that is gone
 * by now is offered as a new one. */
export function OfferRuleSheet({
  offer,
  filed,
  onClose,
}: {
  offer: RuleOffer;
  filed?: { folder: string; name: string };
  onClose: () => void;
}) {
  const update = offer.kind === "update" && offer.rule_id ? offer.rule_id : null;
  const rules = useRules();
  const toast = useToast();
  const failed = update !== null && rules.isError;
  useEffect(() => {
    if (!failed) return;
    toast({ kind: "error", text: `Could not open rule ${update}: ${errorText(rules.error)}` });
    onClose();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [failed]);
  if (update === null) return <RuleSheet initial={offer.draft} filed={filed} onClose={onClose} />;
  if (!rules.data) return null;
  const rule = rules.data.rules.find((r) => r.id === update);
  if (!rule) return <RuleSheet initial={offer.draft} filed={filed} onClose={onClose} />;
  const initial: Rule = { ...rule, then: { ...rule.then, folder: offer.draft.folder, name: offer.draft.name } };
  return <RuleSheet initial={initial} replaces={rule.id} filed={filed} onClose={onClose} />;
}

export function RuleSheet({
  initial,
  replaces,
  filed,
  before,
  samplePage = false,
  nearDriveId,
  onClose,
}: {
  initial: RuleDraft | ZoneDraft | Rule;
  /** The id of the rule this one takes the place of (an update, or an edit). */
  replaces?: string;
  /** Offer mode: what was just filed (its folder and name, shown under the words). */
  filed?: { folder: string; name: string };
  /** The rule as it was before the change in ``initial``: the proof also says how it did,
   * so the effect of the change can be seen ("finds 16 of 16, was 14"). */
  before?: Rule;
  /** Settings: show the rule's areas on a sample page, where they can be changed. */
  samplePage?: boolean;
  /** The document the areas were drawn on: the test looks at the documents in its folder early. */
  nearDriveId?: string;
  onClose: () => void;
}) {
  const draft = isDraft(initial);
  const zoneDraft = isZoneDraft(initial) ? initial : null;
  // who the rule is for (null: anyone): chosen in the For row
  const [person, setPerson] = useState<string | null>(() => (draft ? null : initial.when.person));
  const people = usePeople().data?.people;
  // the person the document the rule is made from is for, and everyone found in its address area
  const foundPerson = zoneDraft?.person ?? null;
  const peopleFound = zoneDraft?.people_found ?? [];
  // who the letter is from (optional): a drawn rule starts from the document's From
  const [fromText, setFromText] = useState(() => (zoneDraft ? zoneDraft.sender : draft ? null : initial.sender) ?? "");
  const sender = fromText.trim() || null;
  const senders = useSenders();
  // a new rule drawn from boxes goes directly above the learned rule that matches the document
  const placeAbove = zoneDraft?.place_above ?? null;
  const [personZone, setPersonZone] = useState<PageBox | null>(() => (draft ? null : initial.person_zone));
  const replacing = replaces ?? (draft ? undefined : initial.id);
  const inbox = useInboxFolder();
  const trays = useTrays().data?.trays ?? [];
  const toast = useToast();
  const save = useSaveRule();
  const ids = useId();

  // plain words (anywhere in the text) and, apart from them, one group of words per area
  const [words, setWords] = useState<Word[]>(() =>
    zoneDraft
      ? []
      : draft
        ? initial.words.map((w) => ({ ...w }))
        : initial.when.text_contains.map((word) => ({ word, ticked: true })),
  );
  const [areas, setAreas] = useState<RuleArea[]>(() =>
    zoneDraft
      ? [
          ...zoneDraft.zones.map((z) => ({
            box: z.box,
            // OCR noise ("•ö") is not offered as a word
            words: z.words.filter((w) => isWordToken(w.word)).map((w) => ({ ...w })),
            match: "word_start" as Match,
          })),
          ...(zoneDraft.pictures ?? []).map((p) => ({ box: p.box, words: [], image: p.image, minScore: null })),
        ]
      : draft
        ? []
        : initial.when.zones.map((z) =>
            z.image
              ? { box: z.box, words: [], image: z.image, minScore: z.min_score ?? null }
              : { box: z.box, words: (z.text_contains ?? []).map((word) => ({ word, ticked: true })), match: z.match ?? "anywhere" },
          ),
  );
  const [adding, setAdding] = useState("");
  const start = draft ? initial : initial.then; // a draft's actions sit on the draft itself
  // an empty field is one the rule does not set
  const [folder, setFolder] = useState(() => start.folder ?? "");
  const [name, setName] = useState(() => start.name ?? "");
  const [payee, setPayee] = useState(() => start.payee ?? "");
  const [tray, setTray] = useState(() => start.tray ?? "");
  const [tags, setTags] = useState<string[]>(() => start.tags);
  // closed to begin with; what is set in it shows beside the toggle
  const [more, setMore] = useState(false);
  const [filename, setFilename] = useState(() => (draft ? "" : (initial.when.filename_matches ?? "")));
  // A draft has no folder condition: a new rule applies to what is in the inbox. Until
  // the user types, an edited rule keeps its own.
  const [folderIsEdited, setFolderIs] = useState<string | null>(null);
  const folderIs = folderIsEdited ?? (zoneDraft ? zoneDraft.folder_is : draft ? inbox : initial.when.folder_is) ?? "";
  const [asking, setAsking] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [hadAreas] = useState(() => areas.length > 0);
  const ticked = words.filter((w) => w.ticked).map((w) => w.word);
  const areaWords = areas.map((a) => a.words.filter((w) => w.ticked).map((w) => w.word));
  // a rule needs a condition: a ticked word anywhere, or at least one area with a ticked word
  // (or a picture) in each
  const emptyArea = areas.findIndex((a, i) => !a.image && areaWords[i].length === 0);
  const pictureOnly = areas.some((a) => a.image) && ticked.length === 0 && areas.every((a) => a.image);
  const hasCondition = (ticked.length > 0 || areas.length > 0) && emptyArea < 0;
  const rule: RuleIn = useMemo(
    () => ({
      id: initial.id,
      when: {
        text_contains: ticked,
        filename_matches: filename.trim() || null,
        folder_is: folderIs.trim() || null,
        ...(areas.length > 0
          ? {
              zones: areas.map((a, i) =>
                a.image
                  ? { box: a.box, image: a.image, ...(a.minScore != null ? { min_score: a.minScore } : {}) }
                  : { box: a.box, text_contains: areaWords[i], ...matchField(a.match) },
              ),
            }
          : {}),
        ...(person ? { person } : {}),
      },
      then: {
        folder: folder.trim() || null,
        name: name.trim() || null,
        tags,
        tray: tray || null,
        payee: payee.trim() || null,
      },
      ...(personZone ? { person_zone: personZone } : {}),
      ...(sender ? { sender } : {}),
    }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [initial.id, sender, JSON.stringify(ticked), JSON.stringify(areas.map((a, i) => [a.box, areaWords[i], a.image, a.minScore, a.match])), person, JSON.stringify(personZone), filename, folderIs, folder, name, tags, tray, payee],
  );
  const ruleKey = JSON.stringify(rule);

  // The test runs on the server in the background and fills the result in as it goes. Save
  // needs a result for exactly the rule on screen, so the proof is never skipped (a test
  // that is not finished counts: its result so far is what Save asks about).
  const testKey = `${ruleKey}|${replacing ?? ""}`;
  const test = useReplayJob({
    enabled: hasCondition,
    jobKey: testKey,
    request: { rule, replaces: replacing, placeAbove: replacing ? null : placeAbove, nearDriveId },
  });

  // How the rule did before the change (a test of the old rule, asked once).
  const baselineTest = useReplayJob({
    enabled: before !== undefined,
    jobKey: before?.id ?? "",
    request: { rule: before ? ruleInOf(before) : rule, replaces: before?.id, nearDriveId },
    delayMs: 0,
  });
  const baseline = baselineTest.replay ?? null;

  const withWord = (all: Word[], w: string): Word[] =>
    all.some((x) => x.word === w) ? all.map((x) => (x.word === w ? { ...x, ticked: true } : x)) : [...all, { word: w, ticked: true }];
  const addWord = () => {
    const w = adding.trim().toLowerCase();
    setAdding("");
    if (w) setWords((all) => withWord(all, w));
  };
  const changeArea = (at: number, change: (words: Word[]) => Word[]) =>
    setAreas((all) => all.map((a, i) => (i === at ? { ...a, words: change(a.words) } : a)));
  // a picture area whose box changes is cut again from the document it was changed on
  const recut = useAreaPicture();
  const [recutError, setRecutError] = useState<string | null>(null);
  // each re-cut is tagged; a reply is applied only if no later move of the same area, and no
  // removal of an area (which shifts the others), has happened since it was asked for
  const recutTag = useRef({ moves: new Map<number, number>(), removed: 0, next: 0 });
  const moveArea = async (at: number, box: PageBox, driveId: string) => {
    const area = areas[at];
    const tags = recutTag.current;
    const tag = ++tags.next;
    tags.moves.set(at, tag);
    if (!area?.image) {
      setAreas((all) => all.map((a, i) => (i === at ? { ...a, box } : a)));
      return;
    }
    const removed = tags.removed;
    setRecutError(null);
    try {
      const cut = await recut.mutateAsync({ driveId, box, save: true, ruleId: initial.id });
      if (tags.moves.get(at) !== tag || tags.removed !== removed) return; // out of date
      setAreas((all) => all.map((a, i) => (i === at ? { ...a, box, image: cut.image ?? a.image } : a)));
    } catch (e) {
      if (tags.moves.get(at) === tag && tags.removed === removed) setRecutError(errorText(e));
    }
  };
  const defaultMin = useRules(areas.some((a) => a.image)).data?.default_min_score ?? DEFAULT_MIN_SCORE;
  // the lowest score a picture area needs: what the replay's scores are compared with
  const needed = areas.some((a) => a.image)
    ? Math.min(...areas.filter((a) => a.image).map((a) => a.minScore ?? defaultMin))
    : null;

  const tested = test.replay !== undefined && test.resultKey === testKey ? test.replay : null;
  const failed = test.error !== null && tested === null;
  const different = tested?.different.length ?? 0;
  const doSave = async () => {
    setAsking(false);
    setError(null);
    try {
      await save.mutateAsync({ rule, replaces: replacing, placeAbove: replacing ? null : placeAbove });
      toast({ kind: "info", text: `Rule ${rule.id} saved.` });
      onClose();
    } catch (e) {
      setError(errorText(e));
    }
  };
  const canSave = hasCondition && tested !== null && !save.isPending;
  // an existing rule opened from a filing is an update of it
  const title = draft
    ? replaces
      ? `Update rule ${replaces}`
      : "Make a rule"
    : `${filed ? "Update" : "Edit"} rule ${initial.id}`;

  const textField = (label: string, value: string, set: (v: string) => void, tip?: string) => (
    <div className="field rule-field">
      <div className="field-label-row">
        <label htmlFor={`${ids}-${label}`}>{label}</label>
        {tip && <InfoTip id={`${ids}-${label}-tip`} tip={tip} />}
      </div>
      <input
        id={`${ids}-${label}`}
        value={value}
        aria-describedby={tip ? `${ids}-${label}-tip` : undefined}
        onChange={(e) => set(e.target.value)}
      />
    </div>
  );
  const moreSummary = [
    folderIs.trim() ? (inbox && folderIs.trim() === inbox ? "Only in the inbox" : `Only in ${folderIs.trim()}`) : "",
    filename.trim() ? `File name matches ${filename.trim()}` : "",
  ]
    .filter(Boolean)
    .join("; ");

  return (
    <>
      <Sheet
        open
        title={title}
        onClose={onClose}
        className="rule-sheet"
        footer={
          <>
            {!hasCondition && (
              <span className="hint footer-start">
                {emptyArea >= 0
                  ? `Tick a word in area ${emptyArea + 1}`
                  : hadAreas
                    ? "A rule needs a word or an area"
                    : "Tick at least one word"}
              </span>
            )}
            <button type="button" onClick={onClose}>Cancel</button>
            <button
              type="button"
              className="primary"
              disabled={!canSave}
              onClick={() => (different > 0 ? setAsking(true) : void doSave())}
            >
              {hasCondition && tested === null && !failed ? "Testing…" : "Save"}
            </button>
          </>
        }
      >
        {(areas.length === 0 || words.length > 0) && (
          <div className="field">
            <span className="field-label" id={`${ids}-words`}>When the text contains</span>
            <ul className="rule-words" aria-labelledby={`${ids}-words`}>
              {words.map((w) => (
                <li key={w.word}>
                  <button
                    type="button"
                    className="rule-word"
                    aria-pressed={w.ticked}
                    onClick={() => setWords((all) => all.map((x) => (x.word === w.word ? { ...x, ticked: !x.ticked } : x)))}
                  >
                    {visible(w.word)}
                  </button>
                </li>
              ))}
            </ul>
            <input
              aria-label="Add a word"
              placeholder="Add a word"
              value={adding}
              onChange={(e) => setAdding(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  addWord();
                }
              }}
              onBlur={addWord}
            />
            <p className="hint">Any ticked word is enough; more words catch more documents.</p>
          </div>
        )}
        {areas.map((area, at) =>
          area.image ? (
            <AreaPictureView
              key={at}
              n={at + 1}
              several={areas.length > 1}
              image={area.image}
              minScore={area.minScore ?? null}
              defaultScore={defaultMin}
              onScore={(minScore) => setAreas((all) => all.map((a, i) => (i === at ? { ...a, minScore } : a)))}
              onRemove={() => {
                recutTag.current.removed++;
                setAreas((all) => all.filter((_, i) => i !== at));
              }}
            />
          ) : (
            <AreaWords
              key={at}
              n={at + 1}
              several={areas.length > 1}
              words={area.words}
              match={area.match ?? "anywhere"}
              onMatch={(match) => setAreas((all) => all.map((a, i) => (i === at ? { ...a, match } : a)))}
              onToggle={(word) => changeArea(at, (all) => all.map((x) => (x.word === word ? { ...x, ticked: !x.ticked } : x)))}
              onAdd={(word) => changeArea(at, (all) => withWord(all, word))}
              onRemove={() => {
                recutTag.current.removed++;
                setAreas((all) => all.filter((_, i) => i !== at));
              }}
            />
          ),
        )}
        {areas.length > 1 && <p className="hint">The document needs a word or the picture in every area.</p>}
        {pictureOnly && (
          <p className="hint">Add a text box to make this faster and surer: a picture alone takes longer to test and is less sure.</p>
        )}
        {recutError && (
          <p className="error" role="alert">
            {visible(recutError)}
          </p>
        )}
        {samplePage && (areas.length > 0 || personZone) && (
          <SampleAreas
            ruleId={initial.id}
            sample={draft ? null : initial.sample}
            areas={areas.map((a) => ({ box: a.box, picture: !!a.image }))}
            personZone={personZone}
            onArea={(i, box, driveId) => void moveArea(i, box, driveId)}
            onPersonZone={setPersonZone}
          />
        )}
        <div className="field">
          <div className="field-label-row">
            <label htmlFor={`${ids}-from`}>From (sender)</label>
            <InfoTip id={`${ids}-from-tip`} tip={FROM_TIP} />
          </div>
          <input
            id={`${ids}-from`}
            aria-describedby={`${ids}-from-tip`}
            value={fromText}
            placeholder="Optional, such as Pohjola"
            onChange={(e) => setFromText(e.target.value)}
          />
          {(senders.data?.length ?? 0) > 0 && (
            <ul className="assign-choices" aria-label="Senders you have used">
              {senders.data?.map((s) => (
                <li key={s.sender}>
                  <button
                    type="button"
                    className="assign-choice"
                    aria-pressed={sender === s.sender}
                    onClick={() => setFromText(s.sender)}
                  >
                    {visible(s.sender)}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
        <div className="field rule-for" role="group" aria-label="For">
          <div className="field-label-row">
            <span className="field-label">For</span>
            <InfoTip id={`${ids}-for-tip`} tip={FOR_TIP} />
          </div>
          {people !== undefined && people.length === 0 ? (
            <p className="hint">No people listed yet: add them in Settings → Filing rules → People.</p>
          ) : (
            zoneDraft && people !== undefined && <p className="hint rule-found">{visible(foundText(peopleFound, foundPerson))}</p>
          )}
          <div className="rule-for-choice">
            <span className="segmented" role="group" aria-label="Who the rule is for">
              <button type="button" className="segmented-option" aria-pressed={person === null} onClick={() => setPerson(null)}>
                Anyone
              </button>
              <button
                type="button"
                className="segmented-option"
                aria-pressed={person !== null}
                onClick={() => setPerson(person ?? foundPerson ?? people?.[0]?.name ?? "")}
              >
                Only for
              </button>
            </span>
            {person !== null && (
              <select aria-label="Person" value={person} onChange={(e) => setPerson(e.target.value)}>
                {person === "" && <option value="">Pick a person</option>}
                {person !== "" && !(people ?? []).some((p) => p.name === person) && <option value={person}>{visible(person)}</option>}
                {(people ?? []).map((p) => (
                  <option key={p.name} value={p.name}>{visible(p.name)}</option>
                ))}
              </select>
            )}
          </div>
          <div className="rule-for-folder">
            <button
              type="button"
              disabled={folder.includes("{person}")}
              onClick={() => setFolder(folderWithPerson(folder, foundPerson ?? person))}
            >
              Use the person in the folder
            </button>
            {folder.includes("{person}") && (
              <span className="hint rule-preview">
                {visible(
                  foundPerson ?? person
                    ? `This letter would go to ${folder.trim().replaceAll("{person}", (foundPerson ?? person) as string)}`
                    : "No person is known for this letter, so {person} cannot be filled in here.",
                )}
              </span>
            )}
          </div>
        </div>
        {filed && (
          <p className="hint rule-filed">
            Filed as: {visible(`${filed.folder}/${filed.name}`)}
          </p>
        )}
        {textField("Folder", folder, setFolder, FOLDER_TIP)}
        {textField("Name", name, setName, NAME_TIP)}
        <div className="field">
          <label htmlFor={`${ids}-tags`}>Tags</label>
          <TagInput id={`${ids}-tags`} value={tags} onChange={setTags} />
        </div>
        <div className="field rule-field">
          <label htmlFor={`${ids}-tray`}>Tray</label>
          <select id={`${ids}-tray`} value={tray} onChange={(e) => setTray(e.target.value)}>
            <option value="">None</option>
            {trays.map((t) => (
              <option key={t.id} value={t.id}>{visible(t.name)}</option>
            ))}
          </select>
        </div>
        {textField("Payee", payee, setPayee)}
        <div className="rule-more">
          <button type="button" className="link-button" aria-expanded={more} onClick={() => setMore(!more)}>
            More conditions
          </button>
          {!more && <span className="hint">{visible(moreSummary || "None set")}</span>}
        </div>
        {more && (
          <>
            <div className="field">
              <div className="field-label-row">
                <label htmlFor={`${ids}-file`}>File name matches</label>
                <InfoTip id={`${ids}-file-tip`} tip={FILENAME_TIP} />
              </div>
              <input
                id={`${ids}-file`}
                value={filename}
                aria-describedby={`${ids}-file-tip`}
                onChange={(e) => setFilename(e.target.value)}
              />
            </div>
            <div className="field">
              <label htmlFor={`${ids}-in`}>Document is in folder</label>
              <input id={`${ids}-in`} value={folderIs} onChange={(e) => setFolderIs(e.target.value)} />
            </div>
          </>
        )}
        {hasCondition && (
          <ReplayResult
            replay={test.replay}
            before={before ? baseline : null}
            sender={sender}
            needed={needed}
            pending={tested === null && !failed}
            error={failed ? (test.error ?? "") : null}
            onRetry={test.restart}
            rule={rule}
            progress={{ state: test.state, looked: test.looked, total: test.total, waiting: test.waiting }}
            onStop={test.stop}
            onTestAgain={test.restart}
            onReadNow={test.readNow}
            readingNow={test.readingNow}
          />
        )}
        {!draft && !initial.learned && initial.file && <p className="hint">{visible(rewriteNote("Saving", initial.file))}</p>}
        {error && <p className="error" role="alert">{visible(error)}</p>}
      </Sheet>
      {asking && (
        <Sheet
          open
          title="Save anyway?"
          onClose={() => setAsking(false)}
          footer={
            <>
              <button type="button" onClick={() => setAsking(false)}>Cancel</button>
              <button type="button" className="primary" onClick={() => void doSave()}>Save anyway</button>
            </>
          }
        >
          <p>
            {plural(different, "document")} would land somewhere else. Save anyway?
          </p>
        </Sheet>
      )}
    </>
  );
}

/** One area of page 1: its words as chips (any ticked one is enough), a word to add and a
 * way to remove the area. */
function AreaWords({
  n,
  several,
  words,
  match,
  onMatch,
  onToggle,
  onAdd,
  onRemove,
}: {
  n: number;
  several: boolean;
  words: Word[];
  match: Match;
  onMatch: (match: Match) => void;
  onToggle: (word: string) => void;
  onAdd: (word: string) => void;
  onRemove: () => void;
}) {
  const id = useId();
  const [adding, setAdding] = useState("");
  const add = () => {
    const w = adding.trim().toLowerCase();
    setAdding("");
    if (w) onAdd(w);
  };
  const label = several ? `Area ${n}` : "Area";
  return (
    <div className="field rule-area" role="group" aria-label={label}>
      <div className="rule-area-head">
        <span className="field-label" id={`${id}-label`}>
          {several ? `In area ${n} of page 1` : "In the area you drew on page 1"}
        </span>
        <button type="button" className="link-button" aria-label={`Remove ${label.toLowerCase()}`} onClick={onRemove}>
          Remove
        </button>
      </div>
      <ul className="rule-words" aria-labelledby={`${id}-label`}>
        {words.map((w) => (
          <li key={w.word}>
            <button type="button" className="rule-word" aria-pressed={w.ticked} onClick={() => onToggle(w.word)}>
              {visible(w.word)}
            </button>
          </li>
        ))}
      </ul>
      <input
        aria-label={`Add a word to ${label.toLowerCase()}`}
        placeholder="Add a word"
        value={adding}
        onChange={(e) => setAdding(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            add();
          }
        }}
        onBlur={add}
      />
      <div className="rule-match">
        <label htmlFor={`${id}-match`}>Words match</label>
        <select
          id={`${id}-match`}
          value={match}
          aria-label={`How the words match in ${label.toLowerCase()}`}
          aria-describedby={`${id}-match-tip`}
          onChange={(e) => onMatch(e.target.value as Match)}
        >
          {MATCH_CHOICES.map((c) => (
            <option key={c.value} value={c.value}>{c.label}</option>
          ))}
        </select>
        <InfoTip id={`${id}-match-tip`} tip={MATCH_TIP} />
      </div>
    </div>
  );
}

/** A picture area: its crop, the score it needs (the default until it is moved) and a way to
 * remove it. */
function AreaPictureView({
  n,
  several,
  image,
  minScore,
  defaultScore,
  onScore,
  onRemove,
}: {
  n: number;
  several: boolean;
  image: string;
  minScore: number | null;
  defaultScore: number;
  onScore: (score: number | null) => void;
  onRemove: () => void;
}) {
  const id = useId();
  const label = several ? `Area ${n}` : "Area";
  const shown = minScore ?? defaultScore;
  return (
    <div className="field rule-area" role="group" aria-label={label}>
      <div className="rule-area-head">
        <span className="field-label" id={`${id}-label`}>
          {several ? `Picture in area ${n} of page 1` : "Picture in the area you drew on page 1"}
        </span>
        <button type="button" className="link-button" aria-label={`Remove ${label.toLowerCase()}`} onClick={onRemove}>
          Remove
        </button>
      </div>
      <img className="rule-picture" src={areaPictureUrl(image)} alt={`Picture of ${label.toLowerCase()}`} />
      <div className="rule-score">
        <label htmlFor={`${id}-score`}>Match needed</label>
        <input
          id={`${id}-score`}
          type="range"
          min={0.5}
          max={1}
          step={0.01}
          value={shown}
          aria-label={`Match needed for ${label.toLowerCase()}`}
          onChange={(e) => onScore(Number(e.target.value))}
        />
        <output htmlFor={`${id}-score`}>{shown.toFixed(2)}</output>
        <span className="rule-score-reset">
          {minScore !== null && (
            <button type="button" className="link-button" onClick={() => onScore(null)}>
              Use the usual {defaultScore.toFixed(2)}
            </button>
          )}
        </span>
      </div>
    </div>
  );
}

/** A rule's areas on a sample page (the document it matched last, or one from the Inbox), to
 * see them and to change them by dragging. */
function SampleAreas({
  ruleId,
  sample,
  areas,
  personZone,
  onArea,
  onPersonZone,
}: {
  ruleId: string;
  sample: Rule["sample"] | null | undefined;
  areas: { box: PageBox; picture: boolean }[];
  personZone: PageBox | null;
  /** An area was moved on the document ``driveId`` (a picture area is cut again from it). */
  onArea: (index: number, box: PageBox, driveId: string) => void;
  onPersonZone: (box: PageBox) => void;
}) {
  const id = useId();
  const inbox = useInbox();
  const [picked, setPicked] = useState(sample?.drive_id ?? "");
  const choices = [
    ...(sample ? [{ drive_id: sample.drive_id, name: sample.name, ext: sample.ext, label: `Last document it matched: ${sample.name ?? sample.drive_id}` }] : []),
    ...(inbox.data ?? [])
      .filter((e) => e.record.drive_id !== sample?.drive_id)
      .map((e) => ({ drive_id: e.record.drive_id, name: e.record.name, ext: e.record.ext, label: e.record.name ?? e.record.path })),
  ];
  const chosen = choices.find((c) => c.drive_id === picked);
  const shown: Area[] = [
    ...areas.map(({ box, picture }, index) => ({
      rule_id: ruleId,
      index,
      box,
      kind: picture ? ("image" as const) : ("text" as const),
      lines: [],
      score: null,
      matched: true,
      reason: null,
      wins: true,
    })),
    ...(personZone
      ? [{ rule_id: ruleId, index: 0, box: personZone, kind: "address" as const, lines: [], score: null, matched: true, reason: null, wins: true }]
      : []),
  ];
  return (
    <div className="field rule-sample">
      <label htmlFor={`${id}-sample`}>Areas on a sample page</label>
      <select id={`${id}-sample`} value={picked} onChange={(e) => setPicked(e.target.value)}>
        <option value="">Pick a document</option>
        {choices.map((c) => (
          <option key={c.drive_id} value={c.drive_id}>
            {visible(c.label)}
          </option>
        ))}
      </select>
      {chosen ? (
        <>
          <SamplePage
            driveId={chosen.drive_id}
            ext={chosen.ext}
            areas={shown}
            onChange={(area, box) => (area.kind === "address" ? onPersonZone(box) : onArea(area.index, box, chosen.drive_id))}
          />
          <p className="hint">Click an area to select it, then drag it to move it or its handles to resize it. The test below follows.</p>
        </>
      ) : (
        <p className="hint">Pick a document to see the areas on its first page.</p>
      )}
    </div>
  );
}

/** The rule as the save and replay calls take it. */
export function ruleInOf(r: Rule): RuleIn {
  return {
    id: r.id,
    when: {
      text_contains: r.when.text_contains,
      filename_matches: r.when.filename_matches,
      folder_is: r.when.folder_is,
      zones: r.when.zones.map((z) =>
        z.image
          ? { box: z.box, image: z.image, ...(z.min_score != null ? { min_score: z.min_score } : {}) }
          : { box: z.box, text_contains: z.text_contains, ...matchField(z.match) },
      ),
      person: r.when.person,
    },
    then: r.then,
    person_zone: r.person_zone,
    sender: r.sender,
  };
}
