import { Fragment, type KeyboardEvent, type ReactNode, useEffect, useId, useRef } from "react";
import { X } from "lucide-react";
import { IconButton } from "./ui/IconButton";
import { Sheet } from "./ui/Sheet";
import type { ResolvedOp } from "../api/client";
import { noKeysHeld } from "../keyboard";
import { visible } from "../text";

export const KIND_LABEL: Record<ResolvedOp["kind"], string> = {
  rename: "Rename",
  move: "Move",
  copy: "Copy in",
  mkdir: "New folder",
  symlink: "Link",
  unlink_symlink: "Remove link",
  quarantine: "Move to To Delete",
  remove_empty_dir: "Remove empty folder",
  picture_to_quarantine: "Move to To Delete",
  picture_back: "Put back",
};

/** Ops on one path (a folder made or removed, a link removed): shown with that path
 * alone, never "path → path". */
export const SINGLE_PATH = new Set<ResolvedOp["kind"]>(["mkdir", "remove_empty_dir", "unlink_symlink"]);

/** The file a "copy in" op copies, by its name (the full path of a file on this computer
 * is not an archive path and says little). */
export function copySource(src: string): string {
  const path = src.replace(/^abs:/, "");
  return path.slice(Math.max(path.lastIndexOf("/"), path.lastIndexOf("\\")) + 1);
}

/** The place outside the archive a "put back" op names (``abs:<path>/<file>``): the rules'
 * picture folder, by its file (the full path of this computer is not an archive path). */
export function outsideDestination(dst: string): string {
  return `rules/areas/${copySource(dst)}`;
}

/** A path that wraps only after ``/``, ``_`` or a space (never mid-word). */
export function Breakable({ text }: { text: string }) {
  const parts = visible(text).split(/(?<=[/_ ])/);
  return (
    <>
      {parts.map((part, i) => (
        <Fragment key={i}>
          {i > 0 && <wbr />}
          {part}
        </Fragment>
      ))}
    </>
  );
}

/** The folders two paths share at the start, with their trailing "/" ("" for none). */
export function sharedFolder(a: string, b: string): string {
  const x = a.split("/");
  const y = b.split("/");
  let n = 0;
  while (n < x.length - 1 && n < y.length - 1 && x[n] === y[n]) n++;
  return n === 0 ? "" : `${x.slice(0, n).join("/")}/`;
}

/** One path in ``<code>``; the leading folder it shares with the other end of the op
 * is de-emphasised, so the part that changes stands out. */
function PathCode({ path, shared = "" }: { path: string; shared?: string }) {
  const dim = shared && path.startsWith(shared) ? shared : "";
  return (
    <code>
      {dim && (
        <span className="plan-same">
          <Breakable text={dim} />
        </span>
      )}
      <Breakable text={path.slice(dim.length)} />
    </code>
  );
}

type Shown = { op: ResolvedOp } | { kept: string };

/** A link removed and made again at the same path (what a conversion does to the
 * user's own link when the app takes it over) changes nothing the user can see: the
 * pair becomes one "stays" line. */
export function collapseLinkSwaps(ops: ResolvedOp[]): Shown[] {
  const shown: Shown[] = [];
  const used = new Set<number>();
  ops.forEach((op, i) => {
    if (used.has(i)) return;
    if (op.kind === "unlink_symlink") {
      const path = op.dst || op.src || "";
      const j = ops.findIndex((o, k) => k > i && !used.has(k) && o.kind === "symlink" && o.dst === path);
      if (j >= 0) {
        used.add(j);
        shown.push({ kept: path });
        return;
      }
    }
    shown.push({ op });
  });
  return shown;
}

/** Missing folders made one inside the other on the way to a move (``a``, ``a/b``,
 * ``a/b/c``) are one step to the user: the chain is shown as one line, ``folders``
 * holding each path. */
type Line = Shown | { folders: string[] };

const madeOnTheWay = (s: Shown): s is { op: ResolvedOp } =>
  "op" in s && s.op.kind === "mkdir" && s.op.note === "create missing folder";

function collapseFolderChains(shown: Shown[]): Line[] {
  const out: Line[] = [];
  for (const s of shown) {
    const last = out[out.length - 1];
    const chain = last && "folders" in last ? last.folders : last && madeOnTheWay(last) ? [last.op.dst] : null;
    const deepest = chain?.[chain.length - 1];
    if (chain && deepest && madeOnTheWay(s) && parentOf(s.op.dst) === deepest) {
      out[out.length - 1] = { folders: [...chain, s.op.dst] };
    } else {
      out.push(s);
    }
  }
  return out;
}

const parentOf = (path: string) => (path.includes("/") ? path.slice(0, path.lastIndexOf("/")) : "");

/** Notes that only say what happens anyway (a folder is made on the way). */
const ROUTINE_NOTES = new Set(["create missing folder"]);

type ListProps = {
  ops: ResolvedOp[];
  tags?: string[];
  /** What filing does after the move (tray item, collections, note), one line each. */
  followUps?: string[];
};

/** The resolved operations exactly as the API will carry them out. */
export function PlanList({ ops, tags, followUps }: ListProps) {
  const items = collapseFolderChains(collapseLinkSwaps(ops));
  // One step alone is a sentence, not a list: a lone "1." reads like a step number
  const single = items.length === 1;
  const row = (i: number, className: string, content: ReactNode) =>
    single ? (
      <p key={i} className={`plan plan-single ${className}`}>
        {content}
      </p>
    ) : (
      <li key={i} className={className}>
        {content}
      </li>
    );
  const rows = items.map((item, i) => {
    if ("kept" in item) {
      return row(
        i,
        "plan-op",
        <>
          <code>
            <Breakable text={item.kept} />
          </code>{" "}
          stays; the app now manages this link
        </>,
      );
    }
    if ("folders" in item) {
      return row(
        i,
        "plan-op",
        <>
          <span className="plan-kind">New folders</span>
          <PathCode path={item.folders[item.folders.length - 1]} />
          <span className="plan-note plan-note-routine"> ({item.folders.length} missing folders)</span>
        </>,
      );
    }
    const op = item.op;
    const routine = op.note !== null && ROUTINE_NOTES.has(op.note);
    return row(
      i,
      op.note && !routine ? "plan-op plan-noted" : "plan-op",
      <>
        <span className="plan-kind">{KIND_LABEL[op.kind]}</span>
        {SINGLE_PATH.has(op.kind) ? (
          <PathCode path={op.dst || op.src || ""} />
        ) : (
          <>
            {op.src && op.src.startsWith("abs:") ? (
              <>
                <code>
                  <Breakable text={copySource(op.src)} />
                </code>
                <span aria-hidden="true"> → </span>
              </>
            ) : (
              op.src && (
                <>
                  <PathCode path={op.src} shared={sharedFolder(op.src, op.dst)} />
                  <span aria-hidden="true"> → </span>
                </>
              )
            )}
            {op.dst.startsWith("abs:") ? (
              <PathCode path={outsideDestination(op.dst)} />
            ) : (
              <PathCode path={op.dst} shared={op.src && !op.src.startsWith("abs:") ? sharedFolder(op.src, op.dst) : ""} />
            )}
          </>
        )}
        {op.note && <span className={routine ? "plan-note plan-note-routine" : "plan-note"}> ({op.note})</span>}
      </>,
    );
  });
  return (
    <>
      {ops.length === 0 ? <p>No file changes.</p> : single ? rows : <ol className="plan">{rows}</ol>}
      {tags && tags.length > 0 && <p>Tags: {tags.map(visible).join(", ")}</p>}
      {followUps?.map((line) => (
        <p key={line}>{visible(line)}</p>
      ))}
    </>
  );
}

/** Inline result of "Preview": ``onClose`` puts an × in its corner, ``action`` (the
 * screen's own step, such as File it) goes under the plan. */
export function PlanPreview({ onClose, action, ...props }: ListProps & { onClose?: () => void; action?: ReactNode }) {
  const headingId = useId();
  return (
    <section className="plan-preview" aria-labelledby={headingId}>
      <div className="plan-preview-head">
        <h3 id={headingId}>Planned changes</h3>
        {onClose && <IconButton icon={<X size={14} />} label="Close the preview" className="tip-end" onClick={onClose} />}
      </div>
      <PlanList {...props} />
      {action && <div className="plan-preview-action">{action}</div>}
    </section>
  );
}

/** Cmd+Enter confirms only once the dialog has been visible this long, so a reflexive
 * second press right after the one that opened it can never apply the plan. */
export const CONFIRM_KEY_DELAY_MS = 500;

/** A short stable key for a plan's request snapshot: equal JSON, equal key. */
export function snapshotKey(value: unknown): string {
  const text = JSON.stringify(value);
  let hash = 0x811c9dc5; // FNV-1a, 32 bit
  for (let i = 0; i < text.length; i++) {
    hash ^= text.charCodeAt(i);
    hash = Math.imul(hash, 0x01000193);
  }
  return `${(hash >>> 0).toString(16)}-${text.length}`;
}

/** The keyboard arming of a confirm sheet (``ConfirmPlan``, the AI ``SendSheet``), from
 * the moment the component using it mounts: put ``cancelRef`` on Cancel (it gets the
 * focus) and ``onKeyDown`` on the sheet. Esc cancels; a plain Return on Cancel does
 * nothing (it would silently dismiss the sheet). Cmd+Enter confirms only when both
 * hold: mounted for ``CONFIRM_KEY_DELAY_MS``, and no key was down at mount (or a key
 * has been released since); never while ``busy``. Remount (a ``key``) to arm anew. */
export function useArmedConfirm({
  onConfirm,
  onCancel,
  busy,
}: {
  onConfirm: () => void;
  onCancel: () => void;
  busy?: boolean;
}) {
  const cancelRef = useRef<HTMLButtonElement>(null);
  const released = useRef(false); // no key held at open, or a keyup seen since
  const openedAt = useRef(Infinity);
  // The Sheet opens the <dialog> (its effect runs first, being the child); this one arms
  // the keyboard confirm and puts the focus on Cancel.
  useEffect(() => {
    released.current = noKeysHeld();
    openedAt.current = performance.now();
    cancelRef.current?.focus(); // the safe choice has the focus, never the confirm
    const onKeyup = () => {
      released.current = true;
    };
    document.addEventListener("keyup", onKeyup);
    return () => document.removeEventListener("keyup", onKeyup);
  }, []);
  const onKeyDown = (e: KeyboardEvent<HTMLDialogElement>) => {
    e.stopPropagation(); // page shortcuts never see keys pressed in the dialog
    if (e.repeat) return;
    if (e.key === "Escape") {
      e.preventDefault();
      onCancel();
    } else if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      const shownLongEnough = performance.now() - openedAt.current >= CONFIRM_KEY_DELAY_MS;
      if (released.current && shownLongEnough && !busy) onConfirm();
    } else if (e.key === "Enter" && e.target === cancelRef.current) {
      e.preventDefault(); // Return means "go ahead" on a Mac: never a silent Cancel
    }
  };
  return { cancelRef, onKeyDown };
}

type DialogProps = {
  ops: ResolvedOp[];
  /** Replaces the plan list (e.g. the undo view). */
  children?: ReactNode;
  tags?: string[];
  followUps?: string[];
  busy?: boolean;
  title?: string;
  intro?: ReactNode;
  confirmLabel?: string;
  /** The confirm button is red: the plan removes something from the app (red is kept
   * for this last step; menus and first steps stay plain). */
  danger?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
};

type ConfirmProps = DialogProps & {
  /** Identifies the plan shown (a batch id, or ``snapshotKey`` of the requests). A
   * different plan remounts the dialog, so the keyboard arming starts over. */
  planKey: string;
};

/** Modal confirm before applying a plan (native <dialog>: focus stays inside).
 *
 * Cancel has the focus, Esc cancels; a plain Return on Cancel does nothing (it would
 * silently dismiss the sheet), and the primary button shows ⌘↩. Cmd+Enter confirms only when both hold: the dialog
 * has been open for ``CONFIRM_KEY_DELAY_MS``, and no key was down when it opened (or a
 * key has been released since). Clicking the confirm button, or Enter/Space on it, always applies. */
export function ConfirmPlan({ planKey, ...props }: ConfirmProps) {
  return <ConfirmDialog key={planKey} {...props} />;
}

function ConfirmDialog({
  ops,
  tags,
  followUps,
  busy,
  title = "Confirm changes",
  intro,
  confirmLabel = "Confirm",
  danger,
  children,
  onConfirm,
  onCancel,
}: DialogProps) {
  const armed = useArmedConfirm({ onConfirm, onCancel, busy });
  return (
    <Sheet
      open
      className="confirm"
      title={title}
      onClose={onCancel}
      onKeyDown={armed.onKeyDown}
      footer={
        <>
          <button ref={armed.cancelRef} type="button" onClick={onCancel} autoFocus>
            Cancel
          </button>
          <button type="button" className={danger ? "primary danger" : "primary"} onClick={onConfirm} disabled={busy}>
            {confirmLabel}
            <span className="button-key" aria-hidden="true">
              ⌘↩
            </span>
          </button>
        </>
      }
    >
      {intro}
      {children ?? <PlanList ops={ops} tags={tags} followUps={followUps} />}
    </Sheet>
  );
}
