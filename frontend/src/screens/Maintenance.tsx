/** Maintenance (``/maintenance``): checks the owner starts, one by one. Nothing here runs
 * by itself or in the background: a check starts when its button is clicked, shows its
 * progress, can be stopped, and ends in a list. Anything that changes the archive goes
 * through the usual preview, confirm and Undo. Each card folds to one line, and Reset
 * forgets the results (one check's, or all of them) without changing the archive. */
import { ChevronsDownUp, ChevronsUpDown, RotateCcw } from "lucide-react";
import { useState } from "react";
import { errorText, forgetMaintenanceJobs } from "../api/client";
import { Duplicates } from "../components/maintenance/Duplicates";
import { BrokenLinks, EmptyFolders, LabelClashes, Missing, Names, UnfinishedCopies, Waiting } from "../components/maintenance/ListChecks";
import { Moved } from "../components/maintenance/Moved";
import { Remounted } from "../components/maintenance/Remounted";
import { MaintenanceView, useMaintenanceView } from "../components/maintenance/view";
import { useToast } from "../components/Toasts";
import { IconButton } from "../components/ui/IconButton";
import { Toolbar } from "../components/ui/Toolbar";
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
      .then(() => setRound((r) => r + 1))
      .catch((e) => toast({ kind: "error", text: `Not reset: ${visible(errorText(e))}` }));
  return (
    <div className="maintenance-screen">
      <Toolbar
        title="Maintenance"
        subtitle="Checks you start yourself"
        className="maintenance-toolbar"
        actions={
          <>
            {view && (
              <IconButton
                icon={view.allFolded ? <ChevronsUpDown size={16} /> : <ChevronsDownUp size={16} />}
                label={view.allFolded ? "Expand all" : "Collapse all"}
                onClick={() => view.setAll(!view.allFolded)}
              />
            )}
            <IconButton
              icon={<RotateCcw size={16} />}
              label="Reset all"
              tip="Reset all: forget every result, as if no check had run. Nothing in the archive changes."
              onClick={resetAll}
            />
          </>
        }
      />
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
