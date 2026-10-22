/** The one notice banner: a sentence-case message at the left and, when there is
 * something to do about it, one action button at the right. It sits inside the content
 * column of every screen (Today, Important, collection pages). */
import { Link } from "react-router-dom";
import { sentence } from "./collectionText";

export type BannerAction = { label: string } & ({ to: string } | { onClick: () => void });

export function Banner({
  message,
  action,
  label,
}: {
  /** The message; its first letter is capitalised (stored statuses start lowercase). */
  message: string;
  action?: BannerAction;
  /** The region's accessible name (default: the message). */
  label?: string;
}) {
  return (
    <section className="banner page-banner" aria-label={label ?? sentence(message)}>
      <p>{sentence(message)}</p>
      {action &&
        ("to" in action ? (
          <Link className="banner-action" to={action.to}>
            {action.label}
          </Link>
        ) : (
          <button type="button" className="banner-action" onClick={action.onClick}>
            {action.label}
          </button>
        ))}
    </section>
  );
}
