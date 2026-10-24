/** "Page 1 reading speed": how many PDFs with a text layer have their first page read per
 * minute. Scans, photos and slow downloads (cloud files) keep the indexer's pace. Used in
 * Settings and on the Index sheet. */
import { errorText, usePage1Speed } from "../api/client";
import { groupDigits } from "../format";
import { visible } from "../text";

const CHOICES = [30, 60, 120, 300, 600];

export function Page1Speed({ textPerMin, scansPerMin }: { textPerMin: number; scansPerMin: number }) {
  const speed = usePage1Speed();
  const choices = CHOICES.includes(textPerMin) ? CHOICES : [...CHOICES, textPerMin].sort((a, b) => a - b);
  return (
    <div className="page1-speed field">
      <label htmlFor="page1-speed">Page 1 reading speed</label>
      <select
        id="page1-speed"
        value={textPerMin}
        disabled={speed.isPending}
        aria-describedby="page1-speed-hint"
        onChange={(e) => speed.mutate(Number(e.target.value))}
      >
        {choices.map((n) => (
          <option key={n} value={n}>
            {groupDigits(n)} a minute{n <= scansPerMin ? " (the indexer's pace)" : ""}
          </option>
        ))}
      </select>
      <p id="page1-speed-hint" className="hint">
        For PDFs that have a text layer. Scans, photos and files that are slow to fetch are read at the indexer's pace,
        {` ${groupDigits(scansPerMin)} a minute`}.
      </p>
      {speed.isError && (
        <p className="error" role="alert">
          {visible(errorText(speed.error))}
        </p>
      )}
    </div>
  );
}
