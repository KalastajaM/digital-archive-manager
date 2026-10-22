/** Texts for a collection change and the Ongoing sync that followed it (apply routes
 * and member add/remove). Shared by the collection panel and Browse. */
import type { CollectionChange } from "../api/client";

/** The server's ``ongoing_status`` prefixes: a problem the publisher could not fix,
 * and a collection hidden with its parent (a status only). */
export const NOT_MANAGED = "Needs attention: ";
export const NOT_SHOWN = "Not shown: ";

/** The server's refusal to close a parent with open collections inside (the ⋯ menu
 * says it before asking). */
export const CLOSE_CHILDREN_FIRST = "Close or move its collections first";

/** The problems (sync problems, a stopped batch, an index error) and the Ongoing status. */
export function changeLines(result: Pick<CollectionChange, "problems" | "batch" | "ongoing_status">): { problems: string[]; status: string | null } {
  const problems = [...result.problems];
  const batch = result.batch;
  if (batch?.failed) problems.push(`Stopped at ${batch.failed.dst}: ${batch.error ?? "an operation failed"}`);
  else if (batch?.error) problems.push(batch.error);
  if (batch?.index_error) problems.push(batch.index_error);
  return { problems, status: result.ongoing_status };
}

/** The toast after a change: ``done``, or "``done``, but: <problems; status>". */
export function changeToast(done: string, result: CollectionChange): { kind: "info" | "warning"; text: string } {
  const { problems, status } = changeLines(result);
  const extra = [...problems, ...(status ? [status] : [])];
  return extra.length > 0 ? { kind: "warning", text: `${done}, but: ${extra.join("; ")}` } : { kind: "info", text: done };
}

/** A stored status or message shown as a sentence: the first letter capitalised. */
export const sentence = (text: string): string => text.charAt(0).toUpperCase() + text.slice(1);
