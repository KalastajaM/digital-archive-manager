/** Settings → Filing codes: the table of codes (a file gets one from the code's inbox
 * folder or its QR sticker) and what each one files as. The table is saved whole (the old file is kept as a backup). Entries
 * of the file that could not be loaded (``problems``) are not in the table, so saving drops
 * them from the file; that is said next to Save. "Create inbox folders" makes the codes'
 * folders in the inbox, after a preview. */
import { Plus, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import {
  errorText,
  type FilingCode,
  type FilingCodes as FilingCodesData,
  previewCodeFolders,
  type ResolvedOp,
  useCodeFolders,
  useCreateCodeFolders,
  useFilingCodes,
  useSaveFilingCodes,
  useTrays,
} from "../../api/client";
import { visible } from "../../text";
import { FolderPicker } from "../FolderPicker";
import { ConfirmPlan } from "../PlanPreview";
import { IconButton } from "../ui/IconButton";

/** A row being edited: tags and collections as comma-separated text. */
type Draft = {
  key: number;
  code: string;
  label: string;
  tray: string;
  folder: string;
  name: string;
  tags: string;
  collections: string;
  as_suggested: boolean;
  inbox_folder: string;
};

const list = (text: string) =>
  text
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);

let nextKey = 1;
const blank = (): Draft => ({
  key: nextKey++,
  code: "",
  label: "",
  tray: "",
  folder: "",
  name: "",
  tags: "",
  collections: "",
  as_suggested: false,
  inbox_folder: "",
});
const toDraft = (c: FilingCodesData["codes"][number]): Draft => ({
  key: nextKey++,
  code: c.code,
  label: c.label,
  tray: c.tray ?? "",
  folder: c.folder ?? "",
  name: c.name ?? "",
  tags: c.tags.join(", "),
  collections: c.collections.join(", "),
  as_suggested: c.as_suggested,
  inbox_folder: c.inbox_folder ?? "",
});
const toCode = (d: Draft): FilingCode => ({
  code: d.code.trim(),
  label: d.label.trim(),
  tray: d.tray || null,
  folder: d.folder.trim() || null,
  name: d.name.trim() || null,
  tags: list(d.tags),
  collections: list(d.collections),
  as_suggested: d.as_suggested,
  inbox_folder: d.inbox_folder.trim() || null,
});

const GROUPS = ["0OØDQ", "1IL7", "5S", "2Z", "8B", "UV", "6G"];

/** Two codes that differ in exactly one position, by characters that look alike by hand. */
export function confusable(a: string, b: string): boolean {
  const x = a.trim().toUpperCase();
  const y = b.trim().toUpperCase();
  if (!x || x.length !== y.length) return false;
  const diff = [...x].map((c, i) => [c, y[i]] as const).filter(([c, d]) => c !== d);
  return diff.length === 1 && GROUPS.some((g) => g.includes(diff[0][0]) && g.includes(diff[0][1]));
}

/** A name pattern that gives every file the same name: nothing in it changes per file. */
export const fixedName = (pattern: string) =>
  pattern.trim() !== "" && !pattern.includes("{doc_date") && !pattern.includes("{stem}");

export function FilingCodes() {
  const codes = useFilingCodes();
  const trays = useTrays();
  const folders = useCodeFolders();
  const save = useSaveFilingCodes();
  const create = useCreateCodeFolders();
  const [rows, setRows] = useState<Draft[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [plan, setPlan] = useState<ResolvedOp[] | null>(null);
  const loaded = useRef(false);

  // The table is copied into the editor once; later loads (after a save) must not wipe edits.
  useEffect(() => {
    if (codes.data && !loaded.current) {
      loaded.current = true;
      setRows(codes.data.codes.map(toDraft));
    }
  }, [codes.data]);

  if (codes.isError) {
    return (
      <section className="filing-codes" aria-label="Filing codes">
        <h3>Filing codes</h3>
        <p className="error" role="alert">
          {visible(errorText(codes.error))}
        </p>
      </section>
    );
  }
  if (!codes.data || rows === null) {
    return (
      <section className="filing-codes" aria-label="Filing codes">
        <h3>Filing codes</h3>
        <p className="hint">Loading…</p>
      </section>
    );
  }

  const problems = codes.data.problems;
  const trayList = trays.data?.trays ?? [];
  const edit = (key: number, patch: Partial<Draft>) =>
    setRows((rs) => (rs ?? []).map((r) => (r.key === key ? { ...r, ...patch } : r)));

  const doSave = async () => {
    setError(null);
    try {
      const saved = await save.mutateAsync(rows.map(toCode));
      setRows(saved.codes.map(toDraft));
    } catch (e) {
      setError(errorText(e));
    }
  };
  const openPlan = async () => {
    setError(null);
    try {
      setPlan(await previewCodeFolders());
    } catch (e) {
      setError(errorText(e));
    }
  };
  const missing = folders.data?.missing ?? [];
  const stray = folders.data?.stray ?? [];

  return (
    <section className="filing-codes" aria-label="Filing codes">
      <h3>Filing codes</h3>
      <p className="hint">
        A code is a short letter or number. A file gets it when you save it into the code's inbox folder or put the
        code's QR sticker on the paper. It says where the file goes and what it gets. Saved in the filing codes file, with
        a backup of the old one.
      </p>
      <p className="hint">
        A name pattern makes each file's name from its details: <code>{"{doc_date:%Y%m%d}"}</code> is the document's date,{" "}
        <code>{"{year}"}</code> its year and <code>{"{stem}"}</code> the file's own name, so{" "}
        <code>{"{doc_date:%Y%m%d}_Fortum"}</code> gives <code>20261015_Fortum.pdf</code>. It is not used when the file's
        name already starts with a date.
      </p>
      {problems.length > 0 && (
        <div className="banner" role="alert">
          <p>Some entries in the file could not be loaded:</p>
          <ul>
            {problems.map((p, i) => (
              <li key={`${p.code}-${i}`}>
                <code>{visible(p.code)}</code>: {visible(p.message)}
              </li>
            ))}
          </ul>
        </div>
      )}
      <ul className="filing-codes-list">
        {rows.map((r, i) => {
          const same = rows.filter((o) => o.key !== r.key && confusable(r.code, o.code)).map((o) => o.code.trim());
          return (
            <li key={r.key} className="filing-code-row" role="group" aria-label={`Code ${r.code || `row ${i + 1}`}`}>
              <label>
                Code
                <input value={r.code} onChange={(e) => edit(r.key, { code: e.target.value })} maxLength={4} />
              </label>
              <label>
                Label
                <input value={r.label} onChange={(e) => edit(r.key, { label: e.target.value })} maxLength={24} />
              </label>
              <label>
                Tray
                <select value={r.tray} onChange={(e) => edit(r.key, { tray: e.target.value })}>
                  <option value="">No tray</option>
                  {trayList.map((t) => (
                    <option key={t.id} value={t.id}>
                      {visible(t.name)}
                    </option>
                  ))}
                  {r.tray && !trayList.some((t) => t.id === r.tray) && <option value={r.tray}>{visible(r.tray)}</option>}
                </select>
              </label>
              <FolderPicker label="Folder" value={r.folder} onChange={(v) => edit(r.key, { folder: v })} />
              <label>
                Name pattern
                <input
                  value={r.name}
                  placeholder="{doc_date:%Y%m%d}_Fortum"
                  onChange={(e) => edit(r.key, { name: e.target.value })}
                />
              </label>
              <label>
                Tags
                <input value={r.tags} onChange={(e) => edit(r.key, { tags: e.target.value })} />
              </label>
              <label>
                Collections
                <input value={r.collections} onChange={(e) => edit(r.key, { collections: e.target.value })} />
              </label>
              <label>
                Inbox folder
                <input value={r.inbox_folder} onChange={(e) => edit(r.key, { inbox_folder: e.target.value })} />
              </label>
              <label className="check">
                <input
                  type="checkbox"
                  checked={r.as_suggested}
                  onChange={(e) => edit(r.key, { as_suggested: e.target.checked })}
                />
                File as suggested
              </label>
              <IconButton
                icon={<X />}
                label={`Remove code ${r.code || `row ${i + 1}`}`}
                onClick={() => setRows((rs) => (rs ?? []).filter((x) => x.key !== r.key))}
              />
              {!r.as_suggested && fixedName(r.name) && (
                <p className="hint">
                  Every file with this code gets the same name. Add <code>{"{doc_date:%Y%m%d}"}</code> or{" "}
                  <code>{"{stem}"}</code> to tell them apart.
                </p>
              )}
              {same && same.length > 0 && (
                <p className="hint">
                  Easy to confuse with{" "}
                  {same.map((c, j) => (
                    <span key={c}>
                      {j > 0 && ", "}
                      <code>{visible(c)}</code>
                    </span>
                  ))}{" "}
                  if you write codes by hand.
                </p>
              )}
            </li>
          );
        })}
      </ul>
      {(trays.isError || folders.isError) && (
        <p className="error" role="alert">
          {trays.isError && `The trays could not be loaded: ${visible(errorText(trays.error))}. `}
          {folders.isError && `The inbox folders could not be checked: ${visible(errorText(folders.error))}.`}
        </p>
      )}
      {stray.length > 0 && (
        <ul className="filing-codes-stray">
          {stray.map((f) => (
            <li key={f} className="hint">
              <code>{visible(f)}</code>: Not a filing code folder: its files are not in the Inbox.
            </li>
          ))}
        </ul>
      )}
      {problems.length > 0 && (
        <p className="hint" role="note">
          Saving keeps only the codes listed here; the entries with problems above are removed from the file (a backup
          is kept).
        </p>
      )}
      {error && (
        <p className="error" role="alert">
          {visible(error)}
        </p>
      )}
      <div className="filing-codes-actions">
        <button type="button" onClick={() => setRows((rs) => [...(rs ?? []), blank()])}>
          <Plus size={14} aria-hidden="true" /> Add a code
        </button>
        <button type="button" className="primary" disabled={save.isPending} onClick={() => void doSave()}>
          Save
        </button>
        {missing.length > 0 && (
          <button type="button" onClick={() => void openPlan()}>
            Create inbox folders
          </button>
        )}
      </div>
      {plan !== null && (
        <ConfirmPlan
          planKey="create-code-folders"
          title="Create inbox folders"
          ops={plan}
          busy={create.isPending}
          confirmLabel="Create folders"
          onConfirm={async () => {
            try {
              await create.mutateAsync();
              setPlan(null);
            } catch (e) {
              setPlan(null);
              setError(errorText(e));
            }
          }}
          onCancel={() => setPlan(null)}
        />
      )}
    </section>
  );
}
