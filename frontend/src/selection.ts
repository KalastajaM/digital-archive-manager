/** The selection shared with the viewer window (``/viewer/:driveId``) over a
 * ``BroadcastChannel``. The main window publishes the document it has selected; a
 * viewer that follows the selection shows it. Browsers without BroadcastChannel (and
 * jsdom) get no-ops: the viewer then stays on the document it was opened with. */
import { useEffect, useState } from "react";

const CHANNEL = "dam-selection";

type Message = { type: "select"; driveId: string } | { type: "hello" };

const channelClass = (): typeof BroadcastChannel | undefined =>
  typeof globalThis.BroadcastChannel === "function" ? globalThis.BroadcastChannel : undefined;

// The main window's channel, opened on the first publish and kept for the page's life,
// so it can answer a viewer that starts following ("hello") with the current selection.
let sender: BroadcastChannel | null = null;
let senderClass: typeof BroadcastChannel | undefined;
let current: string | null = null;

function senderChannel(): BroadcastChannel | null {
  const Channel = channelClass();
  if (!Channel) return null;
  if (!sender || senderClass !== Channel) {
    sender?.close();
    sender = new Channel(CHANNEL);
    senderClass = Channel;
    sender.onmessage = (e: MessageEvent<Message>) => {
      if (e.data?.type === "hello" && current !== null) {
        sender?.postMessage({ type: "select", driveId: current } satisfies Message);
      }
    };
  }
  return sender;
}

/** Tell a following viewer window that this document is now selected. */
export function publishSelection(driveId: string) {
  current = driveId;
  senderChannel()?.postMessage({ type: "select", driveId } satisfies Message);
}

/** The document the main window selected last, while ``enabled`` (null until it says).
 * Turning it on asks the main window for its current selection. */
export function useSelectionFollower(enabled: boolean): string | null {
  const [selected, setSelected] = useState<string | null>(null);
  useEffect(() => {
    const Channel = channelClass();
    if (!enabled || !Channel) return;
    const channel = new Channel(CHANNEL);
    channel.onmessage = (e: MessageEvent<Message>) => {
      if (e.data?.type === "select" && typeof e.data.driveId === "string") setSelected(e.data.driveId);
    };
    channel.postMessage({ type: "hello" } satisfies Message);
    return () => channel.close();
  }, [enabled]);
  return enabled ? selected : null;
}

/** Forget the main window's channel and its current selection (tests: each starts as a
 * fresh page, so no earlier selection reaches a viewer that says hello). */
export function resetSelectionChannel() {
  sender?.close();
  sender = null;
  senderClass = undefined;
  current = null;
}

/** Open (or reuse) the one viewer window on this document. */
export function openViewer(driveId: string) {
  publishSelection(driveId);
  window.open(`/viewer/${encodeURIComponent(driveId)}`, "dam-viewer", "width=900,height=1000");
}
