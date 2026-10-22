import type { ReactNode } from "react";

export type SegmentedOption<T extends string> = {
  value: T;
  label: ReactNode;
  title?: string;
  /** The accessible name when the label is shortened (it must start with the label). */
  ariaLabel?: string;
  /** A key that picks this option, e.g. "1" (``aria-keyshortcuts``). */
  shortcut?: string;
};

type Props<T extends string> = {
  options: SegmentedOption<T>[];
  value: T;
  onChange: (value: T) => void;
  ariaLabel: string;
  className?: string;
};

/** A Mac segmented control: one group of toggle buttons, the chosen one ``aria-pressed``. */
export function Segmented<T extends string>({ options, value, onChange, ariaLabel, className }: Props<T>) {
  return (
    <div role="group" aria-label={ariaLabel} className={className ? `segmented ${className}` : "segmented"}>
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          className="segmented-option"
          aria-pressed={o.value === value}
          title={o.title}
          aria-label={o.ariaLabel}
          aria-keyshortcuts={o.shortcut}
          onClick={() => onChange(o.value)}
        >
          {o.shortcut && (
            <kbd className="segmented-key" aria-hidden="true">
              {o.shortcut}
            </kbd>
          )}
          {o.label}
        </button>
      ))}
    </div>
  );
}
