/** Pick-one suggestions (stars spec §7): each suggested value that differs from what a
 * field shows is a chip below it, "Suggested: <value>" with its source ("rule <id>",
 * "scan", "AI") and Use. Nothing is applied on its own: Use changes that one field,
 * Use all applies every chip. Each suggested tag is its own chip. */
import { visible } from "../text";
import { Tag } from "./ui/Tag";

/** A suggested value and where it came from (``"rule:<id>"``, ``"scan"``, ``"AI"``). */
export type Offer = { value: string; source: string; note?: string };

/** An AI offer's tip: how sure it was, and why ("85% sure — Northpower Oy sends bills"). */
export function aiNote(confidence: number | undefined, reason: string | undefined): string | undefined {
  const sure = confidence === undefined ? null : `${Math.round(Math.min(1, Math.max(0, confidence)) * 100)}% sure`;
  const why = reason?.trim() || null;
  return [sure, why].filter(Boolean).join(" — ") || undefined;
}

export const AI_SOURCE = "AI";

/** The tags typed in a comma-separated field. */
export const parseTags = (text: string) =>
  text
    .split(",")
    .map((t) => t.trim())
    .filter(Boolean);

const fold = (s: string) => s.normalize("NFC").toLocaleLowerCase();

const SOURCES = " · ";

/** How a filing code was found, for a "code:P" source: "from folder To pay", "from pen
 * mark `P`", "from sticker `P`". Unknown (not found in the file's hits): "code `P`". */
export type CodeLabel = (code: string) => string;

/** "rule:northpower" → "rule northpower", "code:P" → "from folder To pay" (``codeLabel``
 * knows how the code was found); other sources as they are (each of a joined list). */
export const sourceLabel = (source: string, codeLabel?: CodeLabel) =>
  source
    .split(SOURCES)
    .map((s) =>
      s.startsWith("rule:")
        ? `rule ${s.slice(5)}`
        : s.startsWith("code:")
          ? (codeLabel?.(s.slice(5)) ?? `code \`${s.slice(5)}\``)
          : s,
    )
    .join(SOURCES);

/** The offers (first one first) whose value differs from ``current``; one per value,
 * naming every source that suggested it. Empty values are left out. */
export function offersFor(current: string, offers: (Offer | null | undefined)[]): Offer[] {
  const out: Offer[] = [];
  for (const o of offers) {
    if (!o || !o.value.trim() || o.value === current) continue;
    const same = out.find((x) => x.value === o.value);
    if (!same) out.push({ ...o });
    else if (!same.source.split(SOURCES).includes(o.source)) same.source = `${same.source}${SOURCES}${o.source}`;
  }
  return out;
}

/** The tag offers not in the ``tags`` text yet (case does not matter). */
export function tagOffers(tags: string, offers: Offer[]): Offer[] {
  const have = new Set(parseTags(tags).map(fold));
  return offersFor("", offers).filter((o) => !have.has(fold(o.value)));
}

/** ``tags`` (a comma-separated text) with ``tag`` added at the end. */
export function addTags(tags: string, added: string[]): string {
  const list = parseTags(tags);
  const have = new Set(list.map(fold));
  for (const t of added) {
    if (!have.has(fold(t))) {
      list.push(t);
      have.add(fold(t));
    }
  }
  return list.join(", ");
}

type ChipProps = {
  /** The field as named in the label ("Name", "Folder", "Tags", "tray"). */
  field: string;
  offer: Offer;
  /** The value as shown, when it differs from what Use puts in (e.g. a tray's name). */
  shown?: string;
  disabled?: boolean;
  codeLabel?: CodeLabel;
  onUse: () => void;
};

export function SuggestionChip({ field, offer, shown, disabled, codeLabel, onUse }: ChipProps) {
  const text = visible(shown ?? offer.value);
  const source = visible(sourceLabel(offer.source, codeLabel));
  const tip = offer.note ? `${source}: ${visible(offer.note)}` : source;
  return (
    <div className="suggestion-chip" role="group" aria-label={`Suggested ${visible(field)}: ${text} (${source})`}>
      <span className="suggestion-text">
        Suggested: <span className="suggestion-value">{text}</span>
      </span>
      <Tag
        tone={offer.source.split(SOURCES).includes(AI_SOURCE) ? "blue" : "grey"}
        className="suggestion-source"
        title={tip}
      >
        {source}
      </Tag>
      <button type="button" className="suggestion-use" disabled={disabled} onClick={onUse}>
        Use
      </button>
    </div>
  );
}

/** The chips of one field (none: nothing is rendered). */
export function FieldChips({
  field,
  offers,
  shown,
  disabled,
  codeLabel,
  onUse,
}: {
  field: string;
  offers: Offer[];
  shown?: (offer: Offer) => string;
  disabled?: boolean;
  codeLabel?: CodeLabel;
  onUse: (offer: Offer) => void;
}) {
  if (offers.length === 0) return null;
  return (
    <div className="suggestion-chips">
      {offers.map((o) => (
        <SuggestionChip
          key={o.value}
          field={field}
          offer={o}
          shown={shown?.(o)}
          disabled={disabled}
          codeLabel={codeLabel}
          onUse={() => onUse(o)}
        />
      ))}
    </div>
  );
}

/** "Use all": shown while there are chips; applies every one of them. */
export function UseAll({ count, disabled, onUse }: { count: number; disabled?: boolean; onUse: () => void }) {
  if (count === 0) return null;
  return (
    <div className="suggestion-all">
      <span className="hint">
        {count === 1 ? "1 suggestion" : `${count} suggestions`} below the fields
      </span>
      <button type="button" disabled={disabled} onClick={onUse}>
        Use all
      </button>
    </div>
  );
}
