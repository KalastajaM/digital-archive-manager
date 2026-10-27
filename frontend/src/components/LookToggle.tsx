/** The temporary ways to switch the look (Classic or New) outside Settings: a small toggle
 * in the sidebar footer and the Ctrl+Alt+L shortcut. Both go when the redesign is done. */
import { type Look, useStyle } from "../appearance";
import { isTyping, useKeydown } from "../keyboard";
import { useToast } from "./Toasts";
import { Segmented } from "./ui/Segmented";

const OPTIONS: { value: Look; label: string }[] = [
  { value: "classic", label: "Classic" },
  { value: "new", label: "New" },
];

export const LOOK_NAME: Record<Look, string> = { classic: "Classic", new: "New" };

/** Switches the look and says which one is on. */
function useChooseLook() {
  const [look, setLook] = useStyle();
  const toast = useToast();
  const choose = (next: Look) => {
    if (next === look) return;
    setLook(next);
    toast({ kind: "info", text: `Look: ${LOOK_NAME[next]}` });
  };
  return [look, choose] as const;
}

/** Ctrl+Alt+L toggles the look anywhere, except while typing in a field (like the app's
 * other shortcuts). ``e.code``, not ``e.key``: Alt+L types a different letter on a Mac. */
export function useLookShortcut() {
  const [look, choose] = useChooseLook();
  useKeydown((e) => {
    if (e.code !== "KeyL" || !e.ctrlKey || !e.altKey || e.metaKey || e.shiftKey) return;
    if (isTyping(e.target)) return;
    e.preventDefault();
    choose(look === "new" ? "classic" : "new");
  });
}

export function LookToggle() {
  const [look, choose] = useChooseLook();
  return (
    <div className="look-toggle">
      <span className="look-toggle-label" id="look-toggle-label">
        Look
      </span>
      <Segmented options={OPTIONS} value={look} onChange={choose} ariaLabel="Look" className="look-toggle-seg" />
    </div>
  );
}
