/** Settings: a row of section tabs above the section, grouped by what they apply to (this
 * archive, or this browser), and one section at a time at its own address (``/settings/<id>``);
 * ``/settings`` opens the first. A section is listed once it is built (see
 * docs/superpowers/specs/2026-10-23-settings-screen-design.md). */
import type { ReactNode } from "react";
import { Navigate, NavLink, useParams } from "react-router-dom";
import { useArchives } from "../api/client";
import { ArchiveFoldersSettings } from "../components/ArchiveFoldersSettings";
import { AppearanceSettings } from "../components/AppearanceSettings";
import { FilingCodes } from "../components/codes/FilingCodes";
import { IndexingSettings } from "../components/IndexingSettings";
import { FilingRules } from "../components/rules/FilingRules";
import { Toolbar } from "../components/ui/Toolbar";
import { visible } from "../text";

type Section = { id: string; label: string; scope: "archive" | "browser"; render: () => ReactNode };

export const SECTIONS: Section[] = [
  { id: "filing-codes", label: "Filing codes", scope: "archive", render: () => <FilingCodes /> },
  { id: "filing-rules", label: "Filing rules", scope: "archive", render: () => <FilingRules /> },
  { id: "folders", label: "Archive folders", scope: "archive", render: () => <ArchiveFoldersSettings /> },
  { id: "indexing", label: "Indexing", scope: "archive", render: () => <IndexingSettings /> },
  { id: "appearance", label: "Appearance", scope: "browser", render: () => <AppearanceSettings /> },
];

function Group({ title, scope }: { title: string; scope: Section["scope"] }) {
  return (
    <>
      <h4>{title}</h4>
      <ul>
        {SECTIONS.filter((s) => s.scope === scope).map((s) => (
          <li key={s.id}>
            <NavLink to={`/settings/${s.id}`} className="settings-nav-row">
              {s.label}
            </NavLink>
          </li>
        ))}
      </ul>
    </>
  );
}

export default function Settings() {
  const { section } = useParams();
  const archives = useArchives();
  const current = SECTIONS.find((s) => s.id === section);
  if (!current) return <Navigate to={`/settings/${SECTIONS[0].id}`} replace />;
  const archive = archives.data?.archives.find((a) => a.current)?.name;

  return (
    <div className="settings">
      <Toolbar title="Settings" />
      <div className="settings-layout">
        <nav className="settings-nav" aria-label="Settings sections">
          <Group title={archive ? `This archive · ${visible(archive)}` : "This archive"} scope="archive" />
          <Group title="This browser" scope="browser" />
        </nav>
        <div className="settings-body">{current.render()}</div>
      </div>
    </div>
  );
}
