import { Maximize2, Printer } from "lucide-react";
import {
  createContext,
  type Dispatch,
  type ImgHTMLAttributes,
  type ReactNode,
  type RefObject,
  type SetStateAction,
  useContext,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import { useNavigate } from "react-router-dom";
import {
  errorText,
  type FileRecord,
  fetchTextPreview,
  type PageWidth,
  pageUrl,
  rawUrl,
  type TextPreview as TextPreviewData,
  thumbUrl,
  useFileDetail,
} from "../api/client";
import { isShortcutIn, useKeydown } from "../keyboard";
import { openViewer } from "../selection";
import { inFileManager } from "../fileManager";
import { visible, visibleText } from "../text";
import { InlineResults, LaunchButtons, notConnected, useFileLaunch } from "./FileLaunch";
import { pageSrcs, printImages } from "./print";
import { useToast } from "./Toasts";
import { IconButton } from "./ui/IconButton";
import { type BoxTool, WithBoxes } from "./zones/PageBoxes";
import { parentOf } from "../paths";

// Shown with <img> from /raw (never an iframe: /raw is CSP-sandboxed).
const IMAGE_EXTS = new Set(["png", "jpg", "jpeg", "gif", "webp", "avif", "heic", "heif"]);

/** Zoom steps relative to "Fit" (the whole page visible in the pane); 1 is Fit. */
export const ZOOM_LEVELS = [0.5, 0.75, 1, 1.5, 2, 3] as const;
const FIT = ZOOM_LEVELS.indexOf(1);
export const FIT_LEVEL = FIT;

/** The page render width that stays sharp at this zoom (API width buckets). */
const renderWidth = (zoom: number): PageWidth => (zoom <= 1 ? 900 : zoom <= 1.5 ? 1400 : 2000);

/** The zoom level (an index into ``ZOOM_LEVELS``) of a preview, when its owner keeps it
 * (Quick Look keeps the user's zoom while paging through documents). */
export type ZoomControl = [number, Dispatch<SetStateAction<number>>];

/** Whether a preview takes the + / - / 0 keys itself. Quick Look's compare mode turns it
 * off: with two previews in one dialog, it sends the keys to one of them (or both). */
export const ZoomKeys = createContext(true);

/** Zoom state plus the + / - / 0 keys (ignored while typing, and behind an open dialog:
 * a preview inside the dialog, as in Quick Look, keeps them). */
function useZoom(root: RefObject<HTMLElement | null>, control?: ZoomControl) {
  const own = useState(FIT);
  const keys = useContext(ZoomKeys);
  const [level, setLevel] = control ?? own;
  const zoomIn = () => setLevel((l) => Math.min(ZOOM_LEVELS.length - 1, l + 1));
  const zoomOut = () => setLevel((l) => Math.max(0, l - 1));
  const fit = () => setLevel(FIT);
  useKeydown((e) => {
    if (!keys || !isShortcutIn(e, root.current)) return;
    if (e.key === "+" || e.key === "=") zoomIn();
    else if (e.key === "-") zoomOut();
    else if (e.key === "0") fit();
    else return;
    e.preventDefault();
  });
  return { zoom: ZOOM_LEVELS[level], level, zoomIn, zoomOut, fit };
}

type Zoom = ReturnType<typeof useZoom>;

/** ⤢: the document in the separate viewer window. */
function OpenInWindow({ driveId }: { driveId: string }) {
  return <IconButton icon={<Maximize2 />} label="Open in window" className="doc-wide" onClick={() => openViewer(driveId)} />;
}

/** Print: the PDF's pages (sharp: the widest render) or the image. A failure goes to
 * the dialog's status line inside Quick Look, else a toast. */
function PrintButton({ srcs, name }: { srcs: () => Iterable<string>; name: string }) {
  const [busy, setBusy] = useState(false);
  const inline = useContext(InlineResults);
  const toast = useToast();
  const print = async () => {
    setBusy(true);
    try {
      if ((await printImages(srcs(), name)) === 0) {
        (inline ?? toast)({ kind: "error", text: "Could not print: the preview did not load" });
      }
    } finally {
      setBusy(false);
    }
  };
  return (
    <IconButton
      icon={<Printer />}
      label="Print"
      className="doc-wide"
      onClick={() => void print()}
      disabled={busy}
      disabledReason="Preparing to print…"
    />
  );
}

function ZoomControls({ zoom, children }: { zoom: Zoom; children?: ReactNode }) {
  return (
    <div className="zoom-controls" role="group" aria-label="Zoom">
      <button type="button" aria-label="Zoom out" disabled={zoom.level === 0} onClick={zoom.zoomOut}>
        −
      </button>
      {/* The level is also the way back: "150%" fits again on click; at Fit it is inert. */}
      <button
        type="button"
        className="zoom-level"
        data-testid="zoom-level"
        aria-label="Fit"
        title={zoom.level === FIT ? "The whole page fits" : "Fit the whole page (0)"}
        disabled={zoom.level === FIT}
        onClick={zoom.fit}
      >
        {zoom.level === FIT ? "Fit" : `${Math.round(zoom.zoom * 100)}%`}
      </button>
      <button
        type="button"
        aria-label="Zoom in"
        disabled={zoom.level === ZOOM_LEVELS.length - 1}
        onClick={zoom.zoomIn}
      >
        +
      </button>
      {children}
    </div>
  );
}

/** What a ZoomFrame tells its image: the width for a zoom (Fit = the whole page inside
 * the frame, measured; before that is known, a share of the frame width) and the
 * natural size once loaded. */
const FitContext = createContext<{ width: (zoom: number) => string; loaded: (img: HTMLImageElement) => void }>({
  width: (zoom) => `${zoom * 100}%`,
  loaded: () => {},
});

/** A clear loading state for a preview that has not arrived yet. */
function PreviewLoading() {
  return (
    <p className="busy preview-loading">
      Loading preview…
    </p>
  );
}

/** The page or image inside a ZoomFrame, with "Loading preview…" until it has arrived
 * (give it a ``key`` per page: a new page is a new load). */
function ZoomImage({ zoom, className, onLoad, ...rest }: ImgHTMLAttributes<HTMLImageElement> & { zoom: number }) {
  const fit = useContext(FitContext);
  const [ready, setReady] = useState(false);
  return (
    <>
      {!ready && <PreviewLoading />}
      <img
        {...rest}
        className={[className, !ready && "loading"].filter(Boolean).join(" ") || undefined}
        style={{ width: fit.width(zoom) }}
        onLoad={(e) => {
          setReady(true);
          fit.loaded(e.currentTarget);
          onLoad?.(e);
        }}
      />
    </>
  );
}

/** Wheel delta (px) that makes one zoom step; small pinch deltas add up to it. */
const WHEEL_STEP = 50;

/** The scrolling frame around a zoomed image: drag with the mouse to pan, Cmd/Ctrl +
 * wheel (a trackpad pinch arrives as Ctrl + wheel) to zoom around the cursor.
 * A plain wheel scrolls as usual. */
function ZoomFrame({ zoom, children }: { zoom: Zoom; children: ReactNode }) {
  const frame = useRef<HTMLDivElement>(null);
  const [dragging, setDragging] = useState(false);
  const wheel = useRef(0);
  // Where to keep still while the zoom changes: a point in the frame and the zoom before.
  const anchor = useRef<{ x: number; y: number; from: number } | null>(null);
  const zoomRef = useRef(zoom);
  zoomRef.current = zoom;
  // Fit: the whole page inside the frame. The frame's inner size (its height from ``--zoom-max``) and the page's proportions.
  const probe = useRef<HTMLSpanElement>(null);
  const [box, setBox] = useState<{ w: number; h: number } | null>(null);
  const [ratio, setRatio] = useState<number | null>(null);
  useLayoutEffect(() => {
    const el = frame.current;
    if (!el) return;
    const measure = () => {
      const cs = getComputedStyle(el);
      const px = (v: string) => Number.parseFloat(v) || 0;
      // the probe is as tall as the frame may be (``--zoom-max``: a viewport share when the
      // frame grows with its page, all of it when the pane fills it): in px, whatever the unit
      const max = probe.current?.offsetHeight ?? 0;
      const w = el.offsetWidth - px(cs.paddingLeft) - px(cs.paddingRight);
      const h = max - px(cs.paddingTop) - px(cs.paddingBottom);
      setBox((old) => (old && old.w === w && old.h === h ? old : { w, h }));
    };
    measure();
    if (typeof ResizeObserver !== "function") {
      window.addEventListener("resize", measure);
      return () => window.removeEventListener("resize", measure);
    }
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    return () => observer.disconnect();
  }, []);
  const fitContext = {
    width: (z: number) => {
      if (!box || !ratio || box.w <= 0) return `${z * 100}%`;
      const fitWidth = box.h > 0 ? Math.min(box.w, box.h * ratio) : box.w;
      return `${Math.floor(z * fitWidth)}px`;
    },
    loaded: (img: HTMLImageElement) => {
      if (img.naturalWidth > 0 && img.naturalHeight > 0) setRatio(img.naturalWidth / img.naturalHeight);
    },
  };
  // Ends a drag still in progress if the frame goes away (e.g. j to the next file).
  const endDrag = useRef<(() => void) | null>(null);
  useEffect(() => () => endDrag.current?.(), []);

  useEffect(() => {
    const el = frame.current;
    if (!el) return;
    // Native and non-passive: preventDefault must stop the browser's own page zoom.
    const onWheel = (e: WheelEvent) => {
      if (!e.ctrlKey && !e.metaKey) return;
      e.preventDefault();
      wheel.current += e.deltaY;
      if (Math.abs(wheel.current) < WHEEL_STEP) return;
      const z = zoomRef.current;
      const rect = el.getBoundingClientRect();
      anchor.current = { x: e.clientX - rect.left, y: e.clientY - rect.top, from: z.zoom };
      if (wheel.current < 0) z.zoomIn();
      else z.zoomOut();
      wheel.current = 0;
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, []);

  // After a wheel zoom, scroll so the point under the cursor stays under it.
  useLayoutEffect(() => {
    const el = frame.current;
    const a = anchor.current;
    anchor.current = null;
    if (!el || !a || a.from === zoom.zoom) return;
    const ratio = zoom.zoom / a.from;
    el.scrollLeft = (el.scrollLeft + a.x) * ratio - a.x;
    el.scrollTop = (el.scrollTop + a.y) * ratio - a.y;
  }, [zoom.zoom]);

  const onMouseDown = (e: React.MouseEvent) => {
    const el = frame.current;
    if (!el || e.button !== 0 || zoom.zoom <= 1) return;
    e.preventDefault(); // no text selection or native image drag
    const start = { x: e.clientX, y: e.clientY, left: el.scrollLeft, top: el.scrollTop };
    setDragging(true);
    const move = (m: MouseEvent) => {
      el.scrollLeft = start.left - (m.clientX - start.x);
      el.scrollTop = start.top - (m.clientY - start.y);
    };
    const up = () => {
      endDrag.current = null;
      window.removeEventListener("mousemove", move);
      window.removeEventListener("mouseup", up);
      setDragging(false);
    };
    endDrag.current = () => {
      window.removeEventListener("mousemove", move);
      window.removeEventListener("mouseup", up);
    };
    window.addEventListener("mousemove", move);
    window.addEventListener("mouseup", up);
  };

  const cls = ["zoom-frame", zoom.zoom > 1 && "pannable", dragging && "dragging"].filter(Boolean);
  return (
    <div ref={frame} className={cls.join(" ")} data-testid="zoom-frame" onMouseDown={onMouseDown}>
      <span ref={probe} className="zoom-probe" aria-hidden="true" />
      <FitContext.Provider value={fitContext}>{children}</FitContext.Provider>
    </div>
  );
}

/** The last step of the chain: no preview; a double click opens the file. */
function NoPreview({ path, onOpen }: { path: string; onOpen: () => void }) {
  return (
    <div className="no-preview" onDoubleClick={onOpen} title="Double-click to open">
      <p>No preview</p>
      <p>
        {/* a double click here selects the path (to copy it) instead of opening the file */}
        Open it {inFileManager()}: <code onDoubleClick={(e) => e.stopPropagation()}>{visible(path)}</code>
      </p>
    </div>
  );
}

/** Tools above a preview without zoom (text, thumbnail, none). */
function PreviewTools({ children }: { children: ReactNode }) {
  return (
    <div className="preview-tools" role="group" aria-label="File">
      {children}
    </div>
  );
}

/** The start of a text-like file, as text (hidden characters marked). A failure
 * (``onFail``) moves on to the Quick Look thumbnail. */
function TextPreview({ driveId, tools, onFail }: { driveId: string; tools: ReactNode; onFail: () => void }) {
  const [text, setText] = useState<TextPreviewData | null>(null);
  const failed = useRef(onFail);
  failed.current = onFail;
  useEffect(() => {
    let live = true;
    const controller = new AbortController();
    fetchTextPreview(driveId, controller.signal).then(
      (t) => live && setText(t),
      () => live && failed.current(),
    );
    return () => {
      live = false;
      controller.abort();
    };
  }, [driveId]);
  return (
    <figure className="text-figure">
      <PreviewTools>{tools}</PreviewTools>
      {text === null ? (
        <p className="busy preview-loading" role="status">
          Loading the text…
        </p>
      ) : (
        <>
          <pre className="text-preview" data-testid="text-preview">
            {visibleText(text.text.replace(/\r\n?/g, "\n"))}
          </pre>
          {text.truncated && <p className="hint">Only the start of the file is shown. Open it to see all of it.</p>}
        </>
      )}
    </figure>
  );
}

/** How long the selection must stay on a file before its thumbnail is asked for:
 * j/k through a folder starts no Quick Look renders for the files passed over. */
export const THUMB_SETTLE_MS = 250;

type ThumbState = { kind: "waiting" } | { kind: "busy" } | { kind: "ready"; url: string };

/** The Quick Look thumbnail (macOS renders it), fetched once the selection is still;
 * none (404) moves on to "No preview"; a busy server (503) offers a retry. Moving on
 * aborts the request, so the server skips a render nobody will see. */
function ThumbPreview({ file, tools, onFail }: { file: PreviewFile; tools: ReactNode; onFail: () => void }) {
  const name = file.path.slice(file.path.lastIndexOf("/") + 1);
  const [state, setState] = useState<ThumbState>({ kind: "waiting" });
  const [attempt, setAttempt] = useState(0);
  const failed = useRef(onFail);
  failed.current = onFail;
  useEffect(() => {
    const abort = new AbortController();
    let url: string | null = null;
    const load = async () => {
      const response = await fetch(thumbUrl(file.drive_id), { credentials: "same-origin", signal: abort.signal });
      if (abort.signal.aborted) return;
      if (response.status === 503) return setState({ kind: "busy" });
      if (!response.ok) return failed.current();
      const blob = await response.blob();
      if (abort.signal.aborted) return;
      url = URL.createObjectURL(blob);
      setState({ kind: "ready", url });
    };
    const timer = window.setTimeout(
      () =>
        void load().catch(() => {
          if (!abort.signal.aborted) failed.current();
        }),
      attempt === 0 ? THUMB_SETTLE_MS : 0, // a retry is a click: no wait
    );
    return () => {
      window.clearTimeout(timer);
      abort.abort();
      if (url) URL.revokeObjectURL(url);
    };
  }, [file.drive_id, attempt]);
  const retry = () => {
    setState({ kind: "waiting" });
    setAttempt((n) => n + 1);
  };
  return (
    <figure className="thumb-figure">
      <PreviewTools>{tools}</PreviewTools>
      <div className="thumb-frame">
        {state.kind === "ready" ? (
          <img
            className="thumb-preview"
            draggable={false}
            src={state.url}
            alt={`Preview of ${visible(name)}`}
            onError={onFail}
          />
        ) : state.kind === "waiting" ? (
          <PreviewLoading />
        ) : (
          <div className="thumb-busy">
            <p className="hint" role="status">
              Preview busy — try again
            </p>
            <button type="button" onClick={retry}>
              Try again
            </button>
          </div>
        )}
      </div>
    </figure>
  );
}

/** PDF pages as PNGs rendered by the API (page count unknown: a 404 marks the end). */
function PdfPages({
  driveId,
  tools,
  control,
  boxTool,
  onFail,
}: {
  driveId: string;
  tools?: ReactNode;
  control?: ZoomControl;
  boxTool?: BoxTool;
  onFail: () => void;
}) {
  const [page, setPage] = useState(1);
  const [lastPage, setLastPage] = useState<number | null>(null);
  const root = useRef<HTMLElement>(null);
  const zoom = useZoom(root, control);

  return (
    <WithBoxes driveId={driveId} tool={boxTool} pageOne={page === 1}>
      {(boxes) => (
        <figure className="pdf-pages" ref={root}>
          <ZoomControls zoom={zoom}>
            {boxes.button}
            <PrintButton srcs={() => pageSrcs((n) => pageUrl(driveId, n, 2000))} name="Document" />
            {tools}
          </ZoomControls>
          <ZoomFrame zoom={zoom}>
            {boxes.around(
              <ZoomImage
                key={page}
                zoom={zoom.zoom}
                draggable={false}
                src={pageUrl(driveId, page, renderWidth(zoom.zoom))}
                alt={`Page ${page}`}
                onError={() => {
                  if (page === 1) {
                    onFail();
                  } else {
                    setLastPage(page - 1);
                    setPage(page - 1);
                  }
                }}
              />,
            )}
          </ZoomFrame>
          {boxes.panel}
          <figcaption>
            <button
              type="button"
              aria-label="Previous page"
              disabled={page <= 1}
              onClick={() => setPage(page - 1)}
            >
              ‹
            </button>
            <span>
              Page {page}
              {lastPage !== null && ` of ${lastPage}`}
            </span>
            <button
              type="button"
              aria-label="Next page"
              disabled={lastPage !== null && page >= lastPage}
              onClick={() => setPage(page + 1)}
            >
              ›
            </button>
          </figcaption>
        </figure>
      )}
    </WithBoxes>
  );
}

function ImagePreview({
  driveId,
  path,
  tools,
  control,
  boxTool,
  onFail,
}: {
  driveId: string;
  path: string;
  tools?: ReactNode;
  control?: ZoomControl;
  boxTool?: BoxTool;
  onFail: () => void;
}) {
  const root = useRef<HTMLElement>(null);
  const zoom = useZoom(root, control);
  return (
    <WithBoxes driveId={driveId} tool={boxTool} pageOne>
      {(boxes) => (
        <figure className="image-figure" ref={root}>
          <ZoomControls zoom={zoom}>
            {boxes.button}
            <PrintButton srcs={() => [rawUrl(driveId)]} name={path} />
            {tools}
          </ZoomControls>
          <ZoomFrame zoom={zoom}>
            {boxes.around(
              <ZoomImage
                zoom={zoom.zoom}
                className="image-preview"
                draggable={false}
                src={rawUrl(driveId)}
                alt={path}
                onError={onFail}
              />,
            )}
          </ZoomFrame>
          {boxes.panel}
        </figure>
      )}
    </WithBoxes>
  );
}

/** What a preview needs to know about a file (an index record has all of it). A link
 * (``is_link``) previews as its target inside the archive. */
export type PreviewFile = Pick<FileRecord, "drive_id" | "path" | "ext"> & { is_link?: boolean; folder?: string | null; connected?: boolean };

type PreviewProps = {
  file: PreviewFile;
  /** The ⤢ "Open in window" button (off inside the viewer window itself). */
  windowButton?: boolean;
  /** The zoom level, kept by the owner (Quick Look keeps it from one document to the next). */
  zoomControl?: ZoomControl;
  /** More buttons at the right end of the toolbar (the ★ and ! toggles). */
  extraTools?: ReactNode;
  /** The "Draw a box" tool on page 1 of a PDF or an image (off when left out). */
  boxTool?: BoxTool;
};

type LinkProps = {
  /** A link's "Go to target" button (off in the viewer window, which has no Browse). */
  goToTarget?: boolean;
  /** Runs before "Go to target" navigates (Quick Look closes itself first). */
  beforeGoToTarget?: () => void;
};

/** Text-like types the API previews as text (``/text``). */
const TEXT_EXTS = new Set(["txt", "md", "csv", "log", "json", "xml", "yaml", "yml"]);

/** The fallback chain: the document itself (PDF pages, an image) → its text → the
 * Quick Look thumbnail → "No preview". Each step that fails moves on to the next. */
type Stage = "doc" | "text" | "thumb" | "none";

const firstStage = (kind: string): Stage =>
  kind === "pdf" || IMAGE_EXTS.has(kind) ? "doc" : TEXT_EXTS.has(kind) ? "text" : "thumb";

function Preview({ file, windowButton, zoomControl, extraTools, boxTool }: PreviewProps & { windowButton: boolean }) {
  const { drive_id: driveId, path, ext } = file;
  const kind = ext?.toLowerCase() ?? "";
  const [stage, setStage] = useState<Stage>(() => firstStage(kind));
  const launch = useFileLaunch(driveId);
  const offline = file.connected === false;
  const tools = (
    <>
      <LaunchButtons launch={launch} offline={offline} />
      {windowButton && <OpenInWindow driveId={driveId} />}
      {extraTools}
    </>
  );
  const next = (to: Stage) => () => setStage(to);
  if (offline) {
    return (
      <figure className="no-preview-figure">
        <PreviewTools>{tools}</PreviewTools>
        <div className="no-preview">
          <p role="status">{notConnected(file.folder ?? "")}</p>
        </div>
      </figure>
    );
  }
  if (stage === "doc" && kind === "pdf") return <PdfPages driveId={driveId} tools={tools} control={zoomControl} boxTool={boxTool} onFail={next("thumb")} />;
  if (stage === "doc") return <ImagePreview driveId={driveId} path={path} tools={tools} control={zoomControl} boxTool={boxTool} onFail={next("thumb")} />;
  if (stage === "text") return <TextPreview driveId={driveId} tools={tools} onFail={next("thumb")} />;
  if (stage === "thumb") return <ThumbPreview file={file} tools={tools} onFail={next("none")} />;
  return (
    <figure className="no-preview-figure">
      <PreviewTools>{tools}</PreviewTools>
      <NoPreview path={path} onOpen={() => void launch.run("open")} />
    </figure>
  );
}

const extOfPath = (path: string) => {
  const name = path.slice(path.lastIndexOf("/") + 1);
  return name.includes(".") ? name.slice(name.lastIndexOf(".") + 1).toLowerCase() : null;
};

/** "Link to <path>" (hidden characters marked). */
function LinkTo({ path, children }: { path: string; children?: ReactNode }) {
  return (
    <p className="link-to">
      <span>Link to</span> <code>{visible(path)}</code>
      {children}
    </p>
  );
}

/** A link previews, opens and shows in Finder as its target when that is inside the
 * archive (the server follows the link: requests still name the link), with "Go to
 * target" to the target in Browse. Otherwise (outside, missing): no preview and only
 * Show in Finder, which shows the link itself. A detail that fails to load is only
 * that error (nothing is known about the target). */
function LinkPreview({
  file,
  windowButton,
  goToTarget,
  beforeGoToTarget,
  zoomControl,
  extraTools,
  boxTool,
}: PreviewProps & { windowButton: boolean } & LinkProps & { goToTarget: boolean }) {
  const detail = useFileDetail(file.drive_id);
  const navigate = useNavigate();
  const launch = useFileLaunch(file.drive_id);
  // the screen's tools (★ / !, the bin…) stay while the link is loading or failed to
  if (detail.isPending || detail.isError) {
    return (
      <>
        {extraTools && <PreviewTools>{extraTools}</PreviewTools>}
        {detail.isPending ? (
          <p className="hint" role="status">
            Loading the link…
          </p>
        ) : (
          <p className="error" role="alert">
            Could not load the link: {visible(errorText(detail.error))}
          </p>
        )}
      </>
    );
  }
  const d = detail.data;
  const target = d.link_target_path;
  if (d?.link_target_inside && d.link_target_id && target) {
    const targetId = d.link_target_id;
    const goTo = () => {
      beforeGoToTarget?.();
      navigate(`/browse?${new URLSearchParams({ path: parentOf(target), select: targetId })}`);
    };
    return (
      <>
        <LinkTo path={target}>
          {goToTarget && (
            <>
              {" "}
              <button type="button" onClick={goTo}>
                Go to target
              </button>
            </>
          )}
        </LinkTo>
        <Preview
          file={{ drive_id: file.drive_id, path: target, ext: extOfPath(target) }}
          windowButton={windowButton}
          zoomControl={zoomControl}
          extraTools={extraTools}
          boxTool={boxTool}
        />
      </>
    );
  }
  return (
    <figure className="no-preview-figure">
      <PreviewTools>
        <LaunchButtons launch={launch} only="reveal" />
        {extraTools}
      </PreviewTools>
      <div className="no-preview">
        <p>No preview (the link points outside the archive or to nothing)</p>
        {target !== null && <LinkTo path={target} />}
      </div>
    </figure>
  );
}

export function FilePreview({
  file,
  windowButton = true,
  goToTarget = true,
  beforeGoToTarget,
  zoomControl,
  extraTools,
  boxTool,
}: PreviewProps & LinkProps) {
  // key: a different file starts again at its first step, page 1 and "fit"
  if (file.is_link) {
    return (
      <LinkPreview
        key={file.drive_id}
        file={file}
        windowButton={windowButton}
        goToTarget={goToTarget}
        beforeGoToTarget={beforeGoToTarget}
        zoomControl={zoomControl}
        extraTools={extraTools}
        boxTool={boxTool}
      />
    );
  }
  return (
    <Preview
      key={file.drive_id}
      file={file}
      windowButton={windowButton}
      zoomControl={zoomControl}
      extraTools={extraTools}
      boxTool={boxTool}
    />
  );
}
