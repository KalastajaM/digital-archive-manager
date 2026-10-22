/** The system's file manager, for text that names it: Finder on a Mac, Explorer on
 * Windows, and plain words elsewhere (Linux file managers have many names). */

function platform(): string {
  return typeof navigator === "undefined" ? "" : `${navigator.platform} ${navigator.userAgent}`;
}

/** "Finder", "Explorer", or null when the file manager has no name we know. */
export function fileManagerName(): string | null {
  const where = platform();
  if (/mac/i.test(where)) return "Finder";
  if (/\bwin/i.test(where)) return "Explorer"; // not "darwin"
  return null;
}

/** "Show in Finder" / "Show in Explorer" / "Show in file manager". */
export const showInLabel = () => `Show in ${fileManagerName() ?? "file manager"}`;

/** "in Finder" / "in Explorer" / "in your file manager", inside a sentence. */
export const inFileManager = () => `in ${fileManagerName() ?? "your file manager"}`;
