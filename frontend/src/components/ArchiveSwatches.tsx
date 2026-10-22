import { ARCHIVE_COLORS } from "./archivePalette";

/** A row of colour buttons (one pressed). */
export function ArchiveSwatches({
  value,
  onPick,
  label,
  disabled,
}: {
  value: string;
  onPick: (color: string) => void;
  label: string;
  disabled?: boolean;
}) {
  return (
    <div className="archive-swatches" role="group" aria-label={label}>
      {ARCHIVE_COLORS.map((c) => (
        <button
          key={c.value}
          type="button"
          className="archive-swatch"
          style={{ background: c.value }}
          aria-label={c.name}
          aria-pressed={value.toLowerCase() === c.value}
          title={c.name}
          disabled={disabled}
          onClick={() => onPick(c.value)}
        />
      ))}
    </div>
  );
}
