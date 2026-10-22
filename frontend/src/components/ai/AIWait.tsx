/** The live status while an AI call is out: a spinner, who is answering, the seconds
 * waited (ticking each second) and the limit the app gives up at. After
 * ``CALM_AFTER_S`` a calm line says the app is not stuck. Shared by every AI entry point
 * (they all send through ``SendSheet``). */
import { useEffect, useState } from "react";
import { visible } from "../../text";

export const CALM_AFTER_S = 10;

/** Seconds as "45 s", "2 min" or "2 min 20 s". */
export function secondsText(s: number): string {
  const minutes = Math.floor(s / 60);
  const rest = s % 60;
  if (minutes === 0) return `${rest} s`;
  return rest === 0 ? `${minutes} min` : `${minutes} min ${rest} s`;
}

/** Whole seconds since mount, updated every second. */
function useElapsed(): number {
  const [start] = useState(() => Date.now());
  const [now, setNow] = useState(start);
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);
  return Math.max(0, Math.floor((now - start) / 1000));
}

export function AIWait({ model, limitS }: { model: string; limitS: number }) {
  const elapsed = useElapsed();
  return (
    <div className="ai-wait" role="status">
      <p className="busy">
        Waiting for Claude ({visible(model)})… {secondsText(elapsed)}
        <span className="hint"> · gives up after {secondsText(limitS)}</span>
      </p>
      {elapsed >= CALM_AFTER_S && <p className="hint">Larger requests can take a minute; the app is not stuck.</p>}
    </div>
  );
}
