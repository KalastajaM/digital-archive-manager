/** Pay mode: the bill's bank barcode full size with its payee, amount, reference, IBAN and
 * due date in large type to check against the paper. It steps through every open bill
 * (all bill trays, earliest due date first) with Previous bill and Next bill (also ← and
 * →) without closing; the barcode, values, title and Mark paid follow the shown bill.
 * After Mark paid it moves on to the next bill (the previous one after the last; it
 * closes when that was the only one).
 *
 * One sheet for the whole app (``PayModeProvider``, in the shell), opened from the bill's
 * panel and from Today's bill table, so it survives the screen under it changing: a bill
 * marked paid leaves the screen it was opened from. */
import { ChevronLeft, ChevronRight } from "lucide-react";
import { type KeyboardEvent, type ReactNode, useState } from "react";
import { errorText, useItemBarcode } from "../api/client";
import { useStyle } from "../appearance";
import { formatMoney } from "../format";
import { isTyping } from "../keyboard";
import { visible } from "../text";
import { BarcodeSvg, FULL_BAR_HEIGHT, FULL_MODULE_PX, quietZone } from "./Barcode";
import { CopyButton } from "./CopyButton";
import { DoneForm } from "./DoneForm";
import { PayModeContext } from "./payModeContext";
import { payFacts } from "./payFacts";
import { useLocalClock } from "./RelativeDate";
import { Sheet } from "./ui/Sheet";
import { markLabel, useMarkDone } from "./useMarkDone";
import { sumOfBills, useOpenBills } from "./usePayBills";

export function PayModeProvider({ children }: { children: ReactNode }) {
  const [billId, setBillId] = useState<number | null>(null);
  return (
    <PayModeContext.Provider value={{ open: setBillId }}>
      {children}
      {billId !== null && <PayMode startId={billId} onClose={() => setBillId(null)} />}
    </PayModeContext.Provider>
  );
}

function PayMode({ startId, onClose }: { startId: number; onClose: () => void }) {
  const [look] = useStyle();
  const isNew = look === "new";
  const { today } = useLocalClock();
  const { bills } = useOpenBills();
  const [currentId, setCurrentId] = useState(startId);
  const [form, setForm] = useState(false);
  const index = bills.findIndex((b) => b.item.id === currentId);
  const bill = index >= 0 ? bills[index] : undefined;
  const query = useItemBarcode(currentId);
  const done = useMarkDone({ id: currentId, title: bill?.item.title ?? "" }, bill?.tray, today);

  const step = (by: -1 | 1) => {
    setForm(false);
    // from the bill shown now, so two quick presses move two bills
    setCurrentId((id) => bills[bills.findIndex((b) => b.item.id === id) + by]?.item.id ?? id);
  };
  // after Mark paid: the next bill, else the previous one, else the end
  const afterPaid = () => {
    const target = bills[index + 1] ?? bills[index - 1];
    setForm(false);
    if (target) setCurrentId(target.item.id);
    else onClose();
  };
  const markPaid = async () => {
    if (!bill || done.pending) return;
    if (done.needsForm) {
      setForm(true);
      return;
    }
    if (await done.run()) afterPaid();
  };
  const onKeyDown = (e: KeyboardEvent<HTMLDialogElement>) => {
    if ((e.key !== "ArrowLeft" && e.key !== "ArrowRight") || e.metaKey || e.ctrlKey || e.altKey || e.shiftKey) return;
    if (isTyping(e.target)) return;
    e.preventDefault();
    step(e.key === "ArrowLeft" ? -1 : 1);
  };

  const barcode = query.data;
  const code = barcode?.code && barcode.modules ? { code: barcode.code, modules: barcode.modules } : null;
  const updating = query.isFetching && code !== null;
  const pay = bill ? payFacts(bill.item, bill.tray) : [];
  const amount = pay.find((f) => f.copy?.type === "money");
  const doneText = markLabel(bill?.tray.done?.label ?? "Done");

  return (
    <Sheet
      open
      title="Bank barcode"
      className="barcode-sheet"
      onClose={onClose}
      onKeyDown={onKeyDown}
      footer={
        <>
          {code && <CopyButton value={code.code} label="barcode number" />}
          {bill ? (
            <>
              <button type="button" onClick={onClose}>
                Close
              </button>
              <button type="button" className="primary" disabled={done.pending} onClick={() => void markPaid()}>
                {visible(doneText)}
              </button>
            </>
          ) : (
            <button type="button" className="primary" onClick={onClose}>
              Done
            </button>
          )}
        </>
      }
    >
      {bill && (
        <div className="pay-nav">
          <span className="pay-position">
            Bill {index + 1} of {bills.length}
            <span className="pay-open-total"> · {formatMoney(sumOfBills(bills))} open in total</span>
          </span>
          <button type="button" className="pay-step" disabled={index <= 0} title="Previous bill (←)" onClick={() => step(-1)}>
            <ChevronLeft size={14} strokeWidth={1.75} aria-hidden="true" /> Previous bill
          </button>
          <button
            type="button"
            className="pay-step"
            disabled={index >= bills.length - 1}
            title="Next bill (→)"
            onClick={() => step(1)}
          >
            Next bill <ChevronRight size={14} strokeWidth={1.75} aria-hidden="true" />
          </button>
        </div>
      )}
      {isNew && bill && (
        <div className="pay-head">
          <h3 className="pay-title">{visible(bill.item.title)}</h3>
          {amount && <span className="pay-total">{visible(amount.value)}</span>}
        </div>
      )}
      {pay.length > 0 && (
        <dl className="pay-facts" aria-label="Payment details">
          {pay.map((f) => (
            <div key={f.label} className="pay-fact" data-kind={f.copy?.type}>
              <dt>{visible(f.label)}</dt>
              <dd>{visible(f.value)}</dd>
              {isNew && f.copy && <CopyButton value={f.copy.raw} type={f.copy.type} label={f.copy.label} compact />}
            </div>
          ))}
        </dl>
      )}
      {form && bill && (
        <DoneForm
          item={bill.item}
          label={doneText}
          fields={done.fields}
          today={today}
          onClose={() => setForm(false)}
          onDone={afterPaid}
        />
      )}
      {query.isPending ? (
        <p className="hint" role="status">
          Loading…
        </p>
      ) : query.isError ? (
        <p className="hint barcode-reason">Could not load the barcode. {visible(errorText(query.error))}</p>
      ) : code ? (
        <div className="barcode-full">
          <div className="barcode-full-paper" style={quietZone(FULL_MODULE_PX)}>
            <BarcodeSvg code={code.code} modules={code.modules} px={FULL_MODULE_PX} height={FULL_BAR_HEIGHT} />
            <code className="barcode-code">{visible(code.code)}</code>
          </div>
        </div>
      ) : (
        <p className="hint barcode-reason">No barcode: {visible(barcode?.reason ?? "it cannot be built")}</p>
      )}
      {isNew && (
        <ol className="pay-steps" aria-label="How to pay with the barcode">
          <li>In your banking app choose to pay with a barcode (in most Finnish banks: Pay, then Scan barcode).</li>
          <li>Hold the phone about 15 to 25 cm from the screen.</li>
          <li>Check the payee, amount and reference before you confirm.</li>
        </ol>
      )}
      <p className="hint">Scan it from the screen with your banking app.</p>
      <p className="hint barcode-full-status" role="status">
        {updating ? "Updating…" : ""}
      </p>
    </Sheet>
  );
}
