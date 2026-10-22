/** The item's Finnish bank barcode (Code 128 set C), drawn as an SVG a banking app can
 * scan off the monitor, with its 54 digits and Copy. The code always comes from the
 * item's current fields (``GET /api/items/{id}/barcode``); when a barcode printed on the
 * scan disagrees, a warning names the fields and offers its values. It is drawn as large as
 * the pane allows (down to a size a phone still reads); "Show large barcode" (or ``b``, or
 * a double click) opens Pay mode: the barcode full size with the payee, amount, reference,
 * IBAN and due date in large type to check against the bill, and Copy barcode number. */
import { Maximize2 } from "lucide-react";
import { type CSSProperties, type RefObject, useEffect, useId, useRef, useState } from "react";
import { isShortcut, useKeydown } from "../keyboard";
import { errorText, type ItemBarcode, useItemBarcode, useItemUpdate } from "../api/client";
import { fieldWord, formatDate, formatMoney } from "../format";
import { visible } from "../text";
import { CopyButton } from "./CopyButton";
import { Sheet } from "./ui/Sheet";

/** One module (the narrowest bar) in CSS pixels: at least 2 so a phone camera resolves it. */
export const MODULE_PX = 2;
/** The smallest module the inline barcode is scaled down to to fit the pane; below that
 * it scrolls and points to the large view (a phone camera needs about this much). */
export const MIN_MODULE_PX = 1.25;
export const BAR_HEIGHT = 60;
/** The light margin each side that scanners need (Code 128 asks for 10 modules). */
export const QUIET_MODULES = 10;
/** The full-size popup: 3 px a module, never scaled (scaling would break the module
 * widths); a window narrower than the symbol scrolls sideways instead. */
export const FULL_MODULE_PX = 3;
export const FULL_BAR_HEIGHT = 120;

/** ``--quiet-zone`` for the paper around a symbol drawn at ``px`` a module: its digits
 * are inset by it, so they start under the first bar (the CSS never repeats the sum). */
const quietZone = (px: number) => ({ "--quiet-zone": `${QUIET_MODULES * px}px` }) as CSSProperties;

/** The bars' x and width in modules: ``modules`` alternates bar, space, bar, … */
export function bars(modules: number[]): { x: number; w: number }[] {
  const out: { x: number; w: number }[] = [];
  let x = 0;
  modules.forEach((w, i) => {
    if (i % 2 === 0) out.push({ x, w });
    x += w;
  });
  return out;
}

/** Whether the element's content is wider than its box (rechecked as it resizes). */
function useOverflows(ref: RefObject<HTMLElement | null>): boolean {
  const [overflows, setOverflows] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const check = () => setOverflows(el.scrollWidth > el.clientWidth + 1);
    check();
    if (typeof ResizeObserver === "function") {
      const observer = new ResizeObserver(check);
      observer.observe(el);
      return () => observer.disconnect();
    }
    window.addEventListener("resize", check);
    return () => window.removeEventListener("resize", check);
  }, [ref]);
  return overflows;
}

/** The width of the element's box (0 until known: jsdom and the first render). */
function useWidth(ref: RefObject<HTMLElement | null>): number {
  const [width, setWidth] = useState(0);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const measure = () => setWidth(el.clientWidth);
    measure();
    if (typeof ResizeObserver === "function") {
      const observer = new ResizeObserver(measure);
      observer.observe(el);
      return () => observer.disconnect();
    }
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, [ref]);
  return width;
}

/** The bars and digits on white paper, scaled down to the pane while a phone can still
 * read them; narrower than that, a hint to use the large view (a cut-off barcode does
 * not scan). */
function Drawn({ code, modules, onFullSize }: { code: string; modules: number[]; onFullSize: () => void }) {
  const wrap = useRef<HTMLDivElement>(null);
  const paper = useRef<HTMLDivElement>(null);
  const available = useWidth(wrap);
  const overflows = useOverflows(paper);
  const total = modules.reduce((a, b) => a + b, 0) + 2 * QUIET_MODULES;
  // as large as MODULE_PX, smaller when the pane is narrower, never below MIN_MODULE_PX
  const px = available > 0 ? Math.max(MIN_MODULE_PX, Math.min(MODULE_PX, available / total)) : MODULE_PX;
  return (
    <div ref={wrap} className="barcode-drawn">
      <div
        ref={paper}
        className="barcode-paper"
        style={quietZone(px)}
        title="Double-click to show it large"
        onDoubleClick={onFullSize}
      >
        <BarcodeSvg code={code} modules={modules} px={px} />
        <code className="barcode-code">{visible(code)}</code>
      </div>
      {overflows && <p className="barcode-overflow">Too narrow to scan: widen the window or show the large barcode</p>}
    </div>
  );
}

/** The symbol at ``px`` CSS pixels a module, with its quiet zones. */
function BarcodeSvg({
  code,
  modules,
  px = MODULE_PX,
  height = BAR_HEIGHT,
}: {
  code: string;
  modules: number[];
  px?: number;
  height?: number;
}) {
  const width = (modules.reduce((a, b) => a + b, 0) + 2 * QUIET_MODULES) * px;
  return (
    <svg
      className="barcode-svg"
      role="img"
      aria-label={`Bank barcode ${code}`}
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      shapeRendering="crispEdges"
    >
      {bars(modules).map((b) => (
        <rect key={b.x} x={(QUIET_MODULES + b.x) * px} y={0} width={b.w * px} height={height} />
      ))}
    </svg>
  );
}

/** One value of the bill, shown large in Pay mode (``copy``: what its Copy button puts
 * on the clipboard, as in the copy rows). */
export type PayFact = { label: string; value: string; copy?: { raw: string; type: string; label: string } };

/** The barcode full size on white paper, with its digits; Esc or Close returns. While
 * the code is fetched again it stays open with the last code and says "Updating…". */
function FullSize({
  code,
  modules,
  updating,
  pay,
  onClose,
}: {
  code: string;
  modules: number[];
  updating: boolean;
  pay?: PayFact[];
  onClose: () => void;
}) {
  return (
    <Sheet
      open
      title="Bank barcode"
      className="barcode-sheet"
      onClose={onClose}
      footer={
        <>
          <CopyButton value={code} label="barcode number" />
          <button type="button" onClick={onClose}>
            Close
          </button>
        </>
      }
    >
      {pay && pay.length > 0 && (
        <dl className="pay-facts" aria-label="Payment details">
          {pay.map((f) => (
            <div key={f.label} className="pay-fact">
              <dt>{visible(f.label)}</dt>
              <dd>{visible(f.value)}</dd>
            </div>
          ))}
        </dl>
      )}
      <div className="barcode-full">
        <div className="barcode-full-paper" style={quietZone(FULL_MODULE_PX)}>
          <BarcodeSvg code={code} modules={modules} px={FULL_MODULE_PX} height={FULL_BAR_HEIGHT} />
          <code className="barcode-code">{visible(code)}</code>
        </div>
      </div>
      <p className="hint">Scan it from the screen with your banking app.</p>
      <p className="hint barcode-full-status" role="status">
        {updating ? "Updating…" : ""}
      </p>
    </Sheet>
  );
}

/** "amount (printed 4 883,15 €)": a differing field and the printed barcode's value. */
function differs(name: string, printed: ItemBarcode["printed_fields"]): string {
  const value = printed?.[name as keyof NonNullable<ItemBarcode["printed_fields"]>] ?? null;
  if (value === null) return fieldWord(name);
  const shown = name === "amount" ? formatMoney(value) : name === "due_date" ? formatDate(value) : value;
  return `${fieldWord(name)} (printed ${shown})`;
}

function Mismatch({ itemId, barcode }: { itemId: number; barcode: ItemBarcode }) {
  const headingId = useId();
  const update = useItemUpdate();
  const inFlight = useRef(false); // synchronous: a double click patches once
  const [error, setError] = useState<string | null>(null);
  const printed = barcode.printed_fields;
  const fields = Object.fromEntries(
    barcode.mismatch
      .map((name) => [name, printed?.[name as keyof typeof printed] ?? null] as const)
      .filter(([, value]) => value !== null),
  );
  const use = async () => {
    if (inFlight.current) return;
    inFlight.current = true;
    setError(null);
    try {
      await update.mutateAsync({ id: itemId, fields });
    } catch (e) {
      setError(errorText(e));
    } finally {
      inFlight.current = false;
    }
  };
  return (
    <section className="barcode-mismatch notice" aria-labelledby={headingId}>
      <p id={headingId} className="barcode-mismatch-title">
        The printed barcode differs
      </p>
      <p>
        The barcode on the bill says other values for:{" "}
        {barcode.mismatch.map((n) => visible(differs(n, printed))).join(", ")}. The barcode above uses the item's
        fields.
      </p>
      <button type="button" disabled={Object.keys(fields).length === 0} onClick={() => void use()}>
        Use the printed barcode's values
      </button>
      {error && (
        <p className="error" role="alert">
          {visible(error)}
        </p>
      )}
    </section>
  );
}

export function Barcode({ itemId, pay }: { itemId: number; pay?: PayFact[] }) {
  const query = useItemBarcode(itemId);
  const [fullSize, setFullSize] = useState(false);
  const canShow = !!query.data?.code && !!query.data?.modules;
  // ``b``: Pay mode, from the bill (not while typing or behind a dialog)
  useKeydown((e) => {
    if (e.key !== "b" || !isShortcut(e) || !canShow) return;
    e.preventDefault();
    setFullSize(true);
  });
  if (query.isPending) return null;
  if (query.isError) {
    return <p className="hint barcode-reason">Could not load the barcode. {visible(errorText(query.error))}</p>;
  }
  const barcode = query.data;
  // After a field change the code is being rebuilt: never show the old one beside the
  // new values. The full-size sheet stays (the same element: a scan in progress is not
  // interrupted) with the last code and "Updating…".
  const updating = query.isFetching;
  const drawn = barcode.code && barcode.modules ? { code: barcode.code, modules: barcode.modules } : null;
  return (
    <div className="barcode">
      {updating ? (
        <p className="barcode-box barcode-updating" role="status">
          Updating…
        </p>
      ) : drawn ? (
        <div className="barcode-box">
          <Drawn code={drawn.code} modules={drawn.modules} onFullSize={() => setFullSize(true)} />
          <div className="barcode-help">
            <p>Scan it with your banking app, or copy the barcode number into the web bank.</p>
            <div className="barcode-buttons">
              <CopyButton value={drawn.code} label="barcode number" />
              <button type="button" className="barcode-large" onClick={() => setFullSize(true)}>
                <Maximize2 size={14} strokeWidth={1.75} aria-hidden="true" /> Show large barcode <kbd>B</kbd>
              </button>
            </div>
          </div>
        </div>
      ) : (
        <p className="hint barcode-reason">No barcode: {visible(barcode.reason ?? "it cannot be built")}</p>
      )}
      {!updating && barcode.mismatch.length > 0 && <Mismatch itemId={itemId} barcode={barcode} />}
      {fullSize && drawn && (
        <FullSize
          code={drawn.code}
          modules={drawn.modules}
          updating={updating}
          pay={pay}
          onClose={() => setFullSize(false)}
        />
      )}
    </div>
  );
}
