/** Settings → Filing codes: the table of codes (a file gets one from the code's inbox
 * folder or its QR sticker) and what each one files as. Each code is one line (its sticker,
 * code, label and what it does); clicking one opens its editor, one at a time. The table is
 * saved whole from the save bar, shown while there are unsaved edits (the old file is kept as
 * a backup). Edits survive leaving the section: they are kept until saved or discarded, and
 * closing the tab asks first. Entries of the file that could not be loaded (``problems``)
 * are not in the table, so saving drops them from the file; the bar says so. "Create inbox
 * folders" (after a preview) and the folders that belong to no code are notices above the
 * list. Print stickers opens as a sheet. */
import { ChevronRight, Plus, TriangleAlert, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  errorText,
  type FilingCode,
  type FilingCodes as FilingCodesData,
  previewCodeFolders,
  type ResolvedOp,
  type TrayDef as Tray,
  useCodeFolders,
  useCreateCodeFolders,
  useFilingCodes,
  useSaveFilingCodes,
  useTrays,
} from "../../api/client";
import { visible } from "../../text";
import { CollectionPicker } from "../CollectionPicker";
import { FolderPicker } from "../FolderPicker";
import { ConfirmPlan } from "../PlanPreview";
import { TagInput } from "../TagInput";
import { IconButton } from "../ui/IconButton";
import { Sheet } from "../ui/Sheet";
import { PrintStickers } from "./PrintStickers";
import { StickerPreview } from "./StickerPreview";

/** A row being edited; ``collectionText`` is a collection typed in its picker, not added yet. */
type Draft = {
  key: number;
  code: string;
  label: string;
  tray: string;
  folder: string;
  name: string;
  tags: string[];
  collections: string[];
  collectionText: string;
  as_suggested: boolean;
  inbox_folder: string;
};

let nextKey = 1;
const blank = (): Draft => ({
  key: nextKey++,
  code: "",
  label: "",
  tray: "",
  folder: "",
  name: "",
  tags: [],
  collections: [],
  collectionText: "",
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
  tags: [...c.tags],
  collections: [...c.collections],
  collectionText: "",
  as_suggested: c.as_suggested,
  inbox_folder: c.inbox_folder ?? "",
});
const toCode = (d: Draft): FilingCode => ({
  code: d.code.trim(),
  label: d.label.trim(),
  tray: d.tray || null,
  folder: d.folder.trim() || null,
  name: d.name.trim() || null,
  tags: d.tags,
  // a collection typed but not added yet is saved too, as Save is pressed after typing it
  collections: d.collectionText.trim() ? [...d.collections, d.collectionText.trim()] : d.collections,
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

/** What a code does, in a few words, for its line in the list. */
function summary(r: Draft, trays: Tray[]): string {
  const parts = [
    r.as_suggested ? "File as suggested, no tray" : r.tray ? `→ ${trays.find((t) => t.id === r.tray)?.name ?? r.tray}` : "No tray",
    r.folder.trim(),
    r.as_suggested ? "" : r.name.trim(),
  ];
  return parts.filter(Boolean).join(" · ");
}

/** The codes ``r`` is easy to confuse with. */
const confusedWith = (r: Draft, rows: Draft[]) =>
  rows.filter((o) => o.key !== r.key && confusable(r.code, o.code)).map((o) => o.code.trim());

/** The first problem worth flagging on a closed code's line, or null. */
function lineWarning(r: Draft, rows: Draft[]): string | null {
  if (!r.code.trim()) return "No code";
  const same = confusedWith(r, rows);
  if (same.length > 0) return `Easy to confuse with ${same.join(", ")}`;
  if (!r.as_suggested && fixedName(r.name)) return "Same name for every file";
  return null;
}

const sameTable = (a: Draft[], b: Draft[]) => JSON.stringify(a.map(toCode)) === JSON.stringify(b.map(toCode));

/** Unsaved edits kept while the section is not shown (another section or screen), so
 * leaving Settings never loses them; cleared by Save and Discard. A switch of archive
 * reloads the page, which clears it too (after the browser asks). */
let kept: { rows: Draft[]; open: number | null } | null = null;

/** Forget the kept edits (tests start from the server's table). */
export const forgetKeptEdits = () => {
  kept = null;
};

function CodeLine({ r, rows, trays, onOpen }: { r: Draft; rows: Draft[]; trays: Tray[]; onOpen: () => void }) {
  const warning = lineWarning(r, rows);
  const name = [visible(r.code.trim().toUpperCase()) || "No code", visible(r.label) || "No label"].join(" ");
  return (
    <button
      type="button"
      className="code-line"
      aria-expanded={false}
      aria-label={`${name}: ${visible(summary(r, trays))}${warning ? `. ${visible(warning)}` : ""}`}
      onClick={onOpen}
    >
      <StickerPreview code={r.code} label={r.label} small />
      <code className="code-line-code">{visible(r.code.trim().toUpperCase()) || "—"}</code>
      <span className="code-line-label">{visible(r.label) || "No label"}</span>
      <span className="code-line-summary">{visible(summary(r, trays))}</span>
      {warning ? (
        <span className="code-line-warning">
          <TriangleAlert size={13} aria-hidden="true" /> {visible(warning)}
        </span>
      ) : (
        <span />
      )}
      <ChevronRight size={14} className="code-line-chevron" aria-hidden="true" />
    </button>
  );
}

function CodeEditor({
  r,
  i,
  rows,
  trayList,
  edit,
  onRemove,
  onDone,
  printable,
  onPrint,
}: {
  r: Draft;
  i: number;
  rows: Draft[];
  trayList: Tray[];
  edit: (key: number, patch: Partial<Draft>) => void;
  onRemove: () => void;
  onDone: () => void;
  /** Whether the code is saved as shown (printing uses the saved table). */
  printable: boolean;
  onPrint: () => void;
}) {
  const same = confusedWith(r, rows);
  return (
    <>
      <div className="filing-code-row">
          <StickerPreview code={r.code} label={r.label} />
          <div className="code-col">
            <div className="code-field" data-tip="1 to 4 letters or digits, printed big on the sticker and read from its QR code">
              <label htmlFor={`code-${r.key}-code`}>Code</label>
              <input
                id={`code-${r.key}-code`}
                value={r.code}
                onChange={(e) => edit(r.key, { code: e.target.value })}
                maxLength={4}
              />
            </div>
            <div className="code-field" data-tip="A short description, on the sticker and in the Inbox (at most 24 characters)">
              <label htmlFor={`code-${r.key}-label`}>Label</label>
              <input
                id={`code-${r.key}-label`}
                value={r.label}
                onChange={(e) => edit(r.key, { label: e.target.value })}
                maxLength={24}
              />
            </div>
          </div>
          <div className="code-col">
            <div className="code-field" data-tip="The tray the file goes into when it is filed with this code">
              <label htmlFor={`code-${r.key}-tray`}>Tray</label>
              <select id={`code-${r.key}-tray`} value={r.tray} onChange={(e) => edit(r.key, { tray: e.target.value })}>
                <option value="">No tray</option>
                {trayList.map((t) => (
                  <option key={t.id} value={t.id}>
                    {visible(t.name)}
                  </option>
                ))}
                {r.tray && !trayList.some((t) => t.id === r.tray) && <option value={r.tray}>{visible(r.tray)}</option>}
              </select>
            </div>
            <div className="code-field" data-tip="A folder in the inbox: files you save there get this code">
              <label htmlFor={`code-${r.key}-inbox`}>Inbox folder</label>
              <input
                id={`code-${r.key}-inbox`}
                value={r.inbox_folder}
                onChange={(e) => edit(r.key, { inbox_folder: e.target.value })}
              />
            </div>
          </div>
          <div className="code-col">
            <div className="code-field" data-tip="Where the file is filed; {year} and {doc_date:%Y} work here too">
              <FolderPicker label="Folder" value={r.folder} onChange={(v) => edit(r.key, { folder: v })} />
            </div>
            <div className="code-field" data-tip="The collections the filed file is added to">
              <CollectionPicker
                label="Collections"
                value={r.collections}
                onChange={(names) => edit(r.key, { collections: names })}
                text={r.collectionText}
                onTextChange={(text) => edit(r.key, { collectionText: text })}
              />
            </div>
          </div>
          <div className="code-col">
            <div
              className="code-field"
              data-tip="The file's new name, made from its details; not used when its name already starts with a date"
            >
              <label htmlFor={`code-${r.key}-name`}>Name pattern</label>
              <input
                id={`code-${r.key}-name`}
                value={r.name}
                placeholder="{doc_date:%Y%m%d}_Fortum"
                onChange={(e) => edit(r.key, { name: e.target.value })}
              />
            </div>
            <div className="code-field" data-tip="The tags the filed file gets">
              <label htmlFor={`code-${r.key}-tags`}>Tags</label>
              <TagInput id={`code-${r.key}-tags`} value={r.tags} onChange={(tags) => edit(r.key, { tags })} />
            </div>
          </div>
          <div className="code-col code-col-end">
            <IconButton
              icon={<X />}
              label={`Remove code ${r.code || `row ${i + 1}`}`}
              className="tip-end"
              onClick={onRemove}
            />
            <label
              className="check code-field code-check"
              data-tip="Already handled: file it where dam suggests, in no tray; the tray and name pattern are not used"
            >
              <input
                type="checkbox"
                checked={r.as_suggested}
                onChange={(e) => edit(r.key, { as_suggested: e.target.checked })}
              />
              File as suggested
            </label>
          </div>
          {!r.as_suggested && fixedName(r.name) && (
            <p className="hint">
              Every file with this code gets the same name. Add <code>{"{doc_date:%Y%m%d}"}</code> or{" "}
              <code>{"{stem}"}</code> to tell them apart.
            </p>
          )}
          {same.length > 0 && (
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
      </div>
      <p className="hint code-editor-note">
        A name pattern makes each file's name from its details: <code>{"{doc_date:%Y%m%d}"}</code> is the document's date,{" "}
        <code>{"{year}"}</code> its year and <code>{"{stem}"}</code> the file's own name, so{" "}
        <code>{"{doc_date:%Y%m%d}_Fortum"}</code> gives <code>20261015_Fortum.pdf</code>.
      </p>
      <div className="code-editor-actions">
        <span className="button-wrap" data-tip={printable ? "Print stickers of this code" : "Save the code first: stickers print the saved table"}>
          <button type="button" disabled={!printable} onClick={onPrint}>
            Print…
          </button>
        </span>
        <button type="button" onClick={onDone}>
          Done
        </button>
      </div>
    </>
  );
}

export function FilingCodes() {
  const codes = useFilingCodes();
  const trays = useTrays();
  const folders = useCodeFolders();
  const save = useSaveFilingCodes();
  const create = useCreateCodeFolders();
  const [rows, setRows] = useState<Draft[] | null>(null);
  const [open, setOpen] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [plan, setPlan] = useState<ResolvedOp[] | null>(null);
  const [printing, setPrinting] = useState<{ code: string | null } | null>(null);
  const loaded = useRef(false);

  // The table is copied into the editor once (or the edits kept from before); later loads
  // (after a save) must not wipe edits.
  useEffect(() => {
    if (codes.data && !loaded.current) {
      loaded.current = true;
      if (kept) {
        setRows(kept.rows);
        setOpen(kept.open);
      } else setRows(codes.data.codes.map(toDraft));
    }
  }, [codes.data]);

  const saved = codes.data?.codes.map(toDraft) ?? null;
  const dirty = rows !== null && saved !== null && !sameTable(rows, saved);

  // Keep unsaved edits when the section goes away; ask before the tab closes with them.
  const latest = useRef({ rows, open, dirty });
  latest.current = { rows, open, dirty };
  useEffect(
    () => () => {
      const { rows: r, open: o, dirty: d } = latest.current;
      kept = d && r ? { rows: r, open: o } : null;
    },
    [],
  );
  useEffect(() => {
    if (!dirty) return;
    const ask = (e: BeforeUnloadEvent) => e.preventDefault();
    window.addEventListener("beforeunload", ask);
    return () => window.removeEventListener("beforeunload", ask);
  }, [dirty]);

  const header = (
    <>
      <h3>Filing codes</h3>
      <p className="hint">
        A code says where a file goes and what it gets. A file gets it from the code's QR sticker or its inbox folder.{" "}
        <Link to="/help#filing-codes">More in Help</Link>
      </p>
    </>
  );
  if (codes.isError) {
    return (
      <section className="filing-codes" aria-label="Filing codes">
        {header}
        <p className="error" role="alert">
          {visible(errorText(codes.error))}
        </p>
      </section>
    );
  }
  if (!codes.data || rows === null || saved === null) {
    return (
      <section className="filing-codes" aria-label="Filing codes">
        {header}
        <p className="hint">Loading…</p>
      </section>
    );
  }

  const problems = codes.data.problems;
  const trayList = trays.data?.trays ?? [];
  const edit = (key: number, patch: Partial<Draft>) =>
    setRows((rs) => (rs ?? []).map((r) => (r.key === key ? { ...r, ...patch } : r)));
  const isSaved = (r: Draft) => saved.some((s) => JSON.stringify(toCode(s)) === JSON.stringify(toCode(r)));

  const doSave = async () => {
    setError(null);
    try {
      const result = await save.mutateAsync(rows.map(toCode));
      kept = null;
      const next = result.codes.map(toDraft);
      const openCode = rows.find((r) => r.key === open)?.code.trim().toUpperCase();
      setRows(next);
      setOpen(next.find((r) => r.code === openCode)?.key ?? null);
    } catch (e) {
      setError(errorText(e));
    }
  };
  const discard = () => {
    kept = null;
    setError(null);
    setRows(saved);
    setOpen(null);
  };
  const addCode = () => {
    const row = blank();
    setRows((rs) => [...(rs ?? []), row]);
    setOpen(row.key);
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
      {header}
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
      {missing.length > 0 && (
        <div className="notice code-notice" role="note">
          <span>
            {missing.length === 1 ? "A code's inbox folder is missing" : `${missing.length} codes' inbox folders are missing`}:{" "}
            {missing.map((f, j) => (
              <span key={f}>
                {j > 0 && ", "}
                <code>{visible(f)}</code>
              </span>
            ))}
            .
          </span>
          <button type="button" onClick={() => void openPlan()}>
            Create inbox folders…
          </button>
        </div>
      )}
      {stray.length > 0 && (
        <div className="notice code-notice" role="note">
          <span>
            {stray.length === 1 ? "This inbox folder belongs" : "These inbox folders belong"} to no code, so the files in{" "}
            {stray.length === 1 ? "it are" : "them are"} not in the Inbox:{" "}
            {stray.map((f, j) => (
              <span key={f}>
                {j > 0 && ", "}
                <code>{visible(f)}</code>
              </span>
            ))}
            .
          </span>
        </div>
      )}
      {(trays.isError || folders.isError) && (
        <p className="error" role="alert">
          {trays.isError && `The trays could not be loaded: ${visible(errorText(trays.error))}. `}
          {folders.isError && `The inbox folders could not be checked: ${visible(errorText(folders.error))}.`}
        </p>
      )}
      <div className="filing-codes-actions">
        <button type="button" onClick={addCode}>
          <Plus size={14} aria-hidden="true" /> Add a code
        </button>
        <button type="button" onClick={() => setPrinting({ code: null })}>
          Print stickers…
        </button>
      </div>
      {rows.length === 0 ? (
        <p className="hint">No codes yet.</p>
      ) : (
        <ul className="filing-codes-list">
          {rows.map((r, i) =>
            r.key === open ? (
              <li key={r.key} className="code-open" role="group" aria-label={`Code ${r.code || `row ${i + 1}`}`}>
                <CodeEditor
                  r={r}
                  i={i}
                  rows={rows}
                  trayList={trayList}
                  edit={edit}
                  onRemove={() => {
                    setRows((rs) => (rs ?? []).filter((x) => x.key !== r.key));
                    setOpen(null);
                  }}
                  onDone={() => setOpen(null)}
                  printable={isSaved(r)}
                  onPrint={() => setPrinting({ code: r.code.trim().toUpperCase() })}
                />
              </li>
            ) : (
              <li key={r.key}>
                <CodeLine r={r} rows={rows} trays={trayList} onOpen={() => setOpen(r.key)} />
              </li>
            ),
          )}
        </ul>
      )}
      {(dirty || error) && (
        <div className="save-bar" role="region" aria-label="Unsaved changes">
          <span className="save-bar-text">
            {error ? (
              <span className="error" role="alert">
                {visible(error)}
              </span>
            ) : problems.length > 0 ? (
              "Unsaved changes. Saving removes the entries with problems from the file (a backup is kept)."
            ) : (
              "Unsaved changes to the filing codes."
            )}
          </span>
          <button type="button" disabled={save.isPending || !dirty} onClick={discard}>
            Discard
          </button>
          <button type="button" className="primary" disabled={save.isPending || !dirty} onClick={() => void doSave()}>
            Save
          </button>
        </div>
      )}
      {printing && (
        <Sheet open title="Print stickers" onClose={() => setPrinting(null)} footer={<button type="button" onClick={() => setPrinting(null)}>Close</button>}>
          <PrintStickers initialCode={printing.code} />
        </Sheet>
      )}
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
