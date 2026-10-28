/** The shortcut for search and jump: Cmd+K on a Mac, Ctrl+K elsewhere. */

/** True on a Mac (and iPad / iPhone). */
export const onMac = () =>
  typeof navigator !== "undefined" && /mac|iphone|ipad/i.test(`${navigator.platform} ${navigator.userAgent}`);

/** The shortcut as written on the search field: "⌘K" or "Ctrl K". */
export const searchKeyLabel = () => (onMac() ? "⌘K" : "Ctrl K");

/** Cmd+K on a Mac, Ctrl+K elsewhere (never both: Ctrl+K edits text on a Mac). */
export const isSearchKey = (e: Pick<KeyboardEvent, "key" | "metaKey" | "ctrlKey" | "altKey" | "shiftKey">) =>
  e.key.toLowerCase() === "k" && !e.altKey && !e.shiftKey && (onMac() ? e.metaKey && !e.ctrlKey : e.ctrlKey && !e.metaKey);
