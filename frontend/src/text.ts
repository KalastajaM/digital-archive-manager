// Characters that are invisible or change the reading direction, so a path could read
// differently from what it is (e.g. "invoice‮fdp.exe"): bidi embeddings, overrides,
// isolates and marks (incl. ALM), zero-width characters and joiners, word joiner, BOM,
// C0 and C1 controls and DEL.
const HIDDEN_CHARS =
  /[\u0000-\u001F\u007F-\u009F؜​-‏‪-‮⁠⁦-⁩﻿]/g;

/** ``text`` with every hidden or direction-changing character shown as ⟨U+XXXX⟩. */
export const visible = (text: string) =>
  text.replace(
    HIDDEN_CHARS,
    (c) => `⟨U+${c.codePointAt(0)!.toString(16).toUpperCase().padStart(4, "0")}⟩`,
  );

/** Like ``visible`` for a whole text: line breaks and tabs stay as they are. */
export const visibleText = (text: string) =>
  text.replace(HIDDEN_CHARS, (c) =>
    c === "\n" || c === "\t" ? c : `⟨U+${c.codePointAt(0)!.toString(16).toUpperCase().padStart(4, "0")}⟩`,
  );
