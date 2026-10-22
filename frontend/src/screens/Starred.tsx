/** The Starred page (the sidebar's Starred row): the built-in ★ Ongoing collection's
 * page, with no rename, close or parent actions. */
import { errorText, useBuiltin } from "../api/client";
import { visible } from "../text";
import CollectionDetail from "./CollectionDetail";

export default function Starred({ today }: { today?: string }) {
  const starred = useBuiltin("starred");
  if (starred.isPending) return <p className="placeholder">Loading…</p>;
  if (starred.isError) {
    return (
      <p className="error" role="alert">
        Could not load Starred. {visible(errorText(starred.error))}
      </p>
    );
  }
  return (
    <section className="collection-page starred-page" aria-label="Starred">
      <CollectionDetail key={starred.data.id} id={starred.data.id} today={today} />
    </section>
  );
}
