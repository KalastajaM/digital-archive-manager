/** The notice that ``##. Important`` holds top-level entries the app does not manage
 * yet, with the way to Convert ##. Important (Today and the Important page). The count
 * is of entries: a folder of shortcuts counts once. */
import { plural } from "../format";
import { Banner } from "./Banner";

/** "10 entries in ##. Important are not in the app yet." */
export const importantNotice = (count: number) =>
  `${plural(count, "entry", "entries")} in ##. Important ${count === 1 ? "is" : "are"} not in the app yet.`;

export function ImportantBanner({ count }: { count: number }) {
  if (count <= 0) return null;
  return (
    <Banner
      message={importantNotice(count)}
      label="Convert ##. Important"
      action={{ label: "Convert", to: "/important/convert" }}
    />
  );
}
