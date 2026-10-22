import { useEffect, useState } from "react";
import { copyText } from "../format";
import { visible } from "../text";
import { useToast } from "./Toasts";

const COPIED_MS = 1500;

/** "Copy <label>": puts ``value`` on the clipboard (IBANs compact, amounts as "84,20"
 * via the field ``type``) and confirms with "Copied" for 1.5 s. ``compact`` shows just
 * "Copy" (the accessible name still says what), for rows that already name the value. */
export function CopyButton({
  value,
  label,
  type,
  compact = false,
}: {
  value: string;
  label: string;
  type?: string;
  compact?: boolean;
}) {
  const toast = useToast();
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    if (!copied) return;
    const timer = setTimeout(() => setCopied(false), COPIED_MS);
    return () => clearTimeout(timer);
  }, [copied]);

  const copy = async () => {
    const clipboard = typeof navigator !== "undefined" ? navigator.clipboard : undefined;
    if (!clipboard?.writeText) {
      toast({ kind: "warning", text: `Copy not available here: select the ${label} and copy it by hand.` });
      return;
    }
    try {
      await clipboard.writeText(copyText(type, value));
      setCopied(true);
    } catch {
      toast({ kind: "warning", text: `Could not copy the ${label} (copy not available).` });
    }
  };

  return (
    <span className="copy">
      <button
        type="button"
        className={compact ? "copy-compact" : undefined}
        aria-label={compact ? `Copy ${visible(label)}` : undefined}
        onClick={() => void copy()}
      >
        {compact ? "Copy" : `Copy ${visible(label)}`}
      </button>
      {copied && (
        <span role="status" className="copied">
          Copied
        </span>
      )}
    </span>
  );
}
