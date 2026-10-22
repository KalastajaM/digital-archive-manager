/** Today's one compact card for every tray with nothing open: "To pay, To action and To
 * read are clear", so empty trays never take a column of their own. */
import { CircleCheck } from "lucide-react";
import { Link } from "react-router-dom";
import { visible } from "../../text";
import { Card } from "../ui/Card";
import type { CardFrame } from "./frame";

export type ClearTray = { id: string; name: string };

/** "To pay is clear", "To pay and To read are clear", "To pay, To action and To read are clear". */
export function ClearCard({ trays, frame }: { trays: ClearTray[]; frame: CardFrame }) {
  const enc = encodeURIComponent;
  return (
    <Card
      title="Clear"
      icon={<CircleCheck />}
      className="today-card today-card-compact"
      fold={frame.fold}
      headerProps={frame.headerProps}
    >
      {!frame.fold.folded && (
        <p className="today-sub today-clear">
          {trays.map((t, i) => (
            <span key={t.id}>
              {i > 0 && (i === trays.length - 1 ? " and " : ", ")}
              <Link to={`/trays/${enc(t.id)}`}>{visible(t.name)}</Link>
            </span>
          ))}{" "}
          {trays.length === 1 ? "is" : "are"} clear.
        </p>
      )}
    </Card>
  );
}
