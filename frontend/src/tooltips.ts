/** Tooltips for ``data-tip``. One tip element lives in the top layer (the Popover API, so it
 * also sits above a modal dialog), is placed with fixed coordinates, and is kept inside the
 * window: below the control, above it when there is no room below (or
 * ``data-tip-side="above"``), shifted sideways at the edges. One listener set for the whole
 * app, like ``overflowTitles``; the CSS ``::after`` boxes are hidden. */

const SHOW_AFTER_MS = 450;
const GAP = 6;
const MARGIN = 4;
/** Controls wider than this anchor the tip at their left edge instead of their middle. */
const WIDE = 200;

type Box = { left: number; top: number; right: number; bottom: number; width: number };

/** Where the tip goes: ``left`` and ``top`` in window coordinates. Exported for tests. */
export function placeTip(
  anchor: Box,
  tip: { width: number; height: number },
  view: { width: number; height: number },
  above: boolean,
): { left: number; top: number } {
  let left = anchor.width > WIDE ? anchor.left : anchor.left + anchor.width / 2 - tip.width / 2;
  left = Math.max(MARGIN, Math.min(left, view.width - tip.width - MARGIN));
  const below = anchor.bottom + GAP;
  const over = anchor.top - GAP - tip.height;
  const fitsBelow = below + tip.height <= view.height - MARGIN;
  const fitsAbove = over >= MARGIN;
  let top = above ? (fitsAbove ? over : below) : fitsBelow ? below : fitsAbove ? over : below;
  top = Math.max(MARGIN, Math.min(top, view.height - tip.height - MARGIN));
  return { left, top };
}

/** Install the listeners once; returns their removal (tests). */
export function installTooltips(root: Document = document): () => void {
  let tip: HTMLDivElement | null = null;
  let current: HTMLElement | null = null;
  let timer: number | undefined;

  const element = (): HTMLDivElement => {
    if (!tip) {
      tip = root.createElement("div");
      tip.className = "dam-tip";
      tip.setAttribute("popover", "manual");
      tip.setAttribute("aria-hidden", "true");
      root.body.appendChild(tip);
    }
    return tip;
  };

  const hide = () => {
    window.clearTimeout(timer);
    timer = undefined;
    current = null;
    if (!tip) return;
    tip.removeAttribute("data-open");
    try {
      tip.hidePopover?.();
    } catch {
      /* not open */
    }
  };

  const show = (target: HTMLElement) => {
    const text = target.getAttribute("data-tip");
    if (!text || !target.isConnected) return;
    const box = element();
    box.textContent = text;
    box.setAttribute("data-open", "");
    try {
      if (!box.matches(":popover-open")) box.showPopover?.();
    } catch {
      /* no Popover API: the fixed, high z-index fallback in the stylesheet applies */
    }
    const r = target.getBoundingClientRect();
    const size = box.getBoundingClientRect();
    const { left, top } = placeTip(
      r,
      { width: size.width, height: size.height },
      { width: root.documentElement.clientWidth, height: root.documentElement.clientHeight },
      target.getAttribute("data-tip-side") === "above",
    );
    box.style.left = `${left}px`;
    box.style.top = `${top}px`;
  };

  const schedule = (target: HTMLElement, delay: number) => {
    hide();
    current = target;
    if (delay <= 0) show(target);
    else timer = window.setTimeout(() => current === target && show(target), delay);
  };

  const tipOf = (t: EventTarget | null): HTMLElement | null => {
    const el = t instanceof Element ? t.closest<HTMLElement>("[data-tip]") : null;
    return el && !el.matches(":disabled") ? el : null;
  };

  const onOver = (e: Event) => {
    const el = tipOf(e.target);
    if (el === current) return;
    if (el) schedule(el, SHOW_AFTER_MS);
    else hide();
  };
  const onFocus = (e: Event) => {
    const el = tipOf(e.target);
    if (!el) return;
    let visible = true;
    try {
      visible = el.matches(":focus-visible");
    } catch {
      /* old engine: show */
    }
    if (visible) schedule(el, SHOW_AFTER_MS);
  };
  const onBlur = () => hide();
  const onKey = (e: Event) => {
    if ((e as KeyboardEvent).key === "Escape") hide();
  };

  // A drop target that refuses a drag says why at once (hover does not apply during a drag).
  const observer = new MutationObserver((records) => {
    for (const r of records) {
      const el = r.target as HTMLElement;
      if (el.getAttribute("data-drop") === "refused" && el.hasAttribute("data-tip") && !el.matches(".pane-body, .entries li")) {
        schedule(el, 0);
      } else if (el === current && el.getAttribute("data-drop") !== "refused" && !timer && !el.matches(":hover")) {
        hide();
      }
    }
  });
  observer.observe(root.body ?? root.documentElement, { subtree: true, attributes: true, attributeFilter: ["data-drop"] });

  root.addEventListener("pointerover", onOver);
  root.addEventListener("focusin", onFocus);
  root.addEventListener("focusout", onBlur);
  root.addEventListener("pointerdown", onBlur, true);
  root.addEventListener("click", onBlur, true);
  root.addEventListener("keydown", onKey, true);
  root.addEventListener("scroll", onBlur, true);
  root.addEventListener("pointerleave", onBlur);
  return () => {
    hide();
    observer.disconnect();
    root.removeEventListener("pointerover", onOver);
    root.removeEventListener("focusin", onFocus);
    root.removeEventListener("focusout", onBlur);
    root.removeEventListener("pointerdown", onBlur, true);
    root.removeEventListener("click", onBlur, true);
    root.removeEventListener("keydown", onKey, true);
    root.removeEventListener("scroll", onBlur, true);
    root.removeEventListener("pointerleave", onBlur);
    tip?.remove();
  };
}
