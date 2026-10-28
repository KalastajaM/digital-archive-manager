/** Mark an item done from a list: completes at once, sending each done field's default
 * (``paid_on``: today), with a toast that offers Undo. Only a done field that is
 * required and has no default needs the small form (``needsForm``): the caller opens
 * ``DoneForm`` instead. Shared by Today's rows, the New look's bill table and Pay mode. */
import { errorText, type TrayDef, useItemDone, useItemReopen } from "../api/client";
import { visible } from "../text";
import { useToast } from "./Toasts";

/** The done action's button text: the tray's label, "Mark done" for the plain "Done". */
export const markLabel = (doneLabel: string) => (doneLabel === "Done" ? "Mark done" : doneLabel);

export function useMarkDone(item: { id: number; title: string }, tray: TrayDef | undefined, today: string) {
  const markDone = useItemDone();
  const reopen = useItemReopen();
  const toast = useToast();
  const doneFields = tray?.done?.fields ?? {};
  const doneLabel = tray?.done?.label ?? "Done";
  const title = visible(item.title);
  const doneWord = visible(doneLabel).replace(/^mark\s+/i, "").toLowerCase();
  const needsForm = Object.values(doneFields).some((f) => f.required && f.type !== "checkbox" && !f.default);
  const defaults = Object.fromEntries(
    Object.entries(doneFields).flatMap(([n, f]): [string, string | boolean][] =>
      f.type === "checkbox" ? [[n, false]] : f.default === "today" ? [[n, today]] : [],
    ),
  );
  /** Resolves true when the item was marked done (false: it failed, and the toast says so). */
  const run = async (): Promise<boolean> => {
    try {
      await markDone.mutateAsync({ id: item.id, fields: defaults });
    } catch (err) {
      toast({ kind: "error", text: `Could not mark ${title} ${doneWord}: ${visible(errorText(err))}` });
      return false;
    }
    toast({
      kind: "info",
      text: `Marked ${doneWord}: ${title}`,
      action: {
        label: "Undo",
        run: () =>
          void reopen.mutateAsync(item.id).then(
            () => toast({ kind: "info", text: `Reopened: ${title}` }),
            (err) => toast({ kind: "error", text: `Could not reopen ${title}: ${visible(errorText(err))}` }),
          ),
      },
    });
    return true;
  };
  return { needsForm, pending: markDone.isPending, run, label: doneLabel, fields: doneFields };
}
