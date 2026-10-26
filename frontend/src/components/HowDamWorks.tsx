/** The diagrams under "How dam works" in Help: the filing flow, where a filed document
 * lands, when the trays remind, the safety loop and what stays on the computer. Plain SVG
 * coloured from the theme tokens (styles.css, `.hdw`), so they follow Light and Dark. The
 * folder names are the default ones. Wide diagrams scroll sideways in a narrow window
 * rather than shrink their text. */
import { createContext, type ReactNode, useContext, useId } from "react";

type Tone = "plain" | "accent" | "safe" | "tray" | "warn";

/** The id prefix of this instance's arrowheads (one `<marker>` per tone). */
const Markers = createContext("");

function Line({ d, tone = "plain", dashed, both }: { d: string; tone?: Tone; dashed?: boolean; both?: boolean }) {
  const ids = useContext(Markers);
  const head = `url(#${ids}-${tone})`;
  return (
    <path
      d={d}
      className={`hdw-ln ${tone}${dashed ? " hdw-dash" : ""}`}
      markerEnd={head}
      markerStart={both ? head : undefined}
    />
  );
}

/** A box with a title and an optional second line; `folder` adds a tab on top. Tinted boxes
 * sit on a panel-coloured base so lines behind them never show through. */
function Box(props: {
  x: number; y: number; w: number; h: number; title: string; sub?: string;
  tone?: Tone; mono?: boolean; left?: boolean; rx?: number; dashed?: boolean; folder?: boolean;
}) {
  const { x, y, w, h, title, sub, tone = "plain", mono, left, rx = 8, dashed, folder } = props;
  const tx = left ? x + 20 : x + w / 2;
  const ty = sub ? y + h / 2 - 3 : y + h / 2 + 6;
  const anchor = left ? "start" : "middle";
  return (
    <g>
      {folder && <rect x={x} y={y - 10} width={54} height={16} rx={3} className="hdw-box plain" />}
      <rect x={x} y={y} width={w} height={h} rx={rx} className="hdw-base" />
      <rect x={x} y={y} width={w} height={h} rx={rx} className={`hdw-box ${tone}${dashed ? " hdw-dash" : ""}`} />
      <text x={tx} y={ty} textAnchor={anchor} className={`hdw-t ${tone}`}>{title}</text>
      {sub && <text x={tx} y={ty + 20} textAnchor={anchor} className={mono ? "hdw-m" : "hdw-s"}>{sub}</text>}
    </g>
  );
}

function Pill({ cx, text, tone = "plain", dashed }: { cx: number; text: string; tone?: Tone; dashed?: boolean }) {
  return (
    <g>
      <rect x={cx - 52} y={280} width={104} height={38} rx={19} className="hdw-base" />
      <rect x={cx - 52} y={280} width={104} height={38} rx={19} className={`hdw-box ${tone}${dashed ? " hdw-dash" : ""}`} />
      <text x={cx} y={304} textAnchor="middle" className={`hdw-s ${tone}`}>{text}</text>
    </g>
  );
}

/** A sheet of paper with a folded corner. */
function Doc({ x, y, w, h, tone = "plain" }: { x: number; y: number; w: number; h: number; tone?: Tone }) {
  return (
    <g>
      <path d={`M${x} ${y}H${x + w - 18}L${x + w} ${y + 18}V${y + h}H${x}Z`} className={`hdw-box ${tone} hdw-doc`} />
      <path d={`M${x + w - 18} ${y}V${y + 18}H${x + w}`} className={`hdw-ln ${tone} hdw-thin`} />
    </g>
  );
}

function Label({ x, y, children, tone = "plain", anchor = "middle", strong, mono, small }: {
  x: number; y: number; children: ReactNode; tone?: Tone | "ink"; anchor?: "start" | "middle" | "end";
  strong?: boolean; mono?: boolean; small?: boolean;
}) {
  const style = `${mono ? "hdw-m" : "hdw-s"} ${tone}${strong ? " hdw-strong" : ""}${small ? " hdw-small" : ""}`;
  return (
    <text x={x} y={y} textAnchor={anchor} className={style}>
      {children}
    </text>
  );
}

function Figure({ title, note, wide = true, children }: { title: string; note: string; wide?: boolean; children: ReactNode }) {
  return (
    <figure className={wide ? "hdw-fig hdw-wide" : "hdw-fig"}>
      <figcaption>
        <strong>{title}</strong> <span>{note}</span>
      </figcaption>
      <div className="hdw-scroll">{children}</div>
    </figure>
  );
}

function FilingFlow() {
  return (
    <Figure title="The filing flow" note="Nothing moves until you confirm the preview.">
      <svg viewBox="0 0 1080 440" role="img" aria-label="The filing flow: paper, optionally with a QR sticker, is scanned into the inbox or a coded subfolder, read, given suggestions from the filing code, your rules, the scan, similar files and optional AI, previewed, then filed. Undo returns it to the inbox.">
        <Doc x={30} y={100} w={58} h={80} />
        <path d="M40 135H78M40 148H78M40 161H66" className="hdw-faint hdw-thick" />
        <rect x={62} y={152} width={20} height={20} rx={2} className="hdw-box tray hdw-dash" />
        <path d="M66 156h5v5h-5zM73 163h5v5h-5zM66 165h3v3h-3zM75 156h3v3h-3z" className="hdw-fill tray" />
        <Label x={16} y={62} tone="tray" anchor="start">optional QR sticker</Label>
        <Line d="M60 68L70 148" tone="tray" />
        <Label x={59} y={204}>paper → scan</Label>
        <Line d="M95 140H128" />

        <Label x={210} y={62} tone="tray">or a coded subfolder</Label>
        <Label x={210} y={80} tone="tray" mono>To pay/ · To action/</Label>
        <Box x={135} y={102} w={150} h={76} title="Inbox" sub="##. Organize" mono folder />
        <Line d="M290 140H333" />
        <Box x={340} y={102} w={130} h={76} title="Read" sub="text · OCR · QR" />
        <Line d="M475 140H518" />
        <Box x={525} y={102} w={150} h={76} title="Suggest" sub="name · folder · tray" />

        <Line d="M372 280L550 184" tone="tray" />
        <Line d="M486 280L575 184" />
        <Line d="M600 280L600 184" />
        <Line d="M714 280L625 184" />
        <Line d="M828 280L650 184" dashed />
        <Pill cx={372} text="filing code" tone="tray" />
        <Pill cx={486} text="your rules" />
        <Pill cx={600} text="scan fields" />
        <Pill cx={714} text="similar files" />
        <Pill cx={828} text="AI · on click" dashed />

        <Line d="M680 140H723" />
        <Label x={795} y={88}>nothing moved yet</Label>
        <Box x={730} y={102} w={130} h={76} title="Preview" sub="exact plan" tone="accent" />
        <Line d="M865 140H908" tone="accent" />
        <Label x={886} y={128} tone="accent">confirm</Label>
        <Box x={915} y={102} w={145} h={76} title="File" sub="apply · journal" tone="safe" />

        <Line d="M987 182C987 470 210 470 210 186" tone="safe" dashed />
        <Label x={600} y={425} tone="safe" strong>Undo</Label>
      </svg>
    </Figure>
  );
}

function WhereItLands() {
  const rows = [44, 118, 192, 266, 340];
  return (
    <Figure title="Where a filed document lands" note="It moves to one folder; everything else points at it.">
      <svg viewBox="0 0 940 380" role="img" aria-label="Where a filed document lands: it moves to your folder, which your cloud client syncs. A tray, a collection, Important and tags point at it, and lead to reminders, the link folders and search.">
        <Doc x={60} y={150} w={90} h={82} tone="accent" />
        <Label x={105} y={260}>filed document</Label>

        <Line d="M156 180L376 44" tone="accent" />
        {rows.slice(1).map((y, i) => (
          <Line key={y} d={`M156 ${186 + i * 6}L376 ${y}`} dashed />
        ))}
        <Label x={262} y={92} tone="accent" anchor="end" strong>moves</Label>
        <Label x={250} y={310} anchor="end">points at</Label>

        <Box x={380} y={18} w={240} h={52} title="Your folder" sub="40. Finance/Bills/" mono left tone="accent" />
        <Box x={380} y={92} w={240} h={52} title="Tray" sub="To pay · To action · …" left tone="tray" />
        <Box x={380} y={166} w={240} h={52} title="Collection" sub="house sale · court case" left tone="safe" />
        <Box x={380} y={240} w={240} h={52} title="Important" sub="locked against moves" left />
        <Box x={380} y={314} w={240} h={52} title="Tags" sub="rename · merge · group" left />

        <Line d="M624 44H696" tone="accent" />
        <Line d="M624 118H696" tone="tray" />
        <Line d="M624 192H696" tone="safe" dashed />
        <Line d="M624 266H696" dashed />
        <Line d="M624 340H696" />

        <Box x={700} y={18} w={220} h={52} rx={26} title="Cloud sync" sub="your own client" left />
        <Box x={700} y={92} w={220} h={52} title="Reminders" sub="desktop · e-mail" left />
        <circle cx={893} cy={118} r={9} className="hdw-dot" />
        <Box x={700} y={166} w={220} h={52} title="Link folder" sub="##. Ongoing" mono left />
        <Box x={700} y={240} w={220} h={52} title="Link folder" sub="##. Important" mono left />
        <Box x={700} y={314} w={220} h={52} title="Search" sub="Today · Browse" left />
      </svg>
    </Figure>
  );
}

/** The reminder days of each tray, on one axis (the x of each tick). */
const TICKS = { before3: 340, before1: 460, due: 580, overdue: 760 };
const LANES: { tray: string; dots: number[] }[] = [
  { tray: "To pay", dots: [TICKS.before3, TICKS.due, TICKS.overdue] },
  { tray: "To action", dots: [TICKS.before1, TICKS.due] },
  { tray: "Follow up", dots: [TICKS.due, TICKS.overdue] },
];

function Reminders() {
  return (
    <Figure title="When the trays remind you" note="Each reminder is sent once, never for done items.">
      <svg viewBox="0 0 940 240" role="img" aria-label="Reminders: To pay 3 days before the due date, on the day and once overdue; To action 1 day before and on the day; Follow up on the check date and once overdue; To read one nudge 30 days after filing.">
        {Object.values(TICKS).map((x) => (
          <g key={x}>
            <path d={`M${x} 18V196`} className="hdw-faint hdw-dash" />
            <path d={`M${x} 196v6`} className="hdw-ln plain" />
          </g>
        ))}
        <path d="M150 196H900" className="hdw-ln plain" />
        <Label x={TICKS.before3} y={222} mono>−3 days</Label>
        <Label x={TICKS.before1} y={222} mono>−1 day</Label>
        <Label x={TICKS.due} y={222} mono tone="ink">due / check date</Label>
        <Label x={TICKS.overdue} y={222} mono>overdue</Label>
        {[...LANES, { tray: "To read", dots: [870] }].map((lane, i) => {
          const y = 40 + i * 42;
          return (
            <g key={lane.tray}>
              <path d={`M150 ${y}H900`} className="hdw-faint" />
              <text x={20} y={y + 6} className="hdw-t plain hdw-lane">{lane.tray}</text>
              {lane.dots.map((x) => <circle key={x} cx={x} cy={y} r={8} className="hdw-dot" />)}
            </g>
          );
        })}
        <Label x={856} y={160} anchor="end">30 days after filing</Label>
      </svg>
    </Figure>
  );
}

function SafetyLoop() {
  return (
    <Figure title="The safety loop" note="Every change to your files goes round it." wide={false}>
      <svg viewBox="0 0 560 400" role="img" aria-label="The safety loop: plan (a dry run), preview, apply exactly as shown, journal entry in Activity; Undo goes from the journal back to a new plan.">
        <circle cx={280} cy={200} r={130} className="hdw-faint" />
        <Line d="M345 87.4A130 130 0 0 1 405.6 166.4" />
        <Line d="M405.6 233.6A130 130 0 0 1 354.6 306.5" />
        <Line d="M205.4 306.5A130 130 0 0 1 154.4 233.6" />
        <Line d="M154.4 166.4A130 130 0 0 1 205.4 93.5" tone="safe" dashed />
        <Label x={150} y={112} tone="safe" anchor="end" strong>Undo</Label>
        <Box x={210} y={42} w={140} h={56} title="Plan" sub="dry run" />
        <Box x={350} y={172} w={150} h={56} title="Preview" sub="you see every step" tone="accent" />
        <Box x={210} y={302} w={140} h={56} title="Apply" sub="exactly as shown" />
        <Box x={60} y={172} w={150} h={56} title="Journal" sub="Activity entry" tone="safe" />
        <Label x={280} y={196}>every change</Label>
        <Label x={280} y={213}>to your files</Label>
      </svg>
    </Figure>
  );
}

function NeverDeletes() {
  return (
    <Figure title="“Delete” is a move" note="You empty To Delete yourself." wide={false}>
      <svg viewBox="0 0 440 400" role="img" aria-label="Delete moves a file to the To Delete folder. Restore or Undo brings it back. You empty that folder yourself; dam never deletes a file.">
        <Doc x={40} y={60} w={56} h={64} />
        <Label x={68} y={146}>your file</Label>
        <Line d="M104 92H214" tone="warn" />
        <Label x={158} y={82} tone="warn" strong>“Delete”</Label>
        <Box x={220} y={56} w={180} h={70} title="##. To Delete" sub="a move, not a delete" tone="warn" />
        <Line d="M238 130Q170 196 76 156" tone="safe" dashed />
        <Label x={140} y={200} tone="safe" strong>Restore · Undo</Label>
        <Line d="M330 130V186" />
        <Box x={250} y={190} w={160} h={52} title="You empty it" />

        <circle cx={78} cy={320} r={34} className="hdw-ban" />
        <path d="M64 306H92M68 306L71 340H85L88 306M73 300H83" className="hdw-ln plain" />
        <path d="M54 296L102 344" className="hdw-ban" />
        <text x={130} y={316} className="hdw-t plain">dam never deletes</text>
        <Label x={130} y={336} anchor="start">only its own links and empty</Label>
        <Label x={130} y={352} anchor="start">folders, identity-checked</Label>
      </svg>
    </Figure>
  );
}

function StaysLocal() {
  return (
    <Figure title="What stays on your computer" note="Your files and dam's data are kept apart.">
      <svg viewBox="0 0 1080 370" role="img" aria-label="On your computer, the app window talks to dam on 127.0.0.1. dam writes previewed changes to the archive folder and keeps its index, config and journal in a separate data folder. Outside: your own cloud sync, and the optional AI, used only on click after a preview.">
        <rect x={20} y={20} width={800} height={320} rx={14} className="hdw-edge hdw-dash" />
        <Label x={42} y={48} anchor="start" mono>YOUR COMPUTER</Label>

        <Box x={50} y={145} w={160} h={60} title="Browser" sub="the app window" />
        <Line d="M216 175H264" both />
        <Label x={240} y={165} mono small>127.0.0.1</Label>
        <Box x={270} y={125} w={180} h={100} rx={10} title="dam" sub="local server" tone="accent" />

        <Line d="M454 150L534 98" tone="accent" />
        <Label x={505} y={146} tone="accent" anchor="start">previewed writes</Label>
        <Line d="M454 205L534 240" both />
        <Box x={540} y={52} w={240} h={68} title="Archive folder" sub="your documents, plain files" folder />
        <Box x={540} y={212} w={240} h={68} title="Data folder" sub="index · config · journal" />

        <Line d="M784 86H874" tone="accent" />
        <Label x={850} y={76}>synced</Label>
        <Box x={880} y={55} w={180} h={62} rx={31} title="Cloud drive" sub="Drive · OneDrive · iCloud" />

        <Line d="M360 229V315H970V291" dashed />
        <Label x={650} y={333}>only on click, after a preview</Label>
        <Box x={880} y={225} w={180} h={62} title="AI (optional)" sub="Anthropic API" dashed />
        <Label x={42} y={322} anchor="start">no telemetry · no background calls</Label>
      </svg>
    </Figure>
  );
}

const TONES: Tone[] = ["plain", "accent", "safe", "tray", "warn"];

export function HowDamWorks() {
  const ids = `hdw${useId().replace(/[^\w-]/g, "")}`;
  return (
    <Markers.Provider value={ids}>
      <div className="hdw">
        <svg width="0" height="0" className="hdw-defs" aria-hidden="true">
          <defs>
            {TONES.map((tone) => (
              <marker key={tone} id={`${ids}-${tone}`} viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
                <path d="M0 0L10 5L0 10z" className={`hdw-fill ${tone}`} />
              </marker>
            ))}
          </defs>
        </svg>
        <FilingFlow />
        <WhereItLands />
        <Reminders />
        <div className="hdw-pair">
          <SafetyLoop />
          <NeverDeletes />
        </div>
        <StaysLocal />
      </div>
    </Markers.Provider>
  );
}
