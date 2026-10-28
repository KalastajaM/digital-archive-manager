/** Where an archive's folder lives, in words: "Google Drive", "OneDrive", "Dropbox",
 * "iCloud Drive" when the path names a cloud drive, else the folder's own name. It
 * reads the folder path the archive list already carries; nothing is looked up. */
export function archiveSource(root: string | null | undefined): string | null {
  if (!root) return null;
  if (/google\s?drive|googledrive-/i.test(root)) return "Google Drive";
  if (/onedrive/i.test(root)) return "OneDrive";
  if (/dropbox/i.test(root)) return "Dropbox";
  if (/mobile documents|com~apple~clouddocs|icloud/i.test(root)) return "iCloud Drive";
  const last = root.split(/[\\/]+/).filter(Boolean).at(-1);
  return last ?? null;
}
