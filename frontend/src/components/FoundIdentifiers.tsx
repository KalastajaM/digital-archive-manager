/** Found in this document: the business IDs, IBANs and web or mail domains dam read from
 * the file's text, each linking to the other files that carry it (an ``id:`` search). */
import { Link } from "react-router-dom";
import { useFileIdentifiers } from "../api/client";
import { plural } from "../format";

export function FoundIdentifiers({ driveId }: { driveId: string }) {
  const query = useFileIdentifiers(driveId);
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
            {i.others > 0 ? (
              <Link className="found-id-others" to={`/browse?q=${encodeURIComponent(`id:${i.value}`)}`}>
                on {plural(i.others, "other file", "other files")}
              </Link>
            ) : (
              <span className="found-id-others hint">only here</span>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}
