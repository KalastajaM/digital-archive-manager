/** Settings → Print stickers: pick filing codes and how many of each, a sheet layout (the
 * built-ins, or a custom one in mm) and the options, then open the printable sheet in a
 * new tab and print it with the browser's dialog. Test print draws only the label
 * outlines, to print on plain paper and hold against a label sheet. Nothing here changes
 * the archive. */
import { useRef, useState } from "react";
import {
  errorText,
  type SheetLayout,
  type SheetLayoutIn,
  checkStickerSheet,
  type StickerSheet,
  stickerSheetUrl,
  useFilingCodes,
  useSaveCustomSheet,
  useSheetLayouts,
} from "../../api/client";
import { plural } from "../../format";
import { visible } from "../../text";

const CUSTOM = "custom";

/** The custom layout's number fields, in the order they are shown. */
const MM_FIELDS = [
  ["columns", "Columns", 1],
  ["rows", "Rows", 1],
  ["label_w_mm", "Label width (mm)", 0.1],
  ["label_h_mm", "Label height (mm)", 0.1],
  ["top_mm", "Top margin (mm)", 0.1],
  ["left_mm", "Left margin (mm)", 0.1],
  ["gap_x_mm", "Gap across (mm)", 0.1],
  ["gap_y_mm", "Gap down (mm)", 0.1],
] as const;
type MmField = (typeof MM_FIELDS)[number][0];

/** The custom layout being edited: numbers as typed. */
type Draft = { name: string; cut_lines: boolean } & Record<MmField, string>;

const toDraft = (l: SheetLayout, name = l.name): Draft => ({
  name,
  cut_lines: l.cut_lines,
  ...(Object.fromEntries(MM_FIELDS.map(([k]) => [k, String(l[k])])) as Record<MmField, string>),
});

/** The draft as the API takes it, or null when a number field is not a number. */
function toLayout(d: Draft): SheetLayoutIn | null {
  const numbers = MM_FIELDS.map(([k]) => [k, d[k].trim() === "" ? NaN : Number(d[k])] as const);
  if (numbers.some(([, n]) => !Number.isFinite(n))) return null;
  return { name: d.name.trim(), cut_lines: d.cut_lines, ...(Object.fromEntries(numbers) as Record<MmField, number>) };
}

const sameLayout = (a: SheetLayoutIn | null, b: SheetLayout | null) =>
  a !== null && b !== null && a.name === b.name && a.cut_lines === b.cut_lines && MM_FIELDS.every(([k]) => a[k] === b[k]);

export function PrintStickers() {
  const codes = useFilingCodes();
  const layouts = useSheetLayouts();
  const saveCustom = useSaveCustomSheet();
  const [chosen, setChosen] = useState<Record<string, string>>({}); // code -> count as typed
  const [layoutId, setLayoutId] = useState<string | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  // the custom layout this page saved (the list catches up on its next load)
  const [savedNow, setSavedNow] = useState<SheetLayout | null>(null);
  const [startAt, setStartAt] = useState("1");
  const [boxes, setBoxes] = useState(true);
  const [blank, setBlank] = useState(false);
  const [busy, setBusy] = useState(false);
  const inFlight = useRef(false); // one sheet at a time, however fast the clicks
  const [error, setError] = useState<string | null>(null);

  const header = (
    <>
      <h3>Print stickers</h3>
      <p className="hint">
        Pick the codes and how many of each. The sheet opens in a new tab: print it from there at 100 %, without fit to
        page. Test print draws only the label outlines: print it on plain paper and hold it against a label sheet to
        check the fit.
      </p>
    </>
  );
  if (codes.isError || layouts.isError) {
    return (
      <section className="print-stickers" aria-label="Print stickers">
        {header}
        <p className="error" role="alert">
          {visible(errorText(codes.error ?? layouts.error))}
        </p>
      </section>
    );
  }
  if (!codes.data || !layouts.data) {
    return (
      <section className="print-stickers" aria-label="Print stickers">
        {header}
        <p className="hint">Loading…</p>
      </section>
    );
  }

  const list = layouts.data.filter((l) => l.id !== CUSTOM);
  const savedCustom = savedNow ?? layouts.data.find((l) => l.id === CUSTOM) ?? null;
  const current = layoutId ?? list[0]?.id ?? CUSTOM;
  const isCustom = current === CUSTOM;
  const edited = isCustom && draft ? toLayout(draft) : null;
  const customReady = !isCustom || (savedCustom !== null && (draft === null || sameLayout(edited, savedCustom)));
  const perPage = isCustom
    ? edited
      ? edited.columns * edited.rows
      : null
    : ((l) => (l ? l.columns * l.rows : null))(list.find((l) => l.id === current));

  const counts: Record<string, number> = {};
  for (const [code, text] of Object.entries(chosen)) {
    const n = Math.max(0, Math.floor(Number(text) || 0));
    if (n > 0) counts[code] = n;
  }
  const total = Object.values(counts).reduce((a, b) => a + b, 0);

  const pickLayout = (id: string) => {
    setLayoutId(id);
    if (id === CUSTOM && draft === null) {
      const base = savedCustom ?? list[0];
      setDraft(base ? toDraft(base, savedCustom ? base.name : "Custom") : null);
    }
  };
  const editDraft = (patch: Partial<Draft>) => setDraft((d) => (d ? { ...d, ...patch } : d));
  const doSaveCustom = async () => {
    setError(null);
    const layout = draft ? toLayout(draft) : null;
    if (!layout) {
      setError("Fill in every number of the custom sheet.");
      return;
    }
    try {
      setSavedNow(await saveCustom.mutateAsync(layout));
    } catch (e) {
      setError(errorText(e));
    }
  };

  const print = async (outlinesOnly: boolean) => {
    setError(null);
    const body: StickerSheet = {
      codes: outlinesOnly ? {} : counts,
      layout: current,
      start_at: outlinesOnly ? 1 : Math.floor(Number(startAt)) || 1,
      boxes,
      blank_labels: blank,
      outlines_only: outlinesOnly,
    };
    if (inFlight.current) return;
    inFlight.current = true;
    setBusy(true);
    const url = stickerSheetUrl(body);
    try {
      await checkStickerSheet(url); // a refusal is said here, not in an empty tab
      window.open(url, "_blank", "noopener");
    } catch (e) {
      setError(errorText(e));
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  };

  return (
    <section className="print-stickers" aria-label="Print stickers">
      {header}
      {codes.data.codes.length === 0 ? (
        <p className="hint">Add filing codes above first.</p>
      ) : (
        <ul className="print-stickers-codes" aria-label="Codes to print">
          {codes.data.codes.map((c) => {
            const on = c.code in chosen;
            return (
              <li key={c.code}>
                <label className="check">
                  <input
                    type="checkbox"
                    aria-label={`Print ${c.code}`}
                    checked={on}
                    onChange={(e) =>
                      setChosen((old) => {
                        const next = { ...old };
                        if (e.target.checked) next[c.code] = "1";
                        else delete next[c.code];
                        return next;
                      })
                    }
                  />
                  <code>{visible(c.code)}</code> {visible(c.label)}
                </label>
                <input
                  type="number"
                  min={0}
                  max={2000}
                  aria-label={`How many ${c.code}`}
                  disabled={!on}
                  value={chosen[c.code] ?? ""}
                  onChange={(e) => setChosen((old) => ({ ...old, [c.code]: e.target.value }))}
                />
              </li>
            );
          })}
        </ul>
      )}
      <div className="print-stickers-options">
        <label>
          Sheet
          <select value={current} onChange={(e) => pickLayout(e.target.value)}>
            {list.map((l) => (
              <option key={l.id} value={l.id}>
                {visible(l.name)}
              </option>
            ))}
            <option value={CUSTOM}>{savedCustom ? `Custom: ${visible(savedCustom.name)}` : "Custom"}</option>
          </select>
        </label>
        <label>
          Start at label
          <input
            type="number"
            min={1}
            max={perPage ?? undefined}
            value={startAt}
            onChange={(e) => setStartAt(e.target.value)}
          />
        </label>
        <label className="check">
          <input type="checkbox" checked={boxes} onChange={(e) => setBoxes(e.target.checked)} />
          With tick boxes (star, important)
        </label>
        <label className="check">
          <input type="checkbox" checked={blank} onChange={(e) => setBlank(e.target.checked)} />
          Blank labels (write the label by hand)
        </label>
      </div>
      {isCustom && draft && (
        <div className="print-stickers-custom" role="group" aria-label="Custom sheet">
          <label>
            Name
            <input value={draft.name} onChange={(e) => editDraft({ name: e.target.value })} />
          </label>
          {MM_FIELDS.map(([key, label, step]) => (
            <label key={key}>
              {label}
              <input
                type="number"
                min={0}
                step={step}
                value={draft[key]}
                onChange={(e) => editDraft({ [key]: e.target.value } as Partial<Draft>)}
              />
            </label>
          ))}
          <label className="check">
            <input type="checkbox" checked={draft.cut_lines} onChange={(e) => editDraft({ cut_lines: e.target.checked })} />
            Cut lines
          </label>
          <button type="button" disabled={saveCustom.isPending} onClick={() => void doSaveCustom()}>
            Save custom sheet
          </button>
        </div>
      )}
      {!customReady && <p className="hint">Save the custom sheet before printing on it.</p>}
      {error && (
        <p className="error" role="alert">
          {visible(error)}
        </p>
      )}
      <div className="filing-codes-actions">
        <span className="hint">{plural(total, "sticker")}</span>
        <button type="button" disabled={busy || !customReady} onClick={() => void print(true)}>
          Test print
        </button>
        <button
          type="button"
          className="primary"
          disabled={busy || !customReady || total === 0}
          onClick={() => void print(false)}
        >
          Open sheet
        </button>
      </div>
    </section>
  );
}
