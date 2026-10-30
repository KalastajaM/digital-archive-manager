/** /open-collection/<id>: for links that know only a collection's id (Activity, the
 * reorder menu's Open, Maintenance, a new collection): forwards to where the collection
 * opens (Browse; Important on its page), replacing itself so Back skips it. */
import { Navigate, useParams } from "react-router-dom";
import { errorText, useCollectionsWithMarked } from "../api/client";
import { collectionHref } from "../collectionHref";
import { visible } from "../text";

export default function OpenCollection() {
  const id = Number(useParams().id);
  const all = useCollectionsWithMarked();
  if (all.isPending) return <p className="placeholder">Loading…</p>;
  if (all.isError) {
    return (
      <p className="error" role="alert">
        Could not open the collection. {visible(errorText(all.error))}
      </p>
    );
  }
  const c = all.data.find((x) => x.id === id);
  if (!c) return <p className="placeholder">There is no such collection.</p>;
  return <Navigate to={collectionHref(c)} replace />;
}
