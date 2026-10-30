/** Boxes on page 1 of a preview. The "Draw a box" tool (PDF pages and images, on page 1
 * only) lets the user drag a rectangle over the page; on release the lines of page 1 inside
 * it are listed with what the box can mean (see BoxPanel). The zones of the rule behind
 * the current suggestion are drawn faintly on the page, so it shows why the rule fired.
 *
 * Boxes are fractions of the rendered image (origin top left), so the zoom never matters. */
import { Layers, SquareDashed } from "lucide-react";
import { type ReactNode, useMemo, useRef, useState } from "react";
import {
  type Area,
  errorText,
  type FileSuggestions,
  type PageBox,
  type RuleIn,
  useAreaPicture,
  useAreasFor,
  useRuleExplain,
  usePage1,
  usePage1Lines,
  useFileSuggestions,
  useRules,
} from "../../api/client";
import { useStyle } from "../../appearance";
import { isShortcut, useKeydown } from "../../keyboard";
import { visible, withoutNoise } from "../../text";
import { IconButton } from "../ui/IconButton";
import { AreaChange } from "./AreaChange";
import { AreaLayer, percent } from "./AreaLayer";
import { BoxPanel, type KeptBox } from "./BoxPanel";
import { DocumentAddressArea } from "./DocumentAddressArea";
import { useDragBox } from "./useDragBox";

/** Turns the tool on for a preview. ``suggestion``: what the file's current suggestion
 * came from, when the owner already has it (the Inbox card); otherwise it is asked for. */
export type BoxTool = {
  /** The rule being tested (the rule sheet's test result): its areas on this document are
   * drawn instead of the suggestion's, with the best place and score of a picture area. */
  testRule?: RuleIn;
  suggestion?: Pick<FileSuggestions, "name_source" | "folder_source"> &
    Partial<Pick<FileSuggestions, "areas" | "person_line">> & { person?: string | null };
};

/** The id of the rule that gave the suggestion its folder or name, if one did. */
export function ruleIdOf(s: Pick<FileSuggestions, "name_source" | "folder_source">): string | null {
  const source = [s.folder_source, s.name_source].find((x) => x?.startsWith("rule:"));
  return source ? source.slice("rule:".length) : null;
}

/** What the tool gives a preview: its toolbar button, the layer around the page image and
 * the panel with what was found. */
export type Boxes = {
  button: ReactNode;
  /** The hint on how to draw (or why not), apart from ``panel`` when it was asked for
   * (``splitNote``: the New document bar shows it beside the button). Else it is null and
   * ``panel`` starts with it. */
  note: ReactNode;
  around: (image: ReactNode) => ReactNode;
  panel: ReactNode;
};

const NONE: Boxes = { button: null, note: null, around: (image) => image, panel: null };

/** Gives ``children`` the tool of a preview. ``pageOne``: the preview shows page 1 (images
 * always do); the tool is hidden on other pages. Without ``tool`` it does nothing and asks
 * for nothing (previews also render outside a query client). */
export function WithBoxes({
  driveId,
  tool,
  pageOne,
  splitNote = false,
  children,
}: {
  driveId: string;
  tool: BoxTool | undefined;
  pageOne: boolean;
  splitNote?: boolean;
  children: (boxes: Boxes) => ReactNode;
}) {
  if (tool === undefined) return children(NONE);
  return <ActiveBoxes driveId={driveId} tool={tool} pageOne={pageOne} splitNote={splitNote}>{children}</ActiveBoxes>;
}

function ActiveBoxes({
  driveId,
  tool,
  pageOne,
  splitNote,
  children,
}: {
  driveId: string;
  tool: BoxTool;
  pageOne: boolean;
  splitNote: boolean;
  children: (boxes: Boxes) => ReactNode;
}) {
  return children(useBoxTool(driveId, tool, pageOne, splitNote));
}

function useBoxTool(driveId: string, tool: BoxTool, pageOne: boolean, splitNote: boolean): Boxes {
  const active = pageOne;
  const [on, setOn] = useState(false);
  const [look] = useStyle();
  const isNew = look === "new";
  // every box drawn is kept (numbered) until it is removed or the panel is closed
  const [boxes, setBoxes] = useState<KeptBox[]>([]);
  const nextId = useRef(1);
  const page = usePage1(driveId, active && on);
  const readLines = usePage1Lines();
  const cut = useAreaPicture();
  const own = useFileSuggestions(driveId, active && tool.suggestion === undefined);
  const suggestion = tool.suggestion ?? own.data;
  const ruleId = suggestion ? ruleIdOf(suggestion) : null;
  const rules = useRules(active);
  const rule = ruleId ? (rules.data?.rules.find((r) => r.id === ruleId) ?? null) : null;
  // the areas behind the suggestion: shown unless the owner turned them off
  // the rule being tested, or else the suggestion's areas plus, for diagnosis, the areas of
  // rules with a picture area that did not match (their best place and score here, or why
  // no score could be worked out)
  const tested = useAreasFor(tool.testRule, driveId, active && tool.testRule !== undefined);
  // only an archive with a picture rule asks (the explanation is a look at every rule)
  const hasPictureRules = rules.data?.rules.some((r) => r.when.zones.some((z) => z.image)) ?? false;
  const explained = useRuleExplain(driveId, active && tool.testRule === undefined && hasPictureRules);
  const areas = useMemo(() => {
    if (tool.testRule !== undefined) return tested.data?.areas ?? [];
    const own = suggestion?.areas ?? [];
    const seen = new Set(own.map((a) => `${a.rule_id}:${a.index}`));
    const more = (explained.data ?? [])
      .filter((x) => !x.matched && x.areas.some((a) => a.kind === "image"))
      .flatMap((x) => x.areas)
      .filter((a) => !seen.has(`${a.rule_id}:${a.index}`));
    return [...own, ...more];
  }, [tool.testRule, tested.data, suggestion?.areas, explained.data]);
  const personLine = suggestion?.person_line ?? null;
  const [areasOn, setAreasOn] = useState<boolean | null>(null);
  const showAreas = areasOn ?? areas.length > 0;
  // an area the owner moved or resized: the rule sheet (or the address area) opens for it
  const [changed, setChanged] = useState<{ area: Area; box: PageBox } | null>(null);

  const unavailable = page.data?.unavailable ?? null;
  const ready = on && page.data?.read === true;
  const change = (id: number, over: Partial<KeptBox>) =>
    setBoxes((all) => all.map((k) => (k.id === id ? { ...k, ...over } : k)));
  const close = () => {
    setBoxes([]);
    cancelDrag();
  };
  const toggle = () => {
    close();
    setOn(!on);
  };
  // the picture of a box is cut once; a cut that fails puts the box back on its words
  const cutPicture = (id: number, box: PageBox) =>
    cut.mutateAsync({ driveId, box }).then(
      (got) => change(id, { picture: got.png }),
      (e) => change(id, { mode: "words", problem: errorText(e) }),
    );
  const addBox = (drawn: PageBox) => {
    const id = nextId.current++;
    setBoxes((all) => [...all, { id, box: drawn, lines: null, mode: "words" }]);
    // mutateAsync: several boxes can be read at once, and each reply belongs to its box
    readLines.mutateAsync({ driveId, box: drawn }).then(
      (found) => {
        const lines = found.lines.map((l) => l.text);
        // a box without text can only be matched by its picture: start there (the owner
        // can still switch back to Words)
        const empty = lines.map(withoutNoise).every((l) => l === "");
        change(id, empty ? { lines, mode: "picture" } : { lines });
        if (empty) void cutPicture(id, drawn);
      },
      (e) => change(id, { lines: [], problem: errorText(e) }),
    );
  };
  const setMode = (index: number, mode: "words" | "picture") => {
    const k = boxes[index];
    if (!k) return;
    change(k.id, { mode, problem: undefined });
    if (mode === "picture" && !k.picture) void cutPicture(k.id, k.box);
  };

  const { drawing, cancel: cancelDrag, surface } = useDragBox(addBox);

  // Esc: first the box being drawn, then the last box, then the tool.
  useKeydown((e) => {
    if (!active || !on || e.key !== "Escape" || !isShortcut(e)) return;
    e.preventDefault();
    if (drawing) cancelDrag();
    else if (boxes.length > 0) setBoxes((all) => all.slice(0, -1));
    else setOn(false);
  });

  if (!active) return NONE;

  const button = (
    <>
      {(areas.length > 0 || personLine !== null) && (
        <IconButton
          icon={<Layers />}
          label="Show areas"
          tip="Show the areas behind the suggestion, and the score of picture rules that did not match"
          pressed={showAreas}
          onClick={() => setAreasOn(!showAreas)}
        />
      )}
      <IconButton
        icon={<SquareDashed />}
        label="Draw a box"
        text={splitNote ? "Draw a box" : undefined}
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
        <span className="page-surface" data-testid="box-surface" {...surface} />
      )}
      {boxes.map((k, i) => (
        <span key={k.id} className="page-box page-box-kept" data-testid="kept-box" data-tone={i % 5} style={percent(k.box)}>
          <span className="page-box-number">{i + 1}</span>
        </span>
      ))}
      {drawing && <span className="page-box" data-testid="drawn-box" style={percent(drawing)} />}
    </span>
  );
  const note = !on ? null : unavailable !== null ? (
    <p className="hint box-note">{visible(unavailable)}</p>
  ) : page.data?.read !== true ? (
    <p className="busy box-note" role="status">
      {page.isError ? "Could not read page 1." : "Reading page 1…"}
    </p>
  ) : (
    <p className="hint box-note">
      {boxes.length > 0
        ? "Drag over page 1 to add the next box. Esc drops the last box."
        : "Drag over page 1 to draw a box. Esc cancels."}
    </p>
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
      {isNew && <DocumentAddressArea driveId={driveId} open={on || showAreas} />}
      {on && (
    <>
      {!splitNote && note}
      {boxes.length > 0 && (
        <BoxPanel
          driveId={driveId}
          boxes={boxes}
          rule={rule}
          onMode={setMode}
          onRemove={(i) => setBoxes((all) => all.filter((_, at) => at !== i))}
          onClose={close}
        />
      )}
    </>
      )}
    </>
  );
  return { button, note: splitNote ? note : null, around, panel };
}
