/** Today's Search card: type, press Enter, and Browse opens with that search (words and
 * `tag:name` filters, as in Browse's own box). It folds and moves like every Today card. */
import { Search } from "lucide-react";
import { type FormEvent, useId, useState } from "react";
import { useNavigate } from "react-router-dom";
import { splitTagQuery } from "../../searchTags";
import { Card } from "../ui/Card";
import type { CardFrame } from "./frame";

/** The Browse address for what was typed (a trailing tag:name counts as finished). */
export function browseSearchUrl(text: string): string {
  const typed = splitTagQuery(`${text} `);
  const p = new URLSearchParams();
  if (typed.rest.trim()) p.set("q", typed.rest.trim());
  for (const tag of typed.tags) p.append("tag", tag);
  return `/browse?${p}`;
}

export function SearchCard({ frame }: { frame: CardFrame }) {
  const id = useId();
  const [text, setText] = useState("");
  const navigate = useNavigate();
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (text.trim()) navigate(browseSearchUrl(text));
  };
  return (
    <Card
      title="Search"
      icon={<Search />}
      className="today-card today-card-compact"
      fold={frame.fold}
      headerProps={frame.headerProps}
    >
      {!frame.fold.folded && (
        <form className="today-search" role="search" onSubmit={submit}>
          <label htmlFor={id} className="visually-hidden">
            Search the archive
          </label>
          <input
            id={id}
            type="search"
            value={text}
            placeholder="Search files, or tag:name"
            spellCheck={false}
            onChange={(e) => setText(e.target.value)}
          />
        </form>
      )}
    </Card>
  );
}
