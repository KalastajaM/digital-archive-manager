/** Collections. ``/collections`` is the index: "New collection", Open/Closed and the
 * list, as a Mac list. ``/collections/<id>`` is one collection's page (the sidebar
 * lists the open ones and is the main way in). */
import { ChevronRight, Layers } from "lucide-react";
import { type ReactNode, useEffect, useId, useRef, useState } from "react";
import { Link, useLocation, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { type CollectionRow, errorText, useCollections, useCreateCollection } from "../api/client";
import { COLLECTION_NAME_MAX } from "../components/CollectionPicker";
import { sentence } from "../components/collectionText";
import { childrenOf, countsOf, PATH_SEP, pathOf } from "../components/collectionTree";
import {
  type CollectionOrder,
  orderKeys,
  useCollectionDragging,
  useCollectionOrder,
  useMoveCollection,
  useOrderMenu,
  useReorderRow,
} from "../components/useCollectionOrder";
import { readDragCollection, setDragCollection, useDropTarget } from "../dnd";
import { EmptyState } from "../components/ui/EmptyState";
import { Tag } from "../components/ui/Tag";
import { Segmented } from "../components/ui/Segmented";
import { Toolbar } from "../components/ui/Toolbar";
import { visible } from "../text";
import CollectionDetail from "./CollectionDetail";
import { collectionHref } from "../collectionHref";

/** An inline name input: Enter (or Create) creates the collection and opens it. */
function NewCollection({ onCreated }: { onCreated: (id: number) => void }) {
  const id = useId();
  // The sidebar's "+" opens /collections?new=1: the name field takes the focus.
  const location = useLocation();
  const wanted = new URLSearchParams(location.search).get("new") === "1";
  const field = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (wanted) field.current?.focus();
  }, [wanted, location.key]);
  const create = useCreateCollection();
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const inFlight = useRef(false); // Enter and a click (or two clicks) create one collection
  const submit = async () => {
    const value = name.trim();
    if (!value || inFlight.current) return;
    inFlight.current = true;
    setError(null);
    try {
      const c = await create.mutateAsync(value);
      setName("");
      onCreated(c.id);
    } catch (e) {
      setError(errorText(e));
    } finally {
      inFlight.current = false;
    }
  };
  return (
    <div className="new-collection">
      <label htmlFor={id} className="visually-hidden">
        New collection
      </label>
      <div className="new-collection-row">
        <Layers className="new-collection-icon" size={16} strokeWidth={1.75} aria-hidden="true" />
        <input
          id={id}
          ref={field}
          value={name}
          maxLength={COLLECTION_NAME_MAX}
          spellCheck={false}
          placeholder="New collection, e.g. Sauna conversion"
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              void submit();
            }
          }}
        />
        <button type="button" className="primary" disabled={!name.trim() || create.isPending} onClick={() => void submit()}>
          Create
        </button>
      </div>
      {error && (
        <p className="error" role="alert">
          {visible(error)}
        </p>
      )}
    </div>
  );
}

/** One collection of the index. ``where``: the parent path of one whose parent is not
 * in this list (a closed collection inside an open one). */
function Row({
  c,
  href,
  collections,
  where,
  order,
  onMenu,
  mover,
}: {
  c: CollectionRow;
  href: string;
  collections: number;
  where?: string;
  order: CollectionOrder;
  onMenu: (c: CollectionRow) => (e: React.MouseEvent) => void;
  mover: ReturnType<typeof useMoveCollection>;
}) {
  // a dragged collection: top or bottom third puts it before or after this row (a drop
  // line), the middle third inside it (highlighted)
  const target = useDropTarget<number>({ read: readDragCollection, accept: mover.accept(c), onDrop: mover.move(c) });
  const reorder = useReorderRow(order, c, target.props);
  return (
    <article
      className="collection-row"
      aria-label={visible(c.name)}
      data-collection-id={c.id}
      draggable
      onDragStart={(e) => setDragCollection(e, c.id, c.name)}
      onKeyDown={orderKeys(order, c)}
      onContextMenu={onMenu(c)}
      {...reorder.props}
    >
      <Layers className="collection-row-icon" size={18} strokeWidth={1.75} aria-hidden="true" />
      <div className="collection-row-main">
        <p className="collection-row-title">
          <Link to={href}>{visible(c.name)}</Link>
        </p>
        <p className="collection-row-meta">
          {where && <>In {visible(where)} · </>}
          {countsOf(c, collections)}
        </p>
        {c.summary && <p className="collection-row-summary">{visible(c.summary)}</p>}
      </div>
      {c.ongoing_status && <Tag tone="orange">{sentence(visible(c.ongoing_status))}</Tag>}
      <ChevronRight className="collection-row-chevron" size={14} aria-hidden="true" />
    </article>
  );
}

export default function Collections({ today }: { today?: string }) {
  const params = useParams();
  const [search] = useSearchParams();
  const navigate = useNavigate();
  const state = search.get("state") === "closed" ? "closed" : "open";
  const opened = Number(params.id) || null;
  if (opened !== null) {
    return (
      <section className="collection-page" aria-label="Collection">
        <CollectionDetail key={opened} id={opened} today={today} />
      </section>
    );
  }
  return <CollectionIndex state={state} onState={(s) => navigate(s === "closed" ? "/collections?state=closed" : "/collections")} />;
}

function CollectionIndex({ state, onState }: { state: "open" | "closed"; onState: (s: "open" | "closed") => void }) {
  const navigate = useNavigate();
  const list = useCollections(state);
  const order = useCollectionOrder(list.data ?? []);
  const menu = useOrderMenu(order);
  const mover = useMoveCollection(list.data ?? [], () => {});
  const dragging = useCollectionDragging();
  const top = useDropTarget<number>({ read: readDragCollection, accept: mover.accept(null), onDrop: mover.move(null) });

  let body: ReactNode;
  if (list.isPending) body = <p className="placeholder">Loading…</p>;
  else if (list.isError) {
    body = (
      <p className="error" role="alert">
        Could not load the collections. {visible(errorText(list.error))}
      </p>
    );
  } else if (list.data.length === 0) {
    body = (
      <EmptyState
        icon={<Layers size={40} strokeWidth={1.25} />}
        title={state === "open" ? "No open collections." : "No closed collections."}
        hint={state === "open" ? "A collection gathers files for one case: a house sale, an estate, a renovation." : undefined}
      />
    );
  } else {
    const kids = childrenOf(list.data);
    const ids = new Set(list.data.map((c) => c.id));
    const branch = (level: CollectionRow[]): ReactNode =>
      level.map((c) => {
        const under = kids.get(c.id) ?? [];
        const parent = pathOf(c).slice(0, -1);
        const where = c.parent_id != null && !ids.has(c.parent_id) && parent.length > 0 ? parent.join(PATH_SEP) : undefined;
        return (
          <li key={c.id}>
            <Row c={c} href={collectionHref(c)} collections={under.length} where={where} order={order} onMenu={menu.onContextMenu} mover={mover} />
            {under.length > 0 && <ul className="collection-list collection-children-list">{branch(under)}</ul>}
          </li>
        );
      });
    body = (
      <ul className="collection-list" aria-label="Collections">
        {branch(kids.get(null) ?? [])}
      </ul>
    );
  }

  return (
    <div className="collections-index">
      <Toolbar
        title="Collections"
        subtitle={list.data ? `${list.data.length} ${state}` : undefined}
        actions={
          <Segmented
            ariaLabel="Show"
            value={state}
            onChange={onState}
            options={[
              { value: "open", label: "Open" },
              { value: "closed", label: "Closed" },
            ]}
          />
        }
      />
      <div className="collections-index-body">
        {state === "open" && <NewCollection onCreated={(id) => navigate(`/open-collection/${id}`)} />}
        {dragging && (
          <p className="collections-top-drop hint" {...top.props}>
            Drop here to move it to the top level, last
          </p>
        )}
        {body}
        {menu.element}
      </div>
    </div>
  );
}
