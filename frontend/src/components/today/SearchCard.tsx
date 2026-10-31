/** The Browse address for a search typed outside Browse (the search palette). */
import { readQuery, serializeQuery } from "../../searchFilters";

/** The Browse address for what was typed: the whole query in ?q= (a trailing filter
 * counts as finished). */
export function browseSearchUrl(text: string): string {
  const { words, filters } = readQuery(text);
  const p = new URLSearchParams();
  const whole = serializeQuery(words, filters);
  if (whole) p.set("q", whole);
  return `/browse?${p}`;
}
