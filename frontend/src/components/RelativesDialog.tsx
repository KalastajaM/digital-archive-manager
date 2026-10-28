/** The Relatives dialog: the folder outline cut down to the folders that hold a relative,
 * with an arc from this file's row to each relative's row (thicker = more in common,
 * orange dashed = not filed yet). The "In common" strip lights up the files that share one
 * value. Hover or focus on a row shows exactly what it shares, in the side panel so the
 * card never covers the outline or the arcs; it stays on the last row pointed at, so the
 * mouse can travel to its buttons. The actions on the ticked files are the block's own
 * (``ActionBar``). Opened from the block's "Show connections". */
import { X } from "lucide-react";
import { type KeyboardEvent, useMemo, useRef, useState } from "react";
import { type Relative, useRelatives } from "../api/client";
import { plural } from "../format";
import { baseName, parentOf } from "../paths";
import { visible } from "../text";
import {
  ActionBar,
  type BlockFile,
  DismissedList,
  EMPTY_TEXT,
  fold,
  KIND_CLASS,
  KIND_LABEL,
  KIND_NAME,
  kindsOf,
  useNotRelated,
  useRelativeLook,
} from "./relativesShared";
import { AIMark, FindMoreButton, type Finder, FoundLine, isAIPick, useFindRelatives } from "./relativesAI";
import { IconButton } from "./ui/IconButton";
import { Sheet } from "./ui/Sheet";

/** Every row has this height, so an arc's end is just the row's number times it. */
export const ROW_H = 28;
/** The arcs' column: fixed, so there is never a horizontal scroll. */
const ARC_W = 120;
const MAX_BULGE = 150;
/** A folder with more relatives than this is folded to its heading and a count. */
export const FOLD_AT = 8;
const INDENT = 18;

type Row =
  | { t: "folder"; key: string; label: string; depth: number; count: number; foldable: boolean; open: boolean; inbox: boolean }
  | { t: "file"; r: Relative; depth: number; folder: string }
  | { t: "self"; depth: number };

type Group = { key: string; folder: string; items: Relative[]; self: boolean; inbox: boolean };

const collator = new Intl.Collator(undefined, { numeric: true, sensitivity: "base" });

/** The outline: only folders that hold a relative (and this file's own), nested by path. */
export function buildOutline(file: BlockFile, relatives: Relative[], expanded: ReadonlySet<string>): Row[] {
  const here = parentOf(file.path);
  const groups = new Map<string, Group>();
  const group = (folder: string) => {
    const key = fold(folder);
    let g = groups.get(key);
    if (!g) groups.set(key, (g = { key, folder, items: [], self: false, inbox: false }));
    return g;
  };
  group(here).self = true;
  for (const r of relatives) {
    const g = group(r.folder);
    g.items.push(r);
    if (r.in_inbox) g.inbox = true;
  }
  const ordered = [...groups.values()].sort(
    (a, b) => Number(a.inbox) - Number(b.inbox) || collator.compare(a.folder, b.folder),
  );
  const rows: Row[] = [];
  const emitted = new Set<string>();
  for (const g of ordered) {
    const segments = g.folder.split("/").filter(Boolean);
    const names = segments.length ? segments : ["Archive"];
    names.forEach((name, i) => {
      const path = fold(names.slice(0, i + 1).join("/"));
      const leaf = i === names.length - 1;
      if (emitted.has(path)) return;
      emitted.add(path);
      const foldable = leaf && g.items.length > FOLD_AT;
      rows.push({
        t: "folder",
        key: leaf ? g.key : path,
        label: leaf && g.inbox && names.length === 1 ? "Inbox" : name,
        depth: i,
        count: leaf ? g.items.length : 0,
        foldable,
        open: !foldable || expanded.has(g.key),
        inbox: leaf && g.inbox,
      });
    });
    const depth = names.length;
    if (g.self) rows.push({ t: "self", depth });
    const leafRow = rows.find((r) => r.t === "folder" && r.key === g.key);
    if (leafRow?.t === "folder" && leafRow.open) for (const r of g.items) rows.push({ t: "file", r, depth, folder: g.key });
  }
  return rows;
}

const strokeOf = (score: number) => Math.min(4.5, Math.max(1.5, 1 + score * 0.4));
const arcPath = (y0: number, y1: number) => {
  const bulge = Math.min(MAX_BULGE, 24 + Math.abs(y1 - y0) * 0.6);
  return `M0 ${y0} C${bulge} ${y0} ${bulge} ${y1} 0 ${y1}`;
};

type Common = { kind: Relative["links"][number]["kind"]; value: string; count: number };
const sharesValue = (r: Relative, c: Common) => r.links.some((l) => l.kind === c.kind && l.value === c.value);

/** ``finder``: the block's AI search, so what it found shows here too; without it the
 * dialog runs its own. */
export function RelativesDialog({
  file,
  onClose,
  finder: given,
}: {
  file: BlockFile;
  onClose: () => void;
  finder?: Finder;
}) {
  const query = useRelatives(file.drive_id);
  const data = query.data;
  const regular = useMemo(() => data?.relatives ?? [], [data]);
  const own = useFindRelatives(file, regular);
  const finder = given ?? own;
  // the AI's picks sit in the outline beside the regular relatives
  const relatives = useMemo<Relative[]>(() => [...regular, ...finder.picks], [regular, finder.picks]);
  const [selected, setSelected] = useState<ReadonlySet<string>>(new Set());
  const [expanded, setExpanded] = useState<ReadonlySet<string>>(new Set());
  const [lit, setLit] = useState<Common | null>(null);
  // the row whose card shows: the last one hovered or focused (it stays when the pointer
  // leaves, so the card's buttons can be reached)
  const [carded, setCarded] = useState<string | null>(null);
  const [showHidden, setShowHidden] = useState(false);
  const mapRef = useRef<HTMLUListElement>(null);

  const rows = useMemo(() => buildOutline(file, relatives, expanded), [file, relatives, expanded]);
  const outline = rows.flatMap((r) => (r.t === "file" ? [r.r] : []));
  // folded folders keep their relatives in the stepping of Quick Look
  const lookList = useMemo(() => {
    const byFolder = new Map<string, Relative[]>();
    for (const r of relatives) byFolder.set(fold(r.folder), [...(byFolder.get(fold(r.folder)) ?? []), r]);
    const seen = new Set<string>();
    const list: Relative[] = [];
    for (const row of rows) {
      const key = row.t === "file" ? row.folder : row.t === "folder" ? row.key : null;
      if (key === null || seen.has(key)) continue;
      seen.add(key);
      list.push(...(byFolder.get(key) ?? []));
    }
    return list;
  }, [rows, relatives]);

  const notRelated = useNotRelated(file, (r) => {
    finder.drop(r.drive_id);
    setSelected((prev) => {
      const next = new Set(prev);
      next.delete(r.drive_id);
      return next;
    });
  });
  const look = useRelativeLook(file, lookList, notRelated);

  const here = parentOf(file.path);
  const ticked = relatives.filter((r) => selected.has(r.drive_id));
  const toggle = (id: string) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (!next.delete(id)) next.add(id);
      return next;
    });

  // arcs: from this file's row to each relative's row (to its folder's row when folded away)
  const rowY = (i: number) => i * ROW_H + ROW_H / 2;
  const selfAt = rows.findIndex((r) => r.t === "self");
  const arcs = useMemo(() => {
    const out = new Map<number, { key: string; ids: string[]; score: number; inbox: boolean; folded: boolean; rels: Relative[] }>();
    const rowIndexOf = (r: Relative) => {
      const own = rows.findIndex((x) => x.t === "file" && x.r.drive_id === r.drive_id);
      if (own >= 0) return { i: own, folded: false };
      return { i: rows.findIndex((x) => x.t === "folder" && x.key === fold(r.folder)), folded: true };
    };
    for (const r of relatives) {
      const { i, folded } = rowIndexOf(r);
      if (i < 0) continue;
      const cur = out.get(i) ?? { key: folded ? `folder:${fold(r.folder)}` : r.drive_id, ids: [], score: 0, inbox: true, folded, rels: [] };
      cur.ids.push(r.drive_id);
      cur.rels.push(r);
      cur.score = Math.max(cur.score, r.score);
      cur.inbox = cur.inbox && r.in_inbox;
      out.set(i, cur);
    }
    return [...out].map(([i, a]) => ({ i, ...a }));
  }, [rows, relatives]);

  const quick = [
    { label: "2+ links", ids: regular.filter((r) => kindsOf(r).length >= 2).map((r) => r.drive_id) },
    {
      label: "Same sender",
      ids: regular.filter((r) => r.links.some((l) => l.kind === "sender")).map((r) => r.drive_id),
    },
    { label: "Outside this folder", ids: regular.filter((r) => fold(r.folder) !== fold(here)).map((r) => r.drive_id) },
  ];

  const card = relatives.find((r) => r.drive_id === carded) ?? null;
  const rowEls = () => [...(mapRef.current?.querySelectorAll<HTMLElement>("[data-rel]") ?? [])];
  const onKeys = (e: KeyboardEvent<HTMLDialogElement>) => {
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    const li = e.target instanceof Element ? (e.target.closest("[data-rel]") as HTMLElement | null) : null;
    if (!li) {
      if (e.target === e.currentTarget && (e.key === "ArrowDown" || e.key === "ArrowUp")) {
        const els = rowEls();
        (e.key === "ArrowDown" ? els[0] : els[els.length - 1])?.focus();
        e.preventDefault();
      }
      return;
    }
    const id = li.dataset.rel as string;
    const inControl = e.target instanceof Element && e.target !== li && e.target.closest("button, input, a");
    const els = rowEls();
    const at = els.indexOf(li);
    const key = e.key.toLowerCase();
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      els[at + (e.key === "ArrowDown" ? 1 : -1)]?.focus();
    } else if (e.key === " " && !inControl) {
      look.open(id);
    } else if (key === "x" && !(e.target instanceof HTMLInputElement && e.target.type !== "checkbox")) {
      toggle(id);
    } else if (key === "n") {
      const r = relatives.find((x) => x.drive_id === id);
      if (!r) return;
      (els[at + 1] ?? els[at - 1])?.focus();
      notRelated(r);
    } else return;
    e.preventDefault();
  };

  const name = visible(file.name ?? baseName(file.path));
  return (
    <>
      <Sheet open title="Relatives" className="relatives-dialog" onClose={onClose} onKeyDown={onKeys}>
        <div className="rel-head">
          <span className="rel-file trunc" title={name}>
            {name}
          </span>
          <IconButton icon={<X size={14} />} label="Close" shortcut="Esc" onClick={onClose} />
        </div>
        {query.isError ? (
          <p className="hint">Relatives could not be loaded.</p>
        ) : !data ? (
          <p className="hint">Looking for relatives…</p>
        ) : relatives.length === 0 ? (
          <div className="rel-empty">
            <p className="hint">{EMPTY_TEXT}</p>
            <FindMoreButton finder={finder} />
            <FoundLine finder={finder} />
          </div>
        ) : (
          <>
            {data.common.length > 0 && (
              <div className="rel-strip" role="group" aria-label="In common">
                <span className="rel-strip-label">In common</span>
                {data.common.map((c) => {
                  const on = lit?.kind === c.kind && lit.value === c.value;
                  return (
                    <button
                      key={`${c.kind}:${c.value}`}
                      type="button"
                      className={`rel-chip ${KIND_CLASS[c.kind]}`}
                      aria-pressed={on}
                      onClick={() => setLit(on ? null : c)}
                    >
                      {KIND_NAME[c.kind]}: {visible(c.value)} <span className="rel-chip-count">{c.count}</span>
                    </button>
                  );
                })}
              </div>
            )}
            <div className="rel-layout">
              <div className="rel-scroll">
                <div className="rel-map" style={{ height: rows.length * ROW_H }}>
                  <ul className="rel-rows" ref={mapRef} aria-label="Folders with relatives">
                    {rows.map((row, i) => {
                      if (row.t === "folder") {
                        const indent = { paddingLeft: 8 + row.depth * INDENT };
                        const text = (
                          <>
                            <span className="rel-folder-name trunc">{row.label}</span>
                            {row.count > 0 && <span className="rel-folder-count">{plural(row.count, "file")}</span>}
                          </>
                        );
                        return (
                          <li key={`f-${row.key}-${i}`} className={`rel-folder${row.inbox ? " inbox" : ""}`} style={indent}>
                            {row.foldable ? (
                              <button
                                type="button"
                                className="rel-fold"
                                aria-expanded={row.open}
                                onClick={() =>
                                  setExpanded((prev) => {
                                    const next = new Set(prev);
                                    if (!next.delete(row.key)) next.add(row.key);
                                    return next;
                                  })
                                }
                              >
                                {text}
                              </button>
                            ) : (
                              text
                            )}
                          </li>
                        );
                      }
                      if (row.t === "self") {
                        return (
                          <li key="self" className="rel-row self" style={{ paddingLeft: 8 + row.depth * INDENT }}>
                            <span className="rel-name trunc">{name}</span>
                            <span className="rel-self-label">this file</span>
                          </li>
                        );
                      }
                      const r = row.r;
                      const rname = visible(r.name);
                      const pick = isAIPick(r) ? r : null;
                      const faded = lit !== null && !sharesValue(r, lit);
                      const isCarded = carded === r.drive_id;
                      return (
                        <li
                          key={r.drive_id}
                          data-rel={r.drive_id}
                          tabIndex={r.drive_id === outline[0]?.drive_id ? 0 : -1}
                          aria-label={`${rname}, ${pick ? `found by AI: ${visible(pick.reason)}` : kindsOf(r).map((k) => KIND_LABEL[k]).join(", ")}`}
                          className={`rel-row${selected.has(r.drive_id) ? " checked" : ""}${pick ? " ai" : ""}${r.in_inbox ? " unfiled" : ""}${faded ? " faded" : ""}${lit && !faded ? " lit" : ""}${isCarded ? " carded" : ""}`}
                          style={{ paddingLeft: 8 + row.depth * INDENT }}
                          onMouseEnter={() => setCarded(r.drive_id)}
                          onFocus={() => setCarded(r.drive_id)}
                        >
                          <input
                            type="checkbox"
                            tabIndex={-1}
                            checked={selected.has(r.drive_id)}
                            onChange={() => toggle(r.drive_id)}
                            aria-label={`Select ${rname}`}
                          />
                          <span className="rel-name trunc">{rname}</span>
                          {pick ? (
                            <span className="rel-kinds rel-ai-line">
                              <AIMark pick={pick} />
                              <span className="trunc" title={visible(pick.reason)}>
                                {visible(pick.reason)}
                              </span>
                            </span>
                          ) : (
                            <span className="rel-kinds">
                              {kindsOf(r).map((k) => (
                                <span key={k} className={`tag ${KIND_CLASS[k]}`}>
                                  {KIND_LABEL[k]}
                                </span>
                              ))}
                              {r.same_month && <span className="tag tag-grey">+ same month</span>}
                            </span>
                          )}
                        </li>
                      );
                    })}
                  </ul>
                  <svg className="rel-arcs" width={ARC_W} height={rows.length * ROW_H} aria-hidden="true">
                    {selfAt >= 0 &&
                      arcs.map((a) => {
                        const faded = lit !== null && !a.rels.some((r) => sharesValue(r, lit));
                        const ai = a.rels.every(isAIPick);
                        const on = carded !== null && a.ids.includes(carded);
                        const cls = `rel-arc${a.inbox ? " inbox" : ""}${ai ? " ai" : ""}${faded ? " faded" : ""}${on ? " on" : ""}`;
                        return (
                          <g key={a.key} className={cls} data-target={a.key}>
                            <path
                              className="rel-arc-line"
                              d={arcPath(rowY(selfAt), rowY(a.i))}
                              strokeWidth={strokeOf(a.score)}
                            />
                            <circle className="rel-dot" cx={0} cy={rowY(a.i)} r={3} />
                          </g>
                        );
                      })}
                    {selfAt >= 0 && <circle className="rel-dot self" cx={0} cy={rowY(selfAt)} r={5} />}
                  </svg>
                </div>
              </div>
              <aside className="rel-side" aria-label="Actions">
                <div className="rel-side-block rel-card-slot">
                  <span className="rel-side-label">In common with this file</span>
                  {card ? (
                    <RelativeCard relative={card} onLook={() => look.open(card.drive_id)} onNotRelated={() => notRelated(card)} />
                  ) : (
                    <p className="hint">Point at a file, or move to it with the arrow keys, to see exactly what it shares.</p>
                  )}
                </div>
                <div className="rel-side-block">
                  <span className="rel-side-label">Selected</span>
                  {ticked.length > 0 ? (
                    <ActionBar file={file} ticked={ticked} onClear={() => setSelected(new Set())} />
                  ) : (
                    <p className="hint">Tick files to tag, collect, move or link them together with this file.</p>
                  )}
                </div>
                <div className="rel-side-block">
                  <span className="rel-side-label">Select</span>
                  <div className="rel-quick">
                    {quick.map((q) => (
                      <button
                        key={q.label}
                        type="button"
                        className="rel-quick-button"
                        disabled={q.ids.length === 0}
                        title={q.ids.length === 0 ? "No relative matches" : `${plural(q.ids.length, "file")}`}
                        onClick={() => setSelected(new Set(q.ids))}
                      >
                        {q.label}
                      </button>
                    ))}
                  </div>
                </div>
                {(finder.available || finder.answered) && (
                  <div className="rel-side-block">
                    <span className="rel-side-label">AI</span>
                    <FindMoreButton finder={finder} />
                    <FoundLine finder={finder} />
                  </div>
                )}
                {data.hidden > 0 && (
                  <div className="relatives-hidden">
                    <button
                      type="button"
                      className="link-button"
                      aria-expanded={showHidden}
                      onClick={() => setShowHidden((v) => !v)}
                    >
                      {data.hidden} marked not related
                    </button>
                    {showHidden && <DismissedList driveId={file.drive_id} />}
                  </div>
                )}
              </aside>
            </div>
            <div className="rel-legend">
              <span>
                <svg width="24" height="8" aria-hidden="true">
                  <line className="rel-arc-line" x1="0" y1="4" x2="24" y2="4" strokeWidth="4" />
                </svg>
                thicker = more in common
              </span>
              <span>
                <svg width="24" height="8" aria-hidden="true">
                  <line className="rel-arc-line inbox" x1="0" y1="4" x2="24" y2="4" strokeWidth="2" />
                </svg>
                dashed = not filed yet
              </span>
              <span className="rel-keys">↑↓ move · Space Quick Look · X tick · N not related</span>
            </div>
          </>
        )}
      </Sheet>
      {look.view}
      {given ? null : own.sheet}
    </>
  );
}

/** What one relative shares with this file: each value exactly, the AI's reason for a
 * pick, and Quick Look and Not related. */
function RelativeCard({ relative: r, onLook, onNotRelated }: { relative: Relative; onLook: () => void; onNotRelated: () => void }) {
  const rname = visible(r.name);
  const pick = isAIPick(r) ? r : null;
  return (
    <div className="rel-card" role="group" aria-label={`What ${rname} shares`}>
      <span className="rel-card-name" title={rname}>
        {rname}
      </span>
      {pick && (
        <p className="rel-card-reason">
          <AIMark pick={pick} /> {visible(pick.reason)}
        </p>
      )}
      <dl className="rel-card-list">
        {r.links.map((l) => (
          <div key={`${l.kind}:${l.value}`}>
            <dt>{KIND_NAME[l.kind]}</dt>
            <dd>{visible(l.value)}</dd>
          </div>
        ))}
      </dl>
      {r.same_month && <span className="rel-card-note">+ same month</span>}
      <span className="rel-card-actions">
        <button type="button" onClick={onLook}>
          Quick look <kbd>Space</kbd>
        </button>
        <button type="button" className="link-button" onClick={onNotRelated}>
          Not related
        </button>
      </span>
    </div>
  );
}
