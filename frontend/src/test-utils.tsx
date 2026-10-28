import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, waitFor, within } from "@testing-library/react";
import type { ReactElement } from "react";
import { expect, vi } from "vitest";
import { PayModeProvider } from "./components/PayMode";
import { RecoveryProvider } from "./components/Recovery";
import { ToastProvider } from "./components/Toasts";
import { UndoProvider } from "./components/UndoConfirm";

export type Call = {
  method: string;
  url: string;
  headers: Record<string, string>;
  credentials: RequestCredentials | undefined;
  body: unknown;
};

/** ``html``: answer that text as ``text/html`` instead of ``body`` as JSON. */
type Reply = { status?: number; body?: unknown; html?: string };
type Handler = Reply | ((call: Call) => Reply | Promise<Reply>);

/** The jobs a rule test starts on the server (``POST /api/rules/replay/jobs``) and their
 * answers to polling: ``result`` is what a finished test found (or a function of the
 * request that started the job, to answer differently for each rule). Spread it into
 * ``mockFetch``: ``...replayJob(result)``. Each start gets the next job id (job-1,
 * job-2, ...). ``job`` sets the state and counts the server reports. */
export function replayJob(
  result: unknown | ((start: Call) => unknown),
  job: { state?: string; looked_at?: number; total?: number; waiting?: number; error?: string | null } = {},
): Record<string, Handler> {
  const starts: Call[] = [];
  const body = (n: number, withResult: boolean) => {
    const start = starts[n - 1];
    const found = typeof result === "function" ? (result as (c: Call) => unknown)(start) : result;
    const counts = found as { total?: number } | null;
    return {
      job_id: `job-${n}`,
      sheet: "sheet",
      state: "done",
      version: 1,
      looked_at: counts?.total ?? 0,
      total: counts?.total ?? 0,
      waiting: 0,
      elapsed_s: 0.1,
      error: null,
      ...job,
      result: withResult ? found : null,
    };
  };
  const routes: Record<string, Handler> = {
    "POST /api/rules/replay/jobs": (call) => {
      starts.push(call);
      return { body: body(starts.length, false) };
    },
  };
  for (let n = 1; n <= 12; n++) {
    const url = `/api/rules/replay/jobs/job-${n}`;
    routes[`GET ${url}`] = (call) => ({ body: body(n, !call.url.includes("since=1")) });
    routes[`POST ${url}/stop`] = () => ({ body: body(n, true) });
    routes[`DELETE ${url}`] = () => ({ body: body(n, false) });
  }
  return routes;
}

/** Replace global fetch with a router over "METHOD /path" keys; returns the recorded calls. */
export function mockFetch(routes: Record<string, Handler>): Call[] {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
      const url = String(input);
      const method = (init.method ?? "GET").toUpperCase();
      const call: Call = {
        method,
        url,
        headers: { ...((init.headers as Record<string, string>) ?? {}) },
        credentials: init.credentials,
        body: typeof init.body === "string" ? JSON.parse(init.body) : init.body,
      };
      calls.push(call);
      const path = url.split("?")[0];
      const handler = routes[`${method} ${path}`];
      if (handler === undefined) {
        return new Response(JSON.stringify({ error: `no mock for ${method} ${path}` }), {
          status: 404,
          headers: { "Content-Type": "application/json" },
        });
      }
      const reply = typeof handler === "function" ? await handler(call) : handler;
      if (reply.status === 204) return new Response(null, { status: 204 });
      if (reply.html !== undefined)
        return new Response(reply.html, { status: reply.status ?? 200, headers: { "Content-Type": "text/html" } });
      return new Response(JSON.stringify(reply.body), {
        status: reply.status ?? 200,
        headers: { "Content-Type": "application/json" },
      });
    }),
  );
  return calls;
}

/** ``client``: the query client, to change cached data from a test (the AI status). */
export function renderWithProviders(ui: ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const result = render(
    <QueryClientProvider client={client}>
      <ToastProvider>
        <UndoProvider>
          <RecoveryProvider>
            <PayModeProvider>{ui}</PayModeProvider>
          </RecoveryProvider>
        </UndoProvider>
      </ToastProvider>
    </QueryClientProvider>,
  );
  return { ...result, client };
}

/** A promise resolved from the test: hold a mocked response until ``resolve`` is called. */
export function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}

/** A DataTransfer good enough for jsdom: data by type, ``types`` kept in step. Pass
 * ``{ protectedMode: true }`` to model a real browser during dragenter/dragover, where
 * the types are visible but ``getData`` returns "". */
export function dataTransfer(options: { protectedMode?: boolean } = {}) {
  const data: Record<string, string> = {};
  const dt = {
    data,
    protectedMode: options.protectedMode ?? false,
    get types() {
      return Object.keys(data);
    },
    setData: (type: string, value: string) => {
      data[type] = value;
    },
    getData: (type: string) => (dt.protectedMode ? "" : (data[type] ?? "")),
    setDragImage: (_image?: Element, _x?: number, _y?: number) => {},
    effectAllowed: "all",
    dropEffect: "none",
  };
  return dt;
}

/** The undo confirm's Undo button, once the server's undo preview has armed it. */
export async function undoButton(dialog: HTMLElement): Promise<HTMLElement> {
  const button = within(dialog).getByRole("button", { name: "Undo" });
  await waitFor(() => expect(button).toBeEnabled());
  return button;
}

/** ``POST /api/quarantine`` for these files (drive id → path): the dry run (``dry``)
 * and the apply (``q1``) each move them into ``##. To Delete``, keeping the path. */
export function quarantineRoute(files: Record<string, string>) {
  return (call: Call) => {
    const { drive_ids, dry_run } = call.body as { drive_ids: string[]; dry_run: boolean };
    const done = drive_ids.map((id) => ({
      kind: "quarantine",
      src: files[id],
      dst: `##. To Delete/${files[id]}`,
      drive_id: id,
      note: null,
    }));
    return { body: { batch_id: dry_run ? "dry" : "q1", dry_run, done, failed: null, error: null, index_error: null } };
  };
}

/** The server's refusal of a batch holding a file marked Important. */
export const IMPORTANT_REFUSED = (path: string) => ({
  status: 400,
  body: { error: `This file is marked Important; unmark it first: ${path}` },
});
