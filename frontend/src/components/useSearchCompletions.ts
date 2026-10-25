/** What Browse's search box offers while a filter is typed: filter names for a few
 * letters (``col`` -> ``collection:``), and values for the filter being typed (tags,
 * collections, senders, people, trays, folders, file types, ``is:`` words). */
import { useCollections, useFolders, usePeople, useSenders, useTagSuggestions, useTrays } from "../api/client";
import { FILTER_NAMES, type FilterName, IS_VALUES, type SearchFilter, type SearchText, sameFilter, TYPE_VALUES } from "../searchFilters";

export type Completion =
  | { kind: "name"; key: string; label: string; hint?: string; insert: string }
  | { kind: "value"; key: string; label: string; hint?: string; filter: SearchFilter };

const MAX = 6;
const fold = (s: string) => s.normalize("NFD").replace(/\p{M}/gu, "").toLowerCase();

/** The plain word being typed at the end of ``rest`` ("" when a space ended it). */
export const lastWord = (rest: string) => (/\s$/.test(rest) ? "" : (/\S+$/.exec(rest)?.[0] ?? ""));

export function useSearchCompletions(typed: SearchText, active: SearchFilter[], open: boolean): Completion[] {
  const partial = typed.partial;
  const word = partial ? "" : lastWord(typed.rest);
  const negatedWord = word.startsWith("-");
  const bare = negatedWord ? word.slice(1) : word;
  const on = (name: FilterName) => open && partial?.name === name;
  const tagPrefix = partial ? (partial.name === "tag" ? partial.value : "") : bare;
  const wantTags = open && ((partial?.name === "tag") || (!partial && bare.length >= 2));
  const tags = useTagSuggestions(tagPrefix, 8, wantTags);
  const collections = useCollections("all", on("collection"));
  const senders = useSenders(on("from"));
  const people = usePeople(on("for"));
  const trays = useTrays(on("tray"));
  const folders = useFolders(on("in"));
  if (!open) return [];

  const taken = (f: SearchFilter) => active.some((a) => sameFilter(a, f));
  const value = (name: FilterName, v: string, negated: boolean, label = v, hint?: string): Completion => ({
    kind: "value",
    key: `${name}:${v}`,
    label,
    hint,
    filter: { name, value: v, negated },
  });

  if (partial) {
    const want = fold(partial.value);
    const has = (s: string) => fold(s).includes(want);
    const neg = partial.negated;
    let out: Completion[] = [];
    switch (partial.name) {
      case "tag":
        out = (tags.data ?? []).map((t) => value("tag", t.name, neg, t.name, String(t.files)));
        break;
      case "collection":
        out = (collections.data ?? []).filter((c) => !c.kind && has(c.name)).map((c) => value("collection", c.name, neg));
        break;
      case "from":
        out = (senders.data ?? []).filter((s) => has(s.sender)).map((s) => value("from", s.sender, neg, s.sender, String(s.count)));
        break;
      case "for":
        out = (people.data?.people ?? []).filter((p) => has(p.name)).map((p) => value("for", p.name, neg));
        break;
      case "tray":
        out = (trays.data?.trays ?? []).filter((t) => has(t.id) || has(t.name)).map((t) => value("tray", t.id, neg, t.id, t.name));
        break;
      case "in":
        out = (folders.data ?? []).filter(has).sort((a, b) => a.length - b.length || a.localeCompare(b)).map((p) => value("in", p, neg));
        break;
      case "type":
        out = [...TYPE_VALUES].filter((t) => t.startsWith(want)).map((t) => value("type", t, neg));
        break;
      case "is":
        out = [...IS_VALUES].filter((t) => t.startsWith(want)).map((t) => value("is", t, neg));
        break;
      default:
        break; // name, date, before, after: typed in full
    }
    return out.filter((c) => c.kind === "value" && !taken(c.filter)).slice(0, MAX);
  }

  const out: Completion[] = [];
  if (bare.length >= 2) {
    for (const n of FILTER_NAMES) {
      if (n.startsWith(bare.toLowerCase())) out.push({ kind: "name", key: `name:${n}`, label: `${negatedWord ? "-" : ""}${n}:`, insert: `${negatedWord ? "-" : ""}${n}:` });
    }
  }
  if (bare.length >= 2) {
    for (const t of tags.data ?? []) {
      const f = { name: "tag" as const, value: t.name, negated: negatedWord };
      if (!taken(f)) out.push({ kind: "value", key: `tag:${t.name}`, label: t.name, hint: String(t.files), filter: f });
    }
  }
  return out.slice(0, MAX + 2);
}
