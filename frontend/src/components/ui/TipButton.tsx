import type { ButtonHTMLAttributes, Ref } from "react";

type Props = Omit<ButtonHTMLAttributes<HTMLButtonElement>, "type"> & {
  /** The tooltip while the button can be used. */
  tip?: string;
  /** Why it is disabled: shown as the tooltip (a disabled button shows none of its own). */
  disabledReason?: string | null;
  type?: "button" | "submit";
  /** The button element (a popover anchors to it). */
  ref?: Ref<HTMLButtonElement>;
};

/** A text button with a CSS tooltip (``data-tip``), like ``IconButton`` for text: a
 * disabled one with a reason is wrapped so the reason still shows on hover. A ``tip-end``
 * class goes on the wrap too, so the tooltip keeps its anchor. */
export function TipButton({ tip, disabledReason, disabled, className, type = "button", children, ...rest }: Props) {
  const button = (
    <button {...rest} type={type} className={className} data-tip={tip} disabled={disabled}>
      {children}
    </button>
  );
  if (!disabled || !disabledReason) return button;
  const end = className?.split(" ").includes("tip-end");
  return (
    <span className={end ? "button-wrap tip-end" : "button-wrap"} data-tip={disabledReason}>
      {button}
    </span>
  );
}
