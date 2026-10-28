/** "Find more with AI…" for Relatives (block and dialog). The button opens the usual
 * "What will be sent" sheet (``useAISend``): nothing is sent before its Send. The picks
 * that come back are not stored as relatives. They show as extra rows marked AI with the
 * one-line reason, work with the same selection actions, Quick Look compare and Not
 * related, and go away with Hide. Asking again for the same files is answered from the
 * AI cache ("from earlier", free). */
import { Sparkles } from "lucide-react";
import { type ReactNode, useMemo, useState } from "react";
import type { Relative } from "../api/client";
import { euro, plural } from "../format";
import { visible } from "../text";
import { type AIResultInfo, useAISend, useAIState } from "./ai/useAI";
import type { BlockFile } from "./relativesShared";

/** A file the AI picked: shaped as a relative with no links, so every action that works
 * on relatives works on it. */
export type AIPick = Relative & { ai: true; reason: string; confidence: number };

export const isAIPick = (r: Relative): r is AIPick => "ai" in r && (r as AIPick).ai === true;

type Match = {
  drive_id: string;
  reason: string;
  confidence: number;
  name: string;
  path: string;
  folder: string;
  ext: string | null;
  in_inbox: boolean;
};
type Found = { matches: Match[]; candidates: number; hidden?: number };

const toPick = (m: Match): AIPick => ({
  drive_id: m.drive_id,
  name: m.name,
  path: m.path,
  folder: m.folder,
  ext: m.ext,
  in_inbox: m.in_inbox,
  score: 0,
  links: [],
  same_month: false,
  ai: true,
  reason: m.reason,
  confidence: m.confidence,
});

export type Finder = ReturnType<typeof useFindRelatives>;

/** The AI search for one file's relatives. ``relatives`` are the regular ones (a pick that
 * has become one is not listed twice). Render ``sheet`` once. */
export function useFindRelatives(file: BlockFile, relatives: Relative[]) {
  const ai = useAIState();
  const [found, setFound] = useState<{ data: Found; info: AIResultInfo } | null>(null);
  const [gone, setGone] = useState<ReadonlySet<string>>(new Set());
  const send = useAISend<Found>("find-relatives", (data, info) => {
    setGone(new Set());
    setFound({ data, info });
  });

  const picks = useMemo(() => {
    if (!found) return [];
    const regular = new Set(relatives.map((r) => r.drive_id));
    return found.data.matches
      .filter((m) => !gone.has(m.drive_id) && !regular.has(m.drive_id) && m.drive_id !== file.drive_id)
      .map(toPick);
  }, [found, gone, relatives, file.drive_id]);

  return {
    /** AI is on and has a key: the button is shown. */
    available: ai.on,
    busy: send.busy,
    ask: () => send.ask({ drive_id: file.drive_id }),
    sheet: send.sheet,
    picks,
    /** There is an answer on show (the line with Hide). */
    answered: found !== null,
    found: found && { candidates: found.data.candidates, shown: picks.length, info: found.info },
    hide: () => {
      setFound(null);
      setGone(new Set());
    },
    /** A pick marked Not related is gone from the picks too. */
    drop: (id: string) => setGone((prev) => new Set(prev).add(id)),
  };
}

/** The button, or nothing while AI is off or an answer is on show. */
export function FindMoreButton({ finder, className = "" }: { finder: Finder; className?: string }) {
  if (!finder.available || finder.answered) return null;
  return (
    <button
      type="button"
      className={`ai-action link-button relatives-ai-ask ${className}`.trim()}
      disabled={finder.busy}
      onClick={finder.ask}
    >
      <Sparkles size={14} aria-hidden="true" />
      Find more with AI…
    </button>
  );
}

/** "AI found N more out of M candidates · cost · Hide". */
export function FoundLine({ finder }: { finder: Finder }): ReactNode {
  const f = finder.found;
  if (!f) return null;
  const cost = f.info.cached ? "from earlier" : euro(f.info.costEur);
  return (
    <p className="relatives-ai-found" role="status" aria-label="AI result">
      <Sparkles size={14} aria-hidden="true" />
      <span>
        {f.shown === 0 ? "AI found nothing more" : `AI found ${f.shown} more`} out of {plural(f.candidates, "candidate")}
        {" · "}
        {cost}
      </span>
      <button type="button" className="link-button" onClick={finder.hide}>
        Hide
      </button>
    </p>
  );
}

/** The dashed "AI" marker; hover or focus shows how sure the AI was. */
export function AIMark({ pick }: { pick: AIPick }) {
  const sure = `${Math.round(Math.min(1, Math.max(0, pick.confidence)) * 100)}% sure`;
  return (
    <span className="rel-ai-badge" tabIndex={0} aria-label={`Found by AI, ${sure}`} data-tip={`AI · ${sure}`}>
      AI
    </span>
  );
}

export const reasonOf = (pick: AIPick) => visible(pick.reason);
