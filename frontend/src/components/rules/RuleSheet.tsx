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
  type Replay,
  type Rule,
  type RuleDraft,
  type RuleIn,
  type RuleOffer,
  useAreaPicture,
  useInbox,
  useReplay,
  useRules,
  useSaveRule,
  useTrays,
  type ZoneDraft,
} from "../../api/client";
import { plural } from "../../format";
import { visible } from "../../text";
import { useInboxFolder } from "../MoveTo";
import { TagInput } from "../TagInput";
import { useToast } from "../Toasts";
import { SamplePage } from "../zones/SamplePage";
import { Sheet } from "../ui/Sheet";
import { ReplayResult } from "./ReplayResult";

const REPLAY_DELAY_MS = 400;
/** While page 1 of some documents is being read, the replay is asked for again after this
 * long, a few times. */
const READING_POLL_MS = 2000;
const READING_POLLS = 15;

type Word = { word: string; ticked: boolean };
/** An area of page 1: the words of which any one is enough, or (``image``) a picture that
 * has to appear in it with at least ``minScore`` (null: the default). */
type RuleArea = { box: PageBox; words: Word[]; image?: string; minScore?: number | null };

/** The score a picture area needs when the rule names none (the API says; this is the
 * value until it has answered). */
const DEFAULT_MIN_SCORE = 0.85;
/** A field of the "then" part: ``off`` leaves it out of the rule. */
type Text = { off: boolean; value: string };

const isDraft = (r: RuleDraft | Rule): r is RuleDraft => "words" in r;
const isZoneDraft = (r: RuleDraft | ZoneDraft | Rule): r is ZoneDraft => "zones" in r && "words" in r;

/** The replay is still waiting for pages to be read. */
const waiting = (r: Replay) =>
  (r.reading ?? 0) > 0 || (r.not_checked ?? []).some((n) => n.reason === "page 1 not read yet");

/** What saving or deleting a rule kept in a file written by hand does to that file. */
export const rewriteNote = (doing: "Saving" | "Deleting", file: string) =>
  `${doing} rewrites ${file}, so the comments in it are lost. A copy of the old file is kept next to it (.bak).`;
const text = (value: string | null): Text => ({ off: value === null, value: value ?? "" });

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
  onClose: () => void;
}) {
  const draft = isDraft(initial);
  const zoneDraft = isZoneDraft(initial) ? initial : null;
  const person = draft ? null : initial.when.person;
  const sender = zoneDraft ? zoneDraft.sender : draft ? null : initial.sender;
  // a new rule drawn from boxes goes directly above the learned rule that matches the document
  const placeAbove = zoneDraft?.place_above ?? null;
  const [personZone, setPersonZone] = useState<PageBox | null>(() => (draft ? null : initial.person_zone));
  const replacing = replaces ?? (draft ? undefined : initial.id);
  const inbox = useInboxFolder();
  const trays = useTrays().data?.trays ?? [];
  const toast = useToast();
  const replay = useReplay();
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
          ...zoneDraft.zones.map((z) => ({ box: z.box, words: z.words.map((w) => ({ ...w })) })),
          ...(zoneDraft.pictures ?? []).map((p) => ({ box: p.box, words: [], image: p.image, minScore: null })),
        ]
      : draft
        ? []
        : initial.when.zones.map((z) =>
            z.image
              ? { box: z.box, words: [], image: z.image, minScore: z.min_score ?? null }
              : { box: z.box, words: (z.text_contains ?? []).map((word) => ({ word, ticked: true })) },
          ),
  );
  const [adding, setAdding] = useState("");
  const start = draft ? initial : initial.then; // a draft's actions sit on the draft itself
  const [folder, setFolder] = useState(() => text(start.folder));
  const [name, setName] = useState(() => text(start.name));
  const [payee, setPayee] = useState(() => text(start.payee));
  const [tray, setTray] = useState(() => text(start.tray));
  const [tags, setTags] = useState<string[]>(() => start.tags);
  const [tagsOff, setTagsOff] = useState(() => tags.length === 0);
  const [more, setMore] = useState(
    () => (!draft && !!(initial.when.filename_matches || initial.when.folder_is)) || !!zoneDraft?.folder_is,
  );
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
                  : { box: a.box, text_contains: areaWords[i] },
              ),
            }
          : {}),
        ...(person ? { person } : {}),
      },
      then: {
        folder: folder.off ? null : folder.value,
        name: name.off ? null : name.value,
        tags: tagsOff ? [] : tags,
        tray: tray.off || !tray.value ? null : tray.value,
        payee: payee.off ? null : payee.value,
      },
      ...(personZone ? { person_zone: personZone } : {}),
      ...(sender ? { sender } : {}),
    }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [initial.id, JSON.stringify(ticked), JSON.stringify(areas.map((a, i) => [a.box, areaWords[i], a.image, a.minScore])), JSON.stringify(personZone), filename, folderIs, folder, name, tags, tagsOff, tray, payee],
  );
  const ruleKey = JSON.stringify(rule);

  // The last successful replay with the rule it was made for: Save needs one for exactly
  // the rule on screen, so the proof is never skipped.
  const [proof, setProof] = useState<{ key: string; replay: Replay } | null>(null);
  const latestKey = useRef(ruleKey);
  latestKey.current = ruleKey;
  const { mutate: runReplay } = replay;
  // Documents whose page 1 is being read are not counted yet: ask again, a few times.
  const again = useRef<ReturnType<typeof setTimeout>>(undefined);
  const polls = useRef(0);
  // Which run of the effect below a replay belongs to: its cleanup (a new rule, or the
  // sheet closing) ends it, and a reply that arrives later schedules nothing.
  const epoch = useRef(0);
  const run = (mine: number) => {
    const key = ruleKey;
    runReplay(
      { rule, replaces: replacing, placeAbove: replacing ? null : placeAbove },
      {
        onSuccess: (result) => {
          if (mine !== epoch.current || key !== latestKey.current) return;
          setProof({ key, replay: result });
          if (waiting(result) && polls.current < READING_POLLS) {
            polls.current += 1;
            again.current = setTimeout(() => run(mine), READING_POLL_MS);
          }
        },
      },
    );
  };
  useEffect(() => {
    if (!hasCondition) return;
    polls.current = 0;
    const mine = ++epoch.current;
    const timer = setTimeout(() => run(mine), REPLAY_DELAY_MS);
    return () => {
      epoch.current += 1;
      clearTimeout(timer);
      clearTimeout(again.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ruleKey, replacing, runReplay]);

  // How the rule did before the change (a replay of the old rule, asked once).
  const [baseline, setBaseline] = useState<Replay | null>(null);
  const baselineReplay = useReplay();
  const { mutate: runBaseline } = baselineReplay;
  const baselineAgain = useRef<ReturnType<typeof setTimeout>>(undefined);
  useEffect(() => {
    if (!before) return;
    let live = true;
    let polls = 0;
    const ask = () =>
      runBaseline(
        { rule: ruleInOf(before), replaces: before.id },
        {
          onSuccess: (result) => {
            if (!live) return;
            setBaseline(result);
            if (waiting(result) && polls < READING_POLLS) {
              polls += 1;
              baselineAgain.current = setTimeout(ask, READING_POLL_MS);
            }
          },
        },
      );
    ask();
    return () => {
      live = false;
      clearTimeout(baselineAgain.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [before?.id, runBaseline]);

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
  const moveArea = async (at: number, box: PageBox, driveId: string) => {
    const area = areas[at];
    if (!area?.image) {
      setAreas((all) => all.map((a, i) => (i === at ? { ...a, box } : a)));
      return;
    }
    setRecutError(null);
    try {
      const cut = await recut.mutateAsync({ driveId, box, save: true, ruleId: initial.id });
      setAreas((all) => all.map((a, i) => (i === at ? { ...a, box, image: cut.image ?? a.image } : a)));
    } catch (e) {
      setRecutError(errorText(e));
    }
  };
  const defaultMin = useRules(areas.some((a) => a.image)).data?.default_min_score ?? DEFAULT_MIN_SCORE;
  // the lowest score a picture area needs: what the replay's scores are compared with
  const needed = areas.some((a) => a.image)
    ? Math.min(...areas.filter((a) => a.image).map((a) => a.minScore ?? defaultMin))
    : null;

  const tested = proof !== null && proof.key === ruleKey ? proof.replay : null;
  const failed = replay.isError && tested === null;
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

  const textField = (label: string, state: Text, set: (t: Text) => void, hint?: string) => (
    <div className="field rule-field">
      <label htmlFor={`${ids}-${label}`}>{label}</label>
      <div className="rule-field-row">
        <input
          id={`${ids}-${label}`}
          value={state.value}
          disabled={state.off}
          onChange={(e) => set({ ...state, value: e.target.value })}
        />
        <label className="rule-off">
          <input
            type="checkbox"
            checked={state.off}
            aria-label={`Leave out ${label.toLowerCase()}`}
            onChange={(e) => set({ ...state, off: e.target.checked })}
          />
          Leave out
        </label>
      </div>
      {hint && <p className="hint">{hint}</p>}
    </div>
  );

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
              onRemove={() => setAreas((all) => all.filter((_, i) => i !== at))}
            />
          ) : (
            <AreaWords
              key={at}
              n={at + 1}
              several={areas.length > 1}
              words={area.words}
              onToggle={(word) => changeArea(at, (all) => all.map((x) => (x.word === word ? { ...x, ticked: !x.ticked } : x)))}
              onAdd={(word) => changeArea(at, (all) => withWord(all, word))}
              onRemove={() => setAreas((all) => all.filter((_, i) => i !== at))}
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
        {sender && <p className="hint">Sender: {visible(sender)}</p>}
        {filed && (
          <p className="hint rule-filed">
            Filed as: {visible(`${filed.folder}/${filed.name}`)}
          </p>
        )}
        {textField("Folder", folder, setFolder, "Patterns like {year} are filled in for each document.")}
        {textField("Name", name, setName)}
        <div className="field">
          <label htmlFor={`${ids}-tags`}>Tags</label>
          <div className="rule-field-row">
            <TagInput id={`${ids}-tags`} value={tags} onChange={setTags} disabled={tagsOff} />
            <label className="rule-off">
              <input type="checkbox" checked={tagsOff} aria-label="Leave out tags" onChange={(e) => setTagsOff(e.target.checked)} />
              Leave out
            </label>
          </div>
        </div>
        <div className="field rule-field">
          <label htmlFor={`${ids}-tray`}>Tray</label>
          <div className="rule-field-row">
            <select
              id={`${ids}-tray`}
              value={tray.value}
              disabled={tray.off}
              onChange={(e) => setTray({ ...tray, value: e.target.value })}
            >
              <option value="">None</option>
              {trays.map((t) => (
                <option key={t.id} value={t.id}>{visible(t.name)}</option>
              ))}
            </select>
            <label className="rule-off">
              <input type="checkbox" checked={tray.off} aria-label="Leave out tray" onChange={(e) => setTray({ ...tray, off: e.target.checked })} />
              Leave out
            </label>
          </div>
        </div>
        {textField("Payee", payee, setPayee)}
        <button type="button" className="link-button" aria-expanded={more} onClick={() => setMore(!more)}>
          More conditions
        </button>
        {more && (
          <>
            <div className="field">
              <label htmlFor={`${ids}-file`}>File name matches</label>
              <input id={`${ids}-file`} value={filename} onChange={(e) => setFilename(e.target.value)} />
            </div>
            <div className="field">
              <label htmlFor={`${ids}-in`}>Document is in folder</label>
              <input id={`${ids}-in`} value={folderIs} onChange={(e) => setFolderIs(e.target.value)} />
            </div>
          </>
        )}
        {hasCondition && (
          <ReplayResult
            replay={proof?.replay}
            before={before ? baseline : null}
            sender={sender}
            needed={needed}
            pending={tested === null && !failed}
            error={failed ? errorText(replay.error) : null}
            onRetry={() => run(epoch.current)}
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
  onToggle,
  onAdd,
  onRemove,
}: {
  n: number;
  several: boolean;
  words: Word[];
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
          max={0.99}
          step={0.01}
          value={shown}
          aria-label={`Match needed for ${label.toLowerCase()}`}
          onChange={(e) => onScore(Number(e.target.value))}
        />
        <output htmlFor={`${id}-score`}>{shown.toFixed(2)}</output>
        {minScore !== null && (
          <button type="button" className="link-button" onClick={() => onScore(null)}>
            Use the usual {defaultScore.toFixed(2)}
          </button>
        )}
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
          : { box: z.box, text_contains: z.text_contains },
      ),
      person: r.when.person,
    },
    then: r.then,
    person_zone: r.person_zone,
    sender: r.sender,
  };
}
