/** A rule test that runs on the server in the background: it starts a moment after the
 * rule last changed, is polled for what it has found so far, and ends (is dropped) when the
 * rule changes again or the sheet closes. One test per hook, so one per open sheet. */
import { useCallback, useEffect, useRef, useState } from "react";
import {
  dropReplayJob,
  errorText,
  getReplayJob,
  readReplayJobNow,
  type Replay,
  type ReplayJob,
  type RuleIn,
  startReplayJob,
  stopReplayJob,
} from "../../api/client";

export const REPLAY_DELAY_MS = 400;
/** How often a running test is asked how far it has come (a test may change it). */
export const jobPolling = { ms: 1000 };

const LIVE: ReplayJob["state"][] = ["running", "waiting"];

export type JobRequest = {
  rule: RuleIn;
  replaces?: string | null;
  placeAbove?: string | null;
  nearDriveId?: string | null;
};

export type JobTest = {
  /** The latest result, of the rule ``resultKey`` (a newer one is on its way when it differs from the key now). */
  replay: Replay | undefined;
  resultKey: string | null;
  /** "running", "waiting" (all looked at, some documents wait for page 1), "done", "stopped", "error"; null before the server answered. */
  state: ReplayJob["state"] | null;
  /** Documents gone through, of how many (0 while the server prepares the test). */
  looked: number;
  total: number;
  /** Documents waiting for page 1 to be read. */
  waiting: number;
  error: string | null;
  stop: () => void;
  /** Test again now, from the start. */
  restart: () => void;
  /** Have page 1 of the documents the test waits for read now; the test picks them up as they arrive. */
  readNow: () => void;
  /** Page 1 of those documents was asked for now and is being read. */
  readingNow: boolean;
};

const newSheetId = () =>
  typeof crypto !== "undefined" && "randomUUID" in crypto ? crypto.randomUUID() : `sheet-${Math.random().toString(36).slice(2)}${Date.now()}`;

export function useReplayJob({
  enabled,
  jobKey,
  request,
  delayMs = REPLAY_DELAY_MS,
}: {
  enabled: boolean;
  /** Identifies the rule being tested: when it changes, the test starts over. */
  jobKey: string;
  request: JobRequest;
  delayMs?: number;
}): JobTest {
  const sheet = useRef(newSheetId());
  const latest = useRef(request);
  latest.current = request;
  const epoch = useRef(0);
  const jobId = useRef<string | null>(null);
  const keyNow = useRef(jobKey);
  const version = useRef(0); // of the result held for this job: the poll asks only for newer
  const [again, setAgain] = useState(0);
  const immediate = useRef(false); // a restart does not wait for the rule to settle
  // The result of an earlier rule stays on screen until the new test has its first one.
  const [view, setView] = useState<{ job: ReplayJob | null; held: { replay: Replay; key: string } | null }>({
    job: null,
    held: null,
  });
  const [error, setError] = useState<string | null>(null);
  const [readingNow, setReadingNow] = useState(false);

  // A test that ended (stopped, done, error) stays ended: a poll sent before Stop can answer
  // after it, and must not bring "running" back.
  const ended = useRef(false);

  /** Shows ``job``; false (and nothing shown) for a late "running" answer after the end. */
  const take = useCallback((job: ReplayJob, key: string) => {
    const live = LIVE.includes(job.state);
    if (ended.current && live) return false;
    if (!live) ended.current = true;
    if (job.result) version.current = job.version;
    setView((v) => ({ job, held: job.result ? { replay: job.result, key } : v.held }));
    return true;
  }, []);

  useEffect(() => {
    keyNow.current = jobKey;
    if (!enabled) return;
    const mine = ++epoch.current;
    const alive = () => mine === epoch.current;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let poll: ReturnType<typeof setTimeout> | undefined;
    const follow = async (id: string) => {
      try {
        const job = await getReplayJob(id, version.current);
        if (!alive() || !take(job, jobKey)) return;
        if (LIVE.includes(job.state)) poll = setTimeout(() => void follow(id), jobPolling.ms);
      } catch (e) {
        if (alive()) setError(errorText(e));
      }
    };
    const start = async () => {
      try {
        const job = await startReplayJob({ ...latest.current, sheet: sheet.current });
        if (!alive()) {
          void dropReplayJob(job.job_id).catch(() => {});
          return;
        }
        jobId.current = job.job_id;
        take(job, jobKey);
        poll = setTimeout(() => void follow(job.job_id), 20);
      } catch (e) {
        if (alive()) setError(errorText(e));
      }
    };
    setError(null);
    setReadingNow(false);
    version.current = 0;
    ended.current = false;
    setView((v) => (v.job === null ? v : { ...v, job: null }));
    const wait = immediate.current ? 0 : delayMs;
    immediate.current = false;
    timer = setTimeout(() => void start(), wait);
    return () => {
      epoch.current += 1;
      clearTimeout(timer);
      clearTimeout(poll);
      timer = poll = undefined;
      const id = jobId.current;
      jobId.current = null;
      if (id) void dropReplayJob(id).catch(() => {});
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, jobKey, again, delayMs]);

  const stop = useCallback(() => {
    const id = jobId.current;
    if (!id) return;
    void stopReplayJob(id)
      .then((job) => {
        if (jobId.current === id) take(job, keyNow.current);
      })
      .catch((e) => setError(errorText(e)));
  }, [take]);
  const readNow = useCallback(() => {
    const id = jobId.current;
    if (!id) return;
    setReadingNow(true);
    void readReplayJobNow(id).catch((e) => {
      setReadingNow(false);
      setError(errorText(e));
    });
  }, []);
  const restart = useCallback(() => {
    immediate.current = true;
    setAgain((n) => n + 1);
  }, []);

  return {
    replay: view.held?.replay,
    resultKey: view.held?.key ?? null,
    state: view.job?.state ?? null,
    looked: view.job?.looked_at ?? 0,
    total: view.job?.total ?? 0,
    waiting: view.job?.waiting ?? 0,
    error: error ?? (view.job?.state === "error" ? (view.job.error ?? "The test could not be completed") : null),
    stop,
    restart,
    readNow,
    readingNow: readingNow && (view.job?.waiting ?? 0) > 0,
  };
}
