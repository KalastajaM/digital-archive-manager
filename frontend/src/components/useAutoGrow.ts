import { type RefObject, useLayoutEffect } from "react";

/** Grow a textarea with its text, so the whole text reads without scrolling inside
 * the field (it never shrinks below its ``rows``). */
export function useAutoGrow(ref: RefObject<HTMLTextAreaElement | null>, value: string) {
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    if (el.scrollHeight > 0) el.style.height = `${el.scrollHeight}px`;
  }, [ref, value]);
}
