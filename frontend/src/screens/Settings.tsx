/** Settings: one section per area. Filing codes first, then Print stickers; later areas slot in below. */
import { FilingCodes } from "../components/codes/FilingCodes";
import { PrintStickers } from "../components/codes/PrintStickers";
import { Toolbar } from "../components/ui/Toolbar";

export default function Settings() {
  return (
    <div className="settings">
      <Toolbar title="Settings" />
      <div className="settings-body">
        <FilingCodes />
        <PrintStickers />
      </div>
    </div>
  );
}
