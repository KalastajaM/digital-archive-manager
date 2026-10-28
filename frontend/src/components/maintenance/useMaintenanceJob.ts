/** One maintenance check as a job on the server: started by a click, polled while it runs,
 * stopped by a click (or by leaving the screen). On opening the screen the latest job of
 * the kind is shown again, so a result is not lost by visiting another screen. */
import { useCallback, useEffect, useRef, useState } from "react";
import {
  errorText,
  forgetMaintenanceJobs,
  getMaintenanceJob,
  latestMaintenanceJob,
  type MaintenanceJob,
  type MaintenanceKind,
  startMaintenanceJob,
  stopMaintenanceJob,
} from "../../api/client";
import { forgetRun, lastRun, noteRun } from "./lastRun";

/** How often a running check is asked how far it has come (a test may change it). */
export const maintenancePolling = { ms: 700 };

export type Check = {
  job: MaintenanceJob | null;
  running: boolean;
  /** The job was asked for and the server has not answered yet. */
  starting: boolean;
  error: string | null;
  start: (days?: number) => void;
  stop: () => void;
  /** Ask the server for the job again (its result without what changed since). */
  reload: () => void;
  /** Forget the check and its result (a running one is ended): as before it ran. */
  reset: () => void;
  /** When it last ended in this browser (epoch milliseconds), if known. */
  ranAt: number | null;
};

export function useMaintenanceJob(kind: MaintenanceKind): Check {
  const [job, setJob] = useState<MaintenanceJob | null>(null);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [ranAt, setRanAt] = useState<number | null>(() => lastRun(kind));
  const epoch = useRef(0);
  const live = useRef<string | null>(null); // the running job's id, to stop it on leaving
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  const follow = useCallback((id: string, mine: number) => {
    const poll = async () => {
      try {
        const next = await getMaintenanceJob(id);
        if (mine !== epoch.current) return;
        setJob(next);
        if (next.state === "running") timer.current = setTimeout(() => void poll(), maintenancePolling.ms);
        else {
          live.current = null;
          noteRun(kind);
          setRanAt(Date.now());
        }
      } catch (e) {
        if (mine === epoch.current) {
          live.current = null;
          setError(errorText(e));
        }
      }
    };
    timer.current = setTimeout(() => void poll(), 20);
  }, [kind]);

  useEffect(() => {
    const mine = ++epoch.current;
    void latestMaintenanceJob(kind)
      .then((found) => {
        if (mine !== epoch.current || !found) return;
        setJob(found);
        if (found.state === "running") {
          live.current = found.job_id;
          follow(found.job_id, mine);
        }
      })
      .catch(() => {}); // nothing to show yet
    return () => {
      epoch.current += 1;
      clearTimeout(timer.current);
      // nothing keeps reading files after the screen is left
      if (live.current) void stopMaintenanceJob(live.current).catch(() => {});
      live.current = null;
    };
  }, [kind, follow]);

  const start = useCallback(
    (days?: number) => {
      if (live.current || starting) return;
      const mine = ++epoch.current;
      clearTimeout(timer.current);
      setError(null);
      setStarting(true);
      startMaintenanceJob(kind, days)
        .then((started) => {
          if (mine !== epoch.current) {
            void stopMaintenanceJob(started.job_id).catch(() => {});
            return;
          }
          live.current = started.job_id;
          setJob(started);
          follow(started.job_id, mine);
        })
        .catch((e) => {
          if (mine === epoch.current) setError(errorText(e));
        })
        .finally(() => setStarting(false));
    },
    [kind, follow, starting],
  );

  const stop = useCallback(() => {
    const id = live.current ?? job?.job_id;
    if (!id) return;
    void stopMaintenanceJob(id)
      .then((stopped) => {
        clearTimeout(timer.current);
        epoch.current += 1;
        live.current = null;
        setJob(stopped);
        noteRun(kind);
        setRanAt(Date.now());
      })
      .catch((e) => setError(errorText(e)));
  }, [job, kind]);

  const reload = useCallback(() => {
    if (!job) return;
    void getMaintenanceJob(job.job_id)
      .then(setJob)
      .catch(() => {});
  }, [job]);

  const reset = useCallback(() => {
    epoch.current += 1;
    clearTimeout(timer.current);
    live.current = null;
    setJob(null);
    setError(null);
    forgetRun(kind);
    setRanAt(null);
    void forgetMaintenanceJobs(kind).catch((e) => setError(errorText(e)));
  }, [kind]);

  return { job, running: job?.state === "running", starting, error, start, stop, reload, reset, ranAt };
}
