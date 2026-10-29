/** Settings > Reading documents (New look): the address area drawn on a sample letter. The
 * owner picks a PDF or image from their computer; dam reads page 1 in a temporary file and
 * forgets it (nothing is added to the archive). Page 1 shows the area in use now, dashed; a
 * box dragged over it lists the lines it holds and can be saved as the area for all letters.
 * A document with its own area keeps it. */
import { useRef, useState } from "react";
import {
  type Area,
  errorText,
  type PageBox,
  readSampleLetter,
  type SampleLetter,
  type SampleLine,
  usePeople,
  useSavePeople,
} from "../../api/client";
import { isShortcut, useKeydown } from "../../keyboard";
import { visible } from "../../text";
import { AreaLayer, percent } from "./AreaLayer";
import { useDragBox } from "./useDragBox";

const ACCEPT = ".pdf,.jpg,.jpeg,.png,application/pdf,image/jpeg,image/png";

/** How much of ``line`` lies in ``area`` (0..1); a flat line counts by its length. */
function shareInside(line: PageBox, area: PageBox): number {
  const [lx0, ly0, lx1, ly1] = line;
  const w = lx1 - lx0;
  const h = ly1 - ly0;
  const ix = Math.max(0, Math.min(lx1, area[2]) - Math.max(lx0, area[0]));
  const iy = Math.max(0, Math.min(ly1, area[3]) - Math.max(ly0, area[1]));
  if (w > 0 && h > 0) return (ix * iy) / (w * h);
  if (w > 0) return area[1] <= ly0 && ly0 <= area[3] ? ix / w : 0;
  if (h > 0) return area[0] <= lx0 && lx0 <= area[2] ? iy / h : 0;
  return area[0] <= lx0 && lx0 <= area[2] && area[1] <= ly0 && ly0 <= area[3] ? 1 : 0;
}

/** The text of the lines in ``box``, as dam reads an area (``lines_in_zone``): the words of
 * a line that are at least half inside, or a line without words when half of it is. */
export function linesInBox(lines: readonly SampleLine[], box: PageBox): string[] {
  const out: string[] = [];
  for (const line of lines) {
    if (line.words.length === 0) {
      if (shareInside(line.box, box) >= 0.5) out.push(line.text);
      continue;
    }
    const inside = line.words.filter((w) => shareInside(w.box, box) >= 0.5);
    if (inside.length === line.words.length) out.push(line.text);
    else if (inside.length > 0) out.push(inside.map((w) => w.text).join(" "));
  }
  return out;
}

/** The area in use now, drawn dashed under the box. */
const inUse = (box: PageBox): Area => ({
  rule_id: "",
  index: 0,
  box,
  kind: "address",
  lines: [],
  matched: false,
  wins: false,
  document: false,
});

/** ``onSaved``: the area was saved from here (the fields above show it). */
export function SampleLetterArea({ onSaved }: { onSaved: () => void }) {
  const people = usePeople();
  const save = useSavePeople();
  const input = useRef<HTMLInputElement>(null);
  const [sample, setSample] = useState<SampleLetter | null>(null);
  const [reading, setReading] = useState(false);
  const [box, setBox] = useState<PageBox | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const { drawing, cancel, surface } = useDragBox((drawn) => {
    setSaved(false);
    setBox(drawn);
  });

  // Esc: first the box being drawn, then the box drawn
  useKeydown((e) => {
    if (e.key !== "Escape" || !isShortcut(e) || (drawing === null && box === null)) return;
    e.preventDefault();
    if (drawing) cancel();
    else setBox(null);
  });

  const read = async (file: File | undefined) => {
    if (!file) return;
    setError(null);
    setSaved(false);
    setSample(null);
    setBox(null);
    setReading(true);
    try {
      setSample(await readSampleLetter(file));
    } catch (e) {
      setError(errorText(e));
    } finally {
      setReading(false);
    }
  };
  const close = () => {
    setSample(null);
    setBox(null);
    setError(null);
  };
  const use = async () => {
    if (!box || !people.data) return;
    setError(null);
    try {
      await save.mutateAsync({ people: people.data.people, address_zone: box });
      close();
      setSaved(true);
      onSaved();
    } catch (e) {
      setError(errorText(e));
    }
  };

  const found = sample && box ? linesInBox(sample.lines, box) : [];
  return (
    <section className="sample-letter" aria-label="Sample letter">
      <p className="hint">
        Or draw it on a letter: pick a PDF or picture of one on your computer and drag a box around the address on page
        1. The letter is only read to show page 1; it is not added to the archive.
      </p>
      <div className="actions">
        <input
          ref={input}
          type="file"
          accept={ACCEPT}
          hidden
          aria-label="Sample letter file"
          onChange={(e) => {
            const file = e.target.files?.[0];
            e.target.value = ""; // the same file can be picked again
            void read(file);
          }}
        />
        <button type="button" disabled={reading} onClick={() => input.current?.click()}>
          Choose a sample letter…
        </button>
        {sample && (
          <button type="button" onClick={close}>
            Close
          </button>
        )}
      </div>
      {reading && (
        <p className="busy" role="status">
          Reading page 1…
        </p>
      )}
      {saved && (
        <p className="hint" role="status">
          Saved. Letters use the new area from now on.
        </p>
      )}
      {error && (
        <p className="error" role="alert">
          {visible(error)}
        </p>
      )}
      {sample && people.data && (
        <>
          <p className="hint">Drag over page 1 to draw the address area. The dashed box is the area in use now.</p>
          <div className="sample-page sample-letter-page">
            <span className="page-layer">
              <img src={sample.image} alt="Page 1 of the sample letter" draggable={false} />
              <AreaLayer areas={[inUse(people.data.address_zone)]} />
              {box && <span className="page-box page-box-kept" data-testid="sample-box" style={percent(box)} />}
              {drawing && <span className="page-box" style={percent(drawing)} />}
              <span className="page-surface" data-testid="sample-surface" {...surface} />
            </span>
          </div>
          {box && (
            <div className="sample-letter-found">
              {!sample.read ? (
                <p className="hint">The text of this letter could not be read: {visible(sample.unavailable ?? "")}.</p>
              ) : found.length === 0 ? (
                <p className="hint">No text in the box.</p>
              ) : (
                <ul className="sample-lines" aria-label="Lines in the box">
                  {found.map((text, i) => (
                    <li key={i} className="sample-line">
                      {visible(text)}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}
          <div className="actions">
            <button
              type="button"
              className="primary"
              disabled={box === null || save.isPending}
              onClick={() => void use()}
            >
              Use for all letters
            </button>
            {box && people.data.address_zone_set && <span className="hint">This replaces the area you set.</span>}
          </div>
          <p className="hint">
            Documents with their own address area keep it (Draw a box on that document, This document only).
          </p>
        </>
      )}
    </section>
  );
}
