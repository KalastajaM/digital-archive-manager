import { useQueryClient } from "@tanstack/react-query";
import { CircleAlert } from "lucide-react";
import { useState } from "react";
import {
  addArchive,
  checkDataFolder,
  type DataFolderCheck,
  errorText,
  navigation,
  switchArchive,
  useArchives,
} from "../api/client";
import { ArchiveSwatches } from "./ArchiveSwatches";
import { freeColor } from "./archivePalette";
import { FolderPathInput } from "./FolderPathInput";
import { Sheet } from "./ui/Sheet";

type Kind = "own" | "demo";

/** Add an archive: its name and colour first, then either the usual first-run steps for
 * a folder of your own (the new archive opens in setup), or a fictional demo archive
 * built in a folder you pick. A new archive is fully separate from the others. */
export function AddArchive({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const client = useQueryClient();
  const archives = useArchives(open);
  const [name, setName] = useState("");
  const [color, setColor] = useState<string | null>(null);
  const [kind, setKind] = useState<Kind>("own");
  const [folder, setFolder] = useState("");
  const [ownData, setOwnData] = useState(false);
  const [dataFolder, setDataFolder] = useState("");
  // a data folder that already holds dam data, waiting for the owner's decision
  const [existing, setExisting] = useState<DataFolderCheck | null>(null);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  const suggested = freeColor(
    (archives.data?.archives ?? []).map((a) => a.color),
  );
  const chosen = color ?? suggested;
  const customData = kind === "own" && ownData;
  const ready =
    name.trim() !== "" &&
    (kind === "own" || folder.trim() !== "") &&
    (!customData || dataFolder.trim() !== "");

  const submit = async (confirmed = false) => {
    setBusy(true);
    setProblem(null);
    let added = null;
    try {
      if (customData && !confirmed) {
        const check = await checkDataFolder(dataFolder.trim());
        if (check.state === "refused") {
          setProblem(check.message);
          setBusy(false);
          return;
        }
        if (check.state === "dam_data") {
          setExisting(check);
          setBusy(false);
          return;
        }
      }
      added = await addArchive(
        name.trim(),
        chosen,
        kind === "demo" ? folder.trim() : undefined,
        customData
          ? { path: dataFolder.trim(), useExisting: existing !== null }
          : undefined,
      );
      void client.invalidateQueries({ queryKey: ["archives"] });
      await switchArchive(added.id);
      navigation.leave(); // a fresh load of the new archive (its setup, or the demo)
    } catch (e) {
      setProblem(
        added
          ? `Added "${added.name}", but it could not be opened: ${errorText(e)}`
          : errorText(e),
      );
      setBusy(false);
    }
  };

  return (
    <Sheet
      open={open}
      title="Add archive"
      onClose={() => !busy && onClose()}
      footer={
        existing ? (
          <>
            <button
              type="button"
              onClick={() => setExisting(null)}
              disabled={busy}
            >
              Choose another folder
            </button>
            <button
              type="button"
              className="primary"
              disabled={busy}
              onClick={() => void submit(true)}
            >
              {busy ? "Adding…" : "Use this data"}
            </button>
          </>
        ) : (
          <>
            <button type="button" onClick={onClose} disabled={busy}>
              Cancel
            </button>
            <button
              type="button"
              className="primary"
              disabled={!ready || busy}
              onClick={() => void submit()}
            >
              {busy
                ? kind === "demo"
                  ? "Building the demo…"
                  : "Adding…"
                : kind === "demo"
                  ? "Create demo archive"
                  : customData
                    ? "Check and add"
                    : "Add and set up"}
            </button>
          </>
        )
      }
    >
      {existing ? (
        <ExistingData check={existing} />
      ) : (
        <>
          <p className="first-run-hint">
            A new archive is completely separate: its own folder, settings,
            index and reminders. Nothing in your other archives changes.
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
            <ArchiveSwatches
              value={chosen}
              onPick={setColor}
              label="Colour"
              disabled={busy}
            />
          </div>
          <fieldset className="first-run-choice">
            <legend>Which archive?</legend>
            <label>
              <input
                type="radio"
                name="add-archive-kind"
                checked={kind === "own"}
                onChange={() => setKind("own")}
                disabled={busy}
              />
              <span>
                <strong>Use a folder of my own</strong>
                <span className="layout-template-hint">
                  Next you choose the folder, or start a new archive in an empty
                  one.
                </span>
              </span>
            </label>
            <label>
              <input
                type="radio"
                name="add-archive-kind"
                checked={kind === "demo"}
                onChange={() => setKind("demo")}
                disabled={busy}
              />
              <span>
                <strong>Create a demo archive</strong>
                <span className="layout-template-hint">
                  A small fictional archive to try things out. Good for testing.
                </span>
              </span>
            </label>
          </fieldset>
          {kind === "demo" && (
            <div className="field">
              <label htmlFor="add-archive-folder">
                Folder for the demo archive
              </label>
              <FolderPathInput
                id="add-archive-folder"
                value={folder}
                spellCheck={false}
                autoComplete="off"
                placeholder="A new or empty folder, e.g. /Users/you/Documents/Demo archive"
                onChange={setFolder}
                disabled={busy}
              />
              <p className="first-run-hint">
                The folder must be new or empty. dam creates the demo files
                inside it.
              </p>
            </div>
          )}
          {kind === "own" && (
            <fieldset className="first-run-choice">
              <legend>Where does dam keep this archive's data?</legend>
              <label>
                <input
                  type="radio"
                  name="add-archive-data"
                  checked={!ownData}
                  onChange={() => setOwnData(false)}
                  disabled={busy}
                />
                <span>
                  <strong>In dam's own folder</strong>
                  <span className="layout-template-hint">
                    The settings, index and logs. Recommended.
                  </span>
                </span>
              </label>
              <label>
                <input
                  type="radio"
                  name="add-archive-data"
                  checked={ownData}
                  onChange={() => setOwnData(true)}
                  disabled={busy}
                />
                <span>
                  <strong>In a folder I choose</strong>
                  <span className="layout-template-hint">
                    For example a copy of the data from another computer. Choose
                    a folder on this computer that no cloud service syncs.
                  </span>
                </span>
              </label>
            </fieldset>
          )}
          {customData && (
            <div className="field">
              <label htmlFor="add-archive-data-folder">Data folder</label>
              <FolderPathInput
                id="add-archive-data-folder"
                value={dataFolder}
                spellCheck={false}
                autoComplete="off"
                placeholder="A new or empty folder, or one that holds dam data"
                onChange={setDataFolder}
                disabled={busy}
              />
            </div>
          )}
        </>
      )}
      {problem && (
        <p className="first-run-problem" role="alert">
          <CircleAlert size={14} aria-hidden="true" /> {problem}
        </p>
      )}
    </Sheet>
  );
}

/** The question asked when the chosen data folder already holds dam data. */
function ExistingData({ check }: { check: DataFolderCheck }) {
  return (
    <>
      <p>
        <strong>This folder already holds dam data.</strong>
      </p>
      <p>
        <code>{check.path}</code>
      </p>
      {check.archive_root ? (
        <p>
          It belongs to an archive whose documents are in{" "}
          <code>{check.archive_root}</code>
          {check.archive_root_exists
            ? "."
            : ", a folder that is not on this computer."}
        </p>
      ) : (
        <p>It does not name a documents folder yet.</p>
      )}
      {check.archive_root && !check.archive_root_exists && (
        <p className="first-run-hint">
          After adding, choose where the documents are on this computer with
          Change folder in Settings, Archive folders.
        </p>
      )}
      <p>
        Use this data to keep its index, tags, notes, trays and rules. Nothing
        is copied or deleted.
      </p>
      <p className="first-run-hint">
        Use it only if no other dam is using this data, on this or another
        computer.
      </p>
    </>
  );
}
