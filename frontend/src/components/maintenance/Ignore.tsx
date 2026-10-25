/** Ignoring results: an entry the owner ignores is left out of every later result of its
 * check (the server filters it), kept in the archive's database across runs and Reset.
 * Each card lists what it ignores, where an entry can be taken back. Nothing in the
 * archive changes. */
import { useState } from "react";
import { errorText, type IgnoreKind, useMaintenanceIgnore, useMaintenanceIgnored } from "../../api/client";
import { plural } from "../../format";
import { visible } from "../../text";
import { undoAction, useToast } from "../Toasts";

type Entry = { kind: IgnoreKind; key: string; label: string; members?: string[] };

/** Ignore an entry; the toast offers Undo. ``onChange``: read the check's result again. */
export function useIgnore(onChange: () => void) {
  const change = useMaintenanceIgnore();
  const toast = useToast();
  return {
    busy: change.isPending,
    ignore: (entry: Entry) =>
      change
        .mutateAsync(entry)
        .then((added) => {
          onChange();
          toast({
            kind: "info",
            text: `Ignored ${visible(entry.label)}`,
            action: added
              ? undoAction(() =>
                  void change
                    .mutateAsync({ stop: added.id })
                    .then(onChange)
                    .catch((e) => toast({ kind: "error", text: `Still ignored: ${visible(errorText(e))}` })),
                )
              : undefined,
          });
        })
        .catch((e) => toast({ kind: "error", text: `Not ignored: ${visible(errorText(e))}` })),
  };
}

export function IgnoreButton({ label, onClick, disabled }: { label: string; onClick: () => void; disabled?: boolean }) {
  return (
    <button
      type="button"
      className="link-button"
      onClick={onClick}
      disabled={disabled}
      aria-label={`Ignore ${visible(label)}`}
      title="Leave this out of later results. You can take it back under Ignored."
    >
      Ignore
    </button>
  );
}

/** "3 ignored": opens the list of what this card ignores, each with Stop ignoring. */
export function IgnoredList({ kinds, onChange }: { kinds: IgnoreKind[]; onChange: () => void }) {
  const all = useMaintenanceIgnored();
  const change = useMaintenanceIgnore();
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const mine = (all.data ?? []).filter((i) => kinds.includes(i.kind as IgnoreKind));
  if (mine.length === 0) return null;
  const stop = (id: number, label: string) =>
    change
      .mutateAsync({ stop: id })
      .then(() => {
        onChange();
        toast({ kind: "info", text: `No longer ignored: ${visible(label)}` });
      })
      .catch((e) => toast({ kind: "error", text: `Still ignored: ${visible(errorText(e))}` }));
  return (
    <div className="ignored">
      <button type="button" className="link-button" aria-expanded={open} onClick={() => setOpen(!open)}>
        {open ? "Hide ignored" : `${plural(mine.length, "ignored entry", "ignored entries")}`}
      </button>
      {open && (
        <ul className="check-list">
          {mine.map((i) => (
            <li key={i.id}>
              <code>{visible(i.label)}</code>
              <button
                type="button"
                className="link-button"
                disabled={change.isPending}
                onClick={() => void stop(i.id, i.label)}
                aria-label={`Stop ignoring ${visible(i.label)}`}
              >
                Stop ignoring
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
