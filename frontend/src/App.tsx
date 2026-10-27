import { CircleAlert, FileQuestion, KeyRound } from "lucide-react";
import { lazy, Suspense, useEffect } from "react";
import { Route, Routes, useLocation } from "react-router-dom";
import { errorText, NOT_SIGNED_IN, type Status, useConfigured, useSignedOut, useStatus } from "./api/client";
import { useIndexErrorsSheet } from "./components/IndexErrors";
import { RecoveryPanel } from "./components/Recovery";
import { hasBand } from "./components/archivePalette";
import { EmptyState } from "./components/ui/EmptyState";
import { Sidebar } from "./components/ui/Sidebar";
import { LookToggle, useLookShortcut } from "./components/LookToggle";
import { CopyJobProgress } from "./components/CopyJobProgress";
import { groupDigits, plural } from "./format";
import { visible } from "./text";

// Each screen loads when first opened, so the start-up bundle stays small.
const Activity = lazy(() => import("./screens/Activity"));
const SettingsScreen = lazy(() => import("./screens/Settings"));
const Ask = lazy(() => import("./screens/Ask"));
const Browse = lazy(() => import("./screens/Browse"));
const FirstRun = lazy(() => import("./screens/FirstRun"));
const Help = lazy(() => import("./screens/Help"));
const Collections = lazy(() => import("./screens/Collections"));
const ConvertImportant = lazy(() => import("./screens/ConvertImportant"));
const ConvertOngoing = lazy(() => import("./screens/ConvertOngoing"));
const Important = lazy(() => import("./screens/Important"));
const Starred = lazy(() => import("./screens/Starred"));
const Inbox = lazy(() => import("./screens/Inbox"));
const Maintenance = lazy(() => import("./screens/Maintenance"));
const Today = lazy(() => import("./screens/Today"));
const Viewer = lazy(() => import("./screens/Viewer"));
const Tags = lazy(() => import("./screens/Tags"));
const Trays = lazy(() => import("./screens/Trays"));

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

/** The whole page while the API answers 401: this browser is not signed in, and the
 * page says how to sign it in (no token is ever handled here). */
function NotSignedIn() {
  return (
    <main className="not-signed-in">
      <EmptyState
        icon={<KeyRound size={40} strokeWidth={1.25} />}
        title="Not signed in"
        hint={NOT_SIGNED_IN}
      />
    </main>
  );
}

/** The viewer window has no sidebar or status polling: just the document. */
export default function App() {
  const viewer = useLocation().pathname.startsWith("/viewer/");
  const signedOut = useSignedOut();
  if (signedOut) return <NotSignedIn />;
  if (viewer) {
    return (
      <Suspense fallback={null}>
        <Routes>
          <Route path="/viewer/:driveId" element={<Viewer />} />
        </Routes>
      </Suspense>
    );
  }
  return <SetupGate />;
}

/** The first-run screen while no archive folder is chosen, else the app. (The viewer
 * window skips this: it makes no status requests.) */
function SetupGate() {
  const configured = useConfigured();
  if (configured.data?.configured === false) {
    return (
      <Suspense fallback={null}>
        <FirstRun />
      </Suspense>
    );
  }
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
  useLookShortcut();
  const band = hasBand(status.data?.archive, status.data?.profiles_count);
  const onActivity = useLocation().pathname === "/activity"; // it has its own panel
  const foot = (
    <>
      {status.data && <StatusBadge status={status.data} />}
      <LookToggle />
      {status.isError && <p className="status-badge status-attention">{errorText(status.error)}</p>}
    </>
  );
  return (
    <div className="app" data-archive-band={band ? "" : undefined} style={band ? ({ "--archive-color": status.data?.archive?.color } as React.CSSProperties) : undefined}>
      {band && <div className="archive-band" aria-hidden="true" />}
      <Sidebar footer={foot} />
      <div className="content">
        <CopyJobProgress />
        {status.data?.archive_available === false && <ArchiveUnavailableBanner />}
        {!onActivity && <RecoveryPanel count={status.data?.recovery_pending ?? 0} />}
        <main>
          <Suspense fallback={null}>
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
              <Route path="/maintenance" element={<Maintenance />} />
              <Route path="/settings/:section?" element={<SettingsScreen />} />
              <Route path="/help" element={<Help />} />
              <Route path="*" element={<NotFound />} />
            </Routes>
          </Suspense>
        </main>
      </div>
    </div>
  );
}
