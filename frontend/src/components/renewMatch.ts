/** The Inbox's "Renews …?": which open Renew items a new document likely renews. */
import type { InboxEntry, RenewCandidate } from "../api/client";

const fold = (s: string) => s.normalize("NFC").toLocaleLowerCase();

/** The candidates whose current file is in ``folder`` (case and Unicode form do not
 * matter) for the same ``person``: equal, or none on both. One set and the other not is
 * no match, so a shared family folder does not suggest another person's item. */
export function renewMatches(candidates: RenewCandidate[], folder: string, person: string | null): RenewCandidate[] {
  const here = fold(folder.trim());
  if (!here) return [];
  return candidates.filter((c) => c.folder !== null && fold(c.folder) === here && (c.person ?? null) === (person ?? null));
}

/** The For that filing ``entry`` into ``folder`` leaves on it, as the server records it
 * (``InboxService._record_person`` and ``AssignmentService.record_filing`` in the backend):
 * the owner's assignment stays as it is; else a rule's ``{person}`` folder that is kept
 * (compared as ``same``: NFC, case kept) records the suggested person; else a For an
 * earlier filing recorded stays. */
export function filingPerson(entry: InboxEntry, folder: string): string | null {
  const assigned = entry.assignment ?? null;
  if (assigned?.set_by === "owner") return assigned.person ?? null;
  const { person, folder: suggested } = entry.suggestion;
  if (entry.person_follows_folder && person && suggested != null && suggested.normalize("NFC") === folder.normalize("NFC")) {
    return person;
  }
  return assigned?.person ?? null;
}
