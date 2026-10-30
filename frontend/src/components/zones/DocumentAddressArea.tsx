/** The address area of the document on show (New look): the usual one, its own, or none,
 * with the way to remove it or to go back to the usual one. Shown while the areas are shown
 * or Draw a box is on (``open``), and always when the document has none, so it can get one
 * back. A box drawn with Draw a box gives the document its own (``BoxPanel``); moving the
 * box on the page moves this document's own. */
import { errorText, useAddressArea, usePeople, useSetAddressArea } from "../../api/client";
import { visible } from "../../text";

const SAYS = {
  general: "This document uses the usual address area.",
  document: "This document has its own address area.",
  none: "This document has no address area: nobody is looked for on it.",
} as const;

export function DocumentAddressArea({ driveId, open }: { driveId: string; open: boolean }) {
  const people = usePeople();
  const area = useAddressArea(driveId);
  const set = useSetAddressArea();
  // without people there is nobody to look for, so the area does not matter
  if (!people.data?.people.length || !area.data) return null;
  const state = area.data.state;
  if (!open && state !== "none") return null;
  return (
    <div className="document-address-area" role="group" aria-label="Address area of this document">
      <span className="hint">{SAYS[state]}</span>
      {state === "general" ? (
        <button type="button" disabled={set.isPending} onClick={() => set.mutate({ driveId, box: null })}>
          No address area on this document
        </button>
      ) : (
        <button type="button" disabled={set.isPending} onClick={() => set.mutate({ driveId, box: "general" })}>
          Use the usual address area
        </button>
      )}
      {set.isError && (
        <p className="error" role="alert">
          {visible(errorText(set.error))}
        </p>
      )}
    </div>
  );
}
