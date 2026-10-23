/** Settings: one section per area. Filing codes is the first; later areas slot in below it. */
import { FilingCodes } from "../components/codes/FilingCodes";
import { Toolbar } from "../components/ui/Toolbar";

export default function Settings() {
  return (
    <div className="settings">
      <Toolbar title="Settings" />
      <div className="settings-body">
        <FilingCodes />
      </div>
    </div>
  );
}
