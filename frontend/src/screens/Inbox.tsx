import { QrCode, Upload } from "lucide-react";
import { type MouseEvent, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import {
  archiveKey,
  errorText,
  type FileItResult,
  type FileRequest,
  type InboxEntry,
  type ResolvedOp,
  type RuleOffer,
  type TrayDef,
  useAssignCode,
  useDeclineRule,
  useFilingCodes,
  useInbox,
  useStatus,
  useToday,
  useTrays,
} from "../api/client";
import { useAddFiles } from "../components/AddFiles";
import { scannedFields } from "../components/FileDetails";
import { InboxEmpty } from "../components/InboxEmpty";
import { CodePicker } from "../components/codes/CodePicker";
import { MarkedBatch, markedFollowUps } from "../components/codes/MarkedBatch";
import { useSetupFolders } from "../components/SetupFolders";
import { ConfirmPlan, snapshotKey } from "../components/PlanPreview";
import { useLocalToday } from "../components/RelativeDate";
import { OfferRuleSheet } from "../components/rules/RuleSheet";
import { type ToastAction, useBlockToastActions, useToast } from "../components/Toasts";
import { isTrashKey, useTrash } from "../components/Trash";
import { IconButton } from "../components/ui/IconButton";
import { Splitter, useSplitWidth } from "../components/ui/SplitPane";
import { Tag } from "../components/ui/Tag";
import { Thumb } from "../components/Thumb";
import { Toolbar } from "../components/ui/Toolbar";
import { type UndoTarget, useUndoConfirm } from "../components/UndoConfirm";
import { type QLFile, useQuickLook } from "../components/useQuickLook";
import { formatDate, formatMoney, plural, shortDate } from "../format";
import { dragSelection, setDragFiles } from "../dnd";
import { dialogOpen, isShortcut, isTyping, useKeydown } from "../keyboard";
import { publishSelection } from "../selection";
import { visible } from "../text";
import BatchCard from "./BatchCard";
import ReviewCard from "./ReviewCard";
import { followUpLines, speaker, useFiling } from "./useFiling";
import { type KeyHint, KeyHints } from "../components/KeyHints";
import { MarkIcons } from "../components/MarkIcons";
import { baseName } from "../paths";

const MAX_NAMES = 5;


/** "a.pdf, b.pdf, … +N more" for the files a batch filed. */
export function fileList(ops: ResolvedOp[]): string {
  const names = ops.filter((op) => op.kind === "rename" || op.kind === "move").map((op) => baseName(op.dst));
  const shown = names.slice(0, MAX_NAMES).join(", ");
  return names.length > MAX_NAMES ? `${shown} +${names.length - MAX_NAMES} more` : shown;
}

function summary(result: FileItResult): string {
  const files = result.done.filter((op) => op.kind === "rename" || op.kind === "move");
  if (files.length === 1) return `Filed as ${files[0].dst}`;
  if (files.length > 1) return `Filed ${files.length} files: ${fileList(result.done)}`;
  return `${result.done.length} change(s) applied`;
}

/** " · added to To pay, Sauna": the trays (if their items were created) and the
 * collections (unless a follow-up failed: its warning toast says what happened). A
 * marked batch gives each file its own, so every request's are named once. */
function addedTo(result: FileItResult, requests: FileRequest[], trays: TrayDef[]): string {
  if (!speaker(requests)) return "";
  const targets = new Set<string>();
  if (result.items.length > 0) {
    for (const r of requests) if (r.tray) targets.add(trays.find((t) => t.id === r.tray)?.name ?? r.tray);
  }
  if (!result.follow_up_error) for (const r of requests) for (const c of r.collections ?? []) targets.add(c);
  return targets.size > 0 ? ` · added to ${[...targets].join(", ")}` : "";
}

const uniqueTags = (requests: FileRequest[]) => [...new Set(requests.flatMap((r) => r.tags ?? []))];

/** The list's key hints: keys, then what they do. */
const KEYS: KeyHint[] = [
  [["↑", "↓"], "move"],
  [["⇧↑", "⇧↓"], "select several"],
  [["⌘"], "click to add or remove"],
  [["Space"], "Quick Look"],
  [["↩"], "preview"],
  [["⌘↩"], "file it"],
  [["c"], "filing code"],
  [["n"], "name"],
  [["f"], "folder"],
  [["1–9"], "tray"],
  [["0"], "no tray"],
  [["u"], "undo"],
  [["⌘⌫"], "move to To Delete"],
];

/** "due 15.10.2026 · 84,20 €" from the scan, red once the due date has passed. */
function ScanChip({ prefill, today }: { prefill: Record<string, string>; today: string }) {
  const due = prefill.due_date;
  const total = prefill.total;
  if (!due && !total) return null;
  const parts = [due && `due ${formatDate(due)}`, total && formatMoney(total)].filter(Boolean);
  return (
    <Tag tone={due && due < today ? "red" : "blue"} className="entry-chip">
      {visible(parts.join(" · "))}
    </Tag>
  );
}

/** The code the owner assigned to the entry in the app, or null. */
export const assignedOf = (entry: InboxEntry) => entry.suggestion.codes.find((c) => c.via === "assigned")?.code ?? null;

/** The filing codes found for a file ("P", "P?" when the reading was unclear); codes an
 * assigned code overrides are left out. */
function CodeBadge({ codes }: { codes: InboxEntry["suggestion"]["codes"] }) {
  const shown: string[] = [];
  for (const c of codes) {
    if (c.overridden) continue;
    const text = c.unclear ? `${c.code}?` : c.code;
    if (!shown.includes(text)) shown.push(text);
  }
  if (shown.length === 0) return null;
  return (
    <Tag tone="grey" className="entry-chip" title={`Filing code ${shown.join(", ")}`}>
      {visible(shown.join(" "))}
    </Tag>
  );
}

/** The ``##. Organize`` queue in two columns beside the sidebar: the list, then the
 * document (preview plus the form as a narrow inspector) or, with several files
 * selected, the batch form. ⌘-click and ⇧-click select several (the checkboxes do the
 * same); Space opens Quick Look on the current file. Rows drag (the selection, when the
 * row is in it) onto a sidebar tray or collection. */
export default function Inbox() {
  const inbox = useInbox();
  const split = useSplitWidth(archiveKey("dam.inbox.listwidth"), { min: 220, max: 520, initial: 280, unit: "px" });
  const trayList = useTrays().data?.trays ?? [];
  const toast = useToast();
  const status = useStatus();
  const addFiles = useAddFiles(status.data?.inbox_exists === false ? "The inbox folder does not exist yet" : null);
  const setupFolders = useSetupFolders();
  // ``?file=<drive_id>`` starts on that file ("Mark paid & file it…" links here).
  // ``?marked=1`` shows the File N marked panel instead of the form.
  const [search, setSearch] = useSearchParams();
  const markedOpen = search.get("marked") === "1";
  const todayData = useToday().data;
  const marked = todayData?.marked ?? 0;
  const readingCodes = (todayData?.reading_codes ?? 0) > 0;
  const [selectedId, setSelectedId] = useState<string | null>(() => search.get("file"));
  const [checked, setChecked] = useState<Set<string>>(new Set());
  // Where a ⇧-click range starts: the last plainly or ⌘-clicked entry.
  const [anchorId, setAnchorId] = useState<string | null>(null);
  const today = useLocalToday();
  const [lastApplied, setLastApplied] = useState<UndoTarget | null>(null);
  const undo = useUndoConfirm((batchId) =>
    setLastApplied((last) => (last?.batchId === batchId ? null : last)),
  );

  const entries: InboxEntry[] = useMemo(() => inbox.data ?? [], [inbox.data]);
  const found = entries.findIndex((e) => e.record.drive_id === selectedId);
  const index = found >= 0 ? found : 0;
  const current = entries[index] as InboxEntry | undefined;
  const batch = entries.filter((e) => checked.has(e.record.drive_id));

  const declineRule = useDeclineRule();
  const [ruleOffer, setRuleOffer] = useState<{ offer: RuleOffer; filed?: { folder: string; name: string } } | null>(null);
  /** "Make a rule…" / "Update rule …" and "Not for these", on the filed toast. */
  const offerActions = (offer: RuleOffer, requests: FileRequest[]): ToastAction[] => {
    const request = requests.find((r) => r.drive_id === offer.drive_id);
    const filed = request ? { folder: request.folder, name: request.name } : undefined;
    return [
      {
        label: offer.kind === "update" ? `Update rule ${offer.rule_id}…` : "Make a rule…",
        run: () => {
          if (dialogOpen()) return;
          setRuleOffer({ offer, filed });
        },
      },
      {
        label: "Not for these",
        run: () => {
          if (dialogOpen()) return;
          declineRule.mutate(
            offer.draft.words.filter((w) => w.ticked).map((w) => w.word),
            { onError: (e) => toast({ kind: "error", text: `Could not save that: ${errorText(e)}` }) },
          );
        },
      },
    ];
  };

  const filing = useFiling((result, complete, requests) => {
    const added = addedTo(result, requests, trayList);
    if (result.done.length > 0) {
      const target = { batchId: result.batch_id };
      setLastApplied(target);
      const text = `${summary(result)}${added}`;
      toast({
        kind: complete ? "info" : "warning",
        text: complete ? text : `Partly applied: ${text}`,
        action: {
          label: "Undo",
          run: () => {
            // Belt and braces: the button is disabled in these states anyway.
            if (filing.inFlight.current || undo.undoing.current || dialogOpen()) return;
            undo.open(target);
          },
        },
        actions: result.offer ? offerActions(result.offer, requests) : undefined,
      });
    } else if (complete) {
      toast({ kind: "info", text: `No file changes needed.${added}` });
    }
    const requested = new Set(requests.map((r) => r.drive_id));
    if (requested.size > 1 || checked.size > 0) {
      // Batch: uncheck what was filed (everything, unless the batch stopped part way).
      const filed = complete
        ? requested
        : new Set(result.done.map((op) => op.drive_id).filter((id): id is string => !!id));
      setChecked((old) => new Set([...old].filter((id) => !filed.has(id))));
    } else if (complete) {
      // Advance: the next entry, or the previous one when this was the last.
      const next = entries[index + 1] ?? entries[index - 1];
      setSelectedId(next ? next.record.drive_id : null);
    }
  }, (id) => entries.find((e) => e.record.drive_id === id)?.prefill);
  // Trash (⌫, the card's bin, Quick Look): the batch, else the entry on screen. Like
  // filing, a trashed entry is left behind for the next one; a batch is unticked.
  const trash = useTrash({
    onTrashed: (ids) => {
      const gone = new Set(ids);
      if (gone.size === 0) return;
      if (checked.size > 0) {
        setChecked((old) => new Set([...old].filter((id) => !gone.has(id))));
      } else if (current && gone.has(current.record.drive_id)) {
        const next = entries.slice(index + 1).find((e) => !gone.has(e.record.drive_id))
          ?? entries.slice(0, index).reverse().find((e) => !gone.has(e.record.drive_id));
        setSelectedId(next ? next.record.drive_id : null);
      }
    },
  });
  const targets = batch.length > 0 ? batch.map((e) => e.record.drive_id) : current ? [current.record.drive_id] : [];
  const targetsRef = useRef(targets);
  targetsRef.current = targets; // a dry run for other entries than these is dropped
  const locked = filing.busy || filing.inFlight.current || trash.busy;

  // Assign a filing code (c, or the toolbar button) to the selection or the current file.
  const filingCodes = useFilingCodes().data?.codes ?? [];
  const assign = useAssignCode();
  const [codeAnchor, setCodeAnchor] = useState<HTMLButtonElement | null>(null);
  const [picking, setPicking] = useState(false);
  const canAssign = !markedOpen && targets.length > 0 && filingCodes.length > 0;
  const targetEntries = entries.filter((e) => targets.includes(e.record.drive_id));
  const pickCode = (code: string | null) => {
    setPicking(false);
    // each file's code before, for Undo (files that had the same one go back together)
    const before = new Map<string | null, string[]>();
    for (const e of targetEntries) {
      const was = assignedOf(e);
      before.set(was, [...(before.get(was) ?? []), e.record.drive_id]);
    }
    const ids = targetEntries.map((e) => e.record.drive_id);
    const what = ids.length > 1 ? plural(ids.length, "file") : visible(targetEntries[0]?.suggestion.name ?? "");
    assign.mutate(
      { driveIds: ids, code },
      {
        onSuccess: () =>
          toast({
            kind: "info",
            text: code ? `Gave ${what} filing code ${code}.` : `Took the filing code off ${what}.`,
            action: {
              label: "Undo",
              run: () => {
                for (const [was, back] of before) assign.mutate({ driveIds: back, code: was });
              },
            },
          }),
        onError: (e) => toast({ kind: "error", text: `Could not set the filing code: ${errorText(e)}` }),
      },
    );
  };
  const trashTargets = () => {
    // the panel hides the selection: never act on what is not on screen
    if (markedOpen) return;
    if (locked || filing.inFlight.current || undo.undoing.current || targets.length === 0) return;
    const shown = batch.length > 0 ? batch : current ? [current] : [];
    trash.start(targets, { current: () => targetsRef.current, links: shown.some((e) => e.record.is_link) });
  };
  useBlockToastActions(locked || undo.pending || filing.confirm !== null || undo.target !== null);

  // An error for files that have left the inbox has no card to show on: make it a toast.
  const names = useRef(new Map<string, string>());
  for (const e of entries) names.current.set(e.record.drive_id, e.record.name ?? e.record.path);
  const message = filing.message;
  const { dismissMessage } = filing;
  useEffect(() => {
    if (!message || !inbox.data) return;
    const present = new Set(inbox.data.map((e) => e.record.drive_id));
    if (message.ids.some((id) => present.has(id))) return;
    const files = message.ids.map((id) => names.current.get(id) ?? id).join(", ");
    toast({ kind: message.kind === "error" ? "error" : "info", text: `${files}: ${message.text}` });
    dismissMessage();
  }, [message, inbox.data, toast, dismissMessage]); // toast and dismissMessage are stable

  // The list scrolls on its own: keep the selected entry in view as j/k move it.
  const listRef = useRef<HTMLUListElement>(null);
  const currentId = current?.record.drive_id;
  const currentIdRef = useRef(currentId);
  currentIdRef.current = currentId;
  useEffect(() => {
    listRef.current?.querySelector("li.selected")?.scrollIntoView({ block: "nearest" });
  }, [currentId]);

  const select = (id: string | null) => {
    if (locked) return; // never leave an entry while its file call is in flight
    setSelectedId(id);
  };
  const step = (delta: number) => {
    const target = entries[Math.max(0, Math.min(entries.length - 1, index + delta))];
    if (target) select(target.record.drive_id);
  };

  // The viewer window (if it follows the selection) shows the current entry.
  useEffect(() => {
    if (currentId) publishSelection(currentId);
  }, [currentId]);

  const qlFiles = useMemo<QLFile[]>(
    () =>
      entries.map((e) => ({
        drive_id: e.record.drive_id,
        name: e.record.name,
        path: e.record.path,
        ext: e.record.ext,
        is_link: e.record.is_link,
        scanned: scannedFields(e),
      })),
    [entries],
  );
  const quickLook = useQuickLook(
    qlFiles,
    index,
    (i) => {
      const target = entries[i];
      if (target) select(target.record.drive_id);
    },
    // Not while a file call is in flight: its result belongs to the entry on screen.
    {
      canOpen: () => !(filing.busy || filing.inFlight.current || undo.undoing.current || trash.running()),
      trashBusy: trash.busy,
      onTrash: (file, ui) => {
        if (filing.inFlight.current || undo.undoing.current) return;
        trash.start([file.drive_id], {
          current: () => (currentIdRef.current ? [currentIdRef.current] : null),
          links: !!file.is_link,
          onConfirming: ui.close,
          onRefused: ui.report,
        });
      },
    },
  );

  /** Select the entries from the anchor (else the current one) to ``i``: one entry on
   * its own is shown alone, several show the batch form. ⇧-click and ⇧↑/⇧↓. */
  const selectRange = (i: number) => {
    const anchor = entries.findIndex((x) => x.record.drive_id === anchorId);
    const from = anchor >= 0 ? anchor : index;
    if (anchor < 0 && currentId) setAnchorId(currentId);
    const [lo, hi] = from <= i ? [from, i] : [i, from];
    const range = entries.slice(lo, hi + 1).map((x) => x.record.drive_id);
    setChecked(new Set(range.length > 1 ? range : []));
    setSelectedId(entries[i].record.drive_id);
  };

  /** A click on a row: plain selects it alone, ⌘ adds or takes it out, ⇧ selects the
   * range from the anchor. Several selected show the batch form; one left is shown on
   * its own again. */
  const clickRow = (e: MouseEvent, i: number) => {
    if (locked) return;
    if (markedOpen) setSearch({}); // the clicked file is shown in the form
    const id = entries[i].record.drive_id;
    if (e.shiftKey) {
      selectRange(i);
      return;
    }
    setAnchorId(id);
    if (e.metaKey || e.ctrlKey) {
      const next = new Set(checked.size > 0 ? checked : currentId ? [currentId] : []);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      if (next.size > 1) {
        setChecked(next);
        setSelectedId(id);
      } else {
        setChecked(new Set());
        setSelectedId(next.size === 1 ? [...next][0] : id);
      }
      return;
    }
    setChecked(new Set());
    setSelectedId(id);
  };

  useKeydown((e) => {
    if (e.key === "Escape" && isTyping(e.target)) {
      (e.target as HTMLElement).blur();
      return;
    }
    if (isTrashKey(e)) {
      // the focused list (or nothing focused): never from the card's fields or buttons
      const target = e.target instanceof Element ? e.target : null;
      if (target && target !== document.body && !target.closest(".inbox-list")) return;
      e.preventDefault();
      trashTargets();
      return;
    }
    if (isShortcut(e) && e.key === "c" && !e.shiftKey) {
      if (!canAssign || locked) return;
      e.preventDefault();
      setPicking(true);
      return;
    }
    if (!isShortcut(e) || !["j", "k", "J", "K", "u", "ArrowDown", "ArrowUp"].includes(e.key)) return;
    // The marked panel shows no selection: moving it would act on a hidden file.
    if (markedOpen && e.key !== "u") return;
    // ↑/↓ keep their own meaning in a control (a segmented choice, a list box).
    // ↑/↓ keep their own meaning in a control, and scroll the preview and the inspector.
    if (
      e.key.startsWith("Arrow") &&
      e.target instanceof Element &&
      e.target.closest("button:not([data-inbox-entry]), select, [role=option], .preview-pane, .inspector")
    ) {
      return;
    }
    e.preventDefault();
    if (locked || undo.undoing.current) return;
    const down = e.key === "j" || e.key === "J" || e.key === "ArrowDown";
    const up = e.key === "k" || e.key === "K" || e.key === "ArrowUp";
    if (down || up) {
      const target = entries[Math.max(0, Math.min(entries.length - 1, index + (down ? 1 : -1)))];
      if (!target) return;
      // ⇧↑/⇧↓ grow or shrink the selection from the anchor, as ⇧-click does; a plain
      // move starts the next range where it lands.
      if (e.shiftKey) selectRange(entries.indexOf(target));
      else {
        setAnchorId(target.record.drive_id);
        step(down ? 1 : -1);
      }
    } else if (lastApplied) undo.open(lastApplied);
    else toast({ kind: "info", text: "Nothing to undo." });
  });

  const toggle = (id: string) => {
    if (locked) return;
    if (markedOpen) setSearch({}); // the batch form shows the ticked files
    setChecked((old) => {
      const next = new Set(old);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  if (inbox.isPending) return <p className="placeholder">Loading inbox…</p>;
  if (inbox.isError) {
    return (
      <p className="error" role="alert">
        Could not load the inbox. {errorText(inbox.error)}
      </p>
    );
  }

  const multi = checked.size > 0;
  return (
    <div className="inbox" ref={split.hostRef} style={split.hostStyle}>
      <nav className="inbox-list" aria-label="Inbox" {...addFiles.drop.props}>
        <Toolbar
          title="Inbox"
          subtitle={plural(entries.length, "file")}
          actions={
            <>
              {marked > 0 && (
                <button
                  type="button"
                  className="marked-open"
                  aria-pressed={markedOpen}
                  disabled={locked}
                  title="File every inbox file with a filing code, in one batch"
                  onClick={() => setSearch({ marked: "1" })}
                >
                  File {marked} marked
                </button>
              )}
              {readingCodes && (
                <span className="reading-codes" role="status">
                  Reading filing codes…
                </span>
              )}
              <button
                ref={setCodeAnchor}
                type="button"
                className="icon-button"
                aria-label="Assign a filing code…"
                aria-expanded={picking}
                data-tip={canAssign ? "Assign a filing code… c" : "No file to give a filing code"}
                disabled={!canAssign || locked}
                onClick={() => setPicking((open) => !open)}
              >
                <span className="icon-button-glyph" aria-hidden="true">
                  <QrCode />
                </span>
              </button>
              <IconButton
                icon={<Upload />}
                label="Add files…"
                disabledReason="The inbox folder does not exist yet"
                disabled={addFiles.busy || status.data?.inbox_exists === false}
                onClick={addFiles.choose}
              />
            </>
          }
        />
        {entries.length === 0 ? (
          <InboxEmpty
            inbox={status.data?.special_folders?.inbox ?? "the inbox folder"}
            exists={status.data?.inbox_exists !== false}
            onChoose={addFiles.choose}
            choosing={addFiles.busy}
            onSetup={setupFolders.open}
          />
        ) : (
          <ul ref={listRef} className="inbox-entries">
            {entries.map((e, i) => {
              const id = e.record.drive_id;
              const name = e.record.name ?? e.record.path;
              const isChecked = checked.has(id);
              const cls = [i === index && "selected", isChecked && "checked", (multi ? isChecked : i === index) && "highlighted"]
                .filter(Boolean)
                .join(" ");
              const date = e.record.mtime ? shortDate(e.record.mtime) : "";
              // the file's own name first: a suggested name is only that until it is filed
              const suggested = e.suggestion.name !== name ? e.suggestion.name : null;
              return (
                <li
                  key={id}
                  className={cls || undefined}
                  draggable
                  onDragStart={(ev) => {
                    const ids = dragSelection([...checked], id);
                    const pathOf = new Map(entries.map((x) => [x.record.drive_id, x.record.path]));
                    const paths = ids.map((d) => pathOf.get(d)).filter((p): p is string => p !== undefined);
                    setDragFiles(ev, ids, visible(name), paths);
                  }}
                >
                  <input
                    type="checkbox"
                    aria-label={`Select ${visible(name)}`}
                    checked={isChecked}
                    disabled={filing.busy}
                    onChange={() => toggle(id)}
                  />
                  <button
                    type="button"
                    data-inbox-entry
                    data-quicklook
                    aria-current={i === index ? "true" : undefined}
                    onClick={(ev) => clickRow(ev, i)}
                  >
                    <Thumb record={e.record} />
                    <span className="entry-text">
                      <span className="entry-name">
                        {visible(name)}
                        <MarkIcons marks={e.record.marks} driveId={id} path={e.record.path} />
                      </span>
                      <span className="entry-meta">
                        {date}
                        {date && suggested && " · "}
                        {suggested && <>Suggested: {visible(suggested)}</>}
                      </span>
                      <ScanChip prefill={e.prefill} today={today} />
                      <CodeBadge codes={e.suggestion.codes} />
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        )}
        <KeyHints hints={KEYS} />
      </nav>
      <Splitter split={split} label="Resize the list" />
      <section className="inbox-card" aria-label="Review">
        {markedOpen ? (
          <MarkedBatch
            entries={entries}
            trays={trayList}
            filing={filing}
            onOpen={(id) => {
              if (locked) return;
              setChecked(new Set());
              setSelectedId(id);
              setSearch({});
            }}
            onClose={() => setSearch({})}
          />
        ) : batch.length > 0 ? (
          <BatchCard
            entries={batch}
            filing={filing}
            trash={{ run: trashTargets, busy: trash.busy }}
            onAdded={(ids) => setChecked((old) => new Set([...old].filter((id) => !ids.includes(id))))}
          />
        ) : current ? (
          <ReviewCard
            // an assigned code refills the form, as for a file that arrived with it
            key={`${current.record.drive_id}:${assignedOf(current) ?? ""}`}
            entry={current}
            filing={filing}
            trash={{ run: trashTargets, busy: trash.busy }}
          />
        ) : null}
      </section>
      {picking && canAssign && (
        <CodePicker
          anchor={codeAnchor}
          codes={filingCodes}
          count={targetEntries.length}
          canClear={targetEntries.some((e) => assignedOf(e) !== null)}
          onPick={pickCode}
          onClose={() => setPicking(false)}
        />
      )}
      {quickLook.view}
      {trash.view}
      {ruleOffer && (
        <OfferRuleSheet
          key={`${ruleOffer.offer.drive_id}-${ruleOffer.offer.draft.id}`}
          offer={ruleOffer.offer}
          filed={ruleOffer.filed}
          onClose={() => setRuleOffer(null)}
        />
      )}
      {addFiles.view}
      {setupFolders.view}
      {filing.confirm && (
        <ConfirmPlan
          planKey={snapshotKey(filing.confirm.requests)}
          ops={filing.confirm.ops}
          // a marked batch names each file's own tags in its line
          tags={markedOpen ? undefined : uniqueTags(filing.confirm.requests)}
          followUps={
            markedOpen
              ? markedFollowUps(filing.confirm.requests, trayList)
              : followUpLines(filing.confirm.requests, trayList, filing.confirm.prefill)
          }
          busy={filing.busy}
          confirmLabel="File"
          onConfirm={filing.confirmApply}
          onCancel={filing.cancel}
        />
      )}
    </div>
  );
}
