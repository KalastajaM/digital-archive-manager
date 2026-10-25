/** "Ask AI to suggest a name, folder and tags" for a file, as a hook a screen can own: the
 * header's Ask AI button starts it and the file's details show the answer as chips.
 * Nothing is sent without the "What will be sent" sheet (``useAISend``): render ``sheet``. */
import { useRef, useState } from "react";
import type { FilingSuggestion } from "../../api/client";
import { useAISend } from "./useAI";

export function useFilingAI() {
  const [held, setHeld] = useState<{ driveId: string; answer: FilingSuggestion } | null>(null);
  // the file the open sheet was prepared for (the answer belongs to it, whatever is shown later)
  const target = useRef<string | null>(null);
  const send = useAISend<FilingSuggestion>("suggest-filing", (answer) => {
    if (target.current) setHeld({ driveId: target.current, answer });
  });
  return {
    ask: (driveId: string) => {
      target.current = driveId;
      send.ask({ drive_id: driveId });
    },
    busy: send.busy,
    /** The answer received for this file, if any. */
    answerFor: (driveId: string): FilingSuggestion | null => (held?.driveId === driveId ? held.answer : null),
    sheet: send.sheet,
  };
}

export type FilingAI = ReturnType<typeof useFilingAI>;
