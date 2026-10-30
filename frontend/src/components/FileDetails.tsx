/** A document's details as a Mac inspector list: name, folder, its open tray items,
 * its collections and the fields its scan found. Used by Quick Look, the viewer window
 * and the side panels. */
import { type ReactNode, useId } from "react";
import { Link } from "react-router-dom";
import { errorText, type InboxEntry, useFileLinks } from "../api/client";
import { scanFieldLabel, scanFieldValue } from "../format";
import { visible } from "../text";
import { collectionHref } from "../collectionHref";

/** Label → value rows of what the scan found (``entry.fields``: the saved list or the
 * detected one) and, with ``sources``, which rules and date sources the suggestion
 * came from. */
export function scannedFields(entry: InboxEntry, { sources = false } = {}): [string, string][] {
  const rows: [string, string][] = entry.fields.map((f) => [scanFieldLabel(f), scanFieldValue(f)]);
  if (sources && entry.suggestion.sources.length) rows.push(["Sources", entry.suggestion.sources.join(", ")]);
  return rows;
}

export type DetailsFile = { drive_id: string; name: string | null; path: string };

/** The folder part of an archive path ("" at the top). */
export const folderOf = (path: string) => (path.includes("/") ? path.slice(0, path.lastIndexOf("/")) : "");

type Props = {
  file: DetailsFile;
  /** What the scan found, when known (inbox documents). */
  scanned?: [string, string][];
  /** Off in the viewer window: a link there would take the viewer away from the file. */
  links?: boolean;
  /** Off where the name and folder are shown (and edited) above. */
  identity?: boolean;
};

function Row({ label, scanned, children }: { label: string; scanned?: boolean; children: ReactNode }) {
  return (
    <div className={scanned ? "file-details-row scanned" : "file-details-row"}>
      <dt>{label}</dt>
      <dd>{children}</dd>
    </div>
  );
}

export function FileDetails({ file, scanned = [], links = true, identity = true }: Props) {
  const headingId = useId();
  const linked = useFileLinks(file.drive_id);
  const items = (linked.data?.items ?? []).filter((i) => i.state === "open");
  const collections = linked.data?.collections ?? [];
  const name = file.name ?? file.path.slice(file.path.lastIndexOf("/") + 1);
  const folder = folderOf(file.path);
  return (
    <section className="file-details" aria-labelledby={headingId}>
      <h3 id={headingId} className="visually-hidden">
        Details
      </h3>
      <dl>
        {identity && <Row label="Name">{visible(name)}</Row>}
        {identity && <Row label="Folder">{folder ? visible(folder) : "(top)"}</Row>}
        {items.length > 0 && (
          <Row label="Trays">
              <ul className="file-details-list">
                {items.map((i) => (
                  <li key={i.id}>
                    {links ? (
                      <Link to={`/trays/${encodeURIComponent(i.tray_id)}?item=${i.id}`}>
                        {visible(i.tray_name)}: {visible(i.title)}
                      </Link>
                    ) : (
                      `${visible(i.tray_name)}: ${visible(i.title)}`
                    )}
                  </li>
                ))}
              </ul>
          </Row>
        )}
        {collections.length > 0 && (
          <Row label="Collections">
              <ul className="file-details-list">
                {collections.map((c) => (
                  <li key={c.id}>
                    {links ? (
                      <Link to={collectionHref(c)}>
                        {visible(c.name)}
                      </Link>
                    ) : (
                      visible(c.name)
                    )}
                    {c.state === "closed" && " (closed)"}
                  </li>
                ))}
              </ul>
          </Row>
        )}
        {scanned.map(([label, value], i) => (
          <Row key={`${i}-${label}`} label={label} scanned>
            {visible(value)}
          </Row>
        ))}
      </dl>
      {linked.isError && (
        <p className="hint">Its trays and collections could not be loaded: {visible(errorText(linked.error))}</p>
      )}
    </section>
  );
}
