import { CircleAlert, Info, TriangleAlert, X } from "lucide-react";
import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { visible } from "../text";
import { IconButton } from "./ui/IconButton";

export type ToastKind = "info" | "warning" | "error";
export type ToastAction = { label: string; run: () => void };
/** The action every toast for a reversible change offers, worded the same everywhere
 * ("Reopen" stays for Mark paid, which is a state, not an undo). */
export const undoAction = (run: () => void): ToastAction => ({ label: "Undo", run });
export type Toast = {
  id: number;
  kind: ToastKind;
  text: string;
  action?: ToastAction;
  /** More than one button (e.g. Open and Undo), shown after ``action``. */
  actions?: ToastAction[];
};
type NewToast = Omit<Toast, "id">;

const TIMEOUT_MS: Record<ToastKind, number> = { info: 10_000, warning: 20_000, error: 20_000 };
const ICON: Record<ToastKind, typeof Info> = { info: Info, warning: TriangleAlert, error: CircleAlert };

const ToastContext = createContext<(toast: NewToast) => void>(() => {});
/** Registers one blocker; the returned function releases it. */
const BlockContext = createContext<() => () => void>(() => () => {});

/** Show a toast: ``const toast = useToast(); toast({ kind: "info", text: "Done" })``. */
export const useToast = () => useContext(ToastContext);

/** While ``blocked``, every toast action button is disabled (e.g. a call is in flight
 * or a dialog is open), so an action can never start a second dialog or request.
 * Each caller holds its own token: actions stay disabled while any caller blocks. */
export function useBlockToastActions(blocked: boolean) {
  const register = useContext(BlockContext);
  useEffect(() => {
    if (!blocked) return;
    return register();
  }, [blocked, register]);
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [blockers, setBlockers] = useState(0);
  const blocked = blockers > 0;
  const register = useCallback(() => {
    let held = true;
    setBlockers((n) => n + 1);
    return () => {
      if (!held) return; // a token is released once
      held = false;
      setBlockers((n) => n - 1);
    };
  }, []);
  const next = useRef(1);
  // the auto-dismiss timers, cleared on unmount so none fires into a page that is gone
  const timers = useRef(new Set<ReturnType<typeof setTimeout>>());
  useEffect(() => {
    const pending = timers.current;
    return () => {
      for (const t of pending) clearTimeout(t);
      pending.clear();
    };
  }, []);

  const dismiss = useCallback((id: number) => {
    setToasts((all) => all.filter((t) => t.id !== id));
  }, []);

  const show = useCallback(
    (toast: NewToast) => {
      const id = next.current++;
      setToasts((all) => [...all, { ...toast, id }]);
      const timer = setTimeout(() => {
        timers.current.delete(timer);
        dismiss(id);
      }, TIMEOUT_MS[toast.kind]);
      timers.current.add(timer);
    },
    [dismiss],
  );

  const value = useMemo(() => show, [show]);
  return (
    <ToastContext.Provider value={value}>
      <BlockContext.Provider value={register}>{children}</BlockContext.Provider>
      <div className="toasts" role="status" aria-live="polite">
        {toasts.map((t) => {
          const Icon = ICON[t.kind];
          const actions = [...(t.action ? [t.action] : []), ...(t.actions ?? [])];
          return (
            <div key={t.id} className={`toast toast-${t.kind}`}>
              <Icon className="toast-icon" size={16} aria-hidden="true" />
              <span className="toast-text">{visible(t.text)}</span>
              {/* the buttons on their own row under the text, which keeps the full width */}
              {actions.length > 0 && (
                <div className="toast-actions">
                  {actions.map((a, i) => (
                    <button
                      key={`${t.id}-${i}`}
                      type="button"
                      className="toast-action"
                      disabled={blocked}
                      onClick={() => {
                        dismiss(t.id);
                        a.run();
                      }}
                    >
                      {a.label}
                    </button>
                  ))}
                </div>
              )}
              <IconButton
                icon={<X size={14} />}
                label="Dismiss"
                tipSide="above"
                onClick={() => dismiss(t.id)}
                className="toast-dismiss"
              />
            </div>
          );
        })}
      </div>
    </ToastContext.Provider>
  );
}
