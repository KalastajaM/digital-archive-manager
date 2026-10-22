import { ChevronsUpDown } from "lucide-react";
import { useState } from "react";
import { type Archive, errorText, navigation, switchArchive, useArchives } from "../api/client";
import { visible } from "../text";
import { AddArchive } from "./AddArchive";
import { ManageArchives } from "./ManageArchives";
import { useToast } from "./Toasts";
import { type MenuEntry, Menu } from "./ui/Menu";

const FALLBACK_COLOR = "#3b6fd4";

/** The archive menu at the top of the sidebar: the archive shown (name and colour dot),
 * the list to switch to, "Add archive…" and "Manage archives…". Switching closes this
 * archive's background work and opens the other in the same window; an archive that
 * another dam window has open is listed but cannot be switched to. */
export function ArchiveSwitcher() {
  const list = useArchives();
  const toast = useToast();
  const [sheet, setSheet] = useState<"add" | "manage" | null>(null);
  const [switching, setSwitching] = useState(false);
  const archives = list.data?.archives ?? [];
  const current = archives.find((a) => a.current) ?? null;
  const name = current ? visible(current.name) : "Archive";
  const color = current?.color ?? FALLBACK_COLOR;
  const canSwitch = list.data?.can_switch ?? true;

  const pick = (a: Archive) => {
    setSwitching(true);
    switchArchive(a.id)
      .then(() => navigation.leave())
      .catch((e: unknown) => {
        toast({ kind: "error", text: `Could not open ${visible(a.name)}: ${visible(errorText(e))}` });
        setSwitching(false);
      });
  };
  const reason = (a: Archive) =>
    a.in_use_elsewhere
      ? `Open in another window${a.port ? ` (port ${a.port})` : ""}`
      : !canSwitch
        ? "Start dam with --archive to open it"
        : undefined;
  const entries: MenuEntry[] = [
    ...archives.map((a): MenuEntry => {
      const why = a.current ? undefined : reason(a);
      return {
        label: visible(a.name),
        swatch: a.color,
        checked: a.current,
        disabled: !a.current && (switching || why !== undefined),
        reason: why,
        onSelect: () => {
          if (!a.current) pick(a);
        },
      };
    }),
    ...(archives.length > 0 ? (["separator"] as const) : []),
    { label: "Add archive…", onSelect: () => setSheet("add") },
    { label: "Manage archives…", onSelect: () => setSheet("manage") },
  ];
  return (
    <div className="sidebar-brand">
      <h1>
        <Menu
          label={`Archive: ${name}`}
          icon={<span className="archive-dot" style={{ background: color }} />}
          text={
            <>
              <span className="archive-name">{name}</span>
              <ChevronsUpDown className="archive-chevron" size={12} strokeWidth={2} aria-hidden="true" />
            </>
          }
          triggerClassName="archive-button"
          entries={entries}
        />
      </h1>
      <AddArchive open={sheet === "add"} onClose={() => setSheet(null)} />
      <ManageArchives open={sheet === "manage"} onClose={() => setSheet(null)} />
    </div>
  );
}
