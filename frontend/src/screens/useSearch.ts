import { useEffect, useRef, useState } from "react";
import { errorText, MARKS_CHANGED, type SearchHit, searchFiles } from "../api/client";

export const SEARCH_DEBOUNCE_MS = 250;

/** Debounced full-text search; a response for anything but the latest query is dropped.
 * ``tags``: only files with all of them, or with at least one when ``tagMode`` is "any"
 * (words are optional then). */
export function useSearch(query: string, folder = "", reload = 0, tags: string[] = [], tagMode: "all" | "any" = "all") {
  const [results, setResults] = useState<{ key: string; hits: SearchHit[] } | null>(null);
  const [error, setError] = useState<{ key: string; text: string } | null>(null);
  const latest = useRef(0);
  // A mark changed: the hits are fetched again, so their ★ / ! icons follow.
  const [marked, setMarked] = useState(0);
  useEffect(() => {
    const bump = () => setMarked((n) => n + 1);
    window.addEventListener(MARKS_CHANGED, bump);
    return () => window.removeEventListener(MARKS_CHANGED, bump);
  }, []);
  const tagsKey = tags.join("\n");
  const mode = tags.length > 1 ? tagMode : "all";
  const key = `${query}\n${folder}\n${tagsKey}\n${mode}`;
  useEffect(() => {
    if (!query && !tagsKey) {
      latest.current++; // whatever is still on its way is now stale
      return;
    }
    const timer = setTimeout(async () => {
      const seq = ++latest.current;
      try {
        const hits = await searchFiles(query, folder || undefined, tagsKey ? tagsKey.split("\n") : [], mode);
        if (seq === latest.current) setResults({ key, hits });
      } catch (e) {
        if (seq === latest.current) setError({ key, text: errorText(e) });
      }
    }, SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [query, folder, reload, marked, tagsKey, mode]);
  return {
    hits: results?.key === key ? results.hits : null,
    error: error?.key === key && results?.key !== key ? error.text : null,
  };
}
