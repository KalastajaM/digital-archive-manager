import { useQueryClient } from "@tanstack/react-query";
import { CircleAlert } from "lucide-react";
import { useState } from "react";
import { addArchive, errorText, navigation, switchArchive, useArchives } from "../api/client";
import { ArchiveSwatches } from "./ArchiveSwatches";
import { freeColor } from "./archivePalette";
import { FolderPathInput } from "./FolderPathInput";
import { Sheet } from "./ui/Sheet";

type Kind = "own" | "demo";

/** Add an archive: its name and colour first, then either the usual first-run steps for
 * a folder of your own (the new archive opens in setup), or a fictional demo archive
 * built in a folder you pick. A new archive is fully separate from the others. */
export function AddArchive({ open, onClose }: { open: boolean; onClose: () => void }) {
  const client = useQueryClient();
  const archives = useArchives(open);
  const [name, setName] = useState("");
  const [color, setColor] = useState<string | null>(null);
  const [kind, setKind] = useState<Kind>("own");
  const [folder, setFolder] = useState("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  const suggested = freeColor((archives.data?.archives ?? []).map((a) => a.color));
  const chosen = color ?? suggested;
  const ready = name.trim() !== "" && (kind === "own" || folder.trim() !== "");

  const submit = async () => {
    setBusy(true);
    setProblem(null);
    let added = null;
    try {
      added = await addArchive(name.trim(), chosen, kind === "demo" ? folder.trim() : undefined);
      void client.invalidateQueries({ queryKey: ["archives"] });
      await switchArchive(added.id);
      navigation.leave(); // a fresh load of the new archive (its setup, or the demo)
    } catch (e) {
      setProblem(added ? `Added "${added.name}", but it could not be opened: ${errorText(e)}` : errorText(e));
      setBusy(false);
    }
  };

  return (
    <Sheet
      open={open}
      title="Add archive"
      onClose={() => !busy && onClose()}
      footer={
        <>
          <button type="button" onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button type="button" className="primary" disabled={!ready || busy} onClick={() => void submit()}>
            {busy ? (kind === "demo" ? "Building the demo…" : "Adding…") : kind === "demo" ? "Create demo archive" : "Add and set up"}
          </button>
        </>
      }
    >
      <p className="first-run-hint">
        A new archive is completely separate: its own folder, settings, index and reminders. Nothing in your other archives changes.
      </p>
      <div className="field">
        <label htmlFor="add-archive-name">Name</label>
        <input
          id="add-archive-name"
          type="text"
          value={name}
          maxLength={40}
          autoComplete="off"
          placeholder="For example Test"
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && ready && !busy) void submit();
          }}
        />
      </div>
      <div className="field">
        <span className="field-label" id="add-archive-color">
          Colour
        </span>
        <ArchiveSwatches value={chosen} onPick={setColor} label="Colour" disabled={busy} />
      </div>
      <fieldset className="first-run-choice">
        <legend>Which archive?</legend>
        <label>
          <input type="radio" name="add-archive-kind" checked={kind === "own"} onChange={() => setKind("own")} disabled={busy} />
          <span>
            <strong>Use a folder of my own</strong>
            <span className="layout-template-hint">Next you choose the folder, or start a new archive in an empty one.</span>
          </span>
        </label>
        <label>
          <input type="radio" name="add-archive-kind" checked={kind === "demo"} onChange={() => setKind("demo")} disabled={busy} />
          <span>
            <strong>Create a demo archive</strong>
            <span className="layout-template-hint">A small fictional archive to try things out. Good for testing.</span>
          </span>
        </label>
      </fieldset>
      {kind === "demo" && (
        <div className="field">
          <label htmlFor="add-archive-folder">Folder for the demo archive</label>
          <FolderPathInput
            id="add-archive-folder"
            value={folder}
            spellCheck={false}
            autoComplete="off"
            placeholder="A new or empty folder, e.g. /Users/you/Documents/Demo archive"
            onChange={setFolder}
            disabled={busy}
          />
          <p className="first-run-hint">The folder must be new or empty. dam creates the demo files inside it.</p>
        </div>
      )}
      {problem && (
        <p className="first-run-problem" role="alert">
          <CircleAlert size={14} aria-hidden="true" /> {problem}
        </p>
      )}
    </Sheet>
  );
}
