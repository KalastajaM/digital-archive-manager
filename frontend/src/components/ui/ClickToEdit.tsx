import type { ReactNode } from "react";

/** A name or title that is renamed by clicking it. It is a real button (so Enter and Space
 * work and it takes focus), looks like plain text, and shows a subtle underline on hover
 * and a focus ring from the keyboard. ``label`` is its accessible name ("Rename scan.pdf"),
 * ``tip`` the hover text; a disabled one says why in ``tip``. */
export function ClickToEdit({
  label,
  tip,
  disabled = false,
  onClick,
  children,
}: {
  label: string;
  tip: string;
  disabled?: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button type="button" className="click-edit" aria-label={label} title={tip} disabled={disabled} onClick={onClick}>
      {children}
    </button>
  );
}
