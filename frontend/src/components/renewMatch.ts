/** The Inbox's "Renews …?": which open Renew items a new document likely renews. */
import type { RenewCandidate } from "../api/client";

const fold = (s: string) => s.normalize("NFC").toLocaleLowerCase();

/** The candidates whose current file is in ``folder`` (case and Unicode form do not
 * matter) for the same ``person``: equal, or none on both. One set and the other not is
 * no match, so a shared family folder does not suggest another person's item. */
export function renewMatches(candidates: RenewCandidate[], folder: string, person: string | null): RenewCandidate[] {
  const here = fold(folder.trim());
  if (!here) return [];
  return candidates.filter((c) => c.folder !== null && fold(c.folder) === here && (c.person ?? null) === (person ?? null));
}
