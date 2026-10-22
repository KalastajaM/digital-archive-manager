/** Shorten a text to fit a width like Finder: a folder path loses its middle folders
 * ("70. Work/…/Brightwave"), a file name its end but not its extension
 * ("20051025_Asunnonvai….pdf"). Pure: ``fits`` says whether a candidate is narrow
 * enough (the caller measures it), so the functions work for any font and width. */

const ELLIPSIS = "…";

/** ``path`` or the longest shortening of it that fits: the first folder and as many of
 * the last ones as fit, the folders between replaced by "…". Without room for the first
 * folder whole, the last folder stays whole behind the start of the rest ("30. Ho…/
 * Electricity", also for a two-folder path); with room for fewer than 3 characters of
 * that start it is "…/last", which the caller's CSS ellipsis may still clip. */
export function truncatePath(path: string, fits: (text: string) => boolean): string {
  if (fits(path)) return path;
  const parts = path.split("/");
  const n = parts.length;
  if (n < 2) return path;
  const last = (k: number) => parts.slice(n - k).join("/");
  // keep the first folder and the last k, from the most to the fewest
  for (let k = n - 2; k >= 1; k--) {
    const candidate = `${parts[0]}/${ELLIPSIS}/${last(k)}`;
    if (fits(candidate)) return candidate;
  }
  // the last folder whole, the start of the rest as long as fits ("30. Ho…/Electricity")
  const head = Array.from(parts.slice(0, n - 1).join("/"));
  const cut = (k: number) => `${head.slice(0, k).join("")}${ELLIPSIS}/${last(1)}`;
  let lo = 0;
  let hi = head.length - 1;
  while (lo < hi) {
    const mid = Math.ceil((lo + hi) / 2);
    if (fits(cut(mid))) lo = mid;
    else hi = mid - 1;
  }
  if (lo >= MIN_KEPT) return cut(lo);
  return `${ELLIPSIS}/${last(1)}`;
}

/** Fewer characters of a name than this before the extension say nothing ("….pdf"):
 * the name is then left whole for the caller's CSS ellipsis, which keeps its start. */
const MIN_KEPT = 3;

/** ``name`` or its longest shortening that fits, cut in front of the extension. */
export function truncateName(name: string, fits: (text: string) => boolean): string {
  if (fits(name)) return name;
  const ext = /.(\.[^./\s]{1,8})$/.exec(name)?.[1] ?? "";
  const base = Array.from(ext ? name.slice(0, name.length - ext.length) : name);
  const at = (k: number) => `${base.slice(0, k).join("")}${ELLIPSIS}${ext}`;
  // the longest start that fits (fitting is monotonic in the length)
  let lo = 0;
  let hi = base.length - 1;
  while (lo < hi) {
    const mid = Math.ceil((lo + hi) / 2);
    if (fits(at(mid))) lo = mid;
    else hi = mid - 1;
  }
  return lo < MIN_KEPT && base.length > MIN_KEPT ? name : at(lo);
}
