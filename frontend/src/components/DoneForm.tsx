/** The done fields of an item's tray with their defaults; Enter confirms, Esc cancels.
 * Marking done changes only the database (no files move), so no plan confirm.
 * Shared by Today and the Trays screen. */
import { type FormEvent, useEffect, useId, useRef, useState } from "react";
import { errorText, type FieldDef, useItemDone, useItemReopen } from "../api/client";
import { fieldLabel } from "../format";
import { dialogOpen, isTyping, useKeydown } from "../keyboard";
import { visible } from "../text";
import { FieldInput } from "./FieldInput";
import { useToast } from "./Toasts";

type Values = Record<string, string | boolean>;

function initialValues(fields: Record<string, FieldDef>, today: string): Values {
  const values: Values = {};
  for (const [name, def] of Object.entries(fields)) {
    if (def.type === "checkbox") values[name] = false;
    else values[name] = def.default === "today" ? today : "";
  }
  return values;
}

export function DoneForm({
  item,
  label,
  fields,
  today,
  onClose,
  submitLabel,
  onDone,
}: {
  item: { id: number; title: string };
  /** The tray's done label ("Mark paid"). */
  label: string;
  fields: Record<string, FieldDef>;
  today: string;
  onClose: () => void;
  /** The submit button's text when it does more than ``label`` ("Mark paid & file it…"). */
  submitLabel?: string;
  /** After the item was marked done (and the form closed). */
  onDone?: () => void;
}) {
  const ids = useId();
  const toast = useToast();
  const done = useItemDone();
  const reopen = useItemReopen();
  const [values, setValues] = useState<Values>(() => initialValues(fields, today));
  const [error, setError] = useState<string | null>(null);
  const sending = useRef(false); // synchronous: a second Enter never posts twice
  const formRef = useRef<HTMLFormElement>(null);
  const names = Object.keys(fields);
  const { id, title } = item;

  useEffect(() => {
    formRef.current?.querySelector<HTMLElement>("input, button[type=submit]")?.focus();
  }, []);
  // Esc cancels even after the focus has left the form (keys inside it are handled
  // below); never while typing in another field or with a dialog open.
  useKeydown((e) => {
    if (e.key !== "Escape" || e.metaKey || e.ctrlKey || e.altKey || dialogOpen()) return;
    const target = e.target instanceof Node ? e.target : null;
    if (target && formRef.current?.contains(target)) return;
    if (isTyping(e.target)) return;
    onClose();
  });

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (sending.current) return;
    sending.current = true;
    setError(null);
    // Blank text is left out, so the server applies the field's default (paid_on: today)
    // or reports a missing required field; checkboxes are always sent (false is stored).
    const sent = Object.fromEntries(Object.entries(values).filter(([, v]) => v !== ""));
    try {
      await done.mutateAsync({ id, fields: sent });
      onClose();
      onDone?.();
      toast({
        kind: "info",
        text: `${label}: ${title}`,
        action: {
          label: "Reopen",
          run: () => {
            reopen
              .mutateAsync(id)
              .then(() => toast({ kind: "info", text: `Reopened: ${title}` }))
              .catch((err) => toast({ kind: "error", text: `Could not reopen ${title}: ${errorText(err)}` }));
          },
        },
      });
    } catch (err) {
      setError(errorText(err));
    } finally {
      sending.current = false;
    }
  };

  return (
    <form
      ref={formRef}
      className="done-form"
      aria-label={visible(label)}
      onSubmit={(e) => void submit(e)}
      onKeyDown={(e) => {
        if (e.key === "Escape") {
          e.preventDefault();
          e.stopPropagation();
          onClose();
        }
      }}
    >
      {names.length === 0 && <p>Mark “{visible(title)}” as done?</p>}
      {names.map((name) => {
        const inputId = `${ids}-${name}`;
        return (
          <div className="field" key={name}>
            <label htmlFor={inputId}>{visible(fieldLabel(name))}</label>
            <FieldInput
              id={inputId}
              def={fields[name]}
              value={values[name]}
              onChange={(v) => setValues((old) => ({ ...old, [name]: v }))}
            />
          </div>
        );
      })}
      {error && (
        <p className="error" role="alert">
          {visible(error)}
        </p>
      )}
      <div className="actions">
        <button type="button" onClick={onClose}>
          Cancel
        </button>
        <button type="submit" className="primary" disabled={done.isPending}>
          {visible(submitLabel ?? label)}
        </button>
      </div>
    </form>
  );
}
