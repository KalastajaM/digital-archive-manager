/** Text cut off with an ellipsis shows its full text on hover. One listener for the
 * whole app: on pointer-over, the nearest element whose text overflows its box (and
 * has no tooltip of its own) gets its full text as ``title``; text that fits gets none.
 * The title is set only while it is ours, so a later fit (a wider pane) removes it. */

const OURS = "data-overflow-title";

/** The element under ``target`` whose text is cut off, if any (up to 4 levels up: the
 * ellipsis sits on a cell or label, the pointer often on a span inside it). */
function clipped(target: Element | null): HTMLElement | null {
  let el = target instanceof HTMLElement ? target : null;
  for (let i = 0; el && i < 4; i++, el = el.parentElement) {
    if (el.hasAttribute("title") && !el.hasAttribute(OURS)) return null; // its own tooltip wins
    if (el.scrollWidth > el.clientWidth + 1 && getComputedStyle(el).textOverflow === "ellipsis") return el;
  }
  return null;
}

function onOver(e: PointerEvent) {
  const target = e.target instanceof Element ? e.target : null;
  const el = clipped(target);
  if (el) {
    const text = (el.textContent ?? "").replace(/\s+/g, " ").trim();
    if (text) {
      el.setAttribute("title", text);
      el.setAttribute(OURS, "");
    }
    return;
  }
  // Text that fits again (the pane grew): drop a title we set before.
  const ours = target?.closest(`[${OURS}]`);
  if (ours instanceof HTMLElement && ours.scrollWidth <= ours.clientWidth + 1) {
    ours.removeAttribute("title");
    ours.removeAttribute(OURS);
  }
}

/** Install the listener once; returns its removal (tests). */
export function installOverflowTitles(root: Document = document): () => void {
  root.addEventListener("pointerover", onOver);
  return () => root.removeEventListener("pointerover", onOver);
}
