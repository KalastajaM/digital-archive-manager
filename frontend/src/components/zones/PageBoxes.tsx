/** Boxes on page 1 of a preview. The "Draw a box" tool (PDF pages and images, on page 1
 * only) lets the user drag a rectangle over the page; on release the lines of page 1 inside
 * it are listed with what the box can mean (see BoxPanel). The zones of the rule behind
 * the current suggestion are drawn faintly on the page, so it shows why the rule fired.
 *
 * Boxes are fractions of the rendered image (origin top left), so the zoom never matters. */
import { Layers, SquareDashed } from "lucide-react";
import { type PointerEvent, type ReactNode, useState } from "react";
import {
  type Area,
  type FileSuggestions,
  type PageBox,
  usePage1,
  usePage1Lines,
  useFileSuggestions,
  useRules,
} from "../../api/client";
import { isShortcut, useKeydown } from "../../keyboard";
import { visible } from "../../text";
import { IconButton } from "../ui/IconButton";
import { AreaChange } from "./AreaChange";
import { AreaLayer, percent } from "./AreaLayer";
import { BoxPanel, type KeptBox } from "./BoxPanel";

/** Turns the tool on for a preview. ``suggestion``: what the file's current suggestion
 * came from, when the owner already has it (the Inbox card); otherwise it is asked for. */
export type BoxTool = {
  suggestion?: Pick<FileSuggestions, "name_source" | "folder_source"> &
    Partial<Pick<FileSuggestions, "areas" | "person_line">> & { person?: string | null };
};

type Drag = { x0: number; y0: number; x1: number; y1: number };

/** Smallest side of a box (a share of the page): a click or a twitch draws nothing. */
const MIN_SIDE = 0.01;
const clamp = (n: number) => Math.min(1, Math.max(0, n));

/** The id of the rule that gave the suggestion its folder or name, if one did. */
export function ruleIdOf(s: Pick<FileSuggestions, "name_source" | "folder_source">): string | null {
  const source = [s.folder_source, s.name_source].find((x) => x?.startsWith("rule:"));
  return source ? source.slice("rule:".length) : null;
}

/** What the tool gives a preview: its toolbar button, the layer around the page image and
 * the panel with what was found. */
export type Boxes = { button: ReactNode; around: (image: ReactNode) => ReactNode; panel: ReactNode };

const NONE: Boxes = { button: null, around: (image) => image, panel: null };

/** Gives ``children`` the tool of a preview. ``pageOne``: the preview shows page 1 (images
 * always do); the tool is hidden on other pages. Without ``tool`` it does nothing and asks
 * for nothing (previews also render outside a query client). */
export function WithBoxes({
  driveId,
  tool,
  pageOne,
  children,
}: {
  driveId: string;
  tool: BoxTool | undefined;
  pageOne: boolean;
  children: (boxes: Boxes) => ReactNode;
}) {
  if (tool === undefined) return children(NONE);
  return <ActiveBoxes driveId={driveId} tool={tool} pageOne={pageOne}>{children}</ActiveBoxes>;
}

function ActiveBoxes({
  driveId,
  tool,
  pageOne,
  children,
}: {
  driveId: string;
  tool: BoxTool;
  pageOne: boolean;
  children: (boxes: Boxes) => ReactNode;
}) {
  return children(useBoxTool(driveId, tool, pageOne));
}

function useBoxTool(driveId: string, tool: BoxTool, pageOne: boolean): Boxes {
  const active = pageOne;
  const [on, setOn] = useState(false);
  const [drag, setDrag] = useState<Drag | null>(null);
  const [box, setBox] = useState<PageBox | null>(null);
  // boxes kept with "Add another box": the rule being made needs all of them
  const [kept, setKept] = useState<KeptBox[]>([]);
  const page = usePage1(driveId, active && on);
  const lines = usePage1Lines();
  const own = useFileSuggestions(driveId, active && tool.suggestion === undefined);
  const suggestion = tool.suggestion ?? own.data;
  const ruleId = suggestion ? ruleIdOf(suggestion) : null;
  const rules = useRules(active && ruleId !== null);
  const rule = ruleId ? (rules.data?.rules.find((r) => r.id === ruleId) ?? null) : null;
  // the areas behind the suggestion: shown unless the owner turned them off
  const areas = suggestion?.areas ?? [];
  const personLine = suggestion?.person_line ?? null;
  const [areasOn, setAreasOn] = useState<boolean | null>(null);
  const showAreas = areasOn ?? areas.length > 0;
  // an area the owner moved or resized: the rule sheet (or the address area) opens for it
  const [changed, setChanged] = useState<{ area: Area; box: PageBox } | null>(null);

  const unavailable = page.data?.unavailable ?? null;
  const ready = on && page.data?.read === true;
  const dropBox = () => {
    setBox(null);
    setDrag(null);
    lines.reset();
  };
  const close = () => {
    dropBox();
    setKept([]);
  };
  const addAnother = () => {
    if (!box) return;
    setKept((all) => [...all, { box, lines: (lines.data?.lines ?? []).map((l) => l.text) }]);
    dropBox();
  };
  const keepPicture = (png: string) => {
    if (!box) return;
    setKept((all) => [...all, { box, lines: [], picture: png }]);
    dropBox();
  };
  const toggle = () => {
    close();
    setOn(!on);
  };

  // Esc: first the box being drawn, then the box just drawn, then the kept boxes, then the tool.
  useKeydown((e) => {
    if (!active || !on || e.key !== "Escape" || !isShortcut(e)) return;
    e.preventDefault();
    if (drag) setDrag(null);
    else if (box) dropBox();
    else if (kept.length > 0) close();
    else setOn(false);
  });

  const start = (e: PointerEvent<HTMLElement>) => {
    if (e.button !== 0) return;
    dropBox();
    const at = point(e);
    if (!at) return;
    e.currentTarget.setPointerCapture?.(e.pointerId);
    setDrag({ x0: at[0], y0: at[1], x1: at[0], y1: at[1] });
  };
  const move = (e: PointerEvent<HTMLElement>) => {
    const at = point(e);
    if (drag && at) setDrag({ ...drag, x1: at[0], y1: at[1] });
  };
  const end = (e: PointerEvent<HTMLElement>) => {
    if (!drag) return;
    const at = point(e) ?? [drag.x1, drag.y1];
    const drawn: PageBox = [
      Math.min(drag.x0, at[0]),
      Math.min(drag.y0, at[1]),
      Math.max(drag.x0, at[0]),
      Math.max(drag.y0, at[1]),
    ];
    setDrag(null);
    if (drawn[2] - drawn[0] < MIN_SIDE || drawn[3] - drawn[1] < MIN_SIDE) return;
    setBox(drawn);
    lines.mutate({ driveId, box: drawn });
  };

  if (!active) return NONE;

  const button = (
    <>
      {(areas.length > 0 || personLine !== null) && (
        <IconButton
          icon={<Layers />}
          label="Show areas"
          tip="Show the areas of page 1 behind the suggestion"
          pressed={showAreas}
          onClick={() => setAreasOn(!showAreas)}
        />
      )}
      <IconButton
        icon={<SquareDashed />}
        label="Draw a box"
        tip="Draw a box on page 1 to make a rule or set the address area"
        pressed={on}
        disabled={unavailable !== null}
        disabledReason={unavailable ?? undefined}
        onClick={toggle}
      />
    </>
  );
  const around = (image: ReactNode) => (
    <span className="page-layer">
      {image}
      {showAreas && (
        <AreaLayer
          areas={areas}
          person={suggestion?.person ?? null}
          personLine={personLine}
          onChange={on ? undefined : (area, box) => setChanged({ area, box })}
        />
      )}
      {ready && (
        <span
          className="page-surface"
          data-testid="box-surface"
          onMouseDown={(e) => e.stopPropagation()} // the frame's own pan stays off while drawing
          onPointerDown={start}
          onPointerMove={move}
          onPointerUp={end}
          onPointerCancel={() => setDrag(null)}
        />
      )}
      {kept.map((k, i) => (
        <span key={`${i}-${k.box.join(",")}`} className="page-box page-box-kept" data-testid="kept-box" style={percent(k.box)}>
          <span className="page-box-number">{i + 1}</span>
        </span>
      ))}
      {(drag ?? box) && (
        <span
          className="page-box"
          data-testid="drawn-box"
          style={percent(
            drag ? [Math.min(drag.x0, drag.x1), Math.min(drag.y0, drag.y1), Math.max(drag.x0, drag.x1), Math.max(drag.y0, drag.y1)] : (box as PageBox),
          )}
        />
      )}
    </span>
  );
  const panel = (
    <>
      {changed && (
        <AreaChange
          key={`${changed.area.kind}:${changed.area.rule_id}:${changed.area.index}:${changed.box.join(",")}`}
          driveId={driveId}
          area={changed.area}
          box={changed.box}
          onClose={() => setChanged(null)}
        />
      )}
      {on && (
    <>
      {unavailable !== null ? (
        <p className="hint box-note">{visible(unavailable)}</p>
      ) : page.data?.read !== true ? (
        <p className="busy box-note" role="status">
          {page.isError ? "Could not read page 1." : "Reading page 1…"}
        </p>
      ) : (
        !box && <p className="hint box-note">{kept.length > 0 ? "Drag over page 1 to draw the next box. Esc cancels." : "Drag over page 1 to draw a box. Esc cancels."}</p>
      )}
      {(box || kept.length > 0) && (
        <BoxPanel
          driveId={driveId}
          box={box}
          kept={kept}
          onAddAnother={addAnother}
          onKeepPicture={keepPicture}
          onRemoveKept={(i) => setKept((all) => all.filter((_, at) => at !== i))}
          found={lines.data}
          pending={lines.isPending}
          error={lines.isError ? lines.error : null}
          rule={rule}
          onClose={close}
        />
      )}
    </>
      )}
    </>
  );
  return { button, around, panel };
}

/** A pointer's place on the layer under it, as fractions of it (null: it has no size). */
function point(e: PointerEvent<HTMLElement>): [number, number] | null {
  const r = e.currentTarget.getBoundingClientRect();
  if (r.width <= 0 || r.height <= 0) return null;
  return [clamp((e.clientX - r.left) / r.width), clamp((e.clientY - r.top) / r.height)];
}
