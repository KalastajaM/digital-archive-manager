/** Found in this document: the business IDs, IBANs and web or mail domains dam read from
 * the file's text, each linking to the other files that carry it (an ``id:`` search). A
 * business ID can be marked as yours (Mine): it then names no sender and links nothing. */
import { Link } from "react-router-dom";
import { errorText, useFileIdentifiers, usePutOwnIdentifier, useStatus } from "../api/client";
import { plural } from "../format";
import { undoAction, useToast } from "./Toasts";

const documents = (n: number) => plural(n, "document", "documents");

/** Mark a business ID as yours or not, with a toast that can undo it. */
export function useMarkOwn() {
  const put = usePutOwnIdentifier();
  const toast = useToast();
  const mark = (kind: string, value: string, own: boolean, undoing = false) =>
    put.mutate(
      { kind, value, own },
      {
        onSuccess: ({ changed }) => {
          if (undoing) return;
          const from = changed > 0 ? ` From changed on ${documents(changed)}.` : "";
          toast({
            kind: "info",
            text: own
              ? `${value} is marked as yours: it names no sender and links no files.${from}`
              : `${value} is not marked as yours any more.${from}`,
            action: undoAction(() => mark(kind, value, !own, true)),
          });
        },
        onError: (e) => toast({ kind: "error", text: `Could not save: ${errorText(e)}` }),
      },
    );
  return { mark, pending: put.isPending };
}

export function FoundIdentifiers({ driveId }: { driveId: string }) {
  const ids = useStatus().data?.identifiers;
  const query = useFileIdentifiers(driveId, ids !== undefined && ids !== null && ids.read < ids.total);
  const { mark, pending } = useMarkOwn();
  const found = query.data?.identifiers ?? [];
  if (found.length === 0) return null;
  return (
    <section className="found-ids" aria-label="Found in this document">
      <h4>Found in this document</h4>
      <ul>
        {found.map((i) => (
          <li key={`${i.kind}:${i.value}`} className="found-id">
            <span className="found-id-label hint">{i.label}</span>
            <span className="found-id-value" title={i.value}>
              {i.value}
            </span>
            <span className="found-id-end">
              {i.own ? (
                <span className="found-id-others hint">yours</span>
              ) : i.others > 0 ? (
                <Link className="found-id-others" to={`/browse?q=${encodeURIComponent(`id:${i.value}`)}`}>
                  on {plural(i.others, "other file", "other files")}
                </Link>
              ) : (
                <span className="found-id-others hint">only here</span>
              )}
              {i.business && (
                <button
                  type="button"
                  className="link-button"
                  disabled={pending}
                  aria-label={i.own ? `${i.value} is not yours` : `${i.value} is yours`}
                  title={
                    i.own
                      ? "Not your own business ID: it names its sender again"
                      : "Your own business ID: it then names no sender and links no files"
                  }
                  onClick={() => mark(i.kind, i.value, !i.own)}
                >
                  {i.own ? "Not mine" : "Mine"}
                </button>
              )}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}
