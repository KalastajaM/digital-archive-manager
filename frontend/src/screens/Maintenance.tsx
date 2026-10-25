/** Maintenance (``/maintenance``): checks the owner starts, one by one. Nothing here runs
 * by itself or in the background: a check starts when its button is clicked, shows its
 * progress, can be stopped, and ends in a list. Anything that changes the archive goes
 * through the usual preview, confirm and Undo. */
import { Wrench } from "lucide-react";
import { Duplicates } from "../components/maintenance/Duplicates";
import { BrokenLinks, EmptyFolders, Missing, Names, Waiting } from "../components/maintenance/ListChecks";
import { Toolbar } from "../components/ui/Toolbar";

export default function Maintenance() {
  return (
    <div className="maintenance-screen">
      <Toolbar title="Maintenance" subtitle="Checks you start yourself" />
      <div className="maintenance-body">
        <p className="hint">
          <Wrench size={12} aria-hidden="true" /> Nothing here runs by itself. Each check starts when you click it and
          can be stopped; what it finds is a list, and every change goes through a preview you confirm, with Undo.
        </p>
        <Duplicates />
        <EmptyFolders />
        <BrokenLinks />
        <Missing />
        <Names />
        <Waiting />
      </div>
    </div>
  );
}
