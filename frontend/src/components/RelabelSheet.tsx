/** Settings → Archive folders → Change label: the new label, then what changes (index and
 * journal entries, the settings and rule files), then the change. Nothing on the disk
 * changes; the server takes a snapshot first and reopens the archive under the new label. */
import { CircleAlert } from "lucide-react";
import { useState } from "react";
import { type ArchiveFolder, errorText, type Relabel, relabelArchiveFolder } from "../api/client";
import { plural } from "../format";
import { visible } from "../text";
import { Sheet } from "./ui/Sheet";

export function relabelSummary(r: Relabel): string {
  const parts = [plural(r.counts.files ?? 0, "index entry", "index entries"), plural(r.counts.operations ?? 0, "journal entry", "journal entries")];
  if (r.files.length > 0) parts.push(`${plural(r.files.length, "file")} (${r.files.map((f) => visible(f.name)).join(", ")})`);
  const last = parts.pop();
  return `Changes ${parts.length > 0 ? `${parts.join(", ")} and ${last}` : last}. Nothing on the disk changes.`;
}

export function RelabelSheet({ folder, onClose, onDone }: { folder: ArchiveFolder; onClose: () => void; onDone: (r: Relabel) => void }) {
  const label = folder.label ?? "";
  const [next, setNext] = useState("");
  const [checked, setChecked] = useState<Relabel | null>(null);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const submit = async () => {
    setBusy(true);
    setProblem(null);
    try {
      if (checked === null) setChecked(await relabelArchiveFolder(label, next.trim(), true));
      else onDone(await relabelArchiveFolder(label, next.trim(), false));
    } catch (e) {
      setProblem(errorText(e));
    }
    setBusy(false);
  };
  return (
    <Sheet
      open
      title={`Change the label of '${visible(label)}'`}
      onClose={() => !busy && onClose()}
      footer={
        <>
          <button type="button" onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button type="button" className="primary" disabled={!next.trim() || busy} onClick={() => void submit()}>
            {checked === null ? "Preview" : "Change label"}
          </button>
        </>
      }
    >
      <p className="first-run-hint">
        The label is the name the folder has at the top of Browse and at the start of its paths. Its files, tags and notes stay as they are.
      </p>
      <div className="field">
        <label htmlFor="relabel-new">New label</label>
        <input
          id="relabel-new"
          type="text"
          value={next}
          autoComplete="off"
          onChange={(e) => {
            setNext(e.target.value);
            setChecked(null);
            setProblem(null);
          }}
        />
      </div>
      {checked && (
        <>
          <p className="first-run-ok" role="status">
            {relabelSummary(checked)}
          </p>
          {checked.warnings.map((w) => (
            <p key={w} className="first-run-hint">
              {visible(w)}
            </p>
          ))}
          <p className="first-run-hint">A snapshot of the database and settings is taken first.</p>
        </>
      )}
      {problem && (
        <p className="first-run-problem" role="alert">
          <CircleAlert size={14} aria-hidden="true" /> {visible(problem)}
        </p>
      )}
    </Sheet>
  );
}
