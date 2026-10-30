import { useEffect, useRef, useState } from "react";
import { errorText, isAbort, MARKS_CHANGED, SEARCH_STALE, type SearchHit, searchFiles } from "../api/client";

export const SEARCH_DEBOUNCE_MS = 250;

/** Debounced full-text search; a response for anything but the latest query is dropped.
 * ``query`` is the words and the filters as typed (``kela tag:medical``); ``tagMode`` "any":
 * a file needs at least one of the ``tag:`` filters, else every one. With filters alone the
 * words are optional. */
export function useSearch(query: string, folder = "", reload = 0, tagMode: "all" | "any" = "all") {
  const [results, setResults] = useState<{ key: string; hits: SearchHit[] } | null>(null);
  const [error, setError] = useState<{ key: string; text: string } | null>(null);
  const latest = useRef(0);
  const inFlight = useRef<AbortController | null>(null);
  // A mark changed: the hits are fetched again, so their ★ / ! icons follow; so are
  // results that may be stale (SEARCH_STALE).
  const [marked, setMarked] = useState(0);
  useEffect(() => {
    const bump = () => setMarked((n) => n + 1);
    window.addEventListener(MARKS_CHANGED, bump);
    window.addEventListener(SEARCH_STALE, bump);
    return () => {
      window.removeEventListener(MARKS_CHANGED, bump);
      window.removeEventListener(SEARCH_STALE, bump);
    };
  }, []);
  useEffect(() => () => inFlight.current?.abort(), []); // leaving the screen
  const mode = tagMode;
  const key = `${query}\n${folder}\n${mode}`;
  useEffect(() => {
    if (!query) {
      latest.current++; // whatever is still on its way is now stale
      inFlight.current?.abort();
      return;
    }
    const timer = setTimeout(async () => {
      const seq = ++latest.current;
      inFlight.current?.abort(); // the server need not finish a search nobody waits for
      const controller = new AbortController();
      inFlight.current = controller;
      try {
        const hits = await searchFiles(query, folder || undefined, mode, controller.signal);
        if (seq === latest.current) setResults({ key, hits });
      } catch (e) {
        if (seq === latest.current && !isAbort(e)) setError({ key, text: errorText(e) });
      }
    }, SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [query, folder, reload, marked, mode, key]);
  return {
    hits: results?.key === key ? results.hits : null,
    error: error?.key === key && results?.key !== key ? error.text : null,
  };
}
