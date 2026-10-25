import { useEffect, useRef, useState } from "react";
import { errorText, MARKS_CHANGED, type SearchHit, searchFiles } from "../api/client";

export const SEARCH_DEBOUNCE_MS = 250;

/** Debounced full-text search; a response for anything but the latest query is dropped.
 * ``tags``: only files with all of them (words are optional then). */
export function useSearch(query: string, folder = "", reload = 0, tags: string[] = []) {
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
  const key = `${query}\n${folder}\n${tagsKey}`;
  useEffect(() => {
    if (!query && !tagsKey) {
      latest.current++; // whatever is still on its way is now stale
      return;
    }
    const timer = setTimeout(async () => {
      const seq = ++latest.current;
      try {
        const hits = await searchFiles(query, folder || undefined, tagsKey ? tagsKey.split("\n") : []);
        if (seq === latest.current) setResults({ key, hits });
      } catch (e) {
        if (seq === latest.current) setError({ key, text: errorText(e) });
      }
    }, SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [query, folder, reload, marked, tagsKey]);
  return {
    hits: results?.key === key ? results.hits : null,
    error: error?.key === key && results?.key !== key ? error.text : null,
  };
}
