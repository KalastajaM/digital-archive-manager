/** Mark an item done from a list: completes at once, sending each done field's default
 * (``paid_on``: today), with a toast that offers Undo. Only a done field that is
 * required and has no default needs the small form (``needsForm``): the caller opens
 * ``DoneForm`` instead. Shared by Today's rows, the bill table, Pay mode and the tray
 * items' right-click menu. */
import { errorText, type TrayDef, useItemDone, useItemReopen } from "../api/client";
import { visible } from "../text";
import { useToast } from "./Toasts";

/** The done action's button text: the tray's label, "Mark done" for the plain "Done". */
export const markLabel = (doneLabel: string) => (doneLabel === "Done" ? "Mark done" : doneLabel);

type Done = { id: number; title: string };

/** What a tray's done step needs: its label and fields, whether a form must be filled
 * first, and the defaults sent without one. */
export function doneOf(tray: TrayDef | undefined, today: string) {
  const fields = tray?.done?.fields ?? {};
  const label = tray?.done?.label ?? "Done";
  const needsForm = Object.values(fields).some((f) => f.required && f.type !== "checkbox" && !f.default);
  const defaults = Object.fromEntries(
    Object.entries(fields).flatMap(([n, f]): [string, string | boolean][] =>
      f.type === "checkbox" ? [[n, false]] : f.default === "today" ? [[n, today]] : [],
    ),
  );
  return { fields, label, needsForm, defaults };
}

/** Mark any item done (``run``) or open again (``reopen``), each said in a toast; done
 * offers Undo. */
export function useDoneFlow() {
  const markDone = useItemDone();
  const reopenItem = useItemReopen();
  const toast = useToast();
  const reopen = (item: Done) =>
    reopenItem.mutateAsync(item.id).then(
      () => toast({ kind: "info", text: `Reopened: ${visible(item.title)}` }),
      (err) => toast({ kind: "error", text: `Could not reopen ${visible(item.title)}: ${visible(errorText(err))}` }),
    );
  /** Resolves true when the item was marked done (false: it failed, and the toast says so). */
  const run = async (item: Done, tray: TrayDef | undefined, today: string): Promise<boolean> => {
    const { label, defaults } = doneOf(tray, today);
    const title = visible(item.title);
    const doneWord = visible(label).replace(/^mark\s+/i, "").toLowerCase();
    try {
      await markDone.mutateAsync({ id: item.id, fields: defaults });
    } catch (err) {
      toast({ kind: "error", text: `Could not mark ${title} ${doneWord}: ${visible(errorText(err))}` });
      return false;
    }
    toast({ kind: "info", text: `Marked ${doneWord}: ${title}`, action: { label: "Undo", run: () => void reopen(item) } });
    return true;
  };
  return { run, reopen, pending: markDone.isPending };
}

export function useMarkDone(item: Done, tray: TrayDef | undefined, today: string) {
  const flow = useDoneFlow();
  const done = doneOf(tray, today);
  return { needsForm: done.needsForm, pending: flow.pending, run: () => flow.run(item, tray, today), label: done.label, fields: done.fields };
}
