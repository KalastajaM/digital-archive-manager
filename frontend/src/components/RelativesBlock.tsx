/** Relatives: the files a document belongs with, in the details panel.
 *
 * The server ranks them (``GET /api/files/{id}/relatives``) and says why: each shares a
 * folder, sender, tag, collection, IBAN, reference or person with this file. Tick some to
 * act on them together with this file: tag, add to a collection, move, or link. Every
 * change shows what it will do first and can be undone, through the flows the rest of the
 * app uses. "Not related" takes a file out of the list for good (Show again brings it back). */
import { Eye, EyeOff } from "lucide-react";
import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { errorText, type Relative, useRelatives } from "../api/client";
import { visible } from "../text";
import { Collapsible } from "./Collapsible";
import { browseTo, ShowInBrowse } from "./maintenance/ShowInBrowse";
import {
  type BlockFile,
  DismissedList,
  EMPTY_TEXT,
  KIND_CLASS,
  KIND_LABEL,
  KIND_PHRASE,
  kindsOf,
  linkTip,
  useNotRelated,
  useRelativeActions,
  useRelativeLook,
} from "./relativesShared";
import type { MenuEntry } from "./ui/Menu";
import { useContextMenu } from "./ui/useContextMenu";
import { RelativesDialog } from "./RelativesDialog";
import { AIMark, type AIPick, FindMoreButton, type Finder, FoundLine, isAIPick, useFindRelatives } from "./relativesAI";
import { baseName } from "../paths";
import { IconButton } from "./ui/IconButton";

/** How many relatives show before "N more". */
export const SHOWN = 4;

export { EMPTY_TEXT };

export function RelativesBlock({ file, compact = false }: { file: BlockFile; /** A narrow panel: folded until opened. */ compact?: boolean }) {
  const query = useRelatives(file.drive_id);
  const data = query.data;
  const [map, setMap] = useState(false);
  const regular = useMemo(() => data?.relatives ?? [], [data]);
  const finder = useFindRelatives(file, regular);
  return (
    <>
    <Collapsible
      name="relatives"
      title="Relatives"
      className="relatives"
      foldedByDefault={compact}
      aside={
        data && data.total > 0 ? (
          <>
            <span className="relatives-count">{data.total}</span>
            <button type="button" className="link-button relatives-connections" onClick={() => setMap(true)}>
              Show connections
            </button>
          </>
        ) : undefined
      }
    >
      {query.isError ? (
        <p className="hint">Relatives could not be loaded: {visible(errorText(query.error))}</p>
      ) : !data ? (
        <p className="hint">Looking for relatives…</p>
      ) : (
        <RelativesList key={file.drive_id} file={file} relatives={data.relatives} hidden={data.hidden} finder={finder} />
      )}
    </Collapsible>
    {finder.sheet}
    {map && <RelativesDialog file={file} onClose={() => setMap(false)} finder={finder} />}
    </>
  );
}

function RelativesList({
  file,
  relatives,
  hidden,
  finder,
}: {
  file: BlockFile;
  relatives: Relative[];
  hidden: number;
  finder: Finder;
}) {
  const [selected, setSelected] = useState<ReadonlySet<string>>(new Set());
  const [showAll, setShowAll] = useState(false);
  const [showHidden, setShowHidden] = useState(false);

  // files still in the Inbox come first: they are the ones that may need filing
  const ordered = [...relatives.filter((r) => r.in_inbox), ...relatives.filter((r) => !r.in_inbox)];
  const shown = showAll ? ordered : ordered.slice(0, SHOWN);
  const more = ordered.length - shown.length;
  const moreAllSingle = ordered.slice(SHOWN).every((r) => r.links.length === 1);
  const picks = finder.picks;
  const everyone: Relative[] = [...ordered, ...picks];
  const ticked = everyone.filter((r) => selected.has(r.drive_id));

  const toggle = (id: string) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (!next.delete(id)) next.add(id);
      return next;
    });

  const notRelated = useNotRelated(file, (r) => {
    finder.drop(r.drive_id);
    setSelected((prev) => {
      const next = new Set(prev);
      next.delete(r.drive_id);
      return next;
    });
  });
  const look = useRelativeLook(file, everyone, notRelated);
  const clear = () => setSelected(new Set());
  const actions = useRelativeActions({ file, ticked, onClear: clear });
  // a row's right-click: on a ticked row it acts on all ticked; another row is ticked alone first
  const menu = useContextMenu<string>();
  const navigate = useNavigate();
  const onMenu = (r: Relative) => (e: React.MouseEvent) => {
    if (!selected.has(r.drive_id)) setSelected(new Set([r.drive_id]));
    menu.open(r.drive_id, e);
  };
  const menuFor = (id: string) => {
    const r = everyone.find((x) => x.drive_id === id);
    if (!r) return null;
    const entries: MenuEntry[] = [
      // several ticked: only what acts on all of them (the one-file looks drop out)
      ...(ticked.length > 1
        ? [{ label: `Mark ${ticked.length} as not related`, onSelect: () => void notRelated.many(ticked) }]
        : [
            { label: "Quick Look", onSelect: () => look.open(r.drive_id) },
            { label: "Show in Browse", onSelect: () => navigate(browseTo(r.path, r.drive_id)) },
            { label: "Not related", onSelect: () => notRelated(r) },
          ]),
      "separator",
      ...actions.entries,
    ];
    return { label: `Actions for ${ticked.length > 1 ? `${ticked.length} related files` : visible(r.name)}`, entries };
  };

  if (relatives.length === 0 && hidden === 0 && picks.length === 0) {
    return (
      <div className="relatives-body">
        <p className="hint">{EMPTY_TEXT}</p>
        <FindMoreButton finder={finder} />
        <FoundLine finder={finder} />
      </div>
    );
  }
  return (
    <div className="relatives-body">
      {relatives.length === 0 && <p className="hint">{EMPTY_TEXT}</p>}
      <ul className="relatives-list">
        {shown.map((r) => (
          <RelativeRow
            key={r.drive_id}
            relative={r}
            checked={selected.has(r.drive_id)}
            onToggle={() => toggle(r.drive_id)}
            onLook={() => look.open(r.drive_id)}
            onNotRelated={() => notRelated(r)}
            onMenu={onMenu(r)}
          />
        ))}
      </ul>
      {more > 0 && (
        <button type="button" className="link-button relatives-more" onClick={() => setShowAll(true)}>
          {more} more{moreAllSingle ? " with one link in common" : ""}
        </button>
      )}
      {picks.length > 0 && (
        <ul className="relatives-list relatives-ai-list" aria-label="Found by AI">
          {picks.map((r) => (
            <RelativeRow
              key={r.drive_id}
              relative={r}
              checked={selected.has(r.drive_id)}
              onToggle={() => toggle(r.drive_id)}
              onLook={() => look.open(r.drive_id)}
              onNotRelated={() => notRelated(r)}
              onMenu={onMenu(r)}
            />
          ))}
        </ul>
      )}
      <FoundLine finder={finder} />
      <FindMoreButton finder={finder} />
      {ticked.length > 0 && actions.bar}
      {actions.view}
      {menu.view(menuFor)}
      {hidden > 0 && (
        <div className="relatives-hidden">
          <button
            type="button"
            className="link-button"
            aria-expanded={showHidden}
            onClick={() => setShowHidden((v) => !v)}
          >
            {hidden} marked not related
          </button>
          {showHidden && <DismissedList driveId={file.drive_id} />}
        </div>
      )}
      {look.view}
    </div>
  );
}

function RelativeRow({
  relative: r,
  checked,
  onToggle,
  onLook,
  onNotRelated,
  onMenu,
}: {
  relative: Relative;
  checked: boolean;
  onToggle: () => void;
  onLook: () => void;
  onNotRelated: () => void;
  onMenu: (e: React.MouseEvent) => void;
}) {
  const name = visible(r.name);
  const pick: AIPick | null = isAIPick(r) ? r : null;
  const kinds = kindsOf(r);
  const unfiled = r.in_inbox && !pick;
  return (
    <li
      className={`relative-row${checked ? " checked" : ""}${unfiled ? " unfiled" : ""}${pick ? " ai" : ""}`}
      data-drive-id={r.drive_id}
      onContextMenu={onMenu}
    >
      <input type="checkbox" checked={checked} onChange={onToggle} aria-label={`Select ${name}`} />
      <div className="relative-main">
        <div className="relative-line">
          <button type="button" className="relative-name trunc" title={`Quick Look: ${name}`} onClick={onLook}>
            {name}
          </button>
          <span className="relative-folder trunc" title={visible(r.folder)}>
            {r.in_inbox ? "Inbox" : visible(baseName(r.folder)) || "Archive"}
          </span>
        </div>
        {unfiled && (
          <div className="relative-unfiled">
            <span title={`${KIND_PHRASE[kinds[0]]}, not filed yet`}>{KIND_PHRASE[kinds[0]]}, not filed yet</span>
            <Link to="/inbox" className="link-button">
              Go to the inbox
            </Link>
          </div>
        )}
        {pick ? (
          <div className="relative-ai-reason">
            <AIMark pick={pick} />
            <span>{visible(pick.reason)}</span>
          </div>
        ) : (
          <div className="relative-kinds" title={linkTip(r)}>
            {kinds.map((kind) => (
              <span key={kind} className={`tag ${KIND_CLASS[kind]}`}>
                {KIND_LABEL[kind]}
              </span>
            ))}
            {r.same_month && <span className="tag tag-grey">+ same month</span>}
          </div>
        )}
      </div>
      <div className="relative-tools">
        <IconButton icon={<Eye size={14} />} label={`Quick Look ${name}`} tip="Quick Look" onClick={onLook} />
        <ShowInBrowse to={browseTo(r.path, r.drive_id)} label={`Show ${name} in Browse`} />
        <IconButton
          icon={<EyeOff size={14} />}
          label={`Not related: ${name}`}
          tip="Not related: leave this file out of the list"
          onClick={onNotRelated}
        />
      </div>
    </li>
  );
}

