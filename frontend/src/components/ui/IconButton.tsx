import type { MouseEventHandler, ReactNode } from "react";

type Props = {
  icon: ReactNode;
  /** The accessible name; also the tooltip (with the shortcut after it). */
  label: string;
  /** A longer tooltip than ``label`` (which stays the accessible name). */
  tip?: string;
  /** Shown in the tooltip, e.g. "⌘N". */
  shortcut?: string;
  onClick?: MouseEventHandler<HTMLButtonElement>;
  disabled?: boolean;
  /** For toggles (e.g. a split view): marks the button pressed. */
  pressed?: boolean;
  /** Where the tooltip goes; "above" for controls near the bottom of the window. */
  tipSide?: "below" | "above";
  className?: string;
  /** Why it is disabled: shown as the tooltip (a disabled button shows none of its own). */
  disabledReason?: string;
};

/** A toolbar icon button: a Lucide icon, named by ``label``, with a tooltip on hover
 * and keyboard focus (CSS reads ``data-tip``). */
export function IconButton({ icon, label, tip, shortcut, onClick, disabled, pressed, tipSide, className, disabledReason }: Props) {
  const button = (
    <button
      type="button"
      className={className ? `icon-button ${className}` : "icon-button"}
      aria-label={label}
      aria-pressed={pressed}
      data-tip={shortcut ? `${tip ?? label} ${shortcut}` : (tip ?? label)}
      data-tip-side={tipSide === "above" ? "above" : undefined}
      onClick={onClick}
      disabled={disabled}
    >
      <span className="icon-button-glyph" aria-hidden="true">
        {icon}
      </span>
    </button>
  );
  if (!disabled || !disabledReason) return button;
  return (
    <span className="icon-button-wrap" data-tip={disabledReason} data-tip-side={tipSide === "above" ? "above" : undefined}>
      {button}
    </span>
  );
}
