import { CircleAlert, FileQuestion } from "lucide-react";
import { useEffect } from "react";
import { Route, Routes, useLocation } from "react-router-dom";
import { errorText, type Status, useConfigured, useStatus } from "./api/client";
import { useIndexErrorsSheet } from "./components/IndexErrors";
import { RecoveryPanel } from "./components/Recovery";
import { hasBand } from "./components/archivePalette";
import { EmptyState } from "./components/ui/EmptyState";
import { Sidebar } from "./components/ui/Sidebar";
import Activity from "./screens/Activity";
import SettingsScreen from "./screens/Settings";
import Ask from "./screens/Ask";
import Browse from "./screens/Browse";
import FirstRun from "./screens/FirstRun";
import Help from "./screens/Help";
import Collections from "./screens/Collections";
import ConvertImportant from "./screens/ConvertImportant";
import ConvertOngoing from "./screens/ConvertOngoing";
import Important from "./screens/Important";
import Starred from "./screens/Starred";
import Inbox from "./screens/Inbox";
import Today from "./screens/Today";
import Viewer from "./screens/Viewer";
import Tags from "./screens/Tags";
import Trays from "./screens/Trays";
import { groupDigits, plural } from "./format";
import { visible } from "./text";

/** The status line at the sidebar's foot; problems are listed in its tooltip. The whole
 * line is a button: it opens the Index sheet (totals, files that could not be read). */
function StatusBadge({ status }: { status: Status }) {
  const sheet = useIndexErrorsSheet();
  const waiting = status.pending + status.cloud_pending;
  const parts: string[] = [`${groupDigits(status.inbox_count)} in inbox`, `${groupDigits(status.indexed)} searchable`];
  const page1 = status.page1;
  if (page1 && page1.total > 0 && page1.read < page1.total) {
    parts.push(`page 1 read ${groupDigits(page1.read)} of ${groupDigits(page1.total)}`);
  }
  if (waiting > 0) parts.push(`${groupDigits(waiting)} waiting`);
  if (status.unsupported > 0) parts.push(`${groupDigits(status.unsupported)} not readable`);
  if (status.errors > 0) parts.push(plural(status.errors, "error"));
  if (status.rule_errors.length > 0) parts.push(`${status.rule_errors.length} rule file errors`);
  if (status.tray_errors.length > 0) parts.push(`${status.tray_errors.length} tray file errors`);
  const problems = [...status.rule_errors, ...status.tray_errors];
  const title = problems.map((r) => visible(`${r.file}: ${r.message}`)).join("\n") || undefined;
  const attention = status.errors > 0 || problems.length > 0;
  return (
    <>
      <p className={attention ? "status-badge status-attention" : "status-badge"} title={title} data-testid="status-line">
        <button type="button" className="link-button status-line-button" onClick={sheet.open}>
          {parts.join(" · ")}
        </button>
      </p>
      {sheet.view}
    </>
  );
}

function ArchiveUnavailableBanner() {
  return (
    <section className="banner" aria-label="Archive unavailable">
      <CircleAlert className="banner-icon" size={16} aria-hidden="true" />
      <p>
        The archive folder is not available. Check that your cloud drive (Google Drive, OneDrive, Dropbox, ...) is running and signed in,
        and that <code>archive_root</code> in <code>config/settings.yaml</code> is right. Nothing
        is scanned until it is back.
      </p>
    </section>
  );
}

function NotFound() {
  return (
    <EmptyState
      icon={<FileQuestion size={40} strokeWidth={1.25} />}
      title="Not found"
      hint="There is no screen at this address."
    />
  );
}

/** The viewer window has no sidebar or status polling: just the document. */
export default function App() {
  const viewer = useLocation().pathname.startsWith("/viewer/");
  if (viewer) {
    return (
      <Routes>
        <Route path="/viewer/:driveId" element={<Viewer />} />
      </Routes>
    );
  }
  return <SetupGate />;
}

/** The first-run screen while no archive folder is chosen, else the app. (The viewer
 * window skips this: it makes no status requests.) */
function SetupGate() {
  const configured = useConfigured();
  if (configured.data?.configured === false) return <FirstRun />;
  if (configured.isPending) return null; // one quick request; the app (or setup) is next
  return <Shell />;
}

/** The window title names the archive once there are several; a coloured band along the
 * top marks every archive but "Main", so a test archive is never mistaken for the real one. */
function useArchiveChrome(status: Status | undefined) {
  const name = status?.archive?.name;
  const several = (status?.profiles_count ?? 1) > 1;
  useEffect(() => {
    document.title = several && name ? `${visible(name)} — Archive` : "Archive";
  }, [several, name]);
}

function Shell() {
  const status = useStatus();
  useArchiveChrome(status.data);
  const band = hasBand(status.data?.archive, status.data?.profiles_count);
  const onActivity = useLocation().pathname === "/activity"; // it has its own panel
  const foot = (
    <>
      {status.data && <StatusBadge status={status.data} />}
      {status.isError && <p className="status-badge status-attention">{errorText(status.error)}</p>}
    </>
  );
  return (
    <div className="app" data-archive-band={band ? "" : undefined} style={band ? ({ "--archive-color": status.data?.archive?.color } as React.CSSProperties) : undefined}>
      {band && <div className="archive-band" aria-hidden="true" />}
      <Sidebar footer={foot} />
      <div className="content">
        {status.data?.archive_available === false && <ArchiveUnavailableBanner />}
        {!onActivity && <RecoveryPanel count={status.data?.recovery_pending ?? 0} />}
        <main>
          <Routes>
            <Route path="/" element={<Today />} />
            <Route path="/inbox" element={<Inbox />} />
            <Route path="/trays/:trayId?" element={<Trays />} />
            <Route path="/collections/:id?" element={<Collections />} />
            <Route path="/ongoing" element={<ConvertOngoing />} />
            <Route path="/starred" element={<Starred />} />
            <Route path="/important" element={<Important />} />
            <Route path="/important/convert" element={<ConvertImportant />} />
            <Route path="/browse" element={<Browse />} />
            <Route path="/tags" element={<Tags />} />
            <Route path="/ask" element={<Ask />} />
            <Route path="/activity" element={<Activity />} />
            <Route path="/settings/:section?" element={<SettingsScreen />} />
            <Route path="/help" element={<Help />} />
            <Route path="*" element={<NotFound />} />
          </Routes>
        </main>
      </div>
    </div>
  );
}
