import { Fragment } from "react";

/** One hint: the keys (each one ``<kbd>``; several are alternatives, shown "a/b"), then
 * what they do. A chord is one key string ("⌘↩"), written in Apple's modifier order. */
export type KeyHint = [string[], string];

/** The key-hint line at the foot of a list (Browse, Inbox, Trays): one look everywhere. */
export function KeyHints({ hints, className }: { hints: KeyHint[]; className?: string }) {
  return (
    <p className={className ? `hint key-hints ${className}` : "hint key-hints"}>
      {hints.map(([keys, what]) => (
        <span key={what} className="key-group">
          {keys.map((k, i) => (
            <Fragment key={k}>
              {i > 0 && "/"}
              <kbd>{k}</kbd>
            </Fragment>
          ))}
          {keys.length > 0 && " "}
          {what}
        </span>
      ))}
    </p>
  );
}
