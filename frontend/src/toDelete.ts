/** Files under ``##. To Delete`` are read-only until they are restored: every action
 * on them is off, with this reason as its tooltip. The server refuses the same changes
 * (``require_editable``), and keeps their tags, collections, notes and tray items so a
 * restored file comes back with them. */
export const TO_DELETE_REASON = "Marked for deletion: restore it first";

const DEFAULT_NAME = "##. to delete";
let quarantine = DEFAULT_NAME;

/** The name the server says the To Delete folder has now (Settings can rename it); until it
 * says, and for the default, it is ``##. To Delete``. Called with every status answer. */
export function setQuarantineName(name: string | null | undefined): void {
  quarantine = name ? name.normalize("NFC").toLowerCase() : DEFAULT_NAME;
}

/** ``path`` is ``##. To Delete`` itself or inside it (by the configured name, which is the
 * default one unless Settings renamed the folder). */
export const inToDelete = (path: string | null | undefined): boolean =>
  !!path && path.split("/")[0].normalize("NFC").toLowerCase() === quarantine;

/** The reason a change is off for the file at ``path`` (null: it is allowed). */
export const toDeleteReason = (path: string | null | undefined): string | null =>
  inToDelete(path) ? TO_DELETE_REASON : null;

/** The first reason among these paths (null: none is in To Delete). */
export const toDeleteReasonFor = (paths: readonly (string | null | undefined)[]): string | null =>
  paths.some(inToDelete) ? TO_DELETE_REASON : null;
