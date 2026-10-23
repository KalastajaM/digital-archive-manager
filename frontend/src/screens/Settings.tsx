/** Settings: one section per area. Appearance (the whole app) first, then this archive's
 * Filing codes and Print stickers; later areas slot in below (see
 * docs/superpowers/specs/2026-10-23-settings-screen-design.md). */
import { AppearanceSettings } from "../components/AppearanceSettings";
import { FilingCodes } from "../components/codes/FilingCodes";
import { PrintStickers } from "../components/codes/PrintStickers";
import { Toolbar } from "../components/ui/Toolbar";

export default function Settings() {
  return (
    <div className="settings">
      <Toolbar title="Settings" />
      <div className="settings-body">
        <AppearanceSettings />
        <FilingCodes />
        <PrintStickers />
      </div>
    </div>
  );
}
