/** Open a file in its default app, or show it in Finder (macOS ``open`` on the server,
 * by drive id: the path never comes from here). A refusal (apps and scripts, a file
 * that is gone, not macOS) is a toast with the server's reason, except inside a modal
 * dialog (a toast would sit under it): there the dialog provides ``InlineResults`` and
 * shows every outcome on its own ``DialogStatus`` line. */
import { ExternalLink, FolderSearch } from "lucide-react";
import { createContext, useCallback, useContext, useRef, useState } from "react";
import { ApiError, errorText, launchFile } from "../api/client";
import { inFileManager, showInLabel } from "../fileManager";
import { visible } from "../text";
import { useToast } from "./Toasts";
import { IconButton } from "./ui/IconButton";

const ICON = { size: 16, strokeWidth: 1.75 } as const;

export const LAUNCH_BUSY = "Still opening the last request";

/** Said where an archive folder's disk or cloud drive is away. */
export const notConnected = (label: string) =>
  `'${label}' is not connected. Connect the disk or sign in to the cloud drive, and it comes back by itself.`;

type How = "open" | "reveal";
const FAILED: Record<How, () => string> = { open: () => "Could not open it", reveal: () => `Could not show it ${inFileManager()}` };

const DONE: Record<How, () => string> = { open: () => "Opened", reveal: () => `Shown ${inFileManager()}` };

/** An outcome to show on a dialog's status line. */
export type LaunchResult = { kind: "info" | "error"; text: string };
type Report = (result: LaunchResult) => void;

/** Inside a modal dialog: where launch outcomes go instead of toasts. */
export const InlineResults = createContext<Report | null>(null);

/** A dialog's status line state: ``report`` an outcome, render ``<DialogStatus>``. */
export function useDialogStatus() {
  const [result, setResult] = useState<(LaunchResult & { n: number }) | null>(null);
  const count = useRef(0);
  const report = useCallback((r: LaunchResult) => setResult({ ...r, n: ++count.current }), []);
  const clear = useCallback(() => setResult(null), []);
  return { result, report, clear };
}

/** The ``role="status"`` line inside a dialog (always there, so a change is announced). */
export function DialogStatus({ status }: { status: ReturnType<typeof useDialogStatus> }) {
  const { result } = status;
  return (
    <p className={result?.kind === "error" ? "dialog-status is-error" : "dialog-status"} role="status">
      {/* keyed: the same text again (a second refusal) is a new announcement */}
      {result && <span key={result.n}>{visible(result.text)}</span>}
    </p>
  );
}

/** ``run("open" | "reveal")``, one request at a time (a synchronous guard: a double
 * click sends one). Outcomes go to ``onResult``, else to the dialog's
 * ``InlineResults``, else a refusal is a toast (success needs no toast there). */
export function useFileLaunch(driveId: string, onResult?: Report) {
  const toast = useToast();
  const inline = useContext(InlineResults);
  const report = onResult ?? inline;
  const inFlight = useRef(false);
  const [busy, setBusy] = useState(false);
  const run = async (how: How) => {
    if (inFlight.current) return;
    inFlight.current = true;
    setBusy(true);
    try {
      await launchFile(driveId, how);
      report?.({ kind: "info", text: DONE[how]() });
    } catch (e) {
      // A 409 is a full sentence already ("Won't open apps or scripts …").
      const reason = e instanceof ApiError && e.detail ? e.detail : errorText(e);
      const text = visible(e instanceof ApiError && e.status === 409 ? reason : `${FAILED[how]()}: ${reason}`);
      if (report) report({ kind: "error", text });
      else toast({ kind: "error", text });
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  };
  return { busy, run };
}

type Props = {
  launch: ReturnType<typeof useFileLaunch>;
  tipSide?: "below" | "above";
  /** "reveal": Show in Finder alone (a link to outside the archive opens nothing). */
  only?: "reveal";
  /** The file's archive folder is not connected: both buttons are off. */
  offline?: boolean;
};

/** The Open and Show in Finder icon buttons. */
export function LaunchButtons({ launch, tipSide, only, offline = false }: Props) {
  const reason = offline ? "Not connected" : launch.busy ? LAUNCH_BUSY : undefined;
  return (
    <>
      {only !== "reveal" && (
        <IconButton
          icon={<ExternalLink {...ICON} />}
          label="Open"
          tipSide={tipSide}
          disabled={launch.busy || offline}
          disabledReason={reason}
          onClick={() => void launch.run("open")}
        />
      )}
      <IconButton
        icon={<FolderSearch {...ICON} />}
        label={showInLabel()}
        tipSide={tipSide}
        disabled={launch.busy || offline}
        disabledReason={reason}
        onClick={() => void launch.run("reveal")}
      />
    </>
  );
}
