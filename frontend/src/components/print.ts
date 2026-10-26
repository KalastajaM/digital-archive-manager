/** Printing a previewed document: its page images go into a sheet that only print shows
 * (styles.css hides the rest of the app for print), then the browser's print dialog
 * opens. The sheet goes away once printing is done. */

/** The most PDF pages one print loads (a longer PDF prints its first pages). */
export const MAX_PRINT_PAGES = 300;

const SHEET_CLASS = "print-sheet";

/** Resolves true once the image has loaded, false when it fails (past a PDF's last page). */
const loaded = (img: HTMLImageElement) =>
  new Promise<boolean>((resolve) => {
    img.onload = () => resolve(true);
    img.onerror = () => resolve(false);
  });

/** Loads the images one after the other, stopping at the first that fails, and prints
 * those that loaded. Returns how many that was (0: nothing printed). */
export async function printImages(srcs: Iterable<string>, alt: string): Promise<number> {
  document.querySelector(`body > .${SHEET_CLASS}`)?.remove();
  const sheet = document.createElement("div");
  sheet.className = SHEET_CLASS;
  sheet.setAttribute("aria-hidden", "true");
  document.body.append(sheet);
  let n = 0;
  for (const src of srcs) {
    const img = document.createElement("img");
    img.alt = `${alt}, page ${n + 1}`;
    const done = loaded(img);
    img.src = src;
    sheet.append(img);
    if (!(await done)) {
      img.remove();
      break;
    }
    n++;
  }
  if (n === 0) {
    sheet.remove();
    return 0;
  }
  // print() blocks in most browsers; afterprint covers those where it does not.
  window.addEventListener("afterprint", () => sheet.remove(), { once: true });
  window.print();
  return n;
}

/** Page ``n`` URLs for n = 1 … MAX_PRINT_PAGES (the first that fails ends the print). */
export function* pageSrcs(url: (page: number) => string) {
  for (let page = 1; page <= MAX_PRINT_PAGES; page++) yield url(page);
}
