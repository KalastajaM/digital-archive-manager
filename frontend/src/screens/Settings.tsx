/** Settings: a row of section tabs above the section, grouped by what they apply to (this
 * archive, or this browser), and one section at a time at its own address (``/settings/<id>``);
 * ``/settings`` opens the first. A section is listed once it is built. */
import type { ReactNode } from "react";
import { Navigate, NavLink, useParams } from "react-router-dom";
import { useArchives } from "../api/client";
import { ArchiveFoldersSettings } from "../components/ArchiveFoldersSettings";
import { AppearanceSettings } from "../components/AppearanceSettings";
import { SnapshotSettings } from "../components/SnapshotSettings";
import { FilingCodes } from "../components/codes/FilingCodes";
import { AddressAreaSettings } from "../components/AddressAreaSettings";
import { CountriesSettings } from "../components/CountriesSettings";
import { IndexingSettings } from "../components/IndexingSettings";
import { SendersSettings } from "../components/SendersSettings";
import { FilingRules } from "../components/rules/FilingRules";
import { Toolbar } from "../components/ui/Toolbar";
import { useStyle } from "../appearance";
import { visible } from "../text";

/** ``newOnly``: built for the New look only (Classic is kept, not developed). */
type Section = { id: string; label: string; scope: "archive" | "browser"; render: () => ReactNode; newOnly?: boolean };

export const SECTIONS: Section[] = [
  { id: "filing-codes", label: "Filing codes", scope: "archive", render: () => <FilingCodes /> },
  { id: "filing-rules", label: "Filing rules", scope: "archive", render: () => <FilingRules /> },
  { id: "folders", label: "Archive folders", scope: "archive", render: () => <ArchiveFoldersSettings /> },
  { id: "indexing", label: "Indexing", scope: "archive", render: () => <IndexingSettings /> },
  { id: "countries", label: "Reading documents", scope: "archive", render: () => (
      <>
        <CountriesSettings />
        <AddressAreaSettings />
      </>
    ),
  },
  { id: "senders", label: "Senders", scope: "archive", render: () => <SendersSettings />, newOnly: true },
  { id: "snapshots", label: "Snapshots", scope: "archive", render: () => <SnapshotSettings /> },
  { id: "appearance", label: "Appearance", scope: "browser", render: () => <AppearanceSettings /> },
];

/** The sections the current look shows. */
function useSections(): Section[] {
  const [look] = useStyle();
  return SECTIONS.filter((s) => look === "new" || !s.newOnly);
}

function Group({ title, scope }: { title: string; scope: Section["scope"] }) {
  const sections = useSections();
  return (
    <>
      <h4>{title}</h4>
      <ul>
        {sections.filter((s) => s.scope === scope).map((s) => (
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
  const sections = useSections();
  const current = sections.find((s) => s.id === section);
  if (!current) return <Navigate to={`/settings/${sections[0].id}`} replace />;
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
