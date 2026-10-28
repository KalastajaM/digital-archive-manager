/** "Move together" in Quick Look's compare mode: the two previews turn pages and scroll
 * as one (zoom is shared by the caller through one ``ZoomControl``). Each pane's preview
 * registers its page and its scrolling frame with the hub; while ``on``, a page turn or a
 * scroll in one is copied to the other. Scroll is copied as a share of the way down, so
 * documents of different lengths stay at the same place in proportion. A document with
 * fewer pages stays on its last page. */
import { createContext, useContext, useEffect, useRef } from "react";

type Pager = { page: number; to: (page: number) => void };

export type MoveHub = {
  on: boolean;
  pages: Map<string, Pager>;
  frames: Map<string, HTMLElement>;
  /** Where the hub itself just scrolled a frame to, so that scroll is not copied back. */
  expected: WeakMap<HTMLElement, { top: number; left: number }>;
};

export const newHub = (): MoveHub => ({ on: false, pages: new Map(), frames: new Map(), expected: new WeakMap() });

/** The hub and which pane this preview is in; null outside compare mode. */
export const MoveLink = createContext<{ hub: MoveHub; pane: string } | null>(null);

const share = (pos: number, size: number, view: number) => (size - view > 0 ? pos / (size - view) : 0);

/** Copy one pane's scroll to the others, as a share of the way down and across. */
export function alignScroll(hub: MoveHub, from: string) {
  const el = hub.frames.get(from);
  if (!el) return;
  const y = share(el.scrollTop, el.scrollHeight, el.clientHeight);
  const x = share(el.scrollLeft, el.scrollWidth, el.clientWidth);
  for (const [pane, other] of hub.frames) {
    if (pane === from) continue;
    const top = Math.round(y * Math.max(0, other.scrollHeight - other.clientHeight));
    const left = Math.round(x * Math.max(0, other.scrollWidth - other.clientWidth));
    hub.expected.set(other, { top, left });
    other.scrollTop = top;
    other.scrollLeft = left;
  }
}

/** Copy one pane's page to the others (when Move together is switched on). */
export function alignPages(hub: MoveHub, from: string) {
  const pager = hub.pages.get(from);
  if (pager) for (const [pane, other] of hub.pages) if (pane !== from) other.to(pager.page);
}

/** A PDF's page in a linked pane: ``go`` turns this pane's page and, while on, the others'.
 * ``to`` is how the hub turns this one (clamped to its last page when known). */
export function usePageLink(page: number, to: (page: number) => void) {
  const link = useContext(MoveLink);
  const toRef = useRef(to);
  toRef.current = to;
  useEffect(() => {
    if (!link) return;
    const { hub, pane } = link;
    const pager: Pager = { page, to: (p) => toRef.current(p) };
    hub.pages.set(pane, pager);
    return () => {
      if (hub.pages.get(pane) === pager) hub.pages.delete(pane);
    };
  }, [link, page]);
  return (p: number) => {
    to(p);
    if (link?.hub.on) for (const [pane, other] of link.hub.pages) if (pane !== link.pane) other.to(p);
  };
}

/** A scrolling frame in a linked pane: registers it, and returns the onScroll handler. */
export function useScrollLink(frame: React.RefObject<HTMLElement | null>) {
  const link = useContext(MoveLink);
  useEffect(() => {
    const el = frame.current;
    if (!link || !el) return;
    const { hub, pane } = link;
    hub.frames.set(pane, el);
    return () => {
      if (hub.frames.get(pane) === el) hub.frames.delete(pane);
    };
  }, [link, frame]);
  return () => {
    const el = frame.current;
    if (!link || !el || !link.hub.on) return;
    const want = link.hub.expected.get(el);
    if (want) {
      link.hub.expected.delete(el);
      if (Math.abs(el.scrollTop - want.top) <= 1 && Math.abs(el.scrollLeft - want.left) <= 1) return;
    }
    alignScroll(link.hub, link.pane);
  };
}
