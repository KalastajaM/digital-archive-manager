/** Maintenance (``/maintenance``): checks the owner starts, one by one. Nothing here runs
 * by itself or in the background: a check starts when its button is clicked, shows its
 * progress, can be stopped, and ends in a list. Anything that changes the archive goes
 * through the usual preview, confirm and Undo. Each card folds to one line, and Reset
 * forgets the results (one check's, or all of them) without changing the archive. */
import { useState } from "react";
import { errorText, forgetMaintenanceJobs } from "../api/client";
import { Duplicates } from "../components/maintenance/Duplicates";
import { BrokenLinks, EmptyFolders, LabelClashes, Missing, Names, UnfinishedCopies, Waiting } from "../components/maintenance/ListChecks";
import { forgetRun } from "../components/maintenance/lastRun";
import { Moved } from "../components/maintenance/Moved";
import { Remounted } from "../components/maintenance/Remounted";
import { MaintenanceView, useMaintenanceView } from "../components/maintenance/view";
import { useToast } from "../components/Toasts";
import { visible } from "../text";

export default function Maintenance() {
  return (
    <MaintenanceView>
      <Screen />
    </MaintenanceView>
  );
}

function Screen() {
  const view = useMaintenanceView();
  const toast = useToast();
  // a new key mounts the checks afresh, with nothing to show once their jobs are forgotten
  const [round, setRound] = useState(0);
  const resetAll = () =>
    void forgetMaintenanceJobs()
      .then(() => {
        forgetRun();
        setRound((r) => r + 1);
      })
      .catch((e) => toast({ kind: "error", text: `Not reset: ${visible(errorText(e))}` }));
  const collapseAll = view && (
    <button type="button" className="quiet" onClick={() => view.setAll(!view.allFolded)}>
      {view.allFolded ? "Expand all" : "Collapse all"}
    </button>
  );
  const resetAllButton = (
    <button
      type="button"
      data-tip="Reset all: forget every result, as if no check had run. Nothing in the archive changes."
      onClick={resetAll}
    >
      Reset all
    </button>
  );
  return (
    <div className="maintenance-screen">
      <header className="maintenance-head">
        <div className="maintenance-head-text">
          <h2>Maintenance</h2>
          <span className="maintenance-sub">
            Checks you start yourself. Nothing here runs in the background, and every fix is previewed and can be undone.
          </span>
        </div>
        {collapseAll}
        {resetAllButton}
      </header>
      <div className="maintenance-body" key={round}>
        <Duplicates />
        <EmptyFolders />
        <BrokenLinks />
        <Missing />
        <Names />
        <Waiting />
        <LabelClashes />
        <UnfinishedCopies />
        <Moved />
        <Remounted />
      </div>
    </div>
  );
}
