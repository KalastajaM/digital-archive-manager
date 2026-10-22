/** Dragging documents inside the app (native HTML5 drag and drop).
 *
 * A drag carries ``application/x-dam-files`` = JSON ``{ids}`` (drive ids). Browsers only
 * let a drop target read the data on ``drop``; while hovering they see the types only.
 * So the ids of a drag started here are also kept in this module until it ends, and
 * ``readDragFiles`` falls back to them during ``dragenter``/``dragover``: a target can
 * say "not allowed" before the drop. Drags from outside (Finder, another tab) carry no
 * such type and are never accepted.
 *
 * A collection dragged in the sidebar carries ``application/x-dam-collection`` = JSON
 * ``{id}`` and nothing else: a files target never sees it as files, and a collection
 * target never takes a drag of files or a Today card (``application/x-dam-card``).
 *
 * A folder dragged from Browse carries ``application/x-dam-folder`` = JSON ``{id}`` and
 * nothing else: only a collection takes it (as a folder member). Files targets (folders,
 * trays, the Inbox) never see it, so a folder is never moved or put in a tray by a drop. */
import { type DragEvent as ReactDragEvent, useEffect, useRef, useState } from "react";
import { CARD_DRAG_TYPE } from "./components/useCardLayout";

export const DRAG_TYPE = "application/x-dam-files";
export const COLLECTION_DRAG_TYPE = "application/x-dam-collection";
export const FOLDER_DRAG_TYPE = "application/x-dam-folder";

type AnyDragEvent = DragEvent | ReactDragEvent;

let dragging: string[] | null = null;
let draggingLabel: string | null = null;
let draggingPaths: string[] | null = null;
let draggingCollection: number | null = null;
let draggingFolder: string | null = null;
let listening = false;

function forgetOnEnd() {
  if (listening || typeof document === "undefined") return;
  listening = true;
  const clear = () => {
    dragging = null;
    draggingLabel = null;
    draggingPaths = null;
    draggingCollection = null;
    draggingFolder = null;
  };
  document.addEventListener("dragend", clear, true);
  document.addEventListener("drop", () => setTimeout(clear, 0), true);
}

/** The drag image: a small pill saying "N files" (or ``label`` for one file). */
function dragImage(text: string): HTMLElement {
  const el = document.createElement("div");
  el.className = "drag-image";
  el.textContent = text;
  el.style.position = "fixed";
  el.style.top = "-1000px";
  el.style.left = "-1000px";
  document.body.appendChild(el);
  setTimeout(() => el.remove(), 0);
  return el;
}

/** Start a drag of ``ids`` (drive ids); ``label`` names a single file in the image.
 * ``paths`` (archive paths, when the source knows them) let a target refuse a drag
 * before the drop, e.g. files already in the inbox; they stay in this window only. */
export function setDragFiles(e: AnyDragEvent, ids: string[], label: string, paths?: string[]) {
  const dt = e.dataTransfer;
  if (!dt) return;
  dt.setData(DRAG_TYPE, JSON.stringify({ ids }));
  dt.setData("text/plain", ids.length === 1 ? label : `${ids.length} files`);
  dt.effectAllowed = "copyMove";
  dragging = [...ids];
  draggingCollection = null;
  draggingFolder = null;
  draggingLabel = label;
  draggingPaths = paths && paths.length === ids.length ? [...paths] : null;
  forgetOnEnd();
  if (typeof dt.setDragImage === "function") {
    dt.setDragImage(dragImage(ids.length === 1 ? label : `${ids.length} files`), 12, 12);
  }
}

/** The ids a list row drags: the whole selection when the row is part of it, else the
 * row's own file alone (as Finder does). */
export function dragSelection(selected: readonly string[], id: string): string[] {
  return selected.includes(id) ? [...selected] : [id];
}

/** The label of the drag started in this window (a single file's name), while it lasts:
 * for a drop's toast ("a.pdf: already in To pay"). */
export const draggedLabel = (): string | null => draggingLabel;

/** The archive paths of the drag started in this window, when its source gave them. */
export const draggedPaths = (): string[] | null => (draggingPaths ? [...draggingPaths] : null);

function parse(raw: string): string[] | null {
  try {
    const value: unknown = JSON.parse(raw);
    const ids = (value as { ids?: unknown })?.ids;
    if (Array.isArray(ids) && ids.length > 0 && ids.every((x) => typeof x === "string")) return ids;
  } catch {
    // not ours
  }
  return null;
}

/** The drive ids a drag carries, or null when it is not a drag of documents. */
export function readDragFiles(e: AnyDragEvent): string[] | null {
  const dt = e.dataTransfer;
  if (!dt) return null;
  const types = Array.from(dt.types ?? []);
  if (!types.includes(DRAG_TYPE)) return null;
  const raw = dt.getData(DRAG_TYPE);
  if (raw) return parse(raw);
  return dragging ? [...dragging] : null;
}

/** Start a drag of collection ``id``; ``label`` (its name) is the drag image. */
export function setDragCollection(e: AnyDragEvent, id: number, label: string) {
  const dt = e.dataTransfer;
  if (!dt) return;
  // only our type: not the link's own URL (a collection row is a link), so a text field
  // or another app never takes it
  if (typeof dt.clearData === "function") dt.clearData();
  dt.setData(COLLECTION_DRAG_TYPE, JSON.stringify({ id }));
  dt.effectAllowed = "move";
  dragging = null;
  draggingLabel = null;
  draggingPaths = null;
  draggingCollection = id;
  draggingFolder = null;
  forgetOnEnd();
  if (typeof dt.setDragImage === "function") dt.setDragImage(dragImage(label), 12, 12);
}

/** Start a drag of the folder ``id`` (its drive id); ``label`` (its name) is the drag
 * image and what a drop's toast calls it. */
export function setDragFolder(e: AnyDragEvent, id: string, label: string) {
  const dt = e.dataTransfer;
  if (!dt) return;
  if (typeof dt.clearData === "function") dt.clearData();
  dt.setData(FOLDER_DRAG_TYPE, JSON.stringify({ id }));
  dt.effectAllowed = "copy";
  dragging = null;
  draggingLabel = label;
  draggingPaths = null;
  draggingCollection = null;
  draggingFolder = id;
  forgetOnEnd();
  if (typeof dt.setDragImage === "function") dt.setDragImage(dragImage(label), 12, 12);
}

/** The folder (drive id) a drag carries, or null when it is not a folder drag. */
export function readDragFolder(e: AnyDragEvent): string | null {
  const dt = e.dataTransfer;
  if (!dt) return null;
  const types = Array.from(dt.types ?? []);
  if (!types.includes(FOLDER_DRAG_TYPE) || types.includes(DRAG_TYPE) || types.includes(CARD_DRAG_TYPE)) return null;
  const raw = dt.getData(FOLDER_DRAG_TYPE);
  if (raw) {
    try {
      const id = (JSON.parse(raw) as { id?: unknown })?.id;
      return typeof id === "string" && id !== "" ? id : null;
    } catch {
      return null; // not ours
    }
  }
  return draggingFolder;
}

function parseCollection(raw: string): number | null {
  try {
    const id = (JSON.parse(raw) as { id?: unknown })?.id;
    if (typeof id === "number" && Number.isSafeInteger(id) && id > 0) return id;
  } catch {
    // not ours
  }
  return null;
}

/** The collection a drag carries, or null: a drag of files or a card (even one that
 * also says collection) is never a collection drag. */
export function readDragCollection(e: AnyDragEvent): number | null {
  const dt = e.dataTransfer;
  if (!dt) return null;
  const types = Array.from(dt.types ?? []);
  if (!types.includes(COLLECTION_DRAG_TYPE) || types.includes(DRAG_TYPE) || types.includes(CARD_DRAG_TYPE)) return null;
  const raw = dt.getData(COLLECTION_DRAG_TYPE);
  if (raw) return parseCollection(raw);
  return draggingCollection;
}

type DropOptions<T> = {
  /** True to accept, false to ignore (no highlight), a string to refuse with a reason. */
  accept: (value: T) => boolean | string;
  onDrop: (value: T) => void;
  /** What a drag carries for this target, null when it is not one it takes part in
   * (default: the dragged files). */
  read?: (e: AnyDragEvent) => T | null;
};

export type DropTarget = {
  /** Spread on the target element. */
  props: {
    onDragEnter: (e: ReactDragEvent) => void;
    onDragOver: (e: ReactDragEvent) => void;
    onDragLeave: (e: ReactDragEvent) => void;
    onDrop: (e: ReactDragEvent) => void;
    "data-drop"?: "over" | "refused";
    "data-tip"?: string;
  };
  /** A drag this target accepts is over it. */
  over: boolean;
  /** The reason a drag over it is not allowed (null: none is refused). */
  refusal: string | null;
};

/** A drop target for dragged documents (or, with ``read``, anything else dragged here):
 * highlights while an accepted drag is over it, shows the refusal reason as a tooltip
 * for a refused one, and calls ``onDrop``. */
export function useDropTarget<T = string[]>({ accept, onDrop, read }: DropOptions<T>): DropTarget {
  const readDrag = read ?? (readDragFiles as unknown as (e: AnyDragEvent) => T | null);
  const [state, setState] = useState<{ over: boolean; refusal: string | null }>({ over: false, refusal: null });
  const depth = useRef(0); // dragenter/dragleave also fire for the target's children
  const judge = (e: ReactDragEvent): boolean | string | null => {
    const value = readDrag(e);
    return value === null ? null : accept(value);
  };
  const reset = () => {
    depth.current = 0;
    setState((old) => (old.over || old.refusal ? { over: false, refusal: null } : old));
  };
  // A drag that ends anywhere (dropped elsewhere, or cancelled with Esc) leaves no
  // highlight behind: dragleave does not always fire then.
  useEffect(() => {
    const end = () => reset();
    document.addEventListener("dragend", end, true);
    document.addEventListener("drop", end, true);
    return () => {
      document.removeEventListener("dragend", end, true);
      document.removeEventListener("drop", end, true);
    };
  }, []);
  const props: DropTarget["props"] = {
    // A target that takes part in the drag (accepts or refuses it) keeps its events from
    // an enclosing target (a folder row inside a pane's list): only the innermost one
    // highlights, judges and receives the drop.
    onDragEnter: (e) => {
      const verdict = judge(e);
      if (verdict === null || verdict === false) return;
      e.preventDefault();
      e.stopPropagation();
      depth.current += 1;
      setState(verdict === true ? { over: true, refusal: null } : { over: false, refusal: verdict });
    },
    onDragOver: (e) => {
      const verdict = judge(e);
      if (verdict === null || verdict === false) return;
      e.preventDefault(); // without it the drop never fires
      e.stopPropagation();
      if (e.dataTransfer) e.dataTransfer.dropEffect = verdict === true ? "move" : "none";
    },
    onDragLeave: (e) => {
      if (depth.current === 0) return; // not ours: let an enclosing target count it
      e.stopPropagation();
      depth.current -= 1;
      if (depth.current === 0) setState({ over: false, refusal: null });
    },
    onDrop: (e) => {
      const value = readDrag(e);
      const verdict = value === null ? null : accept(value);
      reset();
      if (value === null || verdict === null || verdict === false) return;
      e.preventDefault(); // ours, even when refused: the browser must not open it
      e.stopPropagation();
      if (verdict === true) onDrop(value);
    },
  };
  if (state.over) props["data-drop"] = "over";
  else if (state.refusal) {
    props["data-drop"] = "refused";
    props["data-tip"] = state.refusal;
  }
  return { props, over: state.over, refusal: state.refusal };
}

/** Whether documents are being dragged in this page right now (a drag started here,
 * until it is dropped or cancelled): drop targets that only exist for a drag, such as an
 * empty "Ungrouped", show while it lasts. */
export function useFilesDragging(): boolean {
  const [dragging, setDragging] = useState(false);
  useEffect(() => {
    const start = (e: DragEvent) => {
      if (e.dataTransfer?.types.includes(DRAG_TYPE)) setDragging(true);
    };
    const stop = () => setDragging(false);
    document.addEventListener("dragstart", start);
    document.addEventListener("dragend", stop);
    document.addEventListener("drop", stop);
    return () => {
      document.removeEventListener("dragstart", start);
      document.removeEventListener("dragend", stop);
      document.removeEventListener("drop", stop);
    };
  }, []);
  return dragging;
}
