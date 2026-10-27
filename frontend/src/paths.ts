/**
 * Path helpers shared across the UI. All of them treat "/" as the only separator
 * (archive paths are relative and use "/"; for OS paths with "\" see FirstRun).
 */

/**
 * The last segment of a path. A path without "/" is returned unchanged; a trailing "/"
 * gives "" (it is not stripped); "" gives "".
 */
export const baseName = (path: string) => path.slice(path.lastIndexOf("/") + 1);

/**
 * The folder part of a path, without the trailing "/". A path without "/" has no
 * folder and gives "" (the top level); "a/b/" gives "a/b"; "/a" gives "".
 */
export const parentOf = (path: string) => (path.includes("/") ? path.slice(0, path.lastIndexOf("/")) : "");

/**
 * The lowercase extension of a path's last segment, or null when it has no ".".
 * Edge cases: a dotfile such as ".bashrc" gives "bashrc" (the dot is not special-cased),
 * a trailing dot as in "file." gives "", dots in folder names are ignored, and
 * "a.b/file" gives null.
 */
export const extOf = (path: string) => {
  const name = baseName(path);
  return name.includes(".") ? name.slice(name.lastIndexOf(".") + 1).toLowerCase() : null;
};
