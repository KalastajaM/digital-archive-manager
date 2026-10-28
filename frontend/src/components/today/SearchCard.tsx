/** Today's Search card: type, press Enter, and Browse opens with that search (words and
 * filters such as `tag:name`, as in Browse's own box; the ? lists them). It folds and
 * moves like every Today card. */
import { Search } from "lucide-react";
import { type FormEvent, useId, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { readQuery, serializeQuery } from "../../searchFilters";
import { SearchHelp } from "../SearchHelp";
import { Card } from "../ui/Card";
import type { CardFrame } from "./frame";

/** The Browse address for what was typed: the whole query in ?q= (a trailing filter
 * counts as finished). */
export function browseSearchUrl(text: string): string {
  const { words, filters } = readQuery(text);
  const p = new URLSearchParams();
  const whole = serializeQuery(words, filters);
  if (whole) p.set("q", whole);
  return `/browse?${p}`;
}

export function SearchCard({ frame, Shell = Card }: { frame: CardFrame; Shell?: typeof Card }) {
  const id = useId();
  const [text, setText] = useState("");
  const input = useRef<HTMLInputElement>(null);
  const navigate = useNavigate();
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (text.trim()) navigate(browseSearchUrl(text));
  };
  return (
    <Shell
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
            ref={input}
            type="search"
            value={text}
            placeholder="Search files, or tag:name"
            spellCheck={false}
            onChange={(e) => setText(e.target.value)}
          />
          <SearchHelp
            onUse={(example) => {
              setText((t) => (t.trim() ? `${t.trimEnd()} ` : "") + example);
              input.current?.focus();
            }}
          />
        </form>
      )}
    </Shell>
  );
}
