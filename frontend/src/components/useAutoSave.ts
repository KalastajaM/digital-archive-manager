/** Save-on-commit for one edited value (a field, the title, a note, a checkbox).
 *
 * The input shows the user's draft while there is one, else the server's value. At most
 * one request is in flight per value: a commit made meanwhile only replaces the queued
 * value (the latest wins), which is sent when the request settles unless the server
 * now stores exactly that. So the server always ends with the newest committed value,
 * never an older one that happened to arrive last. A response never replaces text typed
 * after it was sent, and "Saved" shows only while the draft is what was stored. On an
 * error the draft stays, so the user's text is never lost. */
import { useEffect, useRef, useState } from "react";
import { errorText } from "../api/client";

export type SaveStatus = { kind: "saving" } | { kind: "saved" } | { kind: "error"; text: string } | null;

type Box<T> = { value: T };

export function useAutoSave<T>(server: T, save: (value: T) => Promise<T>) {
  const [draft, setDraftState] = useState<Box<T> | null>(null);
  const [status, setStatus] = useState<SaveStatus>(null);
  const draftRef = useRef<Box<T> | null>(null);
  const serverRef = useRef(server);
  serverRef.current = server;
  const saveRef = useRef(save);
  saveRef.current = save;
  const sending = useRef<Box<T> | null>(null); // the value of the request in flight
  const queued = useRef<Box<T> | null>(null); // the latest value committed meanwhile
  const stored = useRef<Box<T> | null>(null); // what the last successful save stored
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const setDraft = (box: Box<T> | null) => {
    draftRef.current = box;
    setDraftState(box);
  };
  const shown = draft ? draft.value : server;

  // The server's value changed to something else than we stored: forget what we stored.
  useEffect(() => {
    if (stored.current && !Object.is(server, stored.current.value)) stored.current = null;
  }, [server]);

  // Once the server has caught up with the draft, show the server's value again.
  useEffect(() => {
    if (draft && Object.is(draft.value, server) && sending.current === null) setDraft(null);
  }, [draft, server]);

  const change = (value: T) => {
    setDraft({ value });
    setStatus((s) => (s?.kind === "saved" ? null : s)); // the new text is not saved yet
  };

  const send = async (value: T) => {
    sending.current = { value };
    if (mounted.current) setStatus({ kind: "saving" });
    let result: Box<T> | null = null;
    let failure: unknown = null;
    try {
      result = { value: await saveRef.current(value) };
      stored.current = result;
    } catch (e) {
      failure = e;
    }
    sending.current = null;
    const next = queued.current;
    queued.current = null;
    // Send what was committed meanwhile, unless the server now has exactly that.
    if (next && !Object.is(next.value, value) && !(result && Object.is(next.value, result.value))) {
      await send(next.value);
      return;
    }
    if (!mounted.current) return;
    if (failure !== null) {
      setStatus({ kind: "error", text: errorText(failure) });
      return;
    }
    const current = draftRef.current;
    if (current === null || Object.is(current.value, value) || Object.is(current.value, result!.value)) {
      // The stored form ("90" → "90,00") replaces the draft only if nothing was typed since.
      setDraft(result);
      setStatus({ kind: "saved" });
    } else {
      setStatus(null); // newer text is not saved yet
    }
  };

  const commit = (value: T = shown): Promise<void> => {
    if (sending.current !== null) {
      // Committing the value in flight again cancels whatever was queued after it.
      queued.current = Object.is(value, sending.current.value) ? null : { value };
      return Promise.resolve();
    }
    // Nothing to send: what the server has, or what was just stored (blur after Enter,
    // before the reloaded item arrives).
    const isServer = Object.is(value, serverRef.current);
    if (isServer || (stored.current && Object.is(value, stored.current.value))) {
      if (isServer) setDraft(null);
      if (status?.kind === "error") setStatus(null);
      return Promise.resolve();
    }
    return send(value);
  };

  return { shown, change, commit, status };
}
