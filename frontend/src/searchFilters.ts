/** The filters of the search box: ``tag:medical``, ``in:"50. Medical"``, ``-tag:paid``.
 *
 * The backend (``dam.query``) is the one that understands them; this reads the same text
 * just enough to turn each finished filter into a chip, keep the plain words in the box
 * and offer completions. A token is complete once a space (or the closing quote) follows
 * it. A token still being typed (``partial``) is kept out of the words, so half a value
 * never searches. An unknown name before the colon (``http:``) is a plain word. */

export const FILTER_NAMES = ["name", "in", "tag", "collection", "from", "for", "id", "iban", "domain", "type", "date", "before", "after", "tray", "is"] as const;
export type FilterName = (typeof FILTER_NAMES)[number];

/** ``anyOf``: typed unquoted with commas (``type:pdf,docx``), so it stays a list of values
 * any of which may match; a value with a comma but no ``anyOf`` is quoted as one value. */
export type SearchFilter = { name: FilterName; value: string; negated: boolean; anyOf?: boolean };
export type PartialFilter = SearchFilter & { quoted: boolean };

export type SearchText = {
  /** The text without the complete and the partial filter tokens. */
  rest: string;
  /** The text without the complete filter tokens only (a partial one stays), for the box. */
  kept: string;
  /** The complete filters, in order. */
  filters: SearchFilter[];
  /** The filter being typed (``name:`` and what follows), or null. */
  partial: PartialFilter | null;
};

export const IS_VALUES = ["starred", "important", "locked", "todo", "note", "summary", "disconnected"] as const;
export const TYPE_VALUES = ["pdf", "image", "doc", "sheet", "slides", "text", "mail", "archive", "audio", "video"] as const;

/** Every filter with an example and a line, for the help popup (and the guide). */
export const FILTER_HELP: { name: FilterName; example: string; text: string }[] = [
  { name: "name", example: "name:*kela*", text: "Words in the file name only. * stands for any text, ? for one character." },
  { name: "in", example: 'in:"50. Medical"', text: "Files in a folder and the folders below it." },
  { name: "tag", example: "tag:insurance", text: "Files with that tag. tag:* any tag; -tag:* no tag at all." },
  { name: "collection", example: 'collection:"House sale"', text: "Files in a collection, and in the collections inside it. collection:* any of yours; -collection:* none." },
  { name: "from", example: "from:Kela", text: "Files whose sender (From) contains this. from:* any sender; -from:* none set yet." },
  { name: "for", example: "for:Tiina", text: "Files assigned to this person (For). for:* anyone; -for:* no one set yet." },
  { name: "id", example: "id:0112038-9", text: "Files that carry this business ID, IBAN or web or mail domain; id:* finds every file with a business ID." },
  { name: "iban", example: "iban:*", text: "Files that carry this IBAN. iban:* any IBAN; -iban:* none." },
  { name: "domain", example: "domain:kela.fi", text: "Files that carry this web or mail domain. domain:* any domain; -domain:* none." },
  { name: "type", example: "type:pdf", text: "Kind of file: an extension (pdf, docx) or a group (image, doc, sheet, text)." },
  { name: "date", example: "date:2026-10", text: "Document date: a year, a month or a day (YYYY, YYYY-MM, YYYY-MM-DD)." },
  { name: "after", example: "after:2025", text: "Dated on or after the first day of that year, month or day." },
  { name: "before", example: "before:2026-06", text: "Dated before the first day of that year, month or day." },
  { name: "tray", example: "tray:to-pay", text: "Files with an open item in that tray (its id or name). tray:* in any tray." },
  { name: "is", example: "is:locked", text: "starred, important, locked (a lock you set; Important files are found with is:important), todo (open checklist items), note, summary or disconnected (files in an archive folder that is not connected now)." },
];

const isSpace = (c: string | undefined) => c !== undefined && /\s/.test(c);

/** At ``i``: the filter head (``-tag:``) there, or null. */
function head(text: string, i: number): { negated: boolean; name: FilterName; end: number } | null {
  let j = i;
  const negated = text[j] === "-";
  if (negated) j++;
  let k = j;
  while (k < text.length && /[a-zA-Z]/.test(text[k])) k++;
  const name = text.slice(j, k).toLowerCase();
  if (text[k] === ":" && (FILTER_NAMES as readonly string[]).includes(name)) return { negated, name: name as FilterName, end: k + 1 };
  return null;
}

export function splitSearch(text: string): SearchText {
  let rest = "";
  let kept = "";
  const filters: SearchFilter[] = [];
  let partial: PartialFilter | null = null;
  let i = 0;
  while (i < text.length) {
    const h = i === 0 || isSpace(text[i - 1]) ? head(text, i) : null;
    if (!h) {
      rest += text[i];
      kept += text[i];
      i++;
      continue;
    }
    let j = h.end;
    let value: string;
    let complete: boolean;
    let quoted = false;
    if (text[j] === '"') {
      quoted = true;
      const close = text.indexOf('"', j + 1);
      if (close < 0) {
        partial = { name: h.name, negated: h.negated, value: text.slice(j + 1), quoted };
        kept += text.slice(i);
        break;
      }
      value = text.slice(j + 1, close);
      j = close + 1;
      complete = true;
    } else {
      let end = j;
      while (end < text.length && !isSpace(text[end])) end++;
      value = text.slice(j, end);
      j = end;
      complete = isSpace(text[end]);
    }
    if (!complete) {
      partial = { name: h.name, negated: h.negated, value, quoted };
      kept += text.slice(i);
      break;
    }
    const trimmed = value.trim();
    if (trimmed) filters.push({ name: h.name, negated: h.negated, value: trimmed, ...(!quoted && trimmed.includes(",") ? { anyOf: true } : {}) });
    if (isSpace(text[j])) j++; // the space that ended the token goes with it
    i = j;
  }
  return { rest, kept, filters, partial };
}

/** The value of a filter being typed, as a list: the values before the last comma, and
 * the one still being typed. A quoted value is one value, whatever it holds. */
export function typedList(partial: PartialFilter): { chosen: string[]; last: string } {
  if (partial.quoted) return { chosen: [], last: partial.value };
  const parts = partial.value.split(",");
  const last = parts.pop() ?? "";
  return { chosen: parts.map((p) => p.trim()).filter(Boolean), last };
}

/** A filter being typed, taken as it stands (null with no value yet). */
export function typedFilter(partial: PartialFilter): SearchFilter | null {
  const { chosen, last } = typedList(partial);
  const values = last.trim() ? [...chosen, last.trim()] : chosen;
  if (values.length === 0) return null;
  return { name: partial.name, negated: partial.negated, value: values.join(","), ...(values.length > 1 ? { anyOf: true } : {}) };
}

/** A filter as it is typed (quoted when the value has spaces, or a comma that is not a list). */
export function filterToken(f: SearchFilter): string {
  const value = f.value.replace(/"/g, "");
  const quote = /\s/.test(value) || value === "" || (value.includes(",") && !f.anyOf);
  return `${f.negated ? "-" : ""}${f.name}:${quote ? `"${value}"` : value}`;
}

export const sameFilter = (a: SearchFilter, b: SearchFilter) =>
  a.name === b.name && a.negated === b.negated && a.value.toLowerCase() === b.value.toLowerCase();

/** The filters with ``add`` put after them, unless one like it is there already. */
export const withFilter = (filters: SearchFilter[], add: SearchFilter) => (filters.some((f) => sameFilter(f, add)) ? filters : [...filters, add]);

/** Words and filters as one text: the form the address and the API take. */
export function serializeQuery(words: string, filters: SearchFilter[]): string {
  return [words.trim(), ...filters.map(filterToken)].filter(Boolean).join(" ");
}

/** A whole query (the address's ``q``): its words and filters. A token at the end counts
 * as finished. */
export function readQuery(q: string | null | undefined): { words: string; filters: SearchFilter[] } {
  const t = splitSearch(`${q ?? ""} `);
  return { words: t.rest.replace(/\s+/g, " ").trim(), filters: t.filters };
}

/** Does this filter set have two or more tags that must all / any match (All/Any shows)? */
export const positiveTags = (filters: SearchFilter[]) =>
  filters.filter((f) => f.name === "tag" && !f.negated && f.value !== "*"); // tag:* is "any tag", not a tag

/** The query that shows the files with this tag (the link from the tag lists). */
export const tagFilter = (name: string) => filterToken({ name: "tag", value: name, negated: false });

const isWordChar = (c: string | undefined) => c !== undefined && /[\p{L}\p{N}]/u.test(c);

/** ``text`` from ``start`` to ``end``, widened where an end cuts a word: search matches
 * whole words, so a selection dragged a little short would find nothing. */
export function wholeWords(text: string, start: number, end: number): string {
  let from = start;
  let to = end;
  if (isWordChar(text[from])) while (isWordChar(text[from - 1])) from--;
  if (isWordChar(text[to - 1])) while (isWordChar(text[to])) to++;
  return text.slice(from, to);
}

/** How much of a selection a phrase search takes: enough to tell documents apart, and an
 * address stays short. */
const PHRASE_MAX_CHARS = 200;

/** Selected text as one phrase for the search box ("" when nothing is left of it). Colons
 * go, or ``Name: x`` inside the quotes would read as a filter (search ignores punctuation
 * anyway), and so do the marks shown for hidden characters. A long selection is cut at a word. */
export function phraseQuery(selected: string): string {
  let words = selected
    .replace(/⟨U\+[0-9A-F]+⟩/g, "")
    .replace(/["：:]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  if (words.length > PHRASE_MAX_CHARS) {
    const cut = words.lastIndexOf(" ", PHRASE_MAX_CHARS);
    words = words.slice(0, cut > 0 ? cut : PHRASE_MAX_CHARS);
  }
  return /[\p{L}\p{N}]/u.test(words) ? `"${words}"` : "";
}
