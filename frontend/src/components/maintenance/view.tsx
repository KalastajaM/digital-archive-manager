/** The Maintenance screen's view of its checks: which cards are folded to their headline
 * (kept in this browser's localStorage, ``dam.maintenance.folded.v1``, per archive) and
 * Reset, which forgets a check's result so its card is as before it ran. Every storage
 * access is in try/catch: private windows and blocked site data throw. */
import { createContext, type ReactNode, useCallback, useContext, useMemo, useState } from "react";
import { archiveKey, type MaintenanceKind } from "../../api/client";

export const FOLDED_KEY = "dam.maintenance.folded.v1";

/** The checks in screen order. */
export const KINDS: MaintenanceKind[] = ["duplicates", "empty_folders", "broken_links", "references", "names", "waiting", "label_clashes"];

function read(): Set<string> {
  try {
    const value: unknown = JSON.parse(localStorage.getItem(archiveKey(FOLDED_KEY)) ?? "[]");
    return new Set(Array.isArray(value) ? value.filter((v): v is string => typeof v === "string") : []);
  } catch {
    return new Set();
  }
}

function write(folded: Set<string>) {
  try {
    if (folded.size === 0) localStorage.removeItem(archiveKey(FOLDED_KEY));
    else localStorage.setItem(archiveKey(FOLDED_KEY), JSON.stringify([...folded]));
  } catch {
    // Not saved: the folds still apply until the page reloads.
  }
}

type View = {
  folded: (kind: MaintenanceKind) => boolean;
  toggle: (kind: MaintenanceKind) => void;
  allFolded: boolean;
  setAll: (folded: boolean) => void;
};

const ViewContext = createContext<View | null>(null);

export function MaintenanceView({ children }: { children: ReactNode }) {
  const [folded, setFolded] = useState(read);
  // from the latest state, so two clicks before a render both count
  const update = useCallback((change: (folded: Set<string>) => Set<string>) => {
    setFolded((before) => {
      const next = change(before);
      write(next);
      return next;
    });
  }, []);
  const view = useMemo<View>(
    () => ({
      folded: (kind) => folded.has(kind),
      toggle: (kind) =>
        update((before) => {
          const next = new Set(before);
          if (!next.delete(kind)) next.add(kind);
          return next;
        }),
      allFolded: KINDS.every((k) => folded.has(k)),
      setAll: (on) => update(() => (on ? new Set(KINDS) : new Set())),
    }),
    [folded, update],
  );
  return <ViewContext.Provider value={view}>{children}</ViewContext.Provider>;
}

/** The card's fold, for ``Card``'s ``fold`` (none outside the screen, e.g. in a test). */
export function useFold(kind: MaintenanceKind) {
  const view = useContext(ViewContext);
  return view ? { folded: view.folded(kind), onToggle: () => view.toggle(kind) } : undefined;
}

export const useMaintenanceView = () => useContext(ViewContext);
