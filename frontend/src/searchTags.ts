/** Tag filters typed into a search box: ``tag:medical`` or ``tag:"two words"``.
 *
 * A token is complete once a space (or the closing quote) follows it; it is then taken
 * out of the words and becomes a chip. A token still being typed (``partial``) is also
 * kept out of the words, so half a name never searches, and gets suggestions. */

export type TagQuery = {
  /** The text without the complete and the partial tag tokens. */
  rest: string;
  /** The text without the complete tag tokens only (a partial one stays), for the box. */
  kept: string;
  /** The complete tag tokens, in order. */
  tags: string[];
  /** The tag name being typed (after ``tag:``), or null when there is none. */
  partial: string | null;
};

const isSpace = (c: string | undefined) => c !== undefined && /\s/.test(c);

export function splitTagQuery(text: string): TagQuery {
  let rest = "";
  let kept = "";
  const tags: string[] = [];
  let partial: string | null = null;
  let i = 0;
  while (i < text.length) {
    const wordStart = i === 0 || isSpace(text[i - 1]);
    if (!wordStart || text.slice(i, i + 4).toLowerCase() !== "tag:") {
      rest += text[i];
      kept += text[i];
      i++;
      continue;
    }
    let j = i + 4;
    let value: string;
    let complete: boolean;
    if (text[j] === '"') {
      const close = text.indexOf('"', j + 1);
      if (close < 0) {
        partial = text.slice(j + 1);
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
      partial = value;
      kept += text.slice(i);
      break;
    }
    const name = value.trim();
    if (name) tags.push(name);
    if (isSpace(text[j])) j++; // the space that ended the token goes with it
    i = j;
  }
  return { rest, kept, tags, partial };
}

/** A tag name as it is typed after ``tag:`` (quoted when it has spaces). */
export const tagToken = (name: string) => (/\s/.test(name) ? `tag:"${name}"` : `tag:${name}`);
