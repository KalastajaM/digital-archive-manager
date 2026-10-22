import { useQueryClient } from "@tanstack/react-query";
import { CircleAlert, CircleCheck } from "lucide-react";
import { useState } from "react";
import {
  type Archive,
  type ArchiveForgotten,
  errorText,
  forgetArchive,
  navigation,
  revealArchive,
  updateArchive,
  useArchives,
} from "../api/client";
import { fileManagerName } from "../fileManager";
import { visible } from "../text";
import { ArchiveSwatches } from "./ArchiveSwatches";
import { Sheet } from "./ui/Sheet";
import { TipButton } from "./ui/TipButton";

function PathRow({ label, path, onShow, manager }: { label: string; path: string | null; onShow: () => void; manager: string }) {
  return (
    <div className="archive-path">
      <span className="archive-path-label">{label}</span>
      {path ? <code title={path}>{path}</code> : <span className="first-run-hint">Not set up yet</span>}
      <button type="button" disabled={!path} onClick={onShow} aria-label={`Show ${label.toLowerCase()} in ${manager}`}>
        Show in {manager}
      </button>
    </div>
  );
}

/** One archive in the list: rename, colour, where its folders are, forget. */
function ArchiveRow({ archive, all, onForgotten }: { archive: Archive; all: Archive[]; onForgotten: (r: ArchiveForgotten) => void }) {
  const client = useQueryClient();
  const manager = fileManagerName() ?? "file manager";
  const [name, setName] = useState(archive.name);
  const [problem, setProblem] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);
  const others = all.filter((a) => a.id !== archive.id);
  const [instead, setInstead] = useState(others.find((a) => !a.in_use_elsewhere)?.id ?? others[0]?.id ?? "");
  const changed = name.trim() !== "" && name.trim() !== archive.name;
  const refresh = () => {
    void client.invalidateQueries({ queryKey: ["archives"] });
    void client.invalidateQueries({ queryKey: ["status"] });
  };
  const attempt = async (run: () => Promise<unknown>) => {
    setProblem(null);
    try {
      await run();
      refresh();
    } catch (e) {
      setProblem(errorText(e));
    }
  };
  const forget = async () => {
    setProblem(null);
    try {
      const done = await forgetArchive(archive.id, archive.current ? instead : undefined);
      refresh();
      onForgotten(done);
      if (archive.current) navigation.leave(); // the server opened the other archive
    } catch (e) {
      setProblem(errorText(e));
    }
  };
  const label = visible(archive.name);
  return (
    <li className="archive-row">
      <div className="archive-row-head">
        <span className="archive-dot" style={{ background: archive.color }} aria-hidden="true" />
        <strong>{label}</strong>
        {archive.current && <span className="archive-this">this window</span>}
        {archive.in_use_elsewhere && (
          <span className="archive-this">open in another window{archive.port ? ` (port ${archive.port})` : ""}</span>
        )}
      </div>
      <div className="archive-edit">
        <input
          type="text"
          aria-label={`Name of ${label}`}
          value={name}
          maxLength={40}
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && changed) void attempt(() => updateArchive(archive.id, { name: name.trim() }));
          }}
        />
        <button type="button" disabled={!changed} onClick={() => void attempt(() => updateArchive(archive.id, { name: name.trim() }))}>
          Rename
        </button>
      </div>
      <ArchiveSwatches
        value={archive.color}
        label={`Colour of ${label}`}
        onPick={(color) => void attempt(() => updateArchive(archive.id, { color }))}
      />
      <PathRow label="Data folder" path={archive.data_dir} manager={manager} onShow={() => void attempt(() => revealArchive(archive.id, "data"))} />
      <PathRow
        label="Archive folder"
        path={archive.archive_root}
        manager={manager}
        onShow={() => void attempt(() => revealArchive(archive.id, "archive"))}
      />
      {confirming ? (
        <div className="archive-forget" role="group" aria-label={`Forget ${label}`}>
          <p>
            <strong>Forget {label}?</strong> This only removes it from this list. <strong>Nothing is deleted</strong>: its data folder
            and its archive folder stay where they are, and you can remove them yourself if you wish.
          </p>
          {archive.current && (
            <div className="field">
              <label htmlFor={`forget-instead-${archive.id}`}>Open this archive instead</label>
              <select id={`forget-instead-${archive.id}`} value={instead} onChange={(e) => setInstead(e.target.value)}>
                {others.map((a) => (
                  <option key={a.id} value={a.id} disabled={a.in_use_elsewhere}>
                    {a.name}
                    {a.in_use_elsewhere ? " (open in another window)" : ""}
                  </option>
                ))}
              </select>
            </div>
          )}
          <div className="archive-forget-actions">
            <button type="button" onClick={() => setConfirming(false)}>
              Keep it
            </button>
            <button type="button" className="danger" disabled={archive.current && !instead} onClick={() => void forget()}>
              Forget {label}
            </button>
          </div>
        </div>
      ) : (
        <div className="archive-forget-actions">
          <TipButton disabled={others.length === 0} disabledReason="This is your only archive" onClick={() => setConfirming(true)}>
            Forget…
          </TipButton>
          {others.length === 0 && <span className="first-run-hint">It is your only archive.</span>}
        </div>
      )}
      {problem && (
        <p className="first-run-problem" role="alert">
          <CircleAlert size={14} aria-hidden="true" /> {problem}
        </p>
      )}
    </li>
  );
}

/** Manage archives: rename, colour, see where each one lives, forget. */
export function ManageArchives({ open, onClose }: { open: boolean; onClose: () => void }) {
  const archives = useArchives(open);
  const [forgotten, setForgotten] = useState<ArchiveForgotten | null>(null);
  const list = archives.data?.archives ?? [];
  return (
    <Sheet
      open={open}
      title="Manage archives"
      onClose={onClose}
      footer={
        <button type="button" className="primary" onClick={onClose}>
          Done
        </button>
      }
    >
      <p className="first-run-hint">
        Every archive has its own data folder (settings, index, logs) and its own archive folder. Forgetting one only takes it off this
        list.
      </p>
      {forgotten && (
        <p className="first-run-ok" role="status">
          <CircleCheck size={14} aria-hidden="true" />
          <span>
            Forgot {visible(forgotten.forgotten.name)}. Nothing was deleted. Its data folder is <code>{forgotten.data_dir}</code>
            {forgotten.archive_root ? (
              <>
                {" "}
                and its archive folder is <code>{forgotten.archive_root}</code>
              </>
            ) : null}
            .
          </span>
        </p>
      )}
      {archives.isError && (
        <p className="first-run-problem" role="alert">
          <CircleAlert size={14} aria-hidden="true" /> {errorText(archives.error)}
        </p>
      )}
      <ul className="archive-list" aria-label="Archives">
        {list.map((a) => (
          <ArchiveRow key={`${a.id}:${a.name}`} archive={a} all={list} onForgotten={setForgotten} />
        ))}
      </ul>
    </Sheet>
  );
}
