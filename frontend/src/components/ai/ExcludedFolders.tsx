/** Activity → AI: the folders whose documents are never sent to AI (``ai.exclude_folders``
 * in settings.yaml). Adding one applies at once; removing one asks first, because its
 * documents can then be sent (still only after the What will be sent sheet). The list
 * is saved whole: it replaces the shipped defaults. */
import { FolderX, X } from "lucide-react";
import { type FormEvent, useRef, useState } from "react";
import { type AIStatus, errorText, useAIExcludeFolders } from "../../api/client";
import { visible } from "../../text";
import { FolderPicker } from "../FolderPicker";
import { ConfirmPlan } from "../PlanPreview";
import { IconButton } from "../ui/IconButton";

export function ExcludedFolders({ status }: { status: AIStatus }) {
  const save = useAIExcludeFolders();
  const [adding, setAdding] = useState("");
  const [removing, setRemoving] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const inFlight = useRef(false);
  const folders = status.exclude_folders;
  const missing = new Set(status.exclude_missing);

  const write = async (next: string[]): Promise<boolean> => {
    if (inFlight.current) return false;
    inFlight.current = true;
    setError(null);
    try {
      await save.mutateAsync(next);
      return true;
    } catch (e) {
      setError(errorText(e));
      return false;
    } finally {
      inFlight.current = false;
    }
  };
  const add = async (e: FormEvent) => {
    e.preventDefault();
    const folder = adding.trim();
    if (!folder) return setError("Choose a folder.");
    if (await write([...folders, folder])) setAdding("");
  };

  return (
    <section className="ai-excluded" aria-label="Excluded folders">
      <h3>Excluded folders</h3>
      <p className="hint">
        Documents in these folders (and every folder inside them) are never sent to AI, by any AI action. Saved in
        settings.yaml.
      </p>
      {folders.length === 0 ? (
        <p className="hint">None: every folder can be sent (only ever after you click Send).</p>
      ) : (
        <ul className="ai-excluded-list">
          {folders.map((f) => (
            <li key={f}>
              <FolderX size={14} aria-hidden="true" />
              <code>{visible(f)}</code>
              {missing.has(f) && <span className="hint">not in the archive</span>}
              <IconButton
                icon={<X />}
                label={`Stop excluding ${visible(f)}`}
                disabled={save.isPending}
                onClick={() => setRemoving(f)}
              />
            </li>
          ))}
        </ul>
      )}
      <form className="ai-excluded-add" onSubmit={(e) => void add(e)}>
        <FolderPicker label="Exclude a folder" value={adding} onChange={setAdding} />
        <button type="submit" disabled={save.isPending || !adding.trim()}>
          Exclude
        </button>
      </form>
      {error && (
        <p className="error" role="alert">
          {visible(error)}
        </p>
      )}
      {removing !== null && (
        <ConfirmPlan
          planKey={`stop-excluding-${removing}`}
          title={`Stop excluding ${visible(removing)}?`}
          ops={[]}
          busy={save.isPending}
          confirmLabel="Stop excluding"
          danger
          onConfirm={async () => {
            const folder = removing;
            await write(folders.filter((f) => f !== folder));
            setRemoving(null);
          }}
          onCancel={() => setRemoving(null)}
        >
          <p>
            Documents in {visible(removing)} can then be sent to AI. Nothing is sent by this: every AI action still
            shows exactly what will be sent and waits for your Send.
          </p>
        </ConfirmPlan>
      )}
    </section>
  );
}
