/** Settings → Indexing: how page 1 of the documents is read in the background, how fast,
 * and whether older documents are read at all. */
import { errorText, usePage1Backfill, useStatus } from "../api/client";
import { groupDigits } from "../format";
import { visible } from "../text";
import { Page1Speed } from "./Page1Speed";

export function IndexingSettings() {
  const status = useStatus();
  const backfill = usePage1Backfill();
  const page1 = status.data?.page1;
  const ids = status.data?.identifiers;
  return (
    <section aria-label="Indexing">
      <h3>Indexing</h3>
      <p className="hint">
        dam reads page 1 of your PDFs and photos in the background, so rules can look at where words and logos sit on the page.
      </p>
      {status.isError && (
        <p className="error" role="alert">
          Could not load the settings: {visible(errorText(status.error))}
        </p>
      )}
      {page1 && (
        <>
          <label className="check">
            <input
              type="checkbox"
              checked={page1.backfill}
              disabled={backfill.isPending}
              onChange={(e) => backfill.mutate(e.target.checked)}
            />
            Read page 1 of older documents in the background
          </label>
          {backfill.isError && (
            <p className="error" role="alert">
              {visible(errorText(backfill.error))}
            </p>
          )}
          <Page1Speed textPerMin={page1.text_per_min ?? 300} scansPerMin={page1.scans_per_min ?? 30} />
          {ids && (
            <p className="hint">
              Business IDs, IBANs and domains read from {groupDigits(ids.read)} of {groupDigits(ids.total)} documents.
            </p>
          )}
        </>
      )}
    </section>
  );
}
