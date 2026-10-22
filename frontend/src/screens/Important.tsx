/** The ! Important page (the sidebar's Important row): the built-in collection's page,
 * with its groups and no rename, close or parent actions. While ##. Important holds
 * entries the app does not manage yet, the page says so next to the count, with the
 * way to Convert them. */
import { Link } from "react-router-dom";
import { errorText, useBuiltin, useToday } from "../api/client";
import { importantNotice } from "../components/ImportantBanner";
import { Banner } from "../components/Banner";
import { visible } from "../text";
import CollectionDetail from "./CollectionDetail";

export default function Important({ today }: { today?: string }) {
  const important = useBuiltin("important");
  const unmanaged = useToday().data?.unmanaged_important ?? 0;
  if (important.isPending) return <p className="placeholder">Loading…</p>;
  if (important.isError) {
    return (
      <p className="error" role="alert">
        Could not load Important. {visible(errorText(important.error))}
      </p>
    );
  }
  return (
    <section className="collection-page important-page" aria-label="Important">
      <CollectionDetail
        key={important.data.id}
        id={important.data.id}
        today={today}
        subtitleExtra={unmanaged > 0 ? `${unmanaged} not in the app yet` : undefined}
        banner={
          unmanaged > 0 ? (
            <Banner
              message={importantNotice(unmanaged)}
              label="Convert ##. Important"
              action={{ label: "Convert", to: "/important/convert" }}
            />
          ) : (
            <p className="hint important-convert-link">
              <Link to="/important/convert">Convert ##. Important…</Link>
            </p>
          )
        }
      />
    </section>
  );
}
