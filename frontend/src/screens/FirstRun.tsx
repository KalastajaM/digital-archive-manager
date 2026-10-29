import { useQueryClient } from "@tanstack/react-query";
import { ArrowUp, CircleAlert, CircleCheck, Cloud, Folder, FolderOpen, ShieldCheck } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import {
  checkSetupPath,
  errorText,
  previewSetupLayout,
  saveSetup,
  type SetupCheck,
  type SetupResult,
  useSetupCandidates,
  useArchives,
} from "../api/client";
import { ArchiveSwitcher } from "../components/ArchiveSwitcher";
import { FolderPathInput } from "../components/FolderPathInput";
import { initialLayout, LayoutEditor, LayoutPreviewList, layoutBody, type LayoutState, useDebouncedPreview } from "../components/LayoutEditor";
import { plural } from "../format";

// Differs from paths.ts: also splits on "\", strips trailing separators, returns null at the top and for a drive root.
/** The parent folder of a path (works for / and \ paths); null at the top. */
function parentOf(path: string): string | null {
  const trimmed = path.replace(/[\\/]+$/, "");
  const cut = Math.max(trimmed.lastIndexOf("/"), trimmed.lastIndexOf("\\"));
  if (cut <= 0 || /^[A-Za-z]:$/.test(trimmed.slice(0, cut))) return null;
  return trimmed.slice(0, cut);
}

// Differs from paths.ts: no shared joinPath; keeps the separator style of the base path.
const joinPath = (base: string, name: string) => `${base.replace(/[\\/]+$/, "")}${base.includes("\\") ? "\\" : "/"}${name}`;

/** What to do with the chosen folder: start a new archive in it (an empty folder, or one
 * dam will make), use it as it is, or use it as it is and also add a layout to it. */
type Choice = "new" | "asis" | "add";

/** Where the post probably comes from: the first browser language that names Finland
 * (Finnish, or a Finnish locale) or the Netherlands (Dutch without a region, or a Dutch
 * locale; not nl-BE), else the clock's time zone (many use an English browser). */
export function guessCountries(languages: readonly string[], timeZone: string): string[] {
  for (const l of languages) {
    if (/^fi\b/i.test(l) || /-FI$/i.test(l)) return ["fi"];
    if (/^nl$/i.test(l) || /-NL$/i.test(l)) return ["nl"];
  }
  if (timeZone === "Europe/Helsinki") return ["fi"];
  if (timeZone === "Europe/Amsterdam") return ["nl"];
  return [];
}

const browserGuess = () =>
  guessCountries(navigator.languages?.length ? navigator.languages : [navigator.language], Intl.DateTimeFormat().resolvedOptions().timeZone ?? "");

/** What the first screen shows while no archive folder is chosen yet: what dam does, the
 * safety promise, and the choice of the folder. Nothing is created or changed until the
 * user presses the button. */
export default function FirstRun() {
  const client = useQueryClient();
  const archives = useArchives();
  const candidates = useSetupCandidates();
  const [path, setPath] = useState("");
  const [check, setCheck] = useState<SetupCheck | null>(null);
  const [checking, setChecking] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [result, setResult] = useState<SetupResult | null>(null);
  const [countries, setCountries] = useState<string[]>(browserGuess);
  const [picked, setPicked] = useState<Choice | null>(null);
  const [edited, setEdited] = useState<LayoutState | null>(null);
  const latest = useRef(0);

  // check the path a moment after the last keystroke; the newest answer wins
  useEffect(() => {
    const text = path.trim();
    const ticket = ++latest.current;
    if (!text) {
      setCheck(null);
      setChecking(false);
      return;
    }
    setChecking(true);
    const timer = setTimeout(() => {
      checkSetupPath(text)
        .then((answer) => {
          if (ticket === latest.current) setCheck(answer);
        })
        .catch((e: unknown) => {
          if (ticket === latest.current) setCheck({ ok: false, path: null, message: errorText(e), exists: false, can_create: false, subfolders: [], empty: false, item_count: 0 });
        })
        .finally(() => {
          if (ticket === latest.current) setChecking(false);
        });
    }, 250);
    return () => clearTimeout(timer);
  }, [path]);

  const choose = (next: string) => {
    setFailure(null);
    setPicked(null);
    setPath(next);
  };

  const templates = candidates.data?.layouts ?? [];
  const specials = candidates.data?.special_folders ?? [];
  const layout = edited ?? (templates.length > 0 ? initialLayout(templates, specials) : null);
  const settled = !checking && check !== null;
  const creating = settled && check.can_create;
  const usable = settled && (check.ok || check.can_create);
  // an empty folder (or one dam will make) starts a new archive unless told otherwise
  const fresh = settled && (creating || check.empty);
  const choice: Choice = picked ?? (fresh ? "new" : "asis");
  const withLayout = usable && choice !== "asis" && layout !== null;
  const body = withLayout ? layoutBody(layout, true) : null;
  const preview = useDebouncedPreview(
    `${check?.path ?? ""}|${JSON.stringify(body)}`,
    () => previewSetupLayout(check?.path ?? path.trim(), body!),
    withLayout && check !== null,
  );

  const submit = async () => {
    setSaving(true);
    setFailure(null);
    try {
      setResult(await saveSetup(path.trim(), check?.can_create === true, body ?? undefined, countries));
    } catch (e) {
      setFailure(errorText(e));
    } finally {
      setSaving(false);
    }
  };

  if (result) return <Done result={result} onContinue={() => void client.invalidateQueries({ queryKey: ["configured"] })} />;

  const base = check?.path ?? null;
  const up = base ? parentOf(base) : null;
  const found = candidates.data?.candidates ?? [];

  return (
    <div className="first-run">
      <div className="first-run-card">
        {(archives.data?.archives.length ?? 1) > 1 && (
          <div className="first-run-archive">
            <span>Setting up</span>
            <ArchiveSwitcher />
          </div>
        )}
        <h1>Welcome to Digital Archive Manager</h1>
        <p>
          dam keeps a folder of your documents in order. It suggests where each new file belongs, reminds you of bills and
          things to do, and finds anything in seconds. Your files stay where they are, in plain folders.
        </p>
        <p className="first-run-promise">
          <ShieldCheck size={16} aria-hidden="true" />
          <span>
            <strong>It never deletes anything.</strong> It moves a file only after you have seen a preview, and every change
            can be undone.
          </span>
        </p>

        <h2>Where is your archive?</h2>
        <p className="first-run-hint">Pick a folder dam found, or type the path of any folder you can read and write.</p>

        {candidates.isPending ? (
          <p className="first-run-hint">Looking for cloud drives…</p>
        ) : found.length > 0 ? (
          <ul className="first-run-places" aria-label="Folders found on this computer">
            {found.map((c) => (
              <li key={c.path}>
                <button type="button" className="first-run-place" aria-pressed={path.trim() === c.path} onClick={() => choose(c.path)}>
                  <Cloud size={16} aria-hidden="true" />
                  <span className="first-run-place-name">{c.label}</span>
                  <span className="first-run-place-path">{c.path}</span>
                </button>
              </li>
            ))}
          </ul>
        ) : (
          <p className="first-run-hint">No cloud-drive folders were found. Type the path below.</p>
        )}

        <div className="field">
          <label htmlFor="first-run-path">Folder path</label>
          <FolderPathInput
            id="first-run-path"
            value={path}
            spellCheck={false}
            autoComplete="off"
            placeholder="For example /Users/you/Documents/Archive"
            onChange={choose}
            onKeyDown={(e) => {
              if (e.key === "Enter" && usable && !saving) void submit();
            }}
          />
        </div>

        <div className="first-run-feedback" aria-live="polite">
          {checking && <p className="first-run-hint">Checking…</p>}
          {settled && check.ok && (
            <p className="first-run-ok">
              <CircleCheck size={14} aria-hidden="true" /> This folder can be used.
            </p>
          )}
          {settled && !check.ok && (
            <p className="first-run-problem">
              <CircleAlert size={14} aria-hidden="true" /> {check.message}
              {creating && " dam can create it: it is the only folder it will make."}
            </p>
          )}
        </div>

        {settled && check.ok && base && (
          <div className="first-run-subs">
            <p className="first-run-hint">
              To use a folder inside it instead, open it:
              {up && (
                <button type="button" className="first-run-up" onClick={() => choose(up)}>
                  <ArrowUp size={12} aria-hidden="true" /> Up one level
                </button>
              )}
            </p>
            {check.subfolders.length > 0 ? (
              <ul aria-label="Folders inside">
                {check.subfolders.map((name) => (
                  <li key={name}>
                    <button type="button" className="first-run-sub" onClick={() => choose(joinPath(base, name))}>
                      <Folder size={14} aria-hidden="true" /> {name}
                    </button>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="first-run-hint">There are no folders inside it.</p>
            )}
          </div>
        )}

        {usable && (
          <fieldset className="first-run-choice">
            <legend>
              <h2>{fresh ? "A new archive?" : "This folder has content"}</h2>
            </legend>
            {fresh ? (
              <p className="first-run-hint">
                {creating ? "This folder does not exist yet." : "This folder is empty."} dam can start a new archive here: a set of
                folders for your documents, and the four special folders it works with.
              </p>
            ) : (
              <p className="first-run-hint">
                It holds {plural(check.item_count, "item")}. dam will use it as it is and never touches what is in it.
              </p>
            )}
            {fresh ? (
              <>
                <label>
                  <input type="radio" name="first-run-choice" checked={choice === "new"} onChange={() => setPicked("new")} />
                  <span>
                    <strong>Start a new archive here</strong>
                    <span className="layout-template-hint">You see every folder first, and can undo it afterwards.</span>
                  </span>
                </label>
                <label>
                  <input type="radio" name="first-run-choice" checked={choice === "asis"} onChange={() => setPicked("asis")} />
                  <span>
                    <strong>Use this folder as it is</strong>
                    <span className="layout-template-hint">dam makes no folders. You can add them later in Browse.</span>
                  </span>
                </label>
              </>
            ) : (
              <>
                <label>
                  <input type="radio" name="first-run-choice" checked={choice === "asis"} onChange={() => setPicked("asis")} />
                  <span>
                    <strong>Use this folder as it is</strong>
                  </span>
                </label>
                <label>
                  <input type="radio" name="first-run-choice" checked={choice === "add"} onChange={() => setPicked("add")} />
                  <span>
                    <strong>Use it, and also add a folder layout</strong>
                    <span className="layout-template-hint">
                      Only folders that do not exist yet are made. Nothing that is there is touched.
                    </span>
                  </span>
                </label>
              </>
            )}
          </fieldset>
        )}

        {withLayout && (
          <>
            <LayoutEditor
              templates={templates}
              specials={specials}
              state={layout}
              onChange={setEdited}
              disabled={saving}
            />
            {preview.error ? (
              <p className="first-run-problem" role="alert">
                <CircleAlert size={14} aria-hidden="true" /> {preview.error}
              </p>
            ) : preview.data ? (
              <LayoutPreviewList preview={preview.data} />
            ) : (
              <p className="first-run-hint">Checking the folders…</p>
            )}
          </>
        )}

        {failure && (
          <p className="first-run-problem" role="alert">
            <CircleAlert size={14} aria-hidden="true" /> {failure}
          </p>
        )}

        <fieldset className="first-run-country">
          <legend>Your post comes from</legend>
          <label className="check">
            <input type="radio" name="country" checked={countries.includes("fi")} onChange={() => setCountries(["fi"])} />
            Finland
          </label>
          <label className="check">
            <input type="radio" name="country" checked={countries.includes("nl")} onChange={() => setCountries(["nl"])} />
            The Netherlands
          </label>
          <label className="check">
            <input type="radio" name="country" checked={countries.length === 0} onChange={() => setCountries([])} />
            Another country
          </label>
          <p className="first-run-hint">
            It decides which payment reference numbers dam reads from bills, and the example rules it offers. You can
            change it later in Settings, Reading documents.
          </p>
        </fieldset>

        <div className="first-run-actions">
          <button
            type="button"
            className="primary"
            disabled={!usable || saving || (withLayout && !preview.data)}
            onClick={() => void submit()}
          >
            {withLayout
              ? creating
                ? "Create the folder, make the folders and use it"
                : "Make the folders and use this folder"
              : creating
                ? "Create this folder and use it"
                : "Use this folder"}
          </button>
        </div>
        <p className="first-run-hint">
          {withLayout ? (
            <>
              dam saves the folder and the special folder names in <code>config/settings.yaml</code>, then makes the folders you see
              above.
            </>
          ) : (
            <>
              dam only saves this one setting. You can change it later in <code>config/settings.yaml</code>.
            </>
          )}
        </p>
      </div>
    </div>
  );
}

function Done({ result, onContinue }: { result: SetupResult; onContinue: () => void }) {
  return (
    <div className="first-run">
      <div className="first-run-card">
        <h1>All set</h1>
        <p>
          Your archive folder is <code>{result.archive_root}</code>.
        </p>
        {result.layout?.error && (
          <p className="first-run-problem" role="alert">
            <CircleAlert size={14} aria-hidden="true" /> {result.layout.error}
          </p>
        )}
        {result.layout?.batch && !result.layout.error && (
          <p className="first-run-ok" role="status">
            <CircleCheck size={14} aria-hidden="true" />
            <span>
              dam made {plural(result.layout.created, "folder")}.{" "}
              {result.layout.rules_written ? "It also saved a few example filing rules for them. " : ""}
              Changed your mind? Undo it from Activity: only folders that are still empty are removed.
            </span>
          </p>
        )}
        <h2>Folders dam looks for</h2>
        <p className="first-run-hint">
          {result.layout?.batch
            ? "dam uses each of these by name."
            : "dam did not create any of these. It uses each one when it exists in your archive, and works without them."}
        </p>
        <ul className="first-run-folders" aria-label="Folders dam looks for">
          {result.special_folders.map((f) => (
            <li key={f.role}>
              {f.exists ? <FolderOpen size={14} aria-hidden="true" /> : <Folder size={14} aria-hidden="true" />}
              <span>
                <strong>{f.name}</strong> <span className="first-run-state">{f.exists ? "found" : "not there yet"}</span>
                <br />
                {f.purpose}
              </span>
            </li>
          ))}
        </ul>
        {result.restart_needed ? (
          <p className="first-run-problem" role="status">
            <CircleAlert size={14} aria-hidden="true" /> One more step: stop dam (Ctrl+C in the terminal) and run{" "}
            <code>dam serve</code> again.
          </p>
        ) : (
          <div className="first-run-actions">
            <button type="button" className="primary" onClick={onContinue}>
              Open dam
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
