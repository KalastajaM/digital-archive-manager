/** How many leading steps of a path to fold into one "…" so the rest fits ``avail``.
 *
 * ``widths`` are the natural widths of every step (the root first, the folder you are in
 * last), ``more`` the width of the "…" button and ``gap`` the space between steps. Returns
 * 0 when everything fits. Otherwise it folds the farthest steps first and never folds the
 * last one (it keeps its place and gives way by ellipsis in CSS), so a long path reads
 * "… › Parent › Current". */
export function hiddenCrumbs(widths: number[], more: number, gap: number, avail: number): number {
  const n = widths.length;
  if (n <= 1 || avail <= 0) return 0;
  const sum = (from: number) => widths.slice(from).reduce((a, w) => a + w, 0) + gap * (n - from - 1);
  if (sum(0) <= avail) return 0;
  for (let k = 1; k < n - 1; k++) {
    if (more + gap + sum(k) <= avail) return k;
  }
  return n - 1;
}
