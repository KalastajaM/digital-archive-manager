/** Tray settings the shipped defaults have and the user's tray file lacks (a new field,
 * a copy button, Today's total). The banner names them; the sheet lists each one with
 * a checkbox (all checked), shows the file and the diff of exactly the checked ones,
 * and adds only those: the server re-checks that the file and the result are still
 * the texts shown, and keeps a backup. Unchecked ones can be dismissed ("Don't offer
 * these"), and dismissed ones offered again. */
import { Settings2 } from "lucide-react";
import { type CSSProperties, useMemo, useRef, useState } from "react";
import {
  errorText,
  type TrayDef,
  type TrayDefaultAdded,
  useTrayDefaults,
  useTrayDefaultsChange,
} from "../api/client";
import { fieldLabel, plural } from "../format";
import { visible, visibleText } from "../text";
import { useToast } from "./Toasts";
import { Sheet } from "./ui/Sheet";

const ATTR: Record<string, (field: string) => string> = {
  copy: (f) => `copy button on ${f}`,
  prefill: (f) => `prefill for ${f}`,
  required: (f) => `${f} required`,
  default: (f) => `default for ${f}`,
  type: (f) => `type of ${f}`,
};

const TOP: Record<string, string> = {
  summary: "total on Today",
  "done.fields": "fields asked when done",
  "done.label": "done button label",
  date_field: "date field",
  reminders: "reminders",
  item_title: "item title pattern",
};

/** A default key path as words: "fields.payee" → "Payee field", "fields.amount.copy" →
 * "copy button on Amount", "summary" → "total on Today". */
export function settingName(path: string): string {
  if (TOP[path]) return TOP[path];
  const parts = path.split(".");
  if (parts[0] === "fields" && parts.length === 2) return `${fieldLabel(parts[1])} field`;
  if (parts[0] === "fields" && parts.length === 3) {
    const field = fieldLabel(parts[1]);
    return ATTR[parts[2]]?.(field) ?? `${parts[2].replace(/_/g, " ")} on ${field}`;
  }
  if (parts[0] === "done" && parts[1] === "fields" && parts.length === 3) {
    return `${fieldLabel(parts[2])} field when done`;
  }
  return path.replace(/[._]/g, " ");
}

/** The checkboxes' width in the list; the value and problem lines are indented by it. */
const CHECK_PX = 14;
const CHECK_WIDTH = { "--check-width": `${CHECK_PX}px` } as CSSProperties;

const capital = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

/** "Payee field, copy button on Amount" */
export const settingList = (paths: string[]) => capital(paths.map(settingName).join(", "));

type DiffLine = { kind: "same" | "add" | "remove"; text: string };

/** A line diff (longest common subsequence; tray files are small). */
export function lineDiff(before: string, after: string): DiffLine[] {
  const a = before.split("\n");
  const b = after.split("\n");
  const n = a.length;
  const m = b.length;
  const lcs: number[][] = Array.from({ length: n + 1 }, () => new Array<number>(m + 1).fill(0));
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      lcs[i][j] = a[i] === b[j] ? lcs[i + 1][j + 1] + 1 : Math.max(lcs[i + 1][j], lcs[i][j + 1]);
    }
  }
  const out: DiffLine[] = [];
  let i = 0;
  let j = 0;
  while (i < n || j < m) {
    if (i < n && j < m && a[i] === b[j]) {
      out.push({ kind: "same", text: a[i] });
      i++;
      j++;
    } else if (j < m && (i === n || lcs[i][j + 1] >= lcs[i + 1][j])) {
      out.push({ kind: "add", text: b[j++] });
    } else {
      out.push({ kind: "remove", text: a[i++] });
    }
  }
  return out;
}

const MARK = { same: "  ", add: "+ ", remove: "- " } as const;

function Diff({ before, after }: { before: string; after: string }) {
  const lines = useMemo(() => lineDiff(before, after), [before, after]);
  return (
    <pre className="defaults-diff" data-testid="defaults-diff">
      {lines.map((l, i) => (
        <span key={i} className={`diff-${l.kind}`}>
          {MARK[l.kind]}
          {visibleText(l.text)}
        </span>
      ))}
    </pre>
  );
}

const valueText = (value: unknown) => {
  try {
    return JSON.stringify(value) ?? String(value);
  } catch {
    return String(value);
  }
};

const sameList = (a: string[], b: string[]) => a.length === b.length && a.every((x, i) => x === b[i]);

function DefaultsSheet({ tray, onClose }: { tray: TrayDef; onClose: () => void }) {
  const base = useTrayDefaults(tray.id, null);
  const added: TrayDefaultAdded[] = base.data?.added ?? [];
  const dismissed = base.data?.dismissed ?? [];
  // Unchecked, not checked: an item offered again later arrives checked.
  const [unchecked, setUnchecked] = useState<Set<string>>(new Set());
  const chosen = added.filter((a) => !unchecked.has(a.path)).map((a) => a.path);
  const leftOut = added.filter((a) => unchecked.has(a.path)).map((a) => a.path);
  // Off from the Update click on: once applied, the chosen keys are no longer missing
  // and asking for that subset again would only answer 400 (back on if it failed).
  const [applying, setApplying] = useState(false);
  const subset = useTrayDefaults(tray.id, chosen, chosen.length > 0 && !applying);
  const change = useTrayDefaultsChange();
  const toast = useToast();
  const inFlight = useRef(false); // synchronous: a second click in the same batch sees it
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [showDismissed, setShowDismissed] = useState(dismissed.length > 0 && added.length === 0);

  const diff = subset.data;
  const current = diff && !subset.isPlaceholderData && !subset.isFetching && sameList(diff.paths, chosen) ? diff : null;
  const whyNot =
    chosen.length === 0
      ? "Check at least one setting to add"
      : !current
        ? "Preparing the update…"
        : current.error
          ? "These cannot be added together"
          : null;

  async function run(work: () => Promise<void>) {
    if (inFlight.current) return;
    inFlight.current = true;
    setBusy(true);
    setProblem(null);
    try {
      await work();
    } catch (e) {
      setProblem(errorText(e));
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  }

  const update = () => {
    if (!current || whyNot) return;
    const shown = current;
    if (inFlight.current) return;
    setApplying(true);
    void run(async () => {
      try {
        await change.mutateAsync({
          op: "apply",
          trayId: tray.id,
          paths: shown.paths,
          expect_current_text: shown.current_text,
          expect_new_text: shown.new_text,
        });
      } catch (e) {
        setApplying(false);
        throw e;
      }
      toast({ kind: "info", text: "Tray settings updated (backup saved)" });
      onClose();
    });
  };
  const dismiss = () => {
    const paths = leftOut;
    if (paths.length === 0) return;
    void run(async () => {
      await change.mutateAsync({ op: "dismiss", trayId: tray.id, paths });
      setUnchecked(new Set());
    });
  };
  const undismiss = (path: string) =>
    void run(async () => {
      await change.mutateAsync({ op: "undismiss", trayId: tray.id, paths: [path] });
    });
  const toggle = (path: string) =>
    setUnchecked((old) => {
      const next = new Set(old);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });

  const file = base.data?.file;
  return (
    <Sheet
      open
      className="tray-defaults"
      title={`Update ${visible(tray.name)} settings`}
      onClose={onClose}
      footer={
        <>
          <button type="button" onClick={onClose}>
            Cancel
          </button>
          <button type="button" disabled={busy || leftOut.length === 0} onClick={dismiss}>
            Don't offer these
          </button>
          <span className="button-wrap" data-tip={busy ? "Still saving the last change" : (whyNot ?? undefined)}>
            <button type="button" className="primary" disabled={busy || whyNot !== null} onClick={update}>
              Update
            </button>
          </span>
        </>
      }
    >
      {base.isError ? (
        <p className="error" role="alert">
          Could not compare with the defaults: {visible(errorText(base.error))}
        </p>
      ) : added.length === 0 ? (
        <p className="placeholder">{base.isPending ? "Loading…" : "Nothing is missing from this tray."}</p>
      ) : (
        <>
          <p>
            Checked settings are added to <code>config/trays/{visible(file ?? "")}</code>. Your own values are kept; a
            backup of the file is saved first.
          </p>
          <ul className="defaults-list" aria-label="Missing settings" style={CHECK_WIDTH}>
            {added.map((a) => (
              <li key={a.path}>
                <label>
                  <input type="checkbox" checked={!unchecked.has(a.path)} onChange={() => toggle(a.path)} />{" "}
                  {capital(settingName(a.path))}
                </label>
                <code className="defaults-value">{visible(`${a.path}: ${valueText(a.value)}`)}</code>
                {a.problem && <p className="defaults-problem">{visible(a.problem)}</p>}
              </li>
            ))}
          </ul>
          {current?.error && (
            <p className="defaults-problem">Can't add these together: {visible(current.error)}</p>
          )}
          {diff && chosen.length > 0 && (
            <details className={current ? "defaults-diff-box" : "defaults-diff-box preparing"} open>
              <summary>
                The change to {visible(diff.file)}
                {!current && (
                  <span className="defaults-preparing" role="status">
                    {" "}
                    · Preparing…
                  </span>
                )}
              </summary>
              <Diff before={diff.current_text} after={diff.new_text} />
            </details>
          )}
        </>
      )}
      {problem && (
        <p className="error" role="alert">
          {visible(problem)}
        </p>
      )}
      {dismissed.length > 0 && (
        <div className="defaults-dismissed">
          <button
            type="button"
            className="link-button"
            aria-expanded={showDismissed}
            onClick={() => setShowDismissed((s) => !s)}
          >
            {showDismissed ? "Hide dismissed" : `Show dismissed (${dismissed.length})`}
          </button>
          {showDismissed && (
            <ul aria-label="Dismissed settings">
              {dismissed.map((path) => (
                <li key={path}>
                  {capital(settingName(path))}{" "}
                  <button
                    type="button"
                    className="link-button"
                    disabled={busy}
                    aria-label={`Offer ${capital(settingName(path))} again`}
                    onClick={() => undismiss(path)}
                  >
                    Offer again
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </Sheet>
  );
}

/** Above the tray's list: what its file is missing, or (nothing missing, some
 * dismissed) a small link to the dismissed ones. Nothing while loading or on error. */
export function TrayDefaultsBanner({ tray }: { tray: TrayDef }) {
  const diff = useTrayDefaults(tray.id, null);
  const [open, setOpen] = useState(false);
  const added = diff.data?.added ?? [];
  const dismissed = diff.data?.dismissed ?? [];
  const sheet = open && <DefaultsSheet tray={tray} onClose={() => setOpen(false)} />;
  if (added.length > 0) {
    return (
      <>
        <section className="banner tray-defaults-banner" aria-label="Tray settings">
          <Settings2 className="banner-icon" size={16} aria-hidden="true" />
          <p>
            Your {visible(tray.name)} settings are missing: {visible(settingList(added.map((a) => a.path)))}
          </p>
          <button type="button" onClick={() => setOpen(true)}>
            Update tray settings…
          </button>
        </section>
        {sheet}
      </>
    );
  }
  if (dismissed.length > 0) {
    return (
      <>
        <p className="hint tray-defaults-dismissed">
          <button type="button" className="link-button" onClick={() => setOpen(true)}>
            Show dismissed tray settings
          </button>{" "}
          ({plural(dismissed.length, "setting")} not offered)
        </p>
        {sheet}
      </>
    );
  }
  return null;
}
