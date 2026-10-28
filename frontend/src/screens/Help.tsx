/** Help: the user guide, docs/guide.md, bundled at build time so it works offline and
 * stays the one source (the same file reads on GitHub). Its contents run down the left;
 * the guide's own Contents list is left out here, the side list replaces it. A heading's
 * id is GitHub's anchor for it, so `/help#trays` and the guide's own `#trays` links both
 * work. Links to the technical reference open it on GitHub, in a new tab. The diagrams of
 * how dam works, and the one of Relatives, sit under their section's heading (they are
 * app code, so GitHub has the text only). */
import { type MouseEvent, type ReactElement, type ReactNode, useEffect, useMemo, useRef } from "react";
import Markdown, { type Components } from "react-markdown";
import { useLocation, useNavigate } from "react-router-dom";
import remarkGfm from "remark-gfm";
import guide from "../../../docs/guide.md?raw";
import { HowDamWorks, RelativesDiagram } from "../components/HowDamWorks";
import { Toolbar } from "../components/ui/Toolbar";

const DOCS_URL = "https://github.com/KalastajaM/digital-archive-manager/blob/main/docs/";
/** The section the diagrams are shown under. */
export const DIAGRAMS_SECTION = "how-dam-works";
/** Diagrams drawn as code (not screenshots, so they never go stale), under their section's heading. */
const SECTION_DIAGRAMS: Record<string, () => ReactElement> = {
  [DIAGRAMS_SECTION]: HowDamWorks,
  relatives: RelativesDiagram,
};

/** GitHub's anchor for a heading: lower case, punctuation dropped, spaces as hyphens. */
export function slug(text: string): string {
  return text
    .trim()
    .toLowerCase()
    .replace(/[^\p{L}\p{N}\s_-]/gu, "")
    .replace(/\s/g, "-");
}

export type Heading = { level: 2 | 3; text: string; id: string };

/** The guide as Help shows it: without the title (the toolbar has it) and without the
 * Contents section (the side list). */
export function helpMarkdown(source: string): string {
  return source.replace(/^# .*\n/m, "").replace(/^## Contents\n[\s\S]*?(?=^## )/m, "");
}

/** The ## and ### headings, in order (fenced code is skipped: a `#` comment is no heading). */
export function headings(markdown: string): Heading[] {
  const out: Heading[] = [];
  let fenced = false;
  for (const line of markdown.split("\n")) {
    if (line.startsWith("```")) fenced = !fenced;
    const m = !fenced && /^(##|###) (.+)$/.exec(line);
    if (m) out.push({ level: m[1].length as 2 | 3, text: m[2].trim(), id: slug(m[2]) });
  }
  return out;
}

function textOf(children: ReactNode): string {
  if (typeof children === "string" || typeof children === "number") return String(children);
  if (Array.isArray(children)) return children.map(textOf).join("");
  return "";
}

function scrollTo(id: string) {
  document.getElementById(id)?.scrollIntoView({ block: "start" });
}

export default function Help() {
  const markdown = useMemo(() => helpMarkdown(guide), []);
  const toc = useMemo(() => headings(markdown), [markdown]);
  const { hash } = useLocation();
  const navigate = useNavigate();
  const current = decodeURIComponent(hash.slice(1)) || toc[0]?.id; // the first section, at the top
  const article = useRef<HTMLElement>(null);

  useEffect(() => {
    if (current) scrollTo(current);
    else if (article.current) article.current.scrollTop = 0;
  }, [current]);

  /** An in-guide link: show the section and keep it in the address, for Back. */
  const go = (e: MouseEvent, id: string) => {
    e.preventDefault();
    if (id === current) scrollTo(id);
    else navigate({ hash: id });
  };

  const components: Components = {
    h2: ({ children }) => {
      const id = slug(textOf(children));
      const heading = <h2 id={id}>{children}</h2>;
      const Diagram = SECTION_DIAGRAMS[id];
      return Diagram ? <>{heading}<Diagram /></> : heading;
    },
    h3: ({ children }) => <h3 id={slug(textOf(children))}>{children}</h3>,
    a: ({ href = "", children }) => {
      if (href.startsWith("#")) {
        return (
          <a href={`/help${href}`} onClick={(e) => go(e, href.slice(1))}>
            {children}
          </a>
        );
      }
      const external = /^https?:/.test(href) ? href : DOCS_URL + href;
      return (
        <a href={external} target="_blank" rel="noreferrer">
          {children}
        </a>
      );
    },
  };

  return (
    <div className="help">
      <Toolbar title="Help" subtitle="User guide" />
      <div className="help-body">
        <nav className="help-toc" aria-label="Contents">
          <ul>
            {toc.map((h) => (
              <li key={h.id} className={h.level === 3 ? "help-toc-sub" : undefined}>
                <a
                  href={`/help#${h.id}`}
                  aria-current={h.id === current ? "location" : undefined}
                  onClick={(e) => go(e, h.id)}
                >
                  {h.text}
                </a>
              </li>
            ))}
          </ul>
        </nav>
        <article className="help-article" ref={article}>
          <Markdown remarkPlugins={[remarkGfm]} components={components}>
            {markdown}
          </Markdown>
        </article>
      </div>
    </div>
  );
}
