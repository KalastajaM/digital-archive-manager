/** The sheet that names a saved search: Save search… in Browse's filter row, and Rename…
 * on a saved search in the sidebar. Saving under a name in use asks to replace that one,
 * which is how a saved search is changed: open it, edit the search, save it again. */
import { type FormEvent, useState } from "react";
import { ApiError, errorText, type SavedSearch, useSavedSearchActions } from "../api/client";
import { visible } from "../text";
import { useToast } from "./Toasts";
import { Sheet } from "./ui/Sheet";

type Props =
  | { mode: "save"; query: string; tagMode: "all" | "any"; initial?: string; onClose: () => void }
  | { mode: "rename"; search: SavedSearch; onClose: () => void };

export function SaveSearchSheet(props: Props) {
  const actions = useSavedSearchActions();
  const toast = useToast();
  const initial = props.mode === "rename" ? props.search.name : (props.initial ?? "");
  const [name, setName] = useState(initial);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // the name in use that saving would replace (asked once; Replace confirms)
  const [replacing, setReplacing] = useState<string | null>(null);
  const trimmed = name.replace(/\s+/g, " ").trim();
  const unchanged = props.mode === "rename" && trimmed === initial;
  const run = async (replace: boolean) => {
    if (!trimmed || unchanged || busy) return;
    setBusy(true);
    setError(null);
    try {
      if (props.mode === "rename") {
        const done = await actions.rename(props.search.id, trimmed);
        toast({ kind: "info", text: `Renamed the search to "${visible(done.name)}"` });
      } else {
        const done = await actions.save({ name: trimmed, query: props.query, tag_mode: props.tagMode, replace });
        toast({ kind: "info", text: `${replace ? "Replaced" : "Saved"} the search "${visible(done.name)}"` });
      }
      props.onClose();
    } catch (e) {
      if (props.mode === "save" && e instanceof ApiError && e.status === 409) setReplacing(trimmed);
      else setError(errorText(e));
      setBusy(false);
    }
  };
  const go = (e?: FormEvent) => {
    e?.preventDefault();
    void run(replacing !== null && replacing === trimmed);
  };
  const asking = replacing !== null && replacing === trimmed;
  return (
    <Sheet
      open
      className="save-search-sheet"
      title={props.mode === "rename" ? `Rename ${visible(props.search.name)}` : "Save search"}
      onClose={props.onClose}
      footer={
        <>
          <button type="button" onClick={props.onClose}>
            Cancel
          </button>
          <button type="button" className="primary" disabled={!trimmed || unchanged || busy} onClick={() => go()}>
            {props.mode === "rename" ? "Rename" : asking ? "Replace" : "Save"}
          </button>
        </>
      }
    >
      <form onSubmit={go}>
        <label className="field">
          <span>Name</span>
          <input value={name} onChange={(e) => setName(e.target.value)} maxLength={200} spellCheck={false} autoFocus />
        </label>
      </form>
      {props.mode === "save" && (
        <p className="muted save-search-query" title={props.query}>
          <code>{visible(props.query)}</code>
        </p>
      )}
      {asking && (
        <p className="notice" role="alert">
          A search named "{visible(trimmed)}" exists. Replace it with this search?
        </p>
      )}
      {error && (
        <p className="error" role="alert">
          {visible(error)}
        </p>
      )}
    </Sheet>
  );
}
